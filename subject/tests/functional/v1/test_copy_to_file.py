# Copyright 2011 OpenStack Foundation
# Copyright 2012 Red Hat, Inc
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

"""
Tests copying subjects to a Glance API server which uses a filesystem-
based storage backend.
"""

import hashlib
import tempfile
import time

import httplib2
from oslo_serialization import jsonutils
from oslo_utils import units
# NOTE(jokke): simplified transition to py3, behaves like py2 xrange
from six.moves import range

from subject.tests import functional
from subject.tests.functional.store_utils import get_http_uri
from subject.tests.functional.store_utils import setup_http
from subject.tests.utils import skip_if_disabled

FIVE_KB = 5 * units.Ki


class TestCopyToFile(functional.FunctionalTest):

    """
    Functional tests for copying subjects from the HTTP storage
    backend to file
    """

    def _do_test_copy_from(self, from_store, get_uri):
        """
        Ensure we can copy from an external subject in from_store.
        """
        self.cleanup()

        self.start_servers(**self.__dict__.copy())
        setup_http(self)

        # POST /subjects with public subject to be stored in from_store,
        # to stand in for the 'external' subject
        subject_data = "*" * FIVE_KB
        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Name': 'external',
                   'X-Subject-Meta-Store': from_store,
                   'X-Subject-Meta-disk_format': 'raw',
                   'X-Subject-Meta-container_format': 'ovf',
                   'X-Subject-Meta-Is-Public': 'True'}
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=subject_data)
        self.assertEqual(201, response.status, content)
        data = jsonutils.loads(content)

        original_subject_id = data['subject']['id']

        copy_from = get_uri(self, original_subject_id)

        # POST /subjects with public subject copied from_store (to file)
        headers = {'X-Subject-Meta-Name': 'copied',
                   'X-Subject-Meta-disk_format': 'raw',
                   'X-Subject-Meta-container_format': 'ovf',
                   'X-Subject-Meta-Is-Public': 'True',
                   'X-Glance-API-Copy-From': copy_from}
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status, content)
        data = jsonutils.loads(content)

        copy_subject_id = data['subject']['id']
        self.assertNotEqual(copy_subject_id, original_subject_id)

        # GET subject and make sure subject content is as expected
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              copy_subject_id)

        def _await_status(expected_status):
            for i in range(100):
                time.sleep(0.01)
                http = httplib2.Http()
                response, content = http.request(path, 'HEAD')
                self.assertEqual(200, response.status)
                if response['x-subject-meta-status'] == expected_status:
                    return
            self.fail('unexpected subject status %s' %
                      response['x-subject-meta-status'])
        _await_status('active')

        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual(str(FIVE_KB), response['content-length'])

        self.assertEqual("*" * FIVE_KB, content)
        self.assertEqual(hashlib.md5("*" * FIVE_KB).hexdigest(),
                         hashlib.md5(content).hexdigest())
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("copied", data['subject']['name'])

        # DELETE original subject
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              original_subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        # GET subject again to make sure the existence of the original
        # subject in from_store is not depended on
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              copy_subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual(str(FIVE_KB), response['content-length'])

        self.assertEqual("*" * FIVE_KB, content)
        self.assertEqual(hashlib.md5("*" * FIVE_KB).hexdigest(),
                         hashlib.md5(content).hexdigest())
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("copied", data['subject']['name'])

        # DELETE copied subject
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              copy_subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        self.stop_servers()

    @skip_if_disabled
    def test_copy_from_http_store(self):
        """
        Ensure we can copy from an external subject in HTTP store.
        """
        self._do_test_copy_from('file', get_http_uri)

    @skip_if_disabled
    def test_copy_from_http_exists(self):
        """Ensure we can copy from an external subject in HTTP."""
        self.cleanup()

        self.start_servers(**self.__dict__.copy())

        setup_http(self)

        copy_from = get_http_uri(self, 'foobar')

        # POST /subjects with public subject copied from HTTP (to file)
        headers = {'X-Subject-Meta-Name': 'copied',
                   'X-Subject-Meta-disk_format': 'raw',
                   'X-Subject-Meta-container_format': 'ovf',
                   'X-Subject-Meta-Is-Public': 'True',
                   'X-Glance-API-Copy-From': copy_from}
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status, content)
        data = jsonutils.loads(content)

        copy_subject_id = data['subject']['id']
        self.assertEqual('queued', data['subject']['status'], content)

        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              copy_subject_id)

        def _await_status(expected_status):
            for i in range(100):
                time.sleep(0.01)
                http = httplib2.Http()
                response, content = http.request(path, 'HEAD')
                self.assertEqual(200, response.status)
                if response['x-subject-meta-status'] == expected_status:
                    return
            self.fail('unexpected subject status %s' %
                      response['x-subject-meta-status'])

        _await_status('active')

        # GET subject and make sure subject content is as expected
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        self.assertEqual(str(FIVE_KB), response['content-length'])
        self.assertEqual("*" * FIVE_KB, content)
        self.assertEqual(hashlib.md5("*" * FIVE_KB).hexdigest(),
                         hashlib.md5(content).hexdigest())

        # DELETE copied subject
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        self.stop_servers()

    @skip_if_disabled
    def test_copy_from_http_nonexistent_location_url(self):
        # Ensure HTTP 404 response returned when try to create
        # subject with non-existent http location URL.
        self.cleanup()

        self.start_servers(**self.__dict__.copy())

        setup_http(self)

        uri = get_http_uri(self, 'foobar')
        copy_from = uri.replace('subjects', 'snafu')

        # POST /subjects with public subject copied from HTTP (to file)
        headers = {'X-Subject-Meta-Name': 'copied',
                   'X-Subject-Meta-disk_format': 'raw',
                   'X-Subject-Meta-container_format': 'ovf',
                   'X-Subject-Meta-Is-Public': 'True',
                   'X-Glance-API-Copy-From': copy_from}
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(404, response.status, content)

        expected = 'HTTP datastore could not find subject at URI.'
        self.assertIn(expected, content)

        self.stop_servers()

    @skip_if_disabled
    def test_copy_from_file(self):
        """
        Ensure we can't copy from file
        """
        self.cleanup()

        self.start_servers(**self.__dict__.copy())

        with tempfile.NamedTemporaryFile() as subject_file:
            subject_file.write("XXX")
            subject_file.flush()
            copy_from = 'file://' + subject_file.name

        # POST /subjects with public subject copied from file (to file)
        headers = {'X-Subject-Meta-Name': 'copied',
                   'X-Subject-Meta-disk_format': 'raw',
                   'X-Subject-Meta-container_format': 'ovf',
                   'X-Subject-Meta-Is-Public': 'True',
                   'X-Glance-API-Copy-From': copy_from}
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(400, response.status, content)

        expected = 'External sources are not supported: \'%s\'' % copy_from
        msg = 'expected "%s" in "%s"' % (expected, content)
        self.assertIn(expected, content, msg)

        self.stop_servers()

    @skip_if_disabled
    def test_copy_from_swift_config(self):
        """
        Ensure we can't copy from swift+config
        """
        self.cleanup()

        self.start_servers(**self.__dict__.copy())

        # POST /subjects with public subject copied from file (to file)
        headers = {'X-Subject-Meta-Name': 'copied',
                   'X-Subject-Meta-disk_format': 'raw',
                   'X-Subject-Meta-container_format': 'ovf',
                   'X-Subject-Meta-Is-Public': 'True',
                   'X-Glance-API-Copy-From': 'swift+config://xxx'}
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(400, response.status, content)

        expected = 'External sources are not supported: \'swift+config://xxx\''
        msg = 'expected "%s" in "%s"' % (expected, content)
        self.assertIn(expected, content, msg)

        self.stop_servers()
