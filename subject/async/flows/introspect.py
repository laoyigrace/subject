# Copyright 2015 Red Hat, Inc.
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

import json

from oslo_concurrency import processutils as putils
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils
from taskflow.patterns import linear_flow as lf

from subject.async import utils
from subject.i18n import _LE


LOG = logging.getLogger(__name__)


class _Introspect(utils.OptionalTask):
    """Taskflow to pull the embedded metadata out of subject file"""

    def __init__(self, task_id, task_type, subject_repo):
        self.task_id = task_id
        self.task_type = task_type
        self.subject_repo = subject_repo
        super(_Introspect, self).__init__(
            name='%s-Introspect-%s' % (task_type, task_id))

    def execute(self, subject_id, file_path):
        """Does the actual introspection

        :param subject_id: Glance subject ID
        :param file_path: Path to the file being introspected
        """

        try:
            stdout, stderr = putils.trycmd('qemu-img', 'info',
                                           '--output=json', file_path,
                                           prlimit=utils.QEMU_IMG_PROC_LIMITS,
                                           log_errors=putils.LOG_ALL_ERRORS)
        except OSError as exc:
            # NOTE(flaper87): errno == 2 means the executable file
            # was not found. For now, log an error and move forward
            # until we have a better way to enable/disable optional
            # tasks.
            if exc.errno != 2:
                with excutils.save_and_reraise_exception():
                    exc_message = encodeutils.exception_to_unicode(exc)
                    msg = _LE('Failed to execute introspection '
                              '%(task_id)s: %(exc)s')
                    LOG.error(msg, {'task_id': self.task_id,
                                    'exc': exc_message})
            return

        if stderr:
            raise RuntimeError(stderr)

        metadata = json.loads(stdout)
        new_subject = self.subject_repo.get(subject_id)
        new_subject.virtual_size = metadata.get('virtual-size', 0)
        new_subject.disk_format = metadata.get('format')
        self.subject_repo.save(new_subject)
        LOG.debug("%(task_id)s: Introspection successful: %(file)s",
                  {'task_id': self.task_id, 'file': file_path})
        return new_subject


def get_flow(**kwargs):
    """Return task flow for introspecting subjects to obtain metadata about the
    subject.

    :param task_id: Task ID
    :param task_type: Type of the task.
    :param subject_repo: Subject repository used.
    """
    task_id = kwargs.get('task_id')
    task_type = kwargs.get('task_type')
    subject_repo = kwargs.get('subject_repo')

    LOG.debug("Flow: %(task_type)s with ID %(id)s on %(repo)s",
              {'task_type': task_type, 'id': task_id, 'repo': subject_repo})

    return lf.Flow(task_type).add(
        _Introspect(task_id, task_type, subject_repo),
    )
