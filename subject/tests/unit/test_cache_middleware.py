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

from oslo_policy import policy
# NOTE(jokke): simplified transition to py3, behaves like py2 xrange
from six.moves import range
import testtools
import webob

import subject.api.middleware.cache
import subject.api.policy
from subject.common import exception
from subject import context
import subject.registry.client.v1.api as registry
from subject.tests.unit import base
from subject.tests.unit import utils as unit_test_utils


class SubjectStub(object):
    def __init__(self, subject_id, extra_properties=None, visibility='private'):
        if extra_properties is None:
            extra_properties = {}
        self.subject_id = subject_id
        self.visibility = visibility
        self.status = 'active'
        self.extra_properties = extra_properties
        self.checksum = 'c1234'
        self.size = 123456789


class TestCacheMiddlewareURLMatching(testtools.TestCase):
    def test_v1_no_match_detail(self):
        req = webob.Request.blank('/v1/subjects/detail')
        out = subject.api.middleware.cache.CacheFilter._match_request(req)
        self.assertIsNone(out)

    def test_v1_no_match_detail_with_query_params(self):
        req = webob.Request.blank('/v1/subjects/detail?limit=10')
        out = subject.api.middleware.cache.CacheFilter._match_request(req)
        self.assertIsNone(out)

    def test_v1_match_id_with_query_param(self):
        req = webob.Request.blank('/v1/subjects/asdf?ping=pong')
        out = subject.api.middleware.cache.CacheFilter._match_request(req)
        self.assertEqual(('v1', 'GET', 'asdf'), out)

    def test_v2_match_id(self):
        req = webob.Request.blank('/v1/subjects/asdf/file')
        out = subject.api.middleware.cache.CacheFilter._match_request(req)
        self.assertEqual(('v1', 'GET', 'asdf'), out)

    def test_v2_no_match_bad_path(self):
        req = webob.Request.blank('/v1/subjects/asdf')
        out = subject.api.middleware.cache.CacheFilter._match_request(req)
        self.assertIsNone(out)

    def test_no_match_unknown_version(self):
        req = webob.Request.blank('/v3/subjects/asdf')
        out = subject.api.middleware.cache.CacheFilter._match_request(req)
        self.assertIsNone(out)


class TestCacheMiddlewareRequestStashCacheInfo(testtools.TestCase):
    def setUp(self):
        super(TestCacheMiddlewareRequestStashCacheInfo, self).setUp()
        self.request = webob.Request.blank('')
        self.middleware = subject.api.middleware.cache.CacheFilter

    def test_stash_cache_request_info(self):
        self.middleware._stash_request_info(self.request, 'asdf', 'GET', 'v1')
        self.assertEqual('asdf', self.request.environ['api.cache.subject_id'])
        self.assertEqual('GET', self.request.environ['api.cache.method'])
        self.assertEqual('v1', self.request.environ['api.cache.version'])

    def test_fetch_cache_request_info(self):
        self.request.environ['api.cache.subject_id'] = 'asdf'
        self.request.environ['api.cache.method'] = 'GET'
        self.request.environ['api.cache.version'] = 'v1'
        (subject_id, method, version) = self.middleware._fetch_request_info(
            self.request)
        self.assertEqual('asdf', subject_id)
        self.assertEqual('GET', method)
        self.assertEqual('v1', version)

    def test_fetch_cache_request_info_unset(self):
        out = self.middleware._fetch_request_info(self.request)
        self.assertIsNone(out)


class ChecksumTestCacheFilter(subject.api.middleware.cache.CacheFilter):
    def __init__(self):
        class DummyCache(object):
            def get_caching_iter(self, subject_id, subject_checksum, app_iter):
                self.subject_checksum = subject_checksum

        self.cache = DummyCache()
        self.policy = unit_test_utils.FakePolicyEnforcer()


class TestCacheMiddlewareChecksumVerification(base.IsolatedUnitTest):
    def setUp(self):
        super(TestCacheMiddlewareChecksumVerification, self).setUp()
        self.context = context.RequestContext(is_admin=True)
        self.request = webob.Request.blank('')
        self.request.context = self.context

    def test_checksum_v1_header(self):
        cache_filter = ChecksumTestCacheFilter()
        headers = {"x-subject-meta-checksum": "1234567890"}
        resp = webob.Response(request=self.request, headers=headers)
        cache_filter._process_GET_response(resp, None)

        self.assertEqual("1234567890", cache_filter.cache.subject_checksum)

    def test_checksum_v2_header(self):
        cache_filter = ChecksumTestCacheFilter()
        headers = {
            "x-subject-meta-checksum": "1234567890",
            "Content-MD5": "abcdefghi"
        }
        resp = webob.Response(request=self.request, headers=headers)
        cache_filter._process_GET_response(resp, None)

        self.assertEqual("abcdefghi", cache_filter.cache.subject_checksum)

    def test_checksum_missing_header(self):
        cache_filter = ChecksumTestCacheFilter()
        resp = webob.Response(request=self.request)
        cache_filter._process_GET_response(resp, None)

        self.assertIsNone(cache_filter.cache.subject_checksum)


class FakeSubjectSerializer(object):
    def show(self, response, raw_response):
        return True


class ProcessRequestTestCacheFilter(subject.api.middleware.cache.CacheFilter):
    def __init__(self):
        self.serializer = FakeSubjectSerializer()

        class DummyCache(object):
            def __init__(self):
                self.deleted_subjects = []

            def is_cached(self, subject_id):
                return True

            def get_caching_iter(self, subject_id, subject_checksum, app_iter):
                pass

            def delete_cached_subject(self, subject_id):
                self.deleted_subjects.append(subject_id)

            def get_subject_size(self, subject_id):
                pass

        self.cache = DummyCache()
        self.policy = unit_test_utils.FakePolicyEnforcer()


class TestCacheMiddlewareProcessRequest(base.IsolatedUnitTest):
    def _enforcer_from_rules(self, unparsed_rules):
        rules = policy.Rules.from_dict(unparsed_rules)
        enforcer = subject.api.policy.Enforcer()
        enforcer.set_rules(rules, overwrite=True)
        return enforcer

    def test_v1_deleted_subject_fetch(self):
        """
        Test for determining that when an admin tries to download a deleted
        subject it returns 404 Not Found error.
        """
        def dummy_img_iterator():
            for i in range(3):
                yield i

        subject_id = 'test1'
        subject_meta = {
            'id': subject_id,
            'name': 'fake_subject',
            'status': 'deleted',
            'created_at': '',
            'min_disk': '10G',
            'min_ram': '1024M',
            'protected': False,
            'locations': '',
            'checksum': 'c1234',
            'owner': '',
            'disk_format': 'raw',
            'container_format': 'bare',
            'size': '123456789',
            'virtual_size': '123456789',
            'is_public': 'public',
            'deleted': True,
            'updated_at': '',
            'properties': {},
        }
        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext()
        cache_filter = ProcessRequestTestCacheFilter()
        self.assertRaises(exception.NotFound, cache_filter._process_v1_request,
                          request, subject_id, dummy_img_iterator, subject_meta)

    def test_process_v1_request_for_deleted_but_cached_subject(self):
        """
        Test for determining subject is deleted from cache when it is not found
        in Glance Registry.
        """
        def fake_process_v1_request(request, subject_id, subject_iterator,
                                    subject_meta):
            raise exception.SubjectNotFound()

        def fake_get_v1_subject_metadata(request, subject_id):
            return {'status': 'active', 'properties': {}}

        subject_id = 'test1'
        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext()

        cache_filter = ProcessRequestTestCacheFilter()
        self.stubs.Set(cache_filter, '_get_v1_subject_metadata',
                       fake_get_v1_subject_metadata)
        self.stubs.Set(cache_filter, '_process_v1_request',
                       fake_process_v1_request)
        cache_filter.process_request(request)
        self.assertIn(subject_id, cache_filter.cache.deleted_subjects)

    def test_v1_process_request_subject_fetch(self):

        def dummy_img_iterator():
            for i in range(3):
                yield i

        subject_id = 'test1'
        subject_meta = {
            'id': subject_id,
            'name': 'fake_subject',
            'status': 'active',
            'created_at': '',
            'min_disk': '10G',
            'min_ram': '1024M',
            'protected': False,
            'locations': '',
            'checksum': 'c1234',
            'owner': '',
            'disk_format': 'raw',
            'container_format': 'bare',
            'size': '123456789',
            'virtual_size': '123456789',
            'is_public': 'public',
            'deleted': False,
            'updated_at': '',
            'properties': {},
        }
        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext()
        cache_filter = ProcessRequestTestCacheFilter()
        actual = cache_filter._process_v1_request(
            request, subject_id, dummy_img_iterator, subject_meta)
        self.assertTrue(actual)

    def test_v1_remove_location_subject_fetch(self):

        class CheckNoLocationDataSerializer(object):
            def show(self, response, raw_response):
                return 'location_data' in raw_response['subject_meta']

        def dummy_img_iterator():
            for i in range(3):
                yield i

        subject_id = 'test1'
        subject_meta = {
            'id': subject_id,
            'name': 'fake_subject',
            'status': 'active',
            'created_at': '',
            'min_disk': '10G',
            'min_ram': '1024M',
            'protected': False,
            'locations': '',
            'checksum': 'c1234',
            'owner': '',
            'disk_format': 'raw',
            'container_format': 'bare',
            'size': '123456789',
            'virtual_size': '123456789',
            'is_public': 'public',
            'deleted': False,
            'updated_at': '',
            'properties': {},
        }
        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext()
        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter.serializer = CheckNoLocationDataSerializer()
        actual = cache_filter._process_v1_request(
            request, subject_id, dummy_img_iterator, subject_meta)
        self.assertFalse(actual)

    def test_verify_metadata_deleted_subject(self):
        """
        Test verify_metadata raises exception.NotFound for a deleted subject
        """
        subject_meta = {'status': 'deleted', 'is_public': True, 'deleted': True}
        cache_filter = ProcessRequestTestCacheFilter()
        self.assertRaises(exception.NotFound,
                          cache_filter._verify_metadata, subject_meta)

    def test_verify_metadata_zero_size(self):
        """
        Test verify_metadata updates metadata with cached subject size for subjects
        with 0 size
        """
        subject_size = 1

        def fake_get_subject_size(subject_id):
            return subject_size

        subject_id = 'test1'
        subject_meta = {'size': 0, 'deleted': False, 'id': subject_id,
                      'status': 'active'}
        cache_filter = ProcessRequestTestCacheFilter()
        self.stubs.Set(cache_filter.cache, 'get_subject_size',
                       fake_get_subject_size)
        cache_filter._verify_metadata(subject_meta)
        self.assertEqual(subject_size, subject_meta['size'])

    def test_v2_process_request_response_headers(self):
        def dummy_img_iterator():
            for i in range(3):
                yield i

        subject_id = 'test1'
        request = webob.Request.blank('/v1/subjects/test1/file')
        request.context = context.RequestContext()
        request.environ['api.cache.subject'] = SubjectStub(subject_id)

        subject_meta = {
            'id': subject_id,
            'name': 'fake_subject',
            'status': 'active',
            'created_at': '',
            'min_disk': '10G',
            'min_ram': '1024M',
            'protected': False,
            'locations': '',
            'checksum': 'c1234',
            'owner': '',
            'disk_format': 'raw',
            'container_format': 'bare',
            'size': '123456789',
            'virtual_size': '123456789',
            'is_public': 'public',
            'deleted': False,
            'updated_at': '',
            'properties': {},
        }

        cache_filter = ProcessRequestTestCacheFilter()
        response = cache_filter._process_v2_request(
            request, subject_id, dummy_img_iterator, subject_meta)
        self.assertEqual('application/octet-stream',
                         response.headers['Content-Type'])
        self.assertEqual('c1234', response.headers['Content-MD5'])
        self.assertEqual('123456789', response.headers['Content-Length'])

    def test_v2_process_request_without_checksum(self):
        def dummy_img_iterator():
            for i in range(3):
                yield i

        subject_id = 'test1'
        request = webob.Request.blank('/v1/subjects/test1/file')
        request.context = context.RequestContext()
        subject = SubjectStub(subject_id)
        subject.checksum = None
        request.environ['api.cache.subject'] = subject

        subject_meta = {
            'id': subject_id,
            'name': 'fake_subject',
            'status': 'active',
            'size': '123456789',
        }

        cache_filter = ProcessRequestTestCacheFilter()
        response = cache_filter._process_v2_request(
            request, subject_id, dummy_img_iterator, subject_meta)
        self.assertNotIn('Content-MD5', response.headers.keys())

    def test_process_request_without_download_subject_policy(self):
        """
        Test for cache middleware skip processing when request
        context has not 'download_subject' role.
        """

        def fake_get_v1_subject_metadata(*args, **kwargs):
            return {'status': 'active', 'properties': {}}

        subject_id = 'test1'
        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext()

        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._get_v1_subject_metadata = fake_get_v1_subject_metadata

        enforcer = self._enforcer_from_rules({'download_subject': '!'})
        cache_filter.policy = enforcer
        self.assertRaises(webob.exc.HTTPForbidden,
                          cache_filter.process_request, request)

    def test_v1_process_request_download_restricted(self):
        """
        Test process_request for v1 api where _member_ role not able to
        download the subject with custom property.
        """
        subject_id = 'test1'

        def fake_get_v1_subject_metadata(*args, **kwargs):
            return {
                'id': subject_id,
                'name': 'fake_subject',
                'status': 'active',
                'created_at': '',
                'min_disk': '10G',
                'min_ram': '1024M',
                'protected': False,
                'locations': '',
                'checksum': 'c1234',
                'owner': '',
                'disk_format': 'raw',
                'container_format': 'bare',
                'size': '123456789',
                'virtual_size': '123456789',
                'is_public': 'public',
                'deleted': False,
                'updated_at': '',
                'x_test_key': 'test_1234'
            }

        enforcer = self._enforcer_from_rules({
            "restricted":
            "not ('test_1234':%(x_test_key)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        })

        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext(roles=['_member_'])
        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._get_v1_subject_metadata = fake_get_v1_subject_metadata
        cache_filter.policy = enforcer
        self.assertRaises(webob.exc.HTTPForbidden,
                          cache_filter.process_request, request)

    def test_v1_process_request_download_permitted(self):
        """
        Test process_request for v1 api where member role able to
        download the subject with custom property.
        """
        subject_id = 'test1'

        def fake_get_v1_subject_metadata(*args, **kwargs):
            return {
                'id': subject_id,
                'name': 'fake_subject',
                'status': 'active',
                'created_at': '',
                'min_disk': '10G',
                'min_ram': '1024M',
                'protected': False,
                'locations': '',
                'checksum': 'c1234',
                'owner': '',
                'disk_format': 'raw',
                'container_format': 'bare',
                'size': '123456789',
                'virtual_size': '123456789',
                'is_public': 'public',
                'deleted': False,
                'updated_at': '',
                'x_test_key': 'test_1234'
            }

        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext(roles=['member'])
        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._get_v1_subject_metadata = fake_get_v1_subject_metadata

        rules = {
            "restricted":
            "not ('test_1234':%(x_test_key)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }
        self.set_policy_rules(rules)
        cache_filter.policy = subject.api.policy.Enforcer()
        actual = cache_filter.process_request(request)
        self.assertTrue(actual)

    def test_v1_process_request_subject_meta_not_found(self):
        """
        Test process_request for v1 api where registry raises NotFound
        exception as subject metadata not found.
        """
        subject_id = 'test1'

        def fake_get_v1_subject_metadata(*args, **kwargs):
            raise exception.NotFound()

        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext(roles=['_member_'])
        cache_filter = ProcessRequestTestCacheFilter()
        self.stubs.Set(registry, 'get_subject_metadata',
                       fake_get_v1_subject_metadata)

        rules = {
            "restricted":
            "not ('test_1234':%(x_test_key)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }
        self.set_policy_rules(rules)
        cache_filter.policy = subject.api.policy.Enforcer()
        self.assertRaises(webob.exc.HTTPNotFound,
                          cache_filter.process_request, request)

    def test_v2_process_request_download_restricted(self):
        """
        Test process_request for v1 api where _member_ role not able to
        download the subject with custom property.
        """
        subject_id = 'test1'
        extra_properties = {
            'x_test_key': 'test_1234'
        }

        def fake_get_v2_subject_metadata(*args, **kwargs):
            subject = SubjectStub(subject_id, extra_properties=extra_properties)
            request.environ['api.cache.subject'] = subject
            return subject.api.policy.SubjectTarget(subject)

        enforcer = self._enforcer_from_rules({
            "restricted":
            "not ('test_1234':%(x_test_key)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        })

        request = webob.Request.blank('/v1/subjects/test1/file')
        request.context = context.RequestContext(roles=['_member_'])
        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._get_v2_subject_metadata = fake_get_v2_subject_metadata

        cache_filter.policy = enforcer
        self.assertRaises(webob.exc.HTTPForbidden,
                          cache_filter.process_request, request)

    def test_v2_process_request_download_permitted(self):
        """
        Test process_request for v1 api where member role able to
        download the subject with custom property.
        """
        subject_id = 'test1'
        extra_properties = {
            'x_test_key': 'test_1234'
        }

        def fake_get_v2_subject_metadata(*args, **kwargs):
            subject = SubjectStub(subject_id, extra_properties=extra_properties)
            request.environ['api.cache.subject'] = subject
            return subject.api.policy.SubjectTarget(subject)

        request = webob.Request.blank('/v1/subjects/test1/file')
        request.context = context.RequestContext(roles=['member'])
        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._get_v2_subject_metadata = fake_get_v2_subject_metadata

        rules = {
            "restricted":
            "not ('test_1234':%(x_test_key)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }
        self.set_policy_rules(rules)
        cache_filter.policy = subject.api.policy.Enforcer()
        actual = cache_filter.process_request(request)
        self.assertTrue(actual)


class TestCacheMiddlewareProcessResponse(base.IsolatedUnitTest):
    def test_process_v1_DELETE_response(self):
        subject_id = 'test1'
        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext()
        cache_filter = ProcessRequestTestCacheFilter()
        headers = {"x-subject-meta-deleted": True}
        resp = webob.Response(request=request, headers=headers)
        actual = cache_filter._process_DELETE_response(resp, subject_id)
        self.assertEqual(resp, actual)

    def test_get_status_code(self):
        headers = {"x-subject-meta-deleted": True}
        resp = webob.Response(headers=headers)
        cache_filter = ProcessRequestTestCacheFilter()
        actual = cache_filter.get_status_code(resp)
        self.assertEqual(200, actual)

    def test_process_response(self):
        def fake_fetch_request_info(*args, **kwargs):
            return ('test1', 'GET', 'v1')

        def fake_get_v1_subject_metadata(*args, **kwargs):
            return {'properties': {}}

        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._fetch_request_info = fake_fetch_request_info
        cache_filter._get_v1_subject_metadata = fake_get_v1_subject_metadata
        subject_id = 'test1'
        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext()
        headers = {"x-subject-meta-deleted": True}
        resp = webob.Response(request=request, headers=headers)
        actual = cache_filter.process_response(resp)
        self.assertEqual(resp, actual)

    def test_process_response_without_download_subject_policy(self):
        """
        Test for cache middleware raise webob.exc.HTTPForbidden directly
        when request context has not 'download_subject' role.
        """
        def fake_fetch_request_info(*args, **kwargs):
            return ('test1', 'GET', 'v1')

        def fake_get_v1_subject_metadata(*args, **kwargs):
            return {'properties': {}}

        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._fetch_request_info = fake_fetch_request_info
        cache_filter._get_v1_subject_metadata = fake_get_v1_subject_metadata
        rules = {'download_subject': '!'}
        self.set_policy_rules(rules)
        cache_filter.policy = subject.api.policy.Enforcer()

        subject_id = 'test1'
        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext()
        resp = webob.Response(request=request)
        self.assertRaises(webob.exc.HTTPForbidden,
                          cache_filter.process_response, resp)
        self.assertEqual([b''], resp.app_iter)

    def test_v1_process_response_download_restricted(self):
        """
        Test process_response for v1 api where _member_ role not able to
        download the subject with custom property.
        """
        subject_id = 'test1'

        def fake_fetch_request_info(*args, **kwargs):
            return ('test1', 'GET', 'v1')

        def fake_get_v1_subject_metadata(*args, **kwargs):
            return {
                'id': subject_id,
                'name': 'fake_subject',
                'status': 'active',
                'created_at': '',
                'min_disk': '10G',
                'min_ram': '1024M',
                'protected': False,
                'locations': '',
                'checksum': 'c1234',
                'owner': '',
                'disk_format': 'raw',
                'container_format': 'bare',
                'size': '123456789',
                'virtual_size': '123456789',
                'is_public': 'public',
                'deleted': False,
                'updated_at': '',
                'x_test_key': 'test_1234'
            }

        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._fetch_request_info = fake_fetch_request_info
        cache_filter._get_v1_subject_metadata = fake_get_v1_subject_metadata
        rules = {
            "restricted":
            "not ('test_1234':%(x_test_key)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }
        self.set_policy_rules(rules)
        cache_filter.policy = subject.api.policy.Enforcer()

        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext(roles=['_member_'])
        resp = webob.Response(request=request)
        self.assertRaises(webob.exc.HTTPForbidden,
                          cache_filter.process_response, resp)

    def test_v1_process_response_download_permitted(self):
        """
        Test process_response for v1 api where member role able to
        download the subject with custom property.
        """
        subject_id = 'test1'

        def fake_fetch_request_info(*args, **kwargs):
            return ('test1', 'GET', 'v1')

        def fake_get_v1_subject_metadata(*args, **kwargs):
            return {
                'id': subject_id,
                'name': 'fake_subject',
                'status': 'active',
                'created_at': '',
                'min_disk': '10G',
                'min_ram': '1024M',
                'protected': False,
                'locations': '',
                'checksum': 'c1234',
                'owner': '',
                'disk_format': 'raw',
                'container_format': 'bare',
                'size': '123456789',
                'virtual_size': '123456789',
                'is_public': 'public',
                'deleted': False,
                'updated_at': '',
                'x_test_key': 'test_1234'
            }

        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._fetch_request_info = fake_fetch_request_info
        cache_filter._get_v1_subject_metadata = fake_get_v1_subject_metadata
        rules = {
            "restricted":
            "not ('test_1234':%(x_test_key)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }
        self.set_policy_rules(rules)
        cache_filter.policy = subject.api.policy.Enforcer()

        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext(roles=['member'])
        resp = webob.Response(request=request)
        actual = cache_filter.process_response(resp)
        self.assertEqual(resp, actual)

    def test_v1_process_response_subject_meta_not_found(self):
        """
        Test process_response for v1 api where registry raises NotFound
        exception as subject metadata not found.
        """
        subject_id = 'test1'

        def fake_fetch_request_info(*args, **kwargs):
            return ('test1', 'GET', 'v1')

        def fake_get_v1_subject_metadata(*args, **kwargs):
            raise exception.NotFound()

        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._fetch_request_info = fake_fetch_request_info

        self.stubs.Set(registry, 'get_subject_metadata',
                       fake_get_v1_subject_metadata)

        rules = {
            "restricted":
            "not ('test_1234':%(x_test_key)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }
        self.set_policy_rules(rules)
        cache_filter.policy = subject.api.policy.Enforcer()

        request = webob.Request.blank('/v1/subjects/%s' % subject_id)
        request.context = context.RequestContext(roles=['_member_'])
        resp = webob.Response(request=request)
        self.assertRaises(webob.exc.HTTPNotFound,
                          cache_filter.process_response, resp)

    def test_v2_process_response_download_restricted(self):
        """
        Test process_response for v1 api where _member_ role not able to
        download the subject with custom property.
        """
        subject_id = 'test1'
        extra_properties = {
            'x_test_key': 'test_1234'
        }

        def fake_fetch_request_info(*args, **kwargs):
            return ('test1', 'GET', 'v1')

        def fake_get_v2_subject_metadata(*args, **kwargs):
            subject = SubjectStub(subject_id, extra_properties=extra_properties)
            request.environ['api.cache.subject'] = subject
            return subject.api.policy.SubjectTarget(subject)

        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._fetch_request_info = fake_fetch_request_info
        cache_filter._get_v2_subject_metadata = fake_get_v2_subject_metadata

        rules = {
            "restricted":
            "not ('test_1234':%(x_test_key)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }
        self.set_policy_rules(rules)
        cache_filter.policy = subject.api.policy.Enforcer()

        request = webob.Request.blank('/v1/subjects/test1/file')
        request.context = context.RequestContext(roles=['_member_'])
        resp = webob.Response(request=request)
        self.assertRaises(webob.exc.HTTPForbidden,
                          cache_filter.process_response, resp)

    def test_v2_process_response_download_permitted(self):
        """
        Test process_response for v1 api where member role able to
        download the subject with custom property.
        """
        subject_id = 'test1'
        extra_properties = {
            'x_test_key': 'test_1234'
        }

        def fake_fetch_request_info(*args, **kwargs):
            return ('test1', 'GET', 'v1')

        def fake_get_v2_subject_metadata(*args, **kwargs):
            subject = SubjectStub(subject_id, extra_properties=extra_properties)
            request.environ['api.cache.subject'] = subject
            return subject.api.policy.SubjectTarget(subject)

        cache_filter = ProcessRequestTestCacheFilter()
        cache_filter._fetch_request_info = fake_fetch_request_info
        cache_filter._get_v2_subject_metadata = fake_get_v2_subject_metadata

        rules = {
            "restricted":
            "not ('test_1234':%(x_test_key)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }
        self.set_policy_rules(rules)
        cache_filter.policy = subject.api.policy.Enforcer()

        request = webob.Request.blank('/v1/subjects/test1/file')
        request.context = context.RequestContext(roles=['member'])
        resp = webob.Response(request=request)
        actual = cache_filter.process_response(resp)
        self.assertEqual(resp, actual)
