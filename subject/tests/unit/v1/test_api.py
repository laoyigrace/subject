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

import copy
import datetime
import hashlib
import os
import signal
import uuid

import glance_store as store
import mock
from oslo_config import cfg
from oslo_serialization import jsonutils
import routes
import six
import webob

import subject.api
import subject.api.common
from subject.api.v1 import router
from subject.api.v1 import upload_utils
import subject.common.config
from subject.common import exception
from subject.common import timeutils
import subject.context
from subject.db.sqlalchemy import api as db_api
from subject.db.sqlalchemy import models as db_models
import subject.registry.client.v1.api as registry
from subject.tests.unit import base
import subject.tests.unit.utils as unit_test_utils
from subject.tests import utils as test_utils

CONF = cfg.CONF

_gen_uuid = lambda: str(uuid.uuid4())

UUID1 = _gen_uuid()
UUID2 = _gen_uuid()
UUID3 = _gen_uuid()


class TestGlanceAPI(base.IsolatedUnitTest):
    def setUp(self):
        """Establish a clean test environment"""
        super(TestGlanceAPI, self).setUp()
        self.mapper = routes.Mapper()
        self.api = test_utils.FakeAuthMiddleware(router.API(self.mapper))
        self.FIXTURES = [
            {'id': UUID1,
             'name': 'fake subject #1',
             'status': 'active',
             'disk_format': 'ami',
             'container_format': 'ami',
             'is_public': False,
             'created_at': timeutils.utcnow(),
             'updated_at': timeutils.utcnow(),
             'deleted_at': None,
             'deleted': False,
             'checksum': None,
             'size': 13,
             'locations': [{'url': "file:///%s/%s" % (self.test_dir, UUID1),
                            'metadata': {}, 'status': 'active'}],
             'properties': {'type': 'kernel'}},
            {'id': UUID2,
             'name': 'fake subject #2',
             'status': 'active',
             'disk_format': 'vhd',
             'container_format': 'ovf',
             'is_public': True,
             'created_at': timeutils.utcnow(),
             'updated_at': timeutils.utcnow(),
             'deleted_at': None,
             'deleted': False,
             'checksum': 'abc123',
             'size': 19,
             'locations': [{'url': "file:///%s/%s" % (self.test_dir, UUID2),
                            'metadata': {}, 'status': 'active'}],
             'properties': {}},
            {'id': UUID3,
             'name': 'fake subject #3',
             'status': 'deactivated',
             'disk_format': 'ami',
             'container_format': 'ami',
             'is_public': False,
             'created_at': timeutils.utcnow(),
             'updated_at': timeutils.utcnow(),
             'deleted_at': None,
             'deleted': False,
             'checksum': '13',
             'size': 13,
             'locations': [{'url': "file:///%s/%s" % (self.test_dir, UUID1),
                            'metadata': {}, 'status': 'active'}],
             'properties': {}}]
        self.context = subject.context.RequestContext(is_admin=True)
        db_api.get_engine()
        self.destroy_fixtures()
        self.addCleanup(self.destroy_fixtures)
        self.create_fixtures()
        # Used to store/track subject status changes for post-analysis
        self.subject_status = []
        self.http_server_pid = None
        self.addCleanup(self._cleanup_server)
        ret = test_utils.start_http_server("foo_subject_id", b"foo_subject")
        self.http_server_pid, self.http_port = ret

    def _cleanup_server(self):
        if self.http_server_pid is not None:
            os.kill(self.http_server_pid, signal.SIGKILL)

    def create_fixtures(self):
        for fixture in self.FIXTURES:
            db_api.subject_create(self.context, fixture)
            # We write a fake subject file to the filesystem
            with open("%s/%s" % (self.test_dir, fixture['id']), 'wb') as subject:
                subject.write(b"chunk00000remainder")
                subject.flush()

    def destroy_fixtures(self):
        # Easiest to just drop the models and re-create them...
        db_models.unregister_models(db_api.get_engine())
        db_models.register_models(db_api.get_engine())

    def _do_test_defaulted_format(self, format_key, format_value):
        fixture_headers = {'x-subject-meta-name': 'defaulted',
                           'x-subject-meta-location': 'http://localhost:0/subject',
                           format_key: format_value}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        http = store.get_store_from_scheme('http')

        with mock.patch.object(http, 'get_size') as mocked_size:
            mocked_size.return_value = 0
            res = req.get_response(self.api)
            self.assertEqual(201, res.status_int)
            res_body = jsonutils.loads(res.body)['subject']
            self.assertEqual(format_value, res_body['disk_format'])
            self.assertEqual(format_value, res_body['container_format'])

    def _http_loc_url(self, path):
        return 'http://127.0.0.1:%d%s' % (self.http_port, path)

    def test_defaulted_amazon_format(self):
        for key in ('x-subject-meta-disk-format',
                    'x-subject-meta-container-format'):
            for value in ('aki', 'ari', 'ami'):
                self._do_test_defaulted_format(key, value)

    def test_bad_time_create_minus_int(self):
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-created_at': '-42',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_bad_time_create_string(self):
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-created_at': 'foo',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_bad_time_create_low_year(self):
        # 'strftime' only allows values after 1900 in subject v1
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-created_at': '1100',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_bad_time_create_string_in_date(self):
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-created_at': '2012-01-01hey12:32:12',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_bad_min_disk_size_create(self):
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-min-disk': '-42',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'Invalid value', res.body)

    def test_updating_subjectid_after_creation(self):
        # Test incorrect/illegal id update
        req = webob.Request.blank("/subjects/%s" % UUID1)
        req.method = 'PUT'
        req.headers['x-subject-meta-id'] = '000000-000-0000-0000-000'
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

        # Test using id of another subject
        req = webob.Request.blank("/subjects/%s" % UUID1)
        req.method = 'PUT'
        req.headers['x-subject-meta-id'] = UUID2
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_bad_min_disk_size_update(self):
        fixture_headers = {'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])
        subject_id = res_body['id']
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['x-subject-meta-min-disk'] = '-42'
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'Invalid value', res.body)

    def test_invalid_min_disk_size_update(self):
        fixture_headers = {'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])
        subject_id = res_body['id']
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['x-subject-meta-min-disk'] = str(2 ** 31 + 1)
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_bad_min_ram_size_create(self):
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-min-ram': '-42',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'Invalid value', res.body)

    def test_bad_min_ram_size_update(self):
        fixture_headers = {'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])
        subject_id = res_body['id']
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['x-subject-meta-min-ram'] = '-42'
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'Invalid value', res.body)

    def test_invalid_min_ram_size_update(self):
        fixture_headers = {'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])
        subject_id = res_body['id']
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['x-subject-meta-min-ram'] = str(2 ** 31 + 1)
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_bad_disk_format(self):
        fixture_headers = {
            'x-subject-meta-store': 'bad',
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': 'http://localhost:0/subject.tar.gz',
            'x-subject-meta-disk-format': 'invalid',
            'x-subject-meta-container-format': 'ami',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'Invalid disk format', res.body)

    def test_configured_disk_format_good(self):
        self.config(disk_formats=['foo'], group="subject_format")
        fixture_headers = {
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': 'http://localhost:0/subject.tar.gz',
            'x-subject-meta-disk-format': 'foo',
            'x-subject-meta-container-format': 'bare',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        http = store.get_store_from_scheme('http')
        with mock.patch.object(http, 'get_size') as mocked_size:
            mocked_size.return_value = 0
            res = req.get_response(self.api)
            self.assertEqual(201, res.status_int)

    def test_configured_disk_format_bad(self):
        self.config(disk_formats=['foo'], group="subject_format")
        fixture_headers = {
            'x-subject-meta-store': 'bad',
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': 'http://localhost:0/subject.tar.gz',
            'x-subject-meta-disk-format': 'bar',
            'x-subject-meta-container-format': 'bare',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'Invalid disk format', res.body)

    def test_configured_container_format_good(self):
        self.config(container_formats=['foo'], group="subject_format")
        fixture_headers = {
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': 'http://localhost:0/subject.tar.gz',
            'x-subject-meta-disk-format': 'raw',
            'x-subject-meta-container-format': 'foo',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        http = store.get_store_from_scheme('http')

        with mock.patch.object(http, 'get_size') as mocked_size:
            mocked_size.return_value = 0
            res = req.get_response(self.api)
            self.assertEqual(201, res.status_int)

    def test_configured_container_format_bad(self):
        self.config(container_formats=['foo'], group="subject_format")
        fixture_headers = {
            'x-subject-meta-store': 'bad',
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': 'http://localhost:0/subject.tar.gz',
            'x-subject-meta-disk-format': 'raw',
            'x-subject-meta-container-format': 'bar',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'Invalid container format', res.body)

    def test_container_and_disk_amazon_format_differs(self):
        fixture_headers = {
            'x-subject-meta-store': 'bad',
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': 'http://localhost:0/subject.tar.gz',
            'x-subject-meta-disk-format': 'aki',
            'x-subject-meta-container-format': 'ami'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        expected = (b"Invalid mix of disk and container formats. "
                    b"When setting a disk or container format to one of "
                    b"'aki', 'ari', or 'ami', "
                    b"the container and disk formats must match.")
        self.assertEqual(400, res.status_int)
        self.assertIn(expected, res.body)

    def test_create_with_location_no_container_format(self):
        fixture_headers = {
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': 'http://localhost:0/subject.tar.gz',
            'x-subject-meta-disk-format': 'vhd',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        http = store.get_store_from_scheme('http')

        with mock.patch.object(http, 'get_size') as mocked_size:
            mocked_size.return_value = 0
            res = req.get_response(self.api)
            self.assertEqual(400, res.status_int)
            self.assertIn(b'Container format is not specified', res.body)

    def test_create_with_location_no_disk_format(self):
        fixture_headers = {
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': 'http://localhost:0/subject.tar.gz',
            'x-subject-meta-container-format': 'bare',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        http = store.get_store_from_scheme('http')

        with mock.patch.object(http, 'get_size') as mocked_size:
            mocked_size.return_value = 0
            res = req.get_response(self.api)
            self.assertEqual(400, res.status_int)
            self.assertIn(b'Disk format is not specified', res.body)

    def test_create_with_empty_location(self):
        fixture_headers = {
            'x-subject-meta-location': '',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_create_with_empty_copy_from(self):
        fixture_headers = {
            'x-subject-api-copy-from': '',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_create_delayed_subject_with_no_disk_and_container_formats(self):
        fixture_headers = {
            'x-subject-meta-name': 'delayed',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        http = store.get_store_from_scheme('http')

        with mock.patch.object(http, 'get_size') as mocked_size:
            mocked_size.return_value = 0
            res = req.get_response(self.api)
            self.assertEqual(201, res.status_int)

    def test_create_with_bad_store_name(self):
        fixture_headers = {
            'x-subject-meta-store': 'bad',
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-disk-format': 'qcow2',
            'x-subject-meta-container-format': 'bare',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'Required store bad is invalid', res.body)

    @mock.patch.object(subject.api.v1.subjects.Controller, '_external_source')
    @mock.patch.object(store, 'get_store_from_location')
    def test_create_with_location_get_store_or_400_raises_exception(
            self, mock_get_store_from_location, mock_external_source):
        location = 'bad+scheme://localhost:0/subject.qcow2'
        scheme = 'bad+scheme'
        fixture_headers = {
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': location,
            'x-subject-meta-disk-format': 'qcow2',
            'x-subject-meta-container-format': 'bare',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        mock_external_source.return_value = location
        mock_get_store_from_location.return_value = scheme

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertEqual(1, mock_external_source.call_count)
        self.assertEqual(1, mock_get_store_from_location.call_count)
        self.assertIn('Store for scheme %s not found' % scheme,
                      res.body.decode('utf-8'))

    def test_create_with_location_unknown_scheme(self):
        fixture_headers = {
            'x-subject-meta-store': 'bad',
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': 'bad+scheme://localhost:0/subject.qcow2',
            'x-subject-meta-disk-format': 'qcow2',
            'x-subject-meta-container-format': 'bare',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'External sources are not supported', res.body)

    def test_create_with_location_bad_store_uri(self):
        fixture_headers = {
            'x-subject-meta-store': 'file',
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': 'http://',
            'x-subject-meta-disk-format': 'qcow2',
            'x-subject-meta-container-format': 'bare',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'Invalid location', res.body)

    def test_create_subject_with_too_many_properties(self):
        self.config(subject_property_quota=1)
        another_request = unit_test_utils.get_fake_request(
            path='/subjects', method='POST')
        headers = {'x-auth-token': 'user:tenant:joe_soap',
                   'x-subject-meta-property-x_all_permitted': '1',
                   'x-subject-meta-property-x_all_permitted_foo': '2'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(413, output.status_int)

    def test_bad_container_format(self):
        fixture_headers = {
            'x-subject-meta-store': 'bad',
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': 'http://localhost:0/subject.tar.gz',
            'x-subject-meta-disk-format': 'vhd',
            'x-subject-meta-container-format': 'invalid',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'Invalid container format', res.body)

    def test_bad_subject_size(self):
        fixture_headers = {
            'x-subject-meta-store': 'bad',
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location': self._http_loc_url('/subject.tar.gz'),
            'x-subject-meta-disk-format': 'vhd',
            'x-subject-meta-container-format': 'bare',
        }

        def exec_bad_size_test(bad_size, expected_substr):
            fixture_headers['x-subject-meta-size'] = bad_size
            req = webob.Request.blank("/subjects",
                                      method='POST',
                                      headers=fixture_headers)
            res = req.get_response(self.api)
            self.assertEqual(400, res.status_int)
            self.assertIn(expected_substr, res.body)

        expected = b"Cannot convert subject size 'invalid' to an integer."
        exec_bad_size_test('invalid', expected)
        expected = b"Cannot be a negative value."
        exec_bad_size_test(-10, expected)

    def test_bad_subject_name(self):
        fixture_headers = {
            'x-subject-meta-store': 'bad',
            'x-subject-meta-name': 'X' * 256,
            'x-subject-meta-location': self._http_loc_url('/subject.tar.gz'),
            'x-subject-meta-disk-format': 'vhd',
            'x-subject-meta-container-format': 'bare',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_add_subject_no_location_no_subject_as_body(self):
        """Tests creates a queued subject for no body and no loc header"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3',
                           'x-subject-created_at': '2015-11-20',
                           'x-subject-updated_at': '2015-12-01 12:10:01',
                           'x-subject-deleted_at': '2000'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])
        subject_id = res_body['id']

        # Test that we are able to edit the Location field
        # per LP Bug #911599

        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['x-subject-meta-location'] = 'http://localhost:0/subjects/123'

        http = store.get_store_from_scheme('http')

        with mock.patch.object(http, 'get_size') as mocked_size:
            mocked_size.return_value = 0
            res = req.get_response(self.api)
            self.assertEqual(200, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        # Once the location is set, the subject should be activated
        # see LP Bug #939484
        self.assertEqual('active', res_body['status'])
        self.assertNotIn('location', res_body)  # location never shown

    def test_add_subject_no_location_no_content_type(self):
        """Tests creates a queued subject for no body and no loc header"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        req.body = b"chunk00000remainder"
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_add_subject_size_header_too_big(self):
        """Tests raises BadRequest for supplied subject size that is too big"""
        fixture_headers = {'x-subject-meta-size': CONF.subject_size_cap + 1,
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_add_subject_size_chunked_data_too_big(self):
        self.config(subject_size_cap=512)
        fixture_headers = {
            'x-subject-meta-name': 'fake subject #3',
            'x-subject-meta-container_format': 'ami',
            'x-subject-meta-disk_format': 'ami',
            'transfer-encoding': 'chunked',
            'content-type': 'application/octet-stream',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'

        req.body_file = six.StringIO('X' * (CONF.subject_size_cap + 1))
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(413, res.status_int)

    def test_add_subject_size_data_too_big(self):
        self.config(subject_size_cap=512)
        fixture_headers = {
            'x-subject-meta-name': 'fake subject #3',
            'x-subject-meta-container_format': 'ami',
            'x-subject-meta-disk_format': 'ami',
            'content-type': 'application/octet-stream',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'

        req.body = b'X' * (CONF.subject_size_cap + 1)
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_add_subject_size_header_exceed_quota(self):
        quota = 500
        self.config(user_storage_quota=str(quota))
        fixture_headers = {'x-subject-meta-size': quota + 1,
                           'x-subject-meta-name': 'fake subject #3',
                           'x-subject-meta-container_format': 'bare',
                           'x-subject-meta-disk_format': 'qcow2',
                           'content-type': 'application/octet-stream',
                           }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        req.body = b'X' * (quota + 1)
        res = req.get_response(self.api)
        self.assertEqual(413, res.status_int)

    def test_add_subject_size_data_exceed_quota(self):
        quota = 500
        self.config(user_storage_quota=str(quota))
        fixture_headers = {
            'x-subject-meta-name': 'fake subject #3',
            'x-subject-meta-container_format': 'bare',
            'x-subject-meta-disk_format': 'qcow2',
            'content-type': 'application/octet-stream',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'

        req.body = b'X' * (quota + 1)
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(413, res.status_int)

    def test_add_subject_size_data_exceed_quota_readd(self):
        quota = 500
        self.config(user_storage_quota=str(quota))
        fixture_headers = {
            'x-subject-meta-name': 'fake subject #3',
            'x-subject-meta-container_format': 'bare',
            'x-subject-meta-disk_format': 'qcow2',
            'content-type': 'application/octet-stream',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        req.body = b'X' * (quota + 1)
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(413, res.status_int)

        used_size = sum([f['size'] for f in self.FIXTURES])

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        req.body = b'X' * (quota - used_size)
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

    def _add_check_no_url_info(self):

        fixture_headers = {'x-subject-meta-disk-format': 'ami',
                           'x-subject-meta-container-format': 'ami',
                           'x-subject-meta-size': '0',
                           'x-subject-meta-name': 'empty subject'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        res_body = jsonutils.loads(res.body)['subject']
        self.assertNotIn('locations', res_body)
        self.assertNotIn('direct_url', res_body)
        subject_id = res_body['id']

        # HEAD empty subject
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertNotIn('x-subject-meta-locations', res.headers)
        self.assertNotIn('x-subject-meta-direct_url', res.headers)

    def test_add_check_no_url_info_ml(self):
        self.config(show_multiple_locations=True)
        self._add_check_no_url_info()

    def test_add_check_no_url_info_direct_url(self):
        self.config(show_subject_direct_url=True)
        self._add_check_no_url_info()

    def test_add_check_no_url_info_both_on(self):
        self.config(show_subject_direct_url=True)
        self.config(show_multiple_locations=True)
        self._add_check_no_url_info()

    def test_add_check_no_url_info_both_off(self):
        self._add_check_no_url_info()

    def test_add_subject_zero_size(self):
        """Tests creating an active subject with explicitly zero size"""
        fixture_headers = {'x-subject-meta-disk-format': 'ami',
                           'x-subject-meta-container-format': 'ami',
                           'x-subject-meta-size': '0',
                           'x-subject-meta-name': 'empty subject'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('active', res_body['status'])
        subject_id = res_body['id']

        # GET empty subject
        req = webob.Request.blank("/subjects/%s" % subject_id)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertEqual(0, len(res.body))

    def _do_test_add_subject_attribute_mismatch(self, attributes):
        fixture_headers = {
            'x-subject-meta-name': 'fake subject #3',
        }
        fixture_headers.update(attributes)

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = b"XXXX"
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_add_subject_checksum_mismatch(self):
        attributes = {
            'x-subject-meta-checksum': 'asdf',
        }
        self._do_test_add_subject_attribute_mismatch(attributes)

    def test_add_subject_size_mismatch(self):
        attributes = {
            'x-subject-meta-size': str(len("XXXX") + 1),
        }
        self._do_test_add_subject_attribute_mismatch(attributes)

    def test_add_subject_checksum_and_size_mismatch(self):
        attributes = {
            'x-subject-meta-checksum': 'asdf',
            'x-subject-meta-size': str(len("XXXX") + 1),
        }
        self._do_test_add_subject_attribute_mismatch(attributes)

    def test_add_subject_bad_store(self):
        """Tests raises BadRequest for invalid store header"""
        fixture_headers = {'x-subject-meta-store': 'bad',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = b"chunk00000remainder"
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_add_subject_basic_file_store(self):
        """Tests to add a basic subject in the file store"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = b"chunk00000remainder"
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        # Test that the Location: header is set to the URI to
        # edit the newly-created subject, as required by APP.
        # See LP Bug #719825
        self.assertIn('location', res.headers,
                      "'location' not in response headers.\n"
                      "res.headerlist = %r" % res.headerlist)
        res_body = jsonutils.loads(res.body)['subject']
        self.assertIn('/subjects/%s' % res_body['id'], res.headers['location'])
        self.assertEqual('active', res_body['status'])
        subject_id = res_body['id']

        # Test that we are NOT able to edit the Location field
        # per LP Bug #911599

        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        url = self._http_loc_url('/subjects/123')
        req.headers['x-subject-meta-location'] = url
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_add_subject_unauthorized(self):
        rules = {"add_subject": '!'}
        self.set_policy_rules(rules)
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = b"chunk00000remainder"
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_add_publicize_subject_unauthorized(self):
        rules = {"add_subject": '@', "modify_subject": '@',
                 "publicize_subject": '!'}
        self.set_policy_rules(rules)
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-is-public': 'true',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = b"chunk00000remainder"
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_add_publicize_subject_authorized(self):
        rules = {"add_subject": '@', "modify_subject": '@',
                 "publicize_subject": '@', "upload_subject": '@'}
        self.set_policy_rules(rules)
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-is-public': 'true',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = b"chunk00000remainder"
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

    def test_add_copy_from_subject_unauthorized(self):
        rules = {"add_subject": '@', "copy_from": '!'}
        self.set_policy_rules(rules)
        url = self._http_loc_url('/i.ovf')
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-api-copy-from': url,
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = b"chunk00000remainder"
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_add_copy_from_upload_subject_unauthorized(self):
        rules = {"add_subject": '@', "copy_from": '@', "upload_subject": '!'}
        self.set_policy_rules(rules)
        url = self._http_loc_url('/i.ovf')
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-api-copy-from': url,
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_add_copy_from_subject_authorized_upload_subject_authorized(self):
        rules = {"add_subject": '@', "copy_from": '@', "upload_subject": '@'}
        self.set_policy_rules(rules)
        url = self._http_loc_url('/i.ovf')
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-api-copy-from': url,
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        http = store.get_store_from_scheme('http')

        with mock.patch.object(http, 'get_size') as mock_size:
            mock_size.return_value = 0
            res = req.get_response(self.api)
            self.assertEqual(201, res.status_int)

    def test_upload_subject_http_nonexistent_location_url(self):
        # Ensure HTTP 404 response returned when try to upload
        # subject from non-existent http location URL.
        rules = {"add_subject": '@', "copy_from": '@', "upload_subject": '@'}
        self.set_policy_rules(rules)
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-api-copy-from':
                               self._http_loc_url('/non_existing_subject_path'),
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

    def test_add_copy_from_with_nonempty_body(self):
        """Tests creates an subject from copy-from and nonempty body"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-api-copy-from': 'http://0.0.0.0:1/c.ovf',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F'}

        req = webob.Request.blank("/subjects")
        req.headers['Content-Type'] = 'application/octet-stream'
        req.method = 'POST'
        req.body = b"chunk00000remainder"
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_add_location_with_nonempty_body(self):
        """Tests creates an subject from location and nonempty body"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-location': 'http://0.0.0.0:1/c.tgz',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F'}

        req = webob.Request.blank("/subjects")
        req.headers['Content-Type'] = 'application/octet-stream'
        req.method = 'POST'
        req.body = b"chunk00000remainder"
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_add_location_with_conflict_subject_size(self):
        """Tests creates an subject from location and conflict subject size"""

        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-location': 'http://a/b/c.tar.gz',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F',
                           'x-subject-meta-size': '1'}

        req = webob.Request.blank("/subjects")
        req.headers['Content-Type'] = 'application/octet-stream'
        req.method = 'POST'

        http = store.get_store_from_scheme('http')

        with mock.patch.object(http, 'get_size') as size:
            size.return_value = 2

            for k, v in six.iteritems(fixture_headers):
                req.headers[k] = v

            res = req.get_response(self.api)
            self.assertEqual(409, res.status_int)

    def test_add_location_with_invalid_location_on_conflict_subject_size(self):
        """Tests creates an subject from location and conflict subject size"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-location': 'http://0.0.0.0:1/c.tgz',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F',
                           'x-subject-meta-size': '1'}

        req = webob.Request.blank("/subjects")
        req.headers['Content-Type'] = 'application/octet-stream'
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_add_location_with_invalid_location_on_restricted_sources(self):
        """Tests creates an subject from location and restricted sources"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-location': 'file:///etc/passwd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F'}

        req = webob.Request.blank("/subjects")
        req.headers['Content-Type'] = 'application/octet-stream'
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-location': 'swift+config://xxx',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F'}

        req = webob.Request.blank("/subjects")
        req.headers['Content-Type'] = 'application/octet-stream'
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_create_subject_with_nonexistent_location_url(self):
        # Ensure HTTP 404 response returned when try to create
        # subject with non-existent http location URL.

        fixture_headers = {
            'x-subject-meta-name': 'bogus',
            'x-subject-meta-location':
                self._http_loc_url('/non_existing_subject_path'),
            'x-subject-meta-disk-format': 'qcow2',
            'x-subject-meta-container-format': 'bare',
        }
        req = webob.Request.blank("/subjects")
        req.method = 'POST'

        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

    def test_add_copy_from_with_location(self):
        """Tests creates an subject from copy-from and location"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-api-copy-from': 'http://0.0.0.0:1/c.ovf',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F',
                           'x-subject-meta-location': 'http://0.0.0.0:1/c.tgz'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_add_copy_from_with_restricted_sources(self):
        """Tests creates an subject from copy-from with restricted sources"""
        header_template = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #F'}

        schemas = ["file:///etc/passwd",
                   "swift+config:///xxx",
                   "filesystem:///etc/passwd"]

        for schema in schemas:
            req = webob.Request.blank("/subjects")
            req.method = 'POST'
            for k, v in six.iteritems(header_template):
                req.headers[k] = v
            req.headers['x-subject-api-copy-from'] = schema
            res = req.get_response(self.api)
            self.assertEqual(400, res.status_int)

    def test_add_copy_from_upload_subject_unauthorized_with_body(self):
        rules = {"upload_subject": '!', "modify_subject": '@',
                 "add_subject": '@'}
        self.set_policy_rules(rules)
        self.config(subject_size_cap=512)
        fixture_headers = {
            'x-subject-meta-name': 'fake subject #3',
            'x-subject-meta-container_format': 'ami',
            'x-subject-meta-disk_format': 'ami',
            'transfer-encoding': 'chunked',
            'content-type': 'application/octet-stream',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'

        req.body_file = six.StringIO('X' * (CONF.subject_size_cap))
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_update_data_upload_bad_store_uri(self):
        fixture_headers = {'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])
        subject_id = res_body['id']
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/octet-stream'
        req.headers['x-subject-disk-format'] = 'vhd'
        req.headers['x-subject-container-format'] = 'ovf'
        req.headers['x-subject-meta-location'] = 'http://'
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)
        self.assertIn(b'Invalid location', res.body)

    def test_update_data_upload_subject_unauthorized(self):
        rules = {"upload_subject": '!', "modify_subject": '@',
                 "add_subject": '@'}
        self.set_policy_rules(rules)
        """Tests creates a queued subject for no body and no loc header"""
        self.config(subject_size_cap=512)
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])
        subject_id = res_body['id']
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/octet-stream'
        req.headers['transfer-encoding'] = 'chunked'
        req.headers['x-subject-disk-format'] = 'vhd'
        req.headers['x-subject-container-format'] = 'ovf'
        req.body_file = six.StringIO('X' * (CONF.subject_size_cap))
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_update_copy_from_upload_subject_unauthorized(self):
        rules = {"upload_subject": '!', "modify_subject": '@',
                 "add_subject": '@', "copy_from": '@'}
        self.set_policy_rules(rules)

        fixture_headers = {'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])
        subject_id = res_body['id']
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/octet-stream'
        req.headers['x-subject-api-copy-from'] = self._http_loc_url('/i.ovf')
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_update_copy_from_unauthorized(self):
        rules = {"upload_subject": '@', "modify_subject": '@',
                 "add_subject": '@', "copy_from": '!'}
        self.set_policy_rules(rules)

        fixture_headers = {'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])
        subject_id = res_body['id']
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/octet-stream'
        req.headers['x-subject-api-copy-from'] = self._http_loc_url('/i.ovf')
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def _do_test_post_subject_content_missing_format(self, missing):
        """Tests creation of an subject with missing format"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        header = 'x-subject-meta-' + missing.replace('_', '-')

        del fixture_headers[header]

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = b"chunk00000remainder"
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_post_subject_content_missing_disk_format(self):
        """Tests creation of an subject with missing disk format"""
        self._do_test_post_subject_content_missing_format('disk_format')

    def test_post_subject_content_missing_container_type(self):
        """Tests creation of an subject with missing container format"""
        self._do_test_post_subject_content_missing_format('container_format')

    def _do_test_put_subject_content_missing_format(self, missing):
        """Tests delayed activation of an subject with missing format"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        header = 'x-subject-meta-' + missing.replace('_', '-')

        del fixture_headers[header]

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])
        subject_id = res_body['id']

        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = b"chunk00000remainder"
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_put_subject_content_missing_disk_format(self):
        """Tests delayed activation of subject with missing disk format"""
        self._do_test_put_subject_content_missing_format('disk_format')

    def test_put_subject_content_missing_container_type(self):
        """Tests delayed activation of subject with missing container format"""
        self._do_test_put_subject_content_missing_format('container_format')

    def test_download_deactivated_subjects(self):
        """Tests exception raised trying to download a deactivated subject"""
        req = webob.Request.blank("/subjects/%s" % UUID3)
        req.method = 'GET'
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_update_deleted_subject(self):
        """Tests that exception raised trying to update a deleted subject"""
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        fixture = {'name': 'test_del_img'}
        req = webob.Request.blank('/subjects/%s' % UUID2)
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(subject=fixture))

        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)
        self.assertIn(b'Forbidden to update deleted subject', res.body)

    def test_delete_deleted_subject(self):
        """Tests that exception raised trying to delete a deleted subject"""
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        # Verify the status is 'deleted'
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertEqual("deleted", res.headers['x-subject-meta-status'])

        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)
        msg = "Subject %s not found." % UUID2
        self.assertIn(msg, res.body.decode())

        # Verify the status is still 'deleted'
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertEqual("deleted", res.headers['x-subject-meta-status'])

    def test_subject_status_when_delete_fails(self):
        """
        Tests that the subject status set to active if deletion of subject fails.
        """

        fs = store.get_store_from_scheme('file')

        with mock.patch.object(fs, 'delete') as mock_fsstore_delete:
            mock_fsstore_delete.side_effect = exception.Forbidden()

            # trigger the v1 delete api
            req = webob.Request.blank("/subjects/%s" % UUID2)
            req.method = 'DELETE'
            res = req.get_response(self.api)
            self.assertEqual(403, res.status_int)
            self.assertIn(b'Forbidden to delete subject', res.body)

            # check subject metadata is still there with active state
            req = webob.Request.blank("/subjects/%s" % UUID2)
            req.method = 'HEAD'
            res = req.get_response(self.api)
            self.assertEqual(200, res.status_int)
            self.assertEqual("active", res.headers['x-subject-meta-status'])

    def test_delete_pending_delete_subject(self):
        """
        Tests that correct response returned when deleting
        a pending_delete subject
        """
        # First deletion
        self.config(delayed_delete=True)
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        # Verify the status is 'pending_delete'
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertEqual("pending_delete", res.headers['x-subject-meta-status'])

        # Second deletion
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)
        self.assertIn(b'Forbidden to delete a pending_delete subject', res.body)

        # Verify the status is still 'pending_delete'
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertEqual("pending_delete", res.headers['x-subject-meta-status'])

    def test_upload_to_subject_status_saving(self):
        """Test subject upload conflict.

        If an subject is uploaded before an existing upload to the same subject
        completes, the original upload should succeed and the conflicting
        one should fail and any data be deleted.
        """
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'some-foo-subject'}

        # create an subject but don't upload yet.
        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)
        res_body = jsonutils.loads(res.body)['subject']

        subject_id = res_body['id']
        self.assertIn('/subjects/%s' % subject_id, res.headers['location'])

        # verify the status is 'queued'
        self.assertEqual('queued', res_body['status'])

        orig_get_subject_metadata = registry.get_subject_metadata
        orig_subject_get = db_api._subject_get
        orig_subject_update = db_api._subject_update
        orig_initiate_deletion = upload_utils.initiate_deletion

        # this will be used to track what is called and their order.
        call_sequence = []
        # use this to determine if we are within a db session i.e. atomic
        # operation, that is setting our active state.
        # We want first status check to be 'queued' so we get past the
        # first guard.
        test_status = {
            'activate_session_started': False,
            'queued_guard_passed': False
        }

        state_changes = []

        def mock_subject_update(context, values, subject_id, purge_props=False,
                              from_state=None):

            status = values.get('status')
            if status:
                state_changes.append(status)
                if status == 'active':
                    # We only expect this state to be entered once.
                    if test_status['activate_session_started']:
                        raise Exception("target session already started")

                    test_status['activate_session_started'] = True
                    call_sequence.append('update_active')

                else:
                    call_sequence.append('update')

            return orig_subject_update(context, values, subject_id,
                                     purge_props=purge_props,
                                     from_state=from_state)

        def mock_subject_get(*args, **kwargs):
            """Force status to 'saving' if not within activate db session.

            If we are in the activate db session we return 'active' which we
            then expect to cause exception.Conflict to be raised since this
            indicates that another upload has succeeded.
            """
            subject = orig_subject_get(*args, **kwargs)
            if test_status['activate_session_started']:
                call_sequence.append('subject_get_active')
                setattr(subject, 'status', 'active')
            else:
                setattr(subject, 'status', 'saving')

            return subject

        def mock_get_subject_metadata(*args, **kwargs):
            """Force subject status sequence.
            """
            call_sequence.append('get_subject_meta')
            meta = orig_get_subject_metadata(*args, **kwargs)
            if not test_status['queued_guard_passed']:
                meta['status'] = 'queued'
                test_status['queued_guard_passed'] = True

            return meta

        def mock_initiate_deletion(*args, **kwargs):
            call_sequence.append('init_del')
            orig_initiate_deletion(*args, **kwargs)

        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = b"chunk00000remainder"

        with mock.patch.object(
                upload_utils, 'initiate_deletion') as mock_init_del:
            mock_init_del.side_effect = mock_initiate_deletion
            with mock.patch.object(
                    registry, 'get_subject_metadata') as mock_get_meta:
                mock_get_meta.side_effect = mock_get_subject_metadata
                with mock.patch.object(db_api, '_subject_get') as mock_db_get:
                    mock_db_get.side_effect = mock_subject_get
                    with mock.patch.object(
                            db_api, '_subject_update') as mock_db_update:
                        mock_db_update.side_effect = mock_subject_update

                        # Expect a 409 Conflict.
                        res = req.get_response(self.api)
                        self.assertEqual(409, res.status_int)

                        # Check expected call sequence
                        self.assertEqual(['get_subject_meta', 'get_subject_meta',
                                          'update', 'update_active',
                                          'subject_get_active',
                                          'init_del'],
                                         call_sequence)

                        self.assertTrue(mock_get_meta.called)
                        self.assertTrue(mock_db_get.called)
                        self.assertTrue(mock_db_update.called)

                        # Ensure cleanup occurred.
                        self.assertEqual(1, mock_init_del.call_count)

                        self.assertEqual(['saving', 'active'], state_changes)

    def test_register_and_upload(self):
        """
        Test that the process of registering an subject with
        some metadata, then uploading an subject file with some
        more metadata doesn't mark the original metadata deleted
        :see LP Bug#901534
        """
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3',
                           'x-subject-meta-property-key1': 'value1'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)
        res_body = jsonutils.loads(res.body)['subject']

        self.assertIn('id', res_body)

        subject_id = res_body['id']
        self.assertIn('/subjects/%s' % subject_id, res.headers['location'])

        # Verify the status is queued
        self.assertIn('status', res_body)
        self.assertEqual('queued', res_body['status'])

        # Check properties are not deleted
        self.assertIn('properties', res_body)
        self.assertIn('key1', res_body['properties'])
        self.assertEqual('value1', res_body['properties']['key1'])

        # Now upload the subject file along with some more
        # metadata and verify original metadata properties
        # are not marked deleted
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/octet-stream'
        req.headers['x-subject-meta-property-key2'] = 'value2'
        req.body = b"chunk00000remainder"
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        # Verify the status is 'queued'
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'HEAD'

        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertIn('x-subject-meta-property-key1', res.headers,
                      "Did not find required property in headers. "
                      "Got headers: %r" % res.headers)
        self.assertEqual("active", res.headers['x-subject-meta-status'])

    def test_upload_subject_raises_store_disabled(self):
        """Test that uploading an subject file returns HTTTP 410 response"""
        # create subject
        fs = store.get_store_from_scheme('file')
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3',
                           'x-subject-meta-property-key1': 'value1'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)
        res_body = jsonutils.loads(res.body)['subject']

        self.assertIn('id', res_body)

        subject_id = res_body['id']
        self.assertIn('/subjects/%s' % subject_id, res.headers['location'])

        # Verify the status is queued
        self.assertIn('status', res_body)
        self.assertEqual('queued', res_body['status'])

        # Now upload the subject file
        with mock.patch.object(fs, 'add') as mock_fsstore_add:
            mock_fsstore_add.side_effect = store.StoreAddDisabled
            req = webob.Request.blank("/subjects/%s" % subject_id)
            req.method = 'PUT'
            req.headers['Content-Type'] = 'application/octet-stream'
            req.body = b"chunk00000remainder"
            res = req.get_response(self.api)
            self.assertEqual(410, res.status_int)
            self._verify_subject_status(subject_id, 'killed')

    def _get_subject_status(self, subject_id):
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'HEAD'
        return req.get_response(self.api)

    def _verify_subject_status(self, subject_id, status, check_deleted=False,
                             use_cached=False):
        if not use_cached:
            res = self._get_subject_status(subject_id)
        else:
            res = self.subject_status.pop(0)

        self.assertEqual(200, res.status_int)
        self.assertEqual(status, res.headers['x-subject-meta-status'])
        self.assertEqual(str(check_deleted),
                         res.headers['x-subject-meta-deleted'])

    def _upload_safe_kill_common(self, mocks):
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3',
                           'x-subject-meta-property-key1': 'value1'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)
        res_body = jsonutils.loads(res.body)['subject']

        self.assertIn('id', res_body)

        self.subject_id = res_body['id']
        self.assertIn('/subjects/%s' %
                      self.subject_id, res.headers['location'])

        # Verify the status is 'queued'
        self.assertEqual('queued', res_body['status'])

        for m in mocks:
            m['mock'].side_effect = m['side_effect']

        # Now upload the subject file along with some more metadata and
        # verify original metadata properties are not marked deleted
        req = webob.Request.blank("/subjects/%s" % self.subject_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/octet-stream'
        req.headers['x-subject-meta-property-key2'] = 'value2'
        req.body = b"chunk00000remainder"
        res = req.get_response(self.api)
        # We expect 500 since an exception occurred during upload.
        self.assertEqual(500, res.status_int)

    @mock.patch('glance_store.store_add_to_backend')
    def test_upload_safe_kill(self, mock_store_add_to_backend):

        def mock_store_add_to_backend_w_exception(*args, **kwargs):
            """Trigger mid-upload failure by raising an exception."""
            self.subject_status.append(self._get_subject_status(self.subject_id))
            # Raise an exception to emulate failed upload.
            raise Exception("== UNIT TEST UPLOAD EXCEPTION ==")

        mocks = [{'mock': mock_store_add_to_backend,
                 'side_effect': mock_store_add_to_backend_w_exception}]

        self._upload_safe_kill_common(mocks)

        # Check we went from 'saving' -> 'killed'
        self._verify_subject_status(self.subject_id, 'saving', use_cached=True)
        self._verify_subject_status(self.subject_id, 'killed')

        self.assertEqual(1, mock_store_add_to_backend.call_count)

    @mock.patch('glance_store.store_add_to_backend')
    def test_upload_safe_kill_deleted(self, mock_store_add_to_backend):
        test_router_api = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(test_router_api,
                                                 is_admin=True)

        def mock_store_add_to_backend_w_exception(*args, **kwargs):
            """We now delete the subject, assert status is 'deleted' then
            raise an exception to emulate a failed upload. This will be caught
            by upload_data_to_store() which will then try to set status to
            'killed' which will be ignored since the subject has been deleted.
            """
            # expect 'saving'
            self.subject_status.append(self._get_subject_status(self.subject_id))

            req = webob.Request.blank("/subjects/%s" % self.subject_id)
            req.method = 'DELETE'
            res = req.get_response(self.api)
            self.assertEqual(200, res.status_int)

            # expect 'deleted'
            self.subject_status.append(self._get_subject_status(self.subject_id))

            # Raise an exception to make the upload fail.
            raise Exception("== UNIT TEST UPLOAD EXCEPTION ==")

        mocks = [{'mock': mock_store_add_to_backend,
                 'side_effect': mock_store_add_to_backend_w_exception}]

        self._upload_safe_kill_common(mocks)

        # Check we went from 'saving' -> 'deleted' -> 'deleted'
        self._verify_subject_status(self.subject_id, 'saving', check_deleted=False,
                                  use_cached=True)

        self._verify_subject_status(self.subject_id, 'deleted', check_deleted=True,
                                  use_cached=True)

        self._verify_subject_status(self.subject_id, 'deleted', check_deleted=True)

        self.assertEqual(1, mock_store_add_to_backend.call_count)

    def _check_delete_during_subject_upload(self, is_admin=False):

        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3',
                           'x-subject-meta-property-key1': 'value1'}

        req = unit_test_utils.get_fake_request(path="/subjects",
                                               is_admin=is_admin)
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)
        res_body = jsonutils.loads(res.body)['subject']

        self.assertIn('id', res_body)

        subject_id = res_body['id']
        self.assertIn('/subjects/%s' % subject_id, res.headers['location'])

        # Verify the status is 'queued'
        self.assertEqual('queued', res_body['status'])

        called = {'initiate_deletion': False}

        def mock_initiate_deletion(*args, **kwargs):
            called['initiate_deletion'] = True

        self.stubs.Set(subject.api.v1.upload_utils, 'initiate_deletion',
                       mock_initiate_deletion)

        orig_update_subject_metadata = registry.update_subject_metadata

        data = b"somedata"

        def mock_update_subject_metadata(*args, **kwargs):

            if args[2].get('size', None) == len(data):
                path = "/subjects/%s" % subject_id
                req = unit_test_utils.get_fake_request(path=path,
                                                       method='DELETE',
                                                       is_admin=is_admin)
                res = req.get_response(self.api)
                self.assertEqual(200, res.status_int)

                self.stubs.Set(registry, 'update_subject_metadata',
                               orig_update_subject_metadata)

            return orig_update_subject_metadata(*args, **kwargs)

        self.stubs.Set(registry, 'update_subject_metadata',
                       mock_update_subject_metadata)

        req = unit_test_utils.get_fake_request(path="/subjects/%s" % subject_id,
                                               method='PUT')
        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = data
        res = req.get_response(self.api)
        self.assertEqual(412, res.status_int)
        self.assertFalse(res.location)

        self.assertTrue(called['initiate_deletion'])

        req = unit_test_utils.get_fake_request(path="/subjects/%s" % subject_id,
                                               method='HEAD',
                                               is_admin=True)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertEqual('True', res.headers['x-subject-meta-deleted'])
        self.assertEqual('deleted', res.headers['x-subject-meta-status'])

    def test_delete_during_subject_upload_by_normal_user(self):
        self._check_delete_during_subject_upload(is_admin=False)

    def test_delete_during_subject_upload_by_admin(self):
        self._check_delete_during_subject_upload(is_admin=True)

    def test_disable_purge_props(self):
        """
        Test the special x-subject-registry-purge-props header controls
        the purge property behaviour of the registry.
        :see LP Bug#901534
        """
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3',
                           'x-subject-meta-property-key1': 'value1'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = b"chunk00000remainder"
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)
        res_body = jsonutils.loads(res.body)['subject']

        self.assertIn('id', res_body)

        subject_id = res_body['id']
        self.assertIn('/subjects/%s' % subject_id, res.headers['location'])

        # Verify the status is queued
        self.assertIn('status', res_body)
        self.assertEqual('active', res_body['status'])

        # Check properties are not deleted
        self.assertIn('properties', res_body)
        self.assertIn('key1', res_body['properties'])
        self.assertEqual('value1', res_body['properties']['key1'])

        # Now update the subject, setting new properties without
        # passing the x-subject-registry-purge-props header and
        # verify that original properties are marked deleted.
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['x-subject-meta-property-key2'] = 'value2'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        # Verify the original property no longer in headers
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'HEAD'

        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertIn('x-subject-meta-property-key2', res.headers,
                      "Did not find required property in headers. "
                      "Got headers: %r" % res.headers)
        self.assertNotIn('x-subject-meta-property-key1', res.headers,
                         "Found property in headers that was not expected. "
                         "Got headers: %r" % res.headers)

        # Now update the subject, setting new properties and
        # passing the x-subject-registry-purge-props header with
        # a value of "false" and verify that second property
        # still appears in headers.
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'
        req.headers['x-subject-meta-property-key3'] = 'value3'
        req.headers['x-subject-registry-purge-props'] = 'false'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        # Verify the second and third property in headers
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'HEAD'

        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertIn('x-subject-meta-property-key2', res.headers,
                      "Did not find required property in headers. "
                      "Got headers: %r" % res.headers)
        self.assertIn('x-subject-meta-property-key3', res.headers,
                      "Did not find required property in headers. "
                      "Got headers: %r" % res.headers)

    def test_publicize_subject_unauthorized(self):
        """Create a non-public subject then fail to make public"""
        rules = {"add_subject": '@', "publicize_subject": '!'}
        self.set_policy_rules(rules)

        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-is-public': 'false',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        req = webob.Request.blank("/subjects/%s" % res_body['id'])
        req.method = 'PUT'
        req.headers['x-subject-meta-is-public'] = 'true'
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_update_subject_size_header_too_big(self):
        """Tests raises BadRequest for supplied subject size that is too big"""
        fixture_headers = {'x-subject-meta-size': CONF.subject_size_cap + 1}

        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'PUT'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_update_subject_size_data_too_big(self):
        self.config(subject_size_cap=512)

        fixture_headers = {'content-type': 'application/octet-stream'}
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'PUT'

        req.body = b'X' * (CONF.subject_size_cap + 1)
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_update_subject_size_chunked_data_too_big(self):
        self.config(subject_size_cap=512)

        # Create new subject that has no data
        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        req.headers['x-subject-meta-name'] = 'something'
        req.headers['x-subject-meta-container_format'] = 'ami'
        req.headers['x-subject-meta-disk_format'] = 'ami'
        res = req.get_response(self.api)
        subject_id = jsonutils.loads(res.body)['subject']['id']

        fixture_headers = {
            'content-type': 'application/octet-stream',
            'transfer-encoding': 'chunked',
        }
        req = webob.Request.blank("/subjects/%s" % subject_id)
        req.method = 'PUT'

        req.body_file = six.StringIO('X' * (CONF.subject_size_cap + 1))
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(413, res.status_int)

    def test_update_non_existing_subject(self):
        self.config(subject_size_cap=100)

        req = webob.Request.blank("subjects/%s" % _gen_uuid())
        req.method = 'PUT'
        req.body = b'test'
        req.headers['x-subject-meta-name'] = 'test'
        req.headers['x-subject-meta-container_format'] = 'ami'
        req.headers['x-subject-meta-disk_format'] = 'ami'
        req.headers['x-subject-meta-is_public'] = 'False'
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

    def test_update_public_subject(self):
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-is-public': 'true',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        req = webob.Request.blank("/subjects/%s" % res_body['id'])
        req.method = 'PUT'
        req.headers['x-subject-meta-name'] = 'updated public subject'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

    @mock.patch.object(registry, 'update_subject_metadata')
    def test_update_without_public_attribute(self, mock_update_subject_metadata):
        req = webob.Request.blank("/subjects/%s" % UUID1)
        req.context = self.context
        subject_meta = {'properties': {}}
        subject_controller = subject.api.v1.subjects.Controller()

        with mock.patch.object(
            subject_controller, 'update_store_acls'
        ) as mock_update_store_acls:
            mock_update_store_acls.return_value = None
            mock_update_subject_metadata.return_value = {}
            subject_controller.update(
                req, UUID1, subject_meta, None)
            self.assertEqual(0, mock_update_store_acls.call_count)

    def test_add_subject_wrong_content_type(self):
        fixture_headers = {
            'x-subject-meta-name': 'fake subject #3',
            'x-subject-meta-container_format': 'ami',
            'x-subject-meta-disk_format': 'ami',
            'transfer-encoding': 'chunked',
            'content-type': 'application/octet-st',
        }

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_get_index_sort_name_asc(self):
        """
        Tests that the /subjects API returns list of
        public subjects sorted alphabetically by name in
        ascending order.
        """
        UUID3 = _gen_uuid()
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'asdf',
                         'size': 19,
                         'checksum': None}

        db_api.subject_create(self.context, extra_fixture)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'xyz',
                         'size': 20,
                         'checksum': None}

        db_api.subject_create(self.context, extra_fixture)

        req = webob.Request.blank('/subjects?sort_key=name&sort_dir=asc')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        res_dict = jsonutils.loads(res.body)

        subjects = res_dict['subjects']
        self.assertEqual(3, len(subjects))
        self.assertEqual(UUID3, subjects[0]['id'])
        self.assertEqual(UUID2, subjects[1]['id'])
        self.assertEqual(UUID4, subjects[2]['id'])

    def test_get_details_filter_changes_since(self):
        """
        Tests that the /subjects/detail API returns list of
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
        extra_fixture = {'id': UUID3,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'fake subject #3',
                         'size': 18,
                         'checksum': None}

        db_api.subject_create(self.context, extra_fixture)
        db_api.subject_destroy(self.context, UUID3)

        UUID4 = _gen_uuid()
        extra_fixture = {'id': UUID4,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'ami',
                         'container_format': 'ami',
                         'name': 'fake subject #4',
                         'size': 20,
                         'checksum': None,
                         'created_at': subject_ts,
                         'updated_at': subject_ts}

        db_api.subject_create(self.context, extra_fixture)

        # Check a standard list, 4 subjects in db (2 deleted)
        req = webob.Request.blank('/subjects/detail')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        res_dict = jsonutils.loads(res.body)
        subjects = res_dict['subjects']
        self.assertEqual(2, len(subjects))
        self.assertEqual(UUID4, subjects[0]['id'])
        self.assertEqual(UUID2, subjects[1]['id'])

        # Expect 3 subjects (1 deleted)
        req = webob.Request.blank('/subjects/detail?changes-since=%s' % iso1)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        res_dict = jsonutils.loads(res.body)
        subjects = res_dict['subjects']
        self.assertEqual(3, len(subjects))
        self.assertEqual(UUID4, subjects[0]['id'])
        self.assertEqual(UUID3, subjects[1]['id'])  # deleted
        self.assertEqual(UUID2, subjects[2]['id'])

        # Expect 1 subjects (0 deleted)
        req = webob.Request.blank('/subjects/detail?changes-since=%s' % iso2)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        res_dict = jsonutils.loads(res.body)
        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(UUID4, subjects[0]['id'])

        # Expect 1 subjects (0 deleted)
        req = webob.Request.blank('/subjects/detail?changes-since=%s' %
                                  hour_before)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        res_dict = jsonutils.loads(res.body)
        subjects = res_dict['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(UUID4, subjects[0]['id'])

        # Expect 0 subjects (0 deleted)
        req = webob.Request.blank('/subjects/detail?changes-since=%s' %
                                  hour_after)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        res_dict = jsonutils.loads(res.body)
        subjects = res_dict['subjects']
        self.assertEqual(0, len(subjects))

        # Expect 0 subjects (0 deleted)
        req = webob.Request.blank('/subjects/detail?changes-since=%s' % iso4)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        res_dict = jsonutils.loads(res.body)
        subjects = res_dict['subjects']
        self.assertEqual(0, len(subjects))

        for param in [date_only1, date_only2, date_only3]:
            # Expect 3 subjects (1 deleted)
            req = webob.Request.blank('/subjects/detail?changes-since=%s' %
                                      param)
            res = req.get_response(self.api)
            self.assertEqual(200, res.status_int)
            res_dict = jsonutils.loads(res.body)
            subjects = res_dict['subjects']
            self.assertEqual(3, len(subjects))
            self.assertEqual(UUID4, subjects[0]['id'])
            self.assertEqual(UUID3, subjects[1]['id'])  # deleted
            self.assertEqual(UUID2, subjects[2]['id'])

        # Bad request (empty changes-since param)
        req = webob.Request.blank('/subjects/detail?changes-since=')
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_get_subjects_bad_urls(self):
        """Check that routes collections are not on (LP bug 1185828)"""
        req = webob.Request.blank('/subjects/detail.xxx')
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

        req = webob.Request.blank('/subjects.xxx')
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

        req = webob.Request.blank('/subjects/new')
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

        req = webob.Request.blank("/subjects/%s/members" % UUID1)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        req = webob.Request.blank("/subjects/%s/members.xxx" % UUID1)
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

    def test_get_index_filter_on_user_defined_properties(self):
        """Check that subject filtering works on user-defined properties"""

        subject1_id = _gen_uuid()
        properties = {'distro': 'ubuntu', 'arch': 'i386'}
        extra_fixture = {'id': subject1_id,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'vhd',
                         'container_format': 'ovf',
                         'name': 'subject-extra-1',
                         'size': 18, 'properties': properties,
                         'checksum': None}
        db_api.subject_create(self.context, extra_fixture)

        subject2_id = _gen_uuid()
        properties = {'distro': 'ubuntu', 'arch': 'x86_64', 'foo': 'bar'}
        extra_fixture = {'id': subject2_id,
                         'status': 'active',
                         'is_public': True,
                         'disk_format': 'ami',
                         'container_format': 'ami',
                         'name': 'subject-extra-2',
                         'size': 20, 'properties': properties,
                         'checksum': None}
        db_api.subject_create(self.context, extra_fixture)

        # Test index with filter containing one user-defined property.
        # Filter is 'property-distro=ubuntu'.
        # Verify both subject1 and subject2 are returned
        req = webob.Request.blank('/subjects?property-distro=ubuntu')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(2, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])
        self.assertEqual(subject1_id, subjects[1]['id'])

        # Test index with filter containing one user-defined property but
        # non-existent value. Filter is 'property-distro=fedora'.
        # Verify neither subjects are returned
        req = webob.Request.blank('/subjects?property-distro=fedora')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

        # Test index with filter containing one user-defined property but
        # unique value. Filter is 'property-arch=i386'.
        # Verify only subject1 is returned.
        req = webob.Request.blank('/subjects?property-arch=i386')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject1_id, subjects[0]['id'])

        # Test index with filter containing one user-defined property but
        # unique value. Filter is 'property-arch=x86_64'.
        # Verify only subject1 is returned.
        req = webob.Request.blank('/subjects?property-arch=x86_64')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])

        # Test index with filter containing unique user-defined property.
        # Filter is 'property-foo=bar'.
        # Verify only subject2 is returned.
        req = webob.Request.blank('/subjects?property-foo=bar')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])

        # Test index with filter containing unique user-defined property but
        # .value is non-existent. Filter is 'property-foo=baz'.
        # Verify neither subjects are returned.
        req = webob.Request.blank('/subjects?property-foo=baz')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

        # Test index with filter containing multiple user-defined properties
        # Filter is 'property-arch=x86_64&property-distro=ubuntu'.
        # Verify only subject2 is returned.
        req = webob.Request.blank('/subjects?property-arch=x86_64&'
                                  'property-distro=ubuntu')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject2_id, subjects[0]['id'])

        # Test index with filter containing multiple user-defined properties
        # Filter is 'property-arch=i386&property-distro=ubuntu'.
        # Verify only subject1 is returned.
        req = webob.Request.blank('/subjects?property-arch=i386&'
                                  'property-distro=ubuntu')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(1, len(subjects))
        self.assertEqual(subject1_id, subjects[0]['id'])

        # Test index with filter containing multiple user-defined properties.
        # Filter is 'property-arch=random&property-distro=ubuntu'.
        # Verify neither subjects are returned.
        req = webob.Request.blank('/subjects?property-arch=random&'
                                  'property-distro=ubuntu')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

        # Test index with filter containing multiple user-defined properties.
        # Filter is 'property-arch=random&property-distro=random'.
        # Verify neither subjects are returned.
        req = webob.Request.blank('/subjects?property-arch=random&'
                                  'property-distro=random')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

        # Test index with filter containing multiple user-defined properties.
        # Filter is 'property-boo=far&property-poo=far'.
        # Verify neither subjects are returned.
        req = webob.Request.blank('/subjects?property-boo=far&'
                                  'property-poo=far')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

        # Test index with filter containing multiple user-defined properties.
        # Filter is 'property-foo=bar&property-poo=far'.
        # Verify neither subjects are returned.
        req = webob.Request.blank('/subjects?property-foo=bar&'
                                  'property-poo=far')
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(0, len(subjects))

    def test_get_subjects_detailed_unauthorized(self):
        rules = {"get_subjects": '!'}
        self.set_policy_rules(rules)
        req = webob.Request.blank('/subjects/detail')
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_get_subjects_unauthorized(self):
        rules = {"get_subjects": '!'}
        self.set_policy_rules(rules)
        req = webob.Request.blank('/subjects')
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_store_location_not_revealed(self):
        """
        Test that the internal store location is NOT revealed
        through the API server
        """
        # Check index and details...
        for url in ('/subjects', '/subjects/detail'):
            req = webob.Request.blank(url)
            res = req.get_response(self.api)
            self.assertEqual(200, res.status_int)
            res_dict = jsonutils.loads(res.body)

            subjects = res_dict['subjects']
            num_locations = sum([1 for record in subjects
                                if 'location' in record.keys()])
            self.assertEqual(0, num_locations, subjects)

        # Check GET
        req = webob.Request.blank("/subjects/%s" % UUID2)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertNotIn('X-Subject-Meta-Location', res.headers)

        # Check HEAD
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertNotIn('X-Subject-Meta-Location', res.headers)

        # Check PUT
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.body = res.body
        req.method = 'PUT'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        res_body = jsonutils.loads(res.body)
        self.assertNotIn('location', res_body['subject'])

        # Check POST
        req = webob.Request.blank("/subjects")
        headers = {'x-subject-meta-location': 'http://localhost',
                   'x-subject-meta-disk-format': 'vhd',
                   'x-subject-meta-container-format': 'ovf',
                   'x-subject-meta-name': 'fake subject #3'}
        for k, v in six.iteritems(headers):
            req.headers[k] = v
        req.method = 'POST'

        http = store.get_store_from_scheme('http')

        with mock.patch.object(http, 'get_size') as size:
            size.return_value = 0
            res = req.get_response(self.api)
            self.assertEqual(201, res.status_int)
            res_body = jsonutils.loads(res.body)
            self.assertNotIn('location', res_body['subject'])

    def test_subject_is_checksummed(self):
        """Test that the subject contents are checksummed properly"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}
        subject_contents = b"chunk00000remainder"
        subject_checksum = hashlib.md5(subject_contents).hexdigest()

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = subject_contents
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual(subject_checksum, res_body['checksum'],
                         "Mismatched checksum. Expected %s, got %s" %
                         (subject_checksum, res_body['checksum']))

    def test_etag_equals_checksum_header(self):
        """Test that the ETag header matches the x-subject-meta-checksum"""
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}
        subject_contents = b"chunk00000remainder"
        subject_checksum = hashlib.md5(subject_contents).hexdigest()

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = subject_contents
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        subject = jsonutils.loads(res.body)['subject']

        # HEAD the subject and check the ETag equals the checksum header...
        expected_headers = {'x-subject-meta-checksum': subject_checksum,
                            'etag': subject_checksum}
        req = webob.Request.blank("/subjects/%s" % subject['id'])
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        for key in expected_headers.keys():
            self.assertIn(key, res.headers,
                          "required header '%s' missing from "
                          "returned headers" % key)
        for key, value in six.iteritems(expected_headers):
            self.assertEqual(value, res.headers[key])

    def test_bad_checksum_prevents_subject_creation(self):
        """Test that the subject contents are checksummed properly"""
        subject_contents = b"chunk00000remainder"
        bad_checksum = hashlib.md5(b"invalid").hexdigest()
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3',
                           'x-subject-meta-checksum': bad_checksum,
                           'x-subject-meta-is-public': 'true'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v

        req.headers['Content-Type'] = 'application/octet-stream'
        req.body = subject_contents
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

        # Test that only one subject was returned (that already exists)
        req = webob.Request.blank("/subjects")
        req.method = 'GET'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        subjects = jsonutils.loads(res.body)['subjects']
        self.assertEqual(1, len(subjects))

    def test_subject_meta(self):
        """Test for HEAD /subjects/<ID>"""
        expected_headers = {'x-subject-meta-id': UUID2,
                            'x-subject-meta-name': 'fake subject #2'}
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertFalse(res.location)

        for key, value in six.iteritems(expected_headers):
            self.assertEqual(value, res.headers[key])

    def test_subject_meta_unauthorized(self):
        rules = {"get_subject": '!'}
        self.set_policy_rules(rules)
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_show_subject_basic(self):
        req = webob.Request.blank("/subjects/%s" % UUID2)
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertFalse(res.location)
        self.assertEqual('application/octet-stream', res.content_type)
        self.assertEqual(b'chunk00000remainder', res.body)

    def test_show_non_exists_subject(self):
        req = webob.Request.blank("/subjects/%s" % _gen_uuid())
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

    def test_show_subject_unauthorized(self):
        rules = {"get_subject": '!'}
        self.set_policy_rules(rules)
        req = webob.Request.blank("/subjects/%s" % UUID2)
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_show_subject_unauthorized_download(self):
        rules = {"download_subject": '!'}
        self.set_policy_rules(rules)
        req = webob.Request.blank("/subjects/%s" % UUID2)
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_show_subject_restricted_download_for_core_property(self):
        rules = {
            "restricted":
            "not ('1024M':%(min_ram)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }
        self.set_policy_rules(rules)
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.headers['X-Auth-Token'] = 'user:tenant:_member_'
        req.headers['min_ram'] = '1024M'
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_show_subject_restricted_download_for_custom_property(self):
        rules = {
            "restricted":
            "not ('test_1234'==%(x_test_key)s and role:_member_)",
            "download_subject": "role:admin or rule:restricted"
        }
        self.set_policy_rules(rules)
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.headers['X-Auth-Token'] = 'user:tenant:_member_'
        req.headers['x_test_key'] = 'test_1234'
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_download_service_unavailable(self):
        """Test subject download returns HTTPServiceUnavailable."""
        subject_fixture = self.FIXTURES[1]
        subject_fixture.update({'location': 'http://0.0.0.0:1/file.tar.gz'})
        request = webob.Request.blank("/subjects/%s" % UUID2)
        request.context = self.context

        subject_controller = subject.api.v1.subjects.Controller()
        with mock.patch.object(subject_controller,
                               'get_active_subject_meta_or_error'
                               ) as mocked_get_subject:
            mocked_get_subject.return_value = subject_fixture
            self.assertRaises(webob.exc.HTTPServiceUnavailable,
                              subject_controller.show,
                              request, mocked_get_subject)

    @mock.patch('glance_store._drivers.filesystem.Store.get')
    def test_show_subject_store_get_not_support(self, m_get):
        m_get.side_effect = store.StoreGetNotSupported()
        req = webob.Request.blank("/subjects/%s" % UUID2)
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    @mock.patch('glance_store._drivers.filesystem.Store.get')
    def test_show_subject_store_random_get_not_support(self, m_get):
        m_get.side_effect = store.StoreRandomGetNotSupported(chunk_size=0,
                                                             offset=0)
        req = webob.Request.blank("/subjects/%s" % UUID2)
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_delete_subject(self):
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertFalse(res.location)
        self.assertEqual(b'', res.body)

        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'GET'
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int, res.body)

        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertEqual('True', res.headers['x-subject-meta-deleted'])
        self.assertEqual('deleted', res.headers['x-subject-meta-status'])

    def test_delete_non_exists_subject(self):
        req = webob.Request.blank("/subjects/%s" % _gen_uuid())
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

    def test_delete_not_allowed(self):
        # Verify we can get the subject data
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'GET'
        req.headers['X-Auth-Token'] = 'user:tenant:'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertEqual(19, len(res.body))

        # Verify we cannot delete the subject
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

        # Verify the subject data is still there
        req.method = 'GET'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertEqual(19, len(res.body))

    def test_delete_queued_subject(self):
        """Delete an subject in a queued state

        Bug #747799 demonstrated that trying to DELETE an subject
        that had had its save process killed manually results in failure
        because the location attribute is None.

        Bug #1048851 demonstrated that the status was not properly
        being updated to 'deleted' from 'queued'.
        """
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])

        # Now try to delete the subject...
        req = webob.Request.blank("/subjects/%s" % res_body['id'])
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        req = webob.Request.blank('/subjects/%s' % res_body['id'])
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertEqual('True', res.headers['x-subject-meta-deleted'])
        self.assertEqual('deleted', res.headers['x-subject-meta-status'])

    def test_delete_queued_subject_delayed_delete(self):
        """Delete an subject in a queued state when delayed_delete is on

        Bug #1048851 demonstrated that the status was not properly
        being updated to 'deleted' from 'queued'.
        """
        self.config(delayed_delete=True)
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-name': 'fake subject #3'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])

        # Now try to delete the subject...
        req = webob.Request.blank("/subjects/%s" % res_body['id'])
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        req = webob.Request.blank('/subjects/%s' % res_body['id'])
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        self.assertEqual('True', res.headers['x-subject-meta-deleted'])
        self.assertEqual('deleted', res.headers['x-subject-meta-status'])

    def test_delete_protected_subject(self):
        fixture_headers = {'x-subject-meta-store': 'file',
                           'x-subject-meta-name': 'fake subject #3',
                           'x-subject-meta-disk-format': 'vhd',
                           'x-subject-meta-container-format': 'ovf',
                           'x-subject-meta-protected': 'True'}

        req = webob.Request.blank("/subjects")
        req.method = 'POST'
        for k, v in six.iteritems(fixture_headers):
            req.headers[k] = v
        res = req.get_response(self.api)
        self.assertEqual(201, res.status_int)

        res_body = jsonutils.loads(res.body)['subject']
        self.assertEqual('queued', res_body['status'])

        # Now try to delete the subject...
        req = webob.Request.blank("/subjects/%s" % res_body['id'])
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_delete_subject_unauthorized(self):
        rules = {"delete_subject": '!'}
        self.set_policy_rules(rules)
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(403, res.status_int)

    def test_head_details(self):
        req = webob.Request.blank('/subjects/detail')
        req.method = 'HEAD'
        res = req.get_response(self.api)
        self.assertEqual(405, res.status_int)
        self.assertEqual('GET', res.headers.get('Allow'))
        self.assertEqual(('GET',), res.allow)
        req.method = 'GET'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

    def test_get_details_invalid_marker(self):
        """
        Tests that the /subjects/detail API returns a 400
        when an invalid marker is provided
        """
        req = webob.Request.blank('/subjects/detail?marker=%s' % _gen_uuid())
        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_get_subject_members(self):
        """
        Tests members listing for existing subjects
        """
        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'GET'

        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        memb_list = jsonutils.loads(res.body)
        num_members = len(memb_list['members'])
        self.assertEqual(0, num_members)

    def test_get_subject_members_allowed_by_policy(self):
        rules = {"get_members": '@'}
        self.set_policy_rules(rules)

        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'GET'

        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        memb_list = jsonutils.loads(res.body)
        num_members = len(memb_list['members'])
        self.assertEqual(0, num_members)

    def test_get_subject_members_forbidden_by_policy(self):
        rules = {"get_members": '!'}
        self.set_policy_rules(rules)

        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'GET'

        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPForbidden.code, res.status_int)

    def test_get_subject_members_not_existing(self):
        """
        Tests proper exception is raised if attempt to get members of
        non-existing subject
        """
        req = webob.Request.blank('/subjects/%s/members' % _gen_uuid())
        req.method = 'GET'

        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

    def test_add_member_positive(self):
        """
        Tests adding subject members
        """
        test_router_api = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router_api, is_admin=True)
        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID2)
        req.method = 'PUT'

        res = req.get_response(self.api)
        self.assertEqual(204, res.status_int)

    def test_get_member_subjects(self):
        """
        Tests subject listing for members
        """
        req = webob.Request.blank('/shared-subjects/pattieblack')
        req.method = 'GET'

        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        memb_list = jsonutils.loads(res.body)
        num_members = len(memb_list['shared_subjects'])
        self.assertEqual(0, num_members)

    def test_replace_members(self):
        """
        Tests replacing subject members raises right exception
        """
        test_router_api = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router_api, is_admin=False)
        fixture = dict(member_id='pattieblack')

        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(subject_memberships=fixture))

        res = req.get_response(self.api)
        self.assertEqual(401, res.status_int)

    def test_active_subject_immutable_props_for_user(self):
        """
        Tests user cannot update immutable props of active subject
        """
        test_router_api = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router_api, is_admin=False)
        fixture_header_list = [{'x-subject-meta-checksum': '1234'},
                               {'x-subject-meta-size': '12345'}]
        for fixture_header in fixture_header_list:
            req = webob.Request.blank('/subjects/%s' % UUID2)
            req.method = 'PUT'
            for k, v in six.iteritems(fixture_header):
                req = webob.Request.blank('/subjects/%s' % UUID2)
                req.method = 'HEAD'
                res = req.get_response(self.api)
                self.assertEqual(200, res.status_int)
                orig_value = res.headers[k]

                req = webob.Request.blank('/subjects/%s' % UUID2)
                req.headers[k] = v
                req.method = 'PUT'
                res = req.get_response(self.api)
                self.assertEqual(403, res.status_int)
                prop = k[len('x-subject-meta-'):]
                body = res.body.decode('utf-8')
                self.assertNotEqual(-1, body.find(
                    "Forbidden to modify '%s' of active subject" % prop))

                req = webob.Request.blank('/subjects/%s' % UUID2)
                req.method = 'HEAD'
                res = req.get_response(self.api)
                self.assertEqual(200, res.status_int)
                self.assertEqual(orig_value, res.headers[k])

    def test_deactivated_subject_immutable_props_for_user(self):
        """
        Tests user cannot update immutable props of deactivated subject
        """
        test_router_api = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router_api, is_admin=False)
        fixture_header_list = [{'x-subject-meta-checksum': '1234'},
                               {'x-subject-meta-size': '12345'}]
        for fixture_header in fixture_header_list:
            req = webob.Request.blank('/subjects/%s' % UUID3)
            req.method = 'PUT'
            for k, v in six.iteritems(fixture_header):
                req = webob.Request.blank('/subjects/%s' % UUID3)
                req.method = 'HEAD'
                res = req.get_response(self.api)
                self.assertEqual(200, res.status_int)
                orig_value = res.headers[k]

                req = webob.Request.blank('/subjects/%s' % UUID3)
                req.headers[k] = v
                req.method = 'PUT'
                res = req.get_response(self.api)
                self.assertEqual(403, res.status_int)
                prop = k[len('x-subject-meta-'):]
                body = res.body.decode('utf-8')
                self.assertNotEqual(-1, body.find(
                    "Forbidden to modify '%s' of deactivated subject" % prop))

                req = webob.Request.blank('/subjects/%s' % UUID3)
                req.method = 'HEAD'
                res = req.get_response(self.api)
                self.assertEqual(200, res.status_int)
                self.assertEqual(orig_value, res.headers[k])

    def test_props_of_active_subject_mutable_for_admin(self):
        """
        Tests admin can update 'immutable' props of active subject
        """
        test_router_api = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router_api, is_admin=True)
        fixture_header_list = [{'x-subject-meta-checksum': '1234'},
                               {'x-subject-meta-size': '12345'}]
        for fixture_header in fixture_header_list:
            req = webob.Request.blank('/subjects/%s' % UUID2)
            req.method = 'PUT'
            for k, v in six.iteritems(fixture_header):
                req = webob.Request.blank('/subjects/%s' % UUID2)
                req.method = 'HEAD'
                res = req.get_response(self.api)
                self.assertEqual(200, res.status_int)

                req = webob.Request.blank('/subjects/%s' % UUID2)
                req.headers[k] = v
                req.method = 'PUT'
                res = req.get_response(self.api)
                self.assertEqual(200, res.status_int)

                req = webob.Request.blank('/subjects/%s' % UUID2)
                req.method = 'HEAD'
                res = req.get_response(self.api)
                self.assertEqual(200, res.status_int)
                self.assertEqual(v, res.headers[k])

    def test_props_of_deactivated_subject_mutable_for_admin(self):
        """
        Tests admin can update 'immutable' props of deactivated subject
        """
        test_router_api = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router_api, is_admin=True)
        fixture_header_list = [{'x-subject-meta-checksum': '1234'},
                               {'x-subject-meta-size': '12345'}]
        for fixture_header in fixture_header_list:
            req = webob.Request.blank('/subjects/%s' % UUID3)
            req.method = 'PUT'
            for k, v in six.iteritems(fixture_header):
                req = webob.Request.blank('/subjects/%s' % UUID3)
                req.method = 'HEAD'
                res = req.get_response(self.api)
                self.assertEqual(200, res.status_int)

                req = webob.Request.blank('/subjects/%s' % UUID3)
                req.headers[k] = v
                req.method = 'PUT'
                res = req.get_response(self.api)
                self.assertEqual(200, res.status_int)

                req = webob.Request.blank('/subjects/%s' % UUID3)
                req.method = 'HEAD'
                res = req.get_response(self.api)
                self.assertEqual(200, res.status_int)
                self.assertEqual(v, res.headers[k])

    def test_replace_members_non_existing_subject(self):
        """
        Tests replacing subject members raises right exception
        """
        test_router_api = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router_api, is_admin=True)
        fixture = dict(member_id='pattieblack')
        req = webob.Request.blank('/subjects/%s/members' % _gen_uuid())
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(subject_memberships=fixture))

        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

    def test_replace_members_bad_request(self):
        """
        Tests replacing subject members raises bad request if body is wrong
        """
        test_router_api = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router_api, is_admin=True)
        fixture = dict(member_id='pattieblack')

        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(subject_memberships=fixture))

        res = req.get_response(self.api)
        self.assertEqual(400, res.status_int)

    def test_replace_members_positive(self):
        """
        Tests replacing subject members
        """
        test_router = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router, is_admin=True)

        fixture = [dict(member_id='pattieblack', can_share=False)]
        # Replace
        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(memberships=fixture))
        res = req.get_response(self.api)
        self.assertEqual(204, res.status_int)

    def test_replace_members_forbidden_by_policy(self):
        rules = {"modify_member": '!'}
        self.set_policy_rules(rules)
        self.api = test_utils.FakeAuthMiddleware(router.API(self.mapper),
                                                 is_admin=True)
        fixture = [{'member_id': 'pattieblack', 'can_share': 'false'}]

        req = webob.Request.blank('/subjects/%s/members' % UUID1)
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(memberships=fixture))

        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPForbidden.code, res.status_int)

    def test_replace_members_allowed_by_policy(self):
        rules = {"modify_member": '@'}
        self.set_policy_rules(rules)
        self.api = test_utils.FakeAuthMiddleware(router.API(self.mapper),
                                                 is_admin=True)
        fixture = [{'member_id': 'pattieblack', 'can_share': 'false'}]

        req = webob.Request.blank('/subjects/%s/members' % UUID1)
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(memberships=fixture))

        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)

    def test_add_member_unauthorized(self):
        """
        Tests adding subject members raises right exception
        """
        test_router = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router, is_admin=False)
        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID2)
        req.method = 'PUT'

        res = req.get_response(self.api)
        self.assertEqual(401, res.status_int)

    def test_add_member_non_existing_subject(self):
        """
        Tests adding subject members raises right exception
        """
        test_router = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router, is_admin=True)
        test_uri = '/subjects/%s/members/pattieblack'
        req = webob.Request.blank(test_uri % _gen_uuid())
        req.method = 'PUT'

        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)

    def test_add_member_with_body(self):
        """
        Tests adding subject members
        """
        fixture = dict(can_share=True)
        test_router = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router, is_admin=True)
        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID2)
        req.method = 'PUT'
        req.body = jsonutils.dump_as_bytes(dict(member=fixture))
        res = req.get_response(self.api)
        self.assertEqual(204, res.status_int)

    def test_add_member_overlimit(self):
        self.config(subject_member_quota=0)
        test_router_api = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router_api, is_admin=True)
        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID2)
        req.method = 'PUT'

        res = req.get_response(self.api)
        self.assertEqual(413, res.status_int)

    def test_add_member_unlimited(self):
        self.config(subject_member_quota=-1)
        test_router_api = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router_api, is_admin=True)
        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID2)
        req.method = 'PUT'

        res = req.get_response(self.api)
        self.assertEqual(204, res.status_int)

    def test_add_member_forbidden_by_policy(self):
        rules = {"modify_member": '!'}
        self.set_policy_rules(rules)
        self.api = test_utils.FakeAuthMiddleware(router.API(self.mapper),
                                                 is_admin=True)
        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID1)
        req.method = 'PUT'

        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPForbidden.code, res.status_int)

    def test_add_member_allowed_by_policy(self):
        rules = {"modify_member": '@'}
        self.set_policy_rules(rules)
        self.api = test_utils.FakeAuthMiddleware(router.API(self.mapper),
                                                 is_admin=True)
        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID1)
        req.method = 'PUT'

        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)

    def test_get_members_of_deleted_subject_raises_404(self):
        """
        Tests members listing for deleted subject raises 404.
        """
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'GET'

        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPNotFound.code, res.status_int)
        self.assertIn('Subject with identifier %s has been deleted.' % UUID2,
                      res.body.decode())

    def test_delete_member_of_deleted_subject_raises_404(self):
        """
        Tests deleting members of deleted subject raises 404.
        """
        test_router = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(test_router, is_admin=True)
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID2)
        req.method = 'DELETE'

        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPNotFound.code, res.status_int)
        self.assertIn('Subject with identifier %s has been deleted.' % UUID2,
                      res.body.decode())

    def test_update_members_of_deleted_subject_raises_404(self):
        """
        Tests update members of deleted subject raises 404.
        """
        test_router = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(test_router, is_admin=True)

        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID2)
        req.method = 'PUT'
        res = req.get_response(self.api)
        self.assertEqual(204, res.status_int)

        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        fixture = [{'member_id': 'pattieblack', 'can_share': 'false'}]
        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(memberships=fixture))
        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPNotFound.code, res.status_int)
        body = res.body.decode('utf-8')
        self.assertIn(
            'Subject with identifier %s has been deleted.' % UUID2, body)

    def test_replace_members_of_subject(self):
        test_router = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(test_router, is_admin=True)

        fixture = [{'member_id': 'pattieblack', 'can_share': 'false'}]
        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'PUT'
        req.body = jsonutils.dump_as_bytes(dict(memberships=fixture))
        res = req.get_response(self.api)
        self.assertEqual(204, res.status_int)

        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'GET'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        memb_list = jsonutils.loads(res.body)
        self.assertEqual(1, len(memb_list))

    def test_replace_members_of_subject_overlimit(self):
        # Set subject_member_quota to 1
        self.config(subject_member_quota=1)
        test_router = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(test_router, is_admin=True)

        # PUT an original member entry
        fixture = [{'member_id': 'baz', 'can_share': False}]
        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'PUT'
        req.body = jsonutils.dump_as_bytes(dict(memberships=fixture))
        res = req.get_response(self.api)
        self.assertEqual(204, res.status_int)

        # GET original subject member list
        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'GET'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)
        original_members = jsonutils.loads(res.body)['members']
        self.assertEqual(1, len(original_members))

        # PUT 2 subject members to replace existing (overlimit)
        fixture = [{'member_id': 'foo1', 'can_share': False},
                   {'member_id': 'foo2', 'can_share': False}]
        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'PUT'
        req.body = jsonutils.dump_as_bytes(dict(memberships=fixture))
        res = req.get_response(self.api)
        self.assertEqual(413, res.status_int)

        # GET member list
        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'GET'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        # Assert the member list was not changed
        memb_list = jsonutils.loads(res.body)['members']
        self.assertEqual(original_members, memb_list)

    def test_replace_members_of_subject_unlimited(self):
        self.config(subject_member_quota=-1)
        test_router = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(test_router, is_admin=True)

        fixture = [{'member_id': 'foo1', 'can_share': False},
                   {'member_id': 'foo2', 'can_share': False}]
        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'PUT'
        req.body = jsonutils.dump_as_bytes(dict(memberships=fixture))
        res = req.get_response(self.api)
        self.assertEqual(204, res.status_int)

        req = webob.Request.blank('/subjects/%s/members' % UUID2)
        req.method = 'GET'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        memb_list = jsonutils.loads(res.body)['members']
        self.assertEqual(fixture, memb_list)

    def test_create_member_to_deleted_subject_raises_404(self):
        """
        Tests adding members to deleted subject raises 404.
        """
        test_router = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(test_router, is_admin=True)
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(200, res.status_int)

        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID2)
        req.method = 'PUT'

        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPNotFound.code, res.status_int)
        self.assertIn('Subject with identifier %s has been deleted.' % UUID2,
                      res.body.decode())

    def test_delete_member(self):
        """
        Tests deleting subject members raises right exception
        """
        test_router = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_router, is_admin=False)
        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID2)
        req.method = 'DELETE'

        res = req.get_response(self.api)
        self.assertEqual(401, res.status_int)

    def test_delete_member_on_non_existing_subject(self):
        """
        Tests deleting subject members raises right exception
        """
        test_router = router.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(test_router, is_admin=True)
        test_uri = '/subjects/%s/members/pattieblack'
        req = webob.Request.blank(test_uri % _gen_uuid())
        req.method = 'DELETE'

        res = req.get_response(api)
        self.assertEqual(404, res.status_int)

    def test_delete_non_exist_member(self):
        """
        Test deleting subject members raises right exception
        """
        test_router = router.API(self.mapper)
        api = test_utils.FakeAuthMiddleware(
            test_router, is_admin=True)
        req = webob.Request.blank('/subjects/%s/members/test_user' % UUID2)
        req.method = 'DELETE'
        res = req.get_response(api)
        self.assertEqual(404, res.status_int)

    def test_delete_subject_member(self):
        test_rserver = router.API(self.mapper)
        self.api = test_utils.FakeAuthMiddleware(
            test_rserver, is_admin=True)

        # Add member to subject:
        fixture = dict(can_share=True)
        test_uri = '/subjects/%s/members/test_add_member_positive'
        req = webob.Request.blank(test_uri % UUID2)
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(dict(member=fixture))
        res = req.get_response(self.api)
        self.assertEqual(204, res.status_int)

        # Delete member
        test_uri = '/subjects/%s/members/test_add_member_positive'
        req = webob.Request.blank(test_uri % UUID2)
        req.headers['X-Auth-Token'] = 'test1:test1:'
        req.method = 'DELETE'
        req.content_type = 'application/json'
        res = req.get_response(self.api)
        self.assertEqual(404, res.status_int)
        self.assertIn(b'Forbidden', res.body)

    def test_delete_member_allowed_by_policy(self):
        rules = {"delete_member": '@', "modify_member": '@'}
        self.set_policy_rules(rules)
        self.api = test_utils.FakeAuthMiddleware(router.API(self.mapper),
                                                 is_admin=True)
        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID2)
        req.method = 'PUT'
        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)

    def test_delete_member_forbidden_by_policy(self):
        rules = {"delete_member": '!', "modify_member": '@'}
        self.set_policy_rules(rules)
        self.api = test_utils.FakeAuthMiddleware(router.API(self.mapper),
                                                 is_admin=True)
        req = webob.Request.blank('/subjects/%s/members/pattieblack' % UUID2)
        req.method = 'PUT'
        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)
        req.method = 'DELETE'
        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPForbidden.code, res.status_int)


class TestSubjectSerializer(base.IsolatedUnitTest):
    def setUp(self):
        """Establish a clean test environment"""
        super(TestSubjectSerializer, self).setUp()
        self.receiving_user = 'fake_user'
        self.receiving_tenant = 2
        self.context = subject.context.RequestContext(
            is_admin=True,
            user=self.receiving_user,
            tenant=self.receiving_tenant)
        self.serializer = subject.api.v1.subjects.SubjectSerializer()

        def subject_iter():
            for x in [b'chunk', b'678911234', b'56789']:
                yield x

        self.FIXTURE = {
            'subject_iterator': subject_iter(),
            'subject_meta': {
                'id': UUID2,
                'name': 'fake subject #2',
                'status': 'active',
                'disk_format': 'vhd',
                'container_format': 'ovf',
                'is_public': True,
                'created_at': timeutils.utcnow(),
                'updated_at': timeutils.utcnow(),
                'deleted_at': None,
                'deleted': False,
                'checksum': '06ff575a2856444fbe93100157ed74ab92eb7eff',
                'size': 19,
                'owner': _gen_uuid(),
                'location': "file:///tmp/subject-tests/2",
                'properties': {},
            }
        }

    def test_meta(self):
        exp_headers = {'x-subject-meta-id': UUID2,
                       'x-subject-meta-location': 'file:///tmp/subject-tests/2',
                       'ETag': self.FIXTURE['subject_meta']['checksum'],
                       'x-subject-meta-name': 'fake subject #2'}
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'HEAD'
        req.remote_addr = "1.2.3.4"
        req.context = self.context
        response = webob.Response(request=req)
        self.serializer.meta(response, self.FIXTURE)
        for key, value in six.iteritems(exp_headers):
            self.assertEqual(value, response.headers[key])

    def test_meta_utf8(self):
        # We get unicode strings from JSON, and therefore all strings in the
        # metadata will actually be unicode when handled internally. But we
        # want to output utf-8.
        FIXTURE = {
            'subject_meta': {
                'id': six.text_type(UUID2),
                'name': u'fake subject #2 with utf-8 éàè',
                'status': u'active',
                'disk_format': u'vhd',
                'container_format': u'ovf',
                'is_public': True,
                'created_at': timeutils.utcnow(),
                'updated_at': timeutils.utcnow(),
                'deleted_at': None,
                'deleted': False,
                'checksum': u'06ff575a2856444fbe93100157ed74ab92eb7eff',
                'size': 19,
                'owner': six.text_type(_gen_uuid()),
                'location': u"file:///tmp/subject-tests/2",
                'properties': {
                    u'prop_éé': u'ça marche',
                    u'prop_çé': u'çé',
                }
            }
        }
        exp_headers = {'x-subject-meta-id': UUID2,
                       'x-subject-meta-location': 'file:///tmp/subject-tests/2',
                       'ETag': '06ff575a2856444fbe93100157ed74ab92eb7eff',
                       'x-subject-meta-size': '19',  # str, not int
                       'x-subject-meta-name': 'fake subject #2 with utf-8 éàè',
                       'x-subject-meta-property-prop_éé': 'ça marche',
                       'x-subject-meta-property-prop_çé': 'çé'}
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'HEAD'
        req.remote_addr = "1.2.3.4"
        req.context = self.context
        response = webob.Response(request=req)
        self.serializer.meta(response, FIXTURE)
        if six.PY2:
            self.assertNotEqual(type(FIXTURE['subject_meta']['name']),
                                type(response.headers['x-subject-meta-name']))
        if six.PY3:
            self.assertEqual(FIXTURE['subject_meta']['name'],
                             response.headers['x-subject-meta-name'])
        else:
            self.assertEqual(
                FIXTURE['subject_meta']['name'],
                response.headers['x-subject-meta-name'].decode('utf-8'))

        for key, value in six.iteritems(exp_headers):
            self.assertEqual(value, response.headers[key])

        if six.PY2:
            FIXTURE['subject_meta']['properties'][u'prop_bad'] = 'çé'
            self.assertRaises(UnicodeDecodeError,
                              self.serializer.meta, response, FIXTURE)

    def test_show(self):
        exp_headers = {'x-subject-meta-id': UUID2,
                       'x-subject-meta-location': 'file:///tmp/subject-tests/2',
                       'ETag': self.FIXTURE['subject_meta']['checksum'],
                       'x-subject-meta-name': 'fake subject #2'}
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'GET'
        req.context = self.context
        response = webob.Response(request=req)
        self.serializer.show(response, self.FIXTURE)
        for key, value in six.iteritems(exp_headers):
            self.assertEqual(value, response.headers[key])

        self.assertEqual(b'chunk67891123456789', response.body)

    def test_show_notify(self):
        """Make sure an eventlet posthook for notify_subject_sent is added."""
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'GET'
        req.context = self.context
        response = webob.Response(request=req)
        response.request.environ['eventlet.posthooks'] = []

        self.serializer.show(response, self.FIXTURE)

        # just make sure the app_iter is called
        for chunk in response.app_iter:
            pass

        self.assertNotEqual([], response.request.environ['eventlet.posthooks'])

    def test_subject_send_notification(self):
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'GET'
        req.remote_addr = '1.2.3.4'
        req.context = self.context

        subject_meta = self.FIXTURE['subject_meta']
        called = {"notified": False}
        expected_payload = {
            'bytes_sent': 19,
            'subject_id': UUID2,
            'owner_id': subject_meta['owner'],
            'receiver_tenant_id': self.receiving_tenant,
            'receiver_user_id': self.receiving_user,
            'destination_ip': '1.2.3.4',
        }

        def fake_info(_event_type, _payload):
            self.assertEqual(expected_payload, _payload)
            called['notified'] = True

        self.stubs.Set(self.serializer.notifier, 'info', fake_info)

        subject.api.common.subject_send_notification(19, 19, subject_meta, req,
                                                   self.serializer.notifier)

        self.assertTrue(called['notified'])

    def test_subject_send_notification_error(self):
        """Ensure subject.send notification is sent on error."""
        req = webob.Request.blank("/subjects/%s" % UUID2)
        req.method = 'GET'
        req.remote_addr = '1.2.3.4'
        req.context = self.context

        subject_meta = self.FIXTURE['subject_meta']
        called = {"notified": False}
        expected_payload = {
            'bytes_sent': 17,
            'subject_id': UUID2,
            'owner_id': subject_meta['owner'],
            'receiver_tenant_id': self.receiving_tenant,
            'receiver_user_id': self.receiving_user,
            'destination_ip': '1.2.3.4',
        }

        def fake_error(_event_type, _payload):
            self.assertEqual(expected_payload, _payload)
            called['notified'] = True

        self.stubs.Set(self.serializer.notifier, 'error', fake_error)

        # expected and actually sent bytes differ
        subject.api.common.subject_send_notification(17, 19, subject_meta, req,
                                                   self.serializer.notifier)

        self.assertTrue(called['notified'])

    def test_redact_location(self):
        """Ensure location redaction does not change original metadata"""
        subject_meta = {'size': 3, 'id': '123', 'location': 'http://localhost'}
        redacted_subject_meta = {'size': 3, 'id': '123'}
        copy_subject_meta = copy.deepcopy(subject_meta)
        tmp_subject_meta = subject.api.v1.subjects.redact_loc(subject_meta)

        self.assertEqual(subject_meta, copy_subject_meta)
        self.assertEqual(redacted_subject_meta, tmp_subject_meta)

    def test_noop_redact_location(self):
        """Check no-op location redaction does not change original metadata"""
        subject_meta = {'size': 3, 'id': '123'}
        redacted_subject_meta = {'size': 3, 'id': '123'}
        copy_subject_meta = copy.deepcopy(subject_meta)
        tmp_subject_meta = subject.api.v1.subjects.redact_loc(subject_meta)

        self.assertEqual(subject_meta, copy_subject_meta)
        self.assertEqual(redacted_subject_meta, tmp_subject_meta)
        self.assertEqual(redacted_subject_meta, subject_meta)


class TestFilterValidator(base.IsolatedUnitTest):
    def test_filter_validator(self):
        self.assertFalse(subject.api.v1.filters.validate('size_max', -1))
        self.assertTrue(subject.api.v1.filters.validate('size_max', 1))
        self.assertTrue(subject.api.v1.filters.validate('protected', 'True'))
        self.assertTrue(subject.api.v1.filters.validate('protected', 'FALSE'))
        self.assertFalse(subject.api.v1.filters.validate('protected', '-1'))


class TestAPIProtectedProps(base.IsolatedUnitTest):
    def setUp(self):
        """Establish a clean test environment"""
        super(TestAPIProtectedProps, self).setUp()
        self.mapper = routes.Mapper()
        # turn on property protections
        self.set_property_protections()
        self.api = test_utils.FakeAuthMiddleware(router.API(self.mapper))
        db_api.get_engine()
        db_models.unregister_models(db_api.get_engine())
        db_models.register_models(db_api.get_engine())

    def tearDown(self):
        """Clear the test environment"""
        super(TestAPIProtectedProps, self).tearDown()
        self.destroy_fixtures()

    def destroy_fixtures(self):
        # Easiest to just drop the models and re-create them...
        db_models.unregister_models(db_api.get_engine())
        db_models.register_models(db_api.get_engine())

    def _create_admin_subject(self, props=None):
        if props is None:
            props = {}
        request = unit_test_utils.get_fake_request(path='/subjects')
        headers = {'x-subject-meta-disk-format': 'ami',
                   'x-subject-meta-container-format': 'ami',
                   'x-subject-meta-name': 'foo',
                   'x-subject-meta-size': '0',
                   'x-auth-token': 'user:tenant:admin'}
        headers.update(props)
        for k, v in six.iteritems(headers):
            request.headers[k] = v
        created_subject = request.get_response(self.api)
        res_body = jsonutils.loads(created_subject.body)['subject']
        subject_id = res_body['id']
        return subject_id

    def test_prop_protection_with_create_and_permitted_role(self):
        """
        As admin role, create an subject and verify permitted role 'member' can
        create a protected property
        """
        subject_id = self._create_admin_subject()
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'x-subject-meta-property-x_owner_foo': 'bar'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('bar', res_body['properties']['x_owner_foo'])

    def test_prop_protection_with_permitted_policy_config(self):
        """
        As admin role, create an subject and verify permitted role 'member' can
        create a protected property
        """
        self.set_property_protections(use_policies=True)
        subject_id = self._create_admin_subject()
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:admin',
                   'x-subject-meta-property-spl_create_prop_policy': 'bar'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('bar',
                         res_body['properties']['spl_create_prop_policy'])

    def test_prop_protection_with_create_and_unpermitted_role(self):
        """
        As admin role, create an subject and verify unpermitted role
        'fake_member' can *not* create a protected property
        """
        subject_id = self._create_admin_subject()
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:fake_member',
                   'x-subject-meta-property-x_owner_foo': 'bar'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        another_request.get_response(self.api)
        output = another_request.get_response(self.api)
        self.assertEqual(webob.exc.HTTPForbidden.code, output.status_int)
        self.assertIn("Property '%s' is protected" %
                      "x_owner_foo", output.body.decode())

    def test_prop_protection_with_show_and_permitted_role(self):
        """
        As admin role, create an subject with a protected property, and verify
        permitted role 'member' can read that protected property via HEAD
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            method='HEAD', path='/subjects/%s' % subject_id)
        headers = {'x-auth-token': 'user:tenant:member'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        res2 = another_request.get_response(self.api)
        self.assertEqual('bar',
                         res2.headers['x-subject-meta-property-x_owner_foo'])

    def test_prop_protection_with_show_and_unpermitted_role(self):
        """
        As admin role, create an subject with a protected property, and verify
        permitted role 'fake_role' can *not* read that protected property via
        HEAD
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            method='HEAD', path='/subjects/%s' % subject_id)
        headers = {'x-auth-token': 'user:tenant:fake_role'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        self.assertEqual(b'', output.body)
        self.assertNotIn('x-subject-meta-property-x_owner_foo', output.headers)

    def test_prop_protection_with_get_and_permitted_role(self):
        """
        As admin role, create an subject with a protected property, and verify
        permitted role 'member' can read that protected property via GET
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            method='GET', path='/subjects/%s' % subject_id)
        headers = {'x-auth-token': 'user:tenant:member'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        res2 = another_request.get_response(self.api)
        self.assertEqual('bar',
                         res2.headers['x-subject-meta-property-x_owner_foo'])

    def test_prop_protection_with_get_and_unpermitted_role(self):
        """
        As admin role, create an subject with a protected property, and verify
        permitted role 'fake_role' can *not* read that protected property via
        GET
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            method='GET', path='/subjects/%s' % subject_id)
        headers = {'x-auth-token': 'user:tenant:fake_role'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        self.assertEqual(b'', output.body)
        self.assertNotIn('x-subject-meta-property-x_owner_foo', output.headers)

    def test_prop_protection_with_detail_and_permitted_role(self):
        """
        As admin role, create an subject with a protected property, and verify
        permitted role 'member' can read that protected property via
        /subjects/detail
        """
        self._create_admin_subject({'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            method='GET', path='/subjects/detail')
        headers = {'x-auth-token': 'user:tenant:member'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        res_body = jsonutils.loads(output.body)['subjects'][0]
        self.assertEqual('bar', res_body['properties']['x_owner_foo'])

    def test_prop_protection_with_detail_and_permitted_policy(self):
        """
        As admin role, create an subject with a protected property, and verify
        permitted role 'member' can read that protected property via
        /subjects/detail
        """
        self.set_property_protections(use_policies=True)
        self._create_admin_subject({'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            method='GET', path='/subjects/detail')
        headers = {'x-auth-token': 'user:tenant:member'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        res_body = jsonutils.loads(output.body)['subjects'][0]
        self.assertEqual('bar', res_body['properties']['x_owner_foo'])

    def test_prop_protection_with_detail_and_unpermitted_role(self):
        """
        As admin role, create an subject with a protected property, and verify
        permitted role 'fake_role' can *not* read that protected property via
        /subjects/detail
        """
        self._create_admin_subject({'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            method='GET', path='/subjects/detail')
        headers = {'x-auth-token': 'user:tenant:fake_role'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        res_body = jsonutils.loads(output.body)['subjects'][0]
        self.assertNotIn('x-subject-meta-property-x_owner_foo',
                         res_body['properties'])

    def test_prop_protection_with_detail_and_unpermitted_policy(self):
        """
        As admin role, create an subject with a protected property, and verify
        permitted role 'fake_role' can *not* read that protected property via
        /subjects/detail
        """
        self.set_property_protections(use_policies=True)
        self._create_admin_subject({'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            method='GET', path='/subjects/detail')
        headers = {'x-auth-token': 'user:tenant:fake_role'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        res_body = jsonutils.loads(output.body)['subjects'][0]
        self.assertNotIn('x-subject-meta-property-x_owner_foo',
                         res_body['properties'])

    def test_prop_protection_with_update_and_permitted_role(self):
        """
        As admin role, create an subject with protected property, and verify
        permitted role 'member' can update that protected property
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'x-subject-meta-property-x_owner_foo': 'baz'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('baz', res_body['properties']['x_owner_foo'])

    def test_prop_protection_with_update_and_permitted_policy(self):
        """
        As admin role, create an subject with protected property, and verify
        permitted role 'admin' can update that protected property
        """
        self.set_property_protections(use_policies=True)
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-spl_default_policy': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:admin',
                   'x-subject-meta-property-spl_default_policy': 'baz'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('baz', res_body['properties']['spl_default_policy'])

    def test_prop_protection_with_update_and_unpermitted_role(self):
        """
        As admin role, create an subject with protected property, and verify
        unpermitted role 'fake_role' can *not* update that protected property
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:fake_role',
                   'x-subject-meta-property-x_owner_foo': 'baz'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(webob.exc.HTTPForbidden.code, output.status_int)
        self.assertIn("Property '%s' is protected" %
                      "x_owner_foo", output.body.decode())

    def test_prop_protection_with_update_and_unpermitted_policy(self):
        """
        As admin role, create an subject with protected property, and verify
        unpermitted role 'fake_role' can *not* update that protected property
        """
        self.set_property_protections(use_policies=True)
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:fake_role',
                   'x-subject-meta-property-x_owner_foo': 'baz'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(webob.exc.HTTPForbidden.code, output.status_int)
        self.assertIn("Property '%s' is protected" %
                      "x_owner_foo", output.body.decode())

    def test_prop_protection_update_without_read(self):
        """
        Test protected property cannot be updated without read permission
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-spl_update_only_prop': 'foo'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:spl_role',
                   'x-subject-meta-property-spl_update_only_prop': 'bar'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(webob.exc.HTTPForbidden.code, output.status_int)
        self.assertIn("Property '%s' is protected" %
                      "spl_update_only_prop", output.body.decode())

    def test_prop_protection_update_noop(self):
        """
        Test protected property update is allowed as long as the user has read
        access and the value is unchanged
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-spl_read_prop': 'foo'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:spl_role',
                   'x-subject-meta-property-spl_read_prop': 'foo'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('foo', res_body['properties']['spl_read_prop'])
        self.assertEqual(200, output.status_int)

    def test_prop_protection_with_delete_and_permitted_role(self):
        """
        As admin role, create an subject with protected property, and verify
        permitted role 'member' can can delete that protected property
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'X-Glance-Registry-Purge-Props': 'True'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual({}, res_body['properties'])

    def test_prop_protection_with_delete_and_permitted_policy(self):
        """
        As admin role, create an subject with protected property, and verify
        permitted role 'member' can can delete that protected property
        """
        self.set_property_protections(use_policies=True)
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'X-Glance-Registry-Purge-Props': 'True'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual({}, res_body['properties'])

    def test_prop_protection_with_delete_and_unpermitted_read(self):
        """
        Test protected property cannot be deleted without read permission
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_owner_foo': 'bar'})

        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:fake_role',
                   'X-Glance-Registry-Purge-Props': 'True'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        self.assertNotIn('x-subject-meta-property-x_owner_foo', output.headers)

        another_request = unit_test_utils.get_fake_request(
            method='HEAD', path='/subjects/%s' % subject_id)
        headers = {'x-auth-token': 'user:tenant:admin'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        self.assertEqual(b'', output.body)
        self.assertEqual('bar',
                         output.headers['x-subject-meta-property-x_owner_foo'])

    def test_prop_protection_with_delete_and_unpermitted_delete(self):
        """
        Test protected property cannot be deleted without delete permission
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-spl_update_prop': 'foo'})

        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:spl_role',
                   'X-Glance-Registry-Purge-Props': 'True'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(403, output.status_int)
        self.assertIn("Property '%s' is protected" %
                      "spl_update_prop", output.body.decode())

        another_request = unit_test_utils.get_fake_request(
            method='HEAD', path='/subjects/%s' % subject_id)
        headers = {'x-auth-token': 'user:tenant:admin'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        self.assertEqual(b'', output.body)
        self.assertEqual(
            'foo', output.headers['x-subject-meta-property-spl_update_prop'])

    def test_read_protected_props_leak_with_update(self):
        """
        Verify when updating props that ones we don't have read permission for
        are not disclosed
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-spl_update_prop': '0',
             'x-subject-meta-property-foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:spl_role',
                   'x-subject-meta-property-spl_update_prop': '1',
                   'X-Glance-Registry-Purge-Props': 'False'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('1', res_body['properties']['spl_update_prop'])
        self.assertNotIn('foo', res_body['properties'])

    def test_update_protected_props_mix_no_read(self):
        """
        Create an subject with two props - one only readable by admin, and one
        readable/updatable by member.  Verify member can successfully update
        their property while the admin owned one is ignored transparently
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-admin_foo': 'bar',
             'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'x-subject-meta-property-x_owner_foo': 'baz'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('baz', res_body['properties']['x_owner_foo'])
        self.assertNotIn('admin_foo', res_body['properties'])

    def test_update_protected_props_mix_read(self):
        """
        Create an subject with two props - one readable/updatable by admin, but
        also readable by spl_role.  The other is readable/updatable by
        spl_role.  Verify spl_role can successfully update their property but
        not the admin owned one
        """
        custom_props = {
            'x-subject-meta-property-spl_read_only_prop': '1',
            'x-subject-meta-property-spl_update_prop': '2'
        }
        subject_id = self._create_admin_subject(custom_props)
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')

        # verify spl_role can update it's prop
        headers = {'x-auth-token': 'user:tenant:spl_role',
                   'x-subject-meta-property-spl_read_only_prop': '1',
                   'x-subject-meta-property-spl_update_prop': '1'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual(200, output.status_int)
        self.assertEqual('1', res_body['properties']['spl_read_only_prop'])
        self.assertEqual('1', res_body['properties']['spl_update_prop'])

        # verify spl_role can not update admin controlled prop
        headers = {'x-auth-token': 'user:tenant:spl_role',
                   'x-subject-meta-property-spl_read_only_prop': '2',
                   'x-subject-meta-property-spl_update_prop': '1'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(403, output.status_int)

    def test_delete_protected_props_mix_no_read(self):
        """
        Create an subject with two props - one only readable by admin, and one
        readable/deletable by member.  Verify member can successfully delete
        their property while the admin owned one is ignored transparently
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-admin_foo': 'bar',
                'x-subject-meta-property-x_owner_foo': 'bar'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'X-Glance-Registry-Purge-Props': 'True'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertNotIn('x_owner_foo', res_body['properties'])
        self.assertNotIn('admin_foo', res_body['properties'])

    def test_delete_protected_props_mix_read(self):
        """
        Create an subject with two props - one readable/deletable by admin, but
        also readable by spl_role.  The other is readable/deletable by
        spl_role.  Verify spl_role is forbidden to purge_props in this scenario
        without retaining the readable prop.
        """
        custom_props = {
            'x-subject-meta-property-spl_read_only_prop': '1',
            'x-subject-meta-property-spl_delete_prop': '2'
        }
        subject_id = self._create_admin_subject(custom_props)
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:spl_role',
                   'X-Glance-Registry-Purge-Props': 'True'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(403, output.status_int)

    def test_create_protected_prop_check_case_insensitive(self):
        """
        Verify that role check is case-insensitive i.e. the property
        marked with role Member is creatable by the member role
        """
        subject_id = self._create_admin_subject()
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'x-subject-meta-property-x_case_insensitive': '1'}
        for k, v in six.iteritems(headers):
                another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('1', res_body['properties']['x_case_insensitive'])

    def test_read_protected_prop_check_case_insensitive(self):
        """
        Verify that role check is case-insensitive i.e. the property
        marked with role Member is readable by the member role
        """
        custom_props = {
            'x-subject-meta-property-x_case_insensitive': '1'
        }
        subject_id = self._create_admin_subject(custom_props)
        another_request = unit_test_utils.get_fake_request(
            method='HEAD', path='/subjects/%s' % subject_id)
        headers = {'x-auth-token': 'user:tenant:member'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        self.assertEqual(b'', output.body)
        self.assertEqual(
            '1', output.headers['x-subject-meta-property-x_case_insensitive'])

    def test_update_protected_props_check_case_insensitive(self):
        """
        Verify that role check is case-insensitive i.e. the property
        marked with role Member is updatable by the member role
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_case_insensitive': '1'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'x-subject-meta-property-x_case_insensitive': '2'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('2', res_body['properties']['x_case_insensitive'])

    def test_delete_protected_props_check_case_insensitive(self):
        """
        Verify that role check is case-insensitive i.e. the property
        marked with role Member is deletable by the member role
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_case_insensitive': '1'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'X-Glance-Registry-Purge-Props': 'True'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual({}, res_body['properties'])

    def test_create_non_protected_prop(self):
        """
        Verify property marked with special char '@' is creatable by an unknown
        role
        """
        subject_id = self._create_admin_subject()
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:joe_soap',
                   'x-subject-meta-property-x_all_permitted': '1'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('1', res_body['properties']['x_all_permitted'])

    def test_read_non_protected_prop(self):
        """
        Verify property marked with special char '@' is readable by an unknown
        role
        """
        custom_props = {
            'x-subject-meta-property-x_all_permitted': '1'
        }
        subject_id = self._create_admin_subject(custom_props)
        another_request = unit_test_utils.get_fake_request(
            method='HEAD', path='/subjects/%s' % subject_id)
        headers = {'x-auth-token': 'user:tenant:joe_soap'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        self.assertEqual(b'', output.body)
        self.assertEqual(
            '1', output.headers['x-subject-meta-property-x_all_permitted'])

    def test_update_non_protected_prop(self):
        """
        Verify property marked with special char '@' is updatable by an unknown
        role
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_all_permitted': '1'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:joe_soap',
                   'x-subject-meta-property-x_all_permitted': '2'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('2', res_body['properties']['x_all_permitted'])

    def test_delete_non_protected_prop(self):
        """
        Verify property marked with special char '@' is deletable by an unknown
        role
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_all_permitted': '1'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:joe_soap',
                   'X-Glance-Registry-Purge-Props': 'True'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual({}, res_body['properties'])

    def test_create_locked_down_protected_prop(self):
        """
        Verify a property protected by special char '!' is creatable by no one
        """
        subject_id = self._create_admin_subject()
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'x-subject-meta-property-x_none_permitted': '1'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(403, output.status_int)
        # also check admin can not create
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:admin',
                   'x-subject-meta-property-x_none_permitted_admin': '1'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(403, output.status_int)

    def test_read_locked_down_protected_prop(self):
        """
        Verify a property protected by special char '!' is readable by no one
        """
        custom_props = {
            'x-subject-meta-property-x_none_read': '1'
        }
        subject_id = self._create_admin_subject(custom_props)
        another_request = unit_test_utils.get_fake_request(
            method='HEAD', path='/subjects/%s' % subject_id)
        headers = {'x-auth-token': 'user:tenant:member'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        self.assertNotIn('x_none_read', output.headers)
        # also check admin can not read
        another_request = unit_test_utils.get_fake_request(
            method='HEAD', path='/subjects/%s' % subject_id)
        headers = {'x-auth-token': 'user:tenant:admin'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(200, output.status_int)
        self.assertNotIn('x_none_read', output.headers)

    def test_update_locked_down_protected_prop(self):
        """
        Verify a property protected by special char '!' is updatable by no one
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_none_update': '1'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'x-subject-meta-property-x_none_update': '2'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(403, output.status_int)
        # also check admin can't update property
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:admin',
                   'x-subject-meta-property-x_none_update': '2'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(403, output.status_int)

    def test_delete_locked_down_protected_prop(self):
        """
        Verify a property protected by special char '!' is deletable by no one
        """
        subject_id = self._create_admin_subject(
            {'x-subject-meta-property-x_none_delete': '1'})
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:member',
                   'X-Glance-Registry-Purge-Props': 'True'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(403, output.status_int)
        # also check admin can't delete
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:admin',
                   'X-Glance-Registry-Purge-Props': 'True'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v
        output = another_request.get_response(self.api)
        self.assertEqual(403, output.status_int)


class TestAPIPropertyQuotas(base.IsolatedUnitTest):
    def setUp(self):
        """Establish a clean test environment"""
        super(TestAPIPropertyQuotas, self).setUp()
        self.mapper = routes.Mapper()
        self.api = test_utils.FakeAuthMiddleware(router.API(self.mapper))
        db_api.get_engine()
        db_models.unregister_models(db_api.get_engine())
        db_models.register_models(db_api.get_engine())

    def _create_admin_subject(self, props=None):
        if props is None:
            props = {}
        request = unit_test_utils.get_fake_request(path='/subjects')
        headers = {'x-subject-meta-disk-format': 'ami',
                   'x-subject-meta-container-format': 'ami',
                   'x-subject-meta-name': 'foo',
                   'x-subject-meta-size': '0',
                   'x-auth-token': 'user:tenant:admin'}
        headers.update(props)
        for k, v in six.iteritems(headers):
            request.headers[k] = v
        created_subject = request.get_response(self.api)
        res_body = jsonutils.loads(created_subject.body)['subject']
        subject_id = res_body['id']
        return subject_id

    def test_update_subject_with_too_many_properties(self):
        """
        Ensure that updating subject properties enforces the quota.
        """
        self.config(subject_property_quota=1)
        subject_id = self._create_admin_subject()
        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:joe_soap',
                   'x-subject-meta-property-x_all_permitted': '1',
                   'x-subject-meta-property-x_all_permitted_foo': '2'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v

        output = another_request.get_response(self.api)

        self.assertEqual(413, output.status_int)
        self.assertIn("Attempted: 2, Maximum: 1", output.text)

    def test_update_subject_with_too_many_properties_without_purge_props(self):
        """
        Ensure that updating subject properties counts existing subject properties
        when enforcing property quota.
        """
        self.config(subject_property_quota=1)
        request = unit_test_utils.get_fake_request(path='/subjects')
        headers = {'x-subject-meta-disk-format': 'ami',
                   'x-subject-meta-container-format': 'ami',
                   'x-subject-meta-name': 'foo',
                   'x-subject-meta-size': '0',
                   'x-subject-meta-property-x_all_permitted_create': '1',
                   'x-auth-token': 'user:tenant:admin'}
        for k, v in six.iteritems(headers):
            request.headers[k] = v
        created_subject = request.get_response(self.api)
        res_body = jsonutils.loads(created_subject.body)['subject']
        subject_id = res_body['id']

        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:joe_soap',
                   'x-subject-registry-purge-props': 'False',
                   'x-subject-meta-property-x_all_permitted': '1'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v

        output = another_request.get_response(self.api)

        self.assertEqual(413, output.status_int)
        self.assertIn("Attempted: 2, Maximum: 1", output.text)

    def test_update_properties_without_purge_props_overwrite_value(self):
        """
        Ensure that updating subject properties does not count against subject
        property quota.
        """
        self.config(subject_property_quota=2)
        request = unit_test_utils.get_fake_request(path='/subjects')
        headers = {'x-subject-meta-disk-format': 'ami',
                   'x-subject-meta-container-format': 'ami',
                   'x-subject-meta-name': 'foo',
                   'x-subject-meta-size': '0',
                   'x-subject-meta-property-x_all_permitted_create': '1',
                   'x-auth-token': 'user:tenant:admin'}
        for k, v in six.iteritems(headers):
            request.headers[k] = v
        created_subject = request.get_response(self.api)
        res_body = jsonutils.loads(created_subject.body)['subject']
        subject_id = res_body['id']

        another_request = unit_test_utils.get_fake_request(
            path='/subjects/%s' % subject_id, method='PUT')
        headers = {'x-auth-token': 'user:tenant:joe_soap',
                   'x-subject-registry-purge-props': 'False',
                   'x-subject-meta-property-x_all_permitted_create': '3',
                   'x-subject-meta-property-x_all_permitted': '1'}
        for k, v in six.iteritems(headers):
            another_request.headers[k] = v

        output = another_request.get_response(self.api)

        self.assertEqual(200, output.status_int)
        res_body = jsonutils.loads(output.body)['subject']
        self.assertEqual('1', res_body['properties']['x_all_permitted'])
        self.assertEqual('3', res_body['properties']['x_all_permitted_create'])
