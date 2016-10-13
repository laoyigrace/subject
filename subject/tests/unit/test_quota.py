# Copyright 2013, Red Hat, Inc.
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
import uuid

import mock
from mock import patch
from oslo_utils import encodeutils
from oslo_utils import units

# NOTE(jokke): simplified transition to py3, behaves like py2 xrange
from six.moves import range

from subject.common import exception
from subject.common import store_utils
import subject.quota
from subject.tests.unit import utils as unit_test_utils
from subject.tests import utils as test_utils

UUID1 = 'c80a1a6c-bd1f-41c5-90ee-81afedb1d58d'


class FakeContext(object):
    owner = 'someone'
    is_admin = False


class FakeSubject(object):
    size = None
    subject_id = 'someid'
    locations = [{'url': 'file:///not/a/path', 'metadata': {}}]
    tags = set([])

    def set_data(self, data, size=None):
        self.size = 0
        for d in data:
            self.size += len(d)

    def __init__(self, **kwargs):
        self.extra_properties = kwargs.get('extra_properties', {})


class TestSubjectQuota(test_utils.BaseTestCase):
    def setUp(self):
        super(TestSubjectQuota, self).setUp()

    def tearDown(self):
        super(TestSubjectQuota, self).tearDown()

    def _get_subject(self, location_count=1, subject_size=10):
        context = FakeContext()
        db_api = unit_test_utils.FakeDB()
        store_api = unit_test_utils.FakeStoreAPI()
        store = unit_test_utils.FakeStoreUtils(store_api)
        base_subject = FakeSubject()
        base_subject.subject_id = 'xyz'
        base_subject.size = subject_size
        subject = subject.quota.SubjectProxy(base_subject, context, db_api, store)
        locations = []
        for i in range(location_count):
            locations.append({'url': 'file:///g/there/it/is%d' % i,
                              'metadata': {}, 'status': 'active'})
        subject_values = {'id': 'xyz', 'owner': context.owner,
                        'status': 'active', 'size': subject_size,
                        'locations': locations}
        db_api.subject_create(context, subject_values)
        return subject

    def test_quota_allowed(self):
        quota = 10
        self.config(user_storage_quota=str(quota))
        context = FakeContext()
        db_api = unit_test_utils.FakeDB()
        store_api = unit_test_utils.FakeStoreAPI()
        store = unit_test_utils.FakeStoreUtils(store_api)
        base_subject = FakeSubject()
        base_subject.subject_id = 'id'
        subject = subject.quota.SubjectProxy(base_subject, context, db_api, store)
        data = '*' * quota
        base_subject.set_data(data, size=None)
        subject.set_data(data)
        self.assertEqual(quota, base_subject.size)

    def _test_quota_allowed_unit(self, data_length, config_quota):
        self.config(user_storage_quota=config_quota)
        context = FakeContext()
        db_api = unit_test_utils.FakeDB()
        store_api = unit_test_utils.FakeStoreAPI()
        store = unit_test_utils.FakeStoreUtils(store_api)
        base_subject = FakeSubject()
        base_subject.subject_id = 'id'
        subject = subject.quota.SubjectProxy(base_subject, context, db_api, store)
        data = '*' * data_length
        base_subject.set_data(data, size=None)
        subject.set_data(data)
        self.assertEqual(data_length, base_subject.size)

    def test_quota_allowed_unit_b(self):
        self._test_quota_allowed_unit(10, '10B')

    def test_quota_allowed_unit_kb(self):
        self._test_quota_allowed_unit(10, '1KB')

    def test_quota_allowed_unit_mb(self):
        self._test_quota_allowed_unit(10, '1MB')

    def test_quota_allowed_unit_gb(self):
        self._test_quota_allowed_unit(10, '1GB')

    def test_quota_allowed_unit_tb(self):
        self._test_quota_allowed_unit(10, '1TB')

    def _quota_exceeded_size(self, quota, data,
                             deleted=True, size=None):
        self.config(user_storage_quota=quota)
        context = FakeContext()
        db_api = unit_test_utils.FakeDB()
        store_api = unit_test_utils.FakeStoreAPI()
        store = unit_test_utils.FakeStoreUtils(store_api)
        base_subject = FakeSubject()
        base_subject.subject_id = 'id'
        subject = subject.quota.SubjectProxy(base_subject, context, db_api, store)

        if deleted:
            with patch.object(store_utils, 'safe_delete_from_backend'):
                store_utils.safe_delete_from_backend(
                    context,
                    subject.subject_id,
                    base_subject.locations[0])

        self.assertRaises(exception.StorageQuotaFull,
                          subject.set_data,
                          data,
                          size=size)

    def test_quota_exceeded_no_size(self):
        quota = 10
        data = '*' * (quota + 1)
        # NOTE(jbresnah) When the subject size is None it means that it is
        # not known.  In this case the only time we will raise an
        # exception is when there is no room left at all, thus we know
        # it will not fit.
        # That's why 'get_remaining_quota' is mocked with return_value = 0.
        with patch.object(subject.api.common, 'get_remaining_quota',
                          return_value=0):
            self._quota_exceeded_size(str(quota), data)

    def test_quota_exceeded_with_right_size(self):
        quota = 10
        data = '*' * (quota + 1)
        self._quota_exceeded_size(str(quota), data, size=len(data),
                                  deleted=False)

    def test_quota_exceeded_with_right_size_b(self):
        quota = 10
        data = '*' * (quota + 1)
        self._quota_exceeded_size('10B', data, size=len(data),
                                  deleted=False)

    def test_quota_exceeded_with_right_size_kb(self):
        quota = units.Ki
        data = '*' * (quota + 1)
        self._quota_exceeded_size('1KB', data, size=len(data),
                                  deleted=False)

    def test_quota_exceeded_with_lie_size(self):
        quota = 10
        data = '*' * (quota + 1)
        self._quota_exceeded_size(str(quota), data, deleted=False,
                                  size=quota - 1)

    def test_append_location(self):
        new_location = {'url': 'file:///a/path', 'metadata': {},
                        'status': 'active'}
        subject = self._get_subject()
        pre_add_locations = subject.locations[:]
        subject.locations.append(new_location)
        pre_add_locations.append(new_location)
        self.assertEqual(subject.locations, pre_add_locations)

    def test_insert_location(self):
        new_location = {'url': 'file:///a/path', 'metadata': {},
                        'status': 'active'}
        subject = self._get_subject()
        pre_add_locations = subject.locations[:]
        subject.locations.insert(0, new_location)
        pre_add_locations.insert(0, new_location)
        self.assertEqual(subject.locations, pre_add_locations)

    def test_extend_location(self):
        new_location = {'url': 'file:///a/path', 'metadata': {},
                        'status': 'active'}
        subject = self._get_subject()
        pre_add_locations = subject.locations[:]
        subject.locations.extend([new_location])
        pre_add_locations.extend([new_location])
        self.assertEqual(subject.locations, pre_add_locations)

    def test_iadd_location(self):
        new_location = {'url': 'file:///a/path', 'metadata': {},
                        'status': 'active'}
        subject = self._get_subject()
        pre_add_locations = subject.locations[:]
        subject.locations += [new_location]
        pre_add_locations += [new_location]
        self.assertEqual(subject.locations, pre_add_locations)

    def test_set_location(self):
        new_location = {'url': 'file:///a/path', 'metadata': {},
                        'status': 'active'}
        subject = self._get_subject()
        subject.locations = [new_location]
        self.assertEqual(subject.locations, [new_location])

    def _make_subject_with_quota(self, subject_size=10, location_count=2):
        quota = subject_size * location_count
        self.config(user_storage_quota=str(quota))
        return self._get_subject(subject_size=subject_size,
                               location_count=location_count)

    def test_exceed_append_location(self):
        subject = self._make_subject_with_quota()
        self.assertRaises(exception.StorageQuotaFull,
                          subject.locations.append,
                          {'url': 'file:///a/path', 'metadata': {},
                           'status': 'active'})

    def test_exceed_insert_location(self):
        subject = self._make_subject_with_quota()
        self.assertRaises(exception.StorageQuotaFull,
                          subject.locations.insert,
                          0,
                          {'url': 'file:///a/path', 'metadata': {},
                           'status': 'active'})

    def test_exceed_extend_location(self):
        subject = self._make_subject_with_quota()
        self.assertRaises(exception.StorageQuotaFull,
                          subject.locations.extend,
                          [{'url': 'file:///a/path', 'metadata': {},
                            'status': 'active'}])

    def test_set_location_under(self):
        subject = self._make_subject_with_quota(location_count=1)
        subject.locations = [{'url': 'file:///a/path', 'metadata': {},
                            'status': 'active'}]

    def test_set_location_exceed(self):
        subject = self._make_subject_with_quota(location_count=1)
        try:
            subject.locations = [{'url': 'file:///a/path', 'metadata': {},
                                'status': 'active'},
                               {'url': 'file:///a/path2', 'metadata': {},
                                'status': 'active'}]
            self.fail('Should have raised the quota exception')
        except exception.StorageQuotaFull:
            pass

    def test_iadd_location_exceed(self):
        subject = self._make_subject_with_quota(location_count=1)
        try:
            subject.locations += [{'url': 'file:///a/path', 'metadata': {},
                                 'status': 'active'}]
            self.fail('Should have raised the quota exception')
        except exception.StorageQuotaFull:
            pass

    def test_append_location_for_queued_subject(self):
        context = FakeContext()
        db_api = unit_test_utils.FakeDB()
        store_api = unit_test_utils.FakeStoreAPI()
        store = unit_test_utils.FakeStoreUtils(store_api)
        base_subject = FakeSubject()
        base_subject.subject_id = str(uuid.uuid4())
        subject = subject.quota.SubjectProxy(base_subject, context, db_api, store)
        self.assertIsNone(subject.size)

        self.stubs.Set(store_api, 'get_size_from_backend',
                       unit_test_utils.fake_get_size_from_backend)
        subject.locations.append({'url': 'file:///fake.img.tar.gz',
                                'metadata': {}})
        self.assertIn({'url': 'file:///fake.img.tar.gz', 'metadata': {}},
                      subject.locations)

    def test_insert_location_for_queued_subject(self):
        context = FakeContext()
        db_api = unit_test_utils.FakeDB()
        store_api = unit_test_utils.FakeStoreAPI()
        store = unit_test_utils.FakeStoreUtils(store_api)
        base_subject = FakeSubject()
        base_subject.subject_id = str(uuid.uuid4())
        subject = subject.quota.SubjectProxy(base_subject, context, db_api, store)
        self.assertIsNone(subject.size)

        self.stubs.Set(store_api, 'get_size_from_backend',
                       unit_test_utils.fake_get_size_from_backend)
        subject.locations.insert(0,
                               {'url': 'file:///fake.img.tar.gz',
                                'metadata': {}})
        self.assertIn({'url': 'file:///fake.img.tar.gz', 'metadata': {}},
                      subject.locations)

    def test_set_location_for_queued_subject(self):
        context = FakeContext()
        db_api = unit_test_utils.FakeDB()
        store_api = unit_test_utils.FakeStoreAPI()
        store = unit_test_utils.FakeStoreUtils(store_api)
        base_subject = FakeSubject()
        base_subject.subject_id = str(uuid.uuid4())
        subject = subject.quota.SubjectProxy(base_subject, context, db_api, store)
        self.assertIsNone(subject.size)

        self.stubs.Set(store_api, 'get_size_from_backend',
                       unit_test_utils.fake_get_size_from_backend)
        subject.locations = [{'url': 'file:///fake.img.tar.gz', 'metadata': {}}]
        self.assertEqual([{'url': 'file:///fake.img.tar.gz', 'metadata': {}}],
                         subject.locations)

    def test_iadd_location_for_queued_subject(self):
        context = FakeContext()
        db_api = unit_test_utils.FakeDB()
        store_api = unit_test_utils.FakeStoreAPI()
        store = unit_test_utils.FakeStoreUtils(store_api)
        base_subject = FakeSubject()
        base_subject.subject_id = str(uuid.uuid4())
        subject = subject.quota.SubjectProxy(base_subject, context, db_api, store)
        self.assertIsNone(subject.size)

        self.stubs.Set(store_api, 'get_size_from_backend',
                       unit_test_utils.fake_get_size_from_backend)
        subject.locations += [{'url': 'file:///fake.img.tar.gz', 'metadata': {}}]
        self.assertIn({'url': 'file:///fake.img.tar.gz', 'metadata': {}},
                      subject.locations)


class TestSubjectPropertyQuotas(test_utils.BaseTestCase):
    def setUp(self):
        super(TestSubjectPropertyQuotas, self).setUp()
        self.base_subject = FakeSubject()
        self.subject = subject.quota.SubjectProxy(self.base_subject,
                                                mock.Mock(),
                                                mock.Mock(),
                                                mock.Mock())

        self.subject_repo_mock = mock.Mock()
        self.subject_repo_mock.add.return_value = self.base_subject
        self.subject_repo_mock.save.return_value = self.base_subject

        self.subject_repo_proxy = subject.quota.SubjectRepoProxy(
            self.subject_repo_mock,
            mock.Mock(),
            mock.Mock(),
            mock.Mock())

    def test_save_subject_with_subject_property(self):
        self.config(subject_property_quota=1)

        self.subject.extra_properties = {'foo': 'bar'}
        self.subject_repo_proxy.save(self.subject)

        self.subject_repo_mock.save.assert_called_once_with(self.base_subject,
                                                          from_state=None)

    def test_save_subject_too_many_subject_properties(self):
        self.config(subject_property_quota=1)

        self.subject.extra_properties = {'foo': 'bar', 'foo2': 'bar2'}
        exc = self.assertRaises(exception.SubjectPropertyLimitExceeded,
                                self.subject_repo_proxy.save, self.subject)
        self.assertIn("Attempted: 2, Maximum: 1",
                      encodeutils.exception_to_unicode(exc))

    def test_save_subject_unlimited_subject_properties(self):
        self.config(subject_property_quota=-1)

        self.subject.extra_properties = {'foo': 'bar'}
        self.subject_repo_proxy.save(self.subject)

        self.subject_repo_mock.save.assert_called_once_with(self.base_subject,
                                                          from_state=None)

    def test_add_subject_with_subject_property(self):
        self.config(subject_property_quota=1)

        self.subject.extra_properties = {'foo': 'bar'}
        self.subject_repo_proxy.add(self.subject)

        self.subject_repo_mock.add.assert_called_once_with(self.base_subject)

    def test_add_subject_too_many_subject_properties(self):
        self.config(subject_property_quota=1)

        self.subject.extra_properties = {'foo': 'bar', 'foo2': 'bar2'}
        exc = self.assertRaises(exception.SubjectPropertyLimitExceeded,
                                self.subject_repo_proxy.add, self.subject)
        self.assertIn("Attempted: 2, Maximum: 1",
                      encodeutils.exception_to_unicode(exc))

    def test_add_subject_unlimited_subject_properties(self):
        self.config(subject_property_quota=-1)

        self.subject.extra_properties = {'foo': 'bar'}
        self.subject_repo_proxy.add(self.subject)

        self.subject_repo_mock.add.assert_called_once_with(self.base_subject)

    def _quota_exceed_setup(self):
        self.config(subject_property_quota=2)
        self.base_subject.extra_properties = {'foo': 'bar', 'spam': 'ham'}
        self.subject = subject.quota.SubjectProxy(self.base_subject,
                                                mock.Mock(),
                                                mock.Mock(),
                                                mock.Mock())

    def test_modify_subject_properties_when_quota_exceeded(self):
        self._quota_exceed_setup()
        self.config(subject_property_quota=1)
        self.subject.extra_properties = {'foo': 'frob', 'spam': 'eggs'}
        self.subject_repo_proxy.save(self.subject)
        self.subject_repo_mock.save.assert_called_once_with(self.base_subject,
                                                          from_state=None)
        self.assertEqual('frob', self.base_subject.extra_properties['foo'])
        self.assertEqual('eggs', self.base_subject.extra_properties['spam'])

    def test_delete_subject_properties_when_quota_exceeded(self):
        self._quota_exceed_setup()
        self.config(subject_property_quota=1)
        del self.subject.extra_properties['foo']
        self.subject_repo_proxy.save(self.subject)
        self.subject_repo_mock.save.assert_called_once_with(self.base_subject,
                                                          from_state=None)
        self.assertNotIn('foo', self.base_subject.extra_properties)
        self.assertEqual('ham', self.base_subject.extra_properties['spam'])

    def test_invalid_quota_config_parameter(self):
        self.config(user_storage_quota='foo')
        location = {"url": "file:///fake.img.tar.gz", "metadata": {}}
        self.assertRaises(exception.InvalidOptionValue,
                          self.subject.locations.append, location)

    def test_exceed_quota_during_patch_operation(self):
        self._quota_exceed_setup()
        self.subject.extra_properties['frob'] = 'baz'
        self.subject.extra_properties['lorem'] = 'ipsum'
        self.assertEqual('bar', self.base_subject.extra_properties['foo'])
        self.assertEqual('ham', self.base_subject.extra_properties['spam'])
        self.assertEqual('baz', self.base_subject.extra_properties['frob'])
        self.assertEqual('ipsum', self.base_subject.extra_properties['lorem'])

        del self.subject.extra_properties['frob']
        del self.subject.extra_properties['lorem']
        self.subject_repo_proxy.save(self.subject)
        call_args = mock.call(self.base_subject, from_state=None)
        self.assertEqual(call_args, self.subject_repo_mock.save.call_args)
        self.assertEqual('bar', self.base_subject.extra_properties['foo'])
        self.assertEqual('ham', self.base_subject.extra_properties['spam'])
        self.assertNotIn('frob', self.base_subject.extra_properties)
        self.assertNotIn('lorem', self.base_subject.extra_properties)

    def test_quota_exceeded_after_delete_subject_properties(self):
        self.config(subject_property_quota=3)
        self.base_subject.extra_properties = {'foo': 'bar',
                                            'spam': 'ham',
                                            'frob': 'baz'}
        self.subject = subject.quota.SubjectProxy(self.base_subject,
                                                mock.Mock(),
                                                mock.Mock(),
                                                mock.Mock())
        self.config(subject_property_quota=1)
        del self.subject.extra_properties['foo']
        self.subject_repo_proxy.save(self.subject)
        self.subject_repo_mock.save.assert_called_once_with(self.base_subject,
                                                          from_state=None)
        self.assertNotIn('foo', self.base_subject.extra_properties)
        self.assertEqual('ham', self.base_subject.extra_properties['spam'])
        self.assertEqual('baz', self.base_subject.extra_properties['frob'])


class TestSubjectTagQuotas(test_utils.BaseTestCase):
    def setUp(self):
        super(TestSubjectTagQuotas, self).setUp()
        self.base_subject = mock.Mock()
        self.base_subject.tags = set([])
        self.base_subject.extra_properties = {}
        self.subject = subject.quota.SubjectProxy(self.base_subject,
                                                mock.Mock(),
                                                mock.Mock(),
                                                mock.Mock())

        self.subject_repo_mock = mock.Mock()
        self.subject_repo_proxy = subject.quota.SubjectRepoProxy(
            self.subject_repo_mock,
            mock.Mock(),
            mock.Mock(),
            mock.Mock())

    def test_replace_subject_tag(self):
        self.config(subject_tag_quota=1)
        self.subject.tags = ['foo']
        self.assertEqual(1, len(self.subject.tags))

    def test_replace_too_many_subject_tags(self):
        self.config(subject_tag_quota=0)

        exc = self.assertRaises(exception.SubjectTagLimitExceeded,
                                setattr, self.subject, 'tags', ['foo', 'bar'])
        self.assertIn('Attempted: 2, Maximum: 0',
                      encodeutils.exception_to_unicode(exc))
        self.assertEqual(0, len(self.subject.tags))

    def test_replace_unlimited_subject_tags(self):
        self.config(subject_tag_quota=-1)
        self.subject.tags = ['foo']
        self.assertEqual(1, len(self.subject.tags))

    def test_add_subject_tag(self):
        self.config(subject_tag_quota=1)
        self.subject.tags.add('foo')
        self.assertEqual(1, len(self.subject.tags))

    def test_add_too_many_subject_tags(self):
        self.config(subject_tag_quota=1)
        self.subject.tags.add('foo')
        exc = self.assertRaises(exception.SubjectTagLimitExceeded,
                                self.subject.tags.add, 'bar')
        self.assertIn('Attempted: 2, Maximum: 1',
                      encodeutils.exception_to_unicode(exc))

    def test_add_unlimited_subject_tags(self):
        self.config(subject_tag_quota=-1)
        self.subject.tags.add('foo')
        self.assertEqual(1, len(self.subject.tags))

    def test_remove_subject_tag_while_over_quota(self):
        self.config(subject_tag_quota=1)
        self.subject.tags.add('foo')
        self.assertEqual(1, len(self.subject.tags))
        self.config(subject_tag_quota=0)
        self.subject.tags.remove('foo')
        self.assertEqual(0, len(self.subject.tags))


class TestQuotaSubjectTagsProxy(test_utils.BaseTestCase):
    def setUp(self):
        super(TestQuotaSubjectTagsProxy, self).setUp()

    def test_add(self):
        proxy = subject.quota.QuotaSubjectTagsProxy(set([]))
        proxy.add('foo')
        self.assertIn('foo', proxy)

    def test_add_too_many_tags(self):
        self.config(subject_tag_quota=0)
        proxy = subject.quota.QuotaSubjectTagsProxy(set([]))
        exc = self.assertRaises(exception.SubjectTagLimitExceeded,
                                proxy.add, 'bar')
        self.assertIn('Attempted: 1, Maximum: 0',
                      encodeutils.exception_to_unicode(exc))

    def test_equals(self):
        proxy = subject.quota.QuotaSubjectTagsProxy(set([]))
        self.assertEqual(set([]), proxy)

    def test_not_equals(self):
        proxy = subject.quota.QuotaSubjectTagsProxy(set([]))
        self.assertNotEqual('foo', proxy)

    def test_contains(self):
        proxy = subject.quota.QuotaSubjectTagsProxy(set(['foo']))
        self.assertIn('foo', proxy)

    def test_len(self):
        proxy = subject.quota.QuotaSubjectTagsProxy(set(['foo',
                                                      'bar',
                                                      'baz',
                                                      'niz']))
        self.assertEqual(4, len(proxy))

    def test_iter(self):
        items = set(['foo', 'bar', 'baz', 'niz'])
        proxy = subject.quota.QuotaSubjectTagsProxy(items.copy())
        self.assertEqual(4, len(items))
        for item in proxy:
            items.remove(item)
        self.assertEqual(0, len(items))


class TestSubjectMemberQuotas(test_utils.BaseTestCase):
    def setUp(self):
        super(TestSubjectMemberQuotas, self).setUp()
        db_api = unit_test_utils.FakeDB()
        store_api = unit_test_utils.FakeStoreAPI()
        store = unit_test_utils.FakeStoreUtils(store_api)
        context = FakeContext()
        self.subject = mock.Mock()
        self.base_subject_member_factory = mock.Mock()
        self.subject_member_factory = subject.quota.SubjectMemberFactoryProxy(
            self.base_subject_member_factory, context,
            db_api, store)

    def test_new_subject_member(self):
        self.config(subject_member_quota=1)

        self.subject_member_factory.new_subject_member(self.subject,
                                                   'fake_id')
        nim = self.base_subject_member_factory.new_subject_member
        nim.assert_called_once_with(self.subject, 'fake_id')

    def test_new_subject_member_unlimited_members(self):
        self.config(subject_member_quota=-1)

        self.subject_member_factory.new_subject_member(self.subject,
                                                   'fake_id')
        nim = self.base_subject_member_factory.new_subject_member
        nim.assert_called_once_with(self.subject, 'fake_id')

    def test_new_subject_member_too_many_members(self):
        self.config(subject_member_quota=0)

        self.assertRaises(exception.SubjectMemberLimitExceeded,
                          self.subject_member_factory.new_subject_member,
                          self.subject, 'fake_id')


class TestSubjectLocationQuotas(test_utils.BaseTestCase):
    def setUp(self):
        super(TestSubjectLocationQuotas, self).setUp()
        self.base_subject = mock.Mock()
        self.base_subject.locations = []
        self.base_subject.size = 1
        self.base_subject.extra_properties = {}
        self.subject = subject.quota.SubjectProxy(self.base_subject,
                                                mock.Mock(),
                                                mock.Mock(),
                                                mock.Mock())

        self.subject_repo_mock = mock.Mock()
        self.subject_repo_proxy = subject.quota.SubjectRepoProxy(
            self.subject_repo_mock,
            mock.Mock(),
            mock.Mock(),
            mock.Mock())

    def test_replace_subject_location(self):
        self.config(subject_location_quota=1)
        self.subject.locations = [{"url": "file:///fake.img.tar.gz",
                                 "metadata": {}
                                 }]
        self.assertEqual(1, len(self.subject.locations))

    def test_replace_too_many_subject_locations(self):
        self.config(subject_location_quota=1)
        self.subject.locations = [{"url": "file:///fake.img.tar.gz",
                                 "metadata": {}}
                                ]
        locations = [
            {"url": "file:///fake1.img.tar.gz", "metadata": {}},
            {"url": "file:///fake2.img.tar.gz", "metadata": {}},
            {"url": "file:///fake3.img.tar.gz", "metadata": {}}
        ]
        exc = self.assertRaises(exception.SubjectLocationLimitExceeded,
                                setattr, self.subject, 'locations', locations)
        self.assertIn('Attempted: 3, Maximum: 1',
                      encodeutils.exception_to_unicode(exc))
        self.assertEqual(1, len(self.subject.locations))

    def test_replace_unlimited_subject_locations(self):
        self.config(subject_location_quota=-1)
        self.subject.locations = [{"url": "file:///fake.img.tar.gz",
                                 "metadata": {}}
                                ]
        self.assertEqual(1, len(self.subject.locations))

    def test_add_subject_location(self):
        self.config(subject_location_quota=1)
        location = {"url": "file:///fake.img.tar.gz", "metadata": {}}
        self.subject.locations.append(location)
        self.assertEqual(1, len(self.subject.locations))

    def test_add_too_many_subject_locations(self):
        self.config(subject_location_quota=1)
        location1 = {"url": "file:///fake1.img.tar.gz", "metadata": {}}
        self.subject.locations.append(location1)
        location2 = {"url": "file:///fake2.img.tar.gz", "metadata": {}}
        exc = self.assertRaises(exception.SubjectLocationLimitExceeded,
                                self.subject.locations.append, location2)
        self.assertIn('Attempted: 2, Maximum: 1',
                      encodeutils.exception_to_unicode(exc))

    def test_add_unlimited_subject_locations(self):
        self.config(subject_location_quota=-1)
        location1 = {"url": "file:///fake1.img.tar.gz", "metadata": {}}
        self.subject.locations.append(location1)
        self.assertEqual(1, len(self.subject.locations))

    def test_remove_subject_location_while_over_quota(self):
        self.config(subject_location_quota=1)
        location1 = {"url": "file:///fake1.img.tar.gz", "metadata": {}}
        self.subject.locations.append(location1)
        self.assertEqual(1, len(self.subject.locations))
        self.config(subject_location_quota=0)
        self.subject.locations.remove(location1)
        self.assertEqual(0, len(self.subject.locations))
