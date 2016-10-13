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

import datetime
import hashlib
import os
import tempfile

from oslo_serialization import jsonutils
from oslo_utils import units
import testtools

from subject.common import timeutils
from subject.tests.integration.legacy_functional import base
from subject.tests.utils import minimal_headers

FIVE_KB = 5 * units.Ki
FIVE_GB = 5 * units.Gi


class TestApi(base.ApiTest):
    def test_get_head_simple_post(self):
        # 0. GET /subjects
        # Verify no public subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual('{"subjects": []}', content)

        # 1. GET /subjects/detail
        # Verify no public subjects
        path = "/v1/subjects/detail"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual('{"subjects": []}', content)

        # 2. POST /subjects with public subject named Image1
        # attribute and no custom properties. Verify a 200 OK is returned
        subject_data = "*" * FIVE_KB
        headers = minimal_headers('Image1')
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers,
                                              body=subject_data)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subject']['checksum'])
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("Image1", data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])

        # 3. HEAD subject
        # Verify subject found now
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual("Image1", response['x-subject-meta-name'])

        # 4. GET subject
        # Verify all information on subject we just added is correct
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)

        expected_subject_headers = {
            'x-subject-meta-id': subject_id,
            'x-subject-meta-name': 'Image1',
            'x-subject-meta-is_public': 'True',
            'x-subject-meta-status': 'active',
            'x-subject-meta-disk_format': 'raw',
            'x-subject-meta-container_format': 'ovf',
            'x-subject-meta-size': str(FIVE_KB)}

        expected_std_headers = {
            'content-length': str(FIVE_KB),
            'content-type': 'application/octet-stream'}

        for expected_key, expected_value in expected_subject_headers.items():
            self.assertEqual(expected_value, response[expected_key],
                             "For key '%s' expected header value '%s'. "
                             "Got '%s'" % (expected_key,
                                           expected_value,
                                           response[expected_key]))

        for expected_key, expected_value in expected_std_headers.items():
            self.assertEqual(expected_value, response[expected_key],
                             "For key '%s' expected header value '%s'. "
                             "Got '%s'" % (expected_key,
                                           expected_value,
                                           response[expected_key]))

        self.assertEqual("*" * FIVE_KB, content)
        self.assertEqual(hashlib.md5("*" * FIVE_KB).hexdigest(),
                         hashlib.md5(content).hexdigest())

        # 5. GET /subjects
        # Verify no public subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)

        expected_result = {"subjects": [
            {"container_format": "ovf",
             "disk_format": "raw",
             "id": subject_id,
             "name": "Image1",
             "checksum": "c2e5db72bd7fd153f53ede5da5a06de3",
             "size": 5120}]}
        self.assertEqual(expected_result, jsonutils.loads(content))

        # 6. GET /subjects/detail
        # Verify subject and all its metadata
        path = "/v1/subjects/detail"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)

        expected_subject = {
            "status": "active",
            "name": "Image1",
            "deleted": False,
            "container_format": "ovf",
            "disk_format": "raw",
            "id": subject_id,
            "is_public": True,
            "deleted_at": None,
            "properties": {},
            "size": 5120}

        subject = jsonutils.loads(content)

        for expected_key, expected_value in expected_subject.items():
            self.assertEqual(expected_value, subject['subjects'][0][expected_key],
                             "For key '%s' expected header value '%s'. "
                             "Got '%s'" % (expected_key,
                                           expected_value,
                                           subject['subjects'][0][expected_key]))

        # 7. PUT subject with custom properties of "distro" and "arch"
        # Verify 200 returned
        headers = {'X-Subject-Meta-Property-Distro': 'Ubuntu',
                   'X-Subject-Meta-Property-Arch': 'x86_64'}
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT', headers=headers)
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual("x86_64", data['subject']['properties']['arch'])
        self.assertEqual("Ubuntu", data['subject']['properties']['distro'])

        # 8. GET /subjects/detail
        # Verify subject and all its metadata
        path = "/v1/subjects/detail"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)

        expected_subject = {
            "status": "active",
            "name": "Image1",
            "deleted": False,
            "container_format": "ovf",
            "disk_format": "raw",
            "id": subject_id,
            "is_public": True,
            "deleted_at": None,
            "properties": {'distro': 'Ubuntu', 'arch': 'x86_64'},
            "size": 5120}

        subject = jsonutils.loads(content)

        for expected_key, expected_value in expected_subject.items():
            self.assertEqual(expected_value, subject['subjects'][0][expected_key],
                             "For key '%s' expected header value '%s'. "
                             "Got '%s'" % (expected_key,
                                           expected_value,
                                           subject['subjects'][0][expected_key]))

        # 9. PUT subject and remove a previously existing property.
        headers = {'X-Subject-Meta-Property-Arch': 'x86_64'}
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT', headers=headers)
        self.assertEqual(200, response.status)

        path = "/v1/subjects/detail"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)['subjects'][0]
        self.assertEqual(1, len(data['properties']))
        self.assertEqual("x86_64", data['properties']['arch'])

        # 10. PUT subject and add a previously deleted property.
        headers = {'X-Subject-Meta-Property-Distro': 'Ubuntu',
                   'X-Subject-Meta-Property-Arch': 'x86_64'}
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT', headers=headers)
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)

        path = "/v1/subjects/detail"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)['subjects'][0]
        self.assertEqual(2, len(data['properties']))
        self.assertEqual("x86_64", data['properties']['arch'])
        self.assertEqual("Ubuntu", data['properties']['distro'])
        self.assertNotEqual(data['created_at'], data['updated_at'])

        # DELETE subject
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

    def test_queued_process_flow(self):
        """
        We test the process flow where a user registers an subject
        with Glance but does not immediately upload an subject file.
        Later, the user uploads an subject file using a PUT operation.
        We track the changing of subject status throughout this process.

        0. GET /subjects
        - Verify no public subjects
        1. POST /subjects with public subject named Image1 with no location
        attribute and no subject data.
        - Verify 201 returned
        2. GET /subjects
        - Verify one public subject
        3. HEAD subject
        - Verify subject now in queued status
        4. PUT subject with subject data
        - Verify 200 returned
        5. HEAD subjects
        - Verify subject now in active status
        6. GET /subjects
        - Verify one public subject
        """

        # 0. GET /subjects
        # Verify no public subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual('{"subjects": []}', content)

        # 1. POST /subjects with public subject named Image1
        # with no location or subject data
        headers = minimal_headers('Image1')
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        self.assertIsNone(data['subject']['checksum'])
        self.assertEqual(0, data['subject']['size'])
        self.assertEqual('ovf', data['subject']['container_format'])
        self.assertEqual('raw', data['subject']['disk_format'])
        self.assertEqual("Image1", data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])

        subject_id = data['subject']['id']

        # 2. GET /subjects
        # Verify 1 public subject
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(subject_id, data['subjects'][0]['id'])
        self.assertIsNone(data['subjects'][0]['checksum'])
        self.assertEqual(0, data['subjects'][0]['size'])
        self.assertEqual('ovf', data['subjects'][0]['container_format'])
        self.assertEqual('raw', data['subjects'][0]['disk_format'])
        self.assertEqual("Image1", data['subjects'][0]['name'])

        # 3. HEAD /subjects
        # Verify status is in queued
        path = "/v1/subjects/%s" % (subject_id)
        response, content = self.http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual("Image1", response['x-subject-meta-name'])
        self.assertEqual("queued", response['x-subject-meta-status'])
        self.assertEqual('0', response['x-subject-meta-size'])
        self.assertEqual(subject_id, response['x-subject-meta-id'])

        # 4. PUT subject with subject data, verify 200 returned
        subject_data = "*" * FIVE_KB
        headers = {'Content-Type': 'application/octet-stream'}
        path = "/v1/subjects/%s" % (subject_id)
        response, content = self.http.request(path, 'PUT', headers=headers,
                                              body=subject_data)
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subject']['checksum'])
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("Image1", data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])

        # 5. HEAD /subjects
        # Verify status is in active
        path = "/v1/subjects/%s" % (subject_id)
        response, content = self.http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual("Image1", response['x-subject-meta-name'])
        self.assertEqual("active", response['x-subject-meta-status'])

        # 6. GET /subjects
        # Verify 1 public subject still...
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subjects'][0]['checksum'])
        self.assertEqual(subject_id, data['subjects'][0]['id'])
        self.assertEqual(FIVE_KB, data['subjects'][0]['size'])
        self.assertEqual('ovf', data['subjects'][0]['container_format'])
        self.assertEqual('raw', data['subjects'][0]['disk_format'])
        self.assertEqual("Image1", data['subjects'][0]['name'])

        # DELETE subject
        path = "/v1/subjects/%s" % (subject_id)
        response, content = self.http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

    def test_v1_not_enabled(self):
        self.config(enable_v1_api=False)
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(300, response.status)

    def test_v1_enabled(self):
        self.config(enable_v1_api=True)
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)

    def test_zero_initial_size(self):
        """
        A test to ensure that an subject with size explicitly set to zero
        has status that immediately transitions to active.
        """
        # 1. POST /subjects with public subject named Image1
        # attribute and a size of zero.
        # Verify a 201 OK is returned
        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Size': '0',
                   'X-Subject-Meta-Name': 'Image1',
                   'X-Subject-Meta-disk_format': 'raw',
                   'X-subject-Meta-container_format': 'ovf',
                   'X-Subject-Meta-Is-Public': 'True'}
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        subject = jsonutils.loads(content)['subject']
        self.assertEqual('active', subject['status'])

        # 2. HEAD subject-location
        # Verify subject size is zero and the status is active
        path = response.get('location')
        response, content = self.http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual('0', response['x-subject-meta-size'])
        self.assertEqual('active', response['x-subject-meta-status'])

        # 3. GET  subject-location
        # Verify subject content is empty
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual(0, len(content))

    def test_traceback_not_consumed(self):
        """
        A test that errors coming from the POST API do not
        get consumed and print the actual error message, and
        not something like &lt;traceback object at 0x1918d40&gt;

        :see https://bugs.launchpad.net/subject/+bug/755912
        """
        # POST /subjects with binary data, but not setting
        # Content-Type to application/octet-stream, verify a
        # 400 returned and that the error is readable.
        with tempfile.NamedTemporaryFile() as test_data_file:
            test_data_file.write("XXX")
            test_data_file.flush()
        path = "/v1/subjects"
        headers = minimal_headers('Image1')
        headers['Content-Type'] = 'not octet-stream'
        response, content = self.http.request(path, 'POST',
                                              body=test_data_file.name,
                                              headers=headers)
        self.assertEqual(400, response.status)
        expected = "Content-Type must be application/octet-stream"
        self.assertIn(expected, content,
                      "Could not find '%s' in '%s'" % (expected, content))

    def test_filtered_subjects(self):
        """
        Set up four test subjects and ensure each query param filter works
        """

        # 0. GET /subjects
        # Verify no public subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual('{"subjects": []}', content)

        subject_ids = []

        # 1. POST /subjects with three public subjects, and one private subject
        # with various attributes
        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Name': 'Image1',
                   'X-Subject-Meta-Status': 'active',
                   'X-Subject-Meta-Container-Format': 'ovf',
                   'X-Subject-Meta-Disk-Format': 'vdi',
                   'X-Subject-Meta-Size': '19',
                   'X-Subject-Meta-Is-Public': 'True',
                   'X-Subject-Meta-Protected': 'True',
                   'X-Subject-Meta-Property-pants': 'are on'}
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        self.assertEqual("are on", data['subject']['properties']['pants'])
        self.assertTrue(data['subject']['is_public'])
        subject_ids.append(data['subject']['id'])

        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Name': 'My Subject!',
                   'X-Subject-Meta-Status': 'active',
                   'X-Subject-Meta-Container-Format': 'ovf',
                   'X-Subject-Meta-Disk-Format': 'vhd',
                   'X-Subject-Meta-Size': '20',
                   'X-Subject-Meta-Is-Public': 'True',
                   'X-Subject-Meta-Protected': 'False',
                   'X-Subject-Meta-Property-pants': 'are on'}
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        self.assertEqual("are on", data['subject']['properties']['pants'])
        self.assertTrue(data['subject']['is_public'])
        subject_ids.append(data['subject']['id'])

        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Name': 'My Subject!',
                   'X-Subject-Meta-Status': 'saving',
                   'X-Subject-Meta-Container-Format': 'ami',
                   'X-Subject-Meta-Disk-Format': 'ami',
                   'X-Subject-Meta-Size': '21',
                   'X-Subject-Meta-Is-Public': 'True',
                   'X-Subject-Meta-Protected': 'False',
                   'X-Subject-Meta-Property-pants': 'are off'}
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        self.assertEqual("are off", data['subject']['properties']['pants'])
        self.assertTrue(data['subject']['is_public'])
        subject_ids.append(data['subject']['id'])

        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Name': 'My Private Subject',
                   'X-Subject-Meta-Status': 'active',
                   'X-Subject-Meta-Container-Format': 'ami',
                   'X-Subject-Meta-Disk-Format': 'ami',
                   'X-Subject-Meta-Size': '22',
                   'X-Subject-Meta-Is-Public': 'False',
                   'X-Subject-Meta-Protected': 'False'}
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        self.assertFalse(data['subject']['is_public'])
        subject_ids.append(data['subject']['id'])

        # 2. GET /subjects
        # Verify three public subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(3, len(data['subjects']))

        # 3. GET /subjects with name filter
        # Verify correct subjects returned with name
        params = "name=My%20Image!"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(2, len(data['subjects']))
        for subject in data['subjects']:
            self.assertEqual("My Subject!", subject['name'])

        # 4. GET /subjects with status filter
        # Verify correct subjects returned with status
        params = "status=queued"
        path = "/v1/subjects/detail?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(3, len(data['subjects']))
        for subject in data['subjects']:
            self.assertEqual("queued", subject['status'])

        params = "status=active"
        path = "/v1/subjects/detail?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(0, len(data['subjects']))

        # 5. GET /subjects with container_format filter
        # Verify correct subjects returned with container_format
        params = "container_format=ovf"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(2, len(data['subjects']))
        for subject in data['subjects']:
            self.assertEqual("ovf", subject['container_format'])

        # 6. GET /subjects with disk_format filter
        # Verify correct subjects returned with disk_format
        params = "disk_format=vdi"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(1, len(data['subjects']))
        for subject in data['subjects']:
            self.assertEqual("vdi", subject['disk_format'])

        # 7. GET /subjects with size_max filter
        # Verify correct subjects returned with size <= expected
        params = "size_max=20"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(2, len(data['subjects']))
        for subject in data['subjects']:
            self.assertLessEqual(subject['size'], 20)

        # 8. GET /subjects with size_min filter
        # Verify correct subjects returned with size >= expected
        params = "size_min=20"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(2, len(data['subjects']))
        for subject in data['subjects']:
            self.assertGreaterEqual(subject['size'], 20)

        # 9. Get /subjects with is_public=None filter
        # Verify correct subjects returned with property
        # Bug lp:803656  Support is_public in filtering
        params = "is_public=None"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(4, len(data['subjects']))

        # 10. Get /subjects with is_public=False filter
        # Verify correct subjects returned with property
        # Bug lp:803656  Support is_public in filtering
        params = "is_public=False"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(1, len(data['subjects']))
        for subject in data['subjects']:
            self.assertEqual("My Private Subject", subject['name'])

        # 11. Get /subjects with is_public=True filter
        # Verify correct subjects returned with property
        # Bug lp:803656  Support is_public in filtering
        params = "is_public=True"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(3, len(data['subjects']))
        for subject in data['subjects']:
            self.assertNotEqual(subject['name'], "My Private Subject")

        # 12. Get /subjects with protected=False filter
        # Verify correct subjects returned with property
        params = "protected=False"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(2, len(data['subjects']))
        for subject in data['subjects']:
            self.assertNotEqual(subject['name'], "Image1")

        # 13. Get /subjects with protected=True filter
        # Verify correct subjects returned with property
        params = "protected=True"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(1, len(data['subjects']))
        for subject in data['subjects']:
            self.assertEqual("Image1", subject['name'])

        # 14. GET /subjects with property filter
        # Verify correct subjects returned with property
        params = "property-pants=are%20on"
        path = "/v1/subjects/detail?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(2, len(data['subjects']))
        for subject in data['subjects']:
            self.assertEqual("are on", subject['properties']['pants'])

        # 15. GET /subjects with property filter and name filter
        # Verify correct subjects returned with property and name
        # Make sure you quote the url when using more than one param!
        params = "name=My%20Image!&property-pants=are%20on"
        path = "/v1/subjects/detail?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(1, len(data['subjects']))
        for subject in data['subjects']:
            self.assertEqual("are on", subject['properties']['pants'])
            self.assertEqual("My Subject!", subject['name'])

        # 16. GET /subjects with past changes-since filter
        yesterday = timeutils.isotime(timeutils.utcnow() -
                                      datetime.timedelta(1))
        params = "changes-since=%s" % yesterday
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(3, len(data['subjects']))

        # one timezone west of Greenwich equates to an hour ago
        # taking care to pre-urlencode '+' as '%2B', otherwise the timezone
        # '+' is wrongly decoded as a space
        # TODO(eglynn): investigate '+' --> <SPACE> decoding, an artifact
        # of WSGI/webob dispatch?
        now = timeutils.utcnow()
        hour_ago = now.strftime('%Y-%m-%dT%H:%M:%S%%2B01:00')
        params = "changes-since=%s" % hour_ago
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(3, len(data['subjects']))

        # 17. GET /subjects with future changes-since filter
        tomorrow = timeutils.isotime(timeutils.utcnow() +
                                     datetime.timedelta(1))
        params = "changes-since=%s" % tomorrow
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(0, len(data['subjects']))

        # one timezone east of Greenwich equates to an hour from now
        now = timeutils.utcnow()
        hour_hence = now.strftime('%Y-%m-%dT%H:%M:%S-01:00')
        params = "changes-since=%s" % hour_hence
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(0, len(data['subjects']))

        # 18. GET /subjects with size_min filter
        # Verify correct subjects returned with size >= expected
        params = "size_min=-1"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(400, response.status)
        self.assertIn("filter size_min got -1", content)

        # 19. GET /subjects with size_min filter
        # Verify correct subjects returned with size >= expected
        params = "size_max=-1"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(400, response.status)
        self.assertIn("filter size_max got -1", content)

        # 20. GET /subjects with size_min filter
        # Verify correct subjects returned with size >= expected
        params = "min_ram=-1"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(400, response.status)
        self.assertIn("Bad value passed to filter min_ram got -1", content)

        # 21. GET /subjects with size_min filter
        # Verify correct subjects returned with size >= expected
        params = "protected=imalittleteapot"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(400, response.status)
        self.assertIn("protected got imalittleteapot", content)

        # 22. GET /subjects with size_min filter
        # Verify correct subjects returned with size >= expected
        params = "is_public=imalittleteapot"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(400, response.status)
        self.assertIn("is_public got imalittleteapot", content)

    def test_limited_subjects(self):
        """
        Ensure marker and limit query params work
        """

        # 0. GET /subjects
        # Verify no public subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual('{"subjects": []}', content)

        subject_ids = []

        # 1. POST /subjects with three public subjects with various attributes
        headers = minimal_headers('Image1')
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        subject_ids.append(jsonutils.loads(content)['subject']['id'])

        headers = minimal_headers('Image2')
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        subject_ids.append(jsonutils.loads(content)['subject']['id'])

        headers = minimal_headers('Image3')
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        subject_ids.append(jsonutils.loads(content)['subject']['id'])

        # 2. GET /subjects with all subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        subjects = jsonutils.loads(content)['subjects']
        self.assertEqual(3, len(subjects))

        # 3. GET /subjects with limit of 2
        # Verify only two subjects were returned
        params = "limit=2"
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)['subjects']
        self.assertEqual(2, len(data))
        self.assertEqual(subjects[0]['id'], data[0]['id'])
        self.assertEqual(subjects[1]['id'], data[1]['id'])

        # 4. GET /subjects with marker
        # Verify only two subjects were returned
        params = "marker=%s" % subjects[0]['id']
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)['subjects']
        self.assertEqual(2, len(data))
        self.assertEqual(subjects[1]['id'], data[0]['id'])
        self.assertEqual(subjects[2]['id'], data[1]['id'])

        # 5. GET /subjects with marker and limit
        # Verify only one subject was returned with the correct id
        params = "limit=1&marker=%s" % subjects[1]['id']
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)['subjects']
        self.assertEqual(1, len(data))
        self.assertEqual(subjects[2]['id'], data[0]['id'])

        # 6. GET /subjects/detail with marker and limit
        # Verify only one subject was returned with the correct id
        params = "limit=1&marker=%s" % subjects[1]['id']
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)['subjects']
        self.assertEqual(1, len(data))
        self.assertEqual(subjects[2]['id'], data[0]['id'])

        # DELETE subjects
        for subject_id in subject_ids:
            path = "/v1/subjects/%s" % (subject_id)
            response, content = self.http.request(path, 'DELETE')
            self.assertEqual(200, response.status)

    def test_ordered_subjects(self):
        """
        Set up three test subjects and ensure each query param filter works
        """
        # 0. GET /subjects
        # Verify no public subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual('{"subjects": []}', content)

        # 1. POST /subjects with three public subjects with various attributes
        subject_ids = []
        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Name': 'Image1',
                   'X-Subject-Meta-Status': 'active',
                   'X-Subject-Meta-Container-Format': 'ovf',
                   'X-Subject-Meta-Disk-Format': 'vdi',
                   'X-Subject-Meta-Size': '19',
                   'X-Subject-Meta-Is-Public': 'True'}
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        subject_ids.append(jsonutils.loads(content)['subject']['id'])

        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Name': 'ASDF',
                   'X-Subject-Meta-Status': 'active',
                   'X-Subject-Meta-Container-Format': 'bare',
                   'X-Subject-Meta-Disk-Format': 'iso',
                   'X-Subject-Meta-Size': '2',
                   'X-Subject-Meta-Is-Public': 'True'}
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        subject_ids.append(jsonutils.loads(content)['subject']['id'])

        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Name': 'XYZ',
                   'X-Subject-Meta-Status': 'saving',
                   'X-Subject-Meta-Container-Format': 'ami',
                   'X-Subject-Meta-Disk-Format': 'ami',
                   'X-Subject-Meta-Size': '5',
                   'X-Subject-Meta-Is-Public': 'True'}
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        subject_ids.append(jsonutils.loads(content)['subject']['id'])

        # 2. GET /subjects with no query params
        # Verify three public subjects sorted by created_at desc
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(3, len(data['subjects']))
        self.assertEqual(subject_ids[2], data['subjects'][0]['id'])
        self.assertEqual(subject_ids[1], data['subjects'][1]['id'])
        self.assertEqual(subject_ids[0], data['subjects'][2]['id'])

        # 3. GET /subjects sorted by name asc
        params = 'sort_key=name&sort_dir=asc'
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(3, len(data['subjects']))
        self.assertEqual(subject_ids[1], data['subjects'][0]['id'])
        self.assertEqual(subject_ids[0], data['subjects'][1]['id'])
        self.assertEqual(subject_ids[2], data['subjects'][2]['id'])

        # 4. GET /subjects sorted by size desc
        params = 'sort_key=size&sort_dir=desc'
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(3, len(data['subjects']))
        self.assertEqual(subject_ids[0], data['subjects'][0]['id'])
        self.assertEqual(subject_ids[2], data['subjects'][1]['id'])
        self.assertEqual(subject_ids[1], data['subjects'][2]['id'])

        # 5. GET /subjects sorted by size desc with a marker
        params = 'sort_key=size&sort_dir=desc&marker=%s' % subject_ids[0]
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(2, len(data['subjects']))
        self.assertEqual(subject_ids[2], data['subjects'][0]['id'])
        self.assertEqual(subject_ids[1], data['subjects'][1]['id'])

        # 6. GET /subjects sorted by name asc with a marker
        params = 'sort_key=name&sort_dir=asc&marker=%s' % subject_ids[2]
        path = "/v1/subjects?%s" % (params)
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(0, len(data['subjects']))

        # DELETE subjects
        for subject_id in subject_ids:
            path = "/v1/subjects/%s" % (subject_id)
            response, content = self.http.request(path, 'DELETE')
            self.assertEqual(200, response.status)

    def test_duplicate_subject_upload(self):
        """
        Upload initial subject, then attempt to upload duplicate subject
        """
        # 0. GET /subjects
        # Verify no public subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual('{"subjects": []}', content)

        # 1. POST /subjects with public subject named Image1
        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Name': 'Image1',
                   'X-Subject-Meta-Status': 'active',
                   'X-Subject-Meta-Container-Format': 'ovf',
                   'X-Subject-Meta-Disk-Format': 'vdi',
                   'X-Subject-Meta-Size': '19',
                   'X-Subject-Meta-Is-Public': 'True'}
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)

        subject = jsonutils.loads(content)['subject']

        # 2. POST /subjects with public subject named Image1, and ID: 1
        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Name': 'Image1 Update',
                   'X-Subject-Meta-Status': 'active',
                   'X-Subject-Meta-Container-Format': 'ovf',
                   'X-Subject-Meta-Disk-Format': 'vdi',
                   'X-Subject-Meta-Size': '19',
                   'X-Subject-Meta-Id': subject['id'],
                   'X-Subject-Meta-Is-Public': 'True'}
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(409, response.status)

    def test_delete_not_existing(self):
        """
        We test the following:

        0. GET /subjects/1
        - Verify 404
        1. DELETE /subjects/1
        - Verify 404
        """

        # 0. GET /subjects
        # Verify no public subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual('{"subjects": []}', content)

        # 1. DELETE /subjects/1
        # Verify 404 returned
        path = "/v1/subjects/1"
        response, content = self.http.request(path, 'DELETE')
        self.assertEqual(404, response.status)

    def _do_test_post_subject_content_bad_format(self, format):
        """
        We test that missing container/disk format fails with 400 "Bad Request"

        :see https://bugs.launchpad.net/subject/+bug/933702
        """

        # Verify no public subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        subjects = jsonutils.loads(content)['subjects']
        self.assertEqual(0, len(subjects))

        path = "/v1/subjects"

        # POST /subjects without given format being specified
        headers = minimal_headers('Image1')
        headers['X-Subject-Meta-' + format] = 'bad_value'
        with tempfile.NamedTemporaryFile() as test_data_file:
            test_data_file.write("XXX")
            test_data_file.flush()
        response, content = self.http.request(path, 'POST',
                                              headers=headers,
                                              body=test_data_file.name)
        self.assertEqual(400, response.status)
        type = format.replace('_format', '')
        expected = "Invalid %s format 'bad_value' for subject" % type
        self.assertIn(expected, content,
                      "Could not find '%s' in '%s'" % (expected, content))

        # make sure the subject was not created
        # Verify no public subjects
        path = "/v1/subjects"
        response, content = self.http.request(path, 'GET')
        self.assertEqual(200, response.status)
        subjects = jsonutils.loads(content)['subjects']
        self.assertEqual(0, len(subjects))

    def test_post_subject_content_bad_container_format(self):
        self._do_test_post_subject_content_bad_format('container_format')

    def test_post_subject_content_bad_disk_format(self):
        self._do_test_post_subject_content_bad_format('disk_format')

    def _do_test_put_subject_content_missing_format(self, format):
        """
        We test that missing container/disk format only fails with
        400 "Bad Request" when the subject content is PUT (i.e. not
        on the original POST of a queued subject).

        :see https://bugs.launchpad.net/subject/+bug/937216
        """

        # POST queued subject
        path = "/v1/subjects"
        headers = {
            'X-Subject-Meta-Name': 'Image1',
            'X-Subject-Meta-Is-Public': 'True',
        }
        response, content = self.http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']
        self.addDetail('subject_data', testtools.content.json_content(data))

        # PUT subject content subjects without given format being specified
        path = "/v1/subjects/%s" % (subject_id)
        headers = minimal_headers('Image1')
        del headers['X-Subject-Meta-' + format]
        with tempfile.NamedTemporaryFile() as test_data_file:
            test_data_file.write("XXX")
            test_data_file.flush()
        response, content = self.http.request(path, 'PUT',
                                              headers=headers,
                                              body=test_data_file.name)
        self.assertEqual(400, response.status)
        type = format.replace('_format', '').capitalize()
        expected = "%s format is not specified" % type
        self.assertIn(expected, content,
                      "Could not find '%s' in '%s'" % (expected, content))

    def test_put_subject_content_bad_container_format(self):
        self._do_test_put_subject_content_missing_format('container_format')

    def test_put_subject_content_bad_disk_format(self):
        self._do_test_put_subject_content_missing_format('disk_format')

    def _do_test_mismatched_attribute(self, attribute, value):
        """
        Test mismatched attribute.
        """

        subject_data = "*" * FIVE_KB
        headers = minimal_headers('Image1')
        headers[attribute] = value
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST', headers=headers,
                                              body=subject_data)
        self.assertEqual(400, response.status)

        subjects_dir = os.path.join(self.test_dir, 'subjects')
        subject_count = len([name for name in os.listdir(subjects_dir)
                           if os.path.isfile(os.path.join(subjects_dir, name))])
        self.assertEqual(0, subject_count)

    def test_mismatched_size(self):
        """
        Test mismatched size.
        """
        self._do_test_mismatched_attribute('x-subject-meta-size',
                                           str(FIVE_KB + 1))

    def test_mismatched_checksum(self):
        """
        Test mismatched checksum.
        """
        self._do_test_mismatched_attribute('x-subject-meta-checksum',
                                           'foobar')


class TestApiWithFakeAuth(base.ApiTest):
    def __init__(self, *args, **kwargs):
        super(TestApiWithFakeAuth, self).__init__(*args, **kwargs)
        self.api_flavor = 'fakeauth'
        self.registry_flavor = 'fakeauth'

    def test_ownership(self):
        # Add an subject with admin privileges and ensure the owner
        # can be set to something other than what was used to authenticate
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }

        create_headers = {
            'X-Subject-Meta-Name': 'MyImage',
            'X-Subject-Meta-disk_format': 'raw',
            'X-Subject-Meta-container_format': 'ovf',
            'X-Subject-Meta-Is-Public': 'True',
            'X-Subject-Meta-Owner': 'tenant2',
        }
        create_headers.update(auth_headers)

        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST',
                                              headers=create_headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']

        path = "/v1/subjects/%s" % (subject_id)
        response, content = self.http.request(path, 'HEAD',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        self.assertEqual('tenant2', response['x-subject-meta-owner'])

        # Now add an subject without admin privileges and ensure the owner
        # cannot be set to something other than what was used to authenticate
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:role1',
        }
        create_headers.update(auth_headers)

        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST',
                                              headers=create_headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']

        # We have to be admin to see the owner
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        create_headers.update(auth_headers)

        path = "/v1/subjects/%s" % (subject_id)
        response, content = self.http.request(path, 'HEAD',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        self.assertEqual('tenant1', response['x-subject-meta-owner'])

        # Make sure the non-privileged user can't update their owner either
        update_headers = {
            'X-Subject-Meta-Name': 'MyImage2',
            'X-Subject-Meta-Owner': 'tenant2',
            'X-Auth-Token': 'user1:tenant1:role1',
        }

        path = "/v1/subjects/%s" % (subject_id)
        response, content = self.http.request(path, 'PUT',
                                              headers=update_headers)
        self.assertEqual(200, response.status)

        # We have to be admin to see the owner
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }

        path = "/v1/subjects/%s" % (subject_id)
        response, content = self.http.request(path, 'HEAD',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        self.assertEqual('tenant1', response['x-subject-meta-owner'])

        # An admin user should be able to update the owner
        auth_headers = {
            'X-Auth-Token': 'user1:tenant3:admin',
        }

        update_headers = {
            'X-Subject-Meta-Name': 'MyImage2',
            'X-Subject-Meta-Owner': 'tenant2',
        }
        update_headers.update(auth_headers)

        path = "/v1/subjects/%s" % (subject_id)
        response, content = self.http.request(path, 'PUT',
                                              headers=update_headers)
        self.assertEqual(200, response.status)

        path = "/v1/subjects/%s" % (subject_id)
        response, content = self.http.request(path, 'HEAD',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        self.assertEqual('tenant2', response['x-subject-meta-owner'])

    def test_subject_visibility_to_different_users(self):
        owners = ['admin', 'tenant1', 'tenant2', 'none']
        visibilities = {'public': 'True', 'private': 'False'}
        subject_ids = {}

        for owner in owners:
            for visibility, is_public in visibilities.items():
                name = '%s-%s' % (owner, visibility)
                headers = {
                    'Content-Type': 'application/octet-stream',
                    'X-Subject-Meta-Name': name,
                    'X-Subject-Meta-Status': 'active',
                    'X-Subject-Meta-Is-Public': is_public,
                    'X-Subject-Meta-Owner': owner,
                    'X-Auth-Token': 'createuser:createtenant:admin',
                }
                path = "/v1/subjects"
                response, content = self.http.request(path, 'POST',
                                                      headers=headers)
                self.assertEqual(201, response.status)
                data = jsonutils.loads(content)
                subject_ids[name] = data['subject']['id']

        def list_subjects(tenant, role='', is_public=None):
            auth_token = 'user:%s:%s' % (tenant, role)
            headers = {'X-Auth-Token': auth_token}
            path = "/v1/subjects/detail"
            if is_public is not None:
                path += '?is_public=%s' % is_public
            response, content = self.http.request(path, 'GET', headers=headers)
            self.assertEqual(200, response.status)
            return jsonutils.loads(content)['subjects']

        # 1. Known user sees public and their own subjects
        subjects = list_subjects('tenant1')
        self.assertEqual(5, len(subjects))
        for subject in subjects:
            self.assertTrue(subject['is_public'] or subject['owner'] == 'tenant1')

        # 2. Unknown user sees only public subjects
        subjects = list_subjects('none')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertTrue(subject['is_public'])

        # 3. Unknown admin sees only public subjects
        subjects = list_subjects('none', role='admin')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertTrue(subject['is_public'])

        # 4. Unknown admin, is_public=none, shows all subjects
        subjects = list_subjects('none', role='admin', is_public='none')
        self.assertEqual(8, len(subjects))

        # 5. Unknown admin, is_public=true, shows only public subjects
        subjects = list_subjects('none', role='admin', is_public='true')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertTrue(subject['is_public'])

        # 6. Unknown admin, is_public=false, sees only private subjects
        subjects = list_subjects('none', role='admin', is_public='false')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertFalse(subject['is_public'])

        # 7. Known admin sees public and their own subjects
        subjects = list_subjects('admin', role='admin')
        self.assertEqual(5, len(subjects))
        for subject in subjects:
            self.assertTrue(subject['is_public'] or subject['owner'] == 'admin')

        # 8. Known admin, is_public=none, shows all subjects
        subjects = list_subjects('admin', role='admin', is_public='none')
        self.assertEqual(8, len(subjects))

        # 9. Known admin, is_public=true, sees all public and their subjects
        subjects = list_subjects('admin', role='admin', is_public='true')
        self.assertEqual(5, len(subjects))
        for subject in subjects:
            self.assertTrue(subject['is_public'] or subject['owner'] == 'admin')

        # 10. Known admin, is_public=false, sees all private subjects
        subjects = list_subjects('admin', role='admin', is_public='false')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertFalse(subject['is_public'])

    def test_property_protections(self):
        # Enable property protection
        self.config(property_protection_file=self.property_file)
        self.init()

        CREATE_HEADERS = {
            'X-Subject-Meta-Name': 'MyImage',
            'X-Subject-Meta-disk_format': 'raw',
            'X-Subject-Meta-container_format': 'ovf',
            'X-Subject-Meta-Is-Public': 'True',
            'X-Subject-Meta-Owner': 'tenant2',
        }

        # Create an subject for role member with extra properties
        # Raises 403 since user is not allowed to create 'foo'
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:member',
        }
        custom_props = {
            'x-subject-meta-property-foo': 'bar'
        }
        auth_headers.update(custom_props)
        auth_headers.update(CREATE_HEADERS)
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST',
                                              headers=auth_headers)
        self.assertEqual(403, response.status)

        # Create an subject for role member without 'foo'
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:member',
        }
        custom_props = {
            'x-subject-meta-property-x_owner_foo': 'o_s_bar',
        }
        auth_headers.update(custom_props)
        auth_headers.update(CREATE_HEADERS)
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST',
                                              headers=auth_headers)
        self.assertEqual(201, response.status)

        # Returned subject entity should have 'x_owner_foo'
        data = jsonutils.loads(content)
        self.assertEqual('o_s_bar',
                         data['subject']['properties']['x_owner_foo'])

        # Create an subject for role spl_role with extra properties
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:spl_role',
        }
        custom_props = {
            'X-Subject-Meta-Property-spl_create_prop': 'create_bar',
            'X-Subject-Meta-Property-spl_read_prop': 'read_bar',
            'X-Subject-Meta-Property-spl_update_prop': 'update_bar',
            'X-Subject-Meta-Property-spl_delete_prop': 'delete_bar'
        }
        auth_headers.update(custom_props)
        auth_headers.update(CREATE_HEADERS)
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST',
                                              headers=auth_headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']

        # Attempt to update two properties, one protected(spl_read_prop), the
        # other not(spl_update_prop).  Request should be forbidden.
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:spl_role',
        }
        custom_props = {
            'X-Subject-Meta-Property-spl_read_prop': 'r',
            'X-Subject-Meta-Property-spl_update_prop': 'u',
            'X-Glance-Registry-Purge-Props': 'False'
        }
        auth_headers.update(auth_headers)
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(403, response.status)

        # Attempt to create properties which are forbidden
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:spl_role',
        }
        custom_props = {
            'X-Subject-Meta-Property-spl_new_prop': 'new',
            'X-Glance-Registry-Purge-Props': 'True'
        }
        auth_headers.update(auth_headers)
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(403, response.status)

        # Attempt to update, create and delete properties
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:spl_role',
        }
        custom_props = {
            'X-Subject-Meta-Property-spl_create_prop': 'create_bar',
            'X-Subject-Meta-Property-spl_read_prop': 'read_bar',
            'X-Subject-Meta-Property-spl_update_prop': 'u',
            'X-Glance-Registry-Purge-Props': 'True'
        }
        auth_headers.update(auth_headers)
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)

        # Returned subject entity should reflect the changes
        subject = jsonutils.loads(content)

        # 'spl_update_prop' has update permission for spl_role
        # hence the value has changed
        self.assertEqual('u', subject['subject']['properties']['spl_update_prop'])

        # 'spl_delete_prop' has delete permission for spl_role
        # hence the property has been deleted
        self.assertNotIn('spl_delete_prop', subject['subject']['properties'])

        # 'spl_create_prop' has create permission for spl_role
        # hence the property has been created
        self.assertEqual('create_bar',
                         subject['subject']['properties']['spl_create_prop'])

        # Subject Deletion should work
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:spl_role',
        }
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'DELETE',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)

        # This subject should be no longer be directly accessible
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:spl_role',
        }
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'HEAD',
                                              headers=auth_headers)
        self.assertEqual(404, response.status)

    def test_property_protections_special_chars(self):
        # Enable property protection
        self.config(property_protection_file=self.property_file)
        self.init()

        CREATE_HEADERS = {
            'X-Subject-Meta-Name': 'MyImage',
            'X-Subject-Meta-disk_format': 'raw',
            'X-Subject-Meta-container_format': 'ovf',
            'X-Subject-Meta-Is-Public': 'True',
            'X-Subject-Meta-Owner': 'tenant2',
            'X-Subject-Meta-Size': '0',
        }

        # Create an subject
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:member',
        }
        auth_headers.update(CREATE_HEADERS)
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST',
                                              headers=auth_headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']

        # Verify both admin and unknown role can create properties marked with
        # '@'
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_all_permitted_admin': '1'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        subject = jsonutils.loads(content)
        self.assertEqual('1',
                         subject['subject']['properties']['x_all_permitted_admin'])
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:joe_soap',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_all_permitted_joe_soap': '1',
            'X-Glance-Registry-Purge-Props': 'False'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        subject = jsonutils.loads(content)
        self.assertEqual(
            '1', subject['subject']['properties']['x_all_permitted_joe_soap'])

        # Verify both admin and unknown role can read properties marked with
        # '@'
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'HEAD',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        self.assertEqual('1', response.get(
            'x-subject-meta-property-x_all_permitted_admin'))
        self.assertEqual('1', response.get(
            'x-subject-meta-property-x_all_permitted_joe_soap'))
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:joe_soap',
        }
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'HEAD',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        self.assertEqual('1', response.get(
            'x-subject-meta-property-x_all_permitted_admin'))
        self.assertEqual('1', response.get(
            'x-subject-meta-property-x_all_permitted_joe_soap'))

        # Verify both admin and unknown role can update properties marked with
        # '@'
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_all_permitted_admin': '2',
            'X-Glance-Registry-Purge-Props': 'False'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        subject = jsonutils.loads(content)
        self.assertEqual('2',
                         subject['subject']['properties']['x_all_permitted_admin'])
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:joe_soap',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_all_permitted_joe_soap': '2',
            'X-Glance-Registry-Purge-Props': 'False'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        subject = jsonutils.loads(content)
        self.assertEqual(
            '2', subject['subject']['properties']['x_all_permitted_joe_soap'])

        # Verify both admin and unknown role can delete properties marked with
        # '@'
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_all_permitted_joe_soap': '2',
            'X-Glance-Registry-Purge-Props': 'True'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        subject = jsonutils.loads(content)
        self.assertNotIn('x_all_permitted_admin', subject['subject']['properties'])
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:joe_soap',
        }
        custom_props = {
            'X-Glance-Registry-Purge-Props': 'True'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        subject = jsonutils.loads(content)
        self.assertNotIn('x_all_permitted_joe_soap',
                         subject['subject']['properties'])

        # Verify neither admin nor unknown role can create a property protected
        # with '!'
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_none_permitted_admin': '1'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(403, response.status)
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:joe_soap',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_none_permitted_joe_soap': '1'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(403, response.status)

        # Verify neither admin nor unknown role can read properties marked with
        # '!'
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_none_read': '1'
        }
        auth_headers.update(custom_props)
        auth_headers.update(CREATE_HEADERS)
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST',
                                              headers=auth_headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'HEAD',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        self.assertRaises(KeyError,
                          response.get, 'X-Subject-Meta-Property-x_none_read')
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:joe_soap',
        }
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'HEAD',
                                              headers=auth_headers)
        self.assertEqual(200, response.status)
        self.assertRaises(KeyError,
                          response.get, 'X-Subject-Meta-Property-x_none_read')

        # Verify neither admin nor unknown role can update properties marked
        # with '!'
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_none_update': '1'
        }
        auth_headers.update(custom_props)
        auth_headers.update(CREATE_HEADERS)
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST',
                                              headers=auth_headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_none_update': '2'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(403, response.status)
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:joe_soap',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_none_update': '2'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(403, response.status)

        # Verify neither admin nor unknown role can delete properties marked
        # with '!'
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        custom_props = {
            'X-Subject-Meta-Property-x_none_delete': '1'
        }
        auth_headers.update(custom_props)
        auth_headers.update(CREATE_HEADERS)
        path = "/v1/subjects"
        response, content = self.http.request(path, 'POST',
                                              headers=auth_headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:admin',
        }
        custom_props = {
            'X-Glance-Registry-Purge-Props': 'True'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(403, response.status)
        auth_headers = {
            'X-Auth-Token': 'user1:tenant1:joe_soap',
        }
        custom_props = {
            'X-Glance-Registry-Purge-Props': 'True'
        }
        auth_headers.update(custom_props)
        path = "/v1/subjects/%s" % subject_id
        response, content = self.http.request(path, 'PUT',
                                              headers=auth_headers)
        self.assertEqual(403, response.status)
