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

import os
import signal
import uuid

from oslo_serialization import jsonutils
import requests
import six
# NOTE(jokke): simplified transition to py3, behaves like py2 xrange
from six.moves import range
from six.moves import urllib

from subject.tests import functional
from subject.tests import utils as test_utils


TENANT1 = str(uuid.uuid4())
TENANT2 = str(uuid.uuid4())
TENANT3 = str(uuid.uuid4())
TENANT4 = str(uuid.uuid4())


class TestSubjects(functional.FunctionalTest):

    def setUp(self):
        super(TestSubjects, self).setUp()
        self.cleanup()
        self.api_server.deployment_flavor = 'noauth'
        self.api_server.data_api = 'subject.db.sqlalchemy.api'
        for i in range(3):
            ret = test_utils.start_http_server("foo_subject_id%d" % i,
                                               "foo_subject%d" % i)
            setattr(self, 'http_server%d_pid' % i, ret[0])
            setattr(self, 'http_port%d' % i, ret[1])

    def tearDown(self):
        for i in range(3):
            pid = getattr(self, 'http_server%d_pid' % i, None)
            if pid:
                os.kill(pid, signal.SIGKILL)

        super(TestSubjects, self).tearDown()

    def _url(self, path):
        return 'http://127.0.0.1:%d%s' % (self.api_port, path)

    def _headers(self, custom_headers=None):
        base_headers = {
            'X-Identity-Status': 'Confirmed',
            'X-Auth-Token': '932c5c84-02ac-4fe5-a9ba-620af0e2bb96',
            'X-User-Id': 'f9a41d13-0c13-47e9-bee2-ce4e8bfe958e',
            'X-Tenant-Id': TENANT1,
            'X-Roles': 'member',
        }
        base_headers.update(custom_headers or {})
        return base_headers

    def test_v1_none_properties_v2(self):
        self.api_server.deployment_flavor = 'noauth'
        self.api_server.use_user_token = True
        self.api_server.send_identity_credentials = True
        self.registry_server.deployment_flavor = ''
        # Subject list should be empty
        self.start_servers(**self.__dict__.copy())

        # Create an subject (with two deployer-defined properties)
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/octet-stream'})
        headers.update(test_utils.minimal_headers('subject-1'))
        # NOTE(flaper87): Sending empty string, the server will use None
        headers['x-subject-meta-property-my_empty_prop'] = ''

        response = requests.post(path, headers=headers)
        self.assertEqual(201, response.status_code)
        data = jsonutils.loads(response.text)
        subject_id = data['subject']['id']

        # NOTE(flaper87): Get the subject using V2 and verify
        # the returned value for `my_empty_prop` is an empty
        # string.
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertEqual('', subject['my_empty_prop'])
        self.stop_servers()

    def test_not_authenticated_in_registry_on_ops(self):
        # https://bugs.launchpad.net/glance/+bug/1451850
        # this configuration guarantees that authentication succeeds in
        # subject-api and fails in subject-registry if no token is passed
        self.api_server.deployment_flavor = ''
        # make sure that request will reach registry
        self.api_server.data_api = 'subject.db.registry.api'
        self.registry_server.deployment_flavor = 'fakeauth'
        self.start_servers(**self.__dict__.copy())
        headers = {'content-type': 'application/json'}
        subject = {'name': 'subject', 'type': 'kernel', 'disk_format': 'qcow2',
                 'container_format': 'bare'}
        # subject create should return 401
        response = requests.post(self._url('/v1/subjects'), headers=headers,
                                 data=jsonutils.dumps(subject))
        self.assertEqual(401, response.status_code)
        # subject list should return 401
        response = requests.get(self._url('/v1/subjects'))
        self.assertEqual(401, response.status_code)
        # subject show should return 401
        response = requests.get(self._url('/v1/subjects/somesubjectid'))
        self.assertEqual(401, response.status_code)
        # subject update should return 401
        ops = [{'op': 'replace', 'path': '/protected', 'value': False}]
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        response = requests.patch(self._url('/v1/subjects/somesubjectid'),
                                  headers={'content-type': media_type},
                                  data=jsonutils.dumps(ops))
        self.assertEqual(401, response.status_code)
        # subject delete should return 401
        response = requests.delete(self._url('/v1/subjects/somesubjectid'))
        self.assertEqual(401, response.status_code)
        self.stop_servers()

    def test_subject_lifecycle(self):
        # Subject list should be empty
        self.api_server.show_multiple_locations = True
        self.start_servers(**self.__dict__.copy())
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Create an subject (with two deployer-defined properties)
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-1', 'type': 'kernel',
                                'foo': 'bar', 'disk_format': 'aki',
                                'container_format': 'aki', 'abc': 'xyz'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject_location_header = response.headers['Location']

        # Returned subject entity should have a generated id and status
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        checked_keys = set([
            u'status',
            u'name',
            u'tags',
            u'created_at',
            u'updated_at',
            u'visibility',
            u'self',
            u'protected',
            u'id',
            u'file',
            u'min_disk',
            u'foo',
            u'abc',
            u'type',
            u'min_ram',
            u'schema',
            u'disk_format',
            u'container_format',
            u'owner',
            u'checksum',
            u'size',
            u'virtual_size',
            u'locations',
        ])
        self.assertEqual(checked_keys, set(subject.keys()))
        expected_subject = {
            'status': 'queued',
            'name': 'subject-1',
            'tags': [],
            'visibility': 'private',
            'self': '/v1/subjects/%s' % subject_id,
            'protected': False,
            'file': '/v1/subjects/%s/file' % subject_id,
            'min_disk': 0,
            'foo': 'bar',
            'abc': 'xyz',
            'type': 'kernel',
            'min_ram': 0,
            'schema': '/v1/schemas/subject',
        }
        for key, value in expected_subject.items():
            self.assertEqual(value, subject[key], key)

        # Subject list should now have one entry
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject_id, subjects[0]['id'])

        # Create another subject (with two deployer-defined properties)
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-2', 'type': 'kernel',
                                'bar': 'foo', 'disk_format': 'aki',
                                'container_format': 'aki', 'xyz': 'abc'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Returned subject entity should have a generated id and status
        subject = jsonutils.loads(response.text)
        subject2_id = subject['id']
        checked_keys = set([
            u'status',
            u'name',
            u'tags',
            u'created_at',
            u'updated_at',
            u'visibility',
            u'self',
            u'protected',
            u'id',
            u'file',
            u'min_disk',
            u'bar',
            u'xyz',
            u'type',
            u'min_ram',
            u'schema',
            u'disk_format',
            u'container_format',
            u'owner',
            u'checksum',
            u'size',
            u'virtual_size',
            u'locations',
        ])
        self.assertEqual(checked_keys, set(subject.keys()))
        expected_subject = {
            'status': 'queued',
            'name': 'subject-2',
            'tags': [],
            'visibility': 'private',
            'self': '/v1/subjects/%s' % subject2_id,
            'protected': False,
            'file': '/v1/subjects/%s/file' % subject2_id,
            'min_disk': 0,
            'bar': 'foo',
            'xyz': 'abc',
            'type': 'kernel',
            'min_ram': 0,
            'schema': '/v1/schemas/subject',
        }
        for key, value in expected_subject.items():
            self.assertEqual(value, subject[key], key)

        # Subject list should now have two entries
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(2, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])
        self.assertEqual(subject_id, subjects[1]['id'])

        # Subject list should list only subject-2 as subject-1 doesn't contain the
        # property 'bar'
        path = self._url('/v1/subjects?bar=foo')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])

        # Subject list should list only subject-1 as subject-2 doesn't contain the
        # property 'foo'
        path = self._url('/v1/subjects?foo=bar')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject_id, subjects[0]['id'])

        # The "changes-since" filter shouldn't work on subject v1
        path = self._url('/v1/subjects?changes-since=20001007T10:10:10')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(400, response.status_code)

        path = self._url('/v1/subjects?changes-since=aaa')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(400, response.status_code)

        # Subject list should list only subject-1 based on the filter
        # 'foo=bar&abc=xyz'
        path = self._url('/v1/subjects?foo=bar&abc=xyz')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject_id, subjects[0]['id'])

        # Subject list should list only subject-2 based on the filter
        # 'bar=foo&xyz=abc'
        path = self._url('/v1/subjects?bar=foo&xyz=abc')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])

        # Subject list should not list anything as the filter 'foo=baz&abc=xyz'
        # is not satisfied by either subjects
        path = self._url('/v1/subjects?foo=baz&abc=xyz')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Get the subject using the returned Location header
        response = requests.get(subject_location_header, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertEqual(subject_id, subject['id'])
        self.assertIsNone(subject['checksum'])
        self.assertIsNone(subject['size'])
        self.assertIsNone(subject['virtual_size'])
        self.assertEqual('bar', subject['foo'])
        self.assertFalse(subject['protected'])
        self.assertEqual('kernel', subject['type'])
        self.assertTrue(subject['created_at'])
        self.assertTrue(subject['updated_at'])
        self.assertEqual(subject['updated_at'], subject['created_at'])

        # The URI file:// should return a 400 rather than a 500
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        url = ('file://')
        changes = [{
            'op': 'add',
            'path': '/locations/-',
            'value': {
                'url': url,
                'metadata': {}
            }
        }]

        data = jsonutils.dumps(changes)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(400, response.status_code, response.text)

        # The subject should be mutable, including adding and removing properties
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        data = jsonutils.dumps([
            {'op': 'replace', 'path': '/name', 'value': 'subject-2'},
            {'op': 'replace', 'path': '/disk_format', 'value': 'vhd'},
            {'op': 'replace', 'path': '/container_format', 'value': 'ami'},
            {'op': 'replace', 'path': '/foo', 'value': 'baz'},
            {'op': 'add', 'path': '/ping', 'value': 'pong'},
            {'op': 'replace', 'path': '/protected', 'value': True},
            {'op': 'remove', 'path': '/type'},
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)

        # Returned subject entity should reflect the changes
        subject = jsonutils.loads(response.text)
        self.assertEqual('subject-2', subject['name'])
        self.assertEqual('vhd', subject['disk_format'])
        self.assertEqual('baz', subject['foo'])
        self.assertEqual('pong', subject['ping'])
        self.assertTrue(subject['protected'])
        self.assertNotIn('type', subject, response.text)

        # Adding 11 subject properties should fail since configured limit is 10
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        changes = []
        for i in range(11):
            changes.append({'op': 'add',
                            'path': '/ping%i' % i,
                            'value': 'pong'})

        data = jsonutils.dumps(changes)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(413, response.status_code, response.text)

        # Adding 3 subject locations should fail since configured limit is 2
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        changes = []
        for i in range(3):
            url = ('http://127.0.0.1:%s/foo_subject' %
                   getattr(self, 'http_port%d' % i))
            changes.append({'op': 'add', 'path': '/locations/-',
                            'value': {'url': url, 'metadata': {}},
                            })

        data = jsonutils.dumps(changes)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(413, response.status_code, response.text)

        # Ensure the v1.0 json-patch content type is accepted
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.0-json-patch'
        headers = self._headers({'content-type': media_type})
        data = jsonutils.dumps([{'add': '/ding', 'value': 'dong'}])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)

        # Returned subject entity should reflect the changes
        subject = jsonutils.loads(response.text)
        self.assertEqual('dong', subject['ding'])

        # Updates should persist across requests
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertEqual(subject_id, subject['id'])
        self.assertEqual('subject-2', subject['name'])
        self.assertEqual('baz', subject['foo'])
        self.assertEqual('pong', subject['ping'])
        self.assertTrue(subject['protected'])
        self.assertNotIn('type', subject, response.text)

        # Try to download data before its uploaded
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers()
        response = requests.get(path, headers=headers)
        self.assertEqual(204, response.status_code)

        def _verify_subject_checksum_and_status(checksum, status):
            # Checksum should be populated and status should be active
            path = self._url('/v1/subjects/%s' % subject_id)
            response = requests.get(path, headers=self._headers())
            self.assertEqual(200, response.status_code)
            subject = jsonutils.loads(response.text)
            self.assertEqual(checksum, subject['checksum'])
            self.assertEqual(status, subject['status'])

        # Upload some subject data
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.put(path, headers=headers, data='ZZZZZ')
        self.assertEqual(204, response.status_code)

        expected_checksum = '8f113e38d28a79a5a451b16048cc2b72'
        _verify_subject_checksum_and_status(expected_checksum, 'active')

        # `disk_format` and `container_format` cannot
        # be replaced when the subject is active.
        immutable_paths = ['/disk_format', '/container_format']
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        path = self._url('/v1/subjects/%s' % subject_id)
        for immutable_path in immutable_paths:
            data = jsonutils.dumps([
                {'op': 'replace', 'path': immutable_path, 'value': 'ari'},
            ])
            response = requests.patch(path, headers=headers, data=data)
            self.assertEqual(403, response.status_code)

        # Try to download the data that was just uploaded
        path = self._url('/v1/subjects/%s/file' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        self.assertEqual(expected_checksum, response.headers['Content-MD5'])
        self.assertEqual('ZZZZZ', response.text)

        # Uploading duplicate data should be rejected with a 409. The
        # original data should remain untouched.
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.put(path, headers=headers, data='XXX')
        self.assertEqual(409, response.status_code)
        _verify_subject_checksum_and_status(expected_checksum, 'active')

        # Ensure the size is updated to reflect the data uploaded
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        self.assertEqual(5, jsonutils.loads(response.text)['size'])

        # Should be able to deactivate subject
        path = self._url('/v1/subjects/%s/actions/deactivate' % subject_id)
        response = requests.post(path, data={}, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # Change the subject to public so TENANT2 can see it
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.0-json-patch'
        headers = self._headers({'content-type': media_type})
        data = jsonutils.dumps([{"replace": "/visibility", "value": "public"}])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)

        # Tenant2 should get Forbidden when deactivating the public subject
        path = self._url('/v1/subjects/%s/actions/deactivate' % subject_id)
        response = requests.post(path, data={}, headers=self._headers(
            {'X-Tenant-Id': TENANT2}))
        self.assertEqual(403, response.status_code)

        # Tenant2 should get Forbidden when reactivating the public subject
        path = self._url('/v1/subjects/%s/actions/reactivate' % subject_id)
        response = requests.post(path, data={}, headers=self._headers(
            {'X-Tenant-Id': TENANT2}))
        self.assertEqual(403, response.status_code)

        # Deactivating a deactivated subject succeeds (no-op)
        path = self._url('/v1/subjects/%s/actions/deactivate' % subject_id)
        response = requests.post(path, data={}, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # Can't download a deactivated subject
        path = self._url('/v1/subjects/%s/file' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(403, response.status_code)

        # Deactivated subject should still be in a listing
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(2, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])
        self.assertEqual(subject_id, subjects[1]['id'])

        # Should be able to reactivate a deactivated subject
        path = self._url('/v1/subjects/%s/actions/reactivate' % subject_id)
        response = requests.post(path, data={}, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # Reactivating an active subject succeeds (no-op)
        path = self._url('/v1/subjects/%s/actions/reactivate' % subject_id)
        response = requests.post(path, data={}, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # Deletion should not work on protected subjects
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(403, response.status_code)

        # Unprotect subject for deletion
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        doc = [{'op': 'replace', 'path': '/protected', 'value': False}]
        data = jsonutils.dumps(doc)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)

        # Deletion should work. Deleting subject-1
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # This subject should be no longer be directly accessible
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(404, response.status_code)

        # And neither should its data
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers()
        response = requests.get(path, headers=headers)
        self.assertEqual(404, response.status_code)

        # Subject list should now contain just subject-2
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])

        # Deleting subject-2 should work
        path = self._url('/v1/subjects/%s' % subject2_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # Subject list should now be empty
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Create subject that tries to send True should return 400
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = 'true'
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(400, response.status_code)

        # Create subject that tries to send a string should return 400
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = '"hello"'
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(400, response.status_code)

        # Create subject that tries to send 123 should return 400
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = '123'
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(400, response.status_code)

        self.stop_servers()

    def test_update_readonly_prop(self):
        self.start_servers(**self.__dict__.copy())
        # Create an subject (with two deployer-defined properties)
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-1'})
        response = requests.post(path, headers=headers, data=data)

        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})

        props = ['/id', '/file', '/location', '/schema', '/self']

        for prop in props:
            doc = [{'op': 'replace',
                    'path': prop,
                    'value': 'value1'}]
            data = jsonutils.dumps(doc)
            response = requests.patch(path, headers=headers, data=data)
            self.assertEqual(403, response.status_code)

        for prop in props:
            doc = [{'op': 'remove',
                    'path': prop,
                    'value': 'value1'}]
            data = jsonutils.dumps(doc)
            response = requests.patch(path, headers=headers, data=data)
            self.assertEqual(403, response.status_code)

        for prop in props:
            doc = [{'op': 'add',
                    'path': prop,
                    'value': 'value1'}]
            data = jsonutils.dumps(doc)
            response = requests.patch(path, headers=headers, data=data)
            self.assertEqual(403, response.status_code)

        self.stop_servers()

    def test_methods_that_dont_accept_illegal_bodies(self):
        # Check subjects can be reached
        self.start_servers(**self.__dict__.copy())
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)

        # Test all the schemas
        schema_urls = [
            '/v1/schemas/subjects',
            '/v1/schemas/subject',
            '/v1/schemas/members',
            '/v1/schemas/member',
        ]
        for value in schema_urls:
            path = self._url(value)
            data = jsonutils.dumps(["body"])
            response = requests.get(path, headers=self._headers(), data=data)
            self.assertEqual(400, response.status_code)

        # Create subject for use with tests
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        test_urls = [
            ('/v1/subjects/%s', 'get'),
            ('/v1/subjects/%s/actions/deactivate', 'post'),
            ('/v1/subjects/%s/actions/reactivate', 'post'),
            ('/v1/subjects/%s/tags/mytag', 'put'),
            ('/v1/subjects/%s/tags/mytag', 'delete'),
            ('/v1/subjects/%s/members', 'get'),
            ('/v1/subjects/%s/file', 'get'),
            ('/v1/subjects/%s', 'delete'),
        ]

        for link, method in test_urls:
            path = self._url(link % subject_id)
            data = jsonutils.dumps(["body"])
            response = getattr(requests, method)(
                path, headers=self._headers(), data=data)
            self.assertEqual(400, response.status_code)

        # DELETE /subjects/imgid without legal json
        path = self._url('/v1/subjects/%s' % subject_id)
        data = '{"hello"]'
        response = requests.delete(path, headers=self._headers(), data=data)
        self.assertEqual(400, response.status_code)

        # POST /subjects/imgid/members
        path = self._url('/v1/subjects/%s/members' % subject_id)
        data = jsonutils.dumps({'member': TENANT3})
        response = requests.post(path, headers=self._headers(), data=data)
        self.assertEqual(200, response.status_code)

        # GET /subjects/imgid/members/memid
        path = self._url('/v1/subjects/%s/members/%s' % (subject_id, TENANT3))
        data = jsonutils.dumps(["body"])
        response = requests.get(path, headers=self._headers(), data=data)
        self.assertEqual(400, response.status_code)

        # DELETE /subjects/imgid/members/memid
        path = self._url('/v1/subjects/%s/members/%s' % (subject_id, TENANT3))
        data = jsonutils.dumps(["body"])
        response = requests.delete(path, headers=self._headers(), data=data)
        self.assertEqual(400, response.status_code)

        self.stop_servers()

    def test_download_random_access(self):
        self.start_servers(**self.__dict__.copy())
        # Create another subject (with two deployer-defined properties)
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-2', 'type': 'kernel',
                                'bar': 'foo', 'disk_format': 'aki',
                                'container_format': 'aki', 'xyz': 'abc'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # Upload data to subject
        subject_data = 'Z' * 15
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.put(path, headers=headers, data=subject_data)
        self.assertEqual(204, response.status_code)

        result_body = ''
        for x in range(15):
            # NOTE(flaper87): Read just 1 byte. Content-Range is
            # 0-indexed and it specifies the first byte to read
            # and the last byte to read.
            content_range = 'bytes %s-%s/15' % (x, x)
            headers = self._headers({'Content-Range': content_range})
            path = self._url('/v1/subjects/%s/file' % subject_id)
            response = requests.get(path, headers=headers)
            result_body += response.text

        self.assertEqual(result_body, subject_data)

        self.stop_servers()

    def test_download_policy_when_cache_is_not_enabled(self):

        rules = {'context_is_admin': 'role:admin',
                 'default': '',
                 'add_subject': '',
                 'get_subject': '',
                 'modify_subject': '',
                 'upload_subject': '',
                 'delete_subject': '',
                 'download_subject': '!'}
        self.set_policy_rules(rules)
        self.start_servers(**self.__dict__.copy())

        # Create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'member'})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Returned subject entity
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        expected_subject = {
            'status': 'queued',
            'name': 'subject-1',
            'tags': [],
            'visibility': 'private',
            'self': '/v1/subjects/%s' % subject_id,
            'protected': False,
            'file': '/v1/subjects/%s/file' % subject_id,
            'min_disk': 0,
            'min_ram': 0,
            'schema': '/v1/schemas/subject',
        }
        for key, value in six.iteritems(expected_subject):
            self.assertEqual(value, subject[key], key)

        # Upload data to subject
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.put(path, headers=headers, data='ZZZZZ')
        self.assertEqual(204, response.status_code)

        # Get an subject should fail
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.get(path, headers=headers)
        self.assertEqual(403, response.status_code)

        # Subject Deletion should work
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # This subject should be no longer be directly accessible
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(404, response.status_code)

        self.stop_servers()

    def test_download_subject_not_allowed_using_restricted_policy(self):

        rules = {
            "context_is_admin": "role:admin",
            "default": "",
            "add_subject": "",
            "get_subject": "",
            "modify_subject": "",
            "upload_subject": "",
            "delete_subject": "",
            "restricted":
            "not ('aki':%(container_format)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }

        self.set_policy_rules(rules)
        self.start_servers(**self.__dict__.copy())

        # Create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'member'})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Returned subject entity
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        expected_subject = {
            'status': 'queued',
            'name': 'subject-1',
            'tags': [],
            'visibility': 'private',
            'self': '/v1/subjects/%s' % subject_id,
            'protected': False,
            'file': '/v1/subjects/%s/file' % subject_id,
            'min_disk': 0,
            'min_ram': 0,
            'schema': '/v1/schemas/subject',
        }

        for key, value in six.iteritems(expected_subject):
            self.assertEqual(value, subject[key], key)

        # Upload data to subject
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.put(path, headers=headers, data='ZZZZZ')
        self.assertEqual(204, response.status_code)

        # Get an subject should fail
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream',
                                 'X-Roles': '_member_'})
        response = requests.get(path, headers=headers)
        self.assertEqual(403, response.status_code)

        # Subject Deletion should work
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # This subject should be no longer be directly accessible
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(404, response.status_code)

        self.stop_servers()

    def test_download_subject_allowed_using_restricted_policy(self):

        rules = {
            "context_is_admin": "role:admin",
            "default": "",
            "add_subject": "",
            "get_subject": "",
            "modify_subject": "",
            "upload_subject": "",
            "get_subject_location": "",
            "delete_subject": "",
            "restricted":
            "not ('aki':%(container_format)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }

        self.set_policy_rules(rules)
        self.start_servers(**self.__dict__.copy())

        # Create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'member'})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Returned subject entity
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        expected_subject = {
            'status': 'queued',
            'name': 'subject-1',
            'tags': [],
            'visibility': 'private',
            'self': '/v1/subjects/%s' % subject_id,
            'protected': False,
            'file': '/v1/subjects/%s/file' % subject_id,
            'min_disk': 0,
            'min_ram': 0,
            'schema': '/v1/schemas/subject',
        }

        for key, value in six.iteritems(expected_subject):
            self.assertEqual(value, subject[key], key)

        # Upload data to subject
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.put(path, headers=headers, data='ZZZZZ')
        self.assertEqual(204, response.status_code)

        # Get an subject should be allowed
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream',
                                 'X-Roles': 'member'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)

        # Subject Deletion should work
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # This subject should be no longer be directly accessible
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(404, response.status_code)

        self.stop_servers()

    def test_download_subject_raises_service_unavailable(self):
        """Test subject download returns HTTPServiceUnavailable."""
        self.api_server.show_multiple_locations = True
        self.start_servers(**self.__dict__.copy())

        # Create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-1',
                                'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Get subject id
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # Update subject locations via PATCH
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        http_server_pid, http_port = test_utils.start_http_server(subject_id,
                                                                  "subject-1")
        values = [{'url': 'http://127.0.0.1:%s/subject-1' % http_port,
                   'metadata': {'idx': '0'}}]
        doc = [{'op': 'replace',
                'path': '/locations',
                'value': values}]
        data = jsonutils.dumps(doc)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code)

        # Download an subject should work
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/json'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)

        # Stop http server used to update subject location
        os.kill(http_server_pid, signal.SIGKILL)

        # Download an subject should raise HTTPServiceUnavailable
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/json'})
        response = requests.get(path, headers=headers)
        self.assertEqual(503, response.status_code)

        # Subject Deletion should work
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # This subject should be no longer be directly accessible
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(404, response.status_code)

        self.stop_servers()

    def test_subject_modification_works_for_owning_tenant_id(self):
        rules = {
            "context_is_admin": "role:admin",
            "default": "",
            "add_subject": "",
            "get_subject": "",
            "modify_subject": "tenant:%(owner)s",
            "upload_subject": "",
            "get_subject_location": "",
            "delete_subject": "",
            "restricted":
            "not ('aki':%(container_format)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }

        self.set_policy_rules(rules)
        self.start_servers(**self.__dict__.copy())

        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Get the subject's ID
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers['content-type'] = media_type
        del headers['X-Roles']
        data = jsonutils.dumps([
            {'op': 'replace', 'path': '/name', 'value': 'new-name'},
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code)

        self.stop_servers()

    def test_subject_modification_fails_on_mismatched_tenant_ids(self):
        rules = {
            "context_is_admin": "role:admin",
            "default": "",
            "add_subject": "",
            "get_subject": "",
            "modify_subject": "'A-Fake-Tenant-Id':%(owner)s",
            "upload_subject": "",
            "get_subject_location": "",
            "delete_subject": "",
            "restricted":
            "not ('aki':%(container_format)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }

        self.set_policy_rules(rules)
        self.start_servers(**self.__dict__.copy())

        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Get the subject's ID
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers['content-type'] = media_type
        del headers['X-Roles']
        data = jsonutils.dumps([
            {'op': 'replace', 'path': '/name', 'value': 'new-name'},
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code)

        self.stop_servers()

    def test_member_additions_works_for_owning_tenant_id(self):
        rules = {
            "context_is_admin": "role:admin",
            "default": "",
            "add_subject": "",
            "get_subject": "",
            "modify_subject": "",
            "upload_subject": "",
            "get_subject_location": "",
            "delete_subject": "",
            "restricted":
            "not ('aki':%(container_format)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted",
            "add_member": "tenant:%(owner)s",
        }

        self.set_policy_rules(rules)
        self.start_servers(**self.__dict__.copy())

        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Get the subject's ID
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # Get the subject's members resource
        path = self._url('/v1/subjects/%s/members' % subject_id)
        body = jsonutils.dumps({'member': TENANT3})
        del headers['X-Roles']
        response = requests.post(path, headers=headers, data=body)
        self.assertEqual(200, response.status_code)

        self.stop_servers()

    def test_subject_additions_works_only_for_specific_tenant_id(self):
        rules = {
            "context_is_admin": "role:admin",
            "default": "",
            "add_subject": "'{0}':%(owner)s".format(TENANT1),
            "get_subject": "",
            "modify_subject": "",
            "upload_subject": "",
            "get_subject_location": "",
            "delete_subject": "",
            "restricted":
            "not ('aki':%(container_format)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted",
            "add_member": "",
        }

        self.set_policy_rules(rules)
        self.start_servers(**self.__dict__.copy())

        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin', 'X-Tenant-Id': TENANT1})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        headers['X-Tenant-Id'] = TENANT2
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code)

        self.stop_servers()

    def test_owning_tenant_id_can_retrieve_subject_information(self):
        rules = {
            "context_is_admin": "role:admin",
            "default": "",
            "add_subject": "",
            "get_subject": "tenant:%(owner)s",
            "modify_subject": "",
            "upload_subject": "",
            "get_subject_location": "",
            "delete_subject": "",
            "restricted":
            "not ('aki':%(container_format)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted",
            "add_member": "",
        }

        self.set_policy_rules(rules)
        self.start_servers(**self.__dict__.copy())

        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin', 'X-Tenant-Id': TENANT1})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Remove the admin role
        del headers['X-Roles']
        # Get the subject's ID
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # Can retrieve the subject as TENANT1
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)

        # Can retrieve the subject's members as TENANT1
        path = self._url('/v1/subjects/%s/members' % subject_id)
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)

        headers['X-Tenant-Id'] = TENANT2
        response = requests.get(path, headers=headers)
        self.assertEqual(403, response.status_code)

        self.stop_servers()

    def test_owning_tenant_can_publicize_subject(self):
        rules = {
            "context_is_admin": "role:admin",
            "default": "",
            "add_subject": "",
            "publicize_subject": "tenant:%(owner)s",
            "get_subject": "tenant:%(owner)s",
            "modify_subject": "",
            "upload_subject": "",
            "get_subject_location": "",
            "delete_subject": "",
            "restricted":
            "not ('aki':%(container_format)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted",
            "add_member": "",
        }

        self.set_policy_rules(rules)
        self.start_servers(**self.__dict__.copy())

        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin', 'X-Tenant-Id': TENANT1})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Get the subject's ID
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({
            'Content-Type': 'application/openstack-subjects-v1.1-json-patch',
            'X-Tenant-Id': TENANT1,
        })
        doc = [{'op': 'replace', 'path': '/visibility', 'value': 'public'}]
        data = jsonutils.dumps(doc)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code)

    def test_owning_tenant_can_delete_subject(self):
        rules = {
            "context_is_admin": "role:admin",
            "default": "",
            "add_subject": "",
            "publicize_subject": "tenant:%(owner)s",
            "get_subject": "tenant:%(owner)s",
            "modify_subject": "",
            "upload_subject": "",
            "get_subject_location": "",
            "delete_subject": "",
            "restricted":
            "not ('aki':%(container_format)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted",
            "add_member": "",
        }

        self.set_policy_rules(rules)
        self.start_servers(**self.__dict__.copy())

        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin', 'X-Tenant-Id': TENANT1})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Get the subject's ID
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.delete(path, headers=headers)
        self.assertEqual(204, response.status_code)

    def test_list_show_ok_when_get_location_allowed_for_admins(self):
        self.api_server.show_subject_direct_url = True
        self.api_server.show_multiple_locations = True
        # setup context to allow a list locations by admin only
        rules = {
            "context_is_admin": "role:admin",
            "default": "",
            "add_subject": "",
            "get_subject": "",
            "modify_subject": "",
            "upload_subject": "",
            "get_subject_location": "role:admin",
            "delete_subject": "",
            "restricted": "",
            "download_subject": "",
            "add_member": "",
        }

        self.set_policy_rules(rules)
        self.start_servers(**self.__dict__.copy())

        # Create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Tenant-Id': TENANT1})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Get the subject's ID
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # Can retrieve the subject as TENANT1
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)

        # Can list subjects as TENANT1
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)

        self.stop_servers()

    def test_subject_size_cap(self):
        self.api_server.subject_size_cap = 128
        self.start_servers(**self.__dict__.copy())
        # create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-size-cap-test-subject',
                                'type': 'kernel', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # try to populate it with oversized data
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})

        class StreamSim(object):
            # Using a one-shot iterator to force chunked transfer in the PUT
            # request
            def __init__(self, size):
                self.size = size

            def __iter__(self):
                yield 'Z' * self.size

        response = requests.put(path, headers=headers, data=StreamSim(
                                self.api_server.subject_size_cap + 1))
        self.assertEqual(413, response.status_code)

        # hashlib.md5('Z'*129).hexdigest()
        #     == '76522d28cb4418f12704dfa7acd6e7ee'
        # If the subject has this checksum, it means that the whole stream was
        # accepted and written to the store, which should not be the case.
        path = self._url('/v1/subjects/{0}'.format(subject_id))
        headers = self._headers({'content-type': 'application/json'})
        response = requests.get(path, headers=headers)
        subject_checksum = jsonutils.loads(response.text).get('checksum')
        self.assertNotEqual(subject_checksum, '76522d28cb4418f12704dfa7acd6e7ee')

    def test_permissions(self):
        self.start_servers(**self.__dict__.copy())
        # Create an subject that belongs to TENANT1
        path = self._url('/v1/subjects')
        headers = self._headers({'Content-Type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'raw',
                                'container_format': 'bare'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject_id = jsonutils.loads(response.text)['id']

        # Upload some subject data
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.put(path, headers=headers, data='ZZZZZ')
        self.assertEqual(204, response.status_code)

        # TENANT1 should see the subject in their list
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(subject_id, subjects[0]['id'])

        # TENANT1 should be able to access the subject directly
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)

        # TENANT2 should not see the subject in their list
        path = self._url('/v1/subjects')
        headers = self._headers({'X-Tenant-Id': TENANT2})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # TENANT2 should not be able to access the subject directly
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'X-Tenant-Id': TENANT2})
        response = requests.get(path, headers=headers)
        self.assertEqual(404, response.status_code)

        # TENANT2 should not be able to modify the subject, either
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({
            'Content-Type': 'application/openstack-subjects-v1.1-json-patch',
            'X-Tenant-Id': TENANT2,
        })
        doc = [{'op': 'replace', 'path': '/name', 'value': 'subject-2'}]
        data = jsonutils.dumps(doc)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(404, response.status_code)

        # TENANT2 should not be able to delete the subject, either
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'X-Tenant-Id': TENANT2})
        response = requests.delete(path, headers=headers)
        self.assertEqual(404, response.status_code)

        # Publicize the subject as an admin of TENANT1
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({
            'Content-Type': 'application/openstack-subjects-v1.1-json-patch',
            'X-Roles': 'admin',
        })
        doc = [{'op': 'replace', 'path': '/visibility', 'value': 'public'}]
        data = jsonutils.dumps(doc)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code)

        # TENANT3 should now see the subject in their list
        path = self._url('/v1/subjects')
        headers = self._headers({'X-Tenant-Id': TENANT3})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(subject_id, subjects[0]['id'])

        # TENANT3 should also be able to access the subject directly
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'X-Tenant-Id': TENANT3})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)

        # TENANT3 still should not be able to modify the subject
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({
            'Content-Type': 'application/openstack-subjects-v1.1-json-patch',
            'X-Tenant-Id': TENANT3,
        })
        doc = [{'op': 'replace', 'path': '/name', 'value': 'subject-2'}]
        data = jsonutils.dumps(doc)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code)

        # TENANT3 should not be able to delete the subject, either
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'X-Tenant-Id': TENANT3})
        response = requests.delete(path, headers=headers)
        self.assertEqual(403, response.status_code)

        # Subject data should still be present after the failed delete
        path = self._url('/v1/subjects/%s/file' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        self.assertEqual(response.text, 'ZZZZZ')

        self.stop_servers()

    def test_property_protections_with_roles(self):
        # Enable property protection
        self.api_server.property_protection_file = self.property_file_roles
        self.start_servers(**self.__dict__.copy())

        # Subject list should be empty
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Create an subject for role member with extra props
        # Raises 403 since user is not allowed to set 'foo'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'member'})
        data = jsonutils.dumps({'name': 'subject-1', 'foo': 'bar',
                                'disk_format': 'aki',
                                'container_format': 'aki',
                                'x_owner_foo': 'o_s_bar'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code)

        # Create an subject for role member without 'foo'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'member'})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki',
                                'x_owner_foo': 'o_s_bar'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Returned subject entity should have 'x_owner_foo'
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        expected_subject = {
            'status': 'queued',
            'name': 'subject-1',
            'tags': [],
            'visibility': 'private',
            'self': '/v1/subjects/%s' % subject_id,
            'protected': False,
            'file': '/v1/subjects/%s/file' % subject_id,
            'min_disk': 0,
            'x_owner_foo': 'o_s_bar',
            'min_ram': 0,
            'schema': '/v1/schemas/subject',
        }
        for key, value in expected_subject.items():
            self.assertEqual(value, subject[key], key)

        # Create an subject for role spl_role with extra props
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'spl_role'})
        data = jsonutils.dumps({'name': 'subject-1',
                                'disk_format': 'aki',
                                'container_format': 'aki',
                                'spl_create_prop': 'create_bar',
                                'spl_create_prop_policy': 'create_policy_bar',
                                'spl_read_prop': 'read_bar',
                                'spl_update_prop': 'update_bar',
                                'spl_delete_prop': 'delete_bar',
                                'spl_delete_empty_prop': ''})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # Attempt to replace, add and remove properties which are forbidden
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'spl_role'})
        data = jsonutils.dumps([
            {'op': 'replace', 'path': '/spl_read_prop', 'value': 'r'},
            {'op': 'replace', 'path': '/spl_update_prop', 'value': 'u'},
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code, response.text)

        # Attempt to replace, add and remove properties which are forbidden
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'spl_role'})
        data = jsonutils.dumps([
            {'op': 'add', 'path': '/spl_new_prop', 'value': 'new'},
            {'op': 'remove', 'path': '/spl_create_prop'},
            {'op': 'remove', 'path': '/spl_delete_prop'},
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code, response.text)

        # Attempt to replace properties
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'spl_role'})
        data = jsonutils.dumps([
            # Updating an empty property to verify bug #1332103.
            {'op': 'replace', 'path': '/spl_update_prop', 'value': ''},
            {'op': 'replace', 'path': '/spl_update_prop', 'value': 'u'},
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)

        # Returned subject entity should reflect the changes
        subject = jsonutils.loads(response.text)

        # 'spl_update_prop' has update permission for spl_role
        # hence the value has changed
        self.assertEqual('u', subject['spl_update_prop'])

        # Attempt to remove properties
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'spl_role'})
        data = jsonutils.dumps([
            {'op': 'remove', 'path': '/spl_delete_prop'},
            # Deleting an empty property to verify bug #1332103.
            {'op': 'remove', 'path': '/spl_delete_empty_prop'},
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)

        # Returned subject entity should reflect the changes
        subject = jsonutils.loads(response.text)

        # 'spl_delete_prop' and 'spl_delete_empty_prop' have delete
        # permission for spl_role hence the property has been deleted
        self.assertNotIn('spl_delete_prop', subject.keys())
        self.assertNotIn('spl_delete_empty_prop', subject.keys())

        # Subject Deletion should work
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # This subject should be no longer be directly accessible
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(404, response.status_code)

        self.stop_servers()

    def test_property_protections_with_policies(self):
        # Enable property protection
        self.api_server.property_protection_file = self.property_file_policies
        self.api_server.property_protection_rule_format = 'policies'
        self.start_servers(**self.__dict__.copy())

        # Subject list should be empty
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Create an subject for role member with extra props
        # Raises 403 since user is not allowed to set 'foo'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'member'})
        data = jsonutils.dumps({'name': 'subject-1', 'foo': 'bar',
                                'disk_format': 'aki',
                                'container_format': 'aki',
                                'x_owner_foo': 'o_s_bar'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code)

        # Create an subject for role member without 'foo'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'member'})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Returned subject entity
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        expected_subject = {
            'status': 'queued',
            'name': 'subject-1',
            'tags': [],
            'visibility': 'private',
            'self': '/v1/subjects/%s' % subject_id,
            'protected': False,
            'file': '/v1/subjects/%s/file' % subject_id,
            'min_disk': 0,
            'min_ram': 0,
            'schema': '/v1/schemas/subject',
        }
        for key, value in expected_subject.items():
            self.assertEqual(value, subject[key], key)

        # Create an subject for role spl_role with extra props
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'spl_role, admin'})
        data = jsonutils.dumps({'name': 'subject-1',
                                'disk_format': 'aki',
                                'container_format': 'aki',
                                'spl_creator_policy': 'creator_bar',
                                'spl_default_policy': 'default_bar'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        self.assertEqual('creator_bar', subject['spl_creator_policy'])
        self.assertEqual('default_bar', subject['spl_default_policy'])

        # Attempt to replace a property which is permitted
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps([
            # Updating an empty property to verify bug #1332103.
            {'op': 'replace', 'path': '/spl_creator_policy', 'value': ''},
            {'op': 'replace', 'path': '/spl_creator_policy', 'value': 'r'},
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)

        # Returned subject entity should reflect the changes
        subject = jsonutils.loads(response.text)

        # 'spl_creator_policy' has update permission for admin
        # hence the value has changed
        self.assertEqual('r', subject['spl_creator_policy'])

        # Attempt to replace a property which is forbidden
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'spl_role'})
        data = jsonutils.dumps([
            {'op': 'replace', 'path': '/spl_creator_policy', 'value': 'z'},
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code, response.text)

        # Attempt to read properties
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'random_role'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)

        subject = jsonutils.loads(response.text)
        # 'random_role' is allowed read 'spl_default_policy'.
        self.assertEqual(subject['spl_default_policy'], 'default_bar')
        # 'random_role' is forbidden to read 'spl_creator_policy'.
        self.assertNotIn('spl_creator_policy', subject)

        # Attempt to replace and remove properties which are permitted
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps([
            # Deleting an empty property to verify bug #1332103.
            {'op': 'replace', 'path': '/spl_creator_policy', 'value': ''},
            {'op': 'remove', 'path': '/spl_creator_policy'},
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)

        # Returned subject entity should reflect the changes
        subject = jsonutils.loads(response.text)

        # 'spl_creator_policy' has delete permission for admin
        # hence the value has been deleted
        self.assertNotIn('spl_creator_policy', subject)

        # Attempt to read a property that is permitted
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'random_role'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)

        # Returned subject entity should reflect the changes
        subject = jsonutils.loads(response.text)
        self.assertEqual(subject['spl_default_policy'], 'default_bar')

        # Subject Deletion should work
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # This subject should be no longer be directly accessible
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(404, response.status_code)

        self.stop_servers()

    def test_property_protections_special_chars_roles(self):
        # Enable property protection
        self.api_server.property_protection_file = self.property_file_roles
        self.start_servers(**self.__dict__.copy())

        # Verify both admin and unknown role can create properties marked with
        # '@'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_all_permitted_admin': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        expected_subject = {
            'status': 'queued',
            'name': 'subject-1',
            'tags': [],
            'visibility': 'private',
            'self': '/v1/subjects/%s' % subject_id,
            'protected': False,
            'file': '/v1/subjects/%s/file' % subject_id,
            'min_disk': 0,
            'x_all_permitted_admin': '1',
            'min_ram': 0,
            'schema': '/v1/schemas/subject',
        }
        for key, value in expected_subject.items():
            self.assertEqual(value, subject[key], key)
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_all_permitted_joe_soap': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        expected_subject = {
            'status': 'queued',
            'name': 'subject-1',
            'tags': [],
            'visibility': 'private',
            'self': '/v1/subjects/%s' % subject_id,
            'protected': False,
            'file': '/v1/subjects/%s/file' % subject_id,
            'min_disk': 0,
            'x_all_permitted_joe_soap': '1',
            'min_ram': 0,
            'schema': '/v1/schemas/subject',
        }
        for key, value in expected_subject.items():
            self.assertEqual(value, subject[key], key)

        # Verify both admin and unknown role can read properties marked with
        # '@'
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertEqual('1', subject['x_all_permitted_joe_soap'])
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'joe_soap'})
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertEqual('1', subject['x_all_permitted_joe_soap'])

        # Verify both admin and unknown role can update properties marked with
        # '@'
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps([
            {'op': 'replace',
             'path': '/x_all_permitted_joe_soap', 'value': '2'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)
        subject = jsonutils.loads(response.text)
        self.assertEqual('2', subject['x_all_permitted_joe_soap'])
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps([
            {'op': 'replace',
             'path': '/x_all_permitted_joe_soap', 'value': '3'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)
        subject = jsonutils.loads(response.text)
        self.assertEqual('3', subject['x_all_permitted_joe_soap'])

        # Verify both admin and unknown role can delete properties marked with
        # '@'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_all_permitted_a': '1',
            'x_all_permitted_b': '2'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps([
            {'op': 'remove', 'path': '/x_all_permitted_a'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)
        subject = jsonutils.loads(response.text)
        self.assertNotIn('x_all_permitted_a', subject.keys())
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps([
            {'op': 'remove', 'path': '/x_all_permitted_b'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)
        subject = jsonutils.loads(response.text)
        self.assertNotIn('x_all_permitted_b', subject.keys())

        # Verify neither admin nor unknown role can create a property protected
        # with '!'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_none_permitted_admin': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code)
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_none_permitted_joe_soap': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code)

        # Verify neither admin nor unknown role can read properties marked with
        # '!'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_none_read': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        self.assertNotIn('x_none_read', subject.keys())
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertNotIn('x_none_read', subject.keys())
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'joe_soap'})
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertNotIn('x_none_read', subject.keys())

        # Verify neither admin nor unknown role can update properties marked
        # with '!'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_none_update': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        self.assertEqual('1', subject['x_none_update'])
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps([
            {'op': 'replace',
             'path': '/x_none_update', 'value': '2'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code, response.text)
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps([
            {'op': 'replace',
             'path': '/x_none_update', 'value': '3'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(409, response.status_code, response.text)

        # Verify neither admin nor unknown role can delete properties marked
        # with '!'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_none_delete': '1',
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps([
            {'op': 'remove', 'path': '/x_none_delete'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code, response.text)
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps([
            {'op': 'remove', 'path': '/x_none_delete'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(409, response.status_code, response.text)

        self.stop_servers()

    def test_property_protections_special_chars_policies(self):
        # Enable property protection
        self.api_server.property_protection_file = self.property_file_policies
        self.api_server.property_protection_rule_format = 'policies'
        self.start_servers(**self.__dict__.copy())

        # Verify both admin and unknown role can create properties marked with
        # '@'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_all_permitted_admin': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        expected_subject = {
            'status': 'queued',
            'name': 'subject-1',
            'tags': [],
            'visibility': 'private',
            'self': '/v1/subjects/%s' % subject_id,
            'protected': False,
            'file': '/v1/subjects/%s/file' % subject_id,
            'min_disk': 0,
            'x_all_permitted_admin': '1',
            'min_ram': 0,
            'schema': '/v1/schemas/subject',
        }
        for key, value in expected_subject.items():
            self.assertEqual(value, subject[key], key)
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_all_permitted_joe_soap': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        expected_subject = {
            'status': 'queued',
            'name': 'subject-1',
            'tags': [],
            'visibility': 'private',
            'self': '/v1/subjects/%s' % subject_id,
            'protected': False,
            'file': '/v1/subjects/%s/file' % subject_id,
            'min_disk': 0,
            'x_all_permitted_joe_soap': '1',
            'min_ram': 0,
            'schema': '/v1/schemas/subject',
        }
        for key, value in expected_subject.items():
            self.assertEqual(value, subject[key], key)

        # Verify both admin and unknown role can read properties marked with
        # '@'
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertEqual('1', subject['x_all_permitted_joe_soap'])
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'joe_soap'})
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertEqual('1', subject['x_all_permitted_joe_soap'])

        # Verify both admin and unknown role can update properties marked with
        # '@'
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps([
            {'op': 'replace',
             'path': '/x_all_permitted_joe_soap', 'value': '2'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)
        subject = jsonutils.loads(response.text)
        self.assertEqual('2', subject['x_all_permitted_joe_soap'])
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps([
            {'op': 'replace',
             'path': '/x_all_permitted_joe_soap', 'value': '3'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)
        subject = jsonutils.loads(response.text)
        self.assertEqual('3', subject['x_all_permitted_joe_soap'])

        # Verify both admin and unknown role can delete properties marked with
        # '@'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_all_permitted_a': '1',
            'x_all_permitted_b': '2'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps([
            {'op': 'remove', 'path': '/x_all_permitted_a'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)
        subject = jsonutils.loads(response.text)
        self.assertNotIn('x_all_permitted_a', subject.keys())
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps([
            {'op': 'remove', 'path': '/x_all_permitted_b'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)
        subject = jsonutils.loads(response.text)
        self.assertNotIn('x_all_permitted_b', subject.keys())

        # Verify neither admin nor unknown role can create a property protected
        # with '!'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_none_permitted_admin': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code)
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_none_permitted_joe_soap': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code)

        # Verify neither admin nor unknown role can read properties marked with
        # '!'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_none_read': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        self.assertNotIn('x_none_read', subject.keys())
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertNotIn('x_none_read', subject.keys())
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'joe_soap'})
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertNotIn('x_none_read', subject.keys())

        # Verify neither admin nor unknown role can update properties marked
        # with '!'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_none_update': '1'
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        self.assertEqual('1', subject['x_none_update'])
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps([
            {'op': 'replace',
             'path': '/x_none_update', 'value': '2'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code, response.text)
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps([
            {'op': 'replace',
             'path': '/x_none_update', 'value': '3'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(409, response.status_code, response.text)

        # Verify neither admin nor unknown role can delete properties marked
        # with '!'
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json',
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps({
            'name': 'subject-1',
            'disk_format': 'aki',
            'container_format': 'aki',
            'x_none_delete': '1',
        })
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'admin'})
        data = jsonutils.dumps([
            {'op': 'remove', 'path': '/x_none_delete'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(403, response.status_code, response.text)
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type,
                                 'X-Roles': 'joe_soap'})
        data = jsonutils.dumps([
            {'op': 'remove', 'path': '/x_none_delete'}
        ])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(409, response.status_code, response.text)

        self.stop_servers()

    def test_tag_lifecycle(self):
        self.start_servers(**self.__dict__.copy())
        # Create an subject with a tag - duplicate should be ignored
        path = self._url('/v1/subjects')
        headers = self._headers({'Content-Type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-1', 'tags': ['sniff', 'sniff']})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject_id = jsonutils.loads(response.text)['id']

        # Subject should show a list with a single tag
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        tags = jsonutils.loads(response.text)['tags']
        self.assertEqual(['sniff'], tags)

        # Delete all tags
        for tag in tags:
            path = self._url('/v1/subjects/%s/tags/%s' % (subject_id, tag))
            response = requests.delete(path, headers=self._headers())
            self.assertEqual(204, response.status_code)

        # Update subject with too many tags via PUT
        # Configured limit is 10 tags
        for i in range(10):
            path = self._url('/v1/subjects/%s/tags/foo%i' % (subject_id, i))
            response = requests.put(path, headers=self._headers())
            self.assertEqual(204, response.status_code)

        # 11th tag should fail
        path = self._url('/v1/subjects/%s/tags/fail_me' % subject_id)
        response = requests.put(path, headers=self._headers())
        self.assertEqual(413, response.status_code)

        # Make sure the 11th tag was not added
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        tags = jsonutils.loads(response.text)['tags']
        self.assertEqual(10, len(tags))

        # Update subject tags via PATCH
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        doc = [
            {
                'op': 'replace',
                'path': '/tags',
                'value': ['foo'],
            },
        ]
        data = jsonutils.dumps(doc)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code)

        # Update subject with too many tags via PATCH
        # Configured limit is 10 tags
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        tags = ['foo%d' % i for i in range(11)]
        doc = [
            {
                'op': 'replace',
                'path': '/tags',
                'value': tags,
            },
        ]
        data = jsonutils.dumps(doc)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(413, response.status_code)

        # Tags should not have changed since request was over limit
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        tags = jsonutils.loads(response.text)['tags']
        self.assertEqual(['foo'], tags)

        # Update subject with duplicate tag - it should be ignored
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        doc = [
            {
                'op': 'replace',
                'path': '/tags',
                'value': ['sniff', 'snozz', 'snozz'],
            },
        ]
        data = jsonutils.dumps(doc)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code)
        tags = jsonutils.loads(response.text)['tags']
        self.assertEqual(['sniff', 'snozz'], sorted(tags))

        # Subject should show the appropriate tags
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        tags = jsonutils.loads(response.text)['tags']
        self.assertEqual(['sniff', 'snozz'], sorted(tags))

        # Attempt to tag the subject with a duplicate should be ignored
        path = self._url('/v1/subjects/%s/tags/snozz' % subject_id)
        response = requests.put(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # Create another more complex tag
        path = self._url('/v1/subjects/%s/tags/gabe%%40example.com' % subject_id)
        response = requests.put(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # Double-check that the tags container on the subject is populated
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        tags = jsonutils.loads(response.text)['tags']
        self.assertEqual(['gabe@example.com', 'sniff', 'snozz'],
                         sorted(tags))

        # Query subjects by single tag
        path = self._url('/v1/subjects?tag=sniff')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual('subject-1', subjects[0]['name'])

        # Query subjects by multiple tags
        path = self._url('/v1/subjects?tag=sniff&tag=snozz')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual('subject-1', subjects[0]['name'])

        # Query subjects by tag and other attributes
        path = self._url('/v1/subjects?tag=sniff&status=queued')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual('subject-1', subjects[0]['name'])

        # Query subjects by tag and a nonexistent tag
        path = self._url('/v1/subjects?tag=sniff&tag=fake')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # The tag should be deletable
        path = self._url('/v1/subjects/%s/tags/gabe%%40example.com' % subject_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # List of tags should reflect the deletion
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        tags = jsonutils.loads(response.text)['tags']
        self.assertEqual(['sniff', 'snozz'], sorted(tags))

        # Deleting the same tag should return a 404
        path = self._url('/v1/subjects/%s/tags/gabe%%40example.com' % subject_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(404, response.status_code)

        # The tags won't be able to query the subjects after deleting
        path = self._url('/v1/subjects?tag=gabe%%40example.com')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Try to add a tag that is too long
        big_tag = 'a' * 300
        path = self._url('/v1/subjects/%s/tags/%s' % (subject_id, big_tag))
        response = requests.put(path, headers=self._headers())
        self.assertEqual(400, response.status_code)

        # Tags should not have changed since request was over limit
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        tags = jsonutils.loads(response.text)['tags']
        self.assertEqual(['sniff', 'snozz'], sorted(tags))

        self.stop_servers()

    def test_subjects_container(self):
        # Subject list should be empty and no next link should be present
        self.start_servers(**self.__dict__.copy())
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        first = jsonutils.loads(response.text)['first']
        self.assertEqual(0, len(subjects))
        self.assertNotIn('next', jsonutils.loads(response.text))
        self.assertEqual('/v1/subjects', first)

        # Create 7 subjects
        subjects = []
        fixtures = [
            {'name': 'subject-3', 'type': 'kernel', 'ping': 'pong',
             'container_format': 'ami', 'disk_format': 'ami'},
            {'name': 'subject-4', 'type': 'kernel', 'ping': 'pong',
             'container_format': 'bare', 'disk_format': 'ami'},
            {'name': 'subject-1', 'type': 'kernel', 'ping': 'pong'},
            {'name': 'subject-3', 'type': 'ramdisk', 'ping': 'pong'},
            {'name': 'subject-2', 'type': 'kernel', 'ping': 'ding'},
            {'name': 'subject-3', 'type': 'kernel', 'ping': 'pong'},
            {'name': 'subject-2,subject-5', 'type': 'kernel', 'ping': 'pong'},
        ]
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        for fixture in fixtures:
            data = jsonutils.dumps(fixture)
            response = requests.post(path, headers=headers, data=data)
            self.assertEqual(201, response.status_code)
            subjects.append(jsonutils.loads(response.text))

        # Subject list should contain 7 subjects
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertEqual(7, len(body['subjects']))
        self.assertEqual('/v1/subjects', body['first'])
        self.assertNotIn('next', jsonutils.loads(response.text))

        # Subject list filters by created_at time
        url_template = '/v1/subjects?created_at=lt:%s'
        path = self._url(url_template % subjects[0]['created_at'])
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertEqual(0, len(body['subjects']))
        self.assertEqual(url_template % subjects[0]['created_at'],
                         urllib.parse.unquote(body['first']))

        # Subject list filters by updated_at time
        url_template = '/v1/subjects?updated_at=lt:%s'
        path = self._url(url_template % subjects[2]['updated_at'])
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertGreaterEqual(3, len(body['subjects']))
        self.assertEqual(url_template % subjects[2]['updated_at'],
                         urllib.parse.unquote(body['first']))

        # Subject list filters by updated_at and created time with invalid value
        url_template = '/v1/subjects?%s=lt:invalid_value'
        for filter in ['updated_at', 'created_at']:
            path = self._url(url_template % filter)
            response = requests.get(path, headers=self._headers())
            self.assertEqual(400, response.status_code)

        # Subject list filters by updated_at and created_at with invalid operator
        url_template = '/v1/subjects?%s=invalid_operator:2015-11-19T12:24:02Z'
        for filter in ['updated_at', 'created_at']:
            path = self._url(url_template % filter)
            response = requests.get(path, headers=self._headers())
            self.assertEqual(400, response.status_code)

        # Subject list filters by non-'URL encoding' value
        path = self._url('/v1/subjects?name=%FF')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(400, response.status_code)

        # Subject list filters by name with in operator
        url_template = '/v1/subjects?name=in:%s'
        filter_value = 'subject-1,subject-2'
        path = self._url(url_template % filter_value)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertGreaterEqual(3, len(body['subjects']))

        # Subject list filters by container_format with in operator
        url_template = '/v1/subjects?container_format=in:%s'
        filter_value = 'bare,ami'
        path = self._url(url_template % filter_value)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertGreaterEqual(2, len(body['subjects']))

        # Subject list filters by disk_format with in operator
        url_template = '/v1/subjects?disk_format=in:%s'
        filter_value = 'bare,ami,iso'
        path = self._url(url_template % filter_value)
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertGreaterEqual(2, len(body['subjects']))

        # Begin pagination after the first subject
        template_url = ('/v1/subjects?limit=2&sort_dir=asc&sort_key=name'
                        '&marker=%s&type=kernel&ping=pong')
        path = self._url(template_url % subjects[2]['id'])
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertEqual(2, len(body['subjects']))
        response_ids = [subject['id'] for subject in body['subjects']]
        self.assertEqual([subjects[6]['id'], subjects[0]['id']], response_ids)

        # Continue pagination using next link from previous request
        path = self._url(body['next'])
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertEqual(2, len(body['subjects']))
        response_ids = [subject['id'] for subject in body['subjects']]
        self.assertEqual([subjects[5]['id'], subjects[1]['id']], response_ids)

        # Continue pagination - expect no results
        path = self._url(body['next'])
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertEqual(0, len(body['subjects']))

        # Delete first subject
        path = self._url('/v1/subjects/%s' % subjects[0]['id'])
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

        # Ensure bad request for using a deleted subject as marker
        path = self._url('/v1/subjects?marker=%s' % subjects[0]['id'])
        response = requests.get(path, headers=self._headers())
        self.assertEqual(400, response.status_code)

        self.stop_servers()

    def test_subject_visibility_to_different_users(self):
        self.cleanup()
        self.api_server.deployment_flavor = 'fakeauth'
        self.registry_server.deployment_flavor = 'fakeauth'

        kwargs = self.__dict__.copy()
        kwargs['use_user_token'] = True
        self.start_servers(**kwargs)

        owners = ['admin', 'tenant1', 'tenant2', 'none']
        visibilities = ['public', 'private']

        for owner in owners:
            for visibility in visibilities:
                path = self._url('/v1/subjects')
                headers = self._headers({
                    'content-type': 'application/json',
                    'X-Auth-Token': 'createuser:%s:admin' % owner,
                })
                data = jsonutils.dumps({
                    'name': '%s-%s' % (owner, visibility),
                    'visibility': visibility,
                })
                response = requests.post(path, headers=headers, data=data)
                self.assertEqual(201, response.status_code)

        def list_subjects(tenant, role='', visibility=None):
            auth_token = 'user:%s:%s' % (tenant, role)
            headers = {'X-Auth-Token': auth_token}
            path = self._url('/v1/subjects')
            if visibility is not None:
                path += '?visibility=%s' % visibility
            response = requests.get(path, headers=headers)
            self.assertEqual(200, response.status_code)
            return jsonutils.loads(response.text)['subjects']

        # 1. Known user sees public and their own subjects
        subjects = list_subjects('tenant1')
        self.assertEqual(5, len(subjects))
        for subject in subjects:
            self.assertTrue(subject['visibility'] == 'public'
                            or 'tenant1' in subject['name'])

        # 2. Known user, visibility=public, sees all public subjects
        subjects = list_subjects('tenant1', visibility='public')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertEqual('public', subject['visibility'])

        # 3. Known user, visibility=private, sees only their private subject
        subjects = list_subjects('tenant1', visibility='private')
        self.assertEqual(1, len(subjects))
        subject = subjects[0]
        self.assertEqual('private', subject['visibility'])
        self.assertIn('tenant1', subject['name'])

        # 4. Unknown user sees only public subjects
        subjects = list_subjects('none')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertEqual('public', subject['visibility'])

        # 5. Unknown user, visibility=public, sees only public subjects
        subjects = list_subjects('none', visibility='public')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertEqual('public', subject['visibility'])

        # 6. Unknown user, visibility=private, sees no subjects
        subjects = list_subjects('none', visibility='private')
        self.assertEqual(0, len(subjects))

        # 7. Unknown admin sees all subjects
        subjects = list_subjects('none', role='admin')
        self.assertEqual(8, len(subjects))

        # 8. Unknown admin, visibility=public, shows only public subjects
        subjects = list_subjects('none', role='admin', visibility='public')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertEqual('public', subject['visibility'])

        # 9. Unknown admin, visibility=private, sees only private subjects
        subjects = list_subjects('none', role='admin', visibility='private')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertEqual('private', subject['visibility'])

        # 10. Known admin sees all subjects
        subjects = list_subjects('admin', role='admin')
        self.assertEqual(8, len(subjects))

        # 11. Known admin, visibility=public, sees all public subjects
        subjects = list_subjects('admin', role='admin', visibility='public')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertEqual('public', subject['visibility'])

        # 12. Known admin, visibility=private, sees all private subjects
        subjects = list_subjects('admin', role='admin', visibility='private')
        self.assertEqual(4, len(subjects))
        for subject in subjects:
            self.assertEqual('private', subject['visibility'])

        self.stop_servers()

    def test_update_locations(self):
        self.api_server.show_multiple_locations = True
        self.start_servers(**self.__dict__.copy())
        # Create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Returned subject entity should have a generated id and status
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        self.assertEqual('queued', subject['status'])
        self.assertIsNone(subject['size'])
        self.assertIsNone(subject['virtual_size'])

        # Update locations for the queued subject
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        url = 'http://127.0.0.1:%s/foo_subject' % self.http_port0
        data = jsonutils.dumps([{'op': 'replace', 'path': '/locations',
                                 'value': [{'url': url, 'metadata': {}}]
                                 }])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code, response.text)

        # The subject size should be updated
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertEqual(10, subject['size'])

    def test_update_locations_with_restricted_sources(self):
        self.api_server.show_multiple_locations = True
        self.start_servers(**self.__dict__.copy())
        # Create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-1', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Returned subject entity should have a generated id and status
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']
        self.assertEqual('queued', subject['status'])
        self.assertIsNone(subject['size'])
        self.assertIsNone(subject['virtual_size'])

        # Update locations for the queued subject
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        data = jsonutils.dumps([{'op': 'replace', 'path': '/locations',
                                 'value': [{'url': 'file:///foo_subject',
                                            'metadata': {}}]
                                 }])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(400, response.status_code, response.text)

        data = jsonutils.dumps([{'op': 'replace', 'path': '/locations',
                                 'value': [{'url': 'swift+config:///foo_subject',
                                            'metadata': {}}]
                                 }])
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(400, response.status_code, response.text)


class TestSubjectsWithRegistry(TestSubjects):
    def setUp(self):
        super(TestSubjectsWithRegistry, self).setUp()
        self.api_server.data_api = (
            'subject.tests.functional.v1.registry_data_api')
        self.registry_server.deployment_flavor = 'trusted-auth'


class TestSubjectDirectURLVisibility(functional.FunctionalTest):

    def setUp(self):
        super(TestSubjectDirectURLVisibility, self).setUp()
        self.cleanup()
        self.api_server.deployment_flavor = 'noauth'

    def _url(self, path):
        return 'http://127.0.0.1:%d%s' % (self.api_port, path)

    def _headers(self, custom_headers=None):
        base_headers = {
            'X-Identity-Status': 'Confirmed',
            'X-Auth-Token': '932c5c84-02ac-4fe5-a9ba-620af0e2bb96',
            'X-User-Id': 'f9a41d13-0c13-47e9-bee2-ce4e8bfe958e',
            'X-Tenant-Id': TENANT1,
            'X-Roles': 'member',
        }
        base_headers.update(custom_headers or {})
        return base_headers

    def test_v2_not_enabled(self):
        self.api_server.enable_v2_api = False
        self.start_servers(**self.__dict__.copy())
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(300, response.status_code)
        self.stop_servers()

    def test_v2_enabled(self):
        self.api_server.enable_v2_api = True
        self.start_servers(**self.__dict__.copy())
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        self.stop_servers()

    def test_subject_direct_url_visible(self):

        self.api_server.show_subject_direct_url = True
        self.start_servers(**self.__dict__.copy())

        # Subject list should be empty
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-1', 'type': 'kernel',
                                'foo': 'bar', 'disk_format': 'aki',
                                'container_format': 'aki',
                                'visibility': 'public'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Get the subject id
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # Subject direct_url should not be visible before location is set
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'Content-Type': 'application/json'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertNotIn('direct_url', subject)

        # Upload some subject data, setting the subject location
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.put(path, headers=headers, data='ZZZZZ')
        self.assertEqual(204, response.status_code)

        # Subject direct_url should be visible
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'Content-Type': 'application/json'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertIn('direct_url', subject)

        # Subject direct_url should be visible to non-owner, non-admin user
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'Content-Type': 'application/json',
                                 'X-Tenant-Id': TENANT2})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertIn('direct_url', subject)

        # Subject direct_url should be visible in a list
        path = self._url('/v1/subjects')
        headers = self._headers({'Content-Type': 'application/json'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)['subjects'][0]
        self.assertIn('direct_url', subject)

        self.stop_servers()

    def test_subject_multiple_location_url_visible(self):
        self.api_server.show_multiple_locations = True
        self.start_servers(**self.__dict__.copy())

        # Create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-1', 'type': 'kernel',
                                'foo': 'bar', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Get the subject id
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # Subject locations should not be visible before location is set
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'Content-Type': 'application/json'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertIn('locations', subject)
        self.assertEqual([], subject["locations"])

        # Upload some subject data, setting the subject location
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.put(path, headers=headers, data='ZZZZZ')
        self.assertEqual(204, response.status_code)

        # Subject locations should be visible
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'Content-Type': 'application/json'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertIn('locations', subject)
        loc = subject['locations']
        self.assertGreater(len(loc), 0)
        loc = loc[0]
        self.assertIn('url', loc)
        self.assertIn('metadata', loc)

        self.stop_servers()

    def test_subject_direct_url_not_visible(self):

        self.api_server.show_subject_direct_url = False
        self.start_servers(**self.__dict__.copy())

        # Subject list should be empty
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-1', 'type': 'kernel',
                                'foo': 'bar', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Get the subject id
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # Upload some subject data, setting the subject location
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.put(path, headers=headers, data='ZZZZZ')
        self.assertEqual(204, response.status_code)

        # Subject direct_url should not be visible
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'Content-Type': 'application/json'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertNotIn('direct_url', subject)

        # Subject direct_url should not be visible in a list
        path = self._url('/v1/subjects')
        headers = self._headers({'Content-Type': 'application/json'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)['subjects'][0]
        self.assertNotIn('direct_url', subject)

        self.stop_servers()


class TestSubjectDirectURLVisibilityWithRegistry(TestSubjectDirectURLVisibility):
    def setUp(self):
        super(TestSubjectDirectURLVisibilityWithRegistry, self).setUp()
        self.api_server.data_api = (
            'subject.tests.functional.v1.registry_data_api')
        self.registry_server.deployment_flavor = 'trusted-auth'


class TestSubjectLocationSelectionStrategy(functional.FunctionalTest):

    def setUp(self):
        super(TestSubjectLocationSelectionStrategy, self).setUp()
        self.cleanup()
        self.api_server.deployment_flavor = 'noauth'
        for i in range(3):
            ret = test_utils.start_http_server("foo_subject_id%d" % i,
                                               "foo_subject%d" % i)
            setattr(self, 'http_server%d_pid' % i, ret[0])
            setattr(self, 'http_port%d' % i, ret[1])

    def tearDown(self):
        for i in range(3):
            pid = getattr(self, 'http_server%d_pid' % i, None)
            if pid:
                os.kill(pid, signal.SIGKILL)

        super(TestSubjectLocationSelectionStrategy, self).tearDown()

    def _url(self, path):
        return 'http://127.0.0.1:%d%s' % (self.api_port, path)

    def _headers(self, custom_headers=None):
        base_headers = {
            'X-Identity-Status': 'Confirmed',
            'X-Auth-Token': '932c5c84-02ac-4fe5-a9ba-620af0e2bb96',
            'X-User-Id': 'f9a41d13-0c13-47e9-bee2-ce4e8bfe958e',
            'X-Tenant-Id': TENANT1,
            'X-Roles': 'member',
        }
        base_headers.update(custom_headers or {})
        return base_headers

    def test_subject_locations_with_order_strategy(self):
        self.api_server.show_subject_direct_url = True
        self.api_server.show_multiple_locations = True
        self.subject_location_quota = 10
        self.api_server.location_strategy = 'location_order'
        preference = "http, swift, filesystem"
        self.api_server.store_type_location_strategy_preference = preference
        self.start_servers(**self.__dict__.copy())

        # Create an subject
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'subject-1', 'type': 'kernel',
                                'foo': 'bar', 'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)

        # Get the subject id
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # Subject locations should not be visible before location is set
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'Content-Type': 'application/json'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertIn('locations', subject)
        self.assertEqual([], subject["locations"])

        # Update subject locations via PATCH
        path = self._url('/v1/subjects/%s' % subject_id)
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        values = [{'url': 'http://127.0.0.1:%s/foo_subject' % self.http_port0,
                   'metadata': {}},
                  {'url': 'http://127.0.0.1:%s/foo_subject' % self.http_port1,
                   'metadata': {}}]
        doc = [{'op': 'replace',
                'path': '/locations',
                'value': values}]
        data = jsonutils.dumps(doc)
        response = requests.patch(path, headers=headers, data=data)
        self.assertEqual(200, response.status_code)

        # Subject locations should be visible
        path = self._url('/v1/subjects/%s' % subject_id)
        headers = self._headers({'Content-Type': 'application/json'})
        response = requests.get(path, headers=headers)
        self.assertEqual(200, response.status_code)
        subject = jsonutils.loads(response.text)
        self.assertIn('locations', subject)
        self.assertEqual(values, subject['locations'])
        self.assertIn('direct_url', subject)
        self.assertEqual(values[0]['url'], subject['direct_url'])

        self.stop_servers()


class TestSubjectLocationSelectionStrategyWithRegistry(
        TestSubjectLocationSelectionStrategy):
    def setUp(self):
        super(TestSubjectLocationSelectionStrategyWithRegistry, self).setUp()
        self.api_server.data_api = (
            'subject.tests.functional.v1.registry_data_api')
        self.registry_server.deployment_flavor = 'trusted-auth'


class TestSubjectMembers(functional.FunctionalTest):

    def setUp(self):
        super(TestSubjectMembers, self).setUp()
        self.cleanup()
        self.api_server.deployment_flavor = 'fakeauth'
        self.registry_server.deployment_flavor = 'fakeauth'
        self.start_servers(**self.__dict__.copy())

    def _url(self, path):
        return 'http://127.0.0.1:%d%s' % (self.api_port, path)

    def _headers(self, custom_headers=None):
        base_headers = {
            'X-Identity-Status': 'Confirmed',
            'X-Auth-Token': '932c5c84-02ac-4fe5-a9ba-620af0e2bb96',
            'X-User-Id': 'f9a41d13-0c13-47e9-bee2-ce4e8bfe958e',
            'X-Tenant-Id': TENANT1,
            'X-Roles': 'member',
        }
        base_headers.update(custom_headers or {})
        return base_headers

    def test_subject_member_lifecycle(self):

        def get_header(tenant, role=''):
            auth_token = 'user:%s:%s' % (tenant, role)
            headers = {'X-Auth-Token': auth_token}
            return headers

        # Subject list should be empty
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=get_header('tenant1'))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        owners = ['tenant1', 'tenant2', 'admin']
        visibilities = ['public', 'private']
        subject_fixture = []
        for owner in owners:
            for visibility in visibilities:
                path = self._url('/v1/subjects')
                headers = self._headers({
                    'content-type': 'application/json',
                    'X-Auth-Token': 'createuser:%s:admin' % owner,
                })
                data = jsonutils.dumps({
                    'name': '%s-%s' % (owner, visibility),
                    'visibility': visibility,
                })
                response = requests.post(path, headers=headers, data=data)
                self.assertEqual(201, response.status_code)
                subject_fixture.append(jsonutils.loads(response.text))

        # Subject list should contain 4 subjects for tenant1
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=get_header('tenant1'))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(4, len(subjects))

        # Subject list should contain 3 subjects for TENANT3
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=get_header(TENANT3))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(3, len(subjects))

        # Add Subject member for tenant1-private subject
        path = self._url('/v1/subjects/%s/members' % subject_fixture[1]['id'])
        body = jsonutils.dumps({'member': TENANT3})
        response = requests.post(path, headers=get_header('tenant1'),
                                 data=body)
        self.assertEqual(200, response.status_code)
        subject_member = jsonutils.loads(response.text)
        self.assertEqual(subject_fixture[1]['id'], subject_member['subject_id'])
        self.assertEqual(TENANT3, subject_member['member_id'])
        self.assertIn('created_at', subject_member)
        self.assertIn('updated_at', subject_member)
        self.assertEqual('pending', subject_member['status'])

        # Subject list should contain 3 subjects for TENANT3
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=get_header(TENANT3))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(3, len(subjects))

        # Subject list should contain 0 shared subjects for TENANT3
        # because default is accepted
        path = self._url('/v1/subjects?visibility=shared')
        response = requests.get(path, headers=get_header(TENANT3))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Subject list should contain 4 subjects for TENANT3 with status pending
        path = self._url('/v1/subjects?member_status=pending')
        response = requests.get(path, headers=get_header(TENANT3))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(4, len(subjects))

        # Subject list should contain 4 subjects for TENANT3 with status all
        path = self._url('/v1/subjects?member_status=all')
        response = requests.get(path, headers=get_header(TENANT3))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(4, len(subjects))

        # Subject list should contain 1 subject for TENANT3 with status pending
        # and visibility shared
        path = self._url('/v1/subjects?member_status=pending&visibility=shared')
        response = requests.get(path, headers=get_header(TENANT3))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subjects[0]['name'], 'tenant1-private')

        # Subject list should contain 0 subject for TENANT3 with status rejected
        # and visibility shared
        path = self._url('/v1/subjects?member_status=rejected&visibility=shared')
        response = requests.get(path, headers=get_header(TENANT3))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Subject list should contain 0 subject for TENANT3 with status accepted
        # and visibility shared
        path = self._url('/v1/subjects?member_status=accepted&visibility=shared')
        response = requests.get(path, headers=get_header(TENANT3))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Subject list should contain 0 subject for TENANT3 with status accepted
        # and visibility private
        path = self._url('/v1/subjects?visibility=private')
        response = requests.get(path, headers=get_header(TENANT3))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Subject tenant2-private's subject members list should contain no members
        path = self._url('/v1/subjects/%s/members' % subject_fixture[3]['id'])
        response = requests.get(path, headers=get_header('tenant2'))
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertEqual(0, len(body['members']))

        # Tenant 1, who is the owner cannot change status of subject member
        path = self._url('/v1/subjects/%s/members/%s' % (subject_fixture[1]['id'],
                                                       TENANT3))
        body = jsonutils.dumps({'status': 'accepted'})
        response = requests.put(path, headers=get_header('tenant1'), data=body)
        self.assertEqual(403, response.status_code)

        # Tenant 1, who is the owner can get status of its own subject member
        path = self._url('/v1/subjects/%s/members/%s' % (subject_fixture[1]['id'],
                                                       TENANT3))
        response = requests.get(path, headers=get_header('tenant1'))
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertEqual('pending', body['status'])
        self.assertEqual(subject_fixture[1]['id'], body['subject_id'])
        self.assertEqual(TENANT3, body['member_id'])

        # Tenant 3, who is the member can get status of its own status
        path = self._url('/v1/subjects/%s/members/%s' % (subject_fixture[1]['id'],
                                                       TENANT3))
        response = requests.get(path, headers=get_header(TENANT3))
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertEqual('pending', body['status'])
        self.assertEqual(subject_fixture[1]['id'], body['subject_id'])
        self.assertEqual(TENANT3, body['member_id'])

        # Tenant 2, who not the owner cannot get status of subject member
        path = self._url('/v1/subjects/%s/members/%s' % (subject_fixture[1]['id'],
                                                       TENANT3))
        response = requests.get(path, headers=get_header('tenant2'))
        self.assertEqual(404, response.status_code)

        # Tenant 3 can change status of subject member
        path = self._url('/v1/subjects/%s/members/%s' % (subject_fixture[1]['id'],
                                                       TENANT3))
        body = jsonutils.dumps({'status': 'accepted'})
        response = requests.put(path, headers=get_header(TENANT3), data=body)
        self.assertEqual(200, response.status_code)
        subject_member = jsonutils.loads(response.text)
        self.assertEqual(subject_fixture[1]['id'], subject_member['subject_id'])
        self.assertEqual(TENANT3, subject_member['member_id'])
        self.assertEqual('accepted', subject_member['status'])

        # Subject list should contain 4 subjects for TENANT3 because status is
        # accepted
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=get_header(TENANT3))
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(4, len(subjects))

        # Tenant 3 invalid status change
        path = self._url('/v1/subjects/%s/members/%s' % (subject_fixture[1]['id'],
                                                       TENANT3))
        body = jsonutils.dumps({'status': 'invalid-status'})
        response = requests.put(path, headers=get_header(TENANT3), data=body)
        self.assertEqual(400, response.status_code)

        # Owner cannot change status of subject
        path = self._url('/v1/subjects/%s/members/%s' % (subject_fixture[1]['id'],
                                                       TENANT3))
        body = jsonutils.dumps({'status': 'accepted'})
        response = requests.put(path, headers=get_header('tenant1'), data=body)
        self.assertEqual(403, response.status_code)

        # Add Subject member for tenant2-private subject
        path = self._url('/v1/subjects/%s/members' % subject_fixture[3]['id'])
        body = jsonutils.dumps({'member': TENANT4})
        response = requests.post(path, headers=get_header('tenant2'),
                                 data=body)
        self.assertEqual(200, response.status_code)
        subject_member = jsonutils.loads(response.text)
        self.assertEqual(subject_fixture[3]['id'], subject_member['subject_id'])
        self.assertEqual(TENANT4, subject_member['member_id'])
        self.assertIn('created_at', subject_member)
        self.assertIn('updated_at', subject_member)

        # Add Subject member to public subject
        path = self._url('/v1/subjects/%s/members' % subject_fixture[0]['id'])
        body = jsonutils.dumps({'member': TENANT2})
        response = requests.post(path, headers=get_header('tenant1'),
                                 data=body)
        self.assertEqual(403, response.status_code)

        # Subject tenant1-private's members list should contain 1 member
        path = self._url('/v1/subjects/%s/members' % subject_fixture[1]['id'])
        response = requests.get(path, headers=get_header('tenant1'))
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertEqual(1, len(body['members']))

        # Admin can see any members
        path = self._url('/v1/subjects/%s/members' % subject_fixture[1]['id'])
        response = requests.get(path, headers=get_header('tenant1', 'admin'))
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertEqual(1, len(body['members']))

        # Subject members not found for private subject not owned by TENANT 1
        path = self._url('/v1/subjects/%s/members' % subject_fixture[3]['id'])
        response = requests.get(path, headers=get_header('tenant1'))
        self.assertEqual(404, response.status_code)

        # Subject members forbidden for public subject
        path = self._url('/v1/subjects/%s/members' % subject_fixture[0]['id'])
        response = requests.get(path, headers=get_header('tenant1'))
        self.assertIn("Public subjects do not have members", response.text)
        self.assertEqual(403, response.status_code)

        # Subject Member Cannot delete Subject membership
        path = self._url('/v1/subjects/%s/members/%s' % (subject_fixture[1]['id'],
                                                       TENANT3))
        response = requests.delete(path, headers=get_header(TENANT3))
        self.assertEqual(403, response.status_code)

        # Delete Subject member
        path = self._url('/v1/subjects/%s/members/%s' % (subject_fixture[1]['id'],
                                                       TENANT3))
        response = requests.delete(path, headers=get_header('tenant1'))
        self.assertEqual(204, response.status_code)

        # Now the subject has no members
        path = self._url('/v1/subjects/%s/members' % subject_fixture[1]['id'])
        response = requests.get(path, headers=get_header('tenant1'))
        self.assertEqual(200, response.status_code)
        body = jsonutils.loads(response.text)
        self.assertEqual(0, len(body['members']))

        # Adding 11 subject members should fail since configured limit is 10
        path = self._url('/v1/subjects/%s/members' % subject_fixture[1]['id'])
        for i in range(10):
            body = jsonutils.dumps({'member': str(uuid.uuid4())})
            response = requests.post(path, headers=get_header('tenant1'),
                                     data=body)
            self.assertEqual(200, response.status_code)

        body = jsonutils.dumps({'member': str(uuid.uuid4())})
        response = requests.post(path, headers=get_header('tenant1'),
                                 data=body)
        self.assertEqual(413, response.status_code)

        # Get Subject member should return not found for public subject
        path = self._url('/v1/subjects/%s/members/%s' % (subject_fixture[0]['id'],
                                                       TENANT3))
        response = requests.get(path, headers=get_header('tenant1'))
        self.assertEqual(404, response.status_code)

        # Delete Subject member should return forbidden for public subject
        path = self._url('/v1/subjects/%s/members/%s' % (subject_fixture[0]['id'],
                                                       TENANT3))
        response = requests.delete(path, headers=get_header('tenant1'))
        self.assertEqual(403, response.status_code)

        self.stop_servers()


class TestSubjectMembersWithRegistry(TestSubjectMembers):
    def setUp(self):
        super(TestSubjectMembersWithRegistry, self).setUp()
        self.api_server.data_api = (
            'subject.tests.functional.v1.registry_data_api')
        self.registry_server.deployment_flavor = 'trusted-auth'


class TestQuotas(functional.FunctionalTest):

    def setUp(self):
        super(TestQuotas, self).setUp()
        self.cleanup()
        self.api_server.deployment_flavor = 'noauth'
        self.registry_server.deployment_flavor = 'trusted-auth'
        self.user_storage_quota = 100
        self.start_servers(**self.__dict__.copy())

    def _url(self, path):
        return 'http://127.0.0.1:%d%s' % (self.api_port, path)

    def _headers(self, custom_headers=None):
        base_headers = {
            'X-Identity-Status': 'Confirmed',
            'X-Auth-Token': '932c5c84-02ac-4fe5-a9ba-620af0e2bb96',
            'X-User-Id': 'f9a41d13-0c13-47e9-bee2-ce4e8bfe958e',
            'X-Tenant-Id': TENANT1,
            'X-Roles': 'member',
        }
        base_headers.update(custom_headers or {})
        return base_headers

    def _upload_subject_test(self, data_src, expected_status):
        # Subject list should be empty
        path = self._url('/v1/subjects')
        response = requests.get(path, headers=self._headers())
        self.assertEqual(200, response.status_code)
        subjects = jsonutils.loads(response.text)['subjects']
        self.assertEqual(0, len(subjects))

        # Create an subject (with a deployer-defined property)
        path = self._url('/v1/subjects')
        headers = self._headers({'content-type': 'application/json'})
        data = jsonutils.dumps({'name': 'testimg',
                                'type': 'kernel',
                                'foo': 'bar',
                                'disk_format': 'aki',
                                'container_format': 'aki'})
        response = requests.post(path, headers=headers, data=data)
        self.assertEqual(201, response.status_code)
        subject = jsonutils.loads(response.text)
        subject_id = subject['id']

        # upload data
        path = self._url('/v1/subjects/%s/file' % subject_id)
        headers = self._headers({'Content-Type': 'application/octet-stream'})
        response = requests.put(path, headers=headers, data=data_src)
        self.assertEqual(expected_status, response.status_code)

        # Deletion should work
        path = self._url('/v1/subjects/%s' % subject_id)
        response = requests.delete(path, headers=self._headers())
        self.assertEqual(204, response.status_code)

    def test_subject_upload_under_quota(self):
        data = 'x' * (self.user_storage_quota - 1)
        self._upload_subject_test(data, 204)

    def test_subject_upload_exceed_quota(self):
        data = 'x' * (self.user_storage_quota + 1)
        self._upload_subject_test(data, 413)

    def test_chunked_subject_upload_under_quota(self):
        def data_gen():
            yield 'x' * (self.user_storage_quota - 1)

        self._upload_subject_test(data_gen(), 204)

    def test_chunked_subject_upload_exceed_quota(self):
        def data_gen():
            yield 'x' * (self.user_storage_quota + 1)

        self._upload_subject_test(data_gen(), 413)


class TestQuotasWithRegistry(TestQuotas):
    def setUp(self):
        super(TestQuotasWithRegistry, self).setUp()
        self.api_server.data_api = (
            'subject.tests.functional.v1.registry_data_api')
        self.registry_server.deployment_flavor = 'trusted-auth'
