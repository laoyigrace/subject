# Copyright 2012 OpenStack Foundation.
# Copyright 2013 IBM Corp.
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
from oslo_db import exception as db_exc
from oslo_utils import encodeutils
from oslo_utils import timeutils

from subject.common import crypt
from subject.common import exception
import subject.context
import subject.db
from subject.db.sqlalchemy import api
import subject.tests.unit.utils as unit_test_utils
import subject.tests.utils as test_utils

CONF = cfg.CONF
CONF.import_opt('metadata_encryption_key', 'subject.common.config')


@mock.patch('oslo_utils.importutils.import_module')
class TestDbUtilities(test_utils.BaseTestCase):
    def setUp(self):
        super(TestDbUtilities, self).setUp()
        self.config(data_api='silly pants')
        self.api = mock.Mock()

    def test_get_api_calls_configure_if_present(self, import_module):
        import_module.return_value = self.api
        self.assertEqual(subject.db.get_api(), self.api)
        import_module.assert_called_once_with('silly pants')
        self.api.configure.assert_called_once_with()

    def test_get_api_skips_configure_if_missing(self, import_module):
        import_module.return_value = self.api
        del self.api.configure
        self.assertEqual(subject.db.get_api(), self.api)
        import_module.assert_called_once_with('silly pants')
        self.assertFalse(hasattr(self.api, 'configure'))


UUID1 = 'c80a1a6c-bd1f-41c5-90ee-81afedb1d58d'
UUID2 = 'a85abd86-55b3-4d5b-b0b4-5d0a6e6042fc'
UUID3 = '971ec09a-8067-4bc8-a91f-ae3557f1c4c7'
UUID4 = '6bbe7cc2-eae7-4c0f-b50d-a7160b0c6a86'

TENANT1 = '6838eb7b-6ded-434a-882c-b344c77fe8df'
TENANT2 = '2c014f32-55eb-467d-8fcb-4bd706012f81'
TENANT3 = '5a3e60e8-cfa9-4a9e-a90a-62b42cea92b8'
TENANT4 = 'c6c87f25-8a94-47ed-8c83-053c25f42df4'

USER1 = '54492ba0-f4df-4e4e-be62-27f4d76b29cf'

UUID1_LOCATION = 'file:///path/to/subject'
UUID1_LOCATION_METADATA = {'key': 'value'}
UUID3_LOCATION = 'http://somehost.com/place'

CHECKSUM = '93264c3edf5972c9f1cb309543d38a5c'
CHCKSUM1 = '43264c3edf4972c9f1cb309543d38a55'


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
    }
    obj.update(kwargs)
    return obj


def _db_task_fixture(task_id, type, status, **kwargs):
    obj = {
        'id': task_id,
        'type': type,
        'status': status,
        'input': None,
        'result': None,
        'owner': None,
        'message': None,
        'deleted': False,
        'expires_at': timeutils.utcnow() + datetime.timedelta(days=365)
    }
    obj.update(kwargs)
    return obj


class TestSubjectRepo(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectRepo, self).setUp()
        self.db = unit_test_utils.FakeDB(initialize=False)
        self.context = subject.context.RequestContext(
            user=USER1, tenant=TENANT1)
        self.subject_repo = subject.db.SubjectRepo(self.context, self.db)
        self.subject_factory = subject.domain.SubjectFactory()
        self._create_subjects()
        self._create_subject_members()

    def _create_subjects(self):
        self.subjects = [
            _db_fixture(UUID1, owner=TENANT1, checksum=CHECKSUM,
                        name='1', size=256,
                        is_public=True, status='active',
                        locations=[{'url': UUID1_LOCATION,
                                    'metadata': UUID1_LOCATION_METADATA,
                                    'status': 'active'}]),
            _db_fixture(UUID2, owner=TENANT1, checksum=CHCKSUM1,
                        name='2', size=512, is_public=False),
            _db_fixture(UUID3, owner=TENANT3, checksum=CHCKSUM1,
                        name='3', size=1024, is_public=True,
                        locations=[{'url': UUID3_LOCATION,
                                    'metadata': {},
                                    'status': 'active'}]),
            _db_fixture(UUID4, owner=TENANT4, name='4', size=2048),
        ]
        [self.db.subject_create(None, subject) for subject in self.subjects]

        self.db.subject_tag_set_all(None, UUID1, ['ping', 'pong'])

    def _create_subject_members(self):
        self.subject_members = [
            _db_subject_member_fixture(UUID2, TENANT2),
            _db_subject_member_fixture(UUID2, TENANT3, status='accepted'),
        ]
        [self.db.subject_member_create(None, subject_member)
            for subject_member in self.subject_members]

    def test_get(self):
        subject = self.subject_repo.get(UUID1)
        self.assertEqual(UUID1, subject.subject_id)
        self.assertEqual('1', subject.name)
        self.assertEqual(set(['ping', 'pong']), subject.tags)
        self.assertEqual('public', subject.visibility)
        self.assertEqual('active', subject.status)
        self.assertEqual(256, subject.size)
        self.assertEqual(TENANT1, subject.owner)

    def test_location_value(self):
        subject = self.subject_repo.get(UUID3)
        self.assertEqual(UUID3_LOCATION, subject.locations[0]['url'])

    def test_location_data_value(self):
        subject = self.subject_repo.get(UUID1)
        self.assertEqual(UUID1_LOCATION, subject.locations[0]['url'])
        self.assertEqual(UUID1_LOCATION_METADATA,
                         subject.locations[0]['metadata'])

    def test_location_data_exists(self):
        subject = self.subject_repo.get(UUID2)
        self.assertEqual([], subject.locations)

    def test_get_not_found(self):
        fake_uuid = str(uuid.uuid4())
        exc = self.assertRaises(exception.SubjectNotFound, self.subject_repo.get,
                                fake_uuid)
        self.assertIn(fake_uuid, encodeutils.exception_to_unicode(exc))

    def test_get_forbidden(self):
        self.assertRaises(exception.NotFound, self.subject_repo.get, UUID4)

    def test_list(self):
        subjects = self.subject_repo.list()
        subject_ids = set([i.subject_id for i in subjects])
        self.assertEqual(set([UUID1, UUID2, UUID3]), subject_ids)

    def _do_test_list_status(self, status, expected):
        self.context = subject.context.RequestContext(
            user=USER1, tenant=TENANT3)
        self.subject_repo = subject.db.SubjectRepo(self.context, self.db)
        subjects = self.subject_repo.list(member_status=status)
        self.assertEqual(expected, len(subjects))

    def test_list_status(self):
        self._do_test_list_status(None, 3)

    def test_list_status_pending(self):
        self._do_test_list_status('pending', 2)

    def test_list_status_rejected(self):
        self._do_test_list_status('rejected', 2)

    def test_list_status_all(self):
        self._do_test_list_status('all', 3)

    def test_list_with_marker(self):
        full_subjects = self.subject_repo.list()
        full_ids = [i.subject_id for i in full_subjects]
        marked_subjects = self.subject_repo.list(marker=full_ids[0])
        actual_ids = [i.subject_id for i in marked_subjects]
        self.assertEqual(full_ids[1:], actual_ids)

    def test_list_with_last_marker(self):
        subjects = self.subject_repo.list()
        marked_subjects = self.subject_repo.list(marker=subjects[-1].subject_id)
        self.assertEqual(0, len(marked_subjects))

    def test_limited_list(self):
        limited_subjects = self.subject_repo.list(limit=2)
        self.assertEqual(2, len(limited_subjects))

    def test_list_with_marker_and_limit(self):
        full_subjects = self.subject_repo.list()
        full_ids = [i.subject_id for i in full_subjects]
        marked_subjects = self.subject_repo.list(marker=full_ids[0], limit=1)
        actual_ids = [i.subject_id for i in marked_subjects]
        self.assertEqual(full_ids[1:2], actual_ids)

    def test_list_private_subjects(self):
        filters = {'visibility': 'private'}
        subjects = self.subject_repo.list(filters=filters)
        subject_ids = set([i.subject_id for i in subjects])
        self.assertEqual(set([UUID2]), subject_ids)

    def test_list_with_checksum_filter_single_subject(self):
        filters = {'checksum': CHECKSUM}
        subjects = self.subject_repo.list(filters=filters)
        subject_ids = list([i.subject_id for i in subjects])
        self.assertEqual(1, len(subject_ids))
        self.assertEqual([UUID1], subject_ids)

    def test_list_with_checksum_filter_multiple_subjects(self):
        filters = {'checksum': CHCKSUM1}
        subjects = self.subject_repo.list(filters=filters)
        subject_ids = list([i.subject_id for i in subjects])
        self.assertEqual(2, len(subject_ids))
        self.assertIn(UUID2, subject_ids)
        self.assertIn(UUID3, subject_ids)

    def test_list_with_wrong_checksum(self):
        WRONG_CHKSUM = 'd2fd42f979e1ed1aafadc7eb9354bff839c858cd'
        filters = {'checksum': WRONG_CHKSUM}
        subjects = self.subject_repo.list(filters=filters)
        self.assertEqual(0, len(subjects))

    def test_list_with_tags_filter_single_tag(self):
        filters = {'tags': ['ping']}
        subjects = self.subject_repo.list(filters=filters)
        subject_ids = list([i.subject_id for i in subjects])
        self.assertEqual(1, len(subject_ids))
        self.assertEqual([UUID1], subject_ids)

    def test_list_with_tags_filter_multiple_tags(self):
        filters = {'tags': ['ping', 'pong']}
        subjects = self.subject_repo.list(filters=filters)
        subject_ids = list([i.subject_id for i in subjects])
        self.assertEqual(1, len(subject_ids))
        self.assertEqual([UUID1], subject_ids)

    def test_list_with_tags_filter_multiple_tags_and_nonexistent(self):
        filters = {'tags': ['ping', 'fake']}
        subjects = self.subject_repo.list(filters=filters)
        subject_ids = list([i.subject_id for i in subjects])
        self.assertEqual(0, len(subject_ids))

    def test_list_with_wrong_tags(self):
        filters = {'tags': ['fake']}
        subjects = self.subject_repo.list(filters=filters)
        self.assertEqual(0, len(subjects))

    def test_list_public_subjects(self):
        filters = {'visibility': 'public'}
        subjects = self.subject_repo.list(filters=filters)
        subject_ids = set([i.subject_id for i in subjects])
        self.assertEqual(set([UUID1, UUID3]), subject_ids)

    def test_sorted_list(self):
        subjects = self.subject_repo.list(sort_key=['size'], sort_dir=['asc'])
        subject_ids = [i.subject_id for i in subjects]
        self.assertEqual([UUID1, UUID2, UUID3], subject_ids)

    def test_sorted_list_with_multiple_keys(self):
        temp_id = 'd80a1a6c-bd1f-41c5-90ee-81afedb1d58d'
        subject = _db_fixture(temp_id, owner=TENANT1, checksum=CHECKSUM,
                            name='1', size=1024,
                            is_public=True, status='active',
                            locations=[{'url': UUID1_LOCATION,
                                        'metadata': UUID1_LOCATION_METADATA,
                                        'status': 'active'}])
        self.db.subject_create(None, subject)
        subjects = self.subject_repo.list(sort_key=['name', 'size'],
                                      sort_dir=['asc'])
        subject_ids = [i.subject_id for i in subjects]
        self.assertEqual([UUID1, temp_id, UUID2, UUID3], subject_ids)

        subjects = self.subject_repo.list(sort_key=['size', 'name'],
                                      sort_dir=['asc'])
        subject_ids = [i.subject_id for i in subjects]
        self.assertEqual([UUID1, UUID2, temp_id, UUID3], subject_ids)

    def test_sorted_list_with_multiple_dirs(self):
        temp_id = 'd80a1a6c-bd1f-41c5-90ee-81afedb1d58d'
        subject = _db_fixture(temp_id, owner=TENANT1, checksum=CHECKSUM,
                            name='1', size=1024,
                            is_public=True, status='active',
                            locations=[{'url': UUID1_LOCATION,
                                        'metadata': UUID1_LOCATION_METADATA,
                                        'status': 'active'}])
        self.db.subject_create(None, subject)
        subjects = self.subject_repo.list(sort_key=['name', 'size'],
                                      sort_dir=['asc', 'desc'])
        subject_ids = [i.subject_id for i in subjects]
        self.assertEqual([temp_id, UUID1, UUID2, UUID3], subject_ids)

        subjects = self.subject_repo.list(sort_key=['name', 'size'],
                                      sort_dir=['desc', 'asc'])
        subject_ids = [i.subject_id for i in subjects]
        self.assertEqual([UUID3, UUID2, UUID1, temp_id], subject_ids)

    def test_add_subject(self):
        subject = self.subject_factory.new_subject(name='added subject')
        self.assertEqual(subject.updated_at, subject.created_at)
        self.subject_repo.add(subject)
        retreived_subject = self.subject_repo.get(subject.subject_id)
        self.assertEqual('added subject', retreived_subject.name)
        self.assertEqual(subject.updated_at, retreived_subject.updated_at)

    def test_save_subject(self):
        subject = self.subject_repo.get(UUID1)
        original_update_time = subject.updated_at
        subject.name = 'foo'
        subject.tags = ['king', 'kong']
        self.subject_repo.save(subject)
        current_update_time = subject.updated_at
        self.assertGreater(current_update_time, original_update_time)
        subject = self.subject_repo.get(UUID1)
        self.assertEqual('foo', subject.name)
        self.assertEqual(set(['king', 'kong']), subject.tags)
        self.assertEqual(current_update_time, subject.updated_at)

    def test_save_subject_not_found(self):
        fake_uuid = str(uuid.uuid4())
        subject = self.subject_repo.get(UUID1)
        subject.subject_id = fake_uuid
        exc = self.assertRaises(exception.SubjectNotFound, self.subject_repo.save,
                                subject)
        self.assertIn(fake_uuid, encodeutils.exception_to_unicode(exc))

    def test_remove_subject(self):
        subject = self.subject_repo.get(UUID1)
        previous_update_time = subject.updated_at
        self.subject_repo.remove(subject)
        self.assertGreater(subject.updated_at, previous_update_time)
        self.assertRaises(exception.SubjectNotFound, self.subject_repo.get, UUID1)

    def test_remove_subject_not_found(self):
        fake_uuid = str(uuid.uuid4())
        subject = self.subject_repo.get(UUID1)
        subject.subject_id = fake_uuid
        exc = self.assertRaises(
            exception.SubjectNotFound, self.subject_repo.remove, subject)
        self.assertIn(fake_uuid, encodeutils.exception_to_unicode(exc))


class TestEncryptedLocations(test_utils.BaseTestCase):
    def setUp(self):
        super(TestEncryptedLocations, self).setUp()
        self.db = unit_test_utils.FakeDB(initialize=False)
        self.context = subject.context.RequestContext(
            user=USER1, tenant=TENANT1)
        self.subject_repo = subject.db.SubjectRepo(self.context, self.db)
        self.subject_factory = subject.domain.SubjectFactory()
        self.crypt_key = '0123456789abcdef'
        self.config(metadata_encryption_key=self.crypt_key)
        self.foo_bar_location = [{'url': 'foo', 'metadata': {},
                                  'status': 'active'},
                                 {'url': 'bar', 'metadata': {},
                                  'status': 'active'}]

    def test_encrypt_locations_on_add(self):
        subject = self.subject_factory.new_subject(UUID1)
        subject.locations = self.foo_bar_location
        self.subject_repo.add(subject)
        db_data = self.db.subject_get(self.context, UUID1)
        self.assertNotEqual(db_data['locations'], ['foo', 'bar'])
        decrypted_locations = [crypt.urlsafe_decrypt(self.crypt_key, l['url'])
                               for l in db_data['locations']]
        self.assertEqual([l['url'] for l in self.foo_bar_location],
                         decrypted_locations)

    def test_encrypt_locations_on_save(self):
        subject = self.subject_factory.new_subject(UUID1)
        self.subject_repo.add(subject)
        subject.locations = self.foo_bar_location
        self.subject_repo.save(subject)
        db_data = self.db.subject_get(self.context, UUID1)
        self.assertNotEqual(db_data['locations'], ['foo', 'bar'])
        decrypted_locations = [crypt.urlsafe_decrypt(self.crypt_key, l['url'])
                               for l in db_data['locations']]
        self.assertEqual([l['url'] for l in self.foo_bar_location],
                         decrypted_locations)

    def test_decrypt_locations_on_get(self):
        url_loc = ['ping', 'pong']
        orig_locations = [{'url': l, 'metadata': {}, 'status': 'active'}
                          for l in url_loc]
        encrypted_locs = [crypt.urlsafe_encrypt(self.crypt_key, l)
                          for l in url_loc]
        encrypted_locations = [{'url': l, 'metadata': {}, 'status': 'active'}
                               for l in encrypted_locs]
        self.assertNotEqual(encrypted_locations, orig_locations)
        db_data = _db_fixture(UUID1, owner=TENANT1,
                              locations=encrypted_locations)
        self.db.subject_create(None, db_data)
        subject = self.subject_repo.get(UUID1)
        self.assertIn('id', subject.locations[0])
        self.assertIn('id', subject.locations[1])
        subject.locations[0].pop('id')
        subject.locations[1].pop('id')
        self.assertEqual(orig_locations, subject.locations)

    def test_decrypt_locations_on_list(self):
        url_loc = ['ping', 'pong']
        orig_locations = [{'url': l, 'metadata': {}, 'status': 'active'}
                          for l in url_loc]
        encrypted_locs = [crypt.urlsafe_encrypt(self.crypt_key, l)
                          for l in url_loc]
        encrypted_locations = [{'url': l, 'metadata': {}, 'status': 'active'}
                               for l in encrypted_locs]
        self.assertNotEqual(encrypted_locations, orig_locations)
        db_data = _db_fixture(UUID1, owner=TENANT1,
                              locations=encrypted_locations)
        self.db.subject_create(None, db_data)
        subject = self.subject_repo.list()[0]
        self.assertIn('id', subject.locations[0])
        self.assertIn('id', subject.locations[1])
        subject.locations[0].pop('id')
        subject.locations[1].pop('id')
        self.assertEqual(orig_locations, subject.locations)


class TestSubjectMemberRepo(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectMemberRepo, self).setUp()
        self.db = unit_test_utils.FakeDB(initialize=False)
        self.context = subject.context.RequestContext(
            user=USER1, tenant=TENANT1)
        self.subject_repo = subject.db.SubjectRepo(self.context, self.db)
        self.subject_member_factory = subject.domain.SubjectMemberFactory()
        self._create_subjects()
        self._create_subject_members()
        subject = self.subject_repo.get(UUID1)
        self.subject_member_repo = subject.db.SubjectMemberRepo(self.context,
                                                            self.db, subject)

    def _create_subjects(self):
        self.subjects = [
            _db_fixture(UUID1, owner=TENANT1, name='1', size=256,
                        status='active'),
            _db_fixture(UUID2, owner=TENANT1, name='2',
                        size=512, is_public=False),
        ]
        [self.db.subject_create(None, subject) for subject in self.subjects]

        self.db.subject_tag_set_all(None, UUID1, ['ping', 'pong'])

    def _create_subject_members(self):
        self.subject_members = [
            _db_subject_member_fixture(UUID1, TENANT2),
            _db_subject_member_fixture(UUID1, TENANT3),
        ]
        [self.db.subject_member_create(None, subject_member)
            for subject_member in self.subject_members]

    def test_list(self):
        subject_members = self.subject_member_repo.list()
        subject_member_ids = set([i.member_id for i in subject_members])
        self.assertEqual(set([TENANT2, TENANT3]), subject_member_ids)

    def test_list_no_members(self):
        subject = self.subject_repo.get(UUID2)
        self.subject_member_repo_uuid2 = subject.db.SubjectMemberRepo(
            self.context, self.db, subject)
        subject_members = self.subject_member_repo_uuid2.list()
        subject_member_ids = set([i.member_id for i in subject_members])
        self.assertEqual(set([]), subject_member_ids)

    def test_save_subject_member(self):
        subject_member = self.subject_member_repo.get(TENANT2)
        subject_member.status = 'accepted'
        self.subject_member_repo.save(subject_member)
        subject_member_updated = self.subject_member_repo.get(TENANT2)
        self.assertEqual(subject_member.id, subject_member_updated.id)
        self.assertEqual('accepted', subject_member_updated.status)

    def test_add_subject_member(self):
        subject = self.subject_repo.get(UUID1)
        subject_member = self.subject_member_factory.new_subject_member(subject,
                                                                  TENANT4)
        self.assertIsNone(subject_member.id)
        self.subject_member_repo.add(subject_member)
        retreived_subject_member = self.subject_member_repo.get(TENANT4)
        self.assertIsNotNone(retreived_subject_member.id)
        self.assertEqual(subject_member.subject_id,
                         retreived_subject_member.subject_id)
        self.assertEqual(subject_member.member_id,
                         retreived_subject_member.member_id)
        self.assertEqual('pending', retreived_subject_member.status)

    def test_add_duplicate_subject_member(self):
        subject = self.subject_repo.get(UUID1)
        subject_member = self.subject_member_factory.new_subject_member(subject,
                                                                  TENANT4)
        self.assertIsNone(subject_member.id)
        self.subject_member_repo.add(subject_member)
        retreived_subject_member = self.subject_member_repo.get(TENANT4)
        self.assertIsNotNone(retreived_subject_member.id)
        self.assertEqual(subject_member.subject_id,
                         retreived_subject_member.subject_id)
        self.assertEqual(subject_member.member_id,
                         retreived_subject_member.member_id)
        self.assertEqual('pending', retreived_subject_member.status)

        self.assertRaises(exception.Duplicate, self.subject_member_repo.add,
                          subject_member)

    def test_get_subject_member(self):
        subject = self.subject_repo.get(UUID1)
        subject_member = self.subject_member_factory.new_subject_member(subject,
                                                                  TENANT4)
        self.assertIsNone(subject_member.id)
        self.subject_member_repo.add(subject_member)

        member = self.subject_member_repo.get(subject_member.member_id)

        self.assertEqual(member.id, subject_member.id)
        self.assertEqual(member.subject_id, subject_member.subject_id)
        self.assertEqual(member.member_id, subject_member.member_id)
        self.assertEqual('pending', member.status)

    def test_get_nonexistent_subject_member(self):
        fake_subject_member_id = 'fake'
        self.assertRaises(exception.NotFound, self.subject_member_repo.get,
                          fake_subject_member_id)

    def test_remove_subject_member(self):
        subject_member = self.subject_member_repo.get(TENANT2)
        self.subject_member_repo.remove(subject_member)
        self.assertRaises(exception.NotFound, self.subject_member_repo.get,
                          TENANT2)

    def test_remove_subject_member_does_not_exist(self):
        fake_uuid = str(uuid.uuid4())
        subject = self.subject_repo.get(UUID2)
        fake_member = subject.domain.SubjectMemberFactory().new_subject_member(
            subject, TENANT4)
        fake_member.id = fake_uuid
        exc = self.assertRaises(exception.NotFound,
                                self.subject_member_repo.remove,
                                fake_member)
        self.assertIn(fake_uuid, encodeutils.exception_to_unicode(exc))


class TestTaskRepo(test_utils.BaseTestCase):

    def setUp(self):
        super(TestTaskRepo, self).setUp()
        self.db = unit_test_utils.FakeDB(initialize=False)
        self.context = subject.context.RequestContext(user=USER1,
                                                      tenant=TENANT1)
        self.task_repo = subject.db.TaskRepo(self.context, self.db)
        self.task_factory = subject.domain.TaskFactory()
        self.fake_task_input = ('{"import_from": '
                                '"swift://cloud.foo/account/mycontainer/path"'
                                ',"import_from_format": "qcow2"}')
        self._create_tasks()

    def _create_tasks(self):
        self.tasks = [
            _db_task_fixture(UUID1, type='import', status='pending',
                             input=self.fake_task_input,
                             result='',
                             owner=TENANT1,
                             message='',
                             ),
            _db_task_fixture(UUID2, type='import', status='processing',
                             input=self.fake_task_input,
                             result='',
                             owner=TENANT1,
                             message='',
                             ),
            _db_task_fixture(UUID3, type='import', status='failure',
                             input=self.fake_task_input,
                             result='',
                             owner=TENANT1,
                             message='',
                             ),
            _db_task_fixture(UUID4, type='import', status='success',
                             input=self.fake_task_input,
                             result='',
                             owner=TENANT2,
                             message='',
                             ),
        ]
        [self.db.task_create(None, task) for task in self.tasks]

    def test_get(self):
        task = self.task_repo.get(UUID1)
        self.assertEqual(task.task_id, UUID1)
        self.assertEqual('import', task.type)
        self.assertEqual('pending', task.status)
        self.assertEqual(task.task_input, self.fake_task_input)
        self.assertEqual('', task.result)
        self.assertEqual('', task.message)
        self.assertEqual(task.owner, TENANT1)

    def test_get_not_found(self):
        self.assertRaises(exception.NotFound,
                          self.task_repo.get,
                          str(uuid.uuid4()))

    def test_get_forbidden(self):
        self.assertRaises(exception.NotFound,
                          self.task_repo.get,
                          UUID4)

    def test_list(self):
        tasks = self.task_repo.list()
        task_ids = set([i.task_id for i in tasks])
        self.assertEqual(set([UUID1, UUID2, UUID3]), task_ids)

    def test_list_with_type(self):
        filters = {'type': 'import'}
        tasks = self.task_repo.list(filters=filters)
        task_ids = set([i.task_id for i in tasks])
        self.assertEqual(set([UUID1, UUID2, UUID3]), task_ids)

    def test_list_with_status(self):
        filters = {'status': 'failure'}
        tasks = self.task_repo.list(filters=filters)
        task_ids = set([i.task_id for i in tasks])
        self.assertEqual(set([UUID3]), task_ids)

    def test_list_with_marker(self):
        full_tasks = self.task_repo.list()
        full_ids = [i.task_id for i in full_tasks]
        marked_tasks = self.task_repo.list(marker=full_ids[0])
        actual_ids = [i.task_id for i in marked_tasks]
        self.assertEqual(full_ids[1:], actual_ids)

    def test_list_with_last_marker(self):
        tasks = self.task_repo.list()
        marked_tasks = self.task_repo.list(marker=tasks[-1].task_id)
        self.assertEqual(0, len(marked_tasks))

    def test_limited_list(self):
        limited_tasks = self.task_repo.list(limit=2)
        self.assertEqual(2, len(limited_tasks))

    def test_list_with_marker_and_limit(self):
        full_tasks = self.task_repo.list()
        full_ids = [i.task_id for i in full_tasks]
        marked_tasks = self.task_repo.list(marker=full_ids[0], limit=1)
        actual_ids = [i.task_id for i in marked_tasks]
        self.assertEqual(full_ids[1:2], actual_ids)

    def test_sorted_list(self):
        tasks = self.task_repo.list(sort_key='status', sort_dir='desc')
        task_ids = [i.task_id for i in tasks]
        self.assertEqual([UUID2, UUID1, UUID3], task_ids)

    def test_add_task(self):
        task_type = 'import'
        task = self.task_factory.new_task(task_type, None,
                                          task_input=self.fake_task_input)
        self.assertEqual(task.updated_at, task.created_at)
        self.task_repo.add(task)
        retrieved_task = self.task_repo.get(task.task_id)
        self.assertEqual(task.updated_at, retrieved_task.updated_at)
        self.assertEqual(self.fake_task_input, retrieved_task.task_input)

    def test_save_task(self):
        task = self.task_repo.get(UUID1)
        original_update_time = task.updated_at
        self.task_repo.save(task)
        current_update_time = task.updated_at
        self.assertGreater(current_update_time, original_update_time)
        task = self.task_repo.get(UUID1)
        self.assertEqual(current_update_time, task.updated_at)

    def test_remove_task(self):
        task = self.task_repo.get(UUID1)
        self.task_repo.remove(task)
        self.assertRaises(exception.NotFound,
                          self.task_repo.get,
                          task.task_id)


class RetryOnDeadlockTestCase(test_utils.BaseTestCase):

    def test_raise_deadlock(self):

        class TestException(Exception):
            pass

        self.attempts = 3

        def _mock_get_session():
            def _raise_exceptions():
                self.attempts -= 1
                if self.attempts <= 0:
                    raise TestException("Exit")
                raise db_exc.DBDeadlock("Fake Exception")
            return _raise_exceptions

        with mock.patch.object(api, 'get_session') as sess:
            sess.side_effect = _mock_get_session()

            try:
                api._subject_update(None, {}, 'fake-id')
            except TestException:
                self.assertEqual(3, sess.call_count)

        # Test retry on subject destroy if db deadlock occurs
        self.attempts = 3
        with mock.patch.object(api, 'get_session') as sess:
            sess.side_effect = _mock_get_session()

            try:
                api.subject_destroy(None, 'fake-id')
            except TestException:
                self.assertEqual(3, sess.call_count)
