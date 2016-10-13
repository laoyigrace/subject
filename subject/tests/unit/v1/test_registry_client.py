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

import copy
import datetime
import os
import uuid

from mock import patch
from six.moves import reload_module
import testtools

from subject.api.v1.subjects import Controller as acontroller
from subject.common import client as test_client
from subject.common import config
from subject.common import exception
from subject.common import timeutils
from subject import context
from subject.db.sqlalchemy import api as db_api
from subject.registry.api.v1.subjects import Controller as rcontroller
import subject.registry.client.v1.api as rapi
from subject.registry.client.v1.api import client as rclient
from subject.tests.unit import base
from subject.tests import utils as test_utils
import webob

_gen_uuid = lambda: str(uuid.uuid4())

UUID1 = _gen_uuid()
UUID2 = _gen_uuid()

# NOTE(bcwaldon): needed to init config_dir cli opt
config.parse_args(args=[])


class TestRegistryV1Client(base.IsolatedUnitTest, test_utils.RegistryAPIMixIn):

    """
    Test proper actions made for both valid and invalid requests
    against a Registry service
    """

    def setUp(self):
        """Establish a clean test environment"""
        super(TestRegistryV1Client, self).setUp()
        db_api.get_engine()
        self.context = context.RequestContext(is_admin=True)

        self.FIXTURES = [
            self.get_fixture(
                id=UUID1, name='fake subject #1', is_public=False,
                disk_format='ami', container_format='ami', size=13,
                location="swift://user:passwd@acct/container/obj.tar.0",
                properties={'type': 'kernel'}),
            self.get_fixture(id=UUID2, name='fake subject #2', properties={},
                             size=19, location="file:///tmp/subject-tests/2")]
        self.destroy_fixtures()
        self.create_fixtures()
        self.client = rclient.RegistryClient("0.0.0.0")

    def tearDown(self):
        """Clear the test environment"""
        super(TestRegistryV1Client, self).tearDown()
        self.destroy_fixtures()

    def test_get_subject_index(self):
        """Test correct set of public subject returned"""
        fixture = {
            'id': UUID2,
            'name': 'fake subject #2'
        }
        subjects = self.client.get_subjects()
        self.assertEqualSubjects(subjects, (UUID2,), unjsonify=False)

        for k, v in fixture.items():
            self.assertEqual(v, subjects[0][k])

    def test_create_subject_with_null_min_disk_min_ram(self):
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, min_disk=None, min_ram=None)
        db_api.subject_create(self.context, extra_fixture)
        subject = self.client.get_subject(UUID3)
        self.assertEqual(0, subject["min_ram"])
        self.assertEqual(0, subject["min_disk"])

    def test_get_index_sort_name_asc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted alphabetically by name in
        ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, name='asdf')

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, name='xyz')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(sort_key='name', sort_dir='asc')

        self.assertEqualSubjects(subjects, (UUID3, UUID2, UUID4), unjsonify=False)

    def test_get_index_sort_status_desc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted alphabetically by status in
        descending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, name='asdf',
                                         status='queued')

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, name='xyz')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(sort_key='status', sort_dir='desc')

        self.assertEqualSubjects(subjects, (UUID3, UUID4, UUID2), unjsonify=False)

    def test_get_index_sort_disk_format_asc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted alphabetically by disk_format in
        ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, name='asdf',
                                         disk_format='ami',
                                         container_format='ami')

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, name='xyz',
                                         disk_format='vdi')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(sort_key='disk_format',
                                        sort_dir='asc')

        self.assertEqualSubjects(subjects, (UUID3, UUID4, UUID2), unjsonify=False)

    def test_get_index_sort_container_format_desc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted alphabetically by container_format in
        descending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, name='asdf',
                                         disk_format='ami',
                                         container_format='ami')

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, name='xyz',
                                         disk_format='iso',
                                         container_format='bare')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(sort_key='container_format',
                                        sort_dir='desc')

        self.assertEqualSubjects(subjects, (UUID2, UUID4, UUID3), unjsonify=False)

    def test_get_index_sort_size_asc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted by size in ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, name='asdf',
                                         disk_format='ami',
                                         container_format='ami', size=100)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, name='asdf',
                                         disk_format='iso',
                                         container_format='bare', size=2)

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(sort_key='size', sort_dir='asc')

        self.assertEqualSubjects(subjects, (UUID4, UUID2, UUID3), unjsonify=False)

    def test_get_index_sort_created_at_asc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted by created_at in ascending order.
        """
        now = timeutils.utcnow()
        time1 = now + datetime.timedelta(seconds=5)
        time2 = now

        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, created_at=time1)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, created_at=time2)

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(sort_key='created_at', sort_dir='asc')

        self.assertEqualSubjects(subjects, (UUID2, UUID4, UUID3), unjsonify=False)

    def test_get_index_sort_updated_at_desc(self):
        """
        Tests that the /subjects registry API returns list of
        public subjects sorted by updated_at in descending order.
        """
        now = timeutils.utcnow()
        time1 = now + datetime.timedelta(seconds=5)
        time2 = now

        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, created_at=None,
                                         updated_at=time1)

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, created_at=None,
                                         updated_at=time2)

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(sort_key='updated_at', sort_dir='desc')

        self.assertEqualSubjects(subjects, (UUID3, UUID4, UUID2), unjsonify=False)

    def test_get_subject_index_marker(self):
        """Test correct set of subjects returned with marker param."""
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, name='new name! #123',
                                         status='saving')

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, name='new name! #125',
                                         status='saving')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(marker=UUID4)

        self.assertEqualSubjects(subjects, (UUID3, UUID2), unjsonify=False)

    def test_get_subject_index_invalid_marker(self):
        """Test exception is raised when marker is invalid"""
        self.assertRaises(exception.Invalid,
                          self.client.get_subjects,
                          marker=_gen_uuid())

    def test_get_subject_index_forbidden_marker(self):
        """Test exception is raised when marker is forbidden"""
        UUID5 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID5, owner='0123',
                                         status='saving', is_public=False)

        db_api.subject_create(self.context, extra_fixture)

        def non_admin_get_subjects(self, context, *args, **kwargs):
            """Convert to non-admin context"""
            context.is_admin = False
            rcontroller.__get_subjects(self, context, *args, **kwargs)

        rcontroller.__get_subjects = rcontroller._get_subjects
        self.stubs.Set(rcontroller, '_get_subjects', non_admin_get_subjects)
        self.assertRaises(exception.Invalid,
                          self.client.get_subjects,
                          marker=UUID5)

    def test_get_subject_index_private_marker(self):
        """Test exception is not raised if private non-owned marker is used"""
        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, owner='1234',
                                         status='saving', is_public=False)

        db_api.subject_create(self.context, extra_fixture)

        try:
            self.client.get_subjects(marker=UUID4)
        except Exception as e:
            self.fail("Unexpected exception '%s'" % e)

    def test_get_subject_index_limit(self):
        """Test correct number of subjects returned with limit param."""
        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving')

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(limit=2)
        self.assertEqual(2, len(subjects))

    def test_get_subject_index_marker_limit(self):
        """Test correct set of subjects returned with marker/limit params."""
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, name='new name! #123',
                                         status='saving')

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, name='new name! #125',
                                         status='saving')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(marker=UUID3, limit=1)

        self.assertEqualSubjects(subjects, (UUID2,), unjsonify=False)

    def test_get_subject_index_limit_None(self):
        """Test correct set of subjects returned with limit param == None."""
        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving')

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(limit=None)
        self.assertEqual(3, len(subjects))

    def test_get_subject_index_by_name(self):
        """
        Test correct set of public, name-filtered subject returned. This
        is just a sanity check, we test the details call more in-depth.
        """
        extra_fixture = self.get_fixture(id=_gen_uuid(), name='new name! #123')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects(filters={'name': 'new name! #123'})
        self.assertEqual(1, len(subjects))

        for subject in subjects:
            self.assertEqual('new name! #123', subject['name'])

    def test_get_subject_details(self):
        """Tests that the detailed info about public subjects returned"""
        fixture = self.get_fixture(id=UUID2, name='fake subject #2',
                                   properties={}, size=19)

        subjects = self.client.get_subjects_detailed()

        self.assertEqual(1, len(subjects))
        for k, v in fixture.items():
            self.assertEqual(v, subjects[0][k])

    def test_get_subject_details_marker_limit(self):
        """Test correct set of subjects returned with marker/limit params."""
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, status='saving')

        db_api.subject_create(self.context, extra_fixture)

        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects_detailed(marker=UUID3, limit=1)

        self.assertEqualSubjects(subjects, (UUID2,), unjsonify=False)

    def test_get_subject_details_invalid_marker(self):
        """Test exception is raised when marker is invalid"""
        self.assertRaises(exception.Invalid,
                          self.client.get_subjects_detailed,
                          marker=_gen_uuid())

    def test_get_subject_details_forbidden_marker(self):
        """Test exception is raised when marker is forbidden"""
        UUID5 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID5, is_public=False,
                                         owner='0123', status='saving')

        db_api.subject_create(self.context, extra_fixture)

        def non_admin_get_subjects(self, context, *args, **kwargs):
            """Convert to non-admin context"""
            context.is_admin = False
            rcontroller.__get_subjects(self, context, *args, **kwargs)

        rcontroller.__get_subjects = rcontroller._get_subjects
        self.stubs.Set(rcontroller, '_get_subjects', non_admin_get_subjects)
        self.assertRaises(exception.Invalid,
                          self.client.get_subjects_detailed,
                          marker=UUID5)

    def test_get_subject_details_private_marker(self):
        """Test exception is not raised if private non-owned marker is used"""
        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, is_public=False,
                                         owner='1234', status='saving')

        db_api.subject_create(self.context, extra_fixture)

        try:
            self.client.get_subjects_detailed(marker=UUID4)
        except Exception as e:
            self.fail("Unexpected exception '%s'" % e)

    def test_get_subject_details_by_name(self):
        """Tests that a detailed call can be filtered by name"""
        extra_fixture = self.get_fixture(id=_gen_uuid(), name='new name! #123')

        db_api.subject_create(self.context, extra_fixture)

        filters = {'name': 'new name! #123'}
        subjects = self.client.get_subjects_detailed(filters=filters)

        self.assertEqual(1, len(subjects))
        for subject in subjects:
            self.assertEqual('new name! #123', subject['name'])

    def test_get_subject_details_by_status(self):
        """Tests that a detailed call can be filtered by status"""
        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects_detailed(filters={'status': 'saving'})

        self.assertEqual(1, len(subjects))
        for subject in subjects:
            self.assertEqual('saving', subject['status'])

    def test_get_subject_details_by_container_format(self):
        """Tests that a detailed call can be filtered by container_format"""
        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving')

        db_api.subject_create(self.context, extra_fixture)

        filters = {'container_format': 'ovf'}
        subjects = self.client.get_subjects_detailed(filters=filters)

        self.assertEqual(2, len(subjects))
        for subject in subjects:
            self.assertEqual('ovf', subject['container_format'])

    def test_get_subject_details_by_disk_format(self):
        """Tests that a detailed call can be filtered by disk_format"""
        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving')

        db_api.subject_create(self.context, extra_fixture)

        filters = {'disk_format': 'vhd'}
        subjects = self.client.get_subjects_detailed(filters=filters)

        self.assertEqual(2, len(subjects))
        for subject in subjects:
            self.assertEqual('vhd', subject['disk_format'])

    def test_get_subject_details_with_maximum_size(self):
        """Tests that a detailed call can be filtered by size_max"""
        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving',
                                         size=21)

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects_detailed(filters={'size_max': 20})

        self.assertEqual(1, len(subjects))
        for subject in subjects:
            self.assertLessEqual(subject['size'], 20)

    def test_get_subject_details_with_minimum_size(self):
        """Tests that a detailed call can be filtered by size_min"""
        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects_detailed(filters={'size_min': 20})

        self.assertEqual(1, len(subjects))
        for subject in subjects:
            self.assertGreaterEqual(subject['size'], 20)

    def test_get_subject_details_with_changes_since(self):
        """Tests that a detailed call can be filtered by changes-since"""
        dt1 = timeutils.utcnow() - datetime.timedelta(1)
        iso1 = timeutils.isotime(dt1)

        dt2 = timeutils.utcnow() + datetime.timedelta(1)
        iso2 = timeutils.isotime(dt2)

        dt3 = timeutils.utcnow() + datetime.timedelta(2)

        dt4 = timeutils.utcnow() + datetime.timedelta(3)
        iso4 = timeutils.isotime(dt4)

        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, name='fake subject #3')

        db_api.subject_create(self.context, extra_fixture)
        db_api.subject_destroy(self.context, UUID3)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, name='fake subject #4',
                                         created_at=dt3, updated_at=dt3)

        db_api.subject_create(self.context, extra_fixture)

        # Check a standard list, 4 subjects in db (2 deleted)
        subjects = self.client.get_subjects_detailed(filters={})
        self.assertEqualSubjects(subjects, (UUID4, UUID2), unjsonify=False)

        # Expect 3 subjects (1 deleted)
        filters = {'changes-since': iso1}
        subjects = self.client.get_subjects(filters=filters)
        self.assertEqualSubjects(subjects, (UUID4, UUID3, UUID2), unjsonify=False)

        # Expect 1 subjects (0 deleted)
        filters = {'changes-since': iso2}
        subjects = self.client.get_subjects_detailed(filters=filters)
        self.assertEqualSubjects(subjects, (UUID4,), unjsonify=False)

        # Expect 0 subjects (0 deleted)
        filters = {'changes-since': iso4}
        subjects = self.client.get_subjects(filters=filters)
        self.assertEqualSubjects(subjects, (), unjsonify=False)

    def test_get_subject_details_with_size_min(self):
        """Tests that a detailed call can be filtered by size_min"""
        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects_detailed(filters={'size_min': 20})
        self.assertEqual(1, len(subjects))

        for subject in subjects:
            self.assertGreaterEqual(subject['size'], 20)

    def test_get_subject_details_by_property(self):
        """Tests that a detailed call can be filtered by a property"""
        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving',
                                         properties={'p a': 'v a'})

        db_api.subject_create(self.context, extra_fixture)

        filters = {'property-p a': 'v a'}
        subjects = self.client.get_subjects_detailed(filters=filters)
        self.assertEqual(1, len(subjects))

        for subject in subjects:
            self.assertEqual('v a', subject['properties']['p a'])

    def test_get_subject_is_public_v1(self):
        """Tests that a detailed call can be filtered by a property"""
        extra_fixture = self.get_fixture(id=_gen_uuid(), status='saving',
                                         properties={'is_public': 'avalue'})

        context = copy.copy(self.context)
        db_api.subject_create(context, extra_fixture)

        filters = {'property-is_public': 'avalue'}
        subjects = self.client.get_subjects_detailed(filters=filters)
        self.assertEqual(1, len(subjects))

        for subject in subjects:
            self.assertEqual('avalue', subject['properties']['is_public'])

    def test_get_subject_details_sort_disk_format_asc(self):
        """
        Tests that a detailed call returns list of
        public subjects sorted alphabetically by disk_format in
        ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID3, name='asdf',
                                         disk_format='ami',
                                         container_format='ami')

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = self.get_fixture(id=UUID4, name='xyz',
                                         disk_format='vdi')

        db_api.subject_create(self.context, extra_fixture)

        subjects = self.client.get_subjects_detailed(sort_key='disk_format',
                                                 sort_dir='asc')

        self.assertEqualSubjects(subjects, (UUID3, UUID4, UUID2), unjsonify=False)

    def test_get_subject(self):
        """Tests that the detailed info about an subject returned"""
        fixture = self.get_fixture(id=UUID1, name='fake subject #1',
                                   disk_format='ami', container_format='ami',
                                   is_public=False, size=13,
                                   properties={'type': 'kernel'})

        data = self.client.get_subject(UUID1)

        for k, v in fixture.items():
            el = data[k]
            self.assertEqual(v, data[k],
                             "Failed v != data[k] where v = %(v)s and "
                             "k = %(k)s and data[k] = %(el)s" % {'v': v,
                                                                 'k': k,
                                                                 'el': el})

    def test_get_subject_non_existing(self):
        """Tests that NotFound is raised when getting a non-existing subject"""
        self.assertRaises(exception.NotFound,
                          self.client.get_subject,
                          _gen_uuid())

    def test_add_subject_basic(self):
        """Tests that we can add subject metadata and returns the new id"""
        fixture = self.get_fixture()

        new_subject = self.client.add_subject(fixture)

        # Test all other attributes set
        data = self.client.get_subject(new_subject['id'])

        for k, v in fixture.items():
            self.assertEqual(v, data[k])

        # Test status was updated properly
        self.assertIn('status', data.keys())
        self.assertEqual('active', data['status'])

    def test_add_subject_with_properties(self):
        """Tests that we can add subject metadata with properties"""
        fixture = self.get_fixture(location="file:///tmp/subject-tests/2",
                                   properties={'distro': 'Ubuntu 10.04 LTS'})

        new_subject = self.client.add_subject(fixture)

        del fixture['location']
        for k, v in fixture.items():
            self.assertEqual(v, new_subject[k])

        # Test status was updated properly
        self.assertIn('status', new_subject.keys())
        self.assertEqual('active', new_subject['status'])

    def test_add_subject_with_location_data(self):
        """Tests that we can add subject metadata with properties"""
        location = "file:///tmp/subject-tests/2"
        loc_meta = {'key': 'value'}
        fixture = self.get_fixture(location_data=[{'url': location,
                                                   'metadata': loc_meta,
                                                   'status': 'active'}],
                                   properties={'distro': 'Ubuntu 10.04 LTS'})

        new_subject = self.client.add_subject(fixture)

        self.assertEqual(location, new_subject['location'])
        self.assertEqual(location, new_subject['location_data'][0]['url'])
        self.assertEqual(loc_meta, new_subject['location_data'][0]['metadata'])

    def test_add_subject_with_location_data_with_encryption(self):
        """Tests that we can add subject metadata with properties and
        enable encryption.
        """
        self.client.metadata_encryption_key = '1234567890123456'

        location = "file:///tmp/subject-tests/%d"
        loc_meta = {'key': 'value'}
        fixture = {'name': 'fake public subject',
                   'is_public': True,
                   'disk_format': 'vmdk',
                   'container_format': 'ovf',
                   'size': 19,
                   'location_data': [{'url': location % 1,
                                      'metadata': loc_meta,
                                      'status': 'active'},
                                     {'url': location % 2,
                                      'metadata': {},
                                      'status': 'active'}],
                   'properties': {'distro': 'Ubuntu 10.04 LTS'}}

        new_subject = self.client.add_subject(fixture)

        self.assertEqual(location % 1, new_subject['location'])
        self.assertEqual(2, len(new_subject['location_data']))
        self.assertEqual(location % 1, new_subject['location_data'][0]['url'])
        self.assertEqual(loc_meta, new_subject['location_data'][0]['metadata'])
        self.assertEqual(location % 2, new_subject['location_data'][1]['url'])
        self.assertEqual({}, new_subject['location_data'][1]['metadata'])

        self.client.metadata_encryption_key = None

    def test_add_subject_already_exists(self):
        """Tests proper exception is raised if subject with ID already exists"""
        fixture = self.get_fixture(id=UUID2,
                                   location="file:///tmp/subject-tests/2")

        self.assertRaises(exception.Duplicate,
                          self.client.add_subject,
                          fixture)

    def test_add_subject_with_bad_status(self):
        """Tests proper exception is raised if a bad status is set"""
        fixture = self.get_fixture(status='bad status',
                                   location="file:///tmp/subject-tests/2")

        self.assertRaises(exception.Invalid,
                          self.client.add_subject,
                          fixture)

    def test_update_subject(self):
        """Tests that the /subjects PUT registry API updates the subject"""
        fixture = {'name': 'fake public subject #2',
                   'disk_format': 'vmdk'}

        self.assertTrue(self.client.update_subject(UUID2, fixture))

        # Test all other attributes set
        data = self.client.get_subject(UUID2)

        for k, v in fixture.items():
            self.assertEqual(v, data[k])

    def test_update_subject_not_existing(self):
        """Tests non existing subject update doesn't work"""
        fixture = self.get_fixture(status='bad status')

        self.assertRaises(exception.NotFound,
                          self.client.update_subject,
                          _gen_uuid(),
                          fixture)

    def test_delete_subject(self):
        """Tests that subject metadata is deleted properly"""
        # Grab the original number of subjects
        orig_num_subjects = len(self.client.get_subjects())

        # Delete subject #2
        subject = self.FIXTURES[1]
        deleted_subject = self.client.delete_subject(subject['id'])
        self.assertTrue(deleted_subject)
        self.assertEqual(subject['id'], deleted_subject['id'])
        self.assertTrue(deleted_subject['deleted'])
        self.assertTrue(deleted_subject['deleted_at'])

        # Verify one less subject
        new_num_subjects = len(self.client.get_subjects())

        self.assertEqual(orig_num_subjects - 1, new_num_subjects)

    def test_delete_subject_not_existing(self):
        """Check that one cannot delete non-existing subject."""
        self.assertRaises(exception.NotFound,
                          self.client.delete_subject,
                          _gen_uuid())

    def test_get_subject_members(self):
        """Test getting subject members."""
        memb_list = self.client.get_subject_members(UUID2)
        num_members = len(memb_list)
        self.assertEqual(0, num_members)

    def test_get_subject_members_not_existing(self):
        """Test getting non-existent subject members."""
        self.assertRaises(exception.NotFound,
                          self.client.get_subject_members,
                          _gen_uuid())

    def test_get_member_subjects(self):
        """Test getting member subjects."""
        memb_list = self.client.get_member_subjects('pattieblack')
        num_members = len(memb_list)
        self.assertEqual(0, num_members)

    def test_add_replace_members(self):
        """Test replacing subject members."""
        self.assertTrue(self.client.add_member(UUID2, 'pattieblack'))
        self.assertTrue(self.client.replace_members(UUID2,
                                                    dict(member_id='pattie'
                                                                   'black2')))

    def test_add_delete_member(self):
        """Tests deleting subject members"""
        self.client.add_member(UUID2, 'pattieblack')
        self.assertTrue(self.client.delete_member(UUID2, 'pattieblack'))


class TestBaseClient(testtools.TestCase):

    """
    Test proper actions made for both valid and invalid requests
    against a Registry service
    """
    def test_connect_kwargs_default_values(self):
        actual = test_client.BaseClient('127.0.0.1').get_connect_kwargs()
        self.assertEqual({'timeout': None}, actual)

    def test_connect_kwargs(self):
        base_client = test_client.BaseClient(
            host='127.0.0.1', port=80, timeout=1, use_ssl=True)
        actual = base_client.get_connect_kwargs()
        expected = {'insecure': False,
                    'key_file': None,
                    'cert_file': None,
                    'timeout': 1}
        for k in expected.keys():
            self.assertEqual(expected[k], actual[k])


class TestRegistryV1ClientApi(base.IsolatedUnitTest):

    def setUp(self):
        """Establish a clean test environment."""
        super(TestRegistryV1ClientApi, self).setUp()
        self.context = context.RequestContext()
        reload_module(rapi)

    def tearDown(self):
        """Clear the test environment."""
        super(TestRegistryV1ClientApi, self).tearDown()

    def test_get_registry_client(self):
        actual_client = rapi.get_registry_client(self.context)
        self.assertIsNone(actual_client.identity_headers)

    def test_get_registry_client_with_identity_headers(self):
        self.config(send_identity_headers=True)
        expected_identity_headers = {
            'X-User-Id': '',
            'X-Tenant-Id': '',
            'X-Roles': ','.join(self.context.roles),
            'X-Identity-Status': 'Confirmed',
            'X-Service-Catalog': 'null',
        }
        actual_client = rapi.get_registry_client(self.context)
        self.assertEqual(expected_identity_headers,
                         actual_client.identity_headers)

    def test_configure_registry_client_not_using_use_user_token(self):
        self.config(use_user_token=False)
        with patch.object(rapi, 'configure_registry_admin_creds') as mock_rapi:
            rapi.configure_registry_client()
            mock_rapi.assert_called_once_with()

    def _get_fake_config_creds(self, auth_url='auth_url', strategy='keystone'):
        return {
            'user': 'user',
            'password': 'password',
            'username': 'user',
            'tenant': 'tenant',
            'auth_url': auth_url,
            'strategy': strategy,
            'region': 'region'
        }

    def test_configure_registry_admin_creds(self):
        expected = self._get_fake_config_creds(auth_url=None,
                                               strategy='configured_strategy')
        self.config(admin_user=expected['user'])
        self.config(admin_password=expected['password'])
        self.config(admin_tenant_name=expected['tenant'])
        self.config(auth_strategy=expected['strategy'])
        self.config(auth_region=expected['region'])
        self.stubs.Set(os, 'getenv', lambda x: None)

        self.assertIsNone(rapi._CLIENT_CREDS)
        rapi.configure_registry_admin_creds()
        self.assertEqual(expected, rapi._CLIENT_CREDS)

    def test_configure_registry_admin_creds_with_auth_url(self):
        expected = self._get_fake_config_creds()
        self.config(admin_user=expected['user'])
        self.config(admin_password=expected['password'])
        self.config(admin_tenant_name=expected['tenant'])
        self.config(auth_url=expected['auth_url'])
        self.config(auth_strategy='test_strategy')
        self.config(auth_region=expected['region'])

        self.assertIsNone(rapi._CLIENT_CREDS)
        rapi.configure_registry_admin_creds()
        self.assertEqual(expected, rapi._CLIENT_CREDS)


class FakeResponse(object):
    status = 202

    def getheader(*args, **kwargs):
        return None


class TestRegistryV1ClientRequests(base.IsolatedUnitTest):

    def setUp(self):
        super(TestRegistryV1ClientRequests, self).setUp()

    def tearDown(self):
        super(TestRegistryV1ClientRequests, self).tearDown()

    def test_do_request_with_identity_headers(self):
        identity_headers = {'foo': 'bar'}
        self.client = rclient.RegistryClient("0.0.0.0",
                                             identity_headers=identity_headers)

        with patch.object(test_client.BaseClient, 'do_request',
                          return_value=FakeResponse()) as mock_do_request:
            self.client.do_request("GET", "/subjects")
            mock_do_request.assert_called_once_with("GET", "/subjects",
                                                    headers=identity_headers)

    def test_do_request(self):
        self.client = rclient.RegistryClient("0.0.0.0")

        with patch.object(test_client.BaseClient, 'do_request',
                          return_value=FakeResponse()) as mock_do_request:
            self.client.do_request("GET", "/subjects")
            mock_do_request.assert_called_once_with("GET", "/subjects",
                                                    headers={})

    def test_registry_invalid_token_exception_handling(self):
        self.subject_controller = acontroller()
        request = webob.Request.blank('/subjects')
        request.method = 'GET'
        request.context = context.RequestContext()

        with patch.object(rapi, 'get_subjects_detail') as mock_detail:
            mock_detail.side_effect = exception.NotAuthenticated()
            self.assertRaises(webob.exc.HTTPUnauthorized,
                              self.subject_controller.detail, request)
