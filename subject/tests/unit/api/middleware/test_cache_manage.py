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

from subject.api import cached_subjects
from subject.api.middleware import cache_manage
import subject.common.config
import subject.common.wsgi
import subject.subject_cache
from subject.tests import utils as test_utils

import mock
import webob


class TestCacheManageFilter(test_utils.BaseTestCase):
    @mock.patch.object(subject.subject_cache.SubjectCache, "init_driver")
    def setUp(self, mock_init_driver):
        super(TestCacheManageFilter, self).setUp()
        self.stub_application_name = "stubApplication"
        self.stub_value = "Stub value"
        self.subject_id = "subject_id_stub"

        mock_init_driver.return_value = None

        self.cache_manage_filter = cache_manage.CacheManageFilter(
            self.stub_application_name)

    def test_bogus_request(self):
        # prepare
        bogus_request = webob.Request.blank("/bogus/")

        # call
        resource = self.cache_manage_filter.process_request(bogus_request)

        # check
        self.assertIsNone(resource)

    @mock.patch.object(cached_subjects.Controller, "get_cached_subjects")
    def test_get_cached_subjects(self,
                               mock_get_cached_subjects):
        # setup
        mock_get_cached_subjects.return_value = self.stub_value

        # prepare
        request = webob.Request.blank("/v1/cached_subjects")

        # call
        resource = self.cache_manage_filter.process_request(request)

        # check
        mock_get_cached_subjects.assert_called_with(request)
        self.assertEqual('"' + self.stub_value + '"',
                         resource.body.decode('utf-8'))

    @mock.patch.object(cached_subjects.Controller, "delete_cached_subject")
    def test_delete_cached_subject(self,
                                 mock_delete_cached_subject):
        # setup
        mock_delete_cached_subject.return_value = self.stub_value

        # prepare
        request = webob.Request.blank("/v1/cached_subjects/" + self.subject_id,
                                      environ={'REQUEST_METHOD': "DELETE"})

        # call
        resource = self.cache_manage_filter.process_request(request)

        # check
        mock_delete_cached_subject.assert_called_with(request,
                                                    subject_id=self.subject_id)
        self.assertEqual('"' + self.stub_value + '"',
                         resource.body.decode('utf-8'))

    @mock.patch.object(cached_subjects.Controller, "delete_cached_subjects")
    def test_delete_cached_subjects(self,
                                  mock_delete_cached_subjects):
        # setup
        mock_delete_cached_subjects.return_value = self.stub_value

        # prepare
        request = webob.Request.blank("/v1/cached_subjects",
                                      environ={'REQUEST_METHOD': "DELETE"})

        # call
        resource = self.cache_manage_filter.process_request(request)

        # check
        mock_delete_cached_subjects.assert_called_with(request)
        self.assertEqual('"' + self.stub_value + '"',
                         resource.body.decode('utf-8'))

    @mock.patch.object(cached_subjects.Controller, "queue_subject")
    def test_put_queued_subject(self,
                              mock_queue_subject):
        # setup
        mock_queue_subject.return_value = self.stub_value

        # prepare
        request = webob.Request.blank("/v1/queued_subjects/" + self.subject_id,
                                      environ={'REQUEST_METHOD': "PUT"})

        # call
        resource = self.cache_manage_filter.process_request(request)

        # check
        mock_queue_subject.assert_called_with(request, subject_id=self.subject_id)
        self.assertEqual('"' + self.stub_value + '"',
                         resource.body.decode('utf-8'))

    @mock.patch.object(cached_subjects.Controller, "get_queued_subjects")
    def test_get_queued_subjects(self,
                               mock_get_queued_subjects):
        # setup
        mock_get_queued_subjects.return_value = self.stub_value

        # prepare
        request = webob.Request.blank("/v1/queued_subjects")

        # call
        resource = self.cache_manage_filter.process_request(request)

        # check
        mock_get_queued_subjects.assert_called_with(request)
        self.assertEqual('"' + self.stub_value + '"',
                         resource.body.decode('utf-8'))

    @mock.patch.object(cached_subjects.Controller, "delete_queued_subject")
    def test_delete_queued_subject(self,
                                 mock_delete_queued_subject):
        # setup
        mock_delete_queued_subject.return_value = self.stub_value

        # prepare
        request = webob.Request.blank("/v1/queued_subjects/" + self.subject_id,
                                      environ={'REQUEST_METHOD': 'DELETE'})

        # call
        resource = self.cache_manage_filter.process_request(request)

        # check
        mock_delete_queued_subject.assert_called_with(request,
                                                    subject_id=self.subject_id)
        self.assertEqual('"' + self.stub_value + '"',
                         resource.body.decode('utf-8'))

    @mock.patch.object(cached_subjects.Controller, "delete_queued_subjects")
    def test_delete_queued_subjects(self,
                                  mock_delete_queued_subjects):
        # setup
        mock_delete_queued_subjects.return_value = self.stub_value

        # prepare
        request = webob.Request.blank("/v1/queued_subjects",
                                      environ={'REQUEST_METHOD': 'DELETE'})

        # call
        resource = self.cache_manage_filter.process_request(request)

        # check
        mock_delete_queued_subjects.assert_called_with(request)
        self.assertEqual('"' + self.stub_value + '"',
                         resource.body.decode('utf-8'))
