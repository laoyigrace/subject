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

"""
Tests a Glance API server which uses the caching middleware that
uses the default SQLite cache driver. We use the filesystem store,
but that is really not relevant, as the subject cache is transparent
to the backend store.
"""

import hashlib
import os
import shutil
import sys
import time

import httplib2
from oslo_serialization import jsonutils
from oslo_utils import units
# NOTE(jokke): simplified transition to py3, behaves like py2 xrange
from six.moves import range

from subject.tests import functional
from subject.tests.functional.store_utils import get_http_uri
from subject.tests.functional.store_utils import setup_http
from subject.tests.utils import execute
from subject.tests.utils import minimal_headers
from subject.tests.utils import skip_if_disabled
from subject.tests.utils import xattr_writes_supported

FIVE_KB = 5 * units.Ki


class BaseCacheMiddlewareTest(object):

    @skip_if_disabled
    def test_cache_middleware_transparent_v1(self):
        """
        We test that putting the cache middleware into the
        application pipeline gives us transparent subject caching
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        # Add an subject and verify a 200 OK is returned
        subject_data = "*" * FIVE_KB
        headers = minimal_headers('Image1')
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=subject_data)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subject']['checksum'])
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("Image1", data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])

        subject_id = data['subject']['id']

        # Verify subject not in cache
        subject_cached_path = os.path.join(self.api_server.subject_cache_dir,
                                         subject_id)
        self.assertFalse(os.path.exists(subject_cached_path))

        # Grab the subject
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        # Verify subject now in cache
        subject_cached_path = os.path.join(self.api_server.subject_cache_dir,
                                         subject_id)

        # You might wonder why the heck this is here... well, it's here
        # because it took me forever to figure out that the disk write
        # cache in Linux was causing random failures of the os.path.exists
        # assert directly below this. Basically, since the cache is writing
        # the subject file to disk in a different process, the write buffers
        # don't flush the cache file during an os.rename() properly, resulting
        # in a false negative on the file existence check below. This little
        # loop pauses the execution of this process for no more than 1.5
        # seconds. If after that time the cached subject file still doesn't
        # appear on disk, something really is wrong, and the assert should
        # trigger...
        i = 0
        while not os.path.exists(subject_cached_path) and i < 30:
            time.sleep(0.05)
            i = i + 1

        self.assertTrue(os.path.exists(subject_cached_path))

        # Now, we delete the subject from the server and verify that
        # the subject cache no longer contains the deleted subject
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        self.assertFalse(os.path.exists(subject_cached_path))

        self.stop_servers()

    @skip_if_disabled
    def test_cache_middleware_transparent_v2(self):
        """Ensure the v1 API subject transfer calls trigger caching"""
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        # Add an subject and verify success
        path = "http://%s:%d/v1/subjects" % ("0.0.0.0", self.api_port)
        http = httplib2.Http()
        headers = {'content-type': 'application/json'}
        subject_entity = {
            'name': 'Image1',
            'visibility': 'public',
            'container_format': 'bare',
            'disk_format': 'raw',
        }
        response, content = http.request(path, 'POST',
                                         headers=headers,
                                         body=jsonutils.dumps(subject_entity))
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['id']

        path = "http://%s:%d/v1/subjects/%s/file" % ("0.0.0.0", self.api_port,
                                                   subject_id)
        headers = {'content-type': 'application/octet-stream'}
        subject_data = "*" * FIVE_KB
        response, content = http.request(path, 'PUT',
                                         headers=headers,
                                         body=subject_data)
        self.assertEqual(204, response.status)

        # Verify subject not in cache
        subject_cached_path = os.path.join(self.api_server.subject_cache_dir,
                                         subject_id)
        self.assertFalse(os.path.exists(subject_cached_path))

        # Grab the subject
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        # Verify subject now in cache
        subject_cached_path = os.path.join(self.api_server.subject_cache_dir,
                                         subject_id)

        # Now, we delete the subject from the server and verify that
        # the subject cache no longer contains the deleted subject
        path = "http://%s:%d/v1/subjects/%s" % ("0.0.0.0", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(204, response.status)

        self.assertFalse(os.path.exists(subject_cached_path))

        self.stop_servers()

    @skip_if_disabled
    def test_cache_remote_subject(self):
        """
        We test that caching is no longer broken for remote subjects
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        setup_http(self)

        # Add a remote subject and verify a 201 Created is returned
        remote_uri = get_http_uri(self, '2')
        headers = {'X-Subject-Meta-Name': 'Image2',
                   'X-Subject-Meta-disk_format': 'raw',
                   'X-Subject-Meta-container_format': 'ovf',
                   'X-Subject-Meta-Is-Public': 'True',
                   'X-Subject-Meta-Location': remote_uri}
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(FIVE_KB, data['subject']['size'])

        subject_id = data['subject']['id']
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)

        # Grab the subject
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        # Grab the subject again to ensure it can be served out from
        # cache with the correct size
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        self.assertEqual(FIVE_KB, int(response['content-length']))

        self.stop_servers()

    @skip_if_disabled
    def test_cache_middleware_trans_v1_without_download_subject_policy(self):
        """
        Ensure the subject v1 API subject transfer applied 'download_subject'
        policy enforcement.
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        # Add an subject and verify a 200 OK is returned
        subject_data = "*" * FIVE_KB
        headers = minimal_headers('Image1')
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=subject_data)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subject']['checksum'])
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("Image1", data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])

        subject_id = data['subject']['id']

        # Verify subject not in cache
        subject_cached_path = os.path.join(self.api_server.subject_cache_dir,
                                         subject_id)
        self.assertFalse(os.path.exists(subject_cached_path))

        rules = {"context_is_admin": "role:admin", "default": "",
                 "download_subject": "!"}
        self.set_policy_rules(rules)

        # Grab the subject
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(403, response.status)

        # Now, we delete the subject from the server and verify that
        # the subject cache no longer contains the deleted subject
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        self.assertFalse(os.path.exists(subject_cached_path))

        self.stop_servers()

    @skip_if_disabled
    def test_cache_middleware_trans_v2_without_download_subject_policy(self):
        """
        Ensure the subject v1 API subject transfer applied 'download_subject'
        policy enforcement.
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        # Add an subject and verify success
        path = "http://%s:%d/v1/subjects" % ("0.0.0.0", self.api_port)
        http = httplib2.Http()
        headers = {'content-type': 'application/json'}
        subject_entity = {
            'name': 'Image1',
            'visibility': 'public',
            'container_format': 'bare',
            'disk_format': 'raw',
        }
        response, content = http.request(path, 'POST',
                                         headers=headers,
                                         body=jsonutils.dumps(subject_entity))
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        subject_id = data['id']

        path = "http://%s:%d/v1/subjects/%s/file" % ("0.0.0.0", self.api_port,
                                                   subject_id)
        headers = {'content-type': 'application/octet-stream'}
        subject_data = "*" * FIVE_KB
        response, content = http.request(path, 'PUT',
                                         headers=headers,
                                         body=subject_data)
        self.assertEqual(204, response.status)

        # Verify subject not in cache
        subject_cached_path = os.path.join(self.api_server.subject_cache_dir,
                                         subject_id)
        self.assertFalse(os.path.exists(subject_cached_path))

        rules = {"context_is_admin": "role:admin", "default": "",
                 "download_subject": "!"}
        self.set_policy_rules(rules)

        # Grab the subject
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(403, response.status)

        # Now, we delete the subject from the server and verify that
        # the subject cache no longer contains the deleted subject
        path = "http://%s:%d/v1/subjects/%s" % ("0.0.0.0", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(204, response.status)

        self.assertFalse(os.path.exists(subject_cached_path))

        self.stop_servers()

    @skip_if_disabled
    def test_cache_middleware_trans_with_deactivated_subject(self):
        """
        Ensure the subject v1/v1 API subject transfer forbids downloading
        deactivated subjects.
        Subject deactivation is not available in v1. So, we'll deactivate the
        subject using v1 but test subject transfer with both v1 and v1.
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        # Add an subject and verify a 200 OK is returned
        subject_data = "*" * FIVE_KB
        headers = minimal_headers('Image1')
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=subject_data)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subject']['checksum'])
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual("Image1", data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])

        subject_id = data['subject']['id']

        # Grab the subject
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        # Verify subject in cache
        subject_cached_path = os.path.join(self.api_server.subject_cache_dir,
                                         subject_id)
        self.assertTrue(os.path.exists(subject_cached_path))

        # Deactivate the subject using v1
        path = "http://%s:%d/v1/subjects/%s/actions/deactivate"
        path = path % ("127.0.0.1", self.api_port, subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'POST')
        self.assertEqual(204, response.status)

        # Download the subject with v1. Ensure it is forbidden
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(403, response.status)

        # Download the subject with v1. This succeeds because
        # we are in admin context.
        path = "http://%s:%d/v1/subjects/%s/file" % ("127.0.0.1", self.api_port,
                                                   subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        # Reactivate the subject using v1
        path = "http://%s:%d/v1/subjects/%s/actions/reactivate"
        path = path % ("127.0.0.1", self.api_port, subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'POST')
        self.assertEqual(204, response.status)

        # Download the subject with v1. Ensure it is allowed
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        # Download the subject with v1. Ensure it is allowed
        path = "http://%s:%d/v1/subjects/%s/file" % ("127.0.0.1", self.api_port,
                                                   subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        # Now, we delete the subject from the server and verify that
        # the subject cache no longer contains the deleted subject
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        self.assertFalse(os.path.exists(subject_cached_path))

        self.stop_servers()


class BaseCacheManageMiddlewareTest(object):

    """Base test class for testing cache management middleware"""

    def verify_no_subjects(self):
        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)
        data = jsonutils.loads(content)
        self.assertIn('subjects', data)
        self.assertEqual(0, len(data['subjects']))

    def add_subject(self, name):
        """
        Adds an subject and returns the newly-added subject
        identifier
        """
        subject_data = "*" * FIVE_KB
        headers = minimal_headers('%s' % name)

        path = "http://%s:%d/v1/subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=subject_data)
        self.assertEqual(201, response.status)
        data = jsonutils.loads(content)
        self.assertEqual(hashlib.md5(subject_data).hexdigest(),
                         data['subject']['checksum'])
        self.assertEqual(FIVE_KB, data['subject']['size'])
        self.assertEqual(name, data['subject']['name'])
        self.assertTrue(data['subject']['is_public'])
        return data['subject']['id']

    def verify_no_cached_subjects(self):
        """
        Verify no subjects in the subject cache
        """
        path = "http://%s:%d/v1/cached_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        data = jsonutils.loads(content)
        self.assertIn('cached_subjects', data)
        self.assertEqual([], data['cached_subjects'])

    @skip_if_disabled
    def test_user_not_authorized(self):
        self.cleanup()
        self.start_servers(**self.__dict__.copy())
        self.verify_no_subjects()

        subject_id1 = self.add_subject("Image1")
        subject_id2 = self.add_subject("Image2")

        # Verify subject does not yet show up in cache (we haven't "hit"
        # it yet using a GET /subjects/1 ...
        self.verify_no_cached_subjects()

        # Grab the subject
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id1)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        # Verify subject now in cache
        path = "http://%s:%d/v1/cached_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        data = jsonutils.loads(content)
        self.assertIn('cached_subjects', data)

        cached_subjects = data['cached_subjects']
        self.assertEqual(1, len(cached_subjects))
        self.assertEqual(subject_id1, cached_subjects[0]['subject_id'])

        # Set policy to disallow access to cache management
        rules = {"manage_subject_cache": '!'}
        self.set_policy_rules(rules)

        # Verify an unprivileged user cannot see cached subjects
        path = "http://%s:%d/v1/cached_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(403, response.status)

        # Verify an unprivileged user cannot delete subjects from the cache
        path = "http://%s:%d/v1/cached_subjects/%s" % ("127.0.0.1",
                                                     self.api_port, subject_id1)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(403, response.status)

        # Verify an unprivileged user cannot delete all cached subjects
        path = "http://%s:%d/v1/cached_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(403, response.status)

        # Verify an unprivileged user cannot queue an subject
        path = "http://%s:%d/v1/queued_subjects/%s" % ("127.0.0.1",
                                                     self.api_port, subject_id2)
        http = httplib2.Http()
        response, content = http.request(path, 'PUT')
        self.assertEqual(403, response.status)

        self.stop_servers()

    @skip_if_disabled
    def test_cache_manage_get_cached_subjects(self):
        """
        Tests that cached subjects are queryable
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        self.verify_no_subjects()

        subject_id = self.add_subject("Image1")

        # Verify subject does not yet show up in cache (we haven't "hit"
        # it yet using a GET /subjects/1 ...
        self.verify_no_cached_subjects()

        # Grab the subject
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        # Verify subject now in cache
        path = "http://%s:%d/v1/cached_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        data = jsonutils.loads(content)
        self.assertIn('cached_subjects', data)

        # Verify the last_modified/last_accessed values are valid floats
        for cached_subject in data['cached_subjects']:
            for time_key in ('last_modified', 'last_accessed'):
                time_val = cached_subject[time_key]
                try:
                    float(time_val)
                except ValueError:
                    self.fail('%s time %s for cached subject %s not a valid '
                              'float' % (time_key, time_val,
                                         cached_subject['subject_id']))

        cached_subjects = data['cached_subjects']
        self.assertEqual(1, len(cached_subjects))
        self.assertEqual(subject_id, cached_subjects[0]['subject_id'])
        self.assertEqual(0, cached_subjects[0]['hits'])

        # Hit the subject
        path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                              subject_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        # Verify subject hits increased in output of manage GET
        path = "http://%s:%d/v1/cached_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        data = jsonutils.loads(content)
        self.assertIn('cached_subjects', data)

        cached_subjects = data['cached_subjects']
        self.assertEqual(1, len(cached_subjects))
        self.assertEqual(subject_id, cached_subjects[0]['subject_id'])
        self.assertEqual(1, cached_subjects[0]['hits'])

        self.stop_servers()

    @skip_if_disabled
    def test_cache_manage_delete_cached_subjects(self):
        """
        Tests that cached subjects may be deleted
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        self.verify_no_subjects()

        ids = {}

        # Add a bunch of subjects...
        for x in range(4):
            ids[x] = self.add_subject("Subject%s" % str(x))

        # Verify no subjects in cached_subjects because no subject has been hit
        # yet using a GET /subjects/<IMAGE_ID> ...
        self.verify_no_cached_subjects()

        # Grab the subjects, essentially caching them...
        for x in range(4):
            path = "http://%s:%d/v1/subjects/%s" % ("127.0.0.1", self.api_port,
                                                  ids[x])
            http = httplib2.Http()
            response, content = http.request(path, 'GET')
            self.assertEqual(200, response.status,
                             "Failed to find subject %s" % ids[x])

        # Verify subjects now in cache
        path = "http://%s:%d/v1/cached_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        data = jsonutils.loads(content)
        self.assertIn('cached_subjects', data)

        cached_subjects = data['cached_subjects']
        self.assertEqual(4, len(cached_subjects))

        for x in range(4, 0):  # Cached subjects returned last modified order
            self.assertEqual(ids[x], cached_subjects[x]['subject_id'])
            self.assertEqual(0, cached_subjects[x]['hits'])

        # Delete third subject of the cached subjects and verify no longer in cache
        path = "http://%s:%d/v1/cached_subjects/%s" % ("127.0.0.1",
                                                     self.api_port, ids[2])
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        path = "http://%s:%d/v1/cached_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        data = jsonutils.loads(content)
        self.assertIn('cached_subjects', data)

        cached_subjects = data['cached_subjects']
        self.assertEqual(3, len(cached_subjects))
        self.assertNotIn(ids[2], [x['subject_id'] for x in cached_subjects])

        # Delete all cached subjects and verify nothing in cache
        path = "http://%s:%d/v1/cached_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        path = "http://%s:%d/v1/cached_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        data = jsonutils.loads(content)
        self.assertIn('cached_subjects', data)

        cached_subjects = data['cached_subjects']
        self.assertEqual(0, len(cached_subjects))

        self.stop_servers()

    @skip_if_disabled
    def test_cache_manage_delete_queued_subjects(self):
        """
        Tests that all queued subjects may be deleted at once
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        self.verify_no_subjects()

        ids = {}
        NUM_IMAGES = 4

        # Add and then queue some subjects
        for x in range(NUM_IMAGES):
            ids[x] = self.add_subject("Subject%s" % str(x))
            path = "http://%s:%d/v1/queued_subjects/%s" % ("127.0.0.1",
                                                         self.api_port, ids[x])
            http = httplib2.Http()
            response, content = http.request(path, 'PUT')
            self.assertEqual(200, response.status)

        # Delete all queued subjects
        path = "http://%s:%d/v1/queued_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        data = jsonutils.loads(content)
        num_deleted = data['num_deleted']
        self.assertEqual(NUM_IMAGES, num_deleted)

        # Verify a second delete now returns num_deleted=0
        path = "http://%s:%d/v1/queued_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(200, response.status)

        data = jsonutils.loads(content)
        num_deleted = data['num_deleted']
        self.assertEqual(0, num_deleted)

        self.stop_servers()

    @skip_if_disabled
    def test_queue_and_prefetch(self):
        """
        Tests that subjects may be queued and prefetched
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        cache_config_filepath = os.path.join(self.test_dir, 'etc',
                                             'subject-cache.conf')
        cache_file_options = {
            'subject_cache_dir': self.api_server.subject_cache_dir,
            'subject_cache_driver': self.subject_cache_driver,
            'registry_port': self.registry_server.bind_port,
            'log_file': os.path.join(self.test_dir, 'cache.log'),
            'metadata_encryption_key': "012345678901234567890123456789ab",
            'filesystem_store_datadir': self.test_dir
        }
        with open(cache_config_filepath, 'w') as cache_file:
            cache_file.write("""[DEFAULT]
debug = True
subject_cache_dir = %(subject_cache_dir)s
subject_cache_driver = %(subject_cache_driver)s
registry_host = 127.0.0.1
registry_port = %(registry_port)s
metadata_encryption_key = %(metadata_encryption_key)s
log_file = %(log_file)s

[glance_store]
filesystem_store_datadir=%(filesystem_store_datadir)s
""" % cache_file_options)

        self.verify_no_subjects()

        ids = {}

        # Add a bunch of subjects...
        for x in range(4):
            ids[x] = self.add_subject("Subject%s" % str(x))

        # Queue the first subject, verify no subjects still in cache after queueing
        # then run the prefetcher and verify that the subject is then in the
        # cache
        path = "http://%s:%d/v1/queued_subjects/%s" % ("127.0.0.1",
                                                     self.api_port, ids[0])
        http = httplib2.Http()
        response, content = http.request(path, 'PUT')
        self.assertEqual(200, response.status)

        self.verify_no_cached_subjects()

        cmd = ("%s -m subject.cmd.cache_prefetcher --config-file %s" %
               (sys.executable, cache_config_filepath))

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertEqual('', out.strip(), out)

        # Verify first subject now in cache
        path = "http://%s:%d/v1/cached_subjects" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(200, response.status)

        data = jsonutils.loads(content)
        self.assertIn('cached_subjects', data)

        cached_subjects = data['cached_subjects']
        self.assertEqual(1, len(cached_subjects))
        self.assertIn(ids[0], [r['subject_id']
                      for r in data['cached_subjects']])

        self.stop_servers()


class TestImageCacheXattr(functional.FunctionalTest,
                          BaseCacheMiddlewareTest):

    """Functional tests that exercise the subject cache using the xattr driver"""

    def setUp(self):
        """
        Test to see if the pre-requisites for the subject cache
        are working (python-xattr installed and xattr support on the
        filesystem)
        """
        if getattr(self, 'disabled', False):
            return

        if not getattr(self, 'inited', False):
            try:
                import xattr  # noqa
            except ImportError:
                self.inited = True
                self.disabled = True
                self.disabled_message = ("python-xattr not installed.")
                return

        self.inited = True
        self.disabled = False
        self.subject_cache_driver = "xattr"

        super(TestImageCacheXattr, self).setUp()

        self.api_server.deployment_flavor = "caching"

        if not xattr_writes_supported(self.test_dir):
            self.inited = True
            self.disabled = True
            self.disabled_message = ("filesystem does not support xattr")
            return

    def tearDown(self):
        super(TestImageCacheXattr, self).tearDown()
        if os.path.exists(self.api_server.subject_cache_dir):
            shutil.rmtree(self.api_server.subject_cache_dir)


class TestImageCacheManageXattr(functional.FunctionalTest,
                                BaseCacheManageMiddlewareTest):

    """
    Functional tests that exercise the subject cache management
    with the Xattr cache driver
    """

    def setUp(self):
        """
        Test to see if the pre-requisites for the subject cache
        are working (python-xattr installed and xattr support on the
        filesystem)
        """
        if getattr(self, 'disabled', False):
            return

        if not getattr(self, 'inited', False):
            try:
                import xattr  # noqa
            except ImportError:
                self.inited = True
                self.disabled = True
                self.disabled_message = ("python-xattr not installed.")
                return

        self.inited = True
        self.disabled = False
        self.subject_cache_driver = "xattr"

        super(TestImageCacheManageXattr, self).setUp()

        self.api_server.deployment_flavor = "cachemanagement"

        if not xattr_writes_supported(self.test_dir):
            self.inited = True
            self.disabled = True
            self.disabled_message = ("filesystem does not support xattr")
            return

    def tearDown(self):
        super(TestImageCacheManageXattr, self).tearDown()
        if os.path.exists(self.api_server.subject_cache_dir):
            shutil.rmtree(self.api_server.subject_cache_dir)


class TestImageCacheSqlite(functional.FunctionalTest,
                           BaseCacheMiddlewareTest):

    """
    Functional tests that exercise the subject cache using the
    SQLite driver
    """

    def setUp(self):
        """
        Test to see if the pre-requisites for the subject cache
        are working (python-xattr installed and xattr support on the
        filesystem)
        """
        if getattr(self, 'disabled', False):
            return

        if not getattr(self, 'inited', False):
            try:
                import sqlite3  # noqa
            except ImportError:
                self.inited = True
                self.disabled = True
                self.disabled_message = ("python-sqlite3 not installed.")
                return

        self.inited = True
        self.disabled = False

        super(TestImageCacheSqlite, self).setUp()

        self.api_server.deployment_flavor = "caching"

    def tearDown(self):
        super(TestImageCacheSqlite, self).tearDown()
        if os.path.exists(self.api_server.subject_cache_dir):
            shutil.rmtree(self.api_server.subject_cache_dir)


class TestImageCacheManageSqlite(functional.FunctionalTest,
                                 BaseCacheManageMiddlewareTest):

    """
    Functional tests that exercise the subject cache management using the
    SQLite driver
    """

    def setUp(self):
        """
        Test to see if the pre-requisites for the subject cache
        are working (python-xattr installed and xattr support on the
        filesystem)
        """
        if getattr(self, 'disabled', False):
            return

        if not getattr(self, 'inited', False):
            try:
                import sqlite3  # noqa
            except ImportError:
                self.inited = True
                self.disabled = True
                self.disabled_message = ("python-sqlite3 not installed.")
                return

        self.inited = True
        self.disabled = False
        self.subject_cache_driver = "sqlite"

        super(TestImageCacheManageSqlite, self).setUp()

        self.api_server.deployment_flavor = "cachemanagement"

    def tearDown(self):
        super(TestImageCacheManageSqlite, self).tearDown()
        if os.path.exists(self.api_server.subject_cache_dir):
            shutil.rmtree(self.api_server.subject_cache_dir)
