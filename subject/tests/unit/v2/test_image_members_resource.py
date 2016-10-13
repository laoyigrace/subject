# Copyright 2013 OpenStack Foundation
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

import glance_store
from oslo_config import cfg
from oslo_serialization import jsonutils
import webob

import subject.api.v2.subject_members
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
UUID5 = '3eee7cc2-eae7-4c0f-b50d-a7160b0c62ed'

TENANT1 = '6838eb7b-6ded-434a-882c-b344c77fe8df'
TENANT2 = '2c014f32-55eb-467d-8fcb-4bd706012f81'
TENANT3 = '5a3e60e8-cfa9-4a9e-a90a-62b42cea92b8'
TENANT4 = 'c6c87f25-8a94-47ed-8c83-053c25f42df4'


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


def _db_subject_member_fixture(subject_id, member_id, **kwargs):
    obj = {
        'subject_id': subject_id,
        'member': member_id,
        'status': 'pending',
    }
    obj.update(kwargs)
    return obj


def _domain_fixture(id, **kwargs):
    properties = {
        'id': id,
    }
    properties.update(kwargs)
    return subject.domain.SubjectMembership(**properties)


class TestSubjectMembersController(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectMembersController, self).setUp()
        self.db = unit_test_utils.FakeDB(initialize=False)
        self.store = unit_test_utils.FakeStoreAPI()
        self.policy = unit_test_utils.FakePolicyEnforcer()
        self.notifier = unit_test_utils.FakeNotifier()
        self._create_subjects()
        self._create_subject_members()
        self.controller = subject.api.v2.subject_members.SubjectMembersController(
            self.db,
            self.policy,
            self.notifier,
            self.store)
        glance_store.register_opts(CONF)

        self.config(default_store='filesystem',
                    filesystem_store_datadir=self.test_dir,
                    group="glance_store")

        glance_store.create_stores()

    def _create_subjects(self):
        self.subjects = [
            _db_fixture(UUID1, owner=TENANT1, name='1', size=256,
                        is_public=True,
                        locations=[{'url': '%s/%s' % (BASE_URI, UUID1),
                                    'metadata': {}, 'status': 'active'}]),
            _db_fixture(UUID2, owner=TENANT1, name='2', size=512),
            _db_fixture(UUID3, owner=TENANT3, name='3', size=512),
            _db_fixture(UUID4, owner=TENANT4, name='4', size=1024),
            _db_fixture(UUID5, owner=TENANT1, name='5', size=1024),
        ]
        [self.db.subject_create(None, subject) for subject in self.subjects]

        self.db.subject_tag_set_all(None, UUID1, ['ping', 'pong'])

    def _create_subject_members(self):
        self.subject_members = [
            _db_subject_member_fixture(UUID2, TENANT4),
            _db_subject_member_fixture(UUID3, TENANT4),
            _db_subject_member_fixture(UUID3, TENANT2),
            _db_subject_member_fixture(UUID4, TENANT1),
        ]
        [self.db.subject_member_create(None, subject_member)
            for subject_member in self.subject_members]

    def test_index(self):
        request = unit_test_utils.get_fake_request()
        output = self.controller.index(request, UUID2)
        self.assertEqual(1, len(output['members']))
        actual = set([subject_member.member_id
                      for subject_member in output['members']])
        expected = set([TENANT4])
        self.assertEqual(expected, actual)

    def test_index_no_members(self):
        request = unit_test_utils.get_fake_request()
        output = self.controller.index(request, UUID5)
        self.assertEqual(0, len(output['members']))
        self.assertEqual({'members': []}, output)

    def test_index_member_view(self):
        # UUID3 is a private subject owned by TENANT3
        # UUID3 has members TENANT2 and TENANT4
        # When TENANT4 lists members for UUID3, should not see TENANT2
        request = unit_test_utils.get_fake_request(tenant=TENANT4)
        output = self.controller.index(request, UUID3)
        self.assertEqual(1, len(output['members']))
        actual = set([subject_member.member_id
                      for subject_member in output['members']])
        expected = set([TENANT4])
        self.assertEqual(expected, actual)

    def test_index_private_subject(self):
        request = unit_test_utils.get_fake_request(tenant=TENANT2)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.index,
                          request, UUID5)

    def test_index_public_subject(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.index,
                          request, UUID1)

    def test_index_private_subject_visible_members_admin(self):
        request = unit_test_utils.get_fake_request(is_admin=True)
        output = self.controller.index(request, UUID4)
        self.assertEqual(1, len(output['members']))
        actual = set([subject_member.member_id
                      for subject_member in output['members']])
        expected = set([TENANT1])
        self.assertEqual(expected, actual)

    def test_index_allowed_by_get_members_policy(self):
        rules = {"get_members": True}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        output = self.controller.index(request, UUID2)
        self.assertEqual(1, len(output['members']))

    def test_index_forbidden_by_get_members_policy(self):
        rules = {"get_members": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.index,
                          request, subject_id=UUID2)

    def test_show(self):
        request = unit_test_utils.get_fake_request(tenant=TENANT1)
        output = self.controller.show(request, UUID2, TENANT4)
        expected = self.subject_members[0]
        self.assertEqual(expected['subject_id'], output.subject_id)
        self.assertEqual(expected['member'], output.member_id)
        self.assertEqual(expected['status'], output.status)

    def test_show_by_member(self):
        request = unit_test_utils.get_fake_request(tenant=TENANT4)
        output = self.controller.show(request, UUID2, TENANT4)
        expected = self.subject_members[0]
        self.assertEqual(expected['subject_id'], output.subject_id)
        self.assertEqual(expected['member'], output.member_id)
        self.assertEqual(expected['status'], output.status)

    def test_show_forbidden(self):
        request = unit_test_utils.get_fake_request(tenant=TENANT2)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          request, UUID2, TENANT4)

    def test_show_not_found(self):
        # one member should not be able to view status of another member
        # of the same subject
        request = unit_test_utils.get_fake_request(tenant=TENANT2)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          request, UUID3, TENANT4)

    def test_create(self):
        request = unit_test_utils.get_fake_request()
        subject_id = UUID2
        member_id = TENANT3
        output = self.controller.create(request, subject_id=subject_id,
                                        member_id=member_id)
        self.assertEqual(UUID2, output.subject_id)
        self.assertEqual(TENANT3, output.member_id)

    def test_create_allowed_by_add_policy(self):
        rules = {"add_member": True}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        output = self.controller.create(request, subject_id=UUID2,
                                        member_id=TENANT3)
        self.assertEqual(UUID2, output.subject_id)
        self.assertEqual(TENANT3, output.member_id)

    def test_create_forbidden_by_add_policy(self):
        rules = {"add_member": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.create,
                          request, subject_id=UUID2, member_id=TENANT3)

    def test_create_duplicate_member(self):
        request = unit_test_utils.get_fake_request()
        subject_id = UUID2
        member_id = TENANT3
        output = self.controller.create(request, subject_id=subject_id,
                                        member_id=member_id)
        self.assertEqual(UUID2, output.subject_id)
        self.assertEqual(TENANT3, output.member_id)

        self.assertRaises(webob.exc.HTTPConflict, self.controller.create,
                          request, subject_id=subject_id, member_id=member_id)

    def test_create_overlimit(self):
        self.config(subject_member_quota=0)
        request = unit_test_utils.get_fake_request()
        subject_id = UUID2
        member_id = TENANT3
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, request,
                          subject_id=subject_id, member_id=member_id)

    def test_create_unlimited(self):
        self.config(subject_member_quota=-1)
        request = unit_test_utils.get_fake_request()
        subject_id = UUID2
        member_id = TENANT3
        output = self.controller.create(request, subject_id=subject_id,
                                        member_id=member_id)
        self.assertEqual(UUID2, output.subject_id)
        self.assertEqual(TENANT3, output.member_id)

    def test_update_done_by_member(self):
        request = unit_test_utils.get_fake_request(tenant=TENANT4)
        subject_id = UUID2
        member_id = TENANT4
        output = self.controller.update(request, subject_id=subject_id,
                                        member_id=member_id,
                                        status='accepted')
        self.assertEqual(UUID2, output.subject_id)
        self.assertEqual(TENANT4, output.member_id)
        self.assertEqual('accepted', output.status)

    def test_update_done_by_member_forbidden_by_policy(self):
        rules = {"modify_member": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request(tenant=TENANT4)
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          request, subject_id=UUID2, member_id=TENANT4,
                          status='accepted')

    def test_update_done_by_member_allowed_by_policy(self):
        rules = {"modify_member": True}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request(tenant=TENANT4)
        output = self.controller.update(request, subject_id=UUID2,
                                        member_id=TENANT4,
                                        status='accepted')
        self.assertEqual(UUID2, output.subject_id)
        self.assertEqual(TENANT4, output.member_id)
        self.assertEqual('accepted', output.status)

    def test_update_done_by_owner(self):
        request = unit_test_utils.get_fake_request(tenant=TENANT1)
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          request, UUID2, TENANT4, status='accepted')

    def test_update_non_existent_subject(self):
        request = unit_test_utils.get_fake_request(tenant=TENANT1)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          request, '123', TENANT4, status='accepted')

    def test_update_invalid_status(self):
        request = unit_test_utils.get_fake_request(tenant=TENANT4)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          request, UUID2, TENANT4, status='accept')

    def test_create_private_subject(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.create,
                          request, UUID4, TENANT2)

    def test_create_public_subject(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.create,
                          request, UUID1, TENANT2)

    def test_create_subject_does_not_exist(self):
        request = unit_test_utils.get_fake_request()
        subject_id = 'fake-subject-id'
        member_id = TENANT3
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          request, subject_id=subject_id, member_id=member_id)

    def test_delete(self):
        request = unit_test_utils.get_fake_request()
        member_id = TENANT4
        subject_id = UUID2
        res = self.controller.delete(request, subject_id, member_id)
        self.assertEqual(b'', res.body)
        self.assertEqual(204, res.status_code)
        found_member = self.db.subject_member_find(
            request.context, subject_id=subject_id, member=member_id)
        self.assertEqual([], found_member)

    def test_delete_by_member(self):
        request = unit_test_utils.get_fake_request(tenant=TENANT4)
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          request, UUID2, TENANT4)
        request = unit_test_utils.get_fake_request()
        output = self.controller.index(request, UUID2)
        self.assertEqual(1, len(output['members']))
        actual = set([subject_member.member_id
                      for subject_member in output['members']])
        expected = set([TENANT4])
        self.assertEqual(expected, actual)

    def test_delete_allowed_by_policies(self):
        rules = {"get_member": True, "delete_member": True}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request(tenant=TENANT1)
        output = self.controller.delete(request, subject_id=UUID2,
                                        member_id=TENANT4)
        request = unit_test_utils.get_fake_request()
        output = self.controller.index(request, UUID2)
        self.assertEqual(0, len(output['members']))

    def test_delete_forbidden_by_get_member_policy(self):
        rules = {"get_member": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request(tenant=TENANT1)
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          request, UUID2, TENANT4)

    def test_delete_forbidden_by_delete_member_policy(self):
        rules = {"delete_member": False}
        self.policy.set_rules(rules)
        request = unit_test_utils.get_fake_request(tenant=TENANT1)
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          request, UUID2, TENANT4)

    def test_delete_private_subject(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          request, UUID4, TENANT1)

    def test_delete_public_subject(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          request, UUID1, TENANT1)

    def test_delete_subject_does_not_exist(self):
        request = unit_test_utils.get_fake_request()
        member_id = TENANT2
        subject_id = 'fake-subject-id'
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          request, subject_id, member_id)

    def test_delete_member_does_not_exist(self):
        request = unit_test_utils.get_fake_request()
        member_id = 'fake-member-id'
        subject_id = UUID2
        found_member = self.db.subject_member_find(
            request.context, subject_id=subject_id, member=member_id)
        self.assertEqual([], found_member)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          request, subject_id, member_id)


class TestSubjectMembersSerializer(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectMembersSerializer, self).setUp()
        self.serializer = subject.api.v2.subject_members.ResponseSerializer()
        self.fixtures = [
            _domain_fixture(id='1', subject_id=UUID2, member_id=TENANT1,
                            status='accepted',
                            created_at=DATETIME, updated_at=DATETIME),
            _domain_fixture(id='2', subject_id=UUID2, member_id=TENANT2,
                            status='pending',
                            created_at=DATETIME, updated_at=DATETIME),
        ]

    def test_index(self):
        expected = {
            'members': [
                {
                    'subject_id': UUID2,
                    'member_id': TENANT1,
                    'status': 'accepted',
                    'created_at': ISOTIME,
                    'updated_at': ISOTIME,
                    'schema': '/v1/schemas/member',
                },
                {
                    'subject_id': UUID2,
                    'member_id': TENANT2,
                    'status': 'pending',
                    'created_at': ISOTIME,
                    'updated_at': ISOTIME,
                    'schema': '/v1/schemas/member',
                },
            ],
            'schema': '/v1/schemas/members',
        }
        request = webob.Request.blank('/v1/subjects/%s/members' % UUID2)
        response = webob.Response(request=request)
        result = {'members': self.fixtures}
        self.serializer.index(response, result)
        actual = jsonutils.loads(response.body)
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)

    def test_show(self):
        expected = {
            'subject_id': UUID2,
            'member_id': TENANT1,
            'status': 'accepted',
            'created_at': ISOTIME,
            'updated_at': ISOTIME,
            'schema': '/v1/schemas/member',
        }
        request = webob.Request.blank('/v1/subjects/%s/members/%s'
                                      % (UUID2, TENANT1))
        response = webob.Response(request=request)
        result = self.fixtures[0]
        self.serializer.show(response, result)
        actual = jsonutils.loads(response.body)
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)

    def test_create(self):
        expected = {'subject_id': UUID2,
                    'member_id': TENANT1,
                    'status': 'accepted',
                    'schema': '/v1/schemas/member',
                    'created_at': ISOTIME,
                    'updated_at': ISOTIME}
        request = webob.Request.blank('/v1/subjects/%s/members/%s'
                                      % (UUID2, TENANT1))
        response = webob.Response(request=request)
        result = self.fixtures[0]
        self.serializer.create(response, result)
        actual = jsonutils.loads(response.body)
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)

    def test_update(self):
        expected = {'subject_id': UUID2,
                    'member_id': TENANT1,
                    'status': 'accepted',
                    'schema': '/v1/schemas/member',
                    'created_at': ISOTIME,
                    'updated_at': ISOTIME}
        request = webob.Request.blank('/v1/subjects/%s/members/%s'
                                      % (UUID2, TENANT1))
        response = webob.Response(request=request)
        result = self.fixtures[0]
        self.serializer.update(response, result)
        actual = jsonutils.loads(response.body)
        self.assertEqual(expected, actual)
        self.assertEqual('application/json', response.content_type)


class TestSubjectsDeserializer(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectsDeserializer, self).setUp()
        self.deserializer = subject.api.v2.subject_members.RequestDeserializer()

    def test_create(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({'member': TENANT1})
        output = self.deserializer.create(request)
        expected = {'member_id': TENANT1}
        self.assertEqual(expected, output)

    def test_create_invalid(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({'mem': TENANT1})
        self.assertRaises(webob.exc.HTTPBadRequest, self.deserializer.create,
                          request)

    def test_create_no_body(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPBadRequest, self.deserializer.create,
                          request)

    def test_create_member_empty(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({'member': ''})
        self.assertRaises(webob.exc.HTTPBadRequest, self.deserializer.create,
                          request)

    def test_create_list_return_error(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes([TENANT1])
        self.assertRaises(webob.exc.HTTPBadRequest, self.deserializer.create,
                          request)

    def test_update_list_return_error(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes([TENANT1])
        self.assertRaises(webob.exc.HTTPBadRequest, self.deserializer.update,
                          request)

    def test_update(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({'status': 'accepted'})
        output = self.deserializer.update(request)
        expected = {'status': 'accepted'}
        self.assertEqual(expected, output)

    def test_update_invalid(self):
        request = unit_test_utils.get_fake_request()
        request.body = jsonutils.dump_as_bytes({'mem': TENANT1})
        self.assertRaises(webob.exc.HTTPBadRequest, self.deserializer.update,
                          request)

    def test_update_no_body(self):
        request = unit_test_utils.get_fake_request()
        self.assertRaises(webob.exc.HTTPBadRequest, self.deserializer.update,
                          request)
