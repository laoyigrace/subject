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
import uuid

from cursive import exception as cursive_exception
import glance_store
import mock
import six
import webob

import subject.api.policy
import subject.api.v2.subject_data
from subject.common import exception
from subject.common import wsgi
from subject.tests.unit import base
import subject.tests.unit.utils as unit_test_utils
import subject.tests.utils as test_utils


class Raise(object):
    def __init__(self, exc):
        self.exc = exc

    def __call__(self, *args, **kwargs):
        raise self.exc


class FakeSubject(object):
    def __init__(self, subject_id=None, data=None, checksum=None, size=0,
                 virtual_size=0, locations=None, container_format='bear',
                 disk_format='rawr', status=None):
        self.subject_id = subject_id
        self.data = data
        self.checksum = checksum
        self.size = size
        self.virtual_size = virtual_size
        self.locations = locations
        self.container_format = container_format
        self.disk_format = disk_format
        self._status = status

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        if isinstance(self._status, BaseException):
            raise self._status
        else:
            self._status = value

    def get_data(self, *args, **kwargs):
        return self.data

    def set_data(self, data, size=None):
        self.data = ''.join(data)
        self.size = size
        self.status = 'modified-by-fake'


class FakeSubjectRepo(object):
    def __init__(self, result=None):
        self.result = result

    def get(self, subject_id):
        if isinstance(self.result, BaseException):
            raise self.result
        else:
            return self.result

    def save(self, subject, from_state=None):
        self.saved_subject = subject


class FakeGateway(object):
    def __init__(self, repo):
        self.repo = repo

    def get_repo(self, context):
        return self.repo


class TestSubjectsController(base.StoreClearingUnitTest):
    def setUp(self):
        super(TestSubjectsController, self).setUp()

        self.config(debug=True)
        self.subject_repo = FakeSubjectRepo()
        self.gateway = FakeGateway(self.subject_repo)
        self.controller = subject.api.v2.subject_data.SubjectDataController(
            gateway=self.gateway)

    def test_download(self):
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('abcd',
                          locations=[{'url': 'http://example.com/subject',
                                      'metadata': {}, 'status': 'active'}])
        self.subject_repo.result = subject
        subject = self.controller.download(request, unit_test_utils.UUID1)
        self.assertEqual('abcd', subject.subject_id)

    def test_download_deactivated(self):
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('abcd',
                          status='deactivated',
                          locations=[{'url': 'http://example.com/subject',
                                      'metadata': {}, 'status': 'active'}])
        self.subject_repo.result = subject
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.download,
                          request, str(uuid.uuid4()))

    def test_download_no_location(self):
        # NOTE(mclaren): NoContent will be raised by the ResponseSerializer
        # That's tested below.
        request = unit_test_utils.get_fake_request()
        self.subject_repo.result = FakeSubject('abcd')
        subject = self.controller.download(request, unit_test_utils.UUID2)
        self.assertEqual('abcd', subject.subject_id)

    def test_download_non_existent_subject(self):
        request = unit_test_utils.get_fake_request()
        self.subject_repo.result = exception.NotFound()
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.download,
                          request, str(uuid.uuid4()))

    def test_download_forbidden(self):
        request = unit_test_utils.get_fake_request()
        self.subject_repo.result = exception.Forbidden()
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.download,
                          request, str(uuid.uuid4()))

    def test_download_ok_when_get_subject_location_forbidden(self):
        class SubjectLocations(object):
            def __len__(self):
                raise exception.Forbidden()

        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('abcd')
        self.subject_repo.result = subject
        subject.locations = SubjectLocations()
        subject = self.controller.download(request, unit_test_utils.UUID1)
        self.assertEqual('abcd', subject.subject_id)

    def test_upload(self):
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('abcd')
        self.subject_repo.result = subject
        self.controller.upload(request, unit_test_utils.UUID2, 'YYYY', 4)
        self.assertEqual('YYYY', subject.data)
        self.assertEqual(4, subject.size)

    def test_upload_status(self):
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('abcd')
        self.subject_repo.result = subject
        insurance = {'called': False}

        def read_data():
            insurance['called'] = True
            self.assertEqual('saving', self.subject_repo.saved_subject.status)
            yield 'YYYY'

        self.controller.upload(request, unit_test_utils.UUID2,
                               read_data(), None)
        self.assertTrue(insurance['called'])
        self.assertEqual('modified-by-fake',
                         self.subject_repo.saved_subject.status)

    def test_upload_no_size(self):
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('abcd')
        self.subject_repo.result = subject
        self.controller.upload(request, unit_test_utils.UUID2, 'YYYY', None)
        self.assertEqual('YYYY', subject.data)
        self.assertIsNone(subject.size)

    def test_upload_invalid(self):
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('abcd')
        subject.status = ValueError()
        self.subject_repo.result = subject
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.upload,
                          request, unit_test_utils.UUID1, 'YYYY', 4)

    def test_upload_with_expired_token(self):
        def side_effect(subject, from_state=None):
            if from_state == 'saving':
                raise exception.NotAuthenticated()

        mocked_save = mock.Mock(side_effect=side_effect)
        mocked_delete = mock.Mock()
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('abcd')
        subject.delete = mocked_delete
        self.subject_repo.result = subject
        self.subject_repo.save = mocked_save
        self.assertRaises(webob.exc.HTTPUnauthorized, self.controller.upload,
                          request, unit_test_utils.UUID1, 'YYYY', 4)
        self.assertEqual(3, mocked_save.call_count)
        mocked_delete.assert_called_once_with()

    def test_upload_non_existent_subject_during_save_initiates_deletion(self):
        def fake_save_not_found(self, from_state=None):
            raise exception.SubjectNotFound()

        def fake_save_conflict(self, from_state=None):
            raise exception.Conflict()

        for fun in [fake_save_not_found, fake_save_conflict]:
            request = unit_test_utils.get_fake_request()
            subject = FakeSubject('abcd', locations=['http://example.com/subject'])
            self.subject_repo.result = subject
            self.subject_repo.save = fun
            subject.delete = mock.Mock()
            self.assertRaises(webob.exc.HTTPGone, self.controller.upload,
                              request, str(uuid.uuid4()), 'ABC', 3)
            self.assertTrue(subject.delete.called)

    def test_upload_non_existent_subject_raises_subject_not_found_exception(self):
        def fake_save(self, from_state=None):
            raise exception.SubjectNotFound()

        def fake_delete():
            raise exception.SubjectNotFound()

        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('abcd', locations=['http://example.com/subject'])
        self.subject_repo.result = subject
        self.subject_repo.save = fake_save
        subject.delete = fake_delete
        self.assertRaises(webob.exc.HTTPGone, self.controller.upload,
                          request, str(uuid.uuid4()), 'ABC', 3)

    def test_upload_non_existent_subject_raises_store_not_found_exception(self):
        def fake_save(self, from_state=None):
            raise glance_store.NotFound()

        def fake_delete():
            raise exception.SubjectNotFound()

        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('abcd', locations=['http://example.com/subject'])
        self.subject_repo.result = subject
        self.subject_repo.save = fake_save
        subject.delete = fake_delete
        self.assertRaises(webob.exc.HTTPGone, self.controller.upload,
                          request, str(uuid.uuid4()), 'ABC', 3)

    def test_upload_non_existent_subject_before_save(self):
        request = unit_test_utils.get_fake_request()
        self.subject_repo.result = exception.NotFound()
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.upload,
                          request, str(uuid.uuid4()), 'ABC', 3)

    def test_upload_data_exists(self):
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject()
        exc = exception.InvalidSubjectStatusTransition(cur_status='active',
                                                     new_status='queued')
        subject.set_data = Raise(exc)
        self.subject_repo.result = subject
        self.assertRaises(webob.exc.HTTPConflict, self.controller.upload,
                          request, unit_test_utils.UUID1, 'YYYY', 4)

    def test_upload_storage_full(self):
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject()
        subject.set_data = Raise(glance_store.StorageFull)
        self.subject_repo.result = subject
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.upload,
                          request, unit_test_utils.UUID2, 'YYYYYYY', 7)

    def test_upload_signature_verification_fails(self):
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject()
        subject.set_data = Raise(cursive_exception.SignatureVerificationError)
        self.subject_repo.result = subject
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.upload,
                          request, unit_test_utils.UUID1, 'YYYY', 4)
        self.assertEqual('killed', self.subject_repo.saved_subject.status)

    def test_subject_size_limit_exceeded(self):
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject()
        subject.set_data = Raise(exception.SubjectSizeLimitExceeded)
        self.subject_repo.result = subject
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.upload,
                          request, unit_test_utils.UUID1, 'YYYYYYY', 7)

    def test_upload_storage_quota_full(self):
        request = unit_test_utils.get_fake_request()
        self.subject_repo.result = exception.StorageQuotaFull("message")
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.upload,
                          request, unit_test_utils.UUID1, 'YYYYYYY', 7)

    def test_upload_storage_forbidden(self):
        request = unit_test_utils.get_fake_request(user=unit_test_utils.USER2)
        subject = FakeSubject()
        subject.set_data = Raise(exception.Forbidden)
        self.subject_repo.result = subject
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.upload,
                          request, unit_test_utils.UUID2, 'YY', 2)

    def test_upload_storage_internal_error(self):
        request = unit_test_utils.get_fake_request()
        self.subject_repo.result = exception.ServerError()
        self.assertRaises(exception.ServerError,
                          self.controller.upload,
                          request, unit_test_utils.UUID1, 'ABC', 3)

    def test_upload_storage_write_denied(self):
        request = unit_test_utils.get_fake_request(user=unit_test_utils.USER3)
        subject = FakeSubject()
        subject.set_data = Raise(glance_store.StorageWriteDenied)
        self.subject_repo.result = subject
        self.assertRaises(webob.exc.HTTPServiceUnavailable,
                          self.controller.upload,
                          request, unit_test_utils.UUID2, 'YY', 2)

    def test_upload_storage_store_disabled(self):
        """Test that uploading an subject file raises StoreDisabled exception"""
        request = unit_test_utils.get_fake_request(user=unit_test_utils.USER3)
        subject = FakeSubject()
        subject.set_data = Raise(glance_store.StoreAddDisabled)
        self.subject_repo.result = subject
        self.assertRaises(webob.exc.HTTPGone,
                          self.controller.upload,
                          request, unit_test_utils.UUID2, 'YY', 2)

    @mock.patch("subject.common.trust_auth.TokenRefresher")
    def test_upload_with_trusts(self, mock_refresher):
        """Test that uploading with registry correctly uses trusts"""
        # initialize trust environment
        self.config(data_api='subject.db.registry.api')
        refresher = mock.MagicMock()
        mock_refresher.return_value = refresher
        refresher.refresh_token.return_value = "fake_token"
        # request an subject upload
        request = unit_test_utils.get_fake_request()
        request.environ['keystone.token_auth'] = mock.MagicMock()
        request.environ['keystone.token_info'] = {
            'token': {
                'roles': [{'name': 'FakeRole', 'id': 'FakeID'}]
            }
        }
        subject = FakeSubject('abcd')
        self.subject_repo.result = subject
        mock_fake_save = mock.Mock()
        mock_fake_save.side_effect = [None, exception.NotAuthenticated, None]
        temp_save = FakeSubjectRepo.save
        # mocking save to raise NotAuthenticated on the second call
        FakeSubjectRepo.save = mock_fake_save
        self.controller.upload(request, unit_test_utils.UUID2, 'YYYY', 4)
        # check subject data
        self.assertEqual('YYYY', subject.data)
        self.assertEqual(4, subject.size)
        FakeSubjectRepo.save = temp_save
        # check that token has been correctly acquired and deleted
        mock_refresher.assert_called_once_with(
            request.environ['keystone.token_auth'],
            request.context.tenant, ['FakeRole'])
        refresher.refresh_token.assert_called_once_with()
        refresher.release_resources.assert_called_once_with()
        self.assertEqual("fake_token", request.context.auth_token)

    @mock.patch("subject.common.trust_auth.TokenRefresher")
    def test_upload_with_trusts_fails(self, mock_refresher):
        """Test upload with registry if trust was not successfully created"""
        # initialize trust environment
        self.config(data_api='subject.db.registry.api')
        mock_refresher().side_effect = Exception()
        # request an subject upload
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('abcd')
        self.subject_repo.result = subject
        self.controller.upload(request, unit_test_utils.UUID2, 'YYYY', 4)
        # check subject data
        self.assertEqual('YYYY', subject.data)
        self.assertEqual(4, subject.size)
        # check that the token has not been updated
        self.assertEqual(0, mock_refresher().refresh_token.call_count)

    def _test_upload_download_prepare_notification(self):
        request = unit_test_utils.get_fake_request()
        self.controller.upload(request, unit_test_utils.UUID2, 'YYYY', 4)
        output = self.controller.download(request, unit_test_utils.UUID2)
        output_log = self.notifier.get_logs()
        prepare_payload = output['meta'].copy()
        prepare_payload['checksum'] = None
        prepare_payload['size'] = None
        prepare_payload['virtual_size'] = None
        prepare_payload['location'] = None
        prepare_payload['status'] = 'queued'
        del prepare_payload['updated_at']
        prepare_log = {
            'notification_type': "INFO",
            'event_type': "subject.prepare",
            'payload': prepare_payload,
        }
        self.assertEqual(3, len(output_log))
        prepare_updated_at = output_log[0]['payload']['updated_at']
        del output_log[0]['payload']['updated_at']
        self.assertLessEqual(prepare_updated_at, output['meta']['updated_at'])
        self.assertEqual(prepare_log, output_log[0])

    def _test_upload_download_upload_notification(self):
        request = unit_test_utils.get_fake_request()
        self.controller.upload(request, unit_test_utils.UUID2, 'YYYY', 4)
        output = self.controller.download(request, unit_test_utils.UUID2)
        output_log = self.notifier.get_logs()
        upload_payload = output['meta'].copy()
        upload_log = {
            'notification_type': "INFO",
            'event_type': "subject.upload",
            'payload': upload_payload,
        }
        self.assertEqual(3, len(output_log))
        self.assertEqual(upload_log, output_log[1])

    def _test_upload_download_activate_notification(self):
        request = unit_test_utils.get_fake_request()
        self.controller.upload(request, unit_test_utils.UUID2, 'YYYY', 4)
        output = self.controller.download(request, unit_test_utils.UUID2)
        output_log = self.notifier.get_logs()
        activate_payload = output['meta'].copy()
        activate_log = {
            'notification_type': "INFO",
            'event_type': "subject.activate",
            'payload': activate_payload,
        }
        self.assertEqual(3, len(output_log))
        self.assertEqual(activate_log, output_log[2])

    def test_restore_subject_when_upload_failed(self):
        request = unit_test_utils.get_fake_request()
        subject = FakeSubject('fake')
        subject.set_data = Raise(glance_store.StorageWriteDenied)
        self.subject_repo.result = subject
        self.assertRaises(webob.exc.HTTPServiceUnavailable,
                          self.controller.upload,
                          request, unit_test_utils.UUID2, 'ZZZ', 3)
        self.assertEqual('queued', self.subject_repo.saved_subject.status)


class TestSubjectDataDeserializer(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectDataDeserializer, self).setUp()
        self.deserializer = subject.api.v2.subject_data.RequestDeserializer()

    def test_upload(self):
        request = unit_test_utils.get_fake_request()
        request.headers['Content-Type'] = 'application/octet-stream'
        request.body = b'YYY'
        request.headers['Content-Length'] = 3
        output = self.deserializer.upload(request)
        data = output.pop('data')
        self.assertEqual(b'YYY', data.read())
        expected = {'size': 3}
        self.assertEqual(expected, output)

    def test_upload_chunked(self):
        request = unit_test_utils.get_fake_request()
        request.headers['Content-Type'] = 'application/octet-stream'
        # If we use body_file, webob assumes we want to do a chunked upload,
        # ignoring the Content-Length header
        request.body_file = six.StringIO('YYY')
        output = self.deserializer.upload(request)
        data = output.pop('data')
        self.assertEqual('YYY', data.read())
        expected = {'size': None}
        self.assertEqual(expected, output)

    def test_upload_chunked_with_content_length(self):
        request = unit_test_utils.get_fake_request()
        request.headers['Content-Type'] = 'application/octet-stream'
        request.body_file = six.BytesIO(b'YYY')
        # The deserializer shouldn't care if the Content-Length is
        # set when the user is attempting to send chunked data.
        request.headers['Content-Length'] = 3
        output = self.deserializer.upload(request)
        data = output.pop('data')
        self.assertEqual(b'YYY', data.read())
        expected = {'size': 3}
        self.assertEqual(expected, output)

    def test_upload_with_incorrect_content_length(self):
        request = unit_test_utils.get_fake_request()
        request.headers['Content-Type'] = 'application/octet-stream'
        # The deserializer shouldn't care if the Content-Length and
        # actual request body length differ. That job is left up
        # to the controller
        request.body = b'YYY'
        request.headers['Content-Length'] = 4
        output = self.deserializer.upload(request)
        data = output.pop('data')
        self.assertEqual(b'YYY', data.read())
        expected = {'size': 4}
        self.assertEqual(expected, output)

    def test_upload_wrong_content_type(self):
        request = unit_test_utils.get_fake_request()
        request.headers['Content-Type'] = 'application/json'
        request.body = b'YYYYY'
        self.assertRaises(webob.exc.HTTPUnsupportedMediaType,
                          self.deserializer.upload, request)

        request = unit_test_utils.get_fake_request()
        request.headers['Content-Type'] = 'application/octet-st'
        request.body = b'YYYYY'
        self.assertRaises(webob.exc.HTTPUnsupportedMediaType,
                          self.deserializer.upload, request)


class TestSubjectDataSerializer(test_utils.BaseTestCase):

    def setUp(self):
        super(TestSubjectDataSerializer, self).setUp()
        self.serializer = subject.api.v2.subject_data.ResponseSerializer()

    def test_download(self):
        request = wsgi.Request.blank('/')
        request.environ = {}
        response = webob.Response()
        response.request = request
        subject = FakeSubject(size=3, data=[b'Z', b'Z', b'Z'])
        self.serializer.download(response, subject)
        self.assertEqual(b'ZZZ', response.body)
        self.assertEqual('3', response.headers['Content-Length'])
        self.assertNotIn('Content-MD5', response.headers)
        self.assertEqual('application/octet-stream',
                         response.headers['Content-Type'])

    def test_download_with_checksum(self):
        request = wsgi.Request.blank('/')
        request.environ = {}
        response = webob.Response()
        response.request = request
        checksum = '0745064918b49693cca64d6b6a13d28a'
        subject = FakeSubject(size=3, checksum=checksum, data=[b'Z', b'Z', b'Z'])
        self.serializer.download(response, subject)
        self.assertEqual(b'ZZZ', response.body)
        self.assertEqual('3', response.headers['Content-Length'])
        self.assertEqual(checksum, response.headers['Content-MD5'])
        self.assertEqual('application/octet-stream',
                         response.headers['Content-Type'])

    def test_download_forbidden(self):
        """Make sure the serializer can return 403 forbidden error instead of
        500 internal server error.
        """
        def get_data(*args, **kwargs):
            raise exception.Forbidden()

        self.stubs.Set(subject.api.policy.SubjectProxy,
                       'get_data',
                       get_data)
        request = wsgi.Request.blank('/')
        request.environ = {}
        response = webob.Response()
        response.request = request
        subject = FakeSubject(size=3, data=iter('ZZZ'))
        subject.get_data = get_data
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.serializer.download,
                          response, subject)

    def test_download_no_content(self):
        """Test subject download returns HTTPNoContent

        Make sure that serializer returns 204 no content error in case of
        subject data is not available at specified location.
        """
        with mock.patch.object(subject.api.policy.SubjectProxy,
                               'get_data') as mock_get_data:
            mock_get_data.side_effect = glance_store.NotFound(subject="subject")

            request = wsgi.Request.blank('/')
            response = webob.Response()
            response.request = request
            subject = FakeSubject(size=3, data=iter('ZZZ'))
            subject.get_data = mock_get_data
            self.assertRaises(webob.exc.HTTPNoContent,
                              self.serializer.download,
                              response, subject)

    def test_download_service_unavailable(self):
        """Test subject download returns HTTPServiceUnavailable."""
        with mock.patch.object(subject.api.policy.SubjectProxy,
                               'get_data') as mock_get_data:
            mock_get_data.side_effect = glance_store.RemoteServiceUnavailable()

            request = wsgi.Request.blank('/')
            response = webob.Response()
            response.request = request
            subject = FakeSubject(size=3, data=iter('ZZZ'))
            subject.get_data = mock_get_data
            self.assertRaises(webob.exc.HTTPServiceUnavailable,
                              self.serializer.download,
                              response, subject)

    def test_download_store_get_not_support(self):
        """Test subject download returns HTTPBadRequest.

        Make sure that serializer returns 400 bad request error in case of
        getting subjects from this store is not supported at specified location.
        """
        with mock.patch.object(subject.api.policy.SubjectProxy,
                               'get_data') as mock_get_data:
            mock_get_data.side_effect = glance_store.StoreGetNotSupported()

            request = wsgi.Request.blank('/')
            response = webob.Response()
            response.request = request
            subject = FakeSubject(size=3, data=iter('ZZZ'))
            subject.get_data = mock_get_data
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.serializer.download,
                              response, subject)

    def test_download_store_random_get_not_support(self):
        """Test subject download returns HTTPBadRequest.

        Make sure that serializer returns 400 bad request error in case of
        getting randomly subjects from this store is not supported at
        specified location.
        """
        with mock.patch.object(subject.api.policy.SubjectProxy,
                               'get_data') as m_get_data:
            err = glance_store.StoreRandomGetNotSupported(offset=0,
                                                          chunk_size=0)
            m_get_data.side_effect = err

            request = wsgi.Request.blank('/')
            response = webob.Response()
            response.request = request
            subject = FakeSubject(size=3, data=iter('ZZZ'))
            subject.get_data = m_get_data
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self.serializer.download,
                              response, subject)

    def test_upload(self):
        request = webob.Request.blank('/')
        request.environ = {}
        response = webob.Response()
        response.request = request
        self.serializer.upload(response, {})
        self.assertEqual(204, response.status_int)
        self.assertEqual('0', response.headers['Content-Length'])
