# Copyright 2012 OpenStack Foundation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import re

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from subject.common import exception
from subject.common import wsgi
from subject.i18n import _, _LE, _LW

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

_CACHED_THREAD_POOL = {}


def size_checked_iter(response, subject_meta, expected_size, subject_iter,
                      notifier):
    subject_id = subject_meta['id']
    bytes_written = 0

    def notify_subject_sent_hook(env):
        subject_send_notification(bytes_written, expected_size,
                                subject_meta, response.request, notifier)

    # Add hook to process after response is fully sent
    if 'eventlet.posthooks' in response.request.environ:
        response.request.environ['eventlet.posthooks'].append(
            (notify_subject_sent_hook, (), {}))

    try:
        for chunk in subject_iter:
            yield chunk
            bytes_written += len(chunk)
    except Exception as err:
        with excutils.save_and_reraise_exception():
            msg = (_LE("An error occurred reading from backend storage for "
                       "subject %(subject_id)s: %(err)s") % {'subject_id': subject_id,
                                                         'err': err})
            LOG.error(msg)

    if expected_size != bytes_written:
        msg = (_LE("Backend storage for subject %(subject_id)s "
                   "disconnected after writing only %(bytes_written)d "
                   "bytes") % {'subject_id': subject_id,
                               'bytes_written': bytes_written})
        LOG.error(msg)
        raise exception.GlanceException(_("Corrupt subject download for "
                                          "subject %(subject_id)s") %
                                        {'subject_id': subject_id})


def subject_send_notification(bytes_written, expected_size, subject_meta, request,
                            notifier):
    """Send an subject.send message to the notifier."""
    try:
        context = request.context
        payload = {
            'bytes_sent': bytes_written,
            'subject_id': subject_meta['id'],
            'owner_id': subject_meta['owner'],
            'receiver_tenant_id': context.tenant,
            'receiver_user_id': context.user,
            'destination_ip': request.remote_addr,
        }
        if bytes_written != expected_size:
            notify = notifier.error
        else:
            notify = notifier.info

        notify('subject.send', payload)

    except Exception as err:
        msg = (_LE("An error occurred during subject.send"
                   " notification: %(err)s") % {'err': err})
        LOG.error(msg)


def get_remaining_quota(context, db_api, subject_id=None):
    """Method called to see if the user is allowed to store an subject.

    Checks if it is allowed based on the given size in subject based on their
    quota and current usage.

    :param context:
    :param db_api:  The db_api in use for this configuration
    :param subject_id: The subject that will be replaced with this new data size
    :returns: The number of bytes the user has remaining under their quota.
             None means infinity
    """

    # NOTE(jbresnah) in the future this value will come from a call to
    # keystone.
    users_quota = CONF.user_storage_quota

    # set quota must have a number optionally followed by B, KB, MB,
    # GB or TB without any spaces in between
    pattern = re.compile('^(\d+)((K|M|G|T)?B)?$')
    match = pattern.match(users_quota)

    if not match:
        LOG.error(_LE("Invalid value for option user_storage_quota: "
                      "%(users_quota)s")
                  % {'users_quota': users_quota})
        raise exception.InvalidOptionValue(option='user_storage_quota',
                                           value=users_quota)

    quota_value, quota_unit = (match.groups())[0:2]
    # fall back to Bytes if user specified anything other than
    # permitted values
    quota_unit = quota_unit or "B"
    factor = getattr(units, quota_unit.replace('B', 'i'), 1)
    users_quota = int(quota_value) * factor

    if users_quota <= 0:
        return

    usage = db_api.user_get_storage_usage(context,
                                          context.owner,
                                          subject_id=subject_id)
    return users_quota - usage


def check_quota(context, subject_size, db_api, subject_id=None):
    """Method called to see if the user is allowed to store an subject.

    Checks if it is allowed based on the given size in subject based on their
    quota and current usage.

    :param context:
    :param subject_size:  The size of the subject we hope to store
    :param db_api:  The db_api in use for this configuration
    :param subject_id: The subject that will be replaced with this new data size
    :returns:
    """

    remaining = get_remaining_quota(context, db_api, subject_id=subject_id)

    if remaining is None:
        return

    user = getattr(context, 'user', '<unknown>')

    if subject_size is None:
        # NOTE(jbresnah) When the subject size is None it means that it is
        # not known.  In this case the only time we will raise an
        # exception is when there is no room left at all, thus we know
        # it will not fit
        if remaining <= 0:
            LOG.warn(_LW("User %(user)s attempted to upload an subject of"
                         " unknown size that will exceed the quota."
                         " %(remaining)d bytes remaining.")
                     % {'user': user, 'remaining': remaining})
            raise exception.StorageQuotaFull(subject_size=subject_size,
                                             remaining=remaining)
        return

    if subject_size > remaining:
        LOG.warn(_LW("User %(user)s attempted to upload an subject of size"
                     " %(size)d that will exceed the quota. %(remaining)d"
                     " bytes remaining.")
                 % {'user': user, 'size': subject_size, 'remaining': remaining})
        raise exception.StorageQuotaFull(subject_size=subject_size,
                                         remaining=remaining)

    return remaining


def memoize(lock_name):
    def memoizer_wrapper(func):
        @lockutils.synchronized(lock_name)
        def memoizer(lock_name):
            if lock_name not in _CACHED_THREAD_POOL:
                _CACHED_THREAD_POOL[lock_name] = func()

            return _CACHED_THREAD_POOL[lock_name]

        return memoizer(lock_name)

    return memoizer_wrapper


def get_thread_pool(lock_name, size=1024):
    """Initializes eventlet thread pool.

    If thread pool is present in cache, then returns it from cache
    else create new pool, stores it in cache and return newly created
    pool.

    @param lock_name:  Name of the lock.
    @param size: Size of eventlet pool.

    @return: eventlet pool
    """
    @memoize(lock_name)
    def _get_thread_pool():
        return wsgi.get_asynchronous_eventlet_pool(size=size)

    return _get_thread_pool
