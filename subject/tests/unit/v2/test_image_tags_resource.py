# Copyright 2012 OpenStack Foundation
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

import webob

import subject.api.v2.subject_tags
from subject.common import exception
from subject.tests.unit import base
import subject.tests.unit.utils as unit_test_utils
import subject.tests.unit.v2.test_subject_data_resource as subject_data_tests
import subject.tests.utils as test_utils


class TestSubjectTagsController(base.IsolatedUnitTest):

    def setUp(self):
        super(TestSubjectTagsController, self).setUp()
        self.db = unit_test_utils.FakeDB()
        self.controller = subject.api.v2.subject_tags.Controller(self.db)

    def test_create_tag(self):
        request = unit_test_utils.get_fake_request()
        self.controller.update(request, unit_test_utils.UUID1, 'dink')
        context = request.context
        tags = self.db.subject_tag_get_all(context, unit_test_utils.UUID1)
        self.assertEqual(1, len([tag for tag in tags if tag == 'dink']))

    def test_create_too_many_tags(self):
        self.config(subject_tag_quota=0)
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update,
                          request, unit_test_utils.UUID1, 'dink')

    def test_create_duplicate_tag_ignored(self):
        request = unit_test_utils.get_fake_request()
        self.controller.update(request, unit_test_utils.UUID1, 'dink')
        self.controller.update(request, unit_test_utils.UUID1, 'dink')
        context = request.context
        tags = self.db.subject_tag_get_all(context, unit_test_utils.UUID1)
        self.assertEqual(1, len([tag for tag in tags if tag == 'dink']))

    def test_update_tag_of_non_existing_subject(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          request, "abcd", "dink")

    def test_delete_tag_forbidden(self):
        def fake_get(self):
            raise exception.Forbidden()

        subject_repo = subject_data_tests.FakeSubjectRepo()
        subject_repo.get = fake_get

        def get_fake_repo(self):
            return subject_repo

        self.controller.gateway.get_repo = get_fake_repo
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          request, unit_test_utils.UUID1, "ping")

    def test_delete_tag(self):
        request = unit_test_utils.get_fake_request()
        self.controller.delete(request, unit_test_utils.UUID1, 'ping')

    def test_delete_tag_not_found(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          request, unit_test_utils.UUID1, 'what')

    def test_delete_tag_of_non_existing_subject(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          request, "abcd", "dink")


class TestSubjectsSerializer(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectsSerializer, self).setUp()
        self.serializer = subject.api.v2.subject_tags.ResponseSerializer()

    def test_create_tag(self):
        response = webob.Response()
        self.serializer.update(response, None)
        self.assertEqual(204, response.status_int)

    def test_delete_tag(self):
        response = webob.Response()
        self.serializer.delete(response, None)
        self.assertEqual(204, response.status_int)
