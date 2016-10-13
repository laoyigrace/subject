# Copyright 2011 OpenStack Foundation
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
import hashlib
import os

import httplib2
from oslo_serialization import jsonutils
from oslo_utils import units

from subject.tests import functional
from subject.tests.utils import minimal_headers

FIVE_KB = 5 * units.Ki
FIVE_GB = 5 * units.Gi


class TestMiscellaneous(functional.FunctionalTest):

    """Some random tests for various bugs and stuff"""

    def setUp(self):
        super(TestMiscellaneous, self).setUp()

        # NOTE(sirp): This is needed in case we are running the tests under an
        # environment in which OS_AUTH_STRATEGY=keystone. The test server we
        # spin up won't have keystone support, so we need to switch to the
        # NoAuth strategy.
        os.environ['OS_AUTH_STRATEGY'] = 'noauth'
        os.environ['OS_AUTH_URL'] = ''

    def test_api_response_when_subject_deleted_from_filesystem(self):
        """
        A test for LP bug #781410 -- subject should fail more gracefully
        on requests for subjects that have been removed from the fs
        """

        self.cleanup()
        self.start_servers()

        # 1. POST /subjects with public subject named Subject1
        # attribute and no custom properties. Verify a 200 OK is returned
        subject_data = "*" * FIVE_KB
        headers = minimal_headers('Subject1')
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=subject_data)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subject']['checksum'])
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("Subject1", data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])

        # 2. REMOVE the subject from the filesystem
        subject_path = "%s/subjects/%s" % (self.test_dir, data['subject']['id'])
        os.remove(subject_path)

        # 3. HEAD /subjects/1
        # Verify subject found now
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              data['subject']['id'])
        http = httplib2.Http()
        response, content = http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual("Subject1", response['x-subject-meta-name'])

        # 4. GET /subjects/1
        # Verify the api throws the appropriate 404 error
        path = "http://%s:%d/v1/subjects/1" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(404, response.status)

        self.stop_servers()

    def test_exception_not_eaten_from_registry_to_api(self):
        """
        A test for LP bug #704854 -- Exception thrown by registry
        server is consumed by API server.

        We start both servers daemonized.

        We then use Glance API to try adding an subject that does not
        meet validation requirements on the registry server and test
        that the error returned from the API server is appropriate
        """
        self.cleanup()
        self.start_servers()

        api_port = self.api_port
        path = 'http://127.0.0.1:%d/v1/subjects' % api_port

        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual('{"subjects": []}', content)

        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Name': 'SubjectName',
                   'X-Subject-Meta-Disk-Format': 'Invalid', }
        ignored, content = http.request(path, 'POST', headers=headers)

        self.assertIn('Invalid disk format', content,
                      "Could not find 'Invalid disk format' "
                      "in output: %s" % content)

        self.stop_servers()
