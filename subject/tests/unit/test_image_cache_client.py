# Copyright 2013 OpenStack Foundation
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
import os

import mock

from subject.common import exception
from subject.subject_cache import client
from subject.tests import utils


class CacheClientTestCase(utils.BaseTestCase):
    def setUp(self):
        super(CacheClientTestCase, self).setUp()
        self.client = client.CacheClient('test_host')
        self.client.do_request = mock.Mock()

    def test_delete_cached_subject(self):
        self.client.do_request.return_value = utils.FakeHTTPResponse()
        self.assertTrue(self.client.delete_cached_subject('test_id'))
        self.client.do_request.assert_called_with("DELETE",
                                                  "/cached_subjects/test_id")

    def test_get_cached_subjects(self):
        expected_data = b'{"cached_subjects": "some_subjects"}'
        self.client.do_request.return_value = utils.FakeHTTPResponse(
            data=expected_data)
        self.assertEqual("some_subjects", self.client.get_cached_subjects())
        self.client.do_request.assert_called_with("GET", "/cached_subjects")

    def test_get_queued_subjects(self):
        expected_data = b'{"queued_subjects": "some_subjects"}'
        self.client.do_request.return_value = utils.FakeHTTPResponse(
            data=expected_data)
        self.assertEqual("some_subjects", self.client.get_queued_subjects())
        self.client.do_request.assert_called_with("GET", "/queued_subjects")

    def test_delete_all_cached_subjects(self):
        expected_data = b'{"num_deleted": 4}'
        self.client.do_request.return_value = utils.FakeHTTPResponse(
            data=expected_data)
        self.assertEqual(4, self.client.delete_all_cached_subjects())
        self.client.do_request.assert_called_with("DELETE", "/cached_subjects")

    def test_queue_subject_for_caching(self):
        self.client.do_request.return_value = utils.FakeHTTPResponse()
        self.assertTrue(self.client.queue_subject_for_caching('test_id'))
        self.client.do_request.assert_called_with("PUT",
                                                  "/queued_subjects/test_id")

    def test_delete_queued_subject(self):
        self.client.do_request.return_value = utils.FakeHTTPResponse()
        self.assertTrue(self.client.delete_queued_subject('test_id'))
        self.client.do_request.assert_called_with("DELETE",
                                                  "/queued_subjects/test_id")

    def test_delete_all_queued_subjects(self):
        expected_data = b'{"num_deleted": 4}'
        self.client.do_request.return_value = utils.FakeHTTPResponse(
            data=expected_data)
        self.assertEqual(4, self.client.delete_all_queued_subjects())
        self.client.do_request.assert_called_with("DELETE", "/queued_subjects")


class GetClientTestCase(utils.BaseTestCase):
    def setUp(self):
        super(GetClientTestCase, self).setUp()
        self.host = 'test_host'
        self.env = os.environ.copy()
        os.environ.clear()

    def tearDown(self):
        os.environ = self.env
        super(GetClientTestCase, self).tearDown()

    def test_get_client_host_only(self):
        expected_creds = {
            'username': None,
            'password': None,
            'tenant': None,
            'auth_url': None,
            'strategy': 'noauth',
            'region': None
        }
        self.assertEqual(expected_creds, client.get_client(self.host).creds)

    def test_get_client_all_creds(self):
        expected_creds = {
            'username': 'name',
            'password': 'pass',
            'tenant': 'ten',
            'auth_url': 'url',
            'strategy': 'keystone',
            'region': 'reg'
        }
        creds = client.get_client(
            self.host,
            username='name',
            password='pass',
            tenant='ten',
            auth_url='url',
            auth_strategy='strategy',
            region='reg'
        ).creds
        self.assertEqual(expected_creds, creds)

    def test_get_client_client_configuration_error(self):
        self.assertRaises(exception.ClientConfigurationError,
                          client.get_client, self.host, username='name',
                          password='pass', tenant='ten',
                          auth_strategy='keystone', region='reg')
