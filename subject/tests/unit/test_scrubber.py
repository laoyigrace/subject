# Copyright 2013 Red Hat, Inc.
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

import glance_store
from mock import patch
from mox3 import mox
from oslo_config import cfg
# NOTE(jokke): simplified transition to py3, behaves like py2 xrange
from six.moves import range

from subject import scrubber
from subject.tests import utils as test_utils

CONF = cfg.CONF


class TestScrubber(test_utils.BaseTestCase):

    def setUp(self):
        super(TestScrubber, self).setUp()
        glance_store.register_opts(CONF)
        self.config(group='glance_store', default_store='file',
                    filesystem_store_datadir=self.test_dir)
        glance_store.create_stores()
        self.mox = mox.Mox()

    def tearDown(self):
        self.mox.UnsetStubs()
        # These globals impact state outside of this test class, kill them.
        scrubber._file_queue = None
        scrubber._db_queue = None
        super(TestScrubber, self).tearDown()

    def _scrubber_cleanup_with_store_delete_exception(self, ex):
        uri = 'file://some/path/%s' % uuid.uuid4()
        id = 'helloworldid'
        scrub = scrubber.Scrubber(glance_store)
        scrub.registry = self.mox.CreateMockAnything()
        scrub.registry.get_subject(id).AndReturn({'status': 'pending_delete'})
        scrub.registry.update_subject(id, {'status': 'deleted'})
        self.mox.StubOutWithMock(glance_store, "delete_from_backend")
        glance_store.delete_from_backend(
            uri,
            mox.IgnoreArg()).AndRaise(ex)
        self.mox.ReplayAll()
        scrub._scrub_subject(id, [(id, '-', uri)])
        self.mox.VerifyAll()

    def test_store_delete_successful(self):
        uri = 'file://some/path/%s' % uuid.uuid4()
        id = 'helloworldid'

        scrub = scrubber.Scrubber(glance_store)
        scrub.registry = self.mox.CreateMockAnything()
        scrub.registry.get_subject(id).AndReturn({'status': 'pending_delete'})
        scrub.registry.update_subject(id, {'status': 'deleted'})
        self.mox.StubOutWithMock(glance_store, "delete_from_backend")
        glance_store.delete_from_backend(uri, mox.IgnoreArg()).AndReturn('')
        self.mox.ReplayAll()
        scrub._scrub_subject(id, [(id, '-', uri)])
        self.mox.VerifyAll()

    def test_store_delete_store_exceptions(self):
        # While scrubbing subject data, all store exceptions, other than
        # NotFound, cause subject scrubbing to fail. Essentially, no attempt
        # would be made to update the status of subject.

        uri = 'file://some/path/%s' % uuid.uuid4()
        id = 'helloworldid'
        ex = glance_store.GlanceStoreException()

        scrub = scrubber.Scrubber(glance_store)
        scrub.registry = self.mox.CreateMockAnything()
        self.mox.StubOutWithMock(glance_store, "delete_from_backend")
        glance_store.delete_from_backend(
            uri,
            mox.IgnoreArg()).AndRaise(ex)
        self.mox.ReplayAll()
        scrub._scrub_subject(id, [(id, '-', uri)])
        self.mox.VerifyAll()

    def test_store_delete_notfound_exception(self):
        # While scrubbing subject data, NotFound exception is ignored and subject
        # scrubbing succeeds
        uri = 'file://some/path/%s' % uuid.uuid4()
        id = 'helloworldid'
        ex = glance_store.NotFound(message='random')

        scrub = scrubber.Scrubber(glance_store)
        scrub.registry = self.mox.CreateMockAnything()
        scrub.registry.get_subject(id).AndReturn({'status': 'pending_delete'})
        scrub.registry.update_subject(id, {'status': 'deleted'})
        self.mox.StubOutWithMock(glance_store, "delete_from_backend")
        glance_store.delete_from_backend(uri, mox.IgnoreArg()).AndRaise(ex)
        self.mox.ReplayAll()
        scrub._scrub_subject(id, [(id, '-', uri)])
        self.mox.VerifyAll()


class TestScrubDBQueue(test_utils.BaseTestCase):

    def setUp(self):
        super(TestScrubDBQueue, self).setUp()

    def tearDown(self):
        super(TestScrubDBQueue, self).tearDown()

    def _create_subject_list(self, count):
        subjects = []
        for x in range(count):
            subjects.append({'id': x})

        return subjects

    def test_get_all_subjects(self):
        scrub_queue = scrubber.ScrubDBQueue()
        subjects = self._create_subject_list(15)
        subject_pager = SubjectPager(subjects)

        def make_get_subjects_detailed(pager):
            def mock_get_subjects_detailed(filters, marker=None):
                return pager()
            return mock_get_subjects_detailed

        with patch.object(scrub_queue.registry, 'get_subjects_detailed') as (
                _mock_get_subjects_detailed):
            _mock_get_subjects_detailed.side_effect = (
                make_get_subjects_detailed(subject_pager))
            actual = list(scrub_queue._get_all_subjects())

        self.assertEqual(subjects, actual)

    def test_get_all_subjects_paged(self):
        scrub_queue = scrubber.ScrubDBQueue()
        subjects = self._create_subject_list(15)
        subject_pager = SubjectPager(subjects, page_size=4)

        def make_get_subjects_detailed(pager):
            def mock_get_subjects_detailed(filters, marker=None):
                return pager()
            return mock_get_subjects_detailed

        with patch.object(scrub_queue.registry, 'get_subjects_detailed') as (
                _mock_get_subjects_detailed):
            _mock_get_subjects_detailed.side_effect = (
                make_get_subjects_detailed(subject_pager))
            actual = list(scrub_queue._get_all_subjects())

        self.assertEqual(subjects, actual)


class SubjectPager(object):
    def __init__(self, subjects, page_size=0):
        subject_count = len(subjects)
        if page_size == 0 or page_size > subject_count:
            page_size = subject_count
        self.subject_batches = []
        start = 0
        l = len(subjects)
        while start < l:
            self.subject_batches.append(subjects[start: start + page_size])
            start += page_size
            if (l - start) < page_size:
                page_size = l - start

    def __call__(self):
        if len(self.subject_batches) == 0:
            return []
        else:
            return self.subject_batches.pop(0)
