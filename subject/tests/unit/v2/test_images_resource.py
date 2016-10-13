# Copyright 2012 OpenStack Foundation.
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

import glance_store as store
import mock
from oslo_config import cfg
from oslo_serialization import jsonutils
import six
# NOTE(jokke): simplified transition to py3, behaves like py2 xrange
from six.moves import range
import testtools
import webob

import subject.api.v2.subject_actions
import subject.api.v2.subjects
from subject.common import exception
from subject import domain
import subject.schema
from subject.tests.unit import base
import subject.tests.unit.utils as unit_test_utils
import subject.tests.utils as test_utils

DATETIME = datetime.datetime(2012, 5, 16, 15, 27, 36, 325355)
ISOTIME = '2012-05-16T15:27:36Z'


CONF = cfg.CONF

BASE_URI = unit_test_utils.BASE_URI


UUID1 = 'c80a1a6c-bd1f-41c5-90ee-81afedb1d58d'
UUID2 = 'a85abd86-55b3-4d5b-b0b4-5d0a6e6042fc'
UUID3 = '971ec09a-8067-4bc8-a91f-ae3557f1c4c7'
UUID4 = '6bbe7cc2-eae7-4c0f-b50d-a7160b0c6a86'

TENANT1 = '6838eb7b-6ded-434a-882c-b344c77fe8df'
TENANT2 = '2c014f32-55eb-467d-8fcb-4bd706012f81'
TENANT3 = '5a3e60e8-cfa9-4a9e-a90a-62b42cea92b8'
TENANT4 = 'c6c87f25-8a94-47ed-8c83-053c25f42df4'

CHKSUM = '93264c3edf5972c9f1cb309543d38a5c'
CHKSUM1 = '43254c3edf6972c9f1cb309543d38a8c'


def _db_fixture(id, **kwargs):
    obj = {
        'id': id,
        'name': None,
        'is_public': False,
        'properties': {},
        'checksum': None,
        'owner': None,
        'status': 'queued',
        'tags': [],
        'size': None,
        'virtual_size': None,
        'locations': [],
        'protected': False,
        'disk_format': None,
        'container_format': None,
        'deleted': False,
        'min_ram': None,
        'min_disk': None,
    }
    obj.update(kwargs)
    return obj


def _domain_fixture(id, **kwargs):
    properties = {
        'subject_id': id,
        'name': None,
        'visibility': 'private',
        'checksum': None,
        'owner': None,
        'status': 'queued',
        'size': None,
        'virtual_size': None,
        'locations': [],
        'protected': False,
        'disk_format': None,
        'container_format': None,
        'min_ram': None,
        'min_disk': None,
        'tags': [],
    }
    properties.update(kwargs)
    return subject.domain.Subject(**properties)


def _db_subject_member_fixture(subject_id, member_id, **kwargs):
    obj = {
        'subject_id': subject_id,
        'member': member_id,
    }
    obj.update(kwargs)
    return obj


class TestSubjectsController(base.IsolatedUnitTest):

    def setUp(self):
        super(TestSubjectsController, self).setUp()
        self.db = unit_test_utils.FakeDB(initialize=False)
        self.policy = unit_test_utils.FakePolicyEnforcer()
        self.notifier = unit_test_utils.FakeNotifier()
        self.store = unit_test_utils.FakeStoreAPI()
        for i in range(1, 4):
            self.store.data['%s/fake_location_%i' % (BASE_URI, i)] = ('Z', 1)
        self.store_utils = unit_test_utils.FakeStoreUtils(self.store)
        self._create_subjects()
        self._create_subject_members()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   self.policy,
                                                                   self.notifier,
                                                                   self.store)
        self.action_controller = (subject.api.v2.subject_actions.
                                  SubjectActionsController(self.db,
                                                         self.policy,
                                                         self.notifier,
                                                         self.store))
        self.controller.gateway.store_utils = self.store_utils
        store.create_stores()

    def _create_subjects(self):
        self.subjects = [
            _db_fixture(UUID1, owner=TENANT1, checksum=CHKSUM,
                        name='1', size=256, virtual_size=1024,
                        is_public=True,
                        locations=[{'url': '%s/%s' % (BASE_URI, UUID1),
                                    'metadata': {}, 'status': 'active'}],
                        disk_format='raw',
                        container_format='bare',
                        status='active'),
            _db_fixture(UUID2, owner=TENANT1, checksum=CHKSUM1,
                        name='2', size=512, virtual_size=2048,
                        is_public=True,
                        disk_format='raw',
                        container_format='bare',
                        status='active',
                        tags=['redhat', '64bit', 'power'],
                        properties={'hypervisor_type': 'kvm', 'foo': 'bar',
                                    'bar': 'foo'}),
            _db_fixture(UUID3, owner=TENANT3, checksum=CHKSUM1,
                        name='3', size=512, virtual_size=2048,
                        is_public=True, tags=['windows', '64bit', 'x86']),
            _db_fixture(UUID4, owner=TENANT4, name='4',
                        size=1024, virtual_size=3072),
        ]
        [self.db.subject_create(None, subject) for subject in self.subjects]

        self.db.subject_tag_set_all(None, UUID1, ['ping', 'pong'])

    def _create_subject_members(self):
        self.subject_members = [
            _db_subject_member_fixture(UUID4, TENANT2),
            _db_subject_member_fixture(UUID4, TENANT3,
                                     status='accepted'),
        ]
        [self.db.subject_member_create(None, subject_member)
            for subject_member in self.subject_members]

    def test_index(self):
        self.config(limit_param_default=1, api_limit_max=3)
        request = unit_test_utils.get_fake_request()
        output = self.controller.index(request)
        self.assertEqual(1, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID3])
        self.assertEqual(expected, actual)

    def test_index_member_status_accepted(self):
        self.config(limit_param_default=5, api_limit_max=5)
        request = unit_test_utils.get_fake_request(tenant=TENANT2)
        output = self.controller.index(request)
        self.assertEqual(3, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID1, UUID2, UUID3])
        # can see only the public subject
        self.assertEqual(expected, actual)

        request = unit_test_utils.get_fake_request(tenant=TENANT3)
        output = self.controller.index(request)
        self.assertEqual(4, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID1, UUID2, UUID3, UUID4])
        self.assertEqual(expected, actual)

    def test_index_admin(self):
        request = unit_test_utils.get_fake_request(is_admin=True)
        output = self.controller.index(request)
        self.assertEqual(4, len(output['subjects']))

    def test_index_admin_deleted_subjects_hidden(self):
        request = unit_test_utils.get_fake_request(is_admin=True)
        self.controller.delete(request, UUID1)
        output = self.controller.index(request)
        self.assertEqual(3, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID2, UUID3, UUID4])
        self.assertEqual(expected, actual)

    def test_index_return_parameters(self):
        self.config(limit_param_default=1, api_limit_max=3)
        request = unit_test_utils.get_fake_request()
        output = self.controller.index(request, marker=UUID3, limit=1,
                                       sort_key=['created_at'],
                                       sort_dir=['desc'])
        self.assertEqual(1, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID2])
        self.assertEqual(actual, expected)
        self.assertEqual(UUID2, output['next_marker'])

    def test_index_next_marker(self):
        self.config(limit_param_default=1, api_limit_max=3)
        request = unit_test_utils.get_fake_request()
        output = self.controller.index(request, marker=UUID3, limit=2)
        self.assertEqual(2, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID2, UUID1])
        self.assertEqual(expected, actual)
        self.assertEqual(UUID1, output['next_marker'])

    def test_index_no_next_marker(self):
        self.config(limit_param_default=1, api_limit_max=3)
        request = unit_test_utils.get_fake_request()
        output = self.controller.index(request, marker=UUID1, limit=2)
        self.assertEqual(0, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([])
        self.assertEqual(expected, actual)
        self.assertNotIn('next_marker', output)

    def test_index_with_id_filter(self):
        request = unit_test_utils.get_fake_request('/subjects?id=%s' % UUID1)
        output = self.controller.index(request, filters={'id': UUID1})
        self.assertEqual(1, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID1])
        self.assertEqual(expected, actual)

    def test_index_with_checksum_filter_single_subject(self):
        req = unit_test_utils.get_fake_request('/subjects?checksum=%s' % CHKSUM)
        output = self.controller.index(req, filters={'checksum': CHKSUM})
        self.assertEqual(1, len(output['subjects']))
        actual = list([subject.subject_id for subject in output['subjects']])
        expected = [UUID1]
        self.assertEqual(expected, actual)

    def test_index_with_checksum_filter_multiple_subjects(self):
        req = unit_test_utils.get_fake_request('/subjects?checksum=%s' % CHKSUM1)
        output = self.controller.index(req, filters={'checksum': CHKSUM1})
        self.assertEqual(2, len(output['subjects']))
        actual = list([subject.subject_id for subject in output['subjects']])
        expected = [UUID3, UUID2]
        self.assertEqual(expected, actual)

    def test_index_with_non_existent_checksum(self):
        req = unit_test_utils.get_fake_request('/subjects?checksum=236231827')
        output = self.controller.index(req, filters={'checksum': '236231827'})
        self.assertEqual(0, len(output['subjects']))

    def test_index_size_max_filter(self):
        request = unit_test_utils.get_fake_request('/subjects?size_max=512')
        output = self.controller.index(request, filters={'size_max': 512})
        self.assertEqual(3, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID1, UUID2, UUID3])
        self.assertEqual(expected, actual)

    def test_index_size_min_filter(self):
        request = unit_test_utils.get_fake_request('/subjects?size_min=512')
        output = self.controller.index(request, filters={'size_min': 512})
        self.assertEqual(2, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID2, UUID3])
        self.assertEqual(expected, actual)

    def test_index_size_range_filter(self):
        path = '/subjects?size_min=512&size_max=512'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request,
                                       filters={'size_min': 512,
                                                'size_max': 512})
        self.assertEqual(2, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID2, UUID3])
        self.assertEqual(expected, actual)

    def test_index_virtual_size_max_filter(self):
        ref = '/subjects?virtual_size_max=2048'
        request = unit_test_utils.get_fake_request(ref)
        output = self.controller.index(request,
                                       filters={'virtual_size_max': 2048})
        self.assertEqual(3, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID1, UUID2, UUID3])
        self.assertEqual(expected, actual)

    def test_index_virtual_size_min_filter(self):
        ref = '/subjects?virtual_size_min=2048'
        request = unit_test_utils.get_fake_request(ref)
        output = self.controller.index(request,
                                       filters={'virtual_size_min': 2048})
        self.assertEqual(2, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID2, UUID3])
        self.assertEqual(expected, actual)

    def test_index_virtual_size_range_filter(self):
        path = '/subjects?virtual_size_min=512&virtual_size_max=2048'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request,
                                       filters={'virtual_size_min': 2048,
                                                'virtual_size_max': 2048})
        self.assertEqual(2, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID2, UUID3])
        self.assertEqual(expected, actual)

    def test_index_with_invalid_max_range_filter_value(self):
        request = unit_test_utils.get_fake_request('/subjects?size_max=blah')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          request,
                          filters={'size_max': 'blah'})

    def test_index_with_filters_return_many(self):
        path = '/subjects?status=queued'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request, filters={'status': 'queued'})
        self.assertEqual(1, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID3])
        self.assertEqual(expected, actual)

    def test_index_with_nonexistent_name_filter(self):
        request = unit_test_utils.get_fake_request('/subjects?name=%s' % 'blah')
        subjects = self.controller.index(request,
                                       filters={'name': 'blah'})['subjects']
        self.assertEqual(0, len(subjects))

    def test_index_with_non_default_is_public_filter(self):
        subject = _db_fixture(str(uuid.uuid4()),
                            is_public=False,
                            owner=TENANT3)
        self.db.subject_create(None, subject)
        path = '/subjects?visibility=private'
        request = unit_test_utils.get_fake_request(path, is_admin=True)
        output = self.controller.index(request,
                                       filters={'visibility': 'private'})
        self.assertEqual(2, len(output['subjects']))

    def test_index_with_many_filters(self):
        url = '/subjects?status=queued&name=3'
        request = unit_test_utils.get_fake_request(url)
        output = self.controller.index(request,
                                       filters={
                                           'status': 'queued',
                                           'name': '3',
                                       })
        self.assertEqual(1, len(output['subjects']))
        actual = set([subject.subject_id for subject in output['subjects']])
        expected = set([UUID3])
        self.assertEqual(expected, actual)

    def test_index_with_marker(self):
        self.config(limit_param_default=1, api_limit_max=3)
        path = '/subjects'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request, marker=UUID3)
        actual = set([subject.subject_id for subject in output['subjects']])
        self.assertEqual(1, len(actual))
        self.assertIn(UUID2, actual)

    def test_index_with_limit(self):
        path = '/subjects'
        limit = 2
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request, limit=limit)
        actual = set([subject.subject_id for subject in output['subjects']])
        self.assertEqual(limit, len(actual))
        self.assertIn(UUID3, actual)
        self.assertIn(UUID2, actual)

    def test_index_greater_than_limit_max(self):
        self.config(limit_param_default=1, api_limit_max=3)
        path = '/subjects'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request, limit=4)
        actual = set([subject.subject_id for subject in output['subjects']])
        self.assertEqual(3, len(actual))
        self.assertNotIn(output['next_marker'], output)

    def test_index_default_limit(self):
        self.config(limit_param_default=1, api_limit_max=3)
        path = '/subjects'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request)
        actual = set([subject.subject_id for subject in output['subjects']])
        self.assertEqual(1, len(actual))

    def test_index_with_sort_dir(self):
        path = '/subjects'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request, sort_dir=['asc'], limit=3)
        actual = [subject.subject_id for subject in output['subjects']]
        self.assertEqual(3, len(actual))
        self.assertEqual(UUID1, actual[0])
        self.assertEqual(UUID2, actual[1])
        self.assertEqual(UUID3, actual[2])

    def test_index_with_sort_key(self):
        path = '/subjects'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request, sort_key=['created_at'],
                                       limit=3)
        actual = [subject.subject_id for subject in output['subjects']]
        self.assertEqual(3, len(actual))
        self.assertEqual(UUID3, actual[0])
        self.assertEqual(UUID2, actual[1])
        self.assertEqual(UUID1, actual[2])

    def test_index_with_multiple_sort_keys(self):
        path = '/subjects'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request,
                                       sort_key=['created_at', 'name'],
                                       limit=3)
        actual = [subject.subject_id for subject in output['subjects']]
        self.assertEqual(3, len(actual))
        self.assertEqual(UUID3, actual[0])
        self.assertEqual(UUID2, actual[1])
        self.assertEqual(UUID1, actual[2])

    def test_index_with_marker_not_found(self):
        fake_uuid = str(uuid.uuid4())
        path = '/subjects'
        request = unit_test_utils.get_fake_request(path)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, request, marker=fake_uuid)

    def test_index_invalid_sort_key(self):
        path = '/subjects'
        request = unit_test_utils.get_fake_request(path)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, request, sort_key=['foo'])

    def test_index_zero_subjects(self):
        self.db.reset()
        request = unit_test_utils.get_fake_request()
        output = self.controller.index(request)
        self.assertEqual([], output['subjects'])

    def test_index_with_tags(self):
        path = '/subjects?tag=64bit'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request, filters={'tags': ['64bit']})
        actual = [subject.tags for subject in output['subjects']]
        self.assertEqual(2, len(actual))
        self.assertIn('64bit', actual[0])
        self.assertIn('64bit', actual[1])

    def test_index_with_multi_tags(self):
        path = '/subjects?tag=power&tag=64bit'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request,
                                       filters={'tags': ['power', '64bit']})
        actual = [subject.tags for subject in output['subjects']]
        self.assertEqual(1, len(actual))
        self.assertIn('64bit', actual[0])
        self.assertIn('power', actual[0])

    def test_index_with_multi_tags_and_nonexistent(self):
        path = '/subjects?tag=power&tag=fake'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request,
                                       filters={'tags': ['power', 'fake']})
        actual = [subject.tags for subject in output['subjects']]
        self.assertEqual(0, len(actual))

    def test_index_with_tags_and_properties(self):
        path = '/subjects?tag=64bit&hypervisor_type=kvm'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request,
                                       filters={'tags': ['64bit'],
                                                'hypervisor_type': 'kvm'})
        tags = [subject.tags for subject in output['subjects']]
        properties = [subject.extra_properties for subject in output['subjects']]
        self.assertEqual(len(tags), len(properties))
        self.assertIn('64bit', tags[0])
        self.assertEqual('kvm', properties[0]['hypervisor_type'])

    def test_index_with_multiple_properties(self):
        path = '/subjects?foo=bar&hypervisor_type=kvm'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request,
                                       filters={'foo': 'bar',
                                                'hypervisor_type': 'kvm'})
        properties = [subject.extra_properties for subject in output['subjects']]
        self.assertEqual('kvm', properties[0]['hypervisor_type'])
        self.assertEqual('bar', properties[0]['foo'])

    def test_index_with_core_and_extra_property(self):
        path = '/subjects?disk_format=raw&foo=bar'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request,
                                       filters={'foo': 'bar',
                                                'disk_format': 'raw'})
        properties = [subject.extra_properties for subject in output['subjects']]
        self.assertEqual(1, len(output['subjects']))
        self.assertEqual('raw', output['subjects'][0].disk_format)
        self.assertEqual('bar', properties[0]['foo'])

    def test_index_with_nonexistent_properties(self):
        path = '/subjects?abc=xyz&pudding=banana'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request,
                                       filters={'abc': 'xyz',
                                                'pudding': 'banana'})
        self.assertEqual(0, len(output['subjects']))

    def test_index_with_non_existent_tags(self):
        path = '/subjects?tag=fake'
        request = unit_test_utils.get_fake_request(path)
        output = self.controller.index(request,
                                       filters={'tags': ['fake']})
        actual = [subject.tags for subject in output['subjects']]
        self.assertEqual(0, len(actual))

    def test_show(self):
        request = unit_test_utils.get_fake_request()
        output = self.controller.show(request, subject_id=UUID2)
        self.assertEqual(UUID2, output.subject_id)
        self.assertEqual('2', output.name)

    def test_show_deleted_properties(self):
        """Ensure that the api filters out deleted subject properties."""

        # get the subject properties into the odd state
        subject = {
            'id': str(uuid.uuid4()),
            'status': 'active',
            'properties': {'poo': 'bear'},
        }
        self.db.subject_create(None, subject)
        self.db.subject_update(None, subject['id'],
                             {'properties': {'yin': 'yang'}},
                             purge_props=True)

        request = unit_test_utils.get_fake_request()
        output = self.controller.show(request, subject['id'])
        self.assertEqual('yang', output.extra_properties['yin'])

    def test_show_non_existent(self):
        request = unit_test_utils.get_fake_request()
        subject_id = str(uuid.uuid4())
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, request, subject_id)

    def test_show_deleted_subject_admin(self):
        request = unit_test_utils.get_fake_request(is_admin=True)
        self.controller.delete(request, UUID1)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, request, UUID1)

    def test_show_not_allowed(self):
        request = unit_test_utils.get_fake_request()
        self.assertEqual(TENANT1, request.context.tenant)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, request, UUID4)

    def test_create(self):
        request = unit_test_utils.get_fake_request()
        subject = {'name': 'subject-1'}
        output = self.controller.create(request, subject=subject,
                                        extra_properties={},
                                        tags=[])
        self.assertEqual('subject-1', output.name)
        self.assertEqual({}, output.extra_properties)
        self.assertEqual(set([]), output.tags)
        self.assertEqual('private', output.visibility)
        output_logs = self.notifier.get_logs()
        self.assertEqual(1, len(output_logs))
        output_log = output_logs[0]
        self.assertEqual('INFO', output_log['notification_type'])
        self.assertEqual('subject.create', output_log['event_type'])
        self.assertEqual('subject-1', output_log['payload']['name'])

    def test_create_disabled_notification(self):
        self.config(disabled_notifications=["subject.create"])
        request = unit_test_utils.get_fake_request()
        subject = {'name': 'subject-1'}
        output = self.controller.create(request, subject=subject,
                                        extra_properties={},
                                        tags=[])
        self.assertEqual('subject-1', output.name)
        self.assertEqual({}, output.extra_properties)
        self.assertEqual(set([]), output.tags)
        self.assertEqual('private', output.visibility)
        output_logs = self.notifier.get_logs()
        self.assertEqual(0, len(output_logs))

    def test_create_with_properties(self):
        request = unit_test_utils.get_fake_request()
        subject_properties = {'foo': 'bar'}
        subject = {'name': 'subject-1'}
        output = self.controller.create(request, subject=subject,
                                        extra_properties=subject_properties,
                                        tags=[])
        self.assertEqual('subject-1', output.name)
        self.assertEqual(subject_properties, output.extra_properties)
        self.assertEqual(set([]), output.tags)
        self.assertEqual('private', output.visibility)
        output_logs = self.notifier.get_logs()
        self.assertEqual(1, len(output_logs))
        output_log = output_logs[0]
        self.assertEqual('INFO', output_log['notification_type'])
        self.assertEqual('subject.create', output_log['event_type'])
        self.assertEqual('subject-1', output_log['payload']['name'])

    def test_create_with_too_many_properties(self):
        self.config(subject_property_quota=1)
        request = unit_test_utils.get_fake_request()
        subject_properties = {'foo': 'bar', 'foo2': 'bar'}
        subject = {'name': 'subject-1'}
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, request,
                          subject=subject,
                          extra_properties=subject_properties,
                          tags=[])

    def test_create_with_bad_min_disk_size(self):
        request = unit_test_utils.get_fake_request()
        subject = {'min_disk': -42, 'name': 'subject-1'}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, request,
                          subject=subject,
                          extra_properties={},
                          tags=[])

    def test_create_with_bad_min_ram_size(self):
        request = unit_test_utils.get_fake_request()
        subject = {'min_ram': -42, 'name': 'subject-1'}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, request,
                          subject=subject,
                          extra_properties={},
                          tags=[])

    def test_create_public_subject_as_admin(self):
        request = unit_test_utils.get_fake_request()
        subject = {'name': 'subject-1', 'visibility': 'public'}
        output = self.controller.create(request, subject=subject,
                                        extra_properties={}, tags=[])
        self.assertEqual('public', output.visibility)
        output_logs = self.notifier.get_logs()
        self.assertEqual(1, len(output_logs))
        output_log = output_logs[0]
        self.assertEqual('INFO', output_log['notification_type'])
        self.assertEqual('subject.create', output_log['event_type'])
        self.assertEqual(output.subject_id, output_log['payload']['id'])

    def test_create_dup_id(self):
        request = unit_test_utils.get_fake_request()
        subject = {'subject_id': UUID4}

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.create,
                          request,
                          subject=subject,
                          extra_properties={},
                          tags=[])

    def test_create_duplicate_tags(self):
        request = unit_test_utils.get_fake_request()
        tags = ['ping', 'ping']
        output = self.controller.create(request, subject={},
                                        extra_properties={}, tags=tags)
        self.assertEqual(set(['ping']), output.tags)
        output_logs = self.notifier.get_logs()
        self.assertEqual(1, len(output_logs))
        output_log = output_logs[0]
        self.assertEqual('INFO', output_log['notification_type'])
        self.assertEqual('subject.create', output_log['event_type'])
        self.assertEqual(output.subject_id, output_log['payload']['id'])

    def test_create_with_too_many_tags(self):
        self.config(subject_tag_quota=1)
        request = unit_test_utils.get_fake_request()
        tags = ['ping', 'pong']
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create,
                          request, subject={}, extra_properties={},
                          tags=tags)

    def test_create_with_owner_non_admin(self):
        request = unit_test_utils.get_fake_request()
        request.context.is_admin = False
        subject = {'owner': '12345'}
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.create,
                          request, subject=subject, extra_properties={},
                          tags=[])

        request = unit_test_utils.get_fake_request()
        request.context.is_admin = False
        subject = {'owner': TENANT1}
        output = self.controller.create(request, subject=subject,
                                        extra_properties={}, tags=[])
        self.assertEqual(TENANT1, output.owner)

    def test_create_with_owner_admin(self):
        request = unit_test_utils.get_fake_request()
        request.context.is_admin = True
        subject = {'owner': '12345'}
        output = self.controller.create(request, subject=subject,
                                        extra_properties={}, tags=[])
        self.assertEqual('12345', output.owner)

    def test_create_with_duplicate_location(self):
        request = unit_test_utils.get_fake_request()
        location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        subject = {'name': 'subject-1', 'locations': [location, location]}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          request, subject=subject, extra_properties={},
                          tags=[])

    def test_create_unexpected_property(self):
        request = unit_test_utils.get_fake_request()
        subject_properties = {'unexpected': 'unexpected'}
        subject = {'name': 'subject-1'}
        with mock.patch.object(domain.SubjectFactory, 'new_subject',
                               side_effect=TypeError):
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.controller.create, request, subject=subject,
                              extra_properties=subject_properties, tags=[])

    def test_create_reserved_property(self):
        request = unit_test_utils.get_fake_request()
        subject_properties = {'reserved': 'reserved'}
        subject = {'name': 'subject-1'}
        with mock.patch.object(domain.SubjectFactory, 'new_subject',
                               side_effect=exception.ReservedProperty(
                                   property='reserved')):
            self.assertRaises(webob.exc.HTTPForbidden,
                              self.controller.create, request, subject=subject,
                              extra_properties=subject_properties, tags=[])

    def test_create_readonly_property(self):
        request = unit_test_utils.get_fake_request()
        subject_properties = {'readonly': 'readonly'}
        subject = {'name': 'subject-1'}
        with mock.patch.object(domain.SubjectFactory, 'new_subject',
                               side_effect=exception.ReadonlyProperty(
                                   property='readonly')):
            self.assertRaises(webob.exc.HTTPForbidden,
                              self.controller.create, request, subject=subject,
                              extra_properties=subject_properties, tags=[])

    def test_update_no_changes(self):
        request = unit_test_utils.get_fake_request()
        output = self.controller.update(request, UUID1, changes=[])
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual(output.created_at, output.updated_at)
        self.assertEqual(2, len(output.tags))
        self.assertIn('ping', output.tags)
        self.assertIn('pong', output.tags)
        output_logs = self.notifier.get_logs()
        # NOTE(markwash): don't send a notification if nothing is updated
        self.assertEqual(0, len(output_logs))

    def test_update_with_bad_min_disk(self):
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'replace', 'path': ['min_disk'], 'value': -42}]
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID1, changes=changes)

    def test_update_with_bad_min_ram(self):
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'replace', 'path': ['min_ram'], 'value': -42}]
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID1, changes=changes)

    def test_update_subject_doesnt_exist(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          request, str(uuid.uuid4()), changes=[])

    def test_update_deleted_subject_admin(self):
        request = unit_test_utils.get_fake_request(is_admin=True)
        self.controller.delete(request, UUID1)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          request, UUID1, changes=[])

    def test_update_with_too_many_properties(self):
        self.config(show_multiple_locations=True)
        self.config(user_storage_quota='1')
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': new_location}]
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update,
                          request, UUID1, changes=changes)

    def test_update_replace_base_attribute(self):
        self.db.subject_update(None, UUID1, {'properties': {'foo': 'bar'}})
        request = unit_test_utils.get_fake_request()
        request.context.is_admin = True
        changes = [{'op': 'replace', 'path': ['name'], 'value': 'fedora'},
                   {'op': 'replace', 'path': ['owner'], 'value': TENANT3}]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual('fedora', output.name)
        self.assertEqual(TENANT3, output.owner)
        self.assertEqual({'foo': 'bar'}, output.extra_properties)
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_replace_onwer_non_admin(self):
        request = unit_test_utils.get_fake_request()
        request.context.is_admin = False
        changes = [{'op': 'replace', 'path': ['owner'], 'value': TENANT3}]
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.update, request, UUID1, changes)

    def test_update_replace_tags(self):
        request = unit_test_utils.get_fake_request()
        changes = [
            {'op': 'replace', 'path': ['tags'], 'value': ['king', 'kong']},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual(2, len(output.tags))
        self.assertIn('king', output.tags)
        self.assertIn('kong', output.tags)
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_replace_property(self):
        request = unit_test_utils.get_fake_request()
        properties = {'foo': 'bar', 'snitch': 'golden'}
        self.db.subject_update(None, UUID1, {'properties': properties})

        output = self.controller.show(request, UUID1)
        self.assertEqual('bar', output.extra_properties['foo'])
        self.assertEqual('golden', output.extra_properties['snitch'])

        changes = [
            {'op': 'replace', 'path': ['foo'], 'value': 'baz'},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual('baz', output.extra_properties['foo'])
        self.assertEqual('golden', output.extra_properties['snitch'])
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_add_too_many_properties(self):
        self.config(subject_property_quota=1)
        request = unit_test_utils.get_fake_request()

        changes = [
            {'op': 'add', 'path': ['foo'], 'value': 'baz'},
            {'op': 'add', 'path': ['snitch'], 'value': 'golden'},
        ]
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update, request,
                          UUID1, changes)

    def test_update_add_and_remove_too_many_properties(self):
        request = unit_test_utils.get_fake_request()

        changes = [
            {'op': 'add', 'path': ['foo'], 'value': 'baz'},
            {'op': 'add', 'path': ['snitch'], 'value': 'golden'},
        ]
        self.controller.update(request, UUID1, changes)
        self.config(subject_property_quota=1)

        # We must remove two properties to avoid being
        # over the limit of 1 property
        changes = [
            {'op': 'remove', 'path': ['foo']},
            {'op': 'add', 'path': ['fizz'], 'value': 'buzz'},
        ]
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update, request,
                          UUID1, changes)

    def test_update_add_unlimited_properties(self):
        self.config(subject_property_quota=-1)
        request = unit_test_utils.get_fake_request()
        output = self.controller.show(request, UUID1)

        changes = [{'op': 'add',
                    'path': ['foo'],
                    'value': 'bar'}]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_format_properties(self):
        statuses_for_immutability = ['active', 'saving', 'killed']
        request = unit_test_utils.get_fake_request(is_admin=True)
        for status in statuses_for_immutability:
            subject = {
                'id': str(uuid.uuid4()),
                'status': status,
                'disk_format': 'ari',
                'container_format': 'ari',
            }
            self.db.subject_create(None, subject)
            changes = [
                {'op': 'replace', 'path': ['disk_format'], 'value': 'ami'},
            ]
            self.assertRaises(webob.exc.HTTPForbidden,
                              self.controller.update,
                              request, subject['id'], changes)
            changes = [
                {'op': 'replace',
                 'path': ['container_format'],
                 'value': 'ami'},
            ]
            self.assertRaises(webob.exc.HTTPForbidden,
                              self.controller.update,
                              request, subject['id'], changes)
        self.db.subject_update(None, subject['id'], {'status': 'queued'})

        changes = [
            {'op': 'replace', 'path': ['disk_format'], 'value': 'raw'},
            {'op': 'replace', 'path': ['container_format'], 'value': 'bare'},
        ]
        resp = self.controller.update(request, subject['id'], changes)
        self.assertEqual('raw', resp.disk_format)
        self.assertEqual('bare', resp.container_format)

    def test_update_remove_property_while_over_limit(self):
        """Ensure that subject properties can be removed.

        Subject properties should be able to be removed as long as the subject has
        fewer than the limited number of subject properties after the
        transaction.

        """
        request = unit_test_utils.get_fake_request()

        changes = [
            {'op': 'add', 'path': ['foo'], 'value': 'baz'},
            {'op': 'add', 'path': ['snitch'], 'value': 'golden'},
            {'op': 'add', 'path': ['fizz'], 'value': 'buzz'},
        ]
        self.controller.update(request, UUID1, changes)
        self.config(subject_property_quota=1)

        # We must remove two properties to avoid being
        # over the limit of 1 property
        changes = [
            {'op': 'remove', 'path': ['foo']},
            {'op': 'remove', 'path': ['snitch']},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual(1, len(output.extra_properties))
        self.assertEqual('buzz', output.extra_properties['fizz'])
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_add_and_remove_property_under_limit(self):
        """Ensure that subject properties can be removed.

        Subject properties should be able to be added and removed simultaneously
        as long as the subject has fewer than the limited number of subject
        properties after the transaction.

        """
        request = unit_test_utils.get_fake_request()

        changes = [
            {'op': 'add', 'path': ['foo'], 'value': 'baz'},
            {'op': 'add', 'path': ['snitch'], 'value': 'golden'},
        ]
        self.controller.update(request, UUID1, changes)
        self.config(subject_property_quota=1)

        # We must remove two properties to avoid being
        # over the limit of 1 property
        changes = [
            {'op': 'remove', 'path': ['foo']},
            {'op': 'remove', 'path': ['snitch']},
            {'op': 'add', 'path': ['fizz'], 'value': 'buzz'},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual(1, len(output.extra_properties))
        self.assertEqual('buzz', output.extra_properties['fizz'])
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_replace_missing_property(self):
        request = unit_test_utils.get_fake_request()

        changes = [
            {'op': 'replace', 'path': 'foo', 'value': 'baz'},
        ]
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.update, request, UUID1, changes)

    def test_prop_protection_with_create_and_permitted_role(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties={},
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['member'])
        changes = [
            {'op': 'add', 'path': ['x_owner_foo'], 'value': 'bar'},
        ]
        output = self.controller.update(another_request,
                                        created_subject.subject_id, changes)
        self.assertEqual('bar', output.extra_properties['x_owner_foo'])

    def test_prop_protection_with_update_and_permitted_policy(self):
        self.set_property_protections(use_policies=True)
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        request = unit_test_utils.get_fake_request(roles=['spl_role'])
        subject = {'name': 'subject-1'}
        extra_props = {'spl_creator_policy': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        self.assertEqual('bar',
                         created_subject.extra_properties['spl_creator_policy'])

        another_request = unit_test_utils.get_fake_request(roles=['spl_role'])
        changes = [
            {'op': 'replace', 'path': ['spl_creator_policy'], 'value': 'par'},
        ]
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          another_request, created_subject.subject_id, changes)
        another_request = unit_test_utils.get_fake_request(roles=['admin'])
        output = self.controller.update(another_request,
                                        created_subject.subject_id, changes)
        self.assertEqual('par',
                         output.extra_properties['spl_creator_policy'])

    def test_prop_protection_with_create_with_patch_and_policy(self):
        self.set_property_protections(use_policies=True)
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        request = unit_test_utils.get_fake_request(roles=['spl_role', 'admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'spl_default_policy': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['fake_role'])
        changes = [
            {'op': 'add', 'path': ['spl_creator_policy'], 'value': 'bar'},
        ]
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          another_request, created_subject.subject_id, changes)

        another_request = unit_test_utils.get_fake_request(roles=['spl_role'])
        output = self.controller.update(another_request,
                                        created_subject.subject_id, changes)
        self.assertEqual('bar',
                         output.extra_properties['spl_creator_policy'])

    def test_prop_protection_with_create_and_unpermitted_role(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties={},
                                               tags=[])
        roles = ['fake_member']
        another_request = unit_test_utils.get_fake_request(roles=roles)
        changes = [
            {'op': 'add', 'path': ['x_owner_foo'], 'value': 'bar'},
        ]
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.update, another_request,
                          created_subject.subject_id, changes)

    def test_prop_protection_with_show_and_permitted_role(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_owner_foo': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['member'])
        output = self.controller.show(another_request, created_subject.subject_id)
        self.assertEqual('bar', output.extra_properties['x_owner_foo'])

    def test_prop_protection_with_show_and_unpermitted_role(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['member'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_owner_foo': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['fake_role'])
        output = self.controller.show(another_request, created_subject.subject_id)
        self.assertRaises(KeyError, output.extra_properties.__getitem__,
                          'x_owner_foo')

    def test_prop_protection_with_update_and_permitted_role(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_owner_foo': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['member'])
        changes = [
            {'op': 'replace', 'path': ['x_owner_foo'], 'value': 'baz'},
        ]
        output = self.controller.update(another_request,
                                        created_subject.subject_id, changes)
        self.assertEqual('baz', output.extra_properties['x_owner_foo'])

    def test_prop_protection_with_update_and_unpermitted_role(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_owner_foo': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['fake_role'])
        changes = [
            {'op': 'replace', 'path': ['x_owner_foo'], 'value': 'baz'},
        ]
        self.assertRaises(webob.exc.HTTPConflict, self.controller.update,
                          another_request, created_subject.subject_id, changes)

    def test_prop_protection_with_delete_and_permitted_role(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_owner_foo': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['member'])
        changes = [
            {'op': 'remove', 'path': ['x_owner_foo']}
        ]
        output = self.controller.update(another_request,
                                        created_subject.subject_id, changes)
        self.assertRaises(KeyError, output.extra_properties.__getitem__,
                          'x_owner_foo')

    def test_prop_protection_with_delete_and_unpermitted_role(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_owner_foo': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['fake_role'])
        changes = [
            {'op': 'remove', 'path': ['x_owner_foo']}
        ]
        self.assertRaises(webob.exc.HTTPConflict, self.controller.update,
                          another_request, created_subject.subject_id, changes)

    def test_create_protected_prop_case_insensitive(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties={},
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['member'])
        changes = [
            {'op': 'add', 'path': ['x_case_insensitive'], 'value': '1'},
        ]
        output = self.controller.update(another_request,
                                        created_subject.subject_id, changes)
        self.assertEqual('1', output.extra_properties['x_case_insensitive'])

    def test_read_protected_prop_case_insensitive(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_case_insensitive': '1'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['member'])
        output = self.controller.show(another_request, created_subject.subject_id)
        self.assertEqual('1', output.extra_properties['x_case_insensitive'])

    def test_update_protected_prop_case_insensitive(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_case_insensitive': '1'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['member'])
        changes = [
            {'op': 'replace', 'path': ['x_case_insensitive'], 'value': '2'},
        ]
        output = self.controller.update(another_request,
                                        created_subject.subject_id, changes)
        self.assertEqual('2', output.extra_properties['x_case_insensitive'])

    def test_delete_protected_prop_case_insensitive(self):
        enforcer = subject.api.policy.Enforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   enforcer,
                                                                   self.notifier,
                                                                   self.store)
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_case_insensitive': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['member'])
        changes = [
            {'op': 'remove', 'path': ['x_case_insensitive']}
        ]
        output = self.controller.update(another_request,
                                        created_subject.subject_id, changes)
        self.assertRaises(KeyError, output.extra_properties.__getitem__,
                          'x_case_insensitive')

    def test_create_non_protected_prop(self):
        """Property marked with special char @ creatable by an unknown role"""
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_all_permitted_1': '1'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        self.assertEqual('1',
                         created_subject.extra_properties['x_all_permitted_1'])
        another_request = unit_test_utils.get_fake_request(roles=['joe_soap'])
        extra_props = {'x_all_permitted_2': '2'}
        created_subject = self.controller.create(another_request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        self.assertEqual('2',
                         created_subject.extra_properties['x_all_permitted_2'])

    def test_read_non_protected_prop(self):
        """Property marked with special char @ readable by an unknown role"""
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_all_permitted': '1'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['joe_soap'])
        output = self.controller.show(another_request, created_subject.subject_id)
        self.assertEqual('1', output.extra_properties['x_all_permitted'])

    def test_update_non_protected_prop(self):
        """Property marked with special char @ updatable by an unknown role"""
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_all_permitted': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['joe_soap'])
        changes = [
            {'op': 'replace', 'path': ['x_all_permitted'], 'value': 'baz'},
        ]
        output = self.controller.update(another_request,
                                        created_subject.subject_id, changes)
        self.assertEqual('baz', output.extra_properties['x_all_permitted'])

    def test_delete_non_protected_prop(self):
        """Property marked with special char @ deletable by an unknown role"""
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_all_permitted': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['member'])
        changes = [
            {'op': 'remove', 'path': ['x_all_permitted']}
        ]
        output = self.controller.update(another_request,
                                        created_subject.subject_id, changes)
        self.assertRaises(KeyError, output.extra_properties.__getitem__,
                          'x_all_permitted')

    def test_create_locked_down_protected_prop(self):
        """Property marked with special char ! creatable by no one"""
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties={},
                                               tags=[])
        roles = ['fake_member']
        another_request = unit_test_utils.get_fake_request(roles=roles)
        changes = [
            {'op': 'add', 'path': ['x_none_permitted'], 'value': 'bar'},
        ]
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.update, another_request,
                          created_subject.subject_id, changes)

    def test_read_locked_down_protected_prop(self):
        """Property marked with special char ! readable by no one"""
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['member'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_none_read': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['fake_role'])
        output = self.controller.show(another_request, created_subject.subject_id)
        self.assertRaises(KeyError, output.extra_properties.__getitem__,
                          'x_none_read')

    def test_update_locked_down_protected_prop(self):
        """Property marked with special char ! updatable by no one"""
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_none_update': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['fake_role'])
        changes = [
            {'op': 'replace', 'path': ['x_none_update'], 'value': 'baz'},
        ]
        self.assertRaises(webob.exc.HTTPConflict, self.controller.update,
                          another_request, created_subject.subject_id, changes)

    def test_delete_locked_down_protected_prop(self):
        """Property marked with special char ! deletable by no one"""
        self.set_property_protections()
        request = unit_test_utils.get_fake_request(roles=['admin'])
        subject = {'name': 'subject-1'}
        extra_props = {'x_none_delete': 'bar'}
        created_subject = self.controller.create(request, subject=subject,
                                               extra_properties=extra_props,
                                               tags=[])
        another_request = unit_test_utils.get_fake_request(roles=['fake_role'])
        changes = [
            {'op': 'remove', 'path': ['x_none_delete']}
        ]
        self.assertRaises(webob.exc.HTTPConflict, self.controller.update,
                          another_request, created_subject.subject_id, changes)

    def test_update_replace_locations_non_empty(self):
        self.config(show_multiple_locations=True)
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'replace', 'path': ['locations'],
                    'value': [new_location]}]
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID1, changes)

    def test_update_replace_locations_metadata_update(self):
        self.config(show_multiple_locations=True)
        location = {'url': '%s/%s' % (BASE_URI, UUID1),
                    'metadata': {'a': 1}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'replace', 'path': ['locations'],
                    'value': [location]}]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual({'a': 1}, output.locations[0]['metadata'])

    def test_locations_actions_with_locations_invisible(self):
        self.config(show_multiple_locations=False)
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'replace', 'path': ['locations'],
                    'value': [new_location]}]
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          request, UUID1, changes)

    def test_update_replace_locations_invalid(self):
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'replace', 'path': ['locations'], 'value': []}]
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          request, UUID1, changes)

    def test_update_add_property(self):
        request = unit_test_utils.get_fake_request()

        changes = [
            {'op': 'add', 'path': ['foo'], 'value': 'baz'},
            {'op': 'add', 'path': ['snitch'], 'value': 'golden'},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual('baz', output.extra_properties['foo'])
        self.assertEqual('golden', output.extra_properties['snitch'])
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_add_base_property_json_schema_version_4(self):
        request = unit_test_utils.get_fake_request()
        changes = [{
            'json_schema_version': 4, 'op': 'add',
            'path': ['name'], 'value': 'fedora'
        }]
        self.assertRaises(webob.exc.HTTPConflict, self.controller.update,
                          request, UUID1, changes)

    def test_update_add_extra_property_json_schema_version_4(self):
        self.db.subject_update(None, UUID1, {'properties': {'foo': 'bar'}})
        request = unit_test_utils.get_fake_request()
        changes = [{
            'json_schema_version': 4, 'op': 'add',
            'path': ['foo'], 'value': 'baz'
        }]
        self.assertRaises(webob.exc.HTTPConflict, self.controller.update,
                          request, UUID1, changes)

    def test_update_add_base_property_json_schema_version_10(self):
        request = unit_test_utils.get_fake_request()
        changes = [{
            'json_schema_version': 10, 'op': 'add',
            'path': ['name'], 'value': 'fedora'
        }]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual('fedora', output.name)

    def test_update_add_extra_property_json_schema_version_10(self):
        self.db.subject_update(None, UUID1, {'properties': {'foo': 'bar'}})
        request = unit_test_utils.get_fake_request()
        changes = [{
            'json_schema_version': 10, 'op': 'add',
            'path': ['foo'], 'value': 'baz'
        }]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual({'foo': 'baz'}, output.extra_properties)

    def test_update_add_property_already_present_json_schema_version_4(self):
        request = unit_test_utils.get_fake_request()
        properties = {'foo': 'bar'}
        self.db.subject_update(None, UUID1, {'properties': properties})

        output = self.controller.show(request, UUID1)
        self.assertEqual('bar', output.extra_properties['foo'])

        changes = [
            {'json_schema_version': 4, 'op': 'add',
             'path': ['foo'], 'value': 'baz'},
        ]
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.update, request, UUID1, changes)

    def test_update_add_property_already_present_json_schema_version_10(self):
        request = unit_test_utils.get_fake_request()
        properties = {'foo': 'bar'}
        self.db.subject_update(None, UUID1, {'properties': properties})

        output = self.controller.show(request, UUID1)
        self.assertEqual('bar', output.extra_properties['foo'])

        changes = [
            {'json_schema_version': 10, 'op': 'add',
             'path': ['foo'], 'value': 'baz'},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual({'foo': 'baz'}, output.extra_properties)

    def test_update_add_locations(self):
        self.config(show_multiple_locations=True)
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': new_location}]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual(2, len(output.locations))
        self.assertEqual(new_location, output.locations[1])

    def test_update_add_locations_status_saving(self):
        self.config(show_multiple_locations=True)
        self.subjects = [
            _db_fixture('1', owner=TENANT1, checksum=CHKSUM,
                        name='1',
                        disk_format='raw',
                        container_format='bare',
                        status='saving'),
        ]
        self.db.subject_create(None, self.subjects[0])
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': new_location}]
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.update, request, '1', changes)

    def test_update_add_locations_status_deactivated(self):
        self.config(show_multiple_locations=True)
        self.subjects = [
            _db_fixture('1', owner=TENANT1, checksum=CHKSUM,
                        name='1',
                        disk_format='raw',
                        container_format='bare',
                        status='deactivated'),
        ]
        request = unit_test_utils.get_fake_request()
        self.db.subject_create(request.context, self.subjects[0])
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': new_location}]
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.update, request, '1', changes)

    def test_update_add_locations_status_deleted(self):
        self.config(show_multiple_locations=True)
        self.subjects = [
            _db_fixture('1', owner=TENANT1, checksum=CHKSUM,
                        name='1',
                        disk_format='raw',
                        container_format='bare',
                        status='deleted'),
        ]
        self.db.subject_create(None, self.subjects[0])
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': new_location}]
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.update, request, '1', changes)

    def test_update_add_locations_status_pending_delete(self):
        self.config(show_multiple_locations=True)
        self.subjects = [
            _db_fixture('1', owner=TENANT1, checksum=CHKSUM,
                        name='1',
                        disk_format='raw',
                        container_format='bare',
                        status='pending_delete'),
        ]
        self.db.subject_create(None, self.subjects[0])
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': new_location}]
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.update, request, '1', changes)

    def test_update_add_locations_status_killed(self):
        self.config(show_multiple_locations=True)
        self.subjects = [
            _db_fixture('1', owner=TENANT1, checksum=CHKSUM,
                        name='1',
                        disk_format='raw',
                        container_format='bare',
                        status='killed'),
        ]
        self.db.subject_create(None, self.subjects[0])
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': new_location}]
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.update, request, '1', changes)

    def test_update_add_locations_insertion(self):
        self.config(show_multiple_locations=True)
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'add', 'path': ['locations', '0'],
                    'value': new_location}]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual(2, len(output.locations))
        self.assertEqual(new_location, output.locations[0])

    def test_update_add_locations_list(self):
        self.config(show_multiple_locations=True)
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': {'url': 'foo', 'metadata': {}}}]
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID1, changes)

    def test_update_add_locations_invalid(self):
        self.config(show_multiple_locations=True)
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': {'url': 'unknow://foo', 'metadata': {}}}]
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID1, changes)

        changes = [{'op': 'add', 'path': ['locations', None],
                    'value': {'url': 'unknow://foo', 'metadata': {}}}]
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID1, changes)

    def test_update_add_duplicate_locations(self):
        self.config(show_multiple_locations=True)
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': new_location}]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual(2, len(output.locations))
        self.assertEqual(new_location, output.locations[1])

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID1, changes)

    def test_update_add_too_many_locations(self):
        self.config(show_multiple_locations=True)
        self.config(subject_location_quota=1)
        request = unit_test_utils.get_fake_request()
        changes = [
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location_1' % BASE_URI,
                       'metadata': {}}},
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location_2' % BASE_URI,
                       'metadata': {}}},
        ]
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update, request,
                          UUID1, changes)

    def test_update_add_and_remove_too_many_locations(self):
        self.config(show_multiple_locations=True)
        request = unit_test_utils.get_fake_request()
        changes = [
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location_1' % BASE_URI,
                       'metadata': {}}},
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location_2' % BASE_URI,
                       'metadata': {}}},
        ]
        self.controller.update(request, UUID1, changes)
        self.config(subject_location_quota=1)

        # We must remove two properties to avoid being
        # over the limit of 1 property
        changes = [
            {'op': 'remove', 'path': ['locations', '0']},
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location_3' % BASE_URI,
                       'metadata': {}}},
        ]
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.update, request,
                          UUID1, changes)

    def test_update_add_unlimited_locations(self):
        self.config(show_multiple_locations=True)
        self.config(subject_location_quota=-1)
        request = unit_test_utils.get_fake_request()
        changes = [
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location_1' % BASE_URI,
                       'metadata': {}}},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_remove_location_while_over_limit(self):
        """Ensure that subject locations can be removed.

        Subject locations should be able to be removed as long as the subject has
        fewer than the limited number of subject locations after the
        transaction.
        """
        self.config(show_multiple_locations=True)
        request = unit_test_utils.get_fake_request()
        changes = [
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location_1' % BASE_URI,
                       'metadata': {}}},
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location_2' % BASE_URI,
                       'metadata': {}}},
        ]
        self.controller.update(request, UUID1, changes)
        self.config(subject_location_quota=1)
        self.config(show_multiple_locations=True)

        # We must remove two locations to avoid being over
        # the limit of 1 location
        changes = [
            {'op': 'remove', 'path': ['locations', '0']},
            {'op': 'remove', 'path': ['locations', '0']},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual(1, len(output.locations))
        self.assertIn('fake_location_2', output.locations[0]['url'])
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_add_and_remove_location_under_limit(self):
        """Ensure that subject locations can be removed.

        Subject locations should be able to be added and removed simultaneously
        as long as the subject has fewer than the limited number of subject
        locations after the transaction.
        """
        self.stubs.Set(store, 'get_size_from_backend',
                       unit_test_utils.fake_get_size_from_backend)
        self.config(show_multiple_locations=True)
        request = unit_test_utils.get_fake_request()

        changes = [
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location_1' % BASE_URI,
                       'metadata': {}}},
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location_2' % BASE_URI,
                       'metadata': {}}},
        ]
        self.controller.update(request, UUID1, changes)
        self.config(subject_location_quota=2)

        # We must remove two properties to avoid being
        # over the limit of 1 property
        changes = [
            {'op': 'remove', 'path': ['locations', '0']},
            {'op': 'remove', 'path': ['locations', '0']},
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location_3' % BASE_URI,
                       'metadata': {}}},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual(2, len(output.locations))
        self.assertIn('fake_location_3', output.locations[1]['url'])
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_remove_base_property(self):
        self.db.subject_update(None, UUID1, {'properties': {'foo': 'bar'}})
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'remove', 'path': ['name']}]
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          request, UUID1, changes)

    def test_update_remove_property(self):
        request = unit_test_utils.get_fake_request()
        properties = {'foo': 'bar', 'snitch': 'golden'}
        self.db.subject_update(None, UUID1, {'properties': properties})

        output = self.controller.show(request, UUID1)
        self.assertEqual('bar', output.extra_properties['foo'])
        self.assertEqual('golden', output.extra_properties['snitch'])

        changes = [
            {'op': 'remove', 'path': ['snitch']},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual({'foo': 'bar'}, output.extra_properties)
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_remove_missing_property(self):
        request = unit_test_utils.get_fake_request()

        changes = [
            {'op': 'remove', 'path': ['foo']},
        ]
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.update, request, UUID1, changes)

    def test_update_remove_location(self):
        self.config(show_multiple_locations=True)
        self.stubs.Set(store, 'get_size_from_backend',
                       unit_test_utils.fake_get_size_from_backend)

        request = unit_test_utils.get_fake_request()
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': new_location}]
        self.controller.update(request, UUID1, changes)
        changes = [{'op': 'remove', 'path': ['locations', '0']}]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual(1, len(output.locations))
        self.assertEqual('active', output.status)

    def test_update_remove_location_invalid_pos(self):
        self.config(show_multiple_locations=True)
        request = unit_test_utils.get_fake_request()
        changes = [
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location' % BASE_URI,
                       'metadata': {}}}]
        self.controller.update(request, UUID1, changes)
        changes = [{'op': 'remove', 'path': ['locations', None]}]
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID1, changes)
        changes = [{'op': 'remove', 'path': ['locations', '-1']}]
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID1, changes)
        changes = [{'op': 'remove', 'path': ['locations', '99']}]
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID1, changes)
        changes = [{'op': 'remove', 'path': ['locations', 'x']}]
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID1, changes)

    def test_update_remove_location_store_exception(self):
        self.config(show_multiple_locations=True)

        def fake_delete_subject_location_from_backend(self, *args, **kwargs):
            raise Exception('fake_backend_exception')

        self.stubs.Set(self.store_utils, 'delete_subject_location_from_backend',
                       fake_delete_subject_location_from_backend)

        request = unit_test_utils.get_fake_request()
        changes = [
            {'op': 'add', 'path': ['locations', '-'],
             'value': {'url': '%s/fake_location' % BASE_URI,
                       'metadata': {}}}]
        self.controller.update(request, UUID1, changes)
        changes = [{'op': 'remove', 'path': ['locations', '0']}]
        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.update, request, UUID1, changes)

    def test_update_multiple_changes(self):
        request = unit_test_utils.get_fake_request()
        properties = {'foo': 'bar', 'snitch': 'golden'}
        self.db.subject_update(None, UUID1, {'properties': properties})

        changes = [
            {'op': 'replace', 'path': ['min_ram'], 'value': 128},
            {'op': 'replace', 'path': ['foo'], 'value': 'baz'},
            {'op': 'remove', 'path': ['snitch']},
            {'op': 'add', 'path': ['kb'], 'value': 'dvorak'},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(UUID1, output.subject_id)
        self.assertEqual(128, output.min_ram)
        self.addDetail('extra_properties',
                       testtools.content.json_content(
                           jsonutils.dumps(output.extra_properties)))
        self.assertEqual(2, len(output.extra_properties))
        self.assertEqual('baz', output.extra_properties['foo'])
        self.assertEqual('dvorak', output.extra_properties['kb'])
        self.assertNotEqual(output.created_at, output.updated_at)

    def test_update_invalid_operation(self):
        request = unit_test_utils.get_fake_request()
        change = {'op': 'test', 'path': 'options', 'value': 'puts'}
        try:
            self.controller.update(request, UUID1, [change])
        except AttributeError:
            pass  # AttributeError is the desired behavior
        else:
            self.fail('Failed to raise AssertionError on %s' % change)

    def test_update_duplicate_tags(self):
        request = unit_test_utils.get_fake_request()
        changes = [
            {'op': 'replace', 'path': ['tags'], 'value': ['ping', 'ping']},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual(1, len(output.tags))
        self.assertIn('ping', output.tags)
        output_logs = self.notifier.get_logs()
        self.assertEqual(1, len(output_logs))
        output_log = output_logs[0]
        self.assertEqual('INFO', output_log['notification_type'])
        self.assertEqual('subject.update', output_log['event_type'])
        self.assertEqual(UUID1, output_log['payload']['id'])

    def test_update_disabled_notification(self):
        self.config(disabled_notifications=["subject.update"])
        request = unit_test_utils.get_fake_request()
        changes = [
            {'op': 'replace', 'path': ['name'], 'value': 'Ping Pong'},
        ]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual('Ping Pong', output.name)
        output_logs = self.notifier.get_logs()
        self.assertEqual(0, len(output_logs))

    def test_delete(self):
        request = unit_test_utils.get_fake_request()
        self.assertIn('%s/%s' % (BASE_URI, UUID1), self.store.data)
        try:
            self.controller.delete(request, UUID1)
            output_logs = self.notifier.get_logs()
            self.assertEqual(1, len(output_logs))
            output_log = output_logs[0]
            self.assertEqual('INFO', output_log['notification_type'])
            self.assertEqual("subject.delete", output_log['event_type'])
        except Exception as e:
            self.fail("Delete raised exception: %s" % e)

        deleted_img = self.db.subject_get(request.context, UUID1,
                                        force_show_deleted=True)
        self.assertTrue(deleted_img['deleted'])
        self.assertEqual('deleted', deleted_img['status'])
        self.assertNotIn('%s/%s' % (BASE_URI, UUID1), self.store.data)

    def test_delete_with_tags(self):
        request = unit_test_utils.get_fake_request()
        changes = [
            {'op': 'replace', 'path': ['tags'],
             'value': ['many', 'cool', 'new', 'tags']},
        ]
        self.controller.update(request, UUID1, changes)
        self.assertIn('%s/%s' % (BASE_URI, UUID1), self.store.data)
        self.controller.delete(request, UUID1)
        output_logs = self.notifier.get_logs()

        # Get `delete` event from logs
        output_delete_logs = [output_log for output_log in output_logs
                              if output_log['event_type'] == 'subject.delete']

        self.assertEqual(1, len(output_delete_logs))
        output_log = output_delete_logs[0]

        self.assertEqual('INFO', output_log['notification_type'])

        deleted_img = self.db.subject_get(request.context, UUID1,
                                        force_show_deleted=True)
        self.assertTrue(deleted_img['deleted'])
        self.assertEqual('deleted', deleted_img['status'])
        self.assertNotIn('%s/%s' % (BASE_URI, UUID1), self.store.data)

    def test_delete_disabled_notification(self):
        self.config(disabled_notifications=["subject.delete"])
        request = unit_test_utils.get_fake_request()
        self.assertIn('%s/%s' % (BASE_URI, UUID1), self.store.data)
        try:
            self.controller.delete(request, UUID1)
            output_logs = self.notifier.get_logs()
            self.assertEqual(0, len(output_logs))
        except Exception as e:
            self.fail("Delete raised exception: %s" % e)

        deleted_img = self.db.subject_get(request.context, UUID1,
                                        force_show_deleted=True)
        self.assertTrue(deleted_img['deleted'])
        self.assertEqual('deleted', deleted_img['status'])
        self.assertNotIn('%s/%s' % (BASE_URI, UUID1), self.store.data)

    def test_delete_queued_updates_status(self):
        """Ensure status of queued subject is updated (LP bug #1048851)"""
        request = unit_test_utils.get_fake_request(is_admin=True)
        subject = self.db.subject_create(request.context, {'status': 'queued'})
        subject_id = subject['id']
        self.controller.delete(request, subject_id)

        subject = self.db.subject_get(request.context, subject_id,
                                  force_show_deleted=True)
        self.assertTrue(subject['deleted'])
        self.assertEqual('deleted', subject['status'])

    def test_delete_queued_updates_status_delayed_delete(self):
        """Ensure status of queued subject is updated (LP bug #1048851).

        Must be set to 'deleted' when delayed_delete isenabled.
        """
        self.config(delayed_delete=True)

        request = unit_test_utils.get_fake_request(is_admin=True)
        subject = self.db.subject_create(request.context, {'status': 'queued'})
        subject_id = subject['id']
        self.controller.delete(request, subject_id)

        subject = self.db.subject_get(request.context, subject_id,
                                  force_show_deleted=True)
        self.assertTrue(subject['deleted'])
        self.assertEqual('deleted', subject['status'])

    def test_delete_not_in_store(self):
        request = unit_test_utils.get_fake_request()
        self.assertIn('%s/%s' % (BASE_URI, UUID1), self.store.data)
        for k in self.store.data:
            if UUID1 in k:
                del self.store.data[k]
                break

        self.controller.delete(request, UUID1)
        deleted_img = self.db.subject_get(request.context, UUID1,
                                        force_show_deleted=True)
        self.assertTrue(deleted_img['deleted'])
        self.assertEqual('deleted', deleted_img['status'])
        self.assertNotIn('%s/%s' % (BASE_URI, UUID1), self.store.data)

    def test_delayed_delete(self):
        self.config(delayed_delete=True)
        request = unit_test_utils.get_fake_request()
        self.assertIn('%s/%s' % (BASE_URI, UUID1), self.store.data)

        self.controller.delete(request, UUID1)
        deleted_img = self.db.subject_get(request.context, UUID1,
                                        force_show_deleted=True)
        self.assertTrue(deleted_img['deleted'])
        self.assertEqual('pending_delete', deleted_img['status'])
        self.assertIn('%s/%s' % (BASE_URI, UUID1), self.store.data)

    def test_delete_non_existent(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          request, str(uuid.uuid4()))

    def test_delete_already_deleted_subject_admin(self):
        request = unit_test_utils.get_fake_request(is_admin=True)
        self.controller.delete(request, UUID1)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, request, UUID1)

    def test_delete_not_allowed(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          request, UUID4)

    def test_delete_in_use(self):
        def fake_safe_delete_from_backend(self, *args, **kwargs):
            raise store.exceptions.InUseByStore()
        self.stubs.Set(self.store_utils, 'safe_delete_from_backend',
                       fake_safe_delete_from_backend)
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPConflict, self.controller.delete,
                          request, UUID1)

    def test_delete_has_snapshot(self):
        def fake_safe_delete_from_backend(self, *args, **kwargs):
            raise store.exceptions.HasSnapshot()
        self.stubs.Set(self.store_utils, 'safe_delete_from_backend',
                       fake_safe_delete_from_backend)
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPConflict, self.controller.delete,
                          request, UUID1)

    def test_delete_to_unallowed_status(self):
        # from deactivated to pending-delete
        self.config(delayed_delete=True)
        request = unit_test_utils.get_fake_request(is_admin=True)
        self.action_controller.deactivate(request, UUID1)

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                          request, UUID1)

    def test_index_with_invalid_marker(self):
        fake_uuid = str(uuid.uuid4())
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, request, marker=fake_uuid)

    def test_invalid_locations_op_pos(self):
        pos = self.controller._get_locations_op_pos(None, 2, True)
        self.assertIsNone(pos)
        pos = self.controller._get_locations_op_pos('1', None, True)
        self.assertIsNone(pos)


class TestSubjectsControllerPolicies(base.IsolatedUnitTest):

    def setUp(self):
        super(TestSubjectsControllerPolicies, self).setUp()
        self.db = unit_test_utils.FakeDB()
        self.policy = unit_test_utils.FakePolicyEnforcer()
        self.controller = subject.api.v2.subjects.SubjectsController(self.db,
                                                                   self.policy)
        store = unit_test_utils.FakeStoreAPI()
        self.store_utils = unit_test_utils.FakeStoreUtils(store)

    def test_index_unauthorized(self):
        rules = {"get_subjects": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.index,
                          request)

    def test_show_unauthorized(self):
        rules = {"get_subject": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
                          request, subject_id=UUID2)

    def test_create_subject_unauthorized(self):
        rules = {"add_subject": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        subject = {'name': 'subject-1'}
        extra_properties = {}
        tags = []
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.create,
                          request, subject, extra_properties, tags)

    def test_create_public_subject_unauthorized(self):
        rules = {"publicize_subject": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        subject = {'name': 'subject-1', 'visibility': 'public'}
        extra_properties = {}
        tags = []
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.create,
                          request, subject, extra_properties, tags)

    def test_update_unauthorized(self):
        rules = {"modify_subject": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'replace', 'path': ['name'], 'value': 'subject-2'}]
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          request, UUID1, changes)

    def test_update_publicize_subject_unauthorized(self):
        rules = {"publicize_subject": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'replace', 'path': ['visibility'],
                    'value': 'public'}]
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          request, UUID1, changes)

    def test_update_depublicize_subject_unauthorized(self):
        rules = {"publicize_subject": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'replace', 'path': ['visibility'],
                    'value': 'private'}]
        output = self.controller.update(request, UUID1, changes)
        self.assertEqual('private', output.visibility)

    def test_update_get_subject_location_unauthorized(self):
        rules = {"get_subject_location": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'replace', 'path': ['locations'], 'value': []}]
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          request, UUID1, changes)

    def test_update_set_subject_location_unauthorized(self):
        def fake_delete_subject_location_from_backend(self, *args, **kwargs):
            pass

        rules = {"set_subject_location": False}
        self.policy.set_rules(rules)
        new_location = {'url': '%s/fake_location' % BASE_URI, 'metadata': {}}
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'add', 'path': ['locations', '-'],
                    'value': new_location}]
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          request, UUID1, changes)

    def test_update_delete_subject_location_unauthorized(self):
        rules = {"delete_subject_location": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        changes = [{'op': 'replace', 'path': ['locations'], 'value': []}]
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          request, UUID1, changes)

    def test_delete_unauthorized(self):
        rules = {"delete_subject": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          request, UUID1)


class TestSubjectsDeserializer(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectsDeserializer, self).setUp()
        self.deserializer = subject.api.v2.subjects.RequestDeserializer()

    def test_create_minimal(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({})
        output = self.deserializer.create(request)
        expected = {'subject': {}, 'extra_properties': {}, 'tags': []}
        self.assertEqual(expected, output)

    def test_create_invalid_id(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({'id': 'gabe'})
        self.assertRaises(webob.exc.HTTPBadRequest, self.deserializer.create,
                          request)

    def test_create_id_to_subject_id(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({'id': UUID4})
        output = self.deserializer.create(request)
        expected = {'subject': {'subject_id': UUID4},
                    'extra_properties': {},
                    'tags': []}
        self.assertEqual(expected, output)

    def test_create_no_body(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPBadRequest, self.deserializer.create,
                          request)

    def test_create_full(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({
            'id': UUID3,
            'name': 'subject-1',
            'visibility': 'public',
            'tags': ['one', 'two'],
            'container_format': 'ami',
            'disk_format': 'ami',
            'min_ram': 128,
            'min_disk': 10,
            'foo': 'bar',
            'protected': True,
        })
        output = self.deserializer.create(request)
        properties = {
            'subject_id': UUID3,
            'name': 'subject-1',
            'visibility': 'public',
            'container_format': 'ami',
            'disk_format': 'ami',
            'min_ram': 128,
            'min_disk': 10,
            'protected': True,
        }
        self.maxDiff = None
        expected = {'subject': properties,
                    'extra_properties': {'foo': 'bar'},
                    'tags': ['one', 'two']}
        self.assertEqual(expected, output)

    def test_create_readonly_attributes_forbidden(self):
        bodies = [
            {'direct_url': 'http://example.com'},
            {'self': 'http://example.com'},
            {'file': 'http://example.com'},
            {'schema': 'http://example.com'},
        ]

        for body in bodies:
            request = unit_test_utils.get_fake_request()
            request.body = jsonutils.dump_as_bytes(body)
            self.assertRaises(webob.exc.HTTPForbidden,
                              self.deserializer.create, request)

    def _get_fake_patch_request(self, content_type_minor_version=1):
        request = unit_test_utils.get_fake_request()
        template = 'application/openstack-subjects-v1.%d-json-patch'
        request.content_type = template % content_type_minor_version
        return request

    def test_update_empty_body(self):
        request = self._get_fake_patch_request()
        request.body = jsonutils.dump_as_bytes([])
        output = self.deserializer.update(request)
        expected = {'changes': []}
        self.assertEqual(expected, output)

    def test_update_unsupported_content_type(self):
        request = unit_test_utils.get_fake_request()
        request.content_type = 'application/json-patch'
        request.body = jsonutils.dump_as_bytes([])
        try:
            self.deserializer.update(request)
        except webob.exc.HTTPUnsupportedMediaType as e:
            # desired result, but must have correct Accept-Patch header
            accept_patch = ['application/openstack-subjects-v1.1-json-patch',
                            'application/openstack-subjects-v1.0-json-patch']
            expected = ', '.join(sorted(accept_patch))
            self.assertEqual(expected, e.headers['Accept-Patch'])
        else:
            self.fail('Did not raise HTTPUnsupportedMediaType')

    def test_update_body_not_a_list(self):
        bodies = [
            {'op': 'add', 'path': '/someprop', 'value': 'somevalue'},
            'just some string',
            123,
            True,
            False,
            None,
        ]
        for body in bodies:
            request = self._get_fake_patch_request()
            request.body = jsonutils.dump_as_bytes(body)
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.deserializer.update, request)

    def test_update_invalid_changes(self):
        changes = [
            ['a', 'list', 'of', 'stuff'],
            'just some string',
            123,
            True,
            False,
            None,
            {'op': 'invalid', 'path': '/name', 'value': 'fedora'}
        ]
        for change in changes:
            request = self._get_fake_patch_request()
            request.body = jsonutils.dump_as_bytes([change])
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.deserializer.update, request)

    def test_update(self):
        request = self._get_fake_patch_request()
        body = [
            {'op': 'replace', 'path': '/name', 'value': 'fedora'},
            {'op': 'replace', 'path': '/tags', 'value': ['king', 'kong']},
            {'op': 'replace', 'path': '/foo', 'value': 'bar'},
            {'op': 'add', 'path': '/bebim', 'value': 'bap'},
            {'op': 'remove', 'path': '/sparks'},
            {'op': 'add', 'path': '/locations/-',
             'value': {'url': 'scheme3://path3', 'metadata': {}}},
            {'op': 'add', 'path': '/locations/10',
             'value': {'url': 'scheme4://path4', 'metadata': {}}},
            {'op': 'remove', 'path': '/locations/2'},
            {'op': 'replace', 'path': '/locations', 'value': []},
            {'op': 'replace', 'path': '/locations',
             'value': [{'url': 'scheme5://path5', 'metadata': {}},
                       {'url': 'scheme6://path6', 'metadata': {}}]},
        ]
        request.body = jsonutils.dump_as_bytes(body)
        output = self.deserializer.update(request)
        expected = {'changes': [
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['name'], 'value': 'fedora'},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['tags'], 'value': ['king', 'kong']},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['foo'], 'value': 'bar'},
            {'json_schema_version': 10, 'op': 'add',
             'path': ['bebim'], 'value': 'bap'},
            {'json_schema_version': 10, 'op': 'remove',
             'path': ['sparks']},
            {'json_schema_version': 10, 'op': 'add',
             'path': ['locations', '-'],
             'value': {'url': 'scheme3://path3', 'metadata': {}}},
            {'json_schema_version': 10, 'op': 'add',
             'path': ['locations', '10'],
             'value': {'url': 'scheme4://path4', 'metadata': {}}},
            {'json_schema_version': 10, 'op': 'remove',
             'path': ['locations', '2']},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['locations'], 'value': []},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['locations'],
             'value': [{'url': 'scheme5://path5', 'metadata': {}},
                       {'url': 'scheme6://path6', 'metadata': {}}]},
        ]}
        self.assertEqual(expected, output)

    def test_update_v2_0_compatibility(self):
        request = self._get_fake_patch_request(content_type_minor_version=0)
        body = [
            {'replace': '/name', 'value': 'fedora'},
            {'replace': '/tags', 'value': ['king', 'kong']},
            {'replace': '/foo', 'value': 'bar'},
            {'add': '/bebim', 'value': 'bap'},
            {'remove': '/sparks'},
            {'add': '/locations/-', 'value': {'url': 'scheme3://path3',
                                              'metadata': {}}},
            {'add': '/locations/10', 'value': {'url': 'scheme4://path4',
                                               'metadata': {}}},
            {'remove': '/locations/2'},
            {'replace': '/locations', 'value': []},
            {'replace': '/locations',
             'value': [{'url': 'scheme5://path5', 'metadata': {}},
                       {'url': 'scheme6://path6', 'metadata': {}}]},
        ]
        request.body = jsonutils.dump_as_bytes(body)
        output = self.deserializer.update(request)
        expected = {'changes': [
            {'json_schema_version': 4, 'op': 'replace',
             'path': ['name'], 'value': 'fedora'},
            {'json_schema_version': 4, 'op': 'replace',
             'path': ['tags'], 'value': ['king', 'kong']},
            {'json_schema_version': 4, 'op': 'replace',
             'path': ['foo'], 'value': 'bar'},
            {'json_schema_version': 4, 'op': 'add',
             'path': ['bebim'], 'value': 'bap'},
            {'json_schema_version': 4, 'op': 'remove', 'path': ['sparks']},
            {'json_schema_version': 4, 'op': 'add',
             'path': ['locations', '-'],
             'value': {'url': 'scheme3://path3', 'metadata': {}}},
            {'json_schema_version': 4, 'op': 'add',
             'path': ['locations', '10'],
             'value': {'url': 'scheme4://path4', 'metadata': {}}},
            {'json_schema_version': 4, 'op': 'remove',
             'path': ['locations', '2']},
            {'json_schema_version': 4, 'op': 'replace',
             'path': ['locations'], 'value': []},
            {'json_schema_version': 4, 'op': 'replace', 'path': ['locations'],
             'value': [{'url': 'scheme5://path5', 'metadata': {}},
                       {'url': 'scheme6://path6', 'metadata': {}}]},
        ]}
        self.assertEqual(expected, output)

    def test_update_base_attributes(self):
        request = self._get_fake_patch_request()
        body = [
            {'op': 'replace', 'path': '/name', 'value': 'fedora'},
            {'op': 'replace', 'path': '/visibility', 'value': 'public'},
            {'op': 'replace', 'path': '/tags', 'value': ['king', 'kong']},
            {'op': 'replace', 'path': '/protected', 'value': True},
            {'op': 'replace', 'path': '/container_format', 'value': 'bare'},
            {'op': 'replace', 'path': '/disk_format', 'value': 'raw'},
            {'op': 'replace', 'path': '/min_ram', 'value': 128},
            {'op': 'replace', 'path': '/min_disk', 'value': 10},
            {'op': 'replace', 'path': '/locations', 'value': []},
            {'op': 'replace', 'path': '/locations',
             'value': [{'url': 'scheme5://path5', 'metadata': {}},
                       {'url': 'scheme6://path6', 'metadata': {}}]}
        ]
        request.body = jsonutils.dump_as_bytes(body)
        output = self.deserializer.update(request)
        expected = {'changes': [
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['name'], 'value': 'fedora'},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['visibility'], 'value': 'public'},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['tags'], 'value': ['king', 'kong']},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['protected'], 'value': True},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['container_format'], 'value': 'bare'},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['disk_format'], 'value': 'raw'},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['min_ram'], 'value': 128},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['min_disk'], 'value': 10},
            {'json_schema_version': 10, 'op': 'replace',
             'path': ['locations'], 'value': []},
            {'json_schema_version': 10, 'op': 'replace', 'path': ['locations'],
             'value': [{'url': 'scheme5://path5', 'metadata': {}},
                       {'url': 'scheme6://path6', 'metadata': {}}]}
        ]}
        self.assertEqual(expected, output)

    def test_update_disallowed_attributes(self):
        samples = {
            'direct_url': '/a/b/c/d',
            'self': '/e/f/g/h',
            'file': '/e/f/g/h/file',
            'schema': '/i/j/k',
        }

        for key, value in samples.items():
            request = self._get_fake_patch_request()
            body = [{'op': 'replace', 'path': '/%s' % key, 'value': value}]
            request.body = jsonutils.dump_as_bytes(body)
            try:
                self.deserializer.update(request)
            except webob.exc.HTTPForbidden:
                pass  # desired behavior
            else:
                self.fail("Updating %s did not result in HTTPForbidden" % key)

    def test_update_readonly_attributes(self):
        samples = {
            'id': '00000000-0000-0000-0000-000000000000',
            'status': 'active',
            'checksum': 'abcdefghijklmnopqrstuvwxyz012345',
            'size': 9001,
            'virtual_size': 9001,
            'created_at': ISOTIME,
            'updated_at': ISOTIME,
        }

        for key, value in samples.items():
            request = self._get_fake_patch_request()
            body = [{'op': 'replace', 'path': '/%s' % key, 'value': value}]
            request.body = jsonutils.dump_as_bytes(body)
            try:
                self.deserializer.update(request)
            except webob.exc.HTTPForbidden:
                pass  # desired behavior
            else:
                self.fail("Updating %s did not result in HTTPForbidden" % key)

    def test_update_reserved_attributes(self):
        samples = {
            'deleted': False,
            'deleted_at': ISOTIME,
        }

        for key, value in samples.items():
            request = self._get_fake_patch_request()
            body = [{'op': 'replace', 'path': '/%s' % key, 'value': value}]
            request.body = jsonutils.dump_as_bytes(body)
            try:
                self.deserializer.update(request)
            except webob.exc.HTTPForbidden:
                pass  # desired behavior
            else:
                self.fail("Updating %s did not result in HTTPForbidden" % key)

    def test_update_invalid_attributes(self):
        keys = [
            'noslash',
            '///twoslash',
            '/two/   /slash',
            '/      /      ',
            '/trailingslash/',
            '/lone~tilde',
            '/trailingtilde~'
        ]

        for key in keys:
            request = self._get_fake_patch_request()
            body = [{'op': 'replace', 'path': '%s' % key, 'value': 'dummy'}]
            request.body = jsonutils.dump_as_bytes(body)
            try:
                self.deserializer.update(request)
            except webob.exc.HTTPBadRequest:
                pass  # desired behavior
            else:
                self.fail("Updating %s did not result in HTTPBadRequest" % key)

    def test_update_pointer_encoding(self):
        samples = {
            '/keywith~1slash': [u'keywith/slash'],
            '/keywith~0tilde': [u'keywith~tilde'],
            '/tricky~01': [u'tricky~1'],
        }

        for encoded, decoded in samples.items():
            request = self._get_fake_patch_request()
            doc = [{'op': 'replace', 'path': '%s' % encoded, 'value': 'dummy'}]
            request.body = jsonutils.dump_as_bytes(doc)
            output = self.deserializer.update(request)
            self.assertEqual(decoded, output['changes'][0]['path'])

    def test_update_deep_limited_attributes(self):
        samples = {
            'locations/1/2': [],
        }

        for key, value in samples.items():
            request = self._get_fake_patch_request()
            body = [{'op': 'replace', 'path': '/%s' % key, 'value': value}]
            request.body = jsonutils.dump_as_bytes(body)
            try:
                self.deserializer.update(request)
            except webob.exc.HTTPBadRequest:
                pass  # desired behavior
            else:
                self.fail("Updating %s did not result in HTTPBadRequest" % key)

    def test_update_v2_1_missing_operations(self):
        request = self._get_fake_patch_request()
        body = [{'path': '/colburn', 'value': 'arcata'}]
        request.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.update, request)

    def test_update_v2_1_missing_value(self):
        request = self._get_fake_patch_request()
        body = [{'op': 'replace', 'path': '/colburn'}]
        request.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.update, request)

    def test_update_v2_1_missing_path(self):
        request = self._get_fake_patch_request()
        body = [{'op': 'replace', 'value': 'arcata'}]
        request.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.update, request)

    def test_update_v2_0_multiple_operations(self):
        request = self._get_fake_patch_request(content_type_minor_version=0)
        body = [{'replace': '/foo', 'add': '/bar', 'value': 'snore'}]
        request.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.update, request)

    def test_update_v2_0_missing_operations(self):
        request = self._get_fake_patch_request(content_type_minor_version=0)
        body = [{'value': 'arcata'}]
        request.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.update, request)

    def test_update_v2_0_missing_value(self):
        request = self._get_fake_patch_request(content_type_minor_version=0)
        body = [{'replace': '/colburn'}]
        request.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.update, request)

    def test_index(self):
        marker = str(uuid.uuid4())
        path = '/subjects?limit=1&marker=%s&member_status=pending' % marker
        request = unit_test_utils.get_fake_request(path)
        expected = {'limit': 1,
                    'marker': marker,
                    'sort_key': ['created_at'],
                    'sort_dir': ['desc'],
                    'member_status': 'pending',
                    'filters': {}}
        output = self.deserializer.index(request)
        self.assertEqual(expected, output)

    def test_index_with_filter(self):
        name = 'My Little Subject'
        path = '/subjects?name=%s' % name
        request = unit_test_utils.get_fake_request(path)
        output = self.deserializer.index(request)
        self.assertEqual(name, output['filters']['name'])

    def test_index_strip_params_from_filters(self):
        name = 'My Little Subject'
        path = '/subjects?name=%s' % name
        request = unit_test_utils.get_fake_request(path)
        output = self.deserializer.index(request)
        self.assertEqual(name, output['filters']['name'])
        self.assertEqual(1, len(output['filters']))

    def test_index_with_many_filter(self):
        name = 'My Little Subject'
        instance_id = str(uuid.uuid4())
        path = ('/subjects?name=%(name)s&id=%(instance_id)s' %
                {'name': name, 'instance_id': instance_id})
        request = unit_test_utils.get_fake_request(path)
        output = self.deserializer.index(request)
        self.assertEqual(name, output['filters']['name'])
        self.assertEqual(instance_id, output['filters']['id'])

    def test_index_with_filter_and_limit(self):
        name = 'My Little Subject'
        path = '/subjects?name=%s&limit=1' % name
        request = unit_test_utils.get_fake_request(path)
        output = self.deserializer.index(request)
        self.assertEqual(name, output['filters']['name'])
        self.assertEqual(1, output['limit'])

    def test_index_non_integer_limit(self):
        request = unit_test_utils.get_fake_request('/subjects?limit=blah')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_zero_limit(self):
        request = unit_test_utils.get_fake_request('/subjects?limit=0')
        expected = {'limit': 0,
                    'sort_key': ['created_at'],
                    'member_status': 'accepted',
                    'sort_dir': ['desc'],
                    'filters': {}}
        output = self.deserializer.index(request)
        self.assertEqual(expected, output)

    def test_index_negative_limit(self):
        request = unit_test_utils.get_fake_request('/subjects?limit=-1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_fraction(self):
        request = unit_test_utils.get_fake_request('/subjects?limit=1.1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_invalid_status(self):
        path = '/subjects?member_status=blah'
        request = unit_test_utils.get_fake_request(path)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_marker(self):
        marker = str(uuid.uuid4())
        path = '/subjects?marker=%s' % marker
        request = unit_test_utils.get_fake_request(path)
        output = self.deserializer.index(request)
        self.assertEqual(marker, output.get('marker'))

    def test_index_marker_not_specified(self):
        request = unit_test_utils.get_fake_request('/subjects')
        output = self.deserializer.index(request)
        self.assertNotIn('marker', output)

    def test_index_limit_not_specified(self):
        request = unit_test_utils.get_fake_request('/subjects')
        output = self.deserializer.index(request)
        self.assertNotIn('limit', output)

    def test_index_sort_key_id(self):
        request = unit_test_utils.get_fake_request('/subjects?sort_key=id')
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['id'],
            'sort_dir': ['desc'],
            'member_status': 'accepted',
            'filters': {}
        }
        self.assertEqual(expected, output)

    def test_index_multiple_sort_keys(self):
        request = unit_test_utils.get_fake_request('/subjects?'
                                                   'sort_key=name&'
                                                   'sort_key=size')
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['name', 'size'],
            'sort_dir': ['desc'],
            'member_status': 'accepted',
            'filters': {}
        }
        self.assertEqual(expected, output)

    def test_index_invalid_multiple_sort_keys(self):
        # blah is an invalid sort key
        request = unit_test_utils.get_fake_request('/subjects?'
                                                   'sort_key=name&'
                                                   'sort_key=blah')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_sort_dir_asc(self):
        request = unit_test_utils.get_fake_request('/subjects?sort_dir=asc')
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['created_at'],
            'sort_dir': ['asc'],
            'member_status': 'accepted',
            'filters': {}}
        self.assertEqual(expected, output)

    def test_index_multiple_sort_dirs(self):
        req_string = ('/subjects?sort_key=name&sort_dir=asc&'
                      'sort_key=id&sort_dir=desc')
        request = unit_test_utils.get_fake_request(req_string)
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['name', 'id'],
            'sort_dir': ['asc', 'desc'],
            'member_status': 'accepted',
            'filters': {}}
        self.assertEqual(expected, output)

    def test_index_new_sorting_syntax_single_key_default_dir(self):
        req_string = '/subjects?sort=name'
        request = unit_test_utils.get_fake_request(req_string)
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['name'],
            'sort_dir': ['desc'],
            'member_status': 'accepted',
            'filters': {}}
        self.assertEqual(expected, output)

    def test_index_new_sorting_syntax_single_key_desc_dir(self):
        req_string = '/subjects?sort=name:desc'
        request = unit_test_utils.get_fake_request(req_string)
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['name'],
            'sort_dir': ['desc'],
            'member_status': 'accepted',
            'filters': {}}
        self.assertEqual(expected, output)

    def test_index_new_sorting_syntax_multiple_keys_default_dir(self):
        req_string = '/subjects?sort=name,size'
        request = unit_test_utils.get_fake_request(req_string)
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['name', 'size'],
            'sort_dir': ['desc', 'desc'],
            'member_status': 'accepted',
            'filters': {}}
        self.assertEqual(expected, output)

    def test_index_new_sorting_syntax_multiple_keys_asc_dir(self):
        req_string = '/subjects?sort=name:asc,size:asc'
        request = unit_test_utils.get_fake_request(req_string)
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['name', 'size'],
            'sort_dir': ['asc', 'asc'],
            'member_status': 'accepted',
            'filters': {}}
        self.assertEqual(expected, output)

    def test_index_new_sorting_syntax_multiple_keys_different_dirs(self):
        req_string = '/subjects?sort=name:desc,size:asc'
        request = unit_test_utils.get_fake_request(req_string)
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['name', 'size'],
            'sort_dir': ['desc', 'asc'],
            'member_status': 'accepted',
            'filters': {}}
        self.assertEqual(expected, output)

    def test_index_new_sorting_syntax_multiple_keys_optional_dir(self):
        req_string = '/subjects?sort=name:asc,size'
        request = unit_test_utils.get_fake_request(req_string)
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['name', 'size'],
            'sort_dir': ['asc', 'desc'],
            'member_status': 'accepted',
            'filters': {}}
        self.assertEqual(expected, output)

        req_string = '/subjects?sort=name,size:asc'
        request = unit_test_utils.get_fake_request(req_string)
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['name', 'size'],
            'sort_dir': ['desc', 'asc'],
            'member_status': 'accepted',
            'filters': {}}
        self.assertEqual(expected, output)

        req_string = '/subjects?sort=name,id:asc,size'
        request = unit_test_utils.get_fake_request(req_string)
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['name', 'id', 'size'],
            'sort_dir': ['desc', 'asc', 'desc'],
            'member_status': 'accepted',
            'filters': {}}
        self.assertEqual(expected, output)

        req_string = '/subjects?sort=name:asc,id,size:asc'
        request = unit_test_utils.get_fake_request(req_string)
        output = self.deserializer.index(request)
        expected = {
            'sort_key': ['name', 'id', 'size'],
            'sort_dir': ['asc', 'desc', 'asc'],
            'member_status': 'accepted',
            'filters': {}}
        self.assertEqual(expected, output)

    def test_index_sort_wrong_sort_dirs_number(self):
        req_string = '/subjects?sort_key=name&sort_dir=asc&sort_dir=desc'
        request = unit_test_utils.get_fake_request(req_string)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_sort_dirs_fewer_than_keys(self):
        req_string = ('/subjects?sort_key=name&sort_dir=asc&sort_key=id&'
                      'sort_dir=asc&sort_key=created_at')
        request = unit_test_utils.get_fake_request(req_string)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_sort_wrong_sort_dirs_number_without_key(self):
        req_string = '/subjects?sort_dir=asc&sort_dir=desc'
        request = unit_test_utils.get_fake_request(req_string)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_sort_private_key(self):
        request = unit_test_utils.get_fake_request('/subjects?sort_key=min_ram')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_sort_key_invalid_value(self):
        # blah is an invalid sort key
        request = unit_test_utils.get_fake_request('/subjects?sort_key=blah')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_sort_dir_invalid_value(self):
        # foo is an invalid sort dir
        request = unit_test_utils.get_fake_request('/subjects?sort_dir=foo')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_new_sorting_syntax_invalid_request(self):
        # 'blah' is not a supported sorting key
        req_string = '/subjects?sort=blah'
        request = unit_test_utils.get_fake_request(req_string)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

        req_string = '/subjects?sort=name,blah'
        request = unit_test_utils.get_fake_request(req_string)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

        # 'foo' isn't a valid sort direction
        req_string = '/subjects?sort=name:foo'
        request = unit_test_utils.get_fake_request(req_string)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)
        # 'asc:desc' isn't a valid sort direction
        req_string = '/subjects?sort=name:asc:desc'
        request = unit_test_utils.get_fake_request(req_string)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_combined_sorting_syntax(self):
        req_string = '/subjects?sort_dir=name&sort=name'
        request = unit_test_utils.get_fake_request(req_string)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.index, request)

    def test_index_with_tag(self):
        path = '/subjects?tag=%s&tag=%s' % ('x86', '64bit')
        request = unit_test_utils.get_fake_request(path)
        output = self.deserializer.index(request)
        self.assertEqual(sorted(['x86', '64bit']),
                         sorted(output['filters']['tags']))


class TestSubjectsDeserializerWithExtendedSchema(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectsDeserializerWithExtendedSchema, self).setUp()
        self.config(allow_additional_subject_properties=False)
        custom_subject_properties = {
            'pants': {
                'type': 'string',
                'enum': ['on', 'off'],
            },
        }
        schema = subject.api.v2.subjects.get_schema(custom_subject_properties)
        self.deserializer = subject.api.v2.subjects.RequestDeserializer(schema)

    def test_create(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({
            'name': 'subject-1',
            'pants': 'on'
        })
        output = self.deserializer.create(request)
        expected = {
            'subject': {'name': 'subject-1'},
            'extra_properties': {'pants': 'on'},
            'tags': [],
        }
        self.assertEqual(expected, output)

    def test_create_bad_data(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({
            'name': 'subject-1',
            'pants': 'borked'
        })
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.create, request)

    def test_update(self):
        request = unit_test_utils.get_fake_request()
        request.content_type = 'application/openstack-subjects-v1.1-json-patch'
        doc = [{'op': 'add', 'path': '/pants', 'value': 'off'}]
        request.body = jsonutils.dump_as_bytes(doc)
        output = self.deserializer.update(request)
        expected = {'changes': [
            {'json_schema_version': 10, 'op': 'add',
             'path': ['pants'], 'value': 'off'},
        ]}
        self.assertEqual(expected, output)

    def test_update_bad_data(self):
        request = unit_test_utils.get_fake_request()
        request.content_type = 'application/openstack-subjects-v1.1-json-patch'
        doc = [{'op': 'add', 'path': '/pants', 'value': 'cutoffs'}]
        request.body = jsonutils.dump_as_bytes(doc)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.update,
                          request)


class TestSubjectsDeserializerWithAdditionalProperties(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectsDeserializerWithAdditionalProperties, self).setUp()
        self.config(allow_additional_subject_properties=True)
        self.deserializer = subject.api.v2.subjects.RequestDeserializer()

    def test_create(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({'foo': 'bar'})
        output = self.deserializer.create(request)
        expected = {'subject': {},
                    'extra_properties': {'foo': 'bar'},
                    'tags': []}
        self.assertEqual(expected, output)

    def test_create_with_numeric_property(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({'abc': 123})
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.create, request)

    def test_update_with_numeric_property(self):
        request = unit_test_utils.get_fake_request()
        request.content_type = 'application/openstack-subjects-v1.1-json-patch'
        doc = [{'op': 'add', 'path': '/foo', 'value': 123}]
        request.body = jsonutils.dump_as_bytes(doc)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.update, request)

    def test_create_with_list_property(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({'foo': ['bar']})
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.create, request)

    def test_update_with_list_property(self):
        request = unit_test_utils.get_fake_request()
        request.content_type = 'application/openstack-subjects-v1.1-json-patch'
        doc = [{'op': 'add', 'path': '/foo', 'value': ['bar', 'baz']}]
        request.body = jsonutils.dump_as_bytes(doc)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.update, request)

    def test_update(self):
        request = unit_test_utils.get_fake_request()
        request.content_type = 'application/openstack-subjects-v1.1-json-patch'
        doc = [{'op': 'add', 'path': '/foo', 'value': 'bar'}]
        request.body = jsonutils.dump_as_bytes(doc)
        output = self.deserializer.update(request)
        change = {
            'json_schema_version': 10, 'op': 'add',
            'path': ['foo'], 'value': 'bar'
        }
        self.assertEqual({'changes': [change]}, output)


class TestSubjectsDeserializerNoAdditionalProperties(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectsDeserializerNoAdditionalProperties, self).setUp()
        self.config(allow_additional_subject_properties=False)
        self.deserializer = subject.api.v2.subjects.RequestDeserializer()

    def test_create_with_additional_properties_disallowed(self):
        self.config(allow_additional_subject_properties=False)
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({'foo': 'bar'})
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.create, request)

    def test_update(self):
        request = unit_test_utils.get_fake_request()
        request.content_type = 'application/openstack-subjects-v1.1-json-patch'
        doc = [{'op': 'add', 'path': '/foo', 'value': 'bar'}]
        request.body = jsonutils.dump_as_bytes(doc)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.deserializer.update, request)


class TestSubjectsSerializer(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectsSerializer, self).setUp()
        self.serializer = subject.api.v2.subjects.ResponseSerializer()
        self.fixtures = [
            # NOTE(bcwaldon): This first fixture has every property defined
            _domain_fixture(UUID1, name='subject-1', size=1024,
                            virtual_size=3072, created_at=DATETIME,
                            updated_at=DATETIME, owner=TENANT1,
                            visibility='public', container_format='ami',
                            tags=['one', 'two'], disk_format='ami',
                            min_ram=128, min_disk=10,
                            checksum='ca425b88f047ce8ec45ee90e813ada91'),

            # NOTE(bcwaldon): This second fixture depends on default behavior
            # and sets most values to None
            _domain_fixture(UUID2, created_at=DATETIME, updated_at=DATETIME),
        ]

    def test_index(self):
        expected = {
            'subjects': [
                {
                    'id': UUID1,
                    'name': 'subject-1',
                    'status': 'queued',
                    'visibility': 'public',
                    'protected': False,
                    'tags': set(['one', 'two']),
                    'size': 1024,
                    'virtual_size': 3072,
                    'checksum': 'ca425b88f047ce8ec45ee90e813ada91',
                    'container_format': 'ami',
                    'disk_format': 'ami',
                    'min_ram': 128,
                    'min_disk': 10,
                    'created_at': ISOTIME,
                    'updated_at': ISOTIME,
                    'self': '/v1/subjects/%s' % UUID1,
                    'file': '/v1/subjects/%s/file' % UUID1,
                    'schema': '/v1/schemas/subject',
                    'owner': '6838eb7b-6ded-434a-882c-b344c77fe8df',
                },
                {
                    'id': UUID2,
                    'status': 'queued',
                    'visibility': 'private',
                    'protected': False,
                    'tags': set([]),
                    'created_at': ISOTIME,
                    'updated_at': ISOTIME,
                    'self': '/v1/subjects/%s' % UUID2,
                    'file': '/v1/subjects/%s/file' % UUID2,
                    'schema': '/v1/schemas/subject',
                    'size': None,
                    'name': None,
                    'owner': None,
                    'min_ram': None,
                    'min_disk': None,
                    'checksum': None,
                    'disk_format': None,
                    'virtual_size': None,
                    'container_format': None,

                },
            ],
            'first': '/v1/subjects',
            'schema': '/v1/schemas/subjects',
        }
        request = webob.Request.blank('/v1/subjects')
        response = webob.Response(request=request)
        result = {'subjects': self.fixtures}
        self.serializer.index(response, result)
        actual = jsonutils.loads(response.body)
        for subject in actual['subjects']:
            subject['tags'] = set(subject['tags'])
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)

    def test_index_next_marker(self):
        request = webob.Request.blank('/v1/subjects')
        response = webob.Response(request=request)
        result = {'subjects': self.fixtures, 'next_marker': UUID2}
        self.serializer.index(response, result)
        output = jsonutils.loads(response.body)
        self.assertEqual('/v1/subjects?marker=%s' % UUID2, output['next'])

    def test_index_carries_query_parameters(self):
        url = '/v1/subjects?limit=10&sort_key=id&sort_dir=asc'
        request = webob.Request.blank(url)
        response = webob.Response(request=request)
        result = {'subjects': self.fixtures, 'next_marker': UUID2}
        self.serializer.index(response, result)
        output = jsonutils.loads(response.body)

        expected_url = '/v1/subjects?limit=10&sort_dir=asc&sort_key=id'
        self.assertEqual(unit_test_utils.sort_url_by_qs_keys(expected_url),
                         unit_test_utils.sort_url_by_qs_keys(output['first']))
        expect_next = '/v1/subjects?limit=10&marker=%s&sort_dir=asc&sort_key=id'
        self.assertEqual(unit_test_utils.sort_url_by_qs_keys(
                         expect_next % UUID2),
                         unit_test_utils.sort_url_by_qs_keys(output['next']))

    def test_index_forbidden_get_subject_location(self):
        """Make sure the serializer works fine.

        No mater if current user is authorized to get subject location if the
        show_multiple_locations is False.

        """
        class SubjectLocations(object):
            def __len__(self):
                raise exception.Forbidden()

        self.config(show_multiple_locations=False)
        self.config(show_subject_direct_url=False)
        url = '/v1/subjects?limit=10&sort_key=id&sort_dir=asc'
        request = webob.Request.blank(url)
        response = webob.Response(request=request)
        result = {'subjects': self.fixtures}
        self.assertEqual(200, response.status_int)

        # The subject index should work though the user is forbidden
        result['subjects'][0].locations = SubjectLocations()
        self.serializer.index(response, result)
        self.assertEqual(200, response.status_int)

    def test_show_full_fixture(self):
        expected = {
            'id': UUID1,
            'name': 'subject-1',
            'status': 'queued',
            'visibility': 'public',
            'protected': False,
            'tags': set(['one', 'two']),
            'size': 1024,
            'virtual_size': 3072,
            'checksum': 'ca425b88f047ce8ec45ee90e813ada91',
            'container_format': 'ami',
            'disk_format': 'ami',
            'min_ram': 128,
            'min_disk': 10,
            'created_at': ISOTIME,
            'updated_at': ISOTIME,
            'self': '/v1/subjects/%s' % UUID1,
            'file': '/v1/subjects/%s/file' % UUID1,
            'schema': '/v1/schemas/subject',
            'owner': '6838eb7b-6ded-434a-882c-b344c77fe8df',
        }
        response = webob.Response()
        self.serializer.show(response, self.fixtures[0])
        actual = jsonutils.loads(response.body)
        actual['tags'] = set(actual['tags'])
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)

    def test_show_minimal_fixture(self):
        expected = {
            'id': UUID2,
            'status': 'queued',
            'visibility': 'private',
            'protected': False,
            'tags': [],
            'created_at': ISOTIME,
            'updated_at': ISOTIME,
            'self': '/v1/subjects/%s' % UUID2,
            'file': '/v1/subjects/%s/file' % UUID2,
            'schema': '/v1/schemas/subject',
            'size': None,
            'name': None,
            'owner': None,
            'min_ram': None,
            'min_disk': None,
            'checksum': None,
            'disk_format': None,
            'virtual_size': None,
            'container_format': None,
        }
        response = webob.Response()
        self.serializer.show(response, self.fixtures[1])
        self.assertEqual(expected, jsonutils.loads(response.body))

    def test_create(self):
        expected = {
            'id': UUID1,
            'name': 'subject-1',
            'status': 'queued',
            'visibility': 'public',
            'protected': False,
            'tags': ['one', 'two'],
            'size': 1024,
            'virtual_size': 3072,
            'checksum': 'ca425b88f047ce8ec45ee90e813ada91',
            'container_format': 'ami',
            'disk_format': 'ami',
            'min_ram': 128,
            'min_disk': 10,
            'created_at': ISOTIME,
            'updated_at': ISOTIME,
            'self': '/v1/subjects/%s' % UUID1,
            'file': '/v1/subjects/%s/file' % UUID1,
            'schema': '/v1/schemas/subject',
            'owner': '6838eb7b-6ded-434a-882c-b344c77fe8df',
        }
        response = webob.Response()
        self.serializer.create(response, self.fixtures[0])
        self.assertEqual(201, response.status_int)
        actual = jsonutils.loads(response.body)
        actual['tags'] = sorted(actual['tags'])
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual('/v1/subjects/%s' % UUID1, response.location)

    def test_update(self):
        expected = {
            'id': UUID1,
            'name': 'subject-1',
            'status': 'queued',
            'visibility': 'public',
            'protected': False,
            'tags': set(['one', 'two']),
            'size': 1024,
            'virtual_size': 3072,
            'checksum': 'ca425b88f047ce8ec45ee90e813ada91',
            'container_format': 'ami',
            'disk_format': 'ami',
            'min_ram': 128,
            'min_disk': 10,
            'created_at': ISOTIME,
            'updated_at': ISOTIME,
            'self': '/v1/subjects/%s' % UUID1,
            'file': '/v1/subjects/%s/file' % UUID1,
            'schema': '/v1/schemas/subject',
            'owner': '6838eb7b-6ded-434a-882c-b344c77fe8df',
        }
        response = webob.Response()
        self.serializer.update(response, self.fixtures[0])
        actual = jsonutils.loads(response.body)
        actual['tags'] = set(actual['tags'])
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)


class TestSubjectsSerializerWithUnicode(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectsSerializerWithUnicode, self).setUp()
        self.serializer = subject.api.v2.subjects.ResponseSerializer()
        self.fixtures = [
            # NOTE(bcwaldon): This first fixture has every property defined
            _domain_fixture(UUID1, **{
                'name': u'OpenStack\u2122-1',
                'size': 1024,
                'virtual_size': 3072,
                'tags': [u'\u2160', u'\u2161'],
                'created_at': DATETIME,
                'updated_at': DATETIME,
                'owner': TENANT1,
                'visibility': 'public',
                'container_format': 'ami',
                'disk_format': 'ami',
                'min_ram': 128,
                'min_disk': 10,
                'checksum': u'ca425b88f047ce8ec45ee90e813ada91',
                'extra_properties': {'lang': u'Fran\u00E7ais',
                                     u'dispos\u00E9': u'f\u00E2ch\u00E9'},
            }),
        ]

    def test_index(self):
        expected = {
            u'subjects': [
                {
                    u'id': UUID1,
                    u'name': u'OpenStack\u2122-1',
                    u'status': u'queued',
                    u'visibility': u'public',
                    u'protected': False,
                    u'tags': [u'\u2160', u'\u2161'],
                    u'size': 1024,
                    u'virtual_size': 3072,
                    u'checksum': u'ca425b88f047ce8ec45ee90e813ada91',
                    u'container_format': u'ami',
                    u'disk_format': u'ami',
                    u'min_ram': 128,
                    u'min_disk': 10,
                    u'created_at': six.text_type(ISOTIME),
                    u'updated_at': six.text_type(ISOTIME),
                    u'self': u'/v1/subjects/%s' % UUID1,
                    u'file': u'/v1/subjects/%s/file' % UUID1,
                    u'schema': u'/v1/schemas/subject',
                    u'lang': u'Fran\u00E7ais',
                    u'dispos\u00E9': u'f\u00E2ch\u00E9',
                    u'owner': u'6838eb7b-6ded-434a-882c-b344c77fe8df',
                },
            ],
            u'first': u'/v1/subjects',
            u'schema': u'/v1/schemas/subjects',
        }
        request = webob.Request.blank('/v1/subjects')
        response = webob.Response(request=request)
        result = {u'subjects': self.fixtures}
        self.serializer.index(response, result)
        actual = jsonutils.loads(response.body)
        actual['subjects'][0]['tags'] = sorted(actual['subjects'][0]['tags'])
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)

    def test_show_full_fixture(self):
        expected = {
            u'id': UUID1,
            u'name': u'OpenStack\u2122-1',
            u'status': u'queued',
            u'visibility': u'public',
            u'protected': False,
            u'tags': set([u'\u2160', u'\u2161']),
            u'size': 1024,
            u'virtual_size': 3072,
            u'checksum': u'ca425b88f047ce8ec45ee90e813ada91',
            u'container_format': u'ami',
            u'disk_format': u'ami',
            u'min_ram': 128,
            u'min_disk': 10,
            u'created_at': six.text_type(ISOTIME),
            u'updated_at': six.text_type(ISOTIME),
            u'self': u'/v1/subjects/%s' % UUID1,
            u'file': u'/v1/subjects/%s/file' % UUID1,
            u'schema': u'/v1/schemas/subject',
            u'lang': u'Fran\u00E7ais',
            u'dispos\u00E9': u'f\u00E2ch\u00E9',
            u'owner': u'6838eb7b-6ded-434a-882c-b344c77fe8df',
        }
        response = webob.Response()
        self.serializer.show(response, self.fixtures[0])
        actual = jsonutils.loads(response.body)
        actual['tags'] = set(actual['tags'])
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)

    def test_create(self):
        expected = {
            u'id': UUID1,
            u'name': u'OpenStack\u2122-1',
            u'status': u'queued',
            u'visibility': u'public',
            u'protected': False,
            u'tags': [u'\u2160', u'\u2161'],
            u'size': 1024,
            u'virtual_size': 3072,
            u'checksum': u'ca425b88f047ce8ec45ee90e813ada91',
            u'container_format': u'ami',
            u'disk_format': u'ami',
            u'min_ram': 128,
            u'min_disk': 10,
            u'created_at': six.text_type(ISOTIME),
            u'updated_at': six.text_type(ISOTIME),
            u'self': u'/v1/subjects/%s' % UUID1,
            u'file': u'/v1/subjects/%s/file' % UUID1,
            u'schema': u'/v1/schemas/subject',
            u'lang': u'Fran\u00E7ais',
            u'dispos\u00E9': u'f\u00E2ch\u00E9',
            u'owner': u'6838eb7b-6ded-434a-882c-b344c77fe8df',
        }
        response = webob.Response()
        self.serializer.create(response, self.fixtures[0])
        self.assertEqual(201, response.status_int)
        actual = jsonutils.loads(response.body)
        actual['tags'] = sorted(actual['tags'])
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual('/v1/subjects/%s' % UUID1, response.location)

    def test_update(self):
        expected = {
            u'id': UUID1,
            u'name': u'OpenStack\u2122-1',
            u'status': u'queued',
            u'visibility': u'public',
            u'protected': False,
            u'tags': set([u'\u2160', u'\u2161']),
            u'size': 1024,
            u'virtual_size': 3072,
            u'checksum': u'ca425b88f047ce8ec45ee90e813ada91',
            u'container_format': u'ami',
            u'disk_format': u'ami',
            u'min_ram': 128,
            u'min_disk': 10,
            u'created_at': six.text_type(ISOTIME),
            u'updated_at': six.text_type(ISOTIME),
            u'self': u'/v1/subjects/%s' % UUID1,
            u'file': u'/v1/subjects/%s/file' % UUID1,
            u'schema': u'/v1/schemas/subject',
            u'lang': u'Fran\u00E7ais',
            u'dispos\u00E9': u'f\u00E2ch\u00E9',
            u'owner': u'6838eb7b-6ded-434a-882c-b344c77fe8df',
        }
        response = webob.Response()
        self.serializer.update(response, self.fixtures[0])
        actual = jsonutils.loads(response.body)
        actual['tags'] = set(actual['tags'])
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)


class TestSubjectsSerializerWithExtendedSchema(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectsSerializerWithExtendedSchema, self).setUp()
        self.config(allow_additional_subject_properties=False)
        custom_subject_properties = {
            'color': {
                'type': 'string',
                'enum': ['red', 'green'],
            },
        }
        schema = subject.api.v2.subjects.get_schema(custom_subject_properties)
        self.serializer = subject.api.v2.subjects.ResponseSerializer(schema)

        props = dict(color='green', mood='grouchy')
        self.fixture = _domain_fixture(
            UUID2, name='subject-2', owner=TENANT2,
            checksum='ca425b88f047ce8ec45ee90e813ada91',
            created_at=DATETIME, updated_at=DATETIME, size=1024,
            virtual_size=3072, extra_properties=props)

    def test_show(self):
        expected = {
            'id': UUID2,
            'name': 'subject-2',
            'status': 'queued',
            'visibility': 'private',
            'protected': False,
            'checksum': 'ca425b88f047ce8ec45ee90e813ada91',
            'tags': [],
            'size': 1024,
            'virtual_size': 3072,
            'owner': '2c014f32-55eb-467d-8fcb-4bd706012f81',
            'color': 'green',
            'created_at': ISOTIME,
            'updated_at': ISOTIME,
            'self': '/v1/subjects/%s' % UUID2,
            'file': '/v1/subjects/%s/file' % UUID2,
            'schema': '/v1/schemas/subject',
            'min_ram': None,
            'min_disk': None,
            'disk_format': None,
            'container_format': None,
        }
        response = webob.Response()
        self.serializer.show(response, self.fixture)
        self.assertEqual(expected, jsonutils.loads(response.body))

    def test_show_reports_invalid_data(self):
        self.fixture.extra_properties['color'] = 'invalid'
        expected = {
            'id': UUID2,
            'name': 'subject-2',
            'status': 'queued',
            'visibility': 'private',
            'protected': False,
            'checksum': 'ca425b88f047ce8ec45ee90e813ada91',
            'tags': [],
            'size': 1024,
            'virtual_size': 3072,
            'owner': '2c014f32-55eb-467d-8fcb-4bd706012f81',
            'color': 'invalid',
            'created_at': ISOTIME,
            'updated_at': ISOTIME,
            'self': '/v1/subjects/%s' % UUID2,
            'file': '/v1/subjects/%s/file' % UUID2,
            'schema': '/v1/schemas/subject',
            'min_ram': None,
            'min_disk': None,
            'disk_format': None,
            'container_format': None,
        }
        response = webob.Response()
        self.serializer.show(response, self.fixture)
        self.assertEqual(expected, jsonutils.loads(response.body))


class TestSubjectsSerializerWithAdditionalProperties(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectsSerializerWithAdditionalProperties, self).setUp()
        self.config(allow_additional_subject_properties=True)
        self.fixture = _domain_fixture(
            UUID2, name='subject-2', owner=TENANT2,
            checksum='ca425b88f047ce8ec45ee90e813ada91',
            created_at=DATETIME, updated_at=DATETIME, size=1024,
            virtual_size=3072, extra_properties={'marx': 'groucho'})

    def test_show(self):
        serializer = subject.api.v2.subjects.ResponseSerializer()
        expected = {
            'id': UUID2,
            'name': 'subject-2',
            'status': 'queued',
            'visibility': 'private',
            'protected': False,
            'checksum': 'ca425b88f047ce8ec45ee90e813ada91',
            'marx': 'groucho',
            'tags': [],
            'size': 1024,
            'virtual_size': 3072,
            'created_at': ISOTIME,
            'updated_at': ISOTIME,
            'self': '/v1/subjects/%s' % UUID2,
            'file': '/v1/subjects/%s/file' % UUID2,
            'schema': '/v1/schemas/subject',
            'owner': '2c014f32-55eb-467d-8fcb-4bd706012f81',
            'min_ram': None,
            'min_disk': None,
            'disk_format': None,
            'container_format': None,
        }
        response = webob.Response()
        serializer.show(response, self.fixture)
        self.assertEqual(expected, jsonutils.loads(response.body))

    def test_show_invalid_additional_property(self):
        """Ensure that the serializer passes
        through invalid additional properties.

        It must not complains with i.e. non-string.
        """
        serializer = subject.api.v2.subjects.ResponseSerializer()
        self.fixture.extra_properties['marx'] = 123
        expected = {
            'id': UUID2,
            'name': 'subject-2',
            'status': 'queued',
            'visibility': 'private',
            'protected': False,
            'checksum': 'ca425b88f047ce8ec45ee90e813ada91',
            'marx': 123,
            'tags': [],
            'size': 1024,
            'virtual_size': 3072,
            'created_at': ISOTIME,
            'updated_at': ISOTIME,
            'self': '/v1/subjects/%s' % UUID2,
            'file': '/v1/subjects/%s/file' % UUID2,
            'schema': '/v1/schemas/subject',
            'owner': '2c014f32-55eb-467d-8fcb-4bd706012f81',
            'min_ram': None,
            'min_disk': None,
            'disk_format': None,
            'container_format': None,
        }
        response = webob.Response()
        serializer.show(response, self.fixture)
        self.assertEqual(expected, jsonutils.loads(response.body))

    def test_show_with_additional_properties_disabled(self):
        self.config(allow_additional_subject_properties=False)
        serializer = subject.api.v2.subjects.ResponseSerializer()
        expected = {
            'id': UUID2,
            'name': 'subject-2',
            'status': 'queued',
            'visibility': 'private',
            'protected': False,
            'checksum': 'ca425b88f047ce8ec45ee90e813ada91',
            'tags': [],
            'size': 1024,
            'virtual_size': 3072,
            'owner': '2c014f32-55eb-467d-8fcb-4bd706012f81',
            'created_at': ISOTIME,
            'updated_at': ISOTIME,
            'self': '/v1/subjects/%s' % UUID2,
            'file': '/v1/subjects/%s/file' % UUID2,
            'schema': '/v1/schemas/subject',
            'min_ram': None,
            'min_disk': None,
            'disk_format': None,
            'container_format': None,
        }
        response = webob.Response()
        serializer.show(response, self.fixture)
        self.assertEqual(expected, jsonutils.loads(response.body))


class TestSubjectsSerializerDirectUrl(test_utils.BaseTestCase):
    def setUp(self):
        super(TestSubjectsSerializerDirectUrl, self).setUp()
        self.serializer = subject.api.v2.subjects.ResponseSerializer()

        self.active_subject = _domain_fixture(
            UUID1, name='subject-1', visibility='public',
            status='active', size=1024, virtual_size=3072,
            created_at=DATETIME, updated_at=DATETIME,
            locations=[{'id': '1', 'url': 'http://some/fake/location',
                        'metadata': {}, 'status': 'active'}])

        self.queued_subject = _domain_fixture(
            UUID2, name='subject-2', status='active',
            created_at=DATETIME, updated_at=DATETIME,
            checksum='ca425b88f047ce8ec45ee90e813ada91')

        self.location_data_subject_url = 'http://abc.com/somewhere'
        self.location_data_subject_meta = {'key': 98231}
        self.location_data_subject = _domain_fixture(
            UUID2, name='subject-2', status='active',
            created_at=DATETIME, updated_at=DATETIME,
            locations=[{'id': '2',
                        'url': self.location_data_subject_url,
                        'metadata': self.location_data_subject_meta,
                        'status': 'active'}])

    def _do_index(self):
        request = webob.Request.blank('/v1/subjects')
        response = webob.Response(request=request)
        self.serializer.index(response,
                              {'subjects': [self.active_subject,
                                          self.queued_subject]})
        return jsonutils.loads(response.body)['subjects']

    def _do_show(self, subject):
        request = webob.Request.blank('/v1/subjects')
        response = webob.Response(request=request)
        self.serializer.show(response, subject)
        return jsonutils.loads(response.body)

    def test_index_store_location_enabled(self):
        self.config(show_subject_direct_url=True)
        subjects = self._do_index()

        # NOTE(markwash): ordering sanity check
        self.assertEqual(UUID1, subjects[0]['id'])
        self.assertEqual(UUID2, subjects[1]['id'])

        self.assertEqual('http://some/fake/location', subjects[0]['direct_url'])
        self.assertNotIn('direct_url', subjects[1])

    def test_index_store_multiple_location_enabled(self):
        self.config(show_multiple_locations=True)
        request = webob.Request.blank('/v1/subjects')
        response = webob.Response(request=request)
        self.serializer.index(response,
                              {'subjects': [self.location_data_subject]}),
        subjects = jsonutils.loads(response.body)['subjects']
        location = subjects[0]['locations'][0]
        self.assertEqual(location['url'], self.location_data_subject_url)
        self.assertEqual(location['metadata'], self.location_data_subject_meta)

    def test_index_store_location_explicitly_disabled(self):
        self.config(show_subject_direct_url=False)
        subjects = self._do_index()
        self.assertNotIn('direct_url', subjects[0])
        self.assertNotIn('direct_url', subjects[1])

    def test_show_location_enabled(self):
        self.config(show_subject_direct_url=True)
        subject = self._do_show(self.active_subject)
        self.assertEqual('http://some/fake/location', subject['direct_url'])

    def test_show_location_enabled_but_not_set(self):
        self.config(show_subject_direct_url=True)
        subject = self._do_show(self.queued_subject)
        self.assertNotIn('direct_url', subject)

    def test_show_location_explicitly_disabled(self):
        self.config(show_subject_direct_url=False)
        subject = self._do_show(self.active_subject)
        self.assertNotIn('direct_url', subject)


class TestSubjectSchemaFormatConfiguration(test_utils.BaseTestCase):
    def test_default_disk_formats(self):
        schema = subject.api.v2.subjects.get_schema()
        expected = [None, 'ami', 'ari', 'aki', 'vhd', 'vhdx', 'vmdk',
                    'raw', 'qcow2', 'vdi', 'iso']
        actual = schema.properties['disk_format']['enum']
        self.assertEqual(expected, actual)

    def test_custom_disk_formats(self):
        self.config(disk_formats=['gabe'], group="subject_format")
        schema = subject.api.v2.subjects.get_schema()
        expected = [None, 'gabe']
        actual = schema.properties['disk_format']['enum']
        self.assertEqual(expected, actual)

    def test_default_container_formats(self):
        schema = subject.api.v2.subjects.get_schema()
        expected = [None, 'ami', 'ari', 'aki', 'bare', 'ovf', 'ova', 'docker']
        actual = schema.properties['container_format']['enum']
        self.assertEqual(expected, actual)

    def test_custom_container_formats(self):
        self.config(container_formats=['mark'], group="subject_format")
        schema = subject.api.v2.subjects.get_schema()
        expected = [None, 'mark']
        actual = schema.properties['container_format']['enum']
        self.assertEqual(expected, actual)


class TestSubjectSchemaDeterminePropertyBasis(test_utils.BaseTestCase):
    def test_custom_property_marked_as_non_base(self):
        self.config(allow_additional_subject_properties=False)
        custom_subject_properties = {
            'pants': {
                'type': 'string',
            },
        }
        schema = subject.api.v2.subjects.get_schema(custom_subject_properties)
        self.assertFalse(schema.properties['pants'].get('is_base', True))

    def test_base_property_marked_as_base(self):
        schema = subject.api.v2.subjects.get_schema()
        self.assertTrue(schema.properties['disk_format'].get('is_base', True))
