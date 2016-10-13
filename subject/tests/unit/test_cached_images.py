# Copyright (C) 2013 Yahoo! Inc.
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

from subject.api import cached_subjects
from subject.api import policy
from subject.common import exception
from subject import subject_cache


class FakePolicyEnforcer(policy.Enforcer):
    def __init__(self):
        self.default_rule = ''
        self.policy_path = ''
        self.policy_file_mtime = None
        self.policy_file_contents = None

    def enforce(self, context, action, target):
        return 'pass'

    def check(rule, target, creds, exc=None, *args, **kwargs):
        return 'pass'

    def _check(self, context, rule, target, *args, **kwargs):
        return 'pass'


class FakeCache(subject_cache.ImageCache):
    def __init__(self):
        self.init_driver()
        self.deleted_subjects = []

    def init_driver(self):
        pass

    def get_cached_subjects(self):
        return {'id': 'test'}

    def delete_cached_subject(self, subject_id):
        self.deleted_subjects.append(subject_id)

    def delete_all_cached_subjects(self):
        self.delete_cached_subject(self.get_cached_subjects().get('id'))
        return 1

    def get_queued_subjects(self):
        return {'test': 'passed'}

    def queue_subject(self, subject_id):
        return 'pass'

    def delete_queued_subject(self, subject_id):
        self.deleted_subjects.append(subject_id)

    def delete_all_queued_subjects(self):
        self.delete_queued_subject('deleted_img')
        return 1


class FakeController(cached_subjects.Controller):
    def __init__(self):
        self.cache = FakeCache()
        self.policy = FakePolicyEnforcer()


class TestController(testtools.TestCase):
    def test_initialization_without_conf(self):
        self.assertRaises(exception.BadDriverConfiguration,
                          cached_subjects.Controller)


class TestCachedImages(testtools.TestCase):
    def setUp(self):
        super(TestCachedImages, self).setUp()
        test_controller = FakeController()
        self.controller = test_controller

    def test_get_cached_subjects(self):
        req = webob.Request.blank('')
        req.context = 'test'
        result = self.controller.get_cached_subjects(req)
        self.assertEqual({'cached_subjects': {'id': 'test'}}, result)

    def test_delete_cached_subject(self):
        req = webob.Request.blank('')
        req.context = 'test'
        self.controller.delete_cached_subject(req, subject_id='test')
        self.assertEqual(['test'], self.controller.cache.deleted_subjects)

    def test_delete_cached_subjects(self):
        req = webob.Request.blank('')
        req.context = 'test'
        self.assertEqual({'num_deleted': 1},
                         self.controller.delete_cached_subjects(req))
        self.assertEqual(['test'], self.controller.cache.deleted_subjects)

    def test_policy_enforce_forbidden(self):
        def fake_enforce(context, action, target):
            raise exception.Forbidden()

        self.controller.policy.enforce = fake_enforce
        req = webob.Request.blank('')
        req.context = 'test'
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.get_cached_subjects, req)

    def test_get_queued_subjects(self):
        req = webob.Request.blank('')
        req.context = 'test'
        result = self.controller.get_queued_subjects(req)
        self.assertEqual({'queued_subjects': {'test': 'passed'}}, result)

    def test_queue_subject(self):
        req = webob.Request.blank('')
        req.context = 'test'
        self.controller.queue_subject(req, subject_id='test1')

    def test_delete_queued_subject(self):
        req = webob.Request.blank('')
        req.context = 'test'
        self.controller.delete_queued_subject(req, 'deleted_img')
        self.assertEqual(['deleted_img'],
                         self.controller.cache.deleted_subjects)

    def test_delete_queued_subjects(self):
        req = webob.Request.blank('')
        req.context = 'test'
        self.assertEqual({'num_deleted': 1},
                         self.controller.delete_queued_subjects(req))
        self.assertEqual(['deleted_img'],
                         self.controller.cache.deleted_subjects)
