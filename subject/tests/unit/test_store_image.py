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
from cursive import exception as cursive_exception
from cursive import signature_utils
import glance_store
import mock

from subject.common import exception
import subject.location
from subject.tests.unit import base as unit_test_base
from subject.tests.unit import utils as unit_test_utils
from subject.tests import utils


BASE_URI = 'http://storeurl.com/container'
UUID1 = 'c80a1a6c-bd1f-41c5-90ee-81afedb1d58d'
UUID2 = '971ec09a-8067-4bc8-a91f-ae3557f1c4c7'
USER1 = '54492ba0-f4df-4e4e-be62-27f4d76b29cf'
TENANT1 = '6838eb7b-6ded-434a-882c-b344c77fe8df'
TENANT2 = '2c014f32-55eb-467d-8fcb-4bd706012f81'
TENANT3 = '228c6da5-29cd-4d67-9457-ed632e083fc0'


class ImageRepoStub(object):
    def add(self, subject):
        return subject

    def save(self, subject, from_state=None):
        return subject


class ImageStub(object):
    def __init__(self, subject_id, status=None, locations=None,
                 visibility=None, extra_properties=None):
        self.subject_id = subject_id
        self.status = status
        self.locations = locations or []
        self.visibility = visibility
        self.size = 1
        self.extra_properties = extra_properties or {}

    def delete(self):
        self.status = 'deleted'

    def get_member_repo(self):
        return FakeMemberRepo(self, [TENANT1, TENANT2])


class ImageFactoryStub(object):
    def new_subject(self, subject_id=None, name=None, visibility='private',
                  min_disk=0, min_ram=0, protected=False, owner=None,
                  disk_format=None, container_format=None,
                  extra_properties=None, tags=None, **other_args):
        return ImageStub(subject_id, visibility=visibility,
                         extra_properties=extra_properties, **other_args)


class FakeMemberRepo(object):
    def __init__(self, subject, tenants=None):
        self.subject = subject
        self.factory = subject.domain.ImageMemberFactory()
        self.tenants = tenants or []

    def list(self, *args, **kwargs):
        return [self.factory.new_subject_member(self.subject, tenant)
                for tenant in self.tenants]

    def add(self, member):
        self.tenants.append(member.member_id)

    def remove(self, member):
        self.tenants.remove(member.member_id)


class TestStoreImage(utils.BaseTestCase):
    def setUp(self):
        locations = [{'url': '%s/%s' % (BASE_URI, UUID1),
                      'metadata': {}, 'status': 'active'}]
        self.subject_stub = ImageStub(UUID1, 'active', locations)
        self.store_api = unit_test_utils.FakeStoreAPI()
        self.store_utils = unit_test_utils.FakeStoreUtils(self.store_api)
        super(TestStoreImage, self).setUp()

    def test_subject_delete(self):
        subject = subject.location.SubjectProxy(self.subject_stub, {},
                                              self.store_api, self.store_utils)
        location = subject.locations[0]
        self.assertEqual('active', subject.status)
        self.store_api.get_from_backend(location['url'], context={})
        subject.delete()
        self.assertEqual('deleted', subject.status)
        self.assertRaises(glance_store.NotFound,
                          self.store_api.get_from_backend, location['url'], {})

    def test_subject_get_data(self):
        subject = subject.location.SubjectProxy(self.subject_stub, {},
                                              self.store_api, self.store_utils)
        self.assertEqual('XXX', subject.get_data())

    def test_subject_get_data_from_second_location(self):
        def fake_get_from_backend(self, location, offset=0,
                                  chunk_size=None, context=None):
            if UUID1 in location:
                raise Exception('not allow download from %s' % location)
            else:
                return self.data[location]

        subject1 = subject.location.SubjectProxy(self.subject_stub, {},
                                               self.store_api, self.store_utils)
        self.assertEqual('XXX', subject1.get_data())
        # Multiple location support
        context = subject.context.RequestContext(user=USER1)
        (subject2, subject_stub2) = self._add_subject(context, UUID2, 'ZZZ', 3)
        location_data = subject2.locations[0]
        subject1.locations.append(location_data)
        self.assertEqual(2, len(subject1.locations))
        self.assertEqual(UUID2, location_data['url'])

        self.stubs.Set(unit_test_utils.FakeStoreAPI, 'get_from_backend',
                       fake_get_from_backend)
        # This time, subject1.get_data() returns the data wrapped in a
        # LimitingReader|CooperativeReader pipeline, so peeking under
        # the hood of those objects to get at the underlying string.
        self.assertEqual('ZZZ', subject1.get_data().data.fd)

        subject1.locations.pop(0)
        self.assertEqual(1, len(subject1.locations))
        subject2.delete()

    def test_subject_set_data(self):
        context = subject.context.RequestContext(user=USER1)
        subject_stub = ImageStub(UUID2, status='queued', locations=[])
        subject = subject.location.SubjectProxy(subject_stub, context,
                                              self.store_api, self.store_utils)
        subject.set_data('YYYY', 4)
        self.assertEqual(4, subject.size)
        # NOTE(markwash): FakeStore returns subject_id for location
        self.assertEqual(UUID2, subject.locations[0]['url'])
        self.assertEqual('Z', subject.checksum)
        self.assertEqual('active', subject.status)

    def test_subject_set_data_location_metadata(self):
        context = subject.context.RequestContext(user=USER1)
        subject_stub = ImageStub(UUID2, status='queued', locations=[])
        loc_meta = {'key': 'value5032'}
        store_api = unit_test_utils.FakeStoreAPI(store_metadata=loc_meta)
        store_utils = unit_test_utils.FakeStoreUtils(store_api)
        subject = subject.location.SubjectProxy(subject_stub, context,
                                              store_api, store_utils)
        subject.set_data('YYYY', 4)
        self.assertEqual(4, subject.size)
        location_data = subject.locations[0]
        self.assertEqual(UUID2, location_data['url'])
        self.assertEqual(loc_meta, location_data['metadata'])
        self.assertEqual('Z', subject.checksum)
        self.assertEqual('active', subject.status)
        subject.delete()
        self.assertEqual(subject.status, 'deleted')
        self.assertRaises(glance_store.NotFound,
                          self.store_api.get_from_backend,
                          subject.locations[0]['url'], {})

    def test_subject_set_data_unknown_size(self):
        context = subject.context.RequestContext(user=USER1)
        subject_stub = ImageStub(UUID2, status='queued', locations=[])
        subject = subject.location.SubjectProxy(subject_stub, context,
                                              self.store_api, self.store_utils)
        subject.set_data('YYYY', None)
        self.assertEqual(4, subject.size)
        # NOTE(markwash): FakeStore returns subject_id for location
        self.assertEqual(UUID2, subject.locations[0]['url'])
        self.assertEqual('Z', subject.checksum)
        self.assertEqual('active', subject.status)
        subject.delete()
        self.assertEqual(subject.status, 'deleted')
        self.assertRaises(glance_store.NotFound,
                          self.store_api.get_from_backend,
                          subject.locations[0]['url'], context={})

    @mock.patch('subject.location.LOG')
    def test_subject_set_data_valid_signature(self, mock_log):
        context = subject.context.RequestContext(user=USER1)
        extra_properties = {
            'img_signature_certificate_uuid': 'UUID',
            'img_signature_hash_method': 'METHOD',
            'img_signature_key_type': 'TYPE',
            'img_signature': 'VALID'
        }
        subject_stub = ImageStub(UUID2, status='queued',
                               extra_properties=extra_properties)
        self.stubs.Set(signature_utils, 'get_verifier',
                       unit_test_utils.fake_get_verifier)
        subject = subject.location.SubjectProxy(subject_stub, context,
                                              self.store_api, self.store_utils)
        subject.set_data('YYYY', 4)
        self.assertEqual('active', subject.status)
        mock_log.info.assert_called_once_with(
            u'Successfully verified signature for subject %s',
            UUID2)

    def test_subject_set_data_invalid_signature(self):
        context = subject.context.RequestContext(user=USER1)
        extra_properties = {
            'img_signature_certificate_uuid': 'UUID',
            'img_signature_hash_method': 'METHOD',
            'img_signature_key_type': 'TYPE',
            'img_signature': 'INVALID'
        }
        subject_stub = ImageStub(UUID2, status='queued',
                               extra_properties=extra_properties)
        self.stubs.Set(signature_utils, 'get_verifier',
                       unit_test_utils.fake_get_verifier)
        subject = subject.location.SubjectProxy(subject_stub, context,
                                              self.store_api, self.store_utils)
        self.assertRaises(cursive_exception.SignatureVerificationError,
                          subject.set_data,
                          'YYYY', 4)

    def test_subject_set_data_invalid_signature_missing_metadata(self):
        context = subject.context.RequestContext(user=USER1)
        extra_properties = {
            'img_signature_hash_method': 'METHOD',
            'img_signature_key_type': 'TYPE',
            'img_signature': 'INVALID'
        }
        subject_stub = ImageStub(UUID2, status='queued',
                               extra_properties=extra_properties)
        self.stubs.Set(signature_utils, 'get_verifier',
                       unit_test_utils.fake_get_verifier)
        subject = subject.location.SubjectProxy(subject_stub, context,
                                              self.store_api, self.store_utils)
        subject.set_data('YYYY', 4)
        self.assertEqual(UUID2, subject.locations[0]['url'])
        self.assertEqual('Z', subject.checksum)
        # Subject is still active, since invalid signature was ignored
        self.assertEqual('active', subject.status)

    def _add_subject(self, context, subject_id, data, len):
        subject_stub = ImageStub(subject_id, status='queued', locations=[])
        subject = subject.location.SubjectProxy(subject_stub, context,
                                              self.store_api, self.store_utils)
        subject.set_data(data, len)
        self.assertEqual(len, subject.size)
        # NOTE(markwash): FakeStore returns subject_id for location
        location = {'url': subject_id, 'metadata': {}, 'status': 'active'}
        self.assertEqual([location], subject.locations)
        self.assertEqual([location], subject_stub.locations)
        self.assertEqual('active', subject.status)
        return (subject, subject_stub)

    def test_subject_change_append_invalid_location_uri(self):
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)

        location_bad = {'url': 'unknown://location', 'metadata': {}}
        self.assertRaises(exception.BadStoreUri,
                          subject1.locations.append, location_bad)

        subject1.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())

    def test_subject_change_append_invalid_location_metatdata(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        # Using only one test rule here is enough to make sure
        # 'store.check_location_metadata()' can be triggered
        # in Location proxy layer. Complete test rule for
        # 'store.check_location_metadata()' testing please
        # check below cases within 'TestStoreMetaDataChecker'.
        location_bad = {'url': UUID3, 'metadata': b"a invalid metadata"}

        self.assertRaises(glance_store.BackendException,
                          subject1.locations.append, location_bad)

        subject1.delete()
        subject2.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

    def test_subject_change_append_locations(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        location2 = {'url': UUID2, 'metadata': {}, 'status': 'active'}
        location3 = {'url': UUID3, 'metadata': {}, 'status': 'active'}

        subject1.locations.append(location3)

        self.assertEqual([location2, location3], subject_stub1.locations)
        self.assertEqual([location2, location3], subject1.locations)

        subject1.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

        subject2.delete()

    def test_subject_change_pop_location(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        location2 = {'url': UUID2, 'metadata': {}, 'status': 'active'}
        location3 = {'url': UUID3, 'metadata': {}, 'status': 'active'}

        subject1.locations.append(location3)

        self.assertEqual([location2, location3], subject_stub1.locations)
        self.assertEqual([location2, location3], subject1.locations)

        subject1.locations.pop()

        self.assertEqual([location2], subject_stub1.locations)
        self.assertEqual([location2], subject1.locations)

        subject1.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

        subject2.delete()

    def test_subject_change_extend_invalid_locations_uri(self):
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)

        location_bad = {'url': 'unknown://location', 'metadata': {}}

        self.assertRaises(exception.BadStoreUri,
                          subject1.locations.extend, [location_bad])

        subject1.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())

    def test_subject_change_extend_invalid_locations_metadata(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        location_bad = {'url': UUID3, 'metadata': b"a invalid metadata"}

        self.assertRaises(glance_store.BackendException,
                          subject1.locations.extend, [location_bad])

        subject1.delete()
        subject2.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

    def test_subject_change_extend_locations(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        location2 = {'url': UUID2, 'metadata': {}, 'status': 'active'}
        location3 = {'url': UUID3, 'metadata': {}, 'status': 'active'}

        subject1.locations.extend([location3])

        self.assertEqual([location2, location3], subject_stub1.locations)
        self.assertEqual([location2, location3], subject1.locations)

        subject1.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

        subject2.delete()

    def test_subject_change_remove_location(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        location2 = {'url': UUID2, 'metadata': {}, 'status': 'active'}
        location3 = {'url': UUID3, 'metadata': {}, 'status': 'active'}
        location_bad = {'url': 'unknown://location', 'metadata': {}}

        subject1.locations.extend([location3])
        subject1.locations.remove(location2)

        self.assertEqual([location3], subject_stub1.locations)
        self.assertEqual([location3], subject1.locations)
        self.assertRaises(ValueError,
                          subject1.locations.remove, location_bad)

        subject1.delete()
        subject2.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

    def test_subject_change_delete_location(self):
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)

        del subject1.locations[0]

        self.assertEqual([], subject_stub1.locations)
        self.assertEqual(0, len(subject1.locations))

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())

        subject1.delete()

    def test_subject_change_insert_invalid_location_uri(self):
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)

        location_bad = {'url': 'unknown://location', 'metadata': {}}
        self.assertRaises(exception.BadStoreUri,
                          subject1.locations.insert, 0, location_bad)

        subject1.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())

    def test_subject_change_insert_invalid_location_metadata(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        location_bad = {'url': UUID3, 'metadata': b"a invalid metadata"}

        self.assertRaises(glance_store.BackendException,
                          subject1.locations.insert, 0, location_bad)

        subject1.delete()
        subject2.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

    def test_subject_change_insert_location(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        location2 = {'url': UUID2, 'metadata': {}, 'status': 'active'}
        location3 = {'url': UUID3, 'metadata': {}, 'status': 'active'}

        subject1.locations.insert(0, location3)

        self.assertEqual([location3, location2], subject_stub1.locations)
        self.assertEqual([location3, location2], subject1.locations)

        subject1.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

        subject2.delete()

    def test_subject_change_delete_locations(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        location2 = {'url': UUID2, 'metadata': {}}
        location3 = {'url': UUID3, 'metadata': {}}

        subject1.locations.insert(0, location3)
        del subject1.locations[0:100]

        self.assertEqual([], subject_stub1.locations)
        self.assertEqual(0, len(subject1.locations))
        self.assertRaises(exception.BadStoreUri,
                          subject1.locations.insert, 0, location2)
        self.assertRaises(exception.BadStoreUri,
                          subject2.locations.insert, 0, location3)

        subject1.delete()
        subject2.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

    def test_subject_change_adding_invalid_location_uri(self):
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        subject_stub1 = ImageStub('fake_subject_id', status='queued', locations=[])
        subject1 = subject.location.SubjectProxy(subject_stub1, context,
                                               self.store_api, self.store_utils)

        location_bad = {'url': 'unknown://location', 'metadata': {}}

        self.assertRaises(exception.BadStoreUri,
                          subject1.locations.__iadd__, [location_bad])
        self.assertEqual([], subject_stub1.locations)
        self.assertEqual([], subject1.locations)

        subject1.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())

    def test_subject_change_adding_invalid_location_metadata(self):
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)

        subject_stub2 = ImageStub('fake_subject_id', status='queued', locations=[])
        subject2 = subject.location.SubjectProxy(subject_stub2, context,
                                               self.store_api, self.store_utils)

        location_bad = {'url': UUID2, 'metadata': b"a invalid metadata"}

        self.assertRaises(glance_store.BackendException,
                          subject2.locations.__iadd__, [location_bad])
        self.assertEqual([], subject_stub2.locations)
        self.assertEqual([], subject2.locations)

        subject1.delete()
        subject2.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())

    def test_subject_change_adding_locations(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        subject_stub3 = ImageStub('fake_subject_id', status='queued', locations=[])
        subject3 = subject.location.SubjectProxy(subject_stub3, context,
                                               self.store_api, self.store_utils)

        location2 = {'url': UUID2, 'metadata': {}}
        location3 = {'url': UUID3, 'metadata': {}}

        subject3.locations += [location2, location3]

        self.assertEqual([location2, location3], subject_stub3.locations)
        self.assertEqual([location2, location3], subject3.locations)

        subject3.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

        subject1.delete()
        subject2.delete()

    def test_subject_get_location_index(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)
        subject_stub3 = ImageStub('fake_subject_id', status='queued', locations=[])

        subject3 = subject.location.SubjectProxy(subject_stub3, context,
                                               self.store_api, self.store_utils)

        location2 = {'url': UUID2, 'metadata': {}}
        location3 = {'url': UUID3, 'metadata': {}}

        subject3.locations += [location2, location3]

        self.assertEqual(1, subject_stub3.locations.index(location3))

        subject3.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

        subject1.delete()
        subject2.delete()

    def test_subject_get_location_by_index(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)
        subject_stub3 = ImageStub('fake_subject_id', status='queued', locations=[])
        subject3 = subject.location.SubjectProxy(subject_stub3, context,
                                               self.store_api, self.store_utils)

        location2 = {'url': UUID2, 'metadata': {}}
        location3 = {'url': UUID3, 'metadata': {}}

        subject3.locations += [location2, location3]

        self.assertEqual(1, subject_stub3.locations.index(location3))
        self.assertEqual(location2, subject_stub3.locations[0])

        subject3.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

        subject1.delete()
        subject2.delete()

    def test_subject_checking_location_exists(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        subject_stub3 = ImageStub('fake_subject_id', status='queued', locations=[])
        subject3 = subject.location.SubjectProxy(subject_stub3, context,
                                               self.store_api, self.store_utils)

        location2 = {'url': UUID2, 'metadata': {}}
        location3 = {'url': UUID3, 'metadata': {}}
        location_bad = {'url': 'unknown://location', 'metadata': {}}

        subject3.locations += [location2, location3]

        self.assertIn(location3, subject_stub3.locations)
        self.assertNotIn(location_bad, subject_stub3.locations)

        subject3.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

        subject1.delete()
        subject2.delete()

    def test_subject_reverse_locations_order(self):
        UUID3 = 'a8a61ec4-d7a3-11e2-8c28-000c29c27581'
        self.assertEqual(2, len(self.store_api.data.keys()))

        context = subject.context.RequestContext(user=USER1)
        (subject1, subject_stub1) = self._add_subject(context, UUID2, 'XXXX', 4)
        (subject2, subject_stub2) = self._add_subject(context, UUID3, 'YYYY', 4)

        location2 = {'url': UUID2, 'metadata': {}}
        location3 = {'url': UUID3, 'metadata': {}}

        subject_stub3 = ImageStub('fake_subject_id', status='queued', locations=[])
        subject3 = subject.location.SubjectProxy(subject_stub3, context,
                                               self.store_api, self.store_utils)
        subject3.locations += [location2, location3]

        subject_stub3.locations.reverse()

        self.assertEqual([location3, location2], subject_stub3.locations)
        self.assertEqual([location3, location2], subject3.locations)

        subject3.delete()

        self.assertEqual(2, len(self.store_api.data.keys()))
        self.assertNotIn(UUID2, self.store_api.data.keys())
        self.assertNotIn(UUID3, self.store_api.data.keys())

        subject1.delete()
        subject2.delete()


class TestStoreImageRepo(utils.BaseTestCase):
    def setUp(self):
        super(TestStoreImageRepo, self).setUp()
        self.store_api = unit_test_utils.FakeStoreAPI()
        store_utils = unit_test_utils.FakeStoreUtils(self.store_api)
        self.subject_stub = ImageStub(UUID1)
        self.subject = subject.location.SubjectProxy(self.subject_stub, {},
                                                   self.store_api, store_utils)
        self.subject_repo_stub = ImageRepoStub()
        self.subject_repo = subject.location.SubjectRepoProxy(self.subject_repo_stub,
                                                            {}, self.store_api,
                                                            store_utils)
        patcher = mock.patch("subject.location._get_member_repo_for_store",
                             self.get_fake_member_repo)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake_member_repo = FakeMemberRepo(self.subject, [TENANT1, TENANT2])
        self.subject_member_repo = subject.location.ImageMemberRepoProxy(
            self.fake_member_repo,
            self.subject,
            {}, self.store_api)

    def get_fake_member_repo(self, subject, context, db_api, store_api):
        return FakeMemberRepo(self.subject, [TENANT1, TENANT2])

    def test_add_updates_acls(self):
        self.subject_stub.locations = [{'url': 'foo', 'metadata': {},
                                      'status': 'active'},
                                     {'url': 'bar', 'metadata': {},
                                      'status': 'active'}]
        self.subject_stub.visibility = 'public'
        self.subject_repo.add(self.subject)
        self.assertTrue(self.store_api.acls['foo']['public'])
        self.assertEqual([], self.store_api.acls['foo']['read'])
        self.assertEqual([], self.store_api.acls['foo']['write'])
        self.assertTrue(self.store_api.acls['bar']['public'])
        self.assertEqual([], self.store_api.acls['bar']['read'])
        self.assertEqual([], self.store_api.acls['bar']['write'])

    def test_add_ignores_acls_if_no_locations(self):
        self.subject_stub.locations = []
        self.subject_stub.visibility = 'public'
        self.subject_repo.add(self.subject)
        self.assertEqual(0, len(self.store_api.acls))

    def test_save_updates_acls(self):
        self.subject_stub.locations = [{'url': 'foo', 'metadata': {},
                                      'status': 'active'}]
        self.subject_repo.save(self.subject)
        self.assertIn('foo', self.store_api.acls)

    def test_add_fetches_members_if_private(self):
        self.subject_stub.locations = [{'url': 'glue', 'metadata': {},
                                      'status': 'active'}]
        self.subject_stub.visibility = 'private'
        self.subject_repo.add(self.subject)
        self.assertIn('glue', self.store_api.acls)
        acls = self.store_api.acls['glue']
        self.assertFalse(acls['public'])
        self.assertEqual([], acls['write'])
        self.assertEqual([TENANT1, TENANT2], acls['read'])

    def test_save_fetches_members_if_private(self):
        self.subject_stub.locations = [{'url': 'glue', 'metadata': {},
                                      'status': 'active'}]
        self.subject_stub.visibility = 'private'
        self.subject_repo.save(self.subject)
        self.assertIn('glue', self.store_api.acls)
        acls = self.store_api.acls['glue']
        self.assertFalse(acls['public'])
        self.assertEqual([], acls['write'])
        self.assertEqual([TENANT1, TENANT2], acls['read'])

    def test_member_addition_updates_acls(self):
        self.subject_stub.locations = [{'url': 'glug', 'metadata': {},
                                      'status': 'active'}]
        self.subject_stub.visibility = 'private'
        membership = subject.domain.ImageMembership(
            UUID1, TENANT3, None, None, status='accepted')
        self.subject_member_repo.add(membership)
        self.assertIn('glug', self.store_api.acls)
        acls = self.store_api.acls['glug']
        self.assertFalse(acls['public'])
        self.assertEqual([], acls['write'])
        self.assertEqual([TENANT1, TENANT2, TENANT3], acls['read'])

    def test_member_removal_updates_acls(self):
        self.subject_stub.locations = [{'url': 'glug', 'metadata': {},
                                      'status': 'active'}]
        self.subject_stub.visibility = 'private'
        membership = subject.domain.ImageMembership(
            UUID1, TENANT1, None, None, status='accepted')
        self.subject_member_repo.remove(membership)
        self.assertIn('glug', self.store_api.acls)
        acls = self.store_api.acls['glug']
        self.assertFalse(acls['public'])
        self.assertEqual([], acls['write'])
        self.assertEqual([TENANT2], acls['read'])


class TestImageFactory(unit_test_base.StoreClearingUnitTest):

    def setUp(self):
        super(TestImageFactory, self).setUp()
        store_api = unit_test_utils.FakeStoreAPI()
        store_utils = unit_test_utils.FakeStoreUtils(store_api)
        self.subject_factory = subject.location.SubjectFactoryProxy(
            ImageFactoryStub(),
            subject.context.RequestContext(user=USER1),
            store_api,
            store_utils)

    def test_new_subject(self):
        subject = self.subject_factory.new_subject()
        self.assertIsNone(subject.subject_id)
        self.assertIsNone(subject.status)
        self.assertEqual('private', subject.visibility)
        self.assertEqual([], subject.locations)

    def test_new_subject_with_location(self):
        locations = [{'url': '%s/%s' % (BASE_URI, UUID1),
                      'metadata': {}}]
        subject = self.subject_factory.new_subject(locations=locations)
        self.assertEqual(locations, subject.locations)
        location_bad = {'url': 'unknown://location', 'metadata': {}}
        self.assertRaises(exception.BadStoreUri,
                          self.subject_factory.new_subject,
                          locations=[location_bad])


class TestStoreMetaDataChecker(utils.BaseTestCase):

    def test_empty(self):
        glance_store.check_location_metadata({})

    def test_unicode(self):
        m = {'key': u'somevalue'}
        glance_store.check_location_metadata(m)

    def test_unicode_list(self):
        m = {'key': [u'somevalue', u'2']}
        glance_store.check_location_metadata(m)

    def test_unicode_dict(self):
        inner = {'key1': u'somevalue', 'key2': u'somevalue'}
        m = {'topkey': inner}
        glance_store.check_location_metadata(m)

    def test_unicode_dict_list(self):
        inner = {'key1': u'somevalue', 'key2': u'somevalue'}
        m = {'topkey': inner, 'list': [u'somevalue', u'2'], 'u': u'2'}
        glance_store.check_location_metadata(m)

    def test_nested_dict(self):
        inner = {'key1': u'somevalue', 'key2': u'somevalue'}
        inner = {'newkey': inner}
        inner = {'anotherkey': inner}
        m = {'topkey': inner}
        glance_store.check_location_metadata(m)

    def test_simple_bad(self):
        m = {'key1': object()}
        self.assertRaises(glance_store.BackendException,
                          glance_store.check_location_metadata,
                          m)

    def test_list_bad(self):
        m = {'key1': [u'somevalue', object()]}
        self.assertRaises(glance_store.BackendException,
                          glance_store.check_location_metadata,
                          m)

    def test_nested_dict_bad(self):
        inner = {'key1': u'somevalue', 'key2': object()}
        inner = {'newkey': inner}
        inner = {'anotherkey': inner}
        m = {'topkey': inner}

        self.assertRaises(glance_store.BackendException,
                          glance_store.check_location_metadata,
                          m)
