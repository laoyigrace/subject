# Copyright 2015 OpenStack Foundation
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
import os

import subject_store as store_api
from subject_store import backend
from oslo_concurrency import processutils as putils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils
import six
from stevedore import named
from taskflow.patterns import linear_flow as lf
from taskflow import retry
from taskflow import task
from taskflow.types import failure

from subject.async import utils
from subject.common import exception
from subject.common.scripts.subject_import import main as subject_import
from subject.common.scripts import utils as script_utils
from subject.i18n import _, _LE, _LI


LOG = logging.getLogger(__name__)


CONF = cfg.CONF


class _CreateSubject(task.Task):

    default_provides = 'subject_id'

    def __init__(self, task_id, task_type, task_repo, subject_repo,
                 subject_factory):
        self.task_id = task_id
        self.task_type = task_type
        self.task_repo = task_repo
        self.subject_repo = subject_repo
        self.subject_factory = subject_factory
        super(_CreateSubject, self).__init__(
            name='%s-CreateSubject-%s' % (task_type, task_id))

    def execute(self):
        task = script_utils.get_task(self.task_repo, self.task_id)
        if task is None:
            return
        task_input = script_utils.unpack_task_input(task)
        subject = subject_import.create_subject(
            self.subject_repo, self.subject_factory,
            task_input.get('subject_properties'), self.task_id)

        LOG.debug("Task %(task_id)s created subject %(subject_id)s",
                  {'task_id': task.task_id, 'subject_id': subject.subject_id})
        return subject.subject_id

    def revert(self, *args, **kwargs):
        # TODO(flaper87): Define the revert rules for subjects on failures.
        # Deleting the subject may not be what we want since users could upload
        # the subject data in a separate step. However, it really depends on
        # when the failure happened. I guess we should check if data has been
        # written, although at that point failures are (should be) unexpected,
        # at least subject-workflow wise.
        pass


class _ImportToFS(task.Task):

    default_provides = 'file_path'

    def __init__(self, task_id, task_type, task_repo, uri):
        self.task_id = task_id
        self.task_type = task_type
        self.task_repo = task_repo
        self.uri = uri
        super(_ImportToFS, self).__init__(
            name='%s-ImportToFS-%s' % (task_type, task_id))

        if CONF.task.work_dir is None:
            msg = (_("%(task_id)s of %(task_type)s not configured "
                     "properly. Missing work dir: %(work_dir)s") %
                   {'task_id': self.task_id,
                    'task_type': self.task_type,
                    'work_dir': CONF.task.work_dir})
            raise exception.BadTaskConfiguration(msg)

        self.store = self._build_store()

    def _build_store(self):
        # NOTE(flaper87): Due to the nice subject_store api (#sarcasm), we're
        # forced to build our own config object, register the required options
        # (and by required I mean *ALL* of them, even the ones we don't want),
        # and create our own store instance by calling a private function.
        # This is certainly unfortunate but it's the best we can do until the
        # subject_store refactor is done. A good thing is that subject_store is
        # under our team's management and it gates on Glance so changes to
        # this API will (should?) break task's tests.
        conf = cfg.ConfigOpts()
        backend.register_opts(conf)
        conf.set_override('filesystem_store_datadir',
                          CONF.task.work_dir,
                          group='subject_store',
                          enforce_type=True)

        # NOTE(flaper87): Do not even try to judge me for this... :(
        # With the subject_store refactor, this code will change, until
        # that happens, we don't have a better option and this is the
        # least worst one, IMHO.
        store = backend._load_store(conf, 'file')

        if store is None:
            msg = (_("%(task_id)s of %(task_type)s not configured "
                     "properly. Could not load the filesystem store") %
                   {'task_id': self.task_id, 'task_type': self.task_type})
            raise exception.BadTaskConfiguration(msg)

        store.configure()
        return store

    def execute(self, subject_id):
        """Create temp file into store and return path to it

        :param subject_id: Glance Subject ID
        """
        # NOTE(flaper87): We've decided to use a separate `work_dir` for
        # this task - and tasks coming after this one - as a way to expect
        # users to configure a local store for pre-import works on the subject
        # to happen.
        #
        # While using any path should be "technically" fine, it's not what
        # we recommend as the best solution. For more details on this, please
        # refer to the comment in the `_ImportToStore.execute` method.
        data = script_utils.get_subject_data_iter(self.uri)

        path = self.store.add(subject_id, data, 0, context=None)[0]

        try:
            # NOTE(flaper87): Consider moving this code to a common
            # place that other tasks can consume as well.
            stdout, stderr = putils.trycmd('qemu-img', 'info',
                                           '--output=json', path,
                                           prlimit=utils.QEMU_IMG_PROC_LIMITS,
                                           log_errors=putils.LOG_ALL_ERRORS)
        except OSError as exc:
            with excutils.save_and_reraise_exception():
                exc_message = encodeutils.exception_to_unicode(exc)
                msg = _LE('Failed to execute security checks on the subject '
                          '%(task_id)s: %(exc)s')
                LOG.error(msg, {'task_id': self.task_id, 'exc': exc_message})

        metadata = json.loads(stdout)

        backing_file = metadata.get('backing-filename')
        if backing_file is not None:
            msg = _("File %(path)s has invalid backing file "
                    "%(bfile)s, aborting.") % {'path': path,
                                               'bfile': backing_file}
            raise RuntimeError(msg)

        return path

    def revert(self, subject_id, result, **kwargs):
        if isinstance(result, failure.Failure):
            LOG.exception(_LE('Task: %(task_id)s failed to import subject '
                              '%(subject_id)s to the filesystem.'),
                          {'task_id': self.task_id, 'subject_id': subject_id})
            return

        if os.path.exists(result.split("file://")[-1]):
            store_api.delete_from_backend(result)


class _DeleteFromFS(task.Task):

    def __init__(self, task_id, task_type):
        self.task_id = task_id
        self.task_type = task_type
        super(_DeleteFromFS, self).__init__(
            name='%s-DeleteFromFS-%s' % (task_type, task_id))

    def execute(self, file_path):
        """Remove file from the backend

        :param file_path: path to the file being deleted
        """
        store_api.delete_from_backend(file_path)


class _ImportToStore(task.Task):

    def __init__(self, task_id, task_type, subject_repo, uri):
        self.task_id = task_id
        self.task_type = task_type
        self.subject_repo = subject_repo
        self.uri = uri
        super(_ImportToStore, self).__init__(
            name='%s-ImportToStore-%s' % (task_type, task_id))

    def execute(self, subject_id, file_path=None):
        """Bringing the introspected subject to back end store

        :param subject_id: Glance Subject ID
        :param file_path: path to the subject file
        """
        # NOTE(flaper87): There are a couple of interesting bits in the
        # interaction between this task and the `_ImportToFS` one. I'll try
        # to cover them in this comment.
        #
        # NOTE(flaper87):
        # `_ImportToFS` downloads the subject to a dedicated `work_dir` which
        # needs to be configured in advance (please refer to the config option
        # docs for more info). The motivation behind this is also explained in
        # the `_ImportToFS.execute` method.
        #
        # Due to the fact that we have an `_ImportToFS` task which downloads
        # the subject data already, we need to be as smart as we can in this task
        # to avoid downloading the data several times and reducing the copy or
        # write times. There are several scenarios where the interaction
        # between this task and `_ImportToFS` could be improved. All these
        # scenarios assume the `_ImportToFS` task has been executed before
        # and/or in a more abstract scenario, that `file_path` is being
        # provided.
        #
        # Scenario 1: FS Store is Remote, introspection enabled,
        # conversion disabled
        #
        # In this scenario, the user would benefit from having the scratch path
        # being the same path as the fs store. Only one write would happen and
        # an extra read will happen in order to introspect the subject. Note that
        # this read is just for the subject headers and not the entire file.
        #
        # Scenario 2: FS Store is remote, introspection enabled,
        # conversion enabled
        #
        # In this scenario, the user would benefit from having a *local* store
        # into which the subject can be converted. This will require downloading
        # the subject locally, converting it and then copying the converted subject
        # to the remote store.
        #
        # Scenario 3: FS Store is local, introspection enabled,
        # conversion disabled
        # Scenario 4: FS Store is local, introspection enabled,
        # conversion enabled
        #
        # In both these scenarios the user shouldn't care if the FS
        # store path and the work dir are the same, therefore probably
        # benefit, about the scratch path and the FS store being the
        # same from a performance perspective. Space wise, regardless
        # of the scenario, the user will have to account for it in
        # advance.
        #
        # Lets get to it and identify the different scenarios in the
        # implementation
        subject = self.subject_repo.get(subject_id)
        subject.status = 'saving'
        self.subject_repo.save(subject)

        # NOTE(flaper87): Let's dance... and fall
        #
        # Unfortunatelly, because of the way our domain layers work and
        # the checks done in the FS store, we can't simply rename the file
        # and set the location. To do that, we'd have to duplicate the logic
        # of every and each of the domain factories (quota, location, etc)
        # and we'd also need to hack the FS store to prevent it from raising
        # a "duplication path" error. I'd rather have this task copying the
        # subject bits one more time than duplicating all that logic.
        #
        # Since I don't think this should be the definitive solution, I'm
        # leaving the code below as a reference for what should happen here
        # once the FS store and domain code will be able to handle this case.
        #
        # if file_path is None:
        #    subject_import.set_subject_data(subject, self.uri, None)
        #    return

        # NOTE(flaper87): Don't assume the subject was stored in the
        # work_dir. Think in the case this path was provided by another task.
        # Also, lets try to neither assume things nor create "logic"
        # dependencies between this task and `_ImportToFS`
        #
        # base_path = os.path.dirname(file_path.split("file://")[-1])

        # NOTE(flaper87): Hopefully just scenarios #3 and #4. I say
        # hopefully because nothing prevents the user to use the same
        # FS store path as a work dir
        #
        # subject_path = os.path.join(base_path, subject_id)
        #
        # if (base_path == CONF.subject_store.filesystem_store_datadir or
        #      base_path in CONF.subject_store.filesystem_store_datadirs):
        #     os.rename(file_path, subject_path)
        #
        # subject_import.set_subject_data(subject, subject_path, None)

        subject_import.set_subject_data(subject, file_path or self.uri, self.task_id)

        # NOTE(flaper87): We need to save the subject again after the locations
        # have been set in the subject.
        self.subject_repo.save(subject)


class _SaveSubject(task.Task):

    def __init__(self, task_id, task_type, subject_repo):
        self.task_id = task_id
        self.task_type = task_type
        self.subject_repo = subject_repo
        super(_SaveSubject, self).__init__(
            name='%s-SaveSubject-%s' % (task_type, task_id))

    def execute(self, subject_id):
        """Transition subject status to active

        :param subject_id: Glance Subject ID
        """
        new_subject = self.subject_repo.get(subject_id)
        if new_subject.status == 'saving':
            # NOTE(flaper87): THIS IS WRONG!
            # we should be doing atomic updates to avoid
            # race conditions. This happens in other places
            # too.
            new_subject.status = 'active'
        self.subject_repo.save(new_subject)


class _CompleteTask(task.Task):

    def __init__(self, task_id, task_type, task_repo):
        self.task_id = task_id
        self.task_type = task_type
        self.task_repo = task_repo
        super(_CompleteTask, self).__init__(
            name='%s-CompleteTask-%s' % (task_type, task_id))

    def execute(self, subject_id):
        """Finishing the task flow

        :param subject_id: Glance Subject ID
        """
        task = script_utils.get_task(self.task_repo, self.task_id)
        if task is None:
            return
        try:
            task.succeed({'subject_id': subject_id})
        except Exception as e:
            # Note: The message string contains Error in it to indicate
            # in the task.message that it's a error message for the user.

            # TODO(nikhil): need to bring back save_and_reraise_exception when
            # necessary
            log_msg = _LE("Task ID %(task_id)s failed. Error: %(exc_type)s: "
                          "%(e)s")
            LOG.exception(log_msg, {'exc_type': six.text_type(type(e)),
                                    'e': encodeutils.exception_to_unicode(e),
                                    'task_id': task.task_id})

            err_msg = _("Error: %(exc_type)s: %(e)s")
            task.fail(err_msg % {'exc_type': six.text_type(type(e)),
                                 'e': encodeutils.exception_to_unicode(e)})
        finally:
            self.task_repo.save(task)

        LOG.info(_LI("%(task_id)s of %(task_type)s completed"),
                 {'task_id': self.task_id, 'task_type': self.task_type})


def _get_import_flows(**kwargs):
    # NOTE(flaper87): Until we have a better infrastructure to enable
    # and disable tasks plugins, hard-code the tasks we know exist,
    # instead of loading everything from the namespace. This guarantees
    # both, the load order of these plugins and the fact that no random
    # plugins will be added/loaded until we feel comfortable with this.
    # Future patches will keep using NamedExtensionManager but they'll
    # rely on a config option to control this process.
    extensions = named.NamedExtensionManager('subject.flows.import',
                                             names=['ovf_process',
                                                    'convert',
                                                    'introspect'],
                                             name_order=True,
                                             invoke_on_load=True,
                                             invoke_kwds=kwargs)

    for ext in extensions.extensions:
        yield ext.obj


def get_flow(**kwargs):
    """Return task flow

    :param task_id: Task ID
    :param task_type: Type of the task
    :param task_repo: Task repo
    :param subject_repo: Subject repository used
    :param subject_factory: Glance Subject Factory
    :param uri: uri for the subject file
    """
    task_id = kwargs.get('task_id')
    task_type = kwargs.get('task_type')
    task_repo = kwargs.get('task_repo')
    subject_repo = kwargs.get('subject_repo')
    subject_factory = kwargs.get('subject_factory')
    uri = kwargs.get('uri')

    flow = lf.Flow(task_type, retry=retry.AlwaysRevert()).add(
        _CreateSubject(task_id, task_type, task_repo, subject_repo, subject_factory))

    import_to_store = _ImportToStore(task_id, task_type, subject_repo, uri)

    try:
        # NOTE(flaper87): ImportToLocal and DeleteFromLocal shouldn't be here.
        # Ideally, we should have the different import flows doing this for us
        # and this function should clean up duplicated tasks. For example, say
        # 2 flows need to have a local copy of the subject - ImportToLocal - in
        # order to be able to complete the task - i.e Introspect-. In that
        # case, the introspect.get_flow call should add both, ImportToLocal and
        # DeleteFromLocal, to the flow and this function will reduce the
        # duplicated calls to those tasks by creating a linear flow that
        # ensures those are called before the other tasks.  For now, I'm
        # keeping them here, though.
        limbo = lf.Flow(task_type).add(_ImportToFS(task_id,
                                                   task_type,
                                                   task_repo,
                                                   uri))

        for subflow in _get_import_flows(**kwargs):
            limbo.add(subflow)

        # NOTE(flaper87): We have hard-coded 2 tasks,
        # if there aren't more than 2, it means that
        # no subtask has been registered.
        if len(limbo) > 1:
            flow.add(limbo)

            # NOTE(flaper87): Until this implementation gets smarter,
            # make sure ImportToStore is called *after* the imported
            # flow stages. If not, the subject will be set to saving state
            # invalidating tasks like Introspection or Convert.
            flow.add(import_to_store)

            # NOTE(flaper87): Since this is an "optional" task but required
            # when `limbo` is executed, we're adding it in its own subflow
            # to isolate it from the rest of the flow.
            delete_flow = lf.Flow(task_type).add(_DeleteFromFS(task_id,
                                                               task_type))
            flow.add(delete_flow)
        else:
            flow.add(import_to_store)
    except exception.BadTaskConfiguration as exc:
        # NOTE(flaper87): If something goes wrong with the load of
        # import tasks, make sure we go on.
        LOG.error(_LE('Bad task configuration: %s'), exc.message)
        flow.add(import_to_store)

    flow.add(
        _SaveSubject(task_id, task_type, subject_repo),
        _CompleteTask(task_id, task_type, task_repo)
    )
    return flow
