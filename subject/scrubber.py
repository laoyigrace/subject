# Copyright 2010 OpenStack Foundation
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

import calendar
import time

import eventlet
from glance_store import exceptions as store_exceptions
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import encodeutils
import six

from subject.common import crypt
from subject.common import exception
from subject import context
import subject.db as db_api
from subject.i18n import _, _LE, _LI, _LW
import subject.registry.client.v1.api as registry

LOG = logging.getLogger(__name__)

scrubber_opts = [
    cfg.IntOpt('scrub_time', default=0, min=0,
               help=_("""
The amount of time, in seconds, to delay subject scrubbing.

When delayed delete is turned on, an subject is put into ``pending_delete``
state upon deletion until the scrubber deletes its subject data. Typically, soon
after the subject is put into ``pending_delete`` state, it is available for
scrubbing. However, scrubbing can be delayed until a later point using this
configuration option. This option denotes the time period an subject spends in
``pending_delete`` state before it is available for scrubbing.

It is important to realize that this has storage implications. The larger the
``scrub_time``, the longer the time to reclaim backend storage from deleted
subjects.

Possible values:
    * Any non-negative integer

Related options:
    * ``delayed_delete``

""")),
    cfg.IntOpt('scrub_pool_size', default=1, min=1,
               help=_("""
The size of thread pool to be used for scrubbing subjects.

When there are a large number of subjects to scrub, it is beneficial to scrub
subjects in parallel so that the scrub queue stays in control and the backend
storage is reclaimed in a timely fashion. This configuration option denotes
the maximum number of subjects to be scrubbed in parallel. The default value is
one, which signifies serial scrubbing. Any value above one indicates parallel
scrubbing.

Possible values:
    * Any non-zero positive integer

Related options:
    * ``delayed_delete``

""")),
    cfg.BoolOpt('delayed_delete', default=False,
                help=_("""
Turn on/off delayed delete.

Typically when an subject is deleted, the ``subject-api`` service puts the subject
into ``deleted`` state and deletes its data at the same time. Delayed delete
is a feature in Glance that delays the actual deletion of subject data until a
later point in time (as determined by the configuration option ``scrub_time``).
When delayed delete is turned on, the ``subject-api`` service puts the subject
into ``pending_delete`` state upon deletion and leaves the subject data in the
storage backend for the subject scrubber to delete at a later time. The subject
scrubber will move the subject into ``deleted`` state upon successful deletion
of subject data.

NOTE: When delayed delete is turned on, subject scrubber MUST be running as a
periodic task to prevent the backend storage from filling up with undesired
usage.

Possible values:
    * True
    * False

Related options:
    * ``scrub_time``
    * ``wakeup_time``
    * ``scrub_pool_size``

""")),

    # Note: Though the conf option admin_role is used by other Glance
    # service and their usage differs requiring us to have a differing
    # help text here, oslo.config generator treats them as the same
    # config option and would throw a DuplicateError exception in case
    # of differing help texts. Hence we have the same help text for
    # admin_role here and in context.py.

    cfg.StrOpt('admin_role', default='admin',
               help=_("""
Role used to identify an authenticated user as administrator.

Provide a string value representing a Keystone role to identify an
administrative user. Users with this role will be granted
administrative privileges. The default value for this option is
'admin'.

Possible values:
    * A string value which is a valid Keystone role

Related options:
    * None

""")),
    cfg.BoolOpt('send_identity_headers',
                default=False,
                help=_("""
Send headers received from identity when making requests to
registry.

Typically, Glance registry can be deployed in multiple flavors,
which may or may not include authentication. For example,
``trusted-auth`` is a flavor that does not require the registry
service to authenticate the requests it receives. However, the
registry service may still need a user context to be populated to
serve the requests. This can be achieved by the caller
(the Glance API usually) passing through the headers it received
from authenticating with identity for the same request. The typical
headers sent are ``X-User-Id``, ``X-Tenant-Id``, ``X-Roles``,
``X-Identity-Status`` and ``X-Service-Catalog``.

Provide a boolean value to determine whether to send the identity
headers to provide tenant and user information along with the
requests to registry service. By default, this option is set to
``False``, which means that user and tenant information is not
available readily. It must be obtained by authenticating. Hence, if
this is set to ``False``, ``flavor`` must be set to value that
either includes authentication or authenticated user context.

Possible values:
    * True
    * False

Related options:
    * flavor

""")),
]

scrubber_cmd_opts = [
    cfg.IntOpt('wakeup_time', default=300, min=0,
               help=_("""
Time interval, in seconds, between scrubber runs in daemon mode.

Scrubber can be run either as a cron job or daemon. When run as a daemon, this
configuration time specifies the time period between two runs. When the
scrubber wakes up, it fetches and scrubs all ``pending_delete`` subjects that
are available for scrubbing after taking ``scrub_time`` into consideration.

If the wakeup time is set to a large number, there may be a large number of
subjects to be scrubbed for each run. Also, this impacts how quickly the backend
storage is reclaimed.

Possible values:
    * Any non-negative integer

Related options:
    * ``daemon``
    * ``delayed_delete``

"""))
]

scrubber_cmd_cli_opts = [
    cfg.BoolOpt('daemon',
                short='D',
                default=False,
                help=_("""
Run scrubber as a daemon.

This boolean configuration option indicates whether scrubber should
run as a long-running process that wakes up at regular intervals to
scrub subjects. The wake up interval can be specified using the
configuration option ``wakeup_time``.

If this configuration option is set to ``False``, which is the
default value, scrubber runs once to scrub subjects and exits. In this
case, if the operator wishes to implement continuous scrubbing of
subjects, scrubber needs to be scheduled as a cron job.

Possible values:
    * True
    * False

Related options:
    * ``wakeup_time``

"""))
]

CONF = cfg.CONF
CONF.register_opts(scrubber_opts)
CONF.import_opt('metadata_encryption_key', 'subject.common.config')


class ScrubDBQueue(object):
    """Database-based subject scrub queue class."""
    def __init__(self):
        self.scrub_time = CONF.scrub_time
        self.metadata_encryption_key = CONF.metadata_encryption_key
        registry.configure_registry_client()
        registry.configure_registry_admin_creds()
        admin_user = CONF.admin_user
        admin_tenant = CONF.admin_tenant_name

        if CONF.send_identity_headers:
            # When registry is operating in trusted-auth mode
            roles = [CONF.admin_role]
            self.admin_context = context.RequestContext(user=admin_user,
                                                        tenant=admin_tenant,
                                                        auth_token=None,
                                                        roles=roles)
            self.registry = registry.get_registry_client(self.admin_context)
        else:
            ctxt = context.RequestContext()
            self.registry = registry.get_registry_client(ctxt)
            admin_token = self.registry.auth_token
            self.admin_context = context.RequestContext(user=admin_user,
                                                        tenant=admin_tenant,
                                                        auth_token=admin_token)

    def add_location(self, subject_id, location):
        """Adding subject location to scrub queue.

        :param subject_id: The opaque subject identifier
        :param location: The opaque subject location

        :returns: A boolean value to indicate success or not
        """
        loc_id = location.get('id')
        if loc_id:
            db_api.get_api().subject_location_delete(self.admin_context,
                                                   subject_id, loc_id,
                                                   'pending_delete')
            return True
        else:
            return False

    def _get_subjects_page(self, marker):
        filters = {'deleted': True,
                   'is_public': 'none',
                   'status': 'pending_delete'}

        if marker:
            return self.registry.get_subjects_detailed(filters=filters,
                                                     marker=marker)
        else:
            return self.registry.get_subjects_detailed(filters=filters)

    def _get_all_subjects(self):
        """Generator to fetch all appropriate subjects, paging as needed."""

        marker = None
        while True:
            subjects = self._get_subjects_page(marker)
            if len(subjects) == 0:
                break
            marker = subjects[-1]['id']

            for subject in subjects:
                yield subject

    def get_all_locations(self):
        """Returns a list of subject id and location tuple from scrub queue.

        :returns: a list of subject id, location id and uri tuple from
            scrub queue

        """
        ret = []

        for subject in self._get_all_subjects():
            deleted_at = subject.get('deleted_at')
            if not deleted_at:
                continue

            # NOTE: Strip off microseconds which may occur after the last '.,'
            # Example: 2012-07-07T19:14:34.974216
            date_str = deleted_at.rsplit('.', 1)[0].rsplit(',', 1)[0]
            delete_time = calendar.timegm(time.strptime(date_str,
                                                        "%Y-%m-%dT%H:%M:%S"))

            if delete_time + self.scrub_time > time.time():
                continue

            for loc in subject['location_data']:
                if loc['status'] != 'pending_delete':
                    continue

                if self.metadata_encryption_key:
                    uri = crypt.urlsafe_encrypt(self.metadata_encryption_key,
                                                loc['url'], 64)
                else:
                    uri = loc['url']

                ret.append((subject['id'], loc['id'], uri))
        return ret

    def has_subject(self, subject_id):
        """Returns whether the queue contains an subject or not.

        :param subject_id: The opaque subject identifier

        :returns: a boolean value to inform including or not
        """
        try:
            subject = self.registry.get_subject(subject_id)
            return subject['status'] == 'pending_delete'
        except exception.NotFound:
            return False


_db_queue = None


def get_scrub_queue():
    global _db_queue
    if not _db_queue:
        _db_queue = ScrubDBQueue()
    return _db_queue


class Daemon(object):
    def __init__(self, wakeup_time=300, threads=100):
        LOG.info(_LI("Starting Daemon: wakeup_time=%(wakeup_time)s "
                     "threads=%(threads)s"),
                 {'wakeup_time': wakeup_time, 'threads': threads})
        self.wakeup_time = wakeup_time
        self.event = eventlet.event.Event()
        # This pool is used for periodic instantiation of scrubber
        self.daemon_pool = eventlet.greenpool.GreenPool(threads)

    def start(self, application):
        self._run(application)

    def wait(self):
        try:
            self.event.wait()
        except KeyboardInterrupt:
            msg = _LI("Daemon Shutdown on KeyboardInterrupt")
            LOG.info(msg)

    def _run(self, application):
        LOG.debug("Running application")
        self.daemon_pool.spawn_n(application.run, self.event)
        eventlet.spawn_after(self.wakeup_time, self._run, application)
        LOG.debug("Next run scheduled in %s seconds", self.wakeup_time)


class Scrubber(object):
    def __init__(self, store_api):
        LOG.info(_LI("Initializing scrubber with configuration: %s"),
                 six.text_type({'registry_host': CONF.registry_host,
                                'registry_port': CONF.registry_port}))

        self.store_api = store_api

        registry.configure_registry_client()
        registry.configure_registry_admin_creds()

        # Here we create a request context with credentials to support
        # delayed delete when using multi-tenant backend storage
        admin_user = CONF.admin_user
        admin_tenant = CONF.admin_tenant_name

        if CONF.send_identity_headers:
            # When registry is operating in trusted-auth mode
            roles = [CONF.admin_role]
            self.admin_context = context.RequestContext(user=admin_user,
                                                        tenant=admin_tenant,
                                                        auth_token=None,
                                                        roles=roles)
            self.registry = registry.get_registry_client(self.admin_context)
        else:
            ctxt = context.RequestContext()
            self.registry = registry.get_registry_client(ctxt)
            auth_token = self.registry.auth_token
            self.admin_context = context.RequestContext(user=admin_user,
                                                        tenant=admin_tenant,
                                                        auth_token=auth_token)

        self.db_queue = get_scrub_queue()
        self.pool = eventlet.greenpool.GreenPool(CONF.scrub_pool_size)

    def _get_delete_jobs(self):
        try:
            records = self.db_queue.get_all_locations()
        except Exception as err:
            LOG.error(_LE("Can not get scrub jobs from queue: %s") %
                      encodeutils.exception_to_unicode(err))
            return {}

        delete_jobs = {}
        for subject_id, loc_id, loc_uri in records:
            if subject_id not in delete_jobs:
                delete_jobs[subject_id] = []
            delete_jobs[subject_id].append((subject_id, loc_id, loc_uri))
        return delete_jobs

    def run(self, event=None):
        delete_jobs = self._get_delete_jobs()

        if delete_jobs:
            list(self.pool.starmap(self._scrub_subject, delete_jobs.items()))

    def _scrub_subject(self, subject_id, delete_jobs):
        if len(delete_jobs) == 0:
            return

        LOG.info(_LI("Scrubbing subject %(id)s from %(count)d locations."),
                 {'id': subject_id, 'count': len(delete_jobs)})

        success = True
        for img_id, loc_id, uri in delete_jobs:
            try:
                self._delete_subject_location_from_backend(img_id, loc_id, uri)
            except Exception:
                success = False

        if success:
            subject = self.registry.get_subject(subject_id)
            if subject['status'] == 'pending_delete':
                self.registry.update_subject(subject_id, {'status': 'deleted'})
            LOG.info(_LI("Subject %s has been scrubbed successfully"), subject_id)
        else:
            LOG.warn(_LW("One or more subject locations couldn't be scrubbed "
                         "from backend. Leaving subject '%s' in 'pending_delete'"
                         " status") % subject_id)

    def _delete_subject_location_from_backend(self, subject_id, loc_id, uri):
        if CONF.metadata_encryption_key:
            uri = crypt.urlsafe_decrypt(CONF.metadata_encryption_key, uri)
        try:
            LOG.debug("Scrubbing subject %s from a location.", subject_id)
            try:
                self.store_api.delete_from_backend(uri, self.admin_context)
            except store_exceptions.NotFound:
                LOG.info(_LI("Subject location for subject '%s' not found in "
                             "backend; Marking subject location deleted in "
                             "db."), subject_id)

            if loc_id != '-':
                db_api.get_api().subject_location_delete(self.admin_context,
                                                       subject_id,
                                                       int(loc_id),
                                                       'deleted')
            LOG.info(_LI("Subject %s is scrubbed from a location."), subject_id)
        except Exception as e:
            LOG.error(_LE("Unable to scrub subject %(id)s from a location. "
                          "Reason: %(exc)s ") %
                      {'id': subject_id,
                       'exc': encodeutils.exception_to_unicode(e)})
            raise
