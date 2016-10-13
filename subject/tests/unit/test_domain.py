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
import oslo_utils.importutils

import subject.async
from subject.async import taskflow_executor
from subject.common import exception
from subject.common.glare import definitions
from subject.common import timeutils
from subject import domain
from subject.glare import domain as artifacts_domain
import subject.tests.utils as test_utils


CONF = cfg.CONF


UUID1 = 'c80a1a6c-bd1f-41c5-90ee-81afedb1d58d'
TENANT1 = '6838eb7b-6ded-434a-882c-b344c77fe8df'


class TestImageFactory(test_utils.BaseTestCase):

    def setUp(self):
        super(TestImageFactory, self).setUp()
        self.subject_factory = domain.SubjectFactory()

    def test_minimal_new_subject(self):
        subject = self.subject_factory.new_subject()
        self.assertIsNotNone(subject.subject_id)
        self.assertIsNotNone(subject.created_at)
        self.assertEqual(subject.created_at, subject.updated_at)
        self.assertEqual('queued', subject.status)
        self.assertEqual('private', subject.visibility)
        self.assertIsNone(subject.owner)
        self.assertIsNone(subject.name)
        self.assertIsNone(subject.size)
        self.assertEqual(0, subject.min_disk)
        self.assertEqual(0, subject.min_ram)
        self.assertFalse(subject.protected)
        self.assertIsNone(subject.disk_format)
        self.assertIsNone(subject.container_format)
        self.assertEqual({}, subject.extra_properties)
        self.assertEqual(set([]), subject.tags)

    def test_new_subject(self):
        subject = self.subject_factory.new_subject(
            subject_id=UUID1, name='subject-1', min_disk=256,
            owner=TENANT1)
        self.assertEqual(UUID1, subject.subject_id)
        self.assertIsNotNone(subject.created_at)
        self.assertEqual(subject.created_at, subject.updated_at)
        self.assertEqual('queued', subject.status)
        self.assertEqual('private', subject.visibility)
        self.assertEqual(TENANT1, subject.owner)
        self.assertEqual('subject-1', subject.name)
        self.assertIsNone(subject.size)
        self.assertEqual(256, subject.min_disk)
        self.assertEqual(0, subject.min_ram)
        self.assertFalse(subject.protected)
        self.assertIsNone(subject.disk_format)
        self.assertIsNone(subject.container_format)
        self.assertEqual({}, subject.extra_properties)
        self.assertEqual(set([]), subject.tags)

    def test_new_subject_with_extra_properties_and_tags(self):
        extra_properties = {'foo': 'bar'}
        tags = ['one', 'two']
        subject = self.subject_factory.new_subject(
            subject_id=UUID1, name='subject-1',
            extra_properties=extra_properties, tags=tags)

        self.assertEqual(UUID1, subject.subject_id, UUID1)
        self.assertIsNotNone(subject.created_at)
        self.assertEqual(subject.created_at, subject.updated_at)
        self.assertEqual('queued', subject.status)
        self.assertEqual('private', subject.visibility)
        self.assertIsNone(subject.owner)
        self.assertEqual('subject-1', subject.name)
        self.assertIsNone(subject.size)
        self.assertEqual(0, subject.min_disk)
        self.assertEqual(0, subject.min_ram)
        self.assertFalse(subject.protected)
        self.assertIsNone(subject.disk_format)
        self.assertIsNone(subject.container_format)
        self.assertEqual({'foo': 'bar'}, subject.extra_properties)
        self.assertEqual(set(['one', 'two']), subject.tags)

    def test_new_subject_read_only_property(self):
        self.assertRaises(exception.ReadonlyProperty,
                          self.subject_factory.new_subject, subject_id=UUID1,
                          name='subject-1', size=256)

    def test_new_subject_unexpected_property(self):
        self.assertRaises(TypeError,
                          self.subject_factory.new_subject, subject_id=UUID1,
                          subject_name='name-1')

    def test_new_subject_reserved_property(self):
        extra_properties = {'deleted': True}
        self.assertRaises(exception.ReservedProperty,
                          self.subject_factory.new_subject, subject_id=UUID1,
                          extra_properties=extra_properties)

    def test_new_subject_for_is_public(self):
        extra_prop = {'is_public': True}
        new_subject = self.subject_factory.new_subject(subject_id=UUID1,
                                                   extra_properties=extra_prop)
        self.assertEqual(True, new_subject.extra_properties['is_public'])


class TestImage(test_utils.BaseTestCase):

    def setUp(self):
        super(TestImage, self).setUp()
        self.subject_factory = domain.SubjectFactory()
        self.subject = self.subject_factory.new_subject(
            container_format='bear', disk_format='rawr')

    def test_extra_properties(self):
        self.subject.extra_properties = {'foo': 'bar'}
        self.assertEqual({'foo': 'bar'}, self.subject.extra_properties)

    def test_extra_properties_assign(self):
        self.subject.extra_properties['foo'] = 'bar'
        self.assertEqual({'foo': 'bar'}, self.subject.extra_properties)

    def test_delete_extra_properties(self):
        self.subject.extra_properties = {'foo': 'bar'}
        self.assertEqual({'foo': 'bar'}, self.subject.extra_properties)
        del self.subject.extra_properties['foo']
        self.assertEqual({}, self.subject.extra_properties)

    def test_visibility_enumerated(self):
        self.subject.visibility = 'public'
        self.subject.visibility = 'private'
        self.assertRaises(ValueError, setattr,
                          self.subject, 'visibility', 'ellison')

    def test_tags_always_a_set(self):
        self.subject.tags = ['a', 'b', 'c']
        self.assertEqual(set(['a', 'b', 'c']), self.subject.tags)

    def test_delete_protected_subject(self):
        self.subject.protected = True
        self.assertRaises(exception.ProtectedImageDelete, self.subject.delete)

    def test_status_saving(self):
        self.subject.status = 'saving'
        self.assertEqual('saving', self.subject.status)

    def test_set_incorrect_status(self):
        self.subject.status = 'saving'
        self.subject.status = 'killed'
        self.assertRaises(
            exception.InvalidImageStatusTransition,
            setattr, self.subject, 'status', 'delet')

    def test_status_saving_without_disk_format(self):
        self.subject.disk_format = None
        self.assertRaises(ValueError, setattr,
                          self.subject, 'status', 'saving')

    def test_status_saving_without_container_format(self):
        self.subject.container_format = None
        self.assertRaises(ValueError, setattr,
                          self.subject, 'status', 'saving')

    def test_status_active_without_disk_format(self):
        self.subject.disk_format = None
        self.assertRaises(ValueError, setattr,
                          self.subject, 'status', 'active')

    def test_status_active_without_container_format(self):
        self.subject.container_format = None
        self.assertRaises(ValueError, setattr,
                          self.subject, 'status', 'active')

    def test_delayed_delete(self):
        self.config(delayed_delete=True)
        self.subject.status = 'active'
        self.subject.locations = [{'url': 'http://foo.bar/not.exists',
                                 'metadata': {}}]
        self.assertEqual('active', self.subject.status)
        self.subject.delete()
        self.assertEqual('pending_delete', self.subject.status)


class TestImageMember(test_utils.BaseTestCase):

    def setUp(self):
        super(TestImageMember, self).setUp()
        self.subject_member_factory = domain.ImageMemberFactory()
        self.subject_factory = domain.SubjectFactory()
        self.subject = self.subject_factory.new_subject()
        self.subject_member = self.subject_member_factory.new_subject_member(
            subject=self.subject,
            member_id=TENANT1)

    def test_status_enumerated(self):
        self.subject_member.status = 'pending'
        self.subject_member.status = 'accepted'
        self.subject_member.status = 'rejected'
        self.assertRaises(ValueError, setattr,
                          self.subject_member, 'status', 'ellison')


class TestImageMemberFactory(test_utils.BaseTestCase):

    def setUp(self):
        super(TestImageMemberFactory, self).setUp()
        self.subject_member_factory = domain.ImageMemberFactory()
        self.subject_factory = domain.SubjectFactory()

    def test_minimal_new_subject_member(self):
        member_id = 'fake-member-id'
        subject = self.subject_factory.new_subject(
            subject_id=UUID1, name='subject-1', min_disk=256,
            owner=TENANT1)
        subject_member = self.subject_member_factory.new_subject_member(subject,
                                                                  member_id)
        self.assertEqual(subject_member.subject_id, subject.subject_id)
        self.assertIsNotNone(subject_member.created_at)
        self.assertEqual(subject_member.created_at, subject_member.updated_at)
        self.assertEqual('pending', subject_member.status)
        self.assertIsNotNone(subject_member.member_id)


class TestExtraProperties(test_utils.BaseTestCase):

    def test_getitem(self):
        a_dict = {'foo': 'bar', 'snitch': 'golden'}
        extra_properties = domain.ExtraProperties(a_dict)
        self.assertEqual('bar', extra_properties['foo'])
        self.assertEqual('golden', extra_properties['snitch'])

    def test_getitem_with_no_items(self):
        extra_properties = domain.ExtraProperties()
        self.assertRaises(KeyError, extra_properties.__getitem__, 'foo')

    def test_setitem(self):
        a_dict = {'foo': 'bar', 'snitch': 'golden'}
        extra_properties = domain.ExtraProperties(a_dict)
        extra_properties['foo'] = 'baz'
        self.assertEqual('baz', extra_properties['foo'])

    def test_delitem(self):
        a_dict = {'foo': 'bar', 'snitch': 'golden'}
        extra_properties = domain.ExtraProperties(a_dict)
        del extra_properties['foo']
        self.assertRaises(KeyError, extra_properties.__getitem__, 'foo')
        self.assertEqual('golden', extra_properties['snitch'])

    def test_len_with_zero_items(self):
        extra_properties = domain.ExtraProperties()
        self.assertEqual(0, len(extra_properties))

    def test_len_with_non_zero_items(self):
        extra_properties = domain.ExtraProperties()
        extra_properties['foo'] = 'bar'
        extra_properties['snitch'] = 'golden'
        self.assertEqual(2, len(extra_properties))

    def test_eq_with_a_dict(self):
        a_dict = {'foo': 'bar', 'snitch': 'golden'}
        extra_properties = domain.ExtraProperties(a_dict)
        ref_extra_properties = {'foo': 'bar', 'snitch': 'golden'}
        self.assertEqual(ref_extra_properties, extra_properties)

    def test_eq_with_an_object_of_ExtraProperties(self):
        a_dict = {'foo': 'bar', 'snitch': 'golden'}
        extra_properties = domain.ExtraProperties(a_dict)
        ref_extra_properties = domain.ExtraProperties()
        ref_extra_properties['snitch'] = 'golden'
        ref_extra_properties['foo'] = 'bar'
        self.assertEqual(ref_extra_properties, extra_properties)

    def test_eq_with_uneqal_dict(self):
        a_dict = {'foo': 'bar', 'snitch': 'golden'}
        extra_properties = domain.ExtraProperties(a_dict)
        ref_extra_properties = {'boo': 'far', 'gnitch': 'solden'}
        self.assertNotEqual(ref_extra_properties, extra_properties)

    def test_eq_with_unequal_ExtraProperties_object(self):
        a_dict = {'foo': 'bar', 'snitch': 'golden'}
        extra_properties = domain.ExtraProperties(a_dict)
        ref_extra_properties = domain.ExtraProperties()
        ref_extra_properties['gnitch'] = 'solden'
        ref_extra_properties['boo'] = 'far'
        self.assertNotEqual(ref_extra_properties, extra_properties)

    def test_eq_with_incompatible_object(self):
        a_dict = {'foo': 'bar', 'snitch': 'golden'}
        extra_properties = domain.ExtraProperties(a_dict)
        random_list = ['foo', 'bar']
        self.assertNotEqual(random_list, extra_properties)


class TestTaskFactory(test_utils.BaseTestCase):

    def setUp(self):
        super(TestTaskFactory, self).setUp()
        self.task_factory = domain.TaskFactory()

    def test_new_task(self):
        task_type = 'import'
        owner = TENANT1
        task_input = 'input'
        task = self.task_factory.new_task(task_type, owner,
                                          task_input=task_input,
                                          result='test_result',
                                          message='test_message')
        self.assertIsNotNone(task.task_id)
        self.assertIsNotNone(task.created_at)
        self.assertEqual(task_type, task.type)
        self.assertEqual(task.created_at, task.updated_at)
        self.assertEqual('pending', task.status)
        self.assertIsNone(task.expires_at)
        self.assertEqual(owner, task.owner)
        self.assertEqual(task_input, task.task_input)
        self.assertEqual('test_message', task.message)
        self.assertEqual('test_result', task.result)

    def test_new_task_invalid_type(self):
        task_type = 'blah'
        owner = TENANT1
        self.assertRaises(
            exception.InvalidTaskType,
            self.task_factory.new_task,
            task_type,
            owner,
        )


class TestTask(test_utils.BaseTestCase):

    def setUp(self):
        super(TestTask, self).setUp()
        self.task_factory = domain.TaskFactory()
        task_type = 'import'
        owner = TENANT1
        task_ttl = CONF.task.task_time_to_live
        self.task = self.task_factory.new_task(task_type,
                                               owner,
                                               task_time_to_live=task_ttl)

    def test_task_invalid_status(self):
        task_id = str(uuid.uuid4())
        status = 'blah'
        self.assertRaises(
            exception.InvalidTaskStatus,
            domain.Task,
            task_id,
            task_type='import',
            status=status,
            owner=None,
            expires_at=None,
            created_at=timeutils.utcnow(),
            updated_at=timeutils.utcnow(),
            task_input=None,
            message=None,
            result=None
        )

    def test_validate_status_transition_from_pending(self):
        self.task.begin_processing()
        self.assertEqual('processing', self.task.status)

    def test_validate_status_transition_from_processing_to_success(self):
        self.task.begin_processing()
        self.task.succeed('')
        self.assertEqual('success', self.task.status)

    def test_validate_status_transition_from_processing_to_failure(self):
        self.task.begin_processing()
        self.task.fail('')
        self.assertEqual('failure', self.task.status)

    def test_invalid_status_transitions_from_pending(self):
        # test do not allow transition from pending to success
        self.assertRaises(
            exception.InvalidTaskStatusTransition,
            self.task.succeed,
            ''
        )

    def test_invalid_status_transitions_from_success(self):
        # test do not allow transition from success to processing
        self.task.begin_processing()
        self.task.succeed('')
        self.assertRaises(
            exception.InvalidTaskStatusTransition,
            self.task.begin_processing
        )
        # test do not allow transition from success to failure
        self.assertRaises(
            exception.InvalidTaskStatusTransition,
            self.task.fail,
            ''
        )

    def test_invalid_status_transitions_from_failure(self):
        # test do not allow transition from failure to processing
        self.task.begin_processing()
        self.task.fail('')
        self.assertRaises(
            exception.InvalidTaskStatusTransition,
            self.task.begin_processing
        )
        # test do not allow transition from failure to success
        self.assertRaises(
            exception.InvalidTaskStatusTransition,
            self.task.succeed,
            ''
        )

    def test_begin_processing(self):
        self.task.begin_processing()
        self.assertEqual('processing', self.task.status)

    @mock.patch.object(timeutils, 'utcnow')
    def test_succeed(self, mock_utcnow):
        mock_utcnow.return_value = datetime.datetime.utcnow()
        self.task.begin_processing()
        self.task.succeed('{"location": "file://home"}')
        self.assertEqual('success', self.task.status)
        self.assertEqual('{"location": "file://home"}', self.task.result)
        self.assertEqual(u'', self.task.message)
        expected = (timeutils.utcnow() +
                    datetime.timedelta(hours=CONF.task.task_time_to_live))
        self.assertEqual(
            expected,
            self.task.expires_at
        )

    @mock.patch.object(timeutils, 'utcnow')
    def test_fail(self, mock_utcnow):
        mock_utcnow.return_value = datetime.datetime.utcnow()
        self.task.begin_processing()
        self.task.fail('{"message": "connection failed"}')
        self.assertEqual('failure', self.task.status)
        self.assertEqual('{"message": "connection failed"}', self.task.message)
        self.assertIsNone(self.task.result)
        expected = (timeutils.utcnow() +
                    datetime.timedelta(hours=CONF.task.task_time_to_live))
        self.assertEqual(
            expected,
            self.task.expires_at
        )

    @mock.patch.object(subject.async.TaskExecutor, 'begin_processing')
    def test_run(self, mock_begin_processing):
        executor = subject.async.TaskExecutor(context=mock.ANY,
                                              task_repo=mock.ANY,
                                              subject_repo=mock.ANY,
                                              subject_factory=mock.ANY)
        self.task.run(executor)

        mock_begin_processing.assert_called_once_with(self.task.task_id)


class TestTaskStub(test_utils.BaseTestCase):
    def setUp(self):
        super(TestTaskStub, self).setUp()
        self.task_id = str(uuid.uuid4())
        self.task_type = 'import'
        self.owner = TENANT1
        self.task_ttl = CONF.task.task_time_to_live

    def test_task_stub_init(self):
        self.task_factory = domain.TaskFactory()
        task = domain.TaskStub(
            self.task_id,
            self.task_type,
            'status',
            self.owner,
            'expires_at',
            'created_at',
            'updated_at'
        )
        self.assertEqual(self.task_id, task.task_id)
        self.assertEqual(self.task_type, task.type)
        self.assertEqual(self.owner, task.owner)
        self.assertEqual('status', task.status)
        self.assertEqual('expires_at', task.expires_at)
        self.assertEqual('created_at', task.created_at)
        self.assertEqual('updated_at', task.updated_at)

    def test_task_stub_get_status(self):
        status = 'pending'
        task = domain.TaskStub(
            self.task_id,
            self.task_type,
            status,
            self.owner,
            'expires_at',
            'created_at',
            'updated_at'
        )
        self.assertEqual(status, task.status)


class TestTaskExecutorFactory(test_utils.BaseTestCase):
    def setUp(self):
        super(TestTaskExecutorFactory, self).setUp()
        self.task_repo = mock.Mock()
        self.subject_repo = mock.Mock()
        self.subject_factory = mock.Mock()

    def test_init(self):
        task_executor_factory = domain.TaskExecutorFactory(self.task_repo,
                                                           self.subject_repo,
                                                           self.subject_factory)
        self.assertEqual(self.task_repo, task_executor_factory.task_repo)

    def test_new_task_executor(self):
        task_executor_factory = domain.TaskExecutorFactory(self.task_repo,
                                                           self.subject_repo,
                                                           self.subject_factory)
        context = mock.Mock()
        with mock.patch.object(oslo_utils.importutils,
                               'import_class') as mock_import_class:
            mock_executor = mock.Mock()
            mock_import_class.return_value = mock_executor
            task_executor_factory.new_task_executor(context)

        mock_executor.assert_called_once_with(context,
                                              self.task_repo,
                                              self.subject_repo,
                                              self.subject_factory)

    def test_new_task_executor_error(self):
        task_executor_factory = domain.TaskExecutorFactory(self.task_repo,
                                                           self.subject_repo,
                                                           self.subject_factory)
        context = mock.Mock()
        with mock.patch.object(oslo_utils.importutils,
                               'import_class') as mock_import_class:
            mock_import_class.side_effect = ImportError

            self.assertRaises(ImportError,
                              task_executor_factory.new_task_executor,
                              context)

    def test_new_task_eventlet_backwards_compatibility(self):
        context = mock.MagicMock()

        self.config(task_executor='eventlet', group='task')

        task_executor_factory = domain.TaskExecutorFactory(self.task_repo,
                                                           self.subject_repo,
                                                           self.subject_factory)

        # NOTE(flaper87): "eventlet" executor. short name to avoid > 79.
        te_evnt = task_executor_factory.new_task_executor(context)
        self.assertIsInstance(te_evnt, taskflow_executor.TaskExecutor)


class TestArtifact(definitions.ArtifactType):
    prop1 = definitions.Dict()
    prop2 = definitions.Integer(min_value=10)


class TestArtifactTypeFactory(test_utils.BaseTestCase):

    def setUp(self):
        super(TestArtifactTypeFactory, self).setUp()
        context = mock.Mock(owner='me')
        self.factory = artifacts_domain.ArtifactFactory(context, TestArtifact)

    def test_new_artifact_min_params(self):
        artifact = self.factory.new_artifact("foo", "1.0.0-alpha")
        self.assertEqual('creating', artifact.state)
        self.assertEqual('me', artifact.owner)
        self.assertIsNotNone(artifact.id)
