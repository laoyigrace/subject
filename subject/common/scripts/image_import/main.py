# Copyright 2014 OpenStack Foundation
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

__all__ = [
    'run',
]

from oslo_concurrency import lockutils
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils
import six

from subject.api.v1 import subjects as v2_api
from subject.common import exception
from subject.common.scripts import utils as script_utils
from subject.common import store_utils
from subject.i18n import _, _LE, _LI, _LW

LOG = logging.getLogger(__name__)


def run(t_id, context, task_repo, subject_repo, subject_factory):
    LOG.info(_LI('Task %(task_id)s beginning import '
                 'execution.'), {'task_id': t_id})
    _execute(t_id, task_repo, subject_repo, subject_factory)


# NOTE(nikhil): This lock prevents more than N number of threads to be spawn
# simultaneously. The number N represents the number of threads in the
# executor pool. The value is set to 10 in the eventlet executor.
@lockutils.synchronized("subject_import")
def _execute(t_id, task_repo, subject_repo, subject_factory):
    task = script_utils.get_task(task_repo, t_id)

    if task is None:
        # NOTE: This happens if task is not found in the database. In
        # such cases, there is no way to update the task status so,
        # it's ignored here.
        return

    try:
        task_input = script_utils.unpack_task_input(task)

        uri = script_utils.validate_location_uri(task_input.get('import_from'))
        subject_id = import_subject(subject_repo, subject_factory, task_input, t_id,
                                uri)

        task.succeed({'subject_id': subject_id})
    except Exception as e:
        # Note: The message string contains Error in it to indicate
        # in the task.message that it's a error message for the user.

        # TODO(nikhil): need to bring back save_and_reraise_exception when
        # necessary
        err_msg = ("Error: " + six.text_type(type(e)) + ': ' +
                   encodeutils.exception_to_unicode(e))
        log_msg = _LE(err_msg + ("Task ID %s" % task.task_id))  # noqa
        LOG.exception(log_msg)

        task.fail(_LE(err_msg))  # noqa
    finally:
        task_repo.save(task)


def import_subject(subject_repo, subject_factory, task_input, task_id, uri):
    original_subject = create_subject(subject_repo, subject_factory,
                                  task_input.get('subject_properties'), task_id)
    # NOTE: set subject status to saving just before setting data
    original_subject.status = 'saving'
    subject_repo.save(original_subject)
    subject_id = original_subject.subject_id

    # NOTE: Retrieving subject from the database because the Subject object
    # returned from create_subject method does not have appropriate factories
    # wrapped around it.
    new_subject = subject_repo.get(subject_id)
    set_subject_data(new_subject, uri, task_id)

    try:
        # NOTE: Check if the Subject is not deleted after setting the data
        # before saving the active subject. Here if subject status is
        # saving, then new_subject is saved as it contains updated location,
        # size, virtual_size and checksum information and the status of
        # new_subject is already set to active in set_subject_data() call.
        subject = subject_repo.get(subject_id)
        if subject.status == 'saving':
            subject_repo.save(new_subject)
            return subject_id
        else:
            msg = _("The Subject %(subject_id)s object being created by this task "
                    "%(task_id)s, is no longer in valid status for further "
                    "processing.") % {"subject_id": subject_id,
                                      "task_id": task_id}
            raise exception.Conflict(msg)
    except (exception.Conflict, exception.NotFound,
            exception.NotAuthenticated):
        with excutils.save_and_reraise_exception():
            if new_subject.locations:
                for location in new_subject.locations:
                    store_utils.delete_subject_location_from_backend(
                        new_subject.context,
                        subject_id,
                        location)


def create_subject(subject_repo, subject_factory, subject_properties, task_id):
    _base_properties = []
    for k, v in v2_api.get_base_properties().items():
        _base_properties.append(k)

    properties = {}
    # NOTE: get the base properties
    for key in _base_properties:
        try:
            properties[key] = subject_properties.pop(key)
        except KeyError:
            LOG.debug("Task ID %(task_id)s: Ignoring property %(k)s for "
                      "setting base properties while creating "
                      "Subject.", {'task_id': task_id, 'k': key})

    # NOTE: get the rest of the properties and pass them as
    # extra_properties for Subject to be created with them.
    properties['extra_properties'] = subject_properties
    script_utils.set_base_subject_properties(properties=properties)

    subject = subject_factory.new_subject(**properties)
    subject_repo.add(subject)
    return subject


def set_subject_data(subject, uri, task_id):
    data_iter = None
    try:
        LOG.info(_LI("Task %(task_id)s: Got subject data uri %(data_uri)s to be "
                 "imported"), {"data_uri": uri, "task_id": task_id})
        data_iter = script_utils.get_subject_data_iter(uri)
        subject.set_data(data_iter)
    except Exception as e:
        with excutils.save_and_reraise_exception():
            LOG.warn(_LW("Task %(task_id)s failed with exception %(error)s") %
                     {"error": encodeutils.exception_to_unicode(e),
                      "task_id": task_id})
            LOG.info(_LI("Task %(task_id)s: Could not import subject file"
                         " %(subject_data)s"), {"subject_data": uri,
                                              "task_id": task_id})
    finally:
        if hasattr(data_iter, 'close'):
            data_iter.close()
