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

"""Functional test case that utilizes httplib2 against the API server"""

import hashlib

import httplib2
import sys

from oslo_serialization import jsonutils
from oslo_utils import units
# NOTE(jokke): simplified transition to py3, behaves like py2 xrange
from six.moves import range

from subject.tests import functional
from subject.tests.utils import minimal_headers
from subject.tests.utils import skip_if_disabled

FIVE_KB = 5 * units.Ki
FIVE_GB = 5 * units.Gi


class TestApi(functional.FunctionalTest):

    """Functional tests using httplib2 against the API server"""

    def _check_subject_create(self, headers, status=201,
                            subject_data="*" * FIVE_KB):
        # performs subject_create request, checks the response and returns
        # content
        http = httplib2.Http()
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        response, content = http.request(
            path, 'POST', headers=headers, body=subject_data)
        self.assertEqual(status, response.status)
        return content

    def test_checksum_32_chars_at_subject_create(self):
        self.cleanup()
        self.start_servers(**self.__dict__.copy())
        headers = minimal_headers('Subject1')
        subject_data = "*" * FIVE_KB

        # checksum can be no longer that 32 characters (String(32))
        headers['X-Subject-Meta-Checksum'] = 'x' * 42
        content = self._check_subject_create(headers, 400)
        self.assertIn("Invalid checksum", content)
        # test positive case as well
        headers['X-Subject-Meta-Checksum'] = hashlib.md5(subject_data).hexdigest()
        self._check_subject_create(headers)

    def test_param_int_too_large_at_create(self):
        # currently 2 params min_disk/min_ram can cause DBError on save
        self.cleanup()
        self.start_servers(**self.__dict__.copy())
        # Integer field can't be greater than max 8-byte signed integer
        for param in ['min_disk', 'min_ram']:
            headers = minimal_headers('Subject1')
            # check that long numbers result in 400
            headers['X-Subject-Meta-%s' % param] = str(sys.maxint + 1)
            content = self._check_subject_create(headers, 400)
            self.assertIn("'%s' value out of range" % param, content)
            # check that integers over 4 byte result in 400
            headers['X-Subject-Meta-%s' % param] = str(2 ** 31)
            content = self._check_subject_create(headers, 400)
            self.assertIn("'%s' value out of range" % param, content)
            # verify positive case as well
            headers['X-Subject-Meta-%s' % param] = str((2 ** 31) - 1)
            self._check_subject_create(headers)

    @skip_if_disabled
    def test_get_head_simple_post(self):
        """
        We test the following sequential series of actions:

        0. GET /subjects
        - Verify no public subjects
        1. GET /subjects/detail
        - Verify no public subjects
        2. POST /subjects with public subject named Subject1
        and no custom properties
        - Verify 201 returned
        3. HEAD subject
        - Verify HTTP headers have correct information we just added
        4. GET subject
        - Verify all information on subject we just added is correct
        5. GET /subjects
        - Verify the subject we just added is returned
        6. GET /subjects/detail
        - Verify the subject we just added is returned
        7. PUT subject with custom properties of "distro" and "arch"
        - Verify 200 returned
        8. PUT subject with too many custom properties
        - Verify 413 returned
        9. GET subject
        - Verify updated information about subject was stored
        10. PUT subject
        - Remove a previously existing property.
        11. PUT subject
        - Add a previously deleted property.
        12. PUT subject/members/member1
        - Add member1 to subject
        13. PUT subject/members/member2
        - Add member2 to subject
        14. GET subject/members
        - List subject members
        15. DELETE subject/members/member1
        - Delete subject member1
        16. PUT subject/members
        - Attempt to replace members with an overlimit amount
        17. PUT subject/members/member11
        - Attempt to add a member while at limit
        18. POST /subjects with another public subject named Subject2
        - attribute and three custom properties, "distro", "arch" & "foo"
        - Verify a 200 OK is returned
        19. HEAD subject2
        - Verify subject2 found now
        20. GET /subjects
        - Verify 2 public subjects
        21. GET /subjects with filter on user-defined property "distro".
        - Verify both subjects are returned
        22. GET /subjects with filter on user-defined property 'distro' but
        - with non-existent value. Verify no subjects are returned
        23. GET /subjects with filter on non-existent user-defined property
        - "boo". Verify no subjects are returned
        24. GET /subjects with filter 'arch=i386'
        - Verify only subject2 is returned
        25. GET /subjects with filter 'arch=x86_64'
        - Verify only subject1 is returned
        26. GET /subjects with filter 'foo=bar'
        - Verify only subject2 is returned
        27. DELETE subject1
        - Delete subject
        28. GET subject/members
        -  List deleted subject members
        29. PUT subject/members/member2
        - Update existing member2 of deleted subject
        30. PUT subject/members/member3
        - Add member3 to deleted subject
        31. DELETE subject/members/member2
        - Delete member2 from deleted subject
        32. DELETE subject2
        - Delete subject
        33. GET /subjects
        - Verify no subjects are listed
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        # 0. GET /subjects
        # Verify no public subjects
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual('{"subjects": []}', content)

        # 1. GET /subjects/detail
        # Verify no public subjects
        path = "http://%s:%d/v1/subjects/detail" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual('{"subjects": []}', content)

        # 2. POST /subjects with public subject named Subject1
        # attribute and no custom properties. Verify a 200 OK is returned
        subject_data = "*" * FIVE_KB
        headers = minimal_headers('Subject1')
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=subject_data)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subject']['checksum'])
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("Subject1", data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])

        # 3. HEAD subject
        # Verify subject found now
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual("Subject1", response['x-subject-meta-name'])

        # 4. GET subject
        # Verify all information on subject we just added is correct
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        expected_subject_headers = {
            'x-subject-meta-id': subject_id,
            'x-subject-meta-name': 'Subject1',
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
        # Verify one public subject
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        expected_result = {"subjects": [
            {"container_format": "ovf",
             "disk_format": "raw",
             "id": subject_id,
             "name": "Subject1",
             "checksum": "c2e5db72bd7fd153f53ede5da5a06de3",
             "size": 5120}]}
        self.assertEqual(expected_result, jsonutils.loads(content))

        # 6. GET /subjects/detail
        # Verify subject and all its metadata
        path = "http://%s:%d/v1/subjects/detail" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        expected_subject = {
            "status": "active",
            "name": "Subject1",
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
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'PUT', headers=headers)
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual("x86_64", data['subject']['properties']['arch'])
        self.assertEqual("Ubuntu", data['subject']['properties']['distro'])

        # 8. PUT subject with too many custom properties
        # Verify 413 returned
        headers = {}
        for i in range(11):  # configured limit is 10
            headers['X-Subject-Meta-Property-foo%d' % i] = 'bar'
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'PUT', headers=headers)
        self.assertEqual(413, response.status)

        # 9. GET /subjects/detail
        # Verify subject and all its metadata
        path = "http://%s:%d/v1/subjects/detail" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        expected_subject = {
            "status": "active",
            "name": "Subject1",
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

        # 10. PUT subject and remove a previously existing property.
        headers = {'X-Subject-Meta-Property-Arch': 'x86_64'}
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'PUT', headers=headers)
        self.assertEqual(200, response.status)

        path = "http://%s:%d/v1/subjects/detail" % ("127.0.0.1", self.api_port)
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)['subjects'][0]
        self.assertEqual(1, len(data['properties']))
        self.assertEqual("x86_64", data['properties']['arch'])

        # 11. PUT subject and add a previously deleted property.
        headers = {'X-Subject-Meta-Property-Distro': 'Ubuntu',
                   'X-Subject-Meta-Property-Arch': 'x86_64'}
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'PUT', headers=headers)
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)

        path = "http://%s:%d/v1/subjects/detail" % ("127.0.0.1", self.api_port)
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)['subjects'][0]
        self.assertEqual(2, len(data['properties']))
        self.assertEqual("x86_64", data['properties']['arch'])
        self.assertEqual("Ubuntu", data['properties']['distro'])
        self.assertNotEqual(data['created_at'], data['updated_at'])

        # 12. Add member to subject
        path = ("http://%s:%d/v1/subjects/%s/members/pattieblack" %
                ("127.0.0.1", self.api_port, subject_id))
        http = httplib2.Http()
        response, content = http.request(path, 'PUT')
        self.assertEqual(204, response.status)

        # 13. Add member to subject
        path = ("http://%s:%d/v1/subjects/%s/members/pattiewhite" %
                ("127.0.0.1", self.api_port, subject_id))
        http = httplib2.Http()
        response, content = http.request(path, 'PUT')
        self.assertEqual(204, response.status)

        # 14. List subject members
        path = ("http://%s:%d/v1/subjects/%s/members" %
                ("127.0.0.1", self.api_port, subject_id))
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(2, len(data['members']))
        self.assertEqual('pattieblack', data['members'][0]['member_id'])
        self.assertEqual('pattiewhite', data['members'][1]['member_id'])

        # 15. Delete subject member
        path = ("http://%s:%d/v1/subjects/%s/members/pattieblack" %
                ("127.0.0.1", self.api_port, subject_id))
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(204, response.status)

        # 16. Attempt to replace members with an overlimit amount
        # Adding 11 subject members should fail since configured limit is 10
        path = ("http://%s:%d/v1/subjects/%s/members" %
                ("127.0.0.1", self.api_port, subject_id))
        memberships = []
        for i in range(11):
            member_id = "foo%d" % i
            memberships.append(dict(member_id=member_id))
        http = httplib2.Http()
        body = jsonutils.dumps(dict(memberships=memberships))
        response, content = http.request(path, 'PUT', body=body)
        self.assertEqual(413, response.status)

        # 17. Attempt to add a member while at limit
        # Adding an 11th member should fail since configured limit is 10
        path = ("http://%s:%d/v1/subjects/%s/members" %
                ("127.0.0.1", self.api_port, subject_id))
        memberships = []
        for i in range(10):
            member_id = "foo%d" % i
            memberships.append(dict(member_id=member_id))
        http = httplib2.Http()
        body = jsonutils.dumps(dict(memberships=memberships))
        response, content = http.request(path, 'PUT', body=body)
        self.assertEqual(204, response.status)

        path = ("http://%s:%d/v1/subjects/%s/members/fail_me" %
                ("127.0.0.1", self.api_port, subject_id))
        http = httplib2.Http()
        response, content = http.request(path, 'PUT')
        self.assertEqual(413, response.status)

        # 18. POST /subjects with another public subject named Subject2
        # attribute and three custom properties, "distro", "arch" & "foo".
        # Verify a 200 OK is returned
        subject_data = "*" * FIVE_KB
        headers = minimal_headers('Subject2')
        headers['X-Subject-Meta-Property-Distro'] = 'Ubuntu'
        headers['X-Subject-Meta-Property-Arch'] = 'i386'
        headers['X-Subject-Meta-Property-foo'] = 'bar'
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=subject_data)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject2_id = data['subject']['id']
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subject']['checksum'])
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("Subject2", data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])
        self.assertEqual('Ubuntu', data['subject']['properties']['distro'])
        self.assertEqual('i386', data['subject']['properties']['arch'])
        self.assertEqual('bar', data['subject']['properties']['foo'])

        # 19. HEAD subject2
        # Verify subject2 found now
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject2_id)
        http = httplib2.Http()
        response, content = http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual("Subject2", response['x-subject-meta-name'])

        # 20. GET /subjects
        # Verify 2 public subjects
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        subjects = jsonutils.loads(content)['subjects']
        self.assertEqual(2, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])
        self.assertEqual(subject_id, subjects[1]['id'])

        # 21. GET /subjects with filter on user-defined property 'distro'.
        # Verify both subjects are returned
        path = "http://%s:%d/v1/subjects?property-distro=Ubuntu" % (
            "127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        subjects = jsonutils.loads(content)['subjects']
        self.assertEqual(2, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])
        self.assertEqual(subject_id, subjects[1]['id'])

        # 22. GET /subjects with filter on user-defined property 'distro' but
        # with non-existent value. Verify no subjects are returned
        path = "http://%s:%d/v1/subjects?property-distro=fedora" % (
            "127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        subjects = jsonutils.loads(content)['subjects']
        self.assertEqual(0, len(subjects))

        # 23. GET /subjects with filter on non-existent user-defined property
        # 'boo'. Verify no subjects are returned
        path = "http://%s:%d/v1/subjects?property-boo=bar" % ("127.0.0.1",
                                                            self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        subjects = jsonutils.loads(content)['subjects']
        self.assertEqual(0, len(subjects))

        # 24. GET /subjects with filter 'arch=i386'
        # Verify only subject2 is returned
        path = "http://%s:%d/v1/subjects?property-arch=i386" % ("127.0.0.1",
                                                              self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        subjects = jsonutils.loads(content)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])

        # 25. GET /subjects with filter 'arch=x86_64'
        # Verify only subject1 is returned
        path = "http://%s:%d/v1/subjects?property-arch=x86_64" % ("127.0.0.1",
                                                                self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        subjects = jsonutils.loads(content)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject_id, subjects[0]['id'])

        # 26. GET /subjects with filter 'foo=bar'
        # Verify only subject2 is returned
        path = "http://%s:%d/v1/subjects?property-foo=bar" % ("127.0.0.1",
                                                            self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        subjects = jsonutils.loads(content)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])

        # 27. DELETE subject1
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        # 28. Try to list members of deleted subject
        path = ("http://%s:%d/v1/subjects/%s/members" %
                ("127.0.0.1", self.api_port, subject_id))
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(404, response.status)

        # 29. Try to update member of deleted subject
        path = ("http://%s:%d/v1/subjects/%s/members" %
                ("127.0.0.1", self.api_port, subject_id))
        http = httplib2.Http()
        fixture = [{'member_id': 'pattieblack', 'can_share': 'false'}]
        body = jsonutils.dumps(dict(memberships=fixture))
        response, content = http.request(path, 'PUT', body=body)
        self.assertEqual(404, response.status)

        # 30. Try to add member to deleted subject
        path = ("http://%s:%d/v1/subjects/%s/members/chickenpattie" %
                ("127.0.0.1", self.api_port, subject_id))
        http = httplib2.Http()
        response, content = http.request(path, 'PUT')
        self.assertEqual(404, response.status)

        # 31. Try to delete member of deleted subject
        path = ("http://%s:%d/v1/subjects/%s/members/pattieblack" %
                ("127.0.0.1", self.api_port, subject_id))
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(404, response.status)

        # 32. DELETE subject2
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject2_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        # 33. GET /subjects
        # Verify no subjects are listed
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        subjects = jsonutils.loads(content)['subjects']
        self.assertEqual(0, len(subjects))

        # 34. HEAD /subjects/detail
        path = "http://%s:%d/v1/subjects/detail" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'HEAD')
        self.assertEqual(405, response.status)
        self.assertEqual('GET', response.get('allow'))

        self.stop_servers()

    def test_download_non_exists_subject_raises_http_forbidden(self):
        """
        We test the following sequential series of actions::

            0. POST /subjects with public subject named Subject1
               and no custom properties
               - Verify 201 returned
            1. HEAD subject
               - Verify HTTP headers have correct information we just added
            2. GET subject
               - Verify all information on subject we just added is correct
            3. DELETE subject1
               - Delete the newly added subject
            4. GET subject
               - Verify that 403 HTTPForbidden exception is raised prior to
                 404 HTTPNotFound

        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        subject_data = "*" * FIVE_KB
        headers = minimal_headers('Subject1')
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=subject_data)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subject']['checksum'])
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("Subject1", data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])

        # 1. HEAD subject
        # Verify subject found now
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual("Subject1", response['x-subject-meta-name'])

        # 2. GET /subjects
        # Verify one public subject
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        expected_result = {"subjects": [
            {"container_format": "ovf",
             "disk_format": "raw",
             "id": subject_id,
             "name": "Subject1",
             "checksum": "c2e5db72bd7fd153f53ede5da5a06de3",
             "size": 5120}]}
        self.assertEqual(expected_result, jsonutils.loads(content))

        # 3. DELETE subject1
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        # 4. GET subject
        # Verify that 403 HTTPForbidden exception is raised prior to
        # 404 HTTPNotFound
        rules = {"download_subject": '!'}
        self.set_policy_rules(rules)
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(403, response.status)

        self.stop_servers()

    def test_download_non_exists_subject_raises_http_not_found(self):
        """
        We test the following sequential series of actions:

        0. POST /subjects with public subject named Subject1
        and no custom properties
        - Verify 201 returned
        1. HEAD subject
        - Verify HTTP headers have correct information we just added
        2. GET subject
        - Verify all information on subject we just added is correct
        3. DELETE subject1
        - Delete the newly added subject
        4. GET subject
        - Verify that 404 HTTPNotFound exception is raised
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        subject_data = "*" * FIVE_KB
        headers = minimal_headers('Subject1')
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=subject_data)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['subject']['id']
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subject']['checksum'])
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("Subject1", data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])

        # 1. HEAD subject
        # Verify subject found now
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual("Subject1", response['x-subject-meta-name'])

        # 2. GET /subjects
        # Verify one public subject
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        expected_result = {"subjects": [
            {"container_format": "ovf",
             "disk_format": "raw",
             "id": subject_id,
             "name": "Subject1",
             "checksum": "c2e5db72bd7fd153f53ede5da5a06de3",
             "size": 5120}]}
        self.assertEqual(expected_result, jsonutils.loads(content))

        # 3. DELETE subject1
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        # 4. GET subject
        # Verify that 404 HTTPNotFound exception is raised
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(404, response.status)

        self.stop_servers()

    def test_status_cannot_be_manipulated_directly(self):
        self.cleanup()
        self.start_servers(**self.__dict__.copy())
        headers = minimal_headers('Subject1')

        # Create a 'queued' subject
        http = httplib2.Http()
        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Disk-Format': 'raw',
                   'X-Subject-Meta-Container-Format': 'bare'}
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        response, content = http.request(path, 'POST', headers=headers,
                                         body=None)
        self.assertEqual(201, response.status)
        subject = jsonutils.loads(content)['subject']
        self.assertEqual('queued', subject['status'])

        # Ensure status of 'queued' subject can't be changed
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject['id'])
        http = httplib2.Http()
        headers = {'X-Subject-Meta-Status': 'active'}
        response, content = http.request(path, 'PUT', headers=headers)
        self.assertEqual(403, response.status)
        response, content = http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual('queued', response['x-subject-meta-status'])

        # We allow 'setting' to the same status
        http = httplib2.Http()
        headers = {'X-Subject-Meta-Status': 'queued'}
        response, content = http.request(path, 'PUT', headers=headers)
        self.assertEqual(200, response.status)
        response, content = http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual('queued', response['x-subject-meta-status'])

        # Make subject active
        http = httplib2.Http()
        headers = {'Content-Type': 'application/octet-stream'}
        response, content = http.request(path, 'PUT', headers=headers,
                                         body='data')
        self.assertEqual(200, response.status)
        subject = jsonutils.loads(content)['subject']
        self.assertEqual('active', subject['status'])

        # Ensure status of 'active' subject can't be changed
        http = httplib2.Http()
        headers = {'X-Subject-Meta-Status': 'queued'}
        response, content = http.request(path, 'PUT', headers=headers)
        self.assertEqual(403, response.status)
        response, content = http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual('active', response['x-subject-meta-status'])

        # We allow 'setting' to the same status
        http = httplib2.Http()
        headers = {'X-Subject-Meta-Status': 'active'}
        response, content = http.request(path, 'PUT', headers=headers)
        self.assertEqual(200, response.status)
        response, content = http.request(path, 'HEAD')
        self.assertEqual(200, response.status)
        self.assertEqual('active', response['x-subject-meta-status'])

        # Create a 'queued' subject, ensure 'status' header is ignored
        http = httplib2.Http()
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Status': 'active'}
        response, content = http.request(path, 'POST', headers=headers,
                                         body=None)
        self.assertEqual(201, response.status)
        subject = jsonutils.loads(content)['subject']
        self.assertEqual('queued', subject['status'])

        # Create an 'active' subject, ensure 'status' header is ignored
        http = httplib2.Http()
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        headers = {'Content-Type': 'application/octet-stream',
                   'X-Subject-Meta-Disk-Format': 'raw',
                   'X-Subject-Meta-Status': 'queued',
                   'X-Subject-Meta-Container-Format': 'bare'}
        response, content = http.request(path, 'POST', headers=headers,
                                         body='data')
        self.assertEqual(201, response.status)
        subject = jsonutils.loads(content)['subject']
        self.assertEqual('active', subject['status'])
        self.stop_servers()
