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
import mock
import os

import glance_store
from oslo_concurrency import processutils as putils
from oslo_config import cfg
import six
from six.moves import urllib
from taskflow import task
from taskflow.types import failure

import subject.async.flows.base_import as import_flow
from subject.async import taskflow_executor
from subject.async import utils as async_utils
from subject.common.scripts.subject_import import main as subject_import
from subject.common.scripts import utils as script_utils
from subject.common import utils
from subject import domain
from subject import gateway
import subject.tests.utils as test_utils

CONF = cfg.CONF

UUID1 = 'c80a1a6c-bd1f-41c5-90ee-81afedb1d58d'
TENANT1 = '6838eb7b-6ded-434a-882c-b344c77fe8df'


class _ErrorTask(task.Task):

    def execute(self):
        raise RuntimeError()


class TestImportTask(test_utils.BaseTestCase):

    def setUp(self):
        super(TestImportTask, self).setUp()

        glance_store.register_opts(CONF)
        self.config(default_store='file',
                    stores=['file', 'http'],
                    filesystem_store_datadir=self.test_dir,
                    group="glance_store")
        glance_store.create_stores(CONF)

        self.work_dir = os.path.join(self.test_dir, 'work_dir')
        utils.safe_mkdirs(self.work_dir)
        self.config(work_dir=self.work_dir, group='task')

        self.context = mock.MagicMock()
        self.img_repo = mock.MagicMock()
        self.task_repo = mock.MagicMock()

        self.gateway = gateway.Gateway()
        self.task_factory = domain.TaskFactory()
        self.img_factory = self.gateway.get_subject_factory(self.context)
        self.subject = self.img_factory.new_subject(subject_id=UUID1,
                                                  disk_format='qcow2',
                                                  container_format='bare')

        task_input = {
            "import_from": "http://cloud.foo/subject.qcow2",
            "import_from_format": "qcow2",
            "subject_properties": {'disk_format': 'qcow2',
                                 'container_format': 'bare'}
        }
        task_ttl = CONF.task.task_time_to_live

        self.task_type = 'import'
        self.task = self.task_factory.new_task(self.task_type, TENANT1,
                                               task_time_to_live=task_ttl,
                                               task_input=task_input)

    def _assert_qemu_process_limits(self, exec_mock):
        # NOTE(hemanthm): Assert that process limits are being applied
        # on "qemu-img info" calls. See bug #1449062 for more details.
        kw_args = exec_mock.call_args[1]
        self.assertIn('prlimit', kw_args)
        self.assertEqual(async_utils.QEMU_IMG_PROC_LIMITS,
                         kw_args.get('prlimit'))

    def test_import_flow(self):
        self.config(engine_mode='serial',
                    group='taskflow_executor')

        img_factory = mock.MagicMock()

        executor = taskflow_executor.TaskExecutor(
            self.context,
            self.task_repo,
            self.img_repo,
            img_factory)

        self.task_repo.get.return_value = self.task

        def create_subject(*args, **kwargs):
            kwargs['subject_id'] = UUID1
            return self.img_factory.new_subject(*args, **kwargs)

        self.img_repo.get.return_value = self.subject
        img_factory.new_subject.side_effect = create_subject

        with mock.patch.object(script_utils, 'get_subject_data_iter') as dmock:
            dmock.return_value = six.BytesIO(b"TEST_IMAGE")

            with mock.patch.object(putils, 'trycmd') as tmock:
                tmock.return_value = (json.dumps({
                    'format': 'qcow2',
                }), None)

                executor.begin_processing(self.task.task_id)
                subject_path = os.path.join(self.test_dir, self.subject.subject_id)
                tmp_subject_path = os.path.join(self.work_dir,
                                              "%s.tasks_import" % subject_path)

                self.assertFalse(os.path.exists(tmp_subject_path))
                self.assertTrue(os.path.exists(subject_path))
                self.assertEqual(1, len(list(self.subject.locations)))
                self.assertEqual("file://%s/%s" % (self.test_dir,
                                                   self.subject.subject_id),
                                 self.subject.locations[0]['url'])

                self._assert_qemu_process_limits(tmock)

    def test_import_flow_missing_work_dir(self):
        self.config(engine_mode='serial', group='taskflow_executor')
        self.config(work_dir=None, group='task')

        img_factory = mock.MagicMock()

        executor = taskflow_executor.TaskExecutor(
            self.context,
            self.task_repo,
            self.img_repo,
            img_factory)

        self.task_repo.get.return_value = self.task

        def create_subject(*args, **kwargs):
            kwargs['subject_id'] = UUID1
            return self.img_factory.new_subject(*args, **kwargs)

        self.img_repo.get.return_value = self.subject
        img_factory.new_subject.side_effect = create_subject

        with mock.patch.object(script_utils, 'get_subject_data_iter') as dmock:
            dmock.return_value = six.BytesIO(b"TEST_IMAGE")

            with mock.patch.object(import_flow._ImportToFS, 'execute') as emk:
                executor.begin_processing(self.task.task_id)
                self.assertFalse(emk.called)

                subject_path = os.path.join(self.test_dir, self.subject.subject_id)
                tmp_subject_path = os.path.join(self.work_dir,
                                              "%s.tasks_import" % subject_path)
                self.assertFalse(os.path.exists(tmp_subject_path))
                self.assertTrue(os.path.exists(subject_path))

    def test_import_flow_revert_import_to_fs(self):
        self.config(engine_mode='serial', group='taskflow_executor')

        img_factory = mock.MagicMock()

        executor = taskflow_executor.TaskExecutor(
            self.context,
            self.task_repo,
            self.img_repo,
            img_factory)

        self.task_repo.get.return_value = self.task

        def create_subject(*args, **kwargs):
            kwargs['subject_id'] = UUID1
            return self.img_factory.new_subject(*args, **kwargs)

        self.img_repo.get.return_value = self.subject
        img_factory.new_subject.side_effect = create_subject

        with mock.patch.object(script_utils, 'get_subject_data_iter') as dmock:
            dmock.side_effect = RuntimeError

            with mock.patch.object(import_flow._ImportToFS, 'revert') as rmock:
                self.assertRaises(RuntimeError,
                                  executor.begin_processing, self.task.task_id)
                self.assertTrue(rmock.called)
                self.assertIsInstance(rmock.call_args[1]['result'],
                                      failure.Failure)

                subject_path = os.path.join(self.test_dir, self.subject.subject_id)
                tmp_subject_path = os.path.join(self.work_dir,
                                              "%s.tasks_import" % subject_path)
                self.assertFalse(os.path.exists(tmp_subject_path))
                # Note(sabari): The subject should not have been uploaded to
                # the store as the flow failed before ImportToStore Task.
                self.assertFalse(os.path.exists(subject_path))

    def test_import_flow_backed_file_import_to_fs(self):
        self.config(engine_mode='serial', group='taskflow_executor')

        img_factory = mock.MagicMock()

        executor = taskflow_executor.TaskExecutor(
            self.context,
            self.task_repo,
            self.img_repo,
            img_factory)

        self.task_repo.get.return_value = self.task

        def create_subject(*args, **kwargs):
            kwargs['subject_id'] = UUID1
            return self.img_factory.new_subject(*args, **kwargs)

        self.img_repo.get.return_value = self.subject
        img_factory.new_subject.side_effect = create_subject

        with mock.patch.object(script_utils, 'get_subject_data_iter') as dmock:
            dmock.return_value = six.BytesIO(b"TEST_IMAGE")

            with mock.patch.object(putils, 'trycmd') as tmock:
                tmock.return_value = (json.dumps({
                    'backing-filename': '/etc/password'
                }), None)

                with mock.patch.object(import_flow._ImportToFS,
                                       'revert') as rmock:
                    self.assertRaises(RuntimeError,
                                      executor.begin_processing,
                                      self.task.task_id)
                    self.assertTrue(rmock.called)
                    self.assertIsInstance(rmock.call_args[1]['result'],
                                          failure.Failure)
                    self._assert_qemu_process_limits(tmock)

                    subject_path = os.path.join(self.test_dir,
                                              self.subject.subject_id)

                    fname = "%s.tasks_import" % subject_path
                    tmp_subject_path = os.path.join(self.work_dir, fname)

                    self.assertFalse(os.path.exists(tmp_subject_path))
                    # Note(sabari): The subject should not have been uploaded to
                    # the store as the flow failed before ImportToStore Task.
                    self.assertFalse(os.path.exists(subject_path))

    def test_import_flow_revert(self):
        self.config(engine_mode='serial',
                    group='taskflow_executor')

        img_factory = mock.MagicMock()

        executor = taskflow_executor.TaskExecutor(
            self.context,
            self.task_repo,
            self.img_repo,
            img_factory)

        self.task_repo.get.return_value = self.task

        def create_subject(*args, **kwargs):
            kwargs['subject_id'] = UUID1
            return self.img_factory.new_subject(*args, **kwargs)

        self.img_repo.get.return_value = self.subject
        img_factory.new_subject.side_effect = create_subject

        with mock.patch.object(script_utils, 'get_subject_data_iter') as dmock:
            dmock.return_value = six.BytesIO(b"TEST_IMAGE")

            with mock.patch.object(putils, 'trycmd') as tmock:
                tmock.return_value = (json.dumps({
                    'format': 'qcow2',
                }), None)

                with mock.patch.object(import_flow,
                                       "_get_import_flows") as imock:
                    imock.return_value = (x for x in [_ErrorTask()])
                    self.assertRaises(RuntimeError,
                                      executor.begin_processing,
                                      self.task.task_id)

                    self._assert_qemu_process_limits(tmock)

                    subject_path = os.path.join(self.test_dir,
                                              self.subject.subject_id)
                    tmp_subject_path = os.path.join(self.work_dir,
                                                  ("%s.tasks_import" %
                                                   subject_path))
                    self.assertFalse(os.path.exists(tmp_subject_path))

                    # NOTE(flaper87): Eventually, we want this to be assertTrue
                    # The current issue is there's no way to tell taskflow to
                    # continue on failures. That is, revert the subflow but
                    # keep executing the parent flow. Under
                    # discussion/development.
                    self.assertFalse(os.path.exists(subject_path))

    def test_import_flow_no_import_flows(self):
        self.config(engine_mode='serial',
                    group='taskflow_executor')

        img_factory = mock.MagicMock()

        executor = taskflow_executor.TaskExecutor(
            self.context,
            self.task_repo,
            self.img_repo,
            img_factory)

        self.task_repo.get.return_value = self.task

        def create_subject(*args, **kwargs):
            kwargs['subject_id'] = UUID1
            return self.img_factory.new_subject(*args, **kwargs)

        self.img_repo.get.return_value = self.subject
        img_factory.new_subject.side_effect = create_subject

        with mock.patch.object(urllib.request, 'urlopen') as umock:
            content = b"TEST_IMAGE"
            umock.return_value = six.BytesIO(content)

            with mock.patch.object(import_flow, "_get_import_flows") as imock:
                imock.return_value = (x for x in [])
                executor.begin_processing(self.task.task_id)
                subject_path = os.path.join(self.test_dir, self.subject.subject_id)
                tmp_subject_path = os.path.join(self.work_dir,
                                              "%s.tasks_import" % subject_path)
                self.assertFalse(os.path.exists(tmp_subject_path))
                self.assertTrue(os.path.exists(subject_path))
                self.assertEqual(1, umock.call_count)

                with open(subject_path, 'rb') as ifile:
                    self.assertEqual(content, ifile.read())

    def test_create_subject(self):
        subject_create = import_flow._CreateImage(self.task.task_id,
                                                self.task_type,
                                                self.task_repo,
                                                self.img_repo,
                                                self.img_factory)

        self.task_repo.get.return_value = self.task
        with mock.patch.object(subject_import, 'create_subject') as ci_mock:
            ci_mock.return_value = mock.Mock()
            subject_create.execute()

            ci_mock.assert_called_once_with(self.img_repo,
                                            self.img_factory,
                                            {'container_format': 'bare',
                                             'disk_format': 'qcow2'},
                                            self.task.task_id)

    def test_save_subject(self):
        save_subject = import_flow._SaveImage(self.task.task_id,
                                            self.task_type,
                                            self.img_repo)

        with mock.patch.object(self.img_repo, 'get') as get_mock:
            subject_id = mock.sentinel.subject_id
            subject = mock.MagicMock(subject_id=subject_id, status='saving')
            get_mock.return_value = subject

            with mock.patch.object(self.img_repo, 'save') as save_mock:
                save_subject.execute(subject.subject_id)
                get_mock.assert_called_once_with(subject_id)
                save_mock.assert_called_once_with(subject)
                self.assertEqual('active', subject.status)

    def test_import_to_fs(self):
        import_fs = import_flow._ImportToFS(self.task.task_id,
                                            self.task_type,
                                            self.task_repo,
                                            'http://example.com/subject.qcow2')

        with mock.patch.object(script_utils, 'get_subject_data_iter') as dmock:
            content = b"test"
            dmock.return_value = [content]

            with mock.patch.object(putils, 'trycmd') as tmock:
                tmock.return_value = (json.dumps({
                    'format': 'qcow2',
                }), None)

                subject_id = UUID1
                path = import_fs.execute(subject_id)
                reader, size = glance_store.get_from_backend(path)
                self.assertEqual(4, size)
                self.assertEqual(content, b"".join(reader))

                subject_path = os.path.join(self.work_dir, subject_id)
                tmp_subject_path = os.path.join(self.work_dir, subject_path)
                self.assertTrue(os.path.exists(tmp_subject_path))
                self._assert_qemu_process_limits(tmock)

    def test_delete_from_fs(self):
        delete_fs = import_flow._DeleteFromFS(self.task.task_id,
                                              self.task_type)

        data = [b"test"]

        store = glance_store.get_store_from_scheme('file')
        path = glance_store.store_add_to_backend(mock.sentinel.subject_id, data,
                                                 mock.sentinel.subject_size,
                                                 store, context=None)[0]

        path_wo_scheme = path.split("file://")[1]
        self.assertTrue(os.path.exists(path_wo_scheme))
        delete_fs.execute(path)
        self.assertFalse(os.path.exists(path_wo_scheme))

    def test_complete_task(self):
        complete_task = import_flow._CompleteTask(self.task.task_id,
                                                  self.task_type,
                                                  self.task_repo)

        subject_id = mock.sentinel.subject_id
        subject = mock.MagicMock(subject_id=subject_id)

        self.task_repo.get.return_value = self.task
        with mock.patch.object(self.task, 'succeed') as succeed:
            complete_task.execute(subject.subject_id)
            succeed.assert_called_once_with({'subject_id': subject_id})
