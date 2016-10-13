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

"""Version-independent api tests"""


import httplib2
from oslo_serialization import jsonutils

from subject.tests import functional


class TestApiVersions(functional.FunctionalTest):

    def test_version_configurations(self):
        """Test that versioning is handled properly through all channels"""
        # v1 and v1 api enabled
        self.start_servers(**self.__dict__.copy())

        url = 'http://127.0.0.1:%d/v%%s/' % self.api_port
        versions = {'versions': [
            {
                'id': 'v1.4',
                'status': 'CURRENT',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.3',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.2',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.1',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.0',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.1',
                'status': 'DEPRECATED',
                'links': [{'rel': 'self', 'href': url % '1'}],
            },
            {
                'id': 'v1.0',
                'status': 'DEPRECATED',
                'links': [{'rel': 'self', 'href': url % '1'}],
            },
        ]}
        versions_json = jsonutils.dumps(versions)

        # Verify version choices returned.
        path = 'http://%s:%d' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(300, response.status)
        self.assertEqual(versions_json, content)

    def test_v2_api_configuration(self):
        self.api_server.enable_v1_api = False
        self.api_server.enable_v2_api = True
        self.start_servers(**self.__dict__.copy())

        url = 'http://127.0.0.1:%d/v%%s/' % self.api_port
        versions = {'versions': [
            {
                'id': 'v1.4',
                'status': 'CURRENT',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.3',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.2',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.1',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.0',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
        ]}
        versions_json = jsonutils.dumps(versions)

        # Verify version choices returned.
        path = 'http://%s:%d' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(300, response.status)
        self.assertEqual(versions_json, content)

    def test_v1_api_configuration(self):
        self.api_server.enable_v1_api = True
        self.api_server.enable_v2_api = False
        self.start_servers(**self.__dict__.copy())

        url = 'http://127.0.0.1:%d/v%%s/' % self.api_port
        versions = {'versions': [
            {
                'id': 'v1.1',
                'status': 'DEPRECATED',
                'links': [{'rel': 'self', 'href': url % '1'}],
            },
            {
                'id': 'v1.0',
                'status': 'DEPRECATED',
                'links': [{'rel': 'self', 'href': url % '1'}],
            },
        ]}
        versions_json = jsonutils.dumps(versions)

        # Verify version choices returned.
        path = 'http://%s:%d' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(300, response.status)
        self.assertEqual(versions_json, content)


class TestApiPaths(functional.FunctionalTest):
    def setUp(self):
        super(TestApiPaths, self).setUp()
        self.start_servers(**self.__dict__.copy())

        url = 'http://127.0.0.1:%d/v%%s/' % self.api_port
        versions = {'versions': [
            {
                'id': 'v1.4',
                'status': 'CURRENT',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.3',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.2',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.1',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.0',
                'status': 'SUPPORTED',
                'links': [{'rel': 'self', 'href': url % '2'}],
            },
            {
                'id': 'v1.1',
                'status': 'DEPRECATED',
                'links': [{'rel': 'self', 'href': url % '1'}],
            },
            {
                'id': 'v1.0',
                'status': 'DEPRECATED',
                'links': [{'rel': 'self', 'href': url % '1'}],
            },
        ]}
        self.versions_json = jsonutils.dumps(versions)
        subjects = {'subjects': []}
        self.subjects_json = jsonutils.dumps(subjects)

    def test_get_root_path(self):
        """Assert GET / with `no Accept:` header.
        Verify version choices returned.
        Bug lp:803260  no Accept header causes a 500 in subject-api
        """
        path = 'http://%s:%d' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(300, response.status)
        self.assertEqual(self.versions_json, content)

    def test_get_subjects_path(self):
        """Assert GET /subjects with `no Accept:` header.
        Verify version choices returned.
        """
        path = 'http://%s:%d/subjects' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(300, response.status)
        self.assertEqual(self.versions_json, content)

    def test_get_v1_subjects_path(self):
        """GET /v1/subjects with `no Accept:` header.
        Verify empty subjects list returned.
        """
        path = 'http://%s:%d/v1/subjects' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

    def test_get_root_path_with_unknown_header(self):
        """Assert GET / with Accept: unknown header
        Verify version choices returned. Verify message in API log about
        unknown accept header.
        """
        path = 'http://%s:%d/' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        headers = {'Accept': 'unknown'}
        response, content = http.request(path, 'GET', headers=headers)
        self.assertEqual(300, response.status)
        self.assertEqual(self.versions_json, content)

    def test_get_root_path_with_openstack_header(self):
        """Assert GET / with an Accept: application/vnd.openstack.subjects-v1
        Verify empty subject list returned
        """
        path = 'http://%s:%d/subjects' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        headers = {'Accept': 'application/vnd.openstack.subjects-v1'}
        response, content = http.request(path, 'GET', headers=headers)
        self.assertEqual(200, response.status)
        self.assertEqual(self.subjects_json, content)

    def test_get_subjects_path_with_openstack_header(self):
        """Assert GET /subjects with a
        `Accept: application/vnd.openstack.compute-v1` header.
        Verify version choices returned. Verify message in API log
        about unknown accept header.
        """
        path = 'http://%s:%d/subjects' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        headers = {'Accept': 'application/vnd.openstack.compute-v1'}
        response, content = http.request(path, 'GET', headers=headers)
        self.assertEqual(300, response.status)
        self.assertEqual(self.versions_json, content)

    def test_get_v10_subjects_path(self):
        """Assert GET /v1.0/subjects with no Accept: header
        Verify version choices returned
        """
        path = 'http://%s:%d/v1.a/subjects' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(300, response.status)

    def test_get_v1a_subjects_path(self):
        """Assert GET /v1.a/subjects with no Accept: header
        Verify version choices returned
        """
        path = 'http://%s:%d/v1.a/subjects' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(300, response.status)

    def test_get_va1_subjects_path(self):
        """Assert GET /va.1/subjects with no Accept: header
        Verify version choices returned
        """
        path = 'http://%s:%d/va.1/subjects' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(300, response.status)
        self.assertEqual(self.versions_json, content)

    def test_get_versions_path(self):
        """Assert GET /versions with no Accept: header
        Verify version choices returned
        """
        path = 'http://%s:%d/versions' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual(self.versions_json, content)

    def test_get_versions_path_with_openstack_header(self):
        """Assert GET /versions with the
        `Accept: application/vnd.openstack.subjects-v1` header.
        Verify version choices returned.
        """
        path = 'http://%s:%d/versions' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        headers = {'Accept': 'application/vnd.openstack.subjects-v1'}
        response, content = http.request(path, 'GET', headers=headers)
        self.assertEqual(200, response.status)
        self.assertEqual(self.versions_json, content)

    def test_get_v1_versions_path(self):
        """Assert GET /v1/versions with `no Accept:` header
        Verify 404 returned
        """
        path = 'http://%s:%d/v1/versions' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(404, response.status)

    def test_get_versions_choices(self):
        """Verify version choices returned"""
        path = 'http://%s:%d/v10' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(300, response.status)
        self.assertEqual(self.versions_json, content)

    def test_get_subjects_path_with_openstack_v2_header(self):
        """Assert GET /subjects with a
        `Accept: application/vnd.openstack.compute-v1` header.
        Verify version choices returned. Verify message in API log
        about unknown version in accept header.
        """
        path = 'http://%s:%d/subjects' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        headers = {'Accept': 'application/vnd.openstack.subjects-v10'}
        response, content = http.request(path, 'GET', headers=headers)
        self.assertEqual(300, response.status)
        self.assertEqual(self.versions_json, content)

    def test_get_v12_subjects_path(self):
        """Assert GET /v1.2/subjects with `no Accept:` header
        Verify version choices returned
        """
        path = 'http://%s:%d/v1.2/subjects' % ('127.0.0.1', self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(300, response.status)
        self.assertEqual(self.versions_json, content)
