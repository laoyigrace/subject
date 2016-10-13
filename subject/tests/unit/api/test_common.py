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

import testtools
import webob

import subject.api.common
from subject.common import config
from subject.common import exception
from subject.tests import utils as test_utils


class SimpleIterator(object):
    def __init__(self, file_object, chunk_size):
        self.file_object = file_object
        self.chunk_size = chunk_size

    def __iter__(self):
        def read_chunk():
            return self.fobj.read(self.chunk_size)

        chunk = read_chunk()
        while chunk:
            yield chunk
            chunk = read_chunk()
        else:
            raise StopIteration()


class TestSizeCheckedIter(testtools.TestCase):
    def _get_subject_metadata(self):
        return {'id': 'e31cb99c-fe89-49fb-9cc5-f5104fffa636'}

    def _get_webob_response(self):
        request = webob.Request.blank('/')
        response = webob.Response()
        response.request = request
        return response

    def test_uniform_chunk_size(self):
        resp = self._get_webob_response()
        meta = self._get_subject_metadata()
        checked_subject = subject.api.common.size_checked_iter(
            resp, meta, 4, ['AB', 'CD'], None)

        self.assertEqual('AB', next(checked_subject))
        self.assertEqual('CD', next(checked_subject))
        self.assertRaises(StopIteration, next, checked_subject)

    def test_small_last_chunk(self):
        resp = self._get_webob_response()
        meta = self._get_subject_metadata()
        checked_subject = subject.api.common.size_checked_iter(
            resp, meta, 3, ['AB', 'C'], None)

        self.assertEqual('AB', next(checked_subject))
        self.assertEqual('C', next(checked_subject))
        self.assertRaises(StopIteration, next, checked_subject)

    def test_variable_chunk_size(self):
        resp = self._get_webob_response()
        meta = self._get_subject_metadata()
        checked_subject = subject.api.common.size_checked_iter(
            resp, meta, 6, ['AB', '', 'CDE', 'F'], None)

        self.assertEqual('AB', next(checked_subject))
        self.assertEqual('', next(checked_subject))
        self.assertEqual('CDE', next(checked_subject))
        self.assertEqual('F', next(checked_subject))
        self.assertRaises(StopIteration, next, checked_subject)

    def test_too_many_chunks(self):
        """An subject should streamed regardless of expected_size"""
        resp = self._get_webob_response()
        meta = self._get_subject_metadata()
        checked_subject = subject.api.common.size_checked_iter(
            resp, meta, 4, ['AB', 'CD', 'EF'], None)

        self.assertEqual('AB', next(checked_subject))
        self.assertEqual('CD', next(checked_subject))
        self.assertEqual('EF', next(checked_subject))
        self.assertRaises(exception.GlanceException, next, checked_subject)

    def test_too_few_chunks(self):
        resp = self._get_webob_response()
        meta = self._get_subject_metadata()
        checked_subject = subject.api.common.size_checked_iter(resp, meta, 6,
                                                             ['AB', 'CD'],
                                                             None)

        self.assertEqual('AB', next(checked_subject))
        self.assertEqual('CD', next(checked_subject))
        self.assertRaises(exception.GlanceException, next, checked_subject)

    def test_too_much_data(self):
        resp = self._get_webob_response()
        meta = self._get_subject_metadata()
        checked_subject = subject.api.common.size_checked_iter(resp, meta, 3,
                                                             ['AB', 'CD'],
                                                             None)

        self.assertEqual('AB', next(checked_subject))
        self.assertEqual('CD', next(checked_subject))
        self.assertRaises(exception.GlanceException, next, checked_subject)

    def test_too_little_data(self):
        resp = self._get_webob_response()
        meta = self._get_subject_metadata()
        checked_subject = subject.api.common.size_checked_iter(resp, meta, 6,
                                                             ['AB', 'CD', 'E'],
                                                             None)

        self.assertEqual('AB', next(checked_subject))
        self.assertEqual('CD', next(checked_subject))
        self.assertEqual('E', next(checked_subject))
        self.assertRaises(exception.GlanceException, next, checked_subject)


class TestMalformedRequest(test_utils.BaseTestCase):
    def setUp(self):
        """Establish a clean test environment"""
        super(TestMalformedRequest, self).setUp()
        self.config(flavor='',
                    group='paste_deploy',
                    config_file='etc/subject-api-paste.ini')
        self.api = config.load_paste_app('subject-api')

    def test_redirect_incomplete_url(self):
        """Test Glance redirects /v# to /v#/ with correct Location header"""
        req = webob.Request.blank('/v1.1')
        res = req.get_response(self.api)
        self.assertEqual(webob.exc.HTTPFound.code, res.status_int)
        self.assertEqual('http://localhost/v1/', res.location)
