# -*- coding: utf-8 -*-

# Copyright 2010-2011 OpenStack Foundation
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

import datetime
import uuid

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils
import routes
import six
import webob

import subject.api.common
import subject.common.config
from subject.common import crypt
from subject.common import timeutils
from subject import context
from subject.db.sqlalchemy import api as db_api
from subject.db.sqlalchemy import models as db_models
from subject.registry.api import v1 as rserver
from subject.tests.unit import base
from subject.tests import utils as test_utils

CONF = cfg.CONF

_gen_uuid = lambda: str(uuid.uuid4())

UUID1 = _gen_uuid()
UUID2 = _gen_uuid()


class TestRegistryAPI(base.IsolatedUnitTest, test_utils.RegistryAPIMixIn):
    def setUp(self):
        """Establish a clean test environment"""
        super(TestRegistryAPI, self).setUp()
        self.mapper = routes.Mapper()
        self.api = test_utils.FakeAuthMiddleware(rserver.API(self.mapper),
                                                 is_admin=True)

        def _get_extra_fixture(id, name, **kwargs):
            return self.get_extra_fixture(
                id, name,
                locations=[{'url': "file:///%s/%s" % (self.test_dir, id),
                            'metadata': {}, 'status': 'active'}], **kwargs)

        self.FIXTURES = [
            _get_extra_fixture(UUID1, 'fake subject #1', is_public=False,
                               disk_format='ami', container_format='ami',
                               min_disk=0, min_ram=0, owner=123,
                               size=13, properties={'type': 'kernel'}),
            _get_extra_fixture(UUID2, 'fake subject #2',
                               min_disk=5, min_ram=256,
                               size=19, properties={})]
        self.context = context.RequestContext(is_admin=True)
        db_api.get_engine()
        self.destroy_fixtures()
        self.create_fixtures()

    def tearDown(self):
        """Clear the test environment"""
        super(TestRegistryAPI, self).tearDown()
        self.destroy_fixtures()

    def test_show(self):
        """
        Tests that the /subjects/<id> registry API endpoint
        returns the expected subject
        """
        fixture = {'id': UUID2,
                   'name': 'fake subject #2',
                   'size': 19,
                   'min_ram': 256,
                   'min_disk': 5,
                   'checksum': None}
        res = self.get_api_response_ext(200, '/subjects/%s' % UUID2)
        res_dict = jsonutils.loads(res.body)
        subject = res_dict['subject']
        for k, v in six.iteritems(fixture):
            self.assertEqual(v, subject[k])

    def test_show_unknown(self):
        """
        Tests that the /subjects/<id> registry API endpoint
        returns a 404 for an unknown subject id
        """
        self.get_api_response_ext(404, '/subjects/%s' % _gen_uuid())

    def test_show_invalid(self):
        """
        Tests that the /subjects/<id> registry API endpoint
        returns a 404 for an invalid (therefore unknown) subject id
        """
        self.get_api_response_ext(404, '/subjects/%s' % _gen_uuid())

    def test_show_deleted_subject_as_admin(self):
        """
        Tests that the /subjects/<id> registry API endpoint
        returns a 200 for deleted subject to admin user.
        """
        # Delete subject #2
        self.get_api_response_ext(200, '/subjects/%s' % UUID2, method='DELETE')

        self.get_api_response_ext(200, '/subjects/%s' % UUID2)

    def test_show_deleted_subject_as_nonadmin(self):
        """
        Tests that the /subjects/<id> registry API endpoint
        returns a 404 for deleted subject to non-admin user.
        """
        # Delete subject #2
        self.get_api_response_ext(200, '/subjects/%s' % UUID2, method='DELETE')

        api = test_utils.FakeAuthMiddleware(rserver.API(self.mapper),
                                            is_admin=False)
        self.get_api_response_ext(404, '/subjects/%s' % UUID2, api=api)

    def test_show_private_subject_with_no_admin_user(self):
        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, size=18, owner='test user',
                                         is_public=False)
        db_api.subject_create(self.context, extra_fixture)
        test_rserv = rserver.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(test_rserv, is_admin=False)
        self.get_api_response_ext(404, '/subjects/%s' % UUID4, api=api)

    def test_get_root(self):
        """
        Tests that the root registry API returns "index",
        which is a list of public subjects
        """
        fixture = {'id': UUID2, 'size': 19, 'checksum': None}
        res = self.get_api_response_ext(200, url='/')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))

        for k, v in six.iteritems(fixture):
            self.assertEqual(v, subjects[0][k])

    def test_get_index(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects
        """
        fixture = {'id': UUID2, 'size': 19, 'checksum': None}
        res = self.get_api_response_ext(200)
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))

        for k, v in six.iteritems(fixture):
            self.assertEqual(v, subjects[0][k])

    def test_get_index_marker(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects that conforms to a marker query param
        """
        time1 = timeutils.utcnow() + datetime.timedelta(seconds=5)
        time2 = timeutils.utcnow() + datetime.timedelta(seconds=4)
        time3 = timeutils.utcnow()

        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, size=19, created_at=time1)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, created_at=time2)

        db_api.subject_create(self.context, extra_fixture)

        UUID5 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID5, created_at=time3)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url='/subjects?marker=%s' % UUID4)
        self.assertEqualSubjects(res, (UUID5, UUID2))

    def test_get_index_unknown_marker(self):
        """
        Tests that the /subjects registry API returns a 400
        when an unknown marker is provided
        """
        self.get_api_response_ext(400, url='/subjects?marker=%s' % _gen_uuid())

    def test_get_index_malformed_marker(self):
        """
        Tests that the /subjects registry API returns a 400
        when a malformed marker is provided
        """
        res = self.get_api_response_ext(400, url='/subjects?marker=4')
        self.assertIn(b'marker', res.body)

    def test_get_index_forbidden_marker(self):
        """
        Tests that the /subjects registry API returns a 400
        when a forbidden marker is provided
        """
        test_rserv = rserver.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(test_rserv, is_admin=False)
        self.get_api_response_ext(400, url='/subjects?marker=%s' % UUID1,
                                  api=api)

    def test_get_index_limit(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects that conforms to a limit query param
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, size=19)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url='/subjects?limit=1')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))

        # expect list to be sorted by created_at desc
        self.assertEqual(UUID4, subjects[0]['id'])

    def test_get_index_limit_negative(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects that conforms to a limit query param
        """
        self.get_api_response_ext(400, url='/subjects?limit=-1')

    def test_get_index_limit_non_int(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects that conforms to a limit query param
        """
        self.get_api_response_ext(400, url='/subjects?limit=a')

    def test_get_index_limit_marker(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects that conforms to limit and marker query params
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, size=19)

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid())

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(
            200, url='/subjects?marker=%s&limit=1' % UUID3)
        self.assertEqualSubjects(res, (UUID2,))

    def test_get_index_filter_on_user_defined_properties(self):
        """
        Tests that /subjects registry API returns list of public subjects based
        a filter on user-defined properties.
        """
        subject1_id = _gen_uuid()
        properties = {'distro': 'ubuntu', 'arch': 'i386'}
        extra_fixture = self.get_fixture(id=subject1_id, name='subject-extra-1',
                                         properties=properties)
        db_api.subject_create(self.context, extra_fixture)

        subject2_id = _gen_uuid()
        properties = {'distro': 'ubuntu', 'arch': 'x86_64', 'foo': 'bar'}
        extra_fixture = self.get_fixture(id=subject2_id, name='subject-extra-2',
                                         properties=properties)
        db_api.subject_create(self.context, extra_fixture)

        # Test index with filter containing one user-defined property.
        # Filter is 'property-distro=ubuntu'.
        # Verify both subject1 and subject2 are returned
        res = self.get_api_response_ext(200, url='/subjects?'
                                                 'property-distro=ubuntu')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(2, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])
        self.assertEqual(subject1_id, subjects[1]['id'])

        # Test index with filter containing one user-defined property but
        # non-existent value. Filter is 'property-distro=fedora'.
        # Verify neither subjects are returned
        res = self.get_api_response_ext(200, url='/subjects?'
                                                 'property-distro=fedora')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

        # Test index with filter containing one user-defined property but
        # unique value. Filter is 'property-arch=i386'.
        # Verify only subject1 is returned.
        res = self.get_api_response_ext(200, url='/subjects?'
                                                 'property-arch=i386')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject1_id, subjects[0]['id'])

        # Test index with filter containing one user-defined property but
        # unique value. Filter is 'property-arch=x86_64'.
        # Verify only subject1 is returned.
        res = self.get_api_response_ext(200, url='/subjects?'
                                                 'property-arch=x86_64')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])

        # Test index with filter containing unique user-defined property.
        # Filter is 'property-foo=bar'.
        # Verify only subject2 is returned.
        res = self.get_api_response_ext(200, url='/subjects?property-foo=bar')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])

        # Test index with filter containing unique user-defined property but
        # .value is non-existent. Filter is 'property-foo=baz'.
        # Verify neither subjects are returned.
        res = self.get_api_response_ext(200, url='/subjects?property-foo=baz')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

        # Test index with filter containing multiple user-defined properties
        # Filter is 'property-arch=x86_64&property-distro=ubuntu'.
        # Verify only subject2 is returned.
        res = self.get_api_response_ext(200, url='/subjects?'
                                                 'property-arch=x86_64&'
                                                 'property-distro=ubuntu')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])

        # Test index with filter containing multiple user-defined properties
        # Filter is 'property-arch=i386&property-distro=ubuntu'.
        # Verify only subject1 is returned.
        res = self.get_api_response_ext(200, url='/subjects?property-arch=i386&'
                                                 'property-distro=ubuntu')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject1_id, subjects[0]['id'])

        # Test index with filter containing multiple user-defined properties.
        # Filter is 'property-arch=random&property-distro=ubuntu'.
        # Verify neither subjects are returned.
        res = self.get_api_response_ext(200, url='/subjects?'
                                                 'property-arch=random&'
                                                 'property-distro=ubuntu')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

        # Test index with filter containing multiple user-defined properties.
        # Filter is 'property-arch=random&property-distro=random'.
        # Verify neither subjects are returned.
        res = self.get_api_response_ext(200, url='/subjects?'
                                                 'property-arch=random&'
                                                 'property-distro=random')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

        # Test index with filter containing multiple user-defined properties.
        # Filter is 'property-boo=far&property-poo=far'.
        # Verify neither subjects are returned.
        res = self.get_api_response_ext(200, url='/subjects?property-boo=far&'
                                                 'property-poo=far')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

        # Test index with filter containing multiple user-defined properties.
        # Filter is 'property-foo=bar&property-poo=far'.
        # Verify neither subjects are returned.
        res = self.get_api_response_ext(200, url='/subjects?property-foo=bar&'
                                                 'property-poo=far')
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

    def test_get_index_filter_name(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects that have a specific name. This is really a sanity
        check, filtering is tested more in-depth using /subjects/detail
        """

        extra_fixture = self.get_fixture(id=_gen_uuid(),
                                         name='new name! #123', size=19)

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), name='new name! #123')
        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url='/subjects?name=new name! #123')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(2, len(subjects))

        for subject in subjects:
            self.assertEqual('new name! #123', subject['name'])

    def test_get_index_sort_default_created_at_desc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects that conforms to a default sort key/dir
        """
        time1 = timeutils.utcnow() + datetime.timedelta(seconds=5)
        time2 = timeutils.utcnow() + datetime.timedelta(seconds=4)
        time3 = timeutils.utcnow()

        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, size=19, created_at=time1)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, created_at=time2)

        db_api.subject_create(self.context, extra_fixture)

        UUID5 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID5, created_at=time3)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url='/subjects')
        self.assertEqualSubjects(res, (UUID3, UUID4, UUID5, UUID2))

    def test_get_index_bad_sort_key(self):
        """Ensure a 400 is returned when a bad sort_key is provided."""
        self.get_api_response_ext(400, url='/subjects?sort_key=asdf')

    def test_get_index_bad_sort_dir(self):
        """Ensure a 400 is returned when a bad sort_dir is provided."""
        self.get_api_response_ext(400, url='/subjects?sort_dir=asdf')

    def test_get_index_null_name(self):
        """Check 200 is returned when sort_key is null name

        Check 200 is returned when sort_key is name and name is null
        for specified marker
        """
        UUID6 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID6, name=None)

        db_api.subject_create(self.context, extra_fixture)
        self.get_api_response_ext(
            200, url='/subjects?sort_key=name&marker=%s' % UUID6)

    def test_get_index_null_disk_format(self):
        """Check 200 is returned when sort_key is null disk_format

        Check 200 is returned when sort_key is disk_format and
        disk_format is null for specified marker
        """
        UUID6 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID6, disk_format=None, size=19)

        db_api.subject_create(self.context, extra_fixture)
        self.get_api_response_ext(
            200, url='/subjects?sort_key=disk_format&marker=%s' % UUID6)

    def test_get_index_null_container_format(self):
        """Check 200 is returned when sort_key is null container_format

        Check 200 is returned when sort_key is container_format and
        container_format is null for specified marker
        """
        UUID6 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID6, container_format=None)

        db_api.subject_create(self.context, extra_fixture)
        self.get_api_response_ext(
            200, url='/subjects?sort_key=container_format&marker=%s' % UUID6)

    def test_get_index_sort_name_asc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted alphabetically by name in
        ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, name='asdf', size=19)
        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, name='xyz')

        db_api.subject_create(self.context, extra_fixture)

        url = '/subjects?sort_key=name&sort_dir=asc'
        res = self.get_api_response_ext(200, url=url)
        self.assertEqualSubjects(res, (UUID3, UUID2, UUID4))

    def test_get_index_sort_status_desc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted alphabetically by status in
        descending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, status='queued', size=19)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url=(
            '/subjects?sort_key=status&sort_dir=desc'))
        self.assertEqualSubjects(res, (UUID3, UUID4, UUID2))

    def test_get_index_sort_disk_format_asc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted alphabetically by disk_format in
        ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, disk_format='ami',
                                         container_format='ami', size=19)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, disk_format='vdi')

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url=(
            '/subjects?sort_key=disk_format&sort_dir=asc'))
        self.assertEqualSubjects(res, (UUID3, UUID4, UUID2))

    def test_get_index_sort_container_format_desc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted alphabetically by container_format in
        descending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, size=19, disk_format='ami',
                                         container_format='ami')

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, disk_format='iso',
                                         container_format='bare')

        db_api.subject_create(self.context, extra_fixture)

        url = '/subjects?sort_key=container_format&sort_dir=desc'
        res = self.get_api_response_ext(200, url=url)
        self.assertEqualSubjects(res, (UUID2, UUID4, UUID3))

    def test_get_index_sort_size_asc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted by size in ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, disk_format='ami',
                                         container_format='ami', size=100)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, disk_format='iso',
                                         container_format='bare', size=2)

        db_api.subject_create(self.context, extra_fixture)

        url = '/subjects?sort_key=size&sort_dir=asc'
        res = self.get_api_response_ext(200, url=url)
        self.assertEqualSubjects(res, (UUID4, UUID2, UUID3))

    def test_get_index_sort_created_at_asc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted by created_at in ascending order.
        """
        now = timeutils.utcnow()
        time1 = now + datetime.timedelta(seconds=5)
        time2 = now

        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, created_at=time1, size=19)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, created_at=time2)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url=(
            '/subjects?sort_key=created_at&sort_dir=asc'))
        self.assertEqualSubjects(res, (UUID2, UUID4, UUID3))

    def test_get_index_sort_updated_at_desc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted by updated_at in descending order.
        """
        now = timeutils.utcnow()
        time1 = now + datetime.timedelta(seconds=5)
        time2 = now

        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, size=19, created_at=None,
                                         updated_at=time1)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, created_at=None,
                                         updated_at=time2)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url=(
            '/subjects?sort_key=updated_at&sort_dir=desc'))
        self.assertEqualSubjects(res, (UUID3, UUID4, UUID2))

    def test_get_details(self):
        """
        Tests that the /subjects/detail registry API returns
        a mapping containing a list of detailed subject information
        """
        fixture = {'id': UUID2,
                   'name': 'fake subject #2',
                   'is_public': True,
                   'size': 19,
                   'min_disk': 5,
                   'min_ram': 256,
                   'checksum': None,
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'status': 'active'}

        res = self.get_api_response_ext(200, url='/subjects/detail')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))

        for k, v in six.iteritems(fixture):
            self.assertEqual(v, subjects[0][k])

    def test_get_details_limit_marker(self):
        """
        Tests that the /subjects/details registry API returns list of
        public subjects that conforms to limit and marker query params.
        This functionality is tested more thoroughly on /subjects, this is
        just a sanity check
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, size=20)

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid())

        db_api.subject_create(self.context, extra_fixture)

        url = '/subjects/detail?marker=%s&limit=1' % UUID3
        res = self.get_api_response_ext(200, url=url)
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))

        # expect list to be sorted by created_at desc
        self.assertEqual(UUID2, subjects[0]['id'])

    def test_get_details_invalid_marker(self):
        """
        Tests that the /subjects/detail registry API returns a 400
        when an invalid marker is provided
        """
        url = '/subjects/detail?marker=%s' % _gen_uuid()
        self.get_api_response_ext(400, url=url)

    def test_get_details_malformed_marker(self):
        """
        Tests that the /subjects/detail registry API returns a 400
        when a malformed marker is provided
        """
        res = self.get_api_response_ext(400, url='/subjects/detail?marker=4')
        self.assertIn(b'marker', res.body)

    def test_get_details_forbidden_marker(self):
        """
        Tests that the /subjects/detail registry API returns a 400
        when a forbidden marker is provided
        """
        test_rserv = rserver.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(test_rserv, is_admin=False)
        self.get_api_response_ext(400, api=api,
                                  url='/subjects/detail?marker=%s' % UUID1)

    def test_get_details_filter_name(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects that have a specific name
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(),
                                         name='new name! #123', size=20)

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(),
                                         name='new name! #123')

        db_api.subject_create(self.context, extra_fixture)

        url = '/subjects/detail?name=new name! #123'
        res = self.get_api_response_ext(200, url=url)
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(2, len(subjects))

        for subject in subjects:
            self.assertEqual('new name! #123', subject['name'])

    def test_get_details_filter_status(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects that have a specific status
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving')

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), size=19,
                                         status='active')

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200,
                                        url='/subjects/detail?status=saving')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))

        for subject in subjects:
            self.assertEqual('saving', subject['status'])

    def test_get_details_filter_container_format(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects that have a specific container_format
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(), disk_format='vdi',
                                         size=19)

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), disk_format='ami',
                                         container_format='ami', size=19)

        db_api.subject_create(self.context, extra_fixture)

        url = '/subjects/detail?container_format=ovf'
        res = self.get_api_response_ext(200, url=url)
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(2, len(subjects))

        for subject in subjects:
            self.assertEqual('ovf', subject['container_format'])

    def test_get_details_filter_min_disk(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects that have a specific min_disk
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(), min_disk=7, size=19)

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), disk_format='ami',
                                         container_format='ami', size=19)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url='/subjects/detail?min_disk=7')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))

        for subject in subjects:
            self.assertEqual(7, subject['min_disk'])

    def test_get_details_filter_min_ram(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects that have a specific min_ram
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(), min_ram=514, size=19)

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), disk_format='ami',
                                         container_format='ami', size=19)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url='/subjects/detail?min_ram=514')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))

        for subject in subjects:
            self.assertEqual(514, subject['min_ram'])

    def test_get_details_filter_disk_format(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects that have a specific disk_format
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(), size=19)

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), disk_format='ami',
                                         container_format='ami', size=19)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200,
                                        url='/subjects/detail?disk_format=vhd')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(2, len(subjects))

        for subject in subjects:
            self.assertEqual('vhd', subject['disk_format'])

    def test_get_details_filter_size_min(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects that have a size greater than or equal to size_min
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(), size=18)

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), disk_format='ami',
                                         container_format='ami')

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url='/subjects/detail?size_min=19')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(2, len(subjects))

        for subject in subjects:
            self.assertGreaterEqual(subject['size'], 19)

    def test_get_details_filter_size_max(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects that have a size less than or equal to size_max
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(), size=18)

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), disk_format='ami',
                                         container_format='ami')

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url='/subjects/detail?size_max=19')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(2, len(subjects))

        for subject in subjects:
            self.assertLessEqual(subject['size'], 19)

    def test_get_details_filter_size_min_max(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects that have a size less than or equal to size_max
        and greater than or equal to size_min
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(), size=18)

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), disk_format='ami',
                                         container_format='ami')

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), size=6)

        db_api.subject_create(self.context, extra_fixture)

        url = '/subjects/detail?size_min=18&size_max=19'
        res = self.get_api_response_ext(200, url=url)
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(2, len(subjects))

        for subject in subjects:
            self.assertTrue(18 <= subject['size'] <= 19)

    def test_get_details_filter_changes_since(self):
        """
        Tests that the /subjects/detail registry API returns list of
        subjects that changed since the time defined by changes-since
        """
        dt1 = timeutils.utcnow() - datetime.timedelta(1)
        iso1 = timeutils.isotime(dt1)

        date_only1 = dt1.strftime('%Y-%m-%d')
        date_only2 = dt1.strftime('%Y%m%d')
        date_only3 = dt1.strftime('%Y-%m%d')

        dt2 = timeutils.utcnow() + datetime.timedelta(1)
        iso2 = timeutils.isotime(dt2)

        subject_ts = timeutils.utcnow() + datetime.timedelta(2)
        hour_before = subject_ts.strftime('%Y-%m-%dT%H:%M:%S%%2B01:00')
        hour_after = subject_ts.strftime('%Y-%m-%dT%H:%M:%S-01:00')

        dt4 = timeutils.utcnow() + datetime.timedelta(3)
        iso4 = timeutils.isotime(dt4)

        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, size=18)

        db_api.subject_create(self.context, extra_fixture)
        db_api.subject_destroy(self.context, UUID3)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4,
                                         disk_format='ami',
                                         container_format='ami',
                                         created_at=subject_ts,
                                         updated_at=subject_ts)

        db_api.subject_create(self.context, extra_fixture)

        # Check a standard list, 4 subjects in db (2 deleted)
        res = self.get_api_response_ext(200, url='/subjects/detail')
        self.assertEqualSubjects(res, (UUID4, UUID2))

        # Expect 3 subjects (1 deleted)
        res = self.get_api_response_ext(200, url=(
            '/subjects/detail?changes-since=%s' % iso1))
        self.assertEqualSubjects(res, (UUID4, UUID3, UUID2))

        # Expect 1 subjects (0 deleted)
        res = self.get_api_response_ext(200, url=(
            '/subjects/detail?changes-since=%s' % iso2))
        self.assertEqualSubjects(res, (UUID4,))

        # Expect 1 subjects (0 deleted)
        res = self.get_api_response_ext(200, url=(
            '/subjects/detail?changes-since=%s' % hour_before))
        self.assertEqualSubjects(res, (UUID4,))

        # Expect 0 subjects (0 deleted)
        res = self.get_api_response_ext(200, url=(
            '/subjects/detail?changes-since=%s' % hour_after))
        self.assertEqualSubjects(res, ())

        # Expect 0 subjects (0 deleted)
        res = self.get_api_response_ext(200, url=(
            '/subjects/detail?changes-since=%s' % iso4))
        self.assertEqualSubjects(res, ())

        for param in [date_only1, date_only2, date_only3]:
            # Expect 3 subjects (1 deleted)
            res = self.get_api_response_ext(200, url=(
                '/subjects/detail?changes-since=%s' % param))
            self.assertEqualSubjects(res, (UUID4, UUID3, UUID2))

        # Bad request (empty changes-since param)
        self.get_api_response_ext(400,
                                  url='/subjects/detail?changes-since=')

    def test_get_details_filter_property(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects that have a specific custom property
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(), size=19,
                                         properties={'prop_123': 'v a'})

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), size=19,
                                         disk_format='ami',
                                         container_format='ami',
                                         properties={'prop_123': 'v b'})

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url=(
            '/subjects/detail?property-prop_123=v%20a'))
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))

        for subject in subjects:
            self.assertEqual('v a', subject['properties']['prop_123'])

    def test_get_details_filter_public_none(self):
        """
        Tests that the /subjects/detail registry API returns list of
        all subjects if is_public none is passed
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(),
                                         is_public=False, size=18)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200,
                                        url='/subjects/detail?is_public=None')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(3, len(subjects))

    def test_get_details_filter_public_false(self):
        """
        Tests that the /subjects/detail registry API returns list of
        private subjects if is_public false is passed
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(),
                                         is_public=False, size=18)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200,
                                        url='/subjects/detail?is_public=False')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(2, len(subjects))

        for subject in subjects:
            self.assertEqual(False, subject['is_public'])

    def test_get_details_filter_public_true(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects if is_public true is passed (same as default)
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(),
                                         is_public=False, size=18)

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200,
                                        url='/subjects/detail?is_public=True')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))

        for subject in subjects:
            self.assertTrue(subject['is_public'])

    def test_get_details_filter_public_string_format(self):
        """
        Tests that the /subjects/detail registry
        API returns 400 Bad error for filter is_public with wrong format
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(),
                                         is_public='true', size=18)

        db_api.subject_create(self.context, extra_fixture)

        self.get_api_response_ext(400, url='/subjects/detail?is_public=public')

    def test_get_details_filter_deleted_false(self):
        """
        Test that the /subjects/detail registry
        API return list of subjects with deleted filter = false

        """
        extra_fixture = {'id': _gen_uuid(),
                         'status': 'active',
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'test deleted filter 1',
                         'size': 18,
                         'deleted': False,
                         'checksum': None}

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200,
                                        url='/subjects/detail?deleted=False')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']

        for subject in subjects:
            self.assertFalse(subject['deleted'])

    def test_get_filter_no_public_with_no_admin(self):
        """
        Tests that the /subjects/detail registry API returns list of
        public subjects if is_public true is passed (same as default)
        """
        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4,
                                         is_public=False, size=18)

        db_api.subject_create(self.context, extra_fixture)
        test_rserv = rserver.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(test_rserv, is_admin=False)
        res = self.get_api_response_ext(200, api=api,
                                        url='/subjects/detail?is_public=False')
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))
        # Check that for non admin user only is_public = True subjects returns
        for subject in subjects:
            self.assertTrue(subject['is_public'])

    def test_get_filter_protected_with_None_value(self):
        """
        Tests that the /subjects/detail registry API returns 400 error
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(), size=18,
                                         protected="False")

        db_api.subject_create(self.context, extra_fixture)
        self.get_api_response_ext(400, url='/subjects/detail?protected=')

    def test_get_filter_protected_with_True_value(self):
        """
        Tests that the /subjects/detail registry API returns 400 error
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(),
                                         size=18, protected="True")

        db_api.subject_create(self.context, extra_fixture)
        self.get_api_response_ext(200, url='/subjects/detail?protected=True')

    def test_get_details_sort_name_asc(self):
        """
        Tests that the /subjects/details registry API returns list of
        public subjects sorted alphabetically by name in
        ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, name='asdf', size=19)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, name='xyz')

        db_api.subject_create(self.context, extra_fixture)

        res = self.get_api_response_ext(200, url=(
            '/subjects/detail?sort_key=name&sort_dir=asc'))
        self.assertEqualSubjects(res, (UUID3, UUID2, UUID4))

    def test_create_subject(self):
        """Tests that the /subjects POST registry API creates the subject"""

        fixture = self.get_minimal_fixture()
        body = jsonutils.dump_as_bytes(dict(subject=fixture))

        res = self.get_api_response_ext(200, body=body,
                                        method='POST', content_type='json')
        res_dict = jsonutils.loads(res.body)

        for k, v in six.iteritems(fixture):
            self.assertEqual(v, res_dict['subject'][k])

        # Test status was updated properly
        self.assertEqual('active', res_dict['subject']['status'])

    def test_create_subject_with_min_disk(self):
        """Tests that the /subjects POST registry API creates the subject"""
        fixture = self.get_minimal_fixture(min_disk=5)
        body = jsonutils.dump_as_bytes(dict(subject=fixture))

        res = self.get_api_response_ext(200, body=body,
                                        method='POST', content_type='json')
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(5, res_dict['subject']['min_disk'])

    def test_create_subject_with_min_ram(self):
        """Tests that the /subjects POST registry API creates the subject"""
        fixture = self.get_minimal_fixture(min_ram=256)
        body = jsonutils.dump_as_bytes(dict(subject=fixture))

        res = self.get_api_response_ext(200, body=body,
                                        method='POST', content_type='json')
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(256, res_dict['subject']['min_ram'])

    def test_create_subject_with_min_ram_default(self):
        """Tests that the /subjects POST registry API creates the subject"""
        fixture = self.get_minimal_fixture()
        body = jsonutils.dump_as_bytes(dict(subject=fixture))

        res = self.get_api_response_ext(200, body=body,
                                        method='POST', content_type='json')
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(0, res_dict['subject']['min_ram'])

    def test_create_subject_with_min_disk_default(self):
        """Tests that the /subjects POST registry API creates the subject"""
        fixture = self.get_minimal_fixture()
        body = jsonutils.dump_as_bytes(dict(subject=fixture))

        res = self.get_api_response_ext(200, body=body,
                                        method='POST', content_type='json')
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(0, res_dict['subject']['min_disk'])

    def test_create_subject_with_bad_status(self):
        """Tests proper exception is raised if a bad status is set"""
        fixture = self.get_minimal_fixture(id=_gen_uuid(), status='bad status')
        body = jsonutils.dump_as_bytes(dict(subject=fixture))

        res = self.get_api_response_ext(400, body=body,
                                        method='POST', content_type='json')
        self.assertIn(b'Invalid subject status', res.body)

    def test_create_subject_with_bad_id(self):
        """Tests proper exception is raised if a bad disk_format is set"""
        fixture = self.get_minimal_fixture(id='asdf')

        body = jsonutils.dump_as_bytes(dict(subject=fixture))
        self.get_api_response_ext(400, content_type='json', method='POST',
                                  body=body)

    def test_create_subject_with_subject_id_in_log(self):
        """Tests correct subject id in log message when creating subject"""
        fixture = self.get_minimal_fixture(
            id='0564c64c-3545-4e34-abfb-9d18e5f2f2f9')
        self.log_subject_id = False

        def fake_log_info(msg, subject_data):
            if ('0564c64c-3545-4e34-abfb-9d18e5f2f2f9' == subject_data['id'] and
                    'Successfully created subject' in msg):
                self.log_subject_id = True

        self.stubs.Set(rserver.subjects.LOG, 'info', fake_log_info)

        body = jsonutils.dump_as_bytes(dict(subject=fixture))
        self.get_api_response_ext(200, content_type='json', method='POST',
                                  body=body)
        self.assertTrue(self.log_subject_id)

    def test_update_subject(self):
        """Tests that the /subjects PUT registry API updates the subject"""
        fixture = {'name': 'fake public subject #2',
                   'min_disk': 5,
                   'min_ram': 256,
                   'disk_format': 'raw'}
        body = jsonutils.dump_as_bytes(dict(subject=fixture))

        res = self.get_api_response_ext(200, url='/subjects/%s' % UUID2,
                                        body=body, method='PUT',
                                        content_type='json')

        res_dict = jsonutils.loads(res.body)

        self.assertNotEqual(res_dict['subject']['created_at'],
                            res_dict['subject']['updated_at'])

        for k, v in six.iteritems(fixture):
            self.assertEqual(v, res_dict['subject'][k])

    @mock.patch.object(rserver.subjects.LOG, 'debug')
    def test_update_subject_not_log_sensitive_info(self, log_debug):
        """
        Tests that there is no any sensitive info of subject location
        was logged in subject during the subject update operation.
        """

        def fake_log_debug(fmt_str, subject_meta):
            self.assertNotIn("'locations'", fmt_str % subject_meta)

        fixture = {'name': 'fake public subject #2',
                   'min_disk': 5,
                   'min_ram': 256,
                   'disk_format': 'raw',
                   'location': 'fake://subject'}
        body = jsonutils.dump_as_bytes(dict(subject=fixture))

        log_debug.side_effect = fake_log_debug

        res = self.get_api_response_ext(200, url='/subjects/%s' % UUID2,
                                        body=body, method='PUT',
                                        content_type='json')

        res_dict = jsonutils.loads(res.body)

        self.assertNotEqual(res_dict['subject']['created_at'],
                            res_dict['subject']['updated_at'])

        for k, v in six.iteritems(fixture):
            self.assertEqual(v, res_dict['subject'][k])

    def test_update_subject_not_existing(self):
        """
        Tests proper exception is raised if attempt to update
        non-existing subject
        """
        fixture = {'status': 'killed'}
        body = jsonutils.dump_as_bytes(dict(subject=fixture))

        self.get_api_response_ext(404, url='/subjects/%s' % _gen_uuid(),
                                  method='PUT', body=body, content_type='json')

    def test_update_subject_with_bad_status(self):
        """Tests that exception raised trying to set a bad status"""
        fixture = {'status': 'invalid'}
        body = jsonutils.dump_as_bytes(dict(subject=fixture))

        res = self.get_api_response_ext(400, method='PUT', body=body,
                                        url='/subjects/%s' % UUID2,
                                        content_type='json')
        self.assertIn(b'Invalid subject status', res.body)

    def test_update_private_subject_no_admin(self):
        """
        Tests proper exception is raised if attempt to update
        private subject with non admin user, that not belongs to it
        """
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, size=19, is_public=False,
                                         protected=True, owner='test user')

        db_api.subject_create(self.context, extra_fixture)
        test_rserv = rserver.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(test_rserv, is_admin=False)
        body = jsonutils.dump_as_bytes(dict(subject=extra_fixture))
        self.get_api_response_ext(404, body=body, api=api,
                                  url='/subjects/%s' % UUID8, method='PUT',
                                  content_type='json')

    def test_delete_subject(self):
        """Tests that the /subjects DELETE registry API deletes the subject"""

        # Grab the original number of subjects
        res = self.get_api_response_ext(200)
        res_dict = jsonutils.loads(res.body)

        orig_num_subjects = len(res_dict['subjects'])

        # Delete subject #2
        self.get_api_response_ext(200, url='/subjects/%s' % UUID2,
                                  method='DELETE')

        # Verify one less subject
        res = self.get_api_response_ext(200)
        res_dict = jsonutils.loads(res.body)

        new_num_subjects = len(res_dict['subjects'])
        self.assertEqual(orig_num_subjects - 1, new_num_subjects)

    def test_delete_subject_response(self):
        """Tests that the registry API delete returns the subject metadata"""

        subject = self.FIXTURES[0]
        res = self.get_api_response_ext(200, url='/subjects/%s' % subject['id'],
                                        method='DELETE')
        deleted_subject = jsonutils.loads(res.body)['subject']

        self.assertEqual(subject['id'], deleted_subject['id'])
        self.assertTrue(deleted_subject['deleted'])
        self.assertTrue(deleted_subject['deleted_at'])

    def test_delete_subject_not_existing(self):
        """
        Tests proper exception is raised if attempt to delete
        non-existing subject
        """
        self.get_api_response_ext(404, url='/subjects/%s' % _gen_uuid(),
                                  method='DELETE')

    def test_delete_public_subject_no_admin(self):
        """
        Tests proper exception is raised if attempt to delete
        public subject with non admin user
        """
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, size=19, protected=True,
                                         owner='test user')

        db_api.subject_create(self.context, extra_fixture)
        test_rserv = rserver.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(test_rserv, is_admin=False)
        self.get_api_response_ext(403, url='/subjects/%s' % UUID8,
                                  method='DELETE', api=api)

    def test_delete_private_subject_no_admin(self):
        """
        Tests proper exception is raised if attempt to delete
        private subject with non admin user, that not belongs to it
        """
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, is_public=False, size=19,
                                         protected=True, owner='test user')

        db_api.subject_create(self.context, extra_fixture)
        test_rserv = rserver.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(test_rserv, is_admin=False)
        self.get_api_response_ext(404, url='/subjects/%s' % UUID8,
                                  method='DELETE', api=api)

    def test_get_subject_members(self):
        """
        Tests members listing for existing subjects
        """
        res = self.get_api_response_ext(200, url='/subjects/%s/members' % UUID2,
                                        method='GET')

        memb_list = jsonutils.loads(res.body)
        num_members = len(memb_list['members'])
        self.assertEqual(0, num_members)

    def test_get_subject_members_not_existing(self):
        """
        Tests proper exception is raised if attempt to get members of
        non-existing subject
        """
        self.get_api_response_ext(404, method='GET',
                                  url='/subjects/%s/members' % _gen_uuid())

    def test_get_subject_members_forbidden(self):
        """
        Tests proper exception is raised if attempt to get members of
        non-existing subject

        """
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, is_public=False, size=19,
                                         protected=True, owner='test user')

        db_api.subject_create(self.context, extra_fixture)
        test_rserv = rserver.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(test_rserv, is_admin=False)
        self.get_api_response_ext(404, url='/subjects/%s/members' % UUID8,
                                  method='GET', api=api)

    def test_get_member_subjects(self):
        """
        Tests subject listing for members
        """
        res = self.get_api_response_ext(200, url='/shared-subjects/pattieblack',
                                        method='GET')

        memb_list = jsonutils.loads(res.body)
        num_members = len(memb_list['shared_subjects'])
        self.assertEqual(0, num_members)

    def test_replace_members(self):
        """
        Tests replacing subject members raises right exception
        """
        self.api = test_utils.FakeAuthMiddleware(rserver.API(self.mapper),
                                                 is_admin=False)
        fixture = dict(member_id='pattieblack')
        body = jsonutils.dump_as_bytes(dict(subject_memberships=fixture))

        self.get_api_response_ext(401, method='PUT', body=body,
                                  url='/subjects/%s/members' % UUID2,
                                  content_type='json')

    def test_update_all_subject_members_non_existing_subject_id(self):
        """
        Test update subject members raises right exception
        """
        # Update all subject members
        fixture = dict(member_id='test1')
        req = webob.Request.blank('/subjects/%s/members' % _gen_uuid())
        req.method = 'PUT'
        self.context.tenant = 'test2'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(subject_memberships=fixture))
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

    def test_update_all_subject_members_invalid_membership_association(self):
        """
        Test update subject members raises right exception
        """
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, size=19, protected=False,
                                         owner='test user')

        db_api.subject_create(self.context, extra_fixture)

        # Add several members to subject
        req = webob.Request.blank('/subjects/%s/members/test1' % UUID8)
        req.method = 'PUT'
        res = req.get_response(self.api)
        # Get all subject members:
        res = self.get_api_response_ext(200, url='/subjects/%s/members' % UUID8,
                                        method='GET')

        memb_list = jsonutils.loads(res.body)
        num_members = len(memb_list['members'])
        self.assertEqual(1, num_members)

        fixture = dict(member_id='test1')
        body = jsonutils.dump_as_bytes(dict(subject_memberships=fixture))
        self.get_api_response_ext(400, url='/subjects/%s/members' % UUID8,
                                  method='PUT', body=body,
                                  content_type='json')

    def test_update_all_subject_members_non_shared_subject_forbidden(self):
        """
        Test update subject members raises right exception
        """
        test_rserv = rserver.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(test_rserv, is_admin=False)
        UUID9 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID9, size=19, protected=False)

        db_api.subject_create(self.context, extra_fixture)
        fixture = dict(member_id='test1')
        req = webob.Request.blank('/subjects/%s/members' % UUID9)
        req.headers['X-Auth-Token'] = 'test1:test1:'
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(subject_memberships=fixture))

        res = req.get_response(api)
        self.assertEqual(403, res.status_int)

    def test_update_all_subject_members(self):
        """
        Test update non existing subject members
        """
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, size=19, protected=False,
                                         owner='test user')

        db_api.subject_create(self.context, extra_fixture)

        # Add several members to subject
        req = webob.Request.blank('/subjects/%s/members/test1' % UUID8)
        req.method = 'PUT'
        req.get_response(self.api)

        fixture = [dict(member_id='test2', can_share=True)]
        body = jsonutils.dump_as_bytes(dict(memberships=fixture))
        self.get_api_response_ext(204, url='/subjects/%s/members' % UUID8,
                                  method='PUT', body=body,
                                  content_type='json')

    def test_update_all_subject_members_bad_request(self):
        """
        Test that right exception is raises
        in case if wrong memberships association is supplied
        """
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, size=19, protected=False,
                                         owner='test user')

        db_api.subject_create(self.context, extra_fixture)

        # Add several members to subject
        req = webob.Request.blank('/subjects/%s/members/test1' % UUID8)
        req.method = 'PUT'
        req.get_response(self.api)
        fixture = dict(member_id='test3')
        body = jsonutils.dump_as_bytes(dict(memberships=fixture))
        self.get_api_response_ext(400, url='/subjects/%s/members' % UUID8,
                                  method='PUT', body=body,
                                  content_type='json')

    def test_update_all_subject_existing_members(self):
        """
        Test update existing subject members
        """
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, size=19, protected=False,
                                         owner='test user')

        db_api.subject_create(self.context, extra_fixture)

        # Add several members to subject
        req = webob.Request.blank('/subjects/%s/members/test1' % UUID8)
        req.method = 'PUT'
        req.get_response(self.api)

        fixture = [dict(member_id='test1', can_share=False)]
        body = jsonutils.dump_as_bytes(dict(memberships=fixture))
        self.get_api_response_ext(204, url='/subjects/%s/members' % UUID8,
                                  method='PUT', body=body,
                                  content_type='json')

    def test_update_all_subject_existing_deleted_members(self):
        """
        Test update existing subject members
        """
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, size=19, protected=False,
                                         owner='test user')

        db_api.subject_create(self.context, extra_fixture)

        # Add a new member to an subject
        req = webob.Request.blank('/subjects/%s/members/test1' % UUID8)
        req.method = 'PUT'
        req.get_response(self.api)

        # Delete the existing member
        self.get_api_response_ext(204, method='DELETE',
                                  url='/subjects/%s/members/test1' % UUID8)

        # Re-add the deleted member by replacing membership list
        fixture = [dict(member_id='test1', can_share=False)]
        body = jsonutils.dump_as_bytes(dict(memberships=fixture))
        self.get_api_response_ext(204, url='/subjects/%s/members' % UUID8,
                                  method='PUT', body=body,
                                  content_type='json')
        memb_list = db_api.subject_member_find(self.context, subject_id=UUID8)
        self.assertEqual(1, len(memb_list))

    def test_add_member(self):
        """
        Tests adding subject members raises right exception
        """
        self.api = test_utils.FakeAuthMiddleware(rserver.API(self.mapper),
                                                 is_admin=False)
        self.get_api_response_ext(401, method='PUT',
                                  url=('/subjects/%s/members/pattieblack' %
                                       UUID2))

    def test_add_member_to_subject_positive(self):
        """
        Test check that member can be successfully added
        """
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, size=19, protected=False,
                                         owner='test user')

        db_api.subject_create(self.context, extra_fixture)
        fixture = dict(can_share=True)
        test_uri = '/subjects/%s/members/test_add_member_positive'
        body = jsonutils.dump_as_bytes(dict(member=fixture))
        self.get_api_response_ext(204, url=test_uri % UUID8,
                                  method='PUT', body=body,
                                  content_type='json')

    def test_add_member_to_non_exist_subject(self):
        """
        Test check that member can't be added for
        non exist subject
        """
        fixture = dict(can_share=True)
        test_uri = '/subjects/%s/members/test_add_member_positive'
        body = jsonutils.dump_as_bytes(dict(member=fixture))
        self.get_api_response_ext(404, url=test_uri % _gen_uuid(),
                                  method='PUT', body=body,
                                  content_type='json')

    def test_add_subject_member_non_shared_subject_forbidden(self):
        """
        Test update subject members raises right exception
        """
        test_rserver_api = rserver.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(
            test_rserver_api, is_admin=False)
        UUID9 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID9, size=19, protected=False)
        db_api.subject_create(self.context, extra_fixture)
        fixture = dict(can_share=True)
        test_uri = '/subjects/%s/members/test_add_member_to_non_share_subject'
        req = webob.Request.blank(test_uri % UUID9)
        req.headers['X-Auth-Token'] = 'test1:test1:'
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(member=fixture))

        res = req.get_response(api)
        self.assertEqual(403, res.status_int)

    def test_add_member_to_subject_bad_request(self):
        """
        Test check right status code is returned
        """
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, size=19, protected=False,
                                         owner='test user')

        db_api.subject_create(self.context, extra_fixture)

        fixture = [dict(can_share=True)]
        test_uri = '/subjects/%s/members/test_add_member_bad_request'
        body = jsonutils.dump_as_bytes(dict(member=fixture))
        self.get_api_response_ext(400, url=test_uri % UUID8,
                                  method='PUT', body=body,
                                  content_type='json')

    def test_delete_member(self):
        """
        Tests deleting subject members raises right exception
        """
        self.api = test_utils.FakeAuthMiddleware(rserver.API(self.mapper),
                                                 is_admin=False)
        self.get_api_response_ext(401, method='DELETE',
                                  url=('/subjects/%s/members/pattieblack' %
                                       UUID2))

    def test_delete_member_invalid(self):
        """
        Tests deleting a invalid/non existing member raises right exception
        """
        self.api = test_utils.FakeAuthMiddleware(rserver.API(self.mapper),
                                                 is_admin=True)
        res = self.get_api_response_ext(404, method='DELETE',
                                        url=('/subjects/%s/members/pattieblack' %
                                             UUID2))
        self.assertIn(b'Membership could not be found', res.body)

    def test_delete_member_from_non_exist_subject(self):
        """
        Tests deleting subject members raises right exception
        """
        test_rserver_api = rserver.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_rserver_api, is_admin=True)
        test_uri = '/subjects/%s/members/pattieblack'
        self.get_api_response_ext(404, method='DELETE',
                                  url=test_uri % _gen_uuid())

    def test_delete_subject_member_non_shared_subject_forbidden(self):
        """
        Test delete subject members raises right exception
        """
        test_rserver_api = rserver.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(
            test_rserver_api, is_admin=False)
        UUID9 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID9, size=19, protected=False)

        db_api.subject_create(self.context, extra_fixture)
        test_uri = '/subjects/%s/members/test_add_member_to_non_share_subject'
        req = webob.Request.blank(test_uri % UUID9)
        req.headers['X-Auth-Token'] = 'test1:test1:'
        req.method = 'DELETE'
        req.content_type = 'application/json'

        res = req.get_response(api)
        self.assertEqual(403, res.status_int)

    def test_add_member_delete_create(self):
        """
        Test check that the same member can be successfully added after delete
        it, and the same record will be reused for the same membership.
        """
        # add a member
        UUID8 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID8, size=19, protected=False,
                                         owner='test user')

        db_api.subject_create(self.context, extra_fixture)
        fixture = dict(can_share=True)
        test_uri = '/subjects/%s/members/test_add_member_delete_create'
        body = jsonutils.dump_as_bytes(dict(member=fixture))
        self.get_api_response_ext(204, url=test_uri % UUID8,
                                  method='PUT', body=body,
                                  content_type='json')
        memb_list = db_api.subject_member_find(self.context, subject_id=UUID8)
        self.assertEqual(1, len(memb_list))
        memb_list2 = db_api.subject_member_find(self.context,
                                              subject_id=UUID8,
                                              include_deleted=True)
        self.assertEqual(1, len(memb_list2))
        # delete the member
        self.get_api_response_ext(204, method='DELETE',
                                  url=test_uri % UUID8)
        memb_list = db_api.subject_member_find(self.context, subject_id=UUID8)
        self.assertEqual(0, len(memb_list))
        memb_list2 = db_api.subject_member_find(self.context,
                                              subject_id=UUID8,
                                              include_deleted=True)
        self.assertEqual(1, len(memb_list2))
        # create it again
        self.get_api_response_ext(204, url=test_uri % UUID8,
                                  method='PUT', body=body,
                                  content_type='json')
        memb_list = db_api.subject_member_find(self.context, subject_id=UUID8)
        self.assertEqual(1, len(memb_list))
        memb_list2 = db_api.subject_member_find(self.context,
                                              subject_id=UUID8,
                                              include_deleted=True)
        self.assertEqual(1, len(memb_list2))

    def test_get_on_subject_member(self):
        """
        Test GET on subject members raises 405 and produces correct Allow headers
        """
        self.api = test_utils.FakeAuthMiddleware(rserver.API(self.mapper),
                                                 is_admin=False)
        uri = '/subjects/%s/members/123' % UUID1
        req = webob.Request.blank(uri)
        req.method = 'GET'
        res = req.get_response(self.api)
        self.assertEqual(405, res.status_int)
        self.assertIn(('Allow', 'PUT, DELETE'), res.headerlist)

    def test_get_subjects_bad_urls(self):
        """Check that routes collections are not on (LP bug 1185828)"""
        self.get_api_response_ext(404, url='/subjects/detail.xxx')

        self.get_api_response_ext(404, url='/subjects.xxx')

        self.get_api_response_ext(404, url='/subjects/new')

        self.get_api_response_ext(200, url='/subjects/%s/members' % UUID1)

        self.get_api_response_ext(404, url='/subjects/%s/members.xxx' % UUID1)


class TestRegistryAPILocations(base.IsolatedUnitTest,
                               test_utils.RegistryAPIMixIn):
    def setUp(self):
        """Establish a clean test environment"""
        super(TestRegistryAPILocations, self).setUp()
        self.mapper = routes.Mapper()
        self.api = test_utils.FakeAuthMiddleware(rserver.API(self.mapper),
                                                 is_admin=True)

        def _get_extra_fixture(id, name, **kwargs):
            return self.get_extra_fixture(
                id, name,
                locations=[{'url': "file:///%s/%s" % (self.test_dir, id),
                            'metadata': {}, 'status': 'active'}], **kwargs)

        self.FIXTURES = [
            _get_extra_fixture(UUID1, 'fake subject #1', is_public=False,
                               disk_format='ami', container_format='ami',
                               min_disk=0, min_ram=0, owner=123,
                               size=13, properties={'type': 'kernel'}),
            _get_extra_fixture(UUID2, 'fake subject #2',
                               min_disk=5, min_ram=256,
                               size=19, properties={})]
        self.context = context.RequestContext(is_admin=True)
        db_api.get_engine()
        self.destroy_fixtures()
        self.create_fixtures()

    def tearDown(self):
        """Clear the test environment"""
        super(TestRegistryAPILocations, self).tearDown()
        self.destroy_fixtures()

    def test_show_from_locations(self):
        req = webob.Request.blank('/subjects/%s' % UUID1)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        res_dict = jsonutils.loads(res.body)
        subject = res_dict['subject']
        self.assertIn('id', subject['location_data'][0])
        subject['location_data'][0].pop('id')
        self.assertEqual(self.FIXTURES[0]['locations'][0],
                         subject['location_data'][0])
        self.assertEqual(self.FIXTURES[0]['locations'][0]['url'],
                         subject['location_data'][0]['url'])
        self.assertEqual(self.FIXTURES[0]['locations'][0]['metadata'],
                         subject['location_data'][0]['metadata'])

    def test_show_from_location_data(self):
        req = webob.Request.blank('/subjects/%s' % UUID2)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        res_dict = jsonutils.loads(res.body)
        subject = res_dict['subject']
        self.assertIn('id', subject['location_data'][0])
        subject['location_data'][0].pop('id')
        self.assertEqual(self.FIXTURES[1]['locations'][0],
                         subject['location_data'][0])
        self.assertEqual(self.FIXTURES[1]['locations'][0]['url'],
                         subject['location_data'][0]['url'])
        self.assertEqual(self.FIXTURES[1]['locations'][0]['metadata'],
                         subject['location_data'][0]['metadata'])

    def test_create_from_location_data_with_encryption(self):
        encryption_key = '1234567890123456'
        location_url1 = "file:///%s/%s" % (self.test_dir, _gen_uuid())
        location_url2 = "file:///%s/%s" % (self.test_dir, _gen_uuid())
        encrypted_location_url1 = crypt.urlsafe_encrypt(encryption_key,
                                                        location_url1, 64)
        encrypted_location_url2 = crypt.urlsafe_encrypt(encryption_key,
                                                        location_url2, 64)
        fixture = {'name': 'fake subject #3',
                   'status': 'active',
                   'disk_format': 'vhd',
                   'container_format': 'ovf',
                   'is_public': True,
                   'checksum': None,
                   'min_disk': 5,
                   'min_ram': 256,
                   'size': 19,
                   'location': encrypted_location_url1,
                   'location_data': [{'url': encrypted_location_url1,
                                      'metadata': {'key': 'value'},
                                      'status': 'active'},
                                     {'url': encrypted_location_url2,
                                      'metadata': {'key': 'value'},
                                      'status': 'active'}]}

        self.config(metadata_encryption_key=encryption_key)
        req = webob.Request.blank('/subjects')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(subject=fixture))

        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        res_dict = jsonutils.loads(res.body)
        subject = res_dict['subject']
        # NOTE(zhiyan) _normalize_subject_location_for_db() function will
        # not re-encrypted the url within location.
        self.assertEqual(fixture['location'], subject['location'])
        self.assertEqual(2, len(subject['location_data']))
        self.assertEqual(fixture['location_data'][0]['url'],
                         subject['location_data'][0]['url'])
        self.assertEqual(fixture['location_data'][0]['metadata'],
                         subject['location_data'][0]['metadata'])
        self.assertEqual(fixture['location_data'][1]['url'],
                         subject['location_data'][1]['url'])
        self.assertEqual(fixture['location_data'][1]['metadata'],
                         subject['location_data'][1]['metadata'])

        subject_entry = db_api.subject_get(self.context, subject['id'])
        self.assertEqual(encrypted_location_url1,
                         subject_entry['locations'][0]['url'])
        self.assertEqual(encrypted_location_url2,
                         subject_entry['locations'][1]['url'])
        decrypted_location_url1 = crypt.urlsafe_decrypt(
            encryption_key, subject_entry['locations'][0]['url'])
        decrypted_location_url2 = crypt.urlsafe_decrypt(
            encryption_key, subject_entry['locations'][1]['url'])
        self.assertEqual(location_url1, decrypted_location_url1)
        self.assertEqual(location_url2, decrypted_location_url2)


class TestSharability(test_utils.BaseTestCase):
    def setUp(self):
        super(TestSharability, self).setUp()
        self.setup_db()
        self.controller = subject.registry.api.v1.members.Controller()

    def setup_db(self):
        db_api.get_engine()
        db_models.unregister_models(db_api.get_engine())
        db_models.register_models(db_api.get_engine())

    def test_is_subject_sharable_as_admin(self):
        TENANT1 = str(uuid.uuid4())
        TENANT2 = str(uuid.uuid4())
        ctxt1 = context.RequestContext(is_admin=False, tenant=TENANT1,
                                       auth_token='user:%s:user' % TENANT1,
                                       owner_is_tenant=True)
        ctxt2 = context.RequestContext(is_admin=True, user=TENANT2,
                                       auth_token='user:%s:admin' % TENANT2,
                                       owner_is_tenant=False)
        UUIDX = str(uuid.uuid4())
        # We need private subject and context.owner should not match subject
        # owner
        subject = db_api.subject_create(ctxt1, {'id': UUIDX,
                                            'status': 'queued',
                                            'is_public': False,
                                            'owner': TENANT1})

        result = self.controller.is_subject_sharable(ctxt2, subject)
        self.assertTrue(result)

    def test_is_subject_sharable_owner_can_share(self):
        TENANT1 = str(uuid.uuid4())
        ctxt1 = context.RequestContext(is_admin=False, tenant=TENANT1,
                                       auth_token='user:%s:user' % TENANT1,
                                       owner_is_tenant=True)
        UUIDX = str(uuid.uuid4())
        # We need private subject and context.owner should not match subject
        # owner
        subject = db_api.subject_create(ctxt1, {'id': UUIDX,
                                            'status': 'queued',
                                            'is_public': False,
                                            'owner': TENANT1})

        result = self.controller.is_subject_sharable(ctxt1, subject)
        self.assertTrue(result)

    def test_is_subject_sharable_non_owner_cannot_share(self):
        TENANT1 = str(uuid.uuid4())
        TENANT2 = str(uuid.uuid4())
        ctxt1 = context.RequestContext(is_admin=False, tenant=TENANT1,
                                       auth_token='user:%s:user' % TENANT1,
                                       owner_is_tenant=True)
        ctxt2 = context.RequestContext(is_admin=False, user=TENANT2,
                                       auth_token='user:%s:user' % TENANT2,
                                       owner_is_tenant=False)
        UUIDX = str(uuid.uuid4())
        # We need private subject and context.owner should not match subject
        # owner
        subject = db_api.subject_create(ctxt1, {'id': UUIDX,
                                            'status': 'queued',
                                            'is_public': False,
                                            'owner': TENANT1})

        result = self.controller.is_subject_sharable(ctxt2, subject)
        self.assertFalse(result)

    def test_is_subject_sharable_non_owner_can_share_as_subject_member(self):
        TENANT1 = str(uuid.uuid4())
        TENANT2 = str(uuid.uuid4())
        ctxt1 = context.RequestContext(is_admin=False, tenant=TENANT1,
                                       auth_token='user:%s:user' % TENANT1,
                                       owner_is_tenant=True)
        ctxt2 = context.RequestContext(is_admin=False, user=TENANT2,
                                       auth_token='user:%s:user' % TENANT2,
                                       owner_is_tenant=False)
        UUIDX = str(uuid.uuid4())
        # We need private subject and context.owner should not match subject
        # owner
        subject = db_api.subject_create(ctxt1, {'id': UUIDX,
                                            'status': 'queued',
                                            'is_public': False,
                                            'owner': TENANT1})

        membership = {'can_share': True,
                      'member': TENANT2,
                      'subject_id': UUIDX}

        db_api.subject_member_create(ctxt1, membership)

        result = self.controller.is_subject_sharable(ctxt2, subject)
        self.assertTrue(result)

    def test_is_subject_sharable_non_owner_as_subject_member_without_sharing(self):
        TENANT1 = str(uuid.uuid4())
        TENANT2 = str(uuid.uuid4())
        ctxt1 = context.RequestContext(is_admin=False, tenant=TENANT1,
                                       auth_token='user:%s:user' % TENANT1,
                                       owner_is_tenant=True)
        ctxt2 = context.RequestContext(is_admin=False, user=TENANT2,
                                       auth_token='user:%s:user' % TENANT2,
                                       owner_is_tenant=False)
        UUIDX = str(uuid.uuid4())
        # We need private subject and context.owner should not match subject
        # owner
        subject = db_api.subject_create(ctxt1, {'id': UUIDX,
                                            'status': 'queued',
                                            'is_public': False,
                                            'owner': TENANT1})

        membership = {'can_share': False,
                      'member': TENANT2,
                      'subject_id': UUIDX}

        db_api.subject_member_create(ctxt1, membership)

        result = self.controller.is_subject_sharable(ctxt2, subject)
        self.assertFalse(result)

    def test_is_subject_sharable_owner_is_none(self):
        TENANT1 = str(uuid.uuid4())
        ctxt1 = context.RequestContext(is_admin=False, tenant=TENANT1,
                                       auth_token='user:%s:user' % TENANT1,
                                       owner_is_tenant=True)
        ctxt2 = context.RequestContext(is_admin=False, tenant=None,
                                       auth_token='user:%s:user' % TENANT1,
                                       owner_is_tenant=True)
        UUIDX = str(uuid.uuid4())
        # We need private subject and context.owner should not match subject
        # owner
        subject = db_api.subject_create(ctxt1, {'id': UUIDX,
                                            'status': 'queued',
                                            'is_public': False,
                                            'owner': TENANT1})

        result = self.controller.is_subject_sharable(ctxt2, subject)
        self.assertFalse(result)
