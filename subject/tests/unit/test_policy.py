# Copyright 2012 OpenStack Foundation
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

import os.path

import mock
import oslo_config.cfg

import subject.api.policy
from subject.common import exception
import subject.context
from subject.tests.unit import base
import subject.tests.unit.utils as unit_test_utils
from subject.tests import utils as test_utils

UUID1 = 'c80a1a6c-bd1f-41c5-90ee-81afedb1d58d'


class SubjectRepoStub(object):
    def get(self, *args, **kwargs):
        return 'subject_from_get'

    def save(self, *args, **kwargs):
        return 'subject_from_save'

    def add(self, *args, **kwargs):
        return 'subject_from_add'

    def list(self, *args, **kwargs):
        return ['subject_from_list_0', 'subject_from_list_1']


class SubjectStub(object):
    def __init__(self, subject_id=None, visibility='private',
                 container_format='bear', disk_format='raw',
                 status='active', extra_properties=None):

        if extra_properties is None:
            extra_properties = {}

        self.subject_id = subject_id
        self.visibility = visibility
        self.container_format = container_format
        self.disk_format = disk_format
        self.status = status
        self.extra_properties = extra_properties

    def delete(self):
        self.status = 'deleted'


class SubjectFactoryStub(object):
    def new_subject(self, subject_id=None, name=None, visibility='private',
                  min_disk=0, min_ram=0, protected=False, owner=None,
                  disk_format=None, container_format=None,
                  extra_properties=None, tags=None, **other_args):
        self.visibility = visibility
        return 'new_subject'


class MemberRepoStub(object):
    subject = None

    def add(self, subject_member):
        subject_member.output = 'member_repo_add'

    def get(self, *args, **kwargs):
        return 'member_repo_get'

    def save(self, subject_member, from_state=None):
        subject_member.output = 'member_repo_save'

    def list(self, *args, **kwargs):
        return 'member_repo_list'

    def remove(self, subject_member):
        subject_member.output = 'member_repo_remove'


class SubjectMembershipStub(object):
    def __init__(self, output=None):
        self.output = output


class TaskRepoStub(object):
    def get(self, *args, **kwargs):
        return 'task_from_get'

    def add(self, *args, **kwargs):
        return 'task_from_add'

    def list(self, *args, **kwargs):
        return ['task_from_list_0', 'task_from_list_1']


class TaskStub(object):
    def __init__(self, task_id):
        self.task_id = task_id
        self.status = 'pending'

    def run(self, executor):
        self.status = 'processing'


class TaskFactoryStub(object):
    def new_task(self, *args):
        return 'new_task'


class TestPolicyEnforcer(base.IsolatedUnitTest):
    def test_policy_file_default_rules_default_location(self):
        enforcer = subject.api.policy.Enforcer()

        context = subject.context.RequestContext(roles=[])
        enforcer.enforce(context, 'get_subject', {})

    def test_policy_file_custom_rules_default_location(self):
        rules = {"get_subject": '!'}
        self.set_policy_rules(rules)

        enforcer = subject.api.policy.Enforcer()

        context = subject.context.RequestContext(roles=[])
        self.assertRaises(exception.Forbidden,
                          enforcer.enforce, context, 'get_subject', {})

    def test_policy_file_custom_location(self):
        self.config(policy_file=os.path.join(self.test_dir, 'gobble.gobble'),
                    group='oslo_policy')

        rules = {"get_subject": '!'}
        self.set_policy_rules(rules)

        enforcer = subject.api.policy.Enforcer()

        context = subject.context.RequestContext(roles=[])
        self.assertRaises(exception.Forbidden,
                          enforcer.enforce, context, 'get_subject', {})

    def test_policy_file_check(self):
        self.config(policy_file=os.path.join(self.test_dir, 'gobble.gobble'),
                    group='oslo_policy')

        rules = {"get_subject": '!'}
        self.set_policy_rules(rules)

        enforcer = subject.api.policy.Enforcer()

        context = subject.context.RequestContext(roles=[])
        self.assertEqual(False, enforcer.check(context, 'get_subject', {}))

    def test_policy_file_get_subject_default_everybody(self):
        rules = {"default": ''}
        self.set_policy_rules(rules)

        enforcer = subject.api.policy.Enforcer()

        context = subject.context.RequestContext(roles=[])
        self.assertEqual(True, enforcer.check(context, 'get_subject', {}))

    def test_policy_file_get_subject_default_nobody(self):
        rules = {"default": '!'}
        self.set_policy_rules(rules)

        enforcer = subject.api.policy.Enforcer()

        context = subject.context.RequestContext(roles=[])
        self.assertRaises(exception.Forbidden,
                          enforcer.enforce, context, 'get_subject', {})


class TestPolicyEnforcerNoFile(base.IsolatedUnitTest):
    def test_policy_file_specified_but_not_found(self):
        """Missing defined policy file should result in a default ruleset"""
        self.config(policy_file='gobble.gobble', group='oslo_policy')
        enforcer = subject.api.policy.Enforcer()

        context = subject.context.RequestContext(roles=[])
        enforcer.enforce(context, 'get_subject', {})
        self.assertRaises(exception.Forbidden,
                          enforcer.enforce, context, 'manage_subject_cache', {})

        admin_context = subject.context.RequestContext(roles=['admin'])
        enforcer.enforce(admin_context, 'manage_subject_cache', {})

    def test_policy_file_default_not_found(self):
        """Missing default policy file should result in a default ruleset"""
        def fake_find_file(self, name):
            return None

        self.stubs.Set(oslo_config.cfg.ConfigOpts, 'find_file',
                       fake_find_file)

        enforcer = subject.api.policy.Enforcer()

        context = subject.context.RequestContext(roles=[])
        enforcer.enforce(context, 'get_subject', {})
        self.assertRaises(exception.Forbidden,
                          enforcer.enforce, context, 'manage_subject_cache', {})

        admin_context = subject.context.RequestContext(roles=['admin'])
        enforcer.enforce(admin_context, 'manage_subject_cache', {})


class TestSubjectPolicy(test_utils.BaseTestCase):
    def setUp(self):
        self.subject_stub = SubjectStub(UUID1)
        self.subject_repo_stub = SubjectRepoStub()
        self.subject_factory_stub = SubjectFactoryStub()
        self.policy = mock.Mock()
        self.policy.enforce = mock.Mock()
        super(TestSubjectPolicy, self).setUp()

    def test_publicize_subject_not_allowed(self):
        self.policy.enforce.side_effect = exception.Forbidden
        subject = subject.api.policy.SubjectProxy(self.subject_stub, {}, self.policy)
        self.assertRaises(exception.Forbidden,
                          setattr, subject, 'visibility', 'public')
        self.assertEqual('private', subject.visibility)
        self.policy.enforce.assert_called_once_with({}, "publicize_subject",
                                                    subject.target)

    def test_publicize_subject_allowed(self):
        subject = subject.api.policy.SubjectProxy(self.subject_stub, {}, self.policy)
        subject.visibility = 'public'
        self.assertEqual('public', subject.visibility)
        self.policy.enforce.assert_called_once_with({}, "publicize_subject",
                                                    subject.target)

    def test_delete_subject_not_allowed(self):
        self.policy.enforce.side_effect = exception.Forbidden
        subject = subject.api.policy.SubjectProxy(self.subject_stub, {}, self.policy)
        self.assertRaises(exception.Forbidden, subject.delete)
        self.assertEqual('active', subject.status)
        self.policy.enforce.assert_called_once_with({}, "delete_subject",
                                                    subject.target)

    def test_delete_subject_allowed(self):
        subject = subject.api.policy.SubjectProxy(self.subject_stub, {}, self.policy)
        subject.delete()
        self.assertEqual('deleted', subject.status)
        self.policy.enforce.assert_called_once_with({}, "delete_subject",
                                                    subject.target)

    def test_get_subject_not_allowed(self):
        self.policy.enforce.side_effect = exception.Forbidden
        subject_target = mock.Mock()
        with mock.patch.object(subject.api.policy, 'SubjectTarget') as target:
            target.return_value = subject_target
            subject_repo = subject.api.policy.SubjectRepoProxy(self.subject_repo_stub,
                                                             {}, self.policy)
            self.assertRaises(exception.Forbidden, subject_repo.get, UUID1)
        self.policy.enforce.assert_called_once_with({}, "get_subject",
                                                    subject_target)

    def test_get_subject_allowed(self):
        subject_target = mock.Mock()
        with mock.patch.object(subject.api.policy, 'SubjectTarget') as target:
            target.return_value = subject_target
            subject_repo = subject.api.policy.SubjectRepoProxy(self.subject_repo_stub,
                                                             {}, self.policy)
            output = subject_repo.get(UUID1)
        self.assertIsInstance(output, subject.api.policy.SubjectProxy)
        self.assertEqual('subject_from_get', output.subject)
        self.policy.enforce.assert_called_once_with({}, "get_subject",
                                                    subject_target)

    def test_get_subjects_not_allowed(self):
        self.policy.enforce.side_effect = exception.Forbidden
        subject_repo = subject.api.policy.SubjectRepoProxy(self.subject_repo_stub,
                                                         {}, self.policy)
        self.assertRaises(exception.Forbidden, subject_repo.list)
        self.policy.enforce.assert_called_once_with({}, "get_subjects", {})

    def test_get_subjects_allowed(self):
        subject_repo = subject.api.policy.SubjectRepoProxy(self.subject_repo_stub,
                                                         {}, self.policy)
        subjects = subject_repo.list()
        for i, subject in enumerate(subjects):
            self.assertIsInstance(subject, subject.api.policy.SubjectProxy)
            self.assertEqual('subject_from_list_%d' % i, subject.subject)
            self.policy.enforce.assert_called_once_with({}, "get_subjects", {})

    def test_modify_subject_not_allowed(self):
        self.policy.enforce.side_effect = exception.Forbidden
        subject_repo = subject.api.policy.SubjectRepoProxy(self.subject_repo_stub,
                                                         {}, self.policy)
        subject = subject.api.policy.SubjectProxy(self.subject_stub, {}, self.policy)
        self.assertRaises(exception.Forbidden, subject_repo.save, subject)
        self.policy.enforce.assert_called_once_with({}, "modify_subject",
                                                    subject.target)

    def test_modify_subject_allowed(self):
        subject_repo = subject.api.policy.SubjectRepoProxy(self.subject_repo_stub,
                                                         {}, self.policy)
        subject = subject.api.policy.SubjectProxy(self.subject_stub, {}, self.policy)
        subject_repo.save(subject)
        self.policy.enforce.assert_called_once_with({}, "modify_subject",
                                                    subject.target)

    def test_add_subject_not_allowed(self):
        self.policy.enforce.side_effect = exception.Forbidden
        subject_repo = subject.api.policy.SubjectRepoProxy(self.subject_repo_stub,
                                                         {}, self.policy)
        subject = subject.api.policy.SubjectProxy(self.subject_stub, {}, self.policy)
        self.assertRaises(exception.Forbidden, subject_repo.add, subject)
        self.policy.enforce.assert_called_once_with({}, "add_subject",
                                                    subject.target)

    def test_add_subject_allowed(self):
        subject_repo = subject.api.policy.SubjectRepoProxy(self.subject_repo_stub,
                                                         {}, self.policy)
        subject = subject.api.policy.SubjectProxy(self.subject_stub, {}, self.policy)
        subject_repo.add(subject)
        self.policy.enforce.assert_called_once_with({}, "add_subject",
                                                    subject.target)

    def test_new_subject_visibility(self):
        self.policy.enforce.side_effect = exception.Forbidden
        subject_factory = subject.api.policy.SubjectFactoryProxy(
            self.subject_factory_stub, {}, self.policy)
        self.assertRaises(exception.Forbidden, subject_factory.new_subject,
                          visibility='public')
        self.policy.enforce.assert_called_once_with({}, "publicize_subject", {})

    def test_new_subject_visibility_public_allowed(self):
        subject_factory = subject.api.policy.SubjectFactoryProxy(
            self.subject_factory_stub, {}, self.policy)
        subject_factory.new_subject(visibility='public')
        self.policy.enforce.assert_called_once_with({}, "publicize_subject", {})

    def test_subject_get_data_policy_enforced_with_target(self):
        extra_properties = {
            'test_key': 'test_4321'
        }
        subject_stub = SubjectStub(UUID1, extra_properties=extra_properties)
        with mock.patch('subject.api.policy.SubjectTarget'):
            subject = subject.api.policy.SubjectProxy(subject_stub, {}, self.policy)
        target = subject.target
        self.policy.enforce.side_effect = exception.Forbidden

        self.assertRaises(exception.Forbidden, subject.get_data)
        self.policy.enforce.assert_called_once_with({}, "download_subject",
                                                    target)

    def test_subject_set_data(self):
        self.policy.enforce.side_effect = exception.Forbidden
        subject = subject.api.policy.SubjectProxy(self.subject_stub, {}, self.policy)
        self.assertRaises(exception.Forbidden, subject.set_data)
        self.policy.enforce.assert_called_once_with({}, "upload_subject",
                                                    subject.target)


class TestMemberPolicy(test_utils.BaseTestCase):
    def setUp(self):
        self.policy = mock.Mock()
        self.policy.enforce = mock.Mock()
        self.subject_stub = SubjectStub(UUID1)
        subject = subject.api.policy.SubjectProxy(self.subject_stub, {}, self.policy)
        self.member_repo = subject.api.policy.SubjectMemberRepoProxy(
            MemberRepoStub(), subject, {}, self.policy)
        self.target = self.member_repo.target
        super(TestMemberPolicy, self).setUp()

    def test_add_member_not_allowed(self):
        self.policy.enforce.side_effect = exception.Forbidden
        self.assertRaises(exception.Forbidden, self.member_repo.add, '')
        self.policy.enforce.assert_called_once_with({}, "add_member",
                                                    self.target)

    def test_add_member_allowed(self):
        subject_member = SubjectMembershipStub()
        self.member_repo.add(subject_member)
        self.assertEqual('member_repo_add', subject_member.output)
        self.policy.enforce.assert_called_once_with({}, "add_member",
                                                    self.target)

    def test_get_member_not_allowed(self):
        self.policy.enforce.side_effect = exception.Forbidden
        self.assertRaises(exception.Forbidden, self.member_repo.get, '')
        self.policy.enforce.assert_called_once_with({}, "get_member",
                                                    self.target)

    def test_get_member_allowed(self):
        output = self.member_repo.get('')
        self.assertEqual('member_repo_get', output)
        self.policy.enforce.assert_called_once_with({}, "get_member",
                                                    self.target)

    def test_modify_member_not_allowed(self):
        self.policy.enforce.side_effect = exception.Forbidden
        self.assertRaises(exception.Forbidden, self.member_repo.save, '')
        self.policy.enforce.assert_called_once_with({}, "modify_member",
                                                    self.target)

    def test_modify_member_allowed(self):
        subject_member = SubjectMembershipStub()
        self.member_repo.save(subject_member)
        self.assertEqual('member_repo_save', subject_member.output)
        self.policy.enforce.assert_called_once_with({}, "modify_member",
                                                    self.target)

    def test_get_members_not_allowed(self):
        self.policy.enforce.side_effect = exception.Forbidden
        self.assertRaises(exception.Forbidden, self.member_repo.list, '')
        self.policy.enforce.assert_called_once_with({}, "get_members",
                                                    self.target)

    def test_get_members_allowed(self):
        output = self.member_repo.list('')
        self.assertEqual('member_repo_list', output)
        self.policy.enforce.assert_called_once_with({}, "get_members",
                                                    self.target)

    def test_delete_member_not_allowed(self):
        self.policy.enforce.side_effect = exception.Forbidden
        self.assertRaises(exception.Forbidden, self.member_repo.remove, '')
        self.policy.enforce.assert_called_once_with({}, "delete_member",
                                                    self.target)

    def test_delete_member_allowed(self):
        subject_member = SubjectMembershipStub()
        self.member_repo.remove(subject_member)
        self.assertEqual('member_repo_remove', subject_member.output)
        self.policy.enforce.assert_called_once_with({}, "delete_member",
                                                    self.target)


class TestTaskPolicy(test_utils.BaseTestCase):
    def setUp(self):
        self.task_stub = TaskStub(UUID1)
        self.task_repo_stub = TaskRepoStub()
        self.task_factory_stub = TaskFactoryStub()
        self.policy = unit_test_utils.FakePolicyEnforcer()
        super(TestTaskPolicy, self).setUp()

    def test_get_task_not_allowed(self):
        rules = {"get_task": False}
        self.policy.set_rules(rules)
        task_repo = subject.api.policy.TaskRepoProxy(
            self.task_repo_stub,
            {},
            self.policy
        )
        self.assertRaises(exception.Forbidden,
                          task_repo.get,
                          UUID1)

    def test_get_task_allowed(self):
        rules = {"get_task": True}
        self.policy.set_rules(rules)
        task_repo = subject.api.policy.TaskRepoProxy(
            self.task_repo_stub,
            {},
            self.policy
        )
        task = task_repo.get(UUID1)
        self.assertIsInstance(task, subject.api.policy.TaskProxy)
        self.assertEqual('task_from_get', task.task)

    def test_get_tasks_not_allowed(self):
        rules = {"get_tasks": False}
        self.policy.set_rules(rules)
        task_repo = subject.api.policy.TaskStubRepoProxy(
            self.task_repo_stub,
            {},
            self.policy
        )
        self.assertRaises(exception.Forbidden, task_repo.list)

    def test_get_tasks_allowed(self):
        rules = {"get_task": True}
        self.policy.set_rules(rules)
        task_repo = subject.api.policy.TaskStubRepoProxy(
            self.task_repo_stub,
            {},
            self.policy
        )
        tasks = task_repo.list()
        for i, task in enumerate(tasks):
            self.assertIsInstance(task, subject.api.policy.TaskStubProxy)
            self.assertEqual('task_from_list_%d' % i, task.task_stub)

    def test_add_task_not_allowed(self):
        rules = {"add_task": False}
        self.policy.set_rules(rules)
        task_repo = subject.api.policy.TaskRepoProxy(
            self.task_repo_stub,
            {},
            self.policy
        )
        task = subject.api.policy.TaskProxy(self.task_stub, {}, self.policy)
        self.assertRaises(exception.Forbidden, task_repo.add, task)

    def test_add_task_allowed(self):
        rules = {"add_task": True}
        self.policy.set_rules(rules)
        task_repo = subject.api.policy.TaskRepoProxy(
            self.task_repo_stub,
            {},
            self.policy
        )
        task = subject.api.policy.TaskProxy(self.task_stub, {}, self.policy)
        task_repo.add(task)


class TestContextPolicyEnforcer(base.IsolatedUnitTest):
    def _do_test_policy_influence_context_admin(self,
                                                policy_admin_role,
                                                context_role,
                                                context_is_admin,
                                                admin_expected):
        self.config(policy_file=os.path.join(self.test_dir, 'gobble.gobble'),
                    group='oslo_policy')

        rules = {'context_is_admin': 'role:%s' % policy_admin_role}
        self.set_policy_rules(rules)

        enforcer = subject.api.policy.Enforcer()

        context = subject.context.RequestContext(roles=[context_role],
                                                 is_admin=context_is_admin,
                                                 policy_enforcer=enforcer)
        self.assertEqual(admin_expected, context.is_admin)

    def test_context_admin_policy_admin(self):
        self._do_test_policy_influence_context_admin('test_admin',
                                                     'test_admin',
                                                     True,
                                                     True)

    def test_context_nonadmin_policy_admin(self):
        self._do_test_policy_influence_context_admin('test_admin',
                                                     'test_admin',
                                                     False,
                                                     True)

    def test_context_admin_policy_nonadmin(self):
        self._do_test_policy_influence_context_admin('test_admin',
                                                     'demo',
                                                     True,
                                                     True)

    def test_context_nonadmin_policy_nonadmin(self):
        self._do_test_policy_influence_context_admin('test_admin',
                                                     'demo',
                                                     False,
                                                     False)
