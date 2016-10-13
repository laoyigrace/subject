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

import mock
from six.moves import urllib

import subject.common.exception as exception
from subject.common.scripts.subject_import import main as subject_import_script
from subject.common.scripts import utils
from subject.common import store_utils

import subject.tests.utils as test_utils


class TestSubjectImport(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectImport, self).setUp()

    def test_run(self):
        with mock.patch.object(subject_import_script,
                               '_execute') as mock_execute:
            task_id = mock.ANY
            context = mock.ANY
            task_repo = mock.ANY
            subject_repo = mock.ANY
            subject_factory = mock.ANY
            subject_import_script.run(task_id, context, task_repo, subject_repo,
                                    subject_factory)

        mock_execute.assert_called_once_with(task_id, task_repo, subject_repo,
                                             subject_factory)

    def test_import_subject(self):
        subject_id = mock.ANY
        subject = mock.Mock(subject_id=subject_id)
        subject_repo = mock.Mock()
        subject_repo.get.return_value = subject
        subject_factory = mock.ANY
        task_input = mock.Mock(subject_properties=mock.ANY)
        uri = mock.ANY
        with mock.patch.object(subject_import_script,
                               'create_subject') as mock_create_subject:
            with mock.patch.object(subject_import_script,
                                   'set_subject_data') as mock_set_img_data:
                mock_create_subject.return_value = subject
                self.assertEqual(
                    subject_id,
                    subject_import_script.import_subject(subject_repo, subject_factory,
                                                     task_input, None, uri))
                # Check subject is in saving state before subject_repo.save called
                self.assertEqual('saving', subject.status)
                self.assertTrue(subject_repo.save.called)
                mock_set_img_data.assert_called_once_with(subject, uri, None)
                self.assertTrue(subject_repo.get.called)
                self.assertTrue(subject_repo.save.called)

    def test_create_subject(self):
        subject = mock.ANY
        subject_repo = mock.Mock()
        subject_factory = mock.Mock()
        subject_factory.new_subject.return_value = subject

        # Note: include some base properties to ensure no error while
        # attempting to verify them
        subject_properties = {'disk_format': 'foo',
                            'id': 'bar'}

        self.assertEqual(subject,
                         subject_import_script.create_subject(subject_repo,
                                                          subject_factory,
                                                          subject_properties,
                                                          None))

    @mock.patch.object(utils, 'get_subject_data_iter')
    def test_set_subject_data_http(self, mock_subject_iter):
        uri = 'http://www.example.com'
        subject = mock.Mock()
        mock_subject_iter.return_value = test_utils.FakeHTTPResponse()
        self.assertIsNone(subject_import_script.set_subject_data(subject,
                                                             uri,
                                                             None))

    def test_set_subject_data_http_error(self):
        uri = 'blahhttp://www.example.com'
        subject = mock.Mock()
        self.assertRaises(urllib.error.URLError,
                          subject_import_script.set_subject_data, subject, uri, None)

    @mock.patch.object(subject_import_script, 'create_subject')
    @mock.patch.object(subject_import_script, 'set_subject_data')
    @mock.patch.object(store_utils, 'delete_subject_location_from_backend')
    def test_import_subject_failed_with_expired_token(
            self, mock_delete_data, mock_set_img_data, mock_create_subject):
        subject_id = mock.ANY
        locations = ['location']
        subject = mock.Mock(subject_id=subject_id, locations=locations)
        subject_repo = mock.Mock()
        subject_repo.get.side_effect = [subject, exception.NotAuthenticated]
        subject_factory = mock.ANY
        task_input = mock.Mock(subject_properties=mock.ANY)
        uri = mock.ANY

        mock_create_subject.return_value = subject
        self.assertRaises(exception.NotAuthenticated,
                          subject_import_script.import_subject,
                          subject_repo, subject_factory,
                          task_input, None, uri)
        self.assertEqual(1, mock_set_img_data.call_count)
        mock_delete_data.assert_called_once_with(
            mock_create_subject().context, subject_id, 'location')
