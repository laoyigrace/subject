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
import sys

import glance_store as store
import mock
from oslo_config import cfg
from oslo_log import log as logging
import six

import subject.cmd.api
import subject.cmd.cache_cleaner
import subject.cmd.cache_pruner
import subject.common.config
from subject.common import exception as exc
import subject.common.wsgi
import subject.subject_cache.cleaner
import subject.subject_cache.pruner
from subject.tests import utils as test_utils


CONF = cfg.CONF


class TestGlanceApiCmd(test_utils.BaseTestCase):

    __argv_backup = None

    def _do_nothing(self, *args, **kwargs):
        pass

    def _raise(self, exc):
        def fake(*args, **kwargs):
            raise exc
        return fake

    def setUp(self):
        super(TestGlanceApiCmd, self).setUp()
        self.__argv_backup = sys.argv
        sys.argv = ['subject-api']
        self.stderr = six.StringIO()
        sys.stderr = self.stderr

        store.register_opts(CONF)

        self.stubs.Set(subject.common.config, 'load_paste_app',
                       self._do_nothing)
        self.stubs.Set(subject.common.wsgi.Server, 'start',
                       self._do_nothing)
        self.stubs.Set(subject.common.wsgi.Server, 'wait',
                       self._do_nothing)

    def tearDown(self):
        sys.stderr = sys.__stderr__
        sys.argv = self.__argv_backup
        super(TestGlanceApiCmd, self).tearDown()

    def test_supported_default_store(self):
        self.config(group='glance_store', default_store='file')
        subject.cmd.api.main()

    def test_unsupported_default_store(self):
        self.stubs.UnsetAll()
        self.config(group='glance_store', default_store='shouldnotexist')
        exit = self.assertRaises(SystemExit, subject.cmd.api.main)
        self.assertEqual(1, exit.code)

    def test_worker_creation_failure(self):
        failure = exc.WorkerCreationFailure(reason='test')
        self.stubs.Set(subject.common.wsgi.Server, 'start',
                       self._raise(failure))
        exit = self.assertRaises(SystemExit, subject.cmd.api.main)
        self.assertEqual(2, exit.code)

    @mock.patch.object(subject.common.config, 'parse_cache_args')
    @mock.patch.object(logging, 'setup')
    @mock.patch.object(subject.subject_cache.ImageCache, 'init_driver')
    @mock.patch.object(subject.subject_cache.ImageCache, 'clean')
    def test_cache_cleaner_main(self, mock_cache_clean,
                                mock_cache_init_driver, mock_log_setup,
                                mock_parse_config):
        mock_cache_init_driver.return_value = None

        manager = mock.MagicMock()
        manager.attach_mock(mock_log_setup, 'mock_log_setup')
        manager.attach_mock(mock_parse_config, 'mock_parse_config')
        manager.attach_mock(mock_cache_init_driver, 'mock_cache_init_driver')
        manager.attach_mock(mock_cache_clean, 'mock_cache_clean')
        subject.cmd.cache_cleaner.main()
        expected_call_sequence = [mock.call.mock_parse_config(),
                                  mock.call.mock_log_setup(CONF, 'subject'),
                                  mock.call.mock_cache_init_driver(),
                                  mock.call.mock_cache_clean()]
        self.assertEqual(expected_call_sequence, manager.mock_calls)

    @mock.patch.object(subject.subject_cache.base.CacheApp, '__init__')
    def test_cache_cleaner_main_runtime_exception_handling(self, mock_cache):
        mock_cache.return_value = None
        self.stubs.Set(subject.subject_cache.cleaner.Cleaner, 'run',
                       self._raise(RuntimeError))
        exit = self.assertRaises(SystemExit, subject.cmd.cache_cleaner.main)
        self.assertEqual('ERROR: ', exit.code)

    @mock.patch.object(subject.common.config, 'parse_cache_args')
    @mock.patch.object(logging, 'setup')
    @mock.patch.object(subject.subject_cache.ImageCache, 'init_driver')
    @mock.patch.object(subject.subject_cache.ImageCache, 'prune')
    def test_cache_pruner_main(self, mock_cache_prune,
                               mock_cache_init_driver, mock_log_setup,
                               mock_parse_config):
        mock_cache_init_driver.return_value = None

        manager = mock.MagicMock()
        manager.attach_mock(mock_log_setup, 'mock_log_setup')
        manager.attach_mock(mock_parse_config, 'mock_parse_config')
        manager.attach_mock(mock_cache_init_driver, 'mock_cache_init_driver')
        manager.attach_mock(mock_cache_prune, 'mock_cache_prune')
        subject.cmd.cache_pruner.main()
        expected_call_sequence = [mock.call.mock_parse_config(),
                                  mock.call.mock_log_setup(CONF, 'subject'),
                                  mock.call.mock_cache_init_driver(),
                                  mock.call.mock_cache_prune()]
        self.assertEqual(expected_call_sequence, manager.mock_calls)

    @mock.patch.object(subject.subject_cache.base.CacheApp, '__init__')
    def test_cache_pruner_main_runtime_exception_handling(self, mock_cache):
        mock_cache.return_value = None
        self.stubs.Set(subject.subject_cache.pruner.Pruner, 'run',
                       self._raise(RuntimeError))
        exit = self.assertRaises(SystemExit, subject.cmd.cache_pruner.main)
        self.assertEqual('ERROR: ', exit.code)
