# Copyright 2013 OpenStack Foundation
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

from subject.api import policy
from subject.api import property_protections
from subject.common import exception
from subject.common import property_utils
import subject.domain
from subject.tests import utils


TENANT1 = '6838eb7b-6ded-434a-882c-b344c77fe8df'
TENANT2 = '2c014f32-55eb-467d-8fcb-4bd706012f81'


class TestProtectedSubjectRepoProxy(utils.BaseTestCase):

    class SubjectRepoStub(object):
        def __init__(self, fixtures):
            self.fixtures = fixtures

        def get(self, subject_id):
            for f in self.fixtures:
                if f.subject_id == subject_id:
                    return f
            else:
                raise ValueError(subject_id)

        def list(self, *args, **kwargs):
            return self.fixtures

        def add(self, subject):
            self.fixtures.append(subject)

    def setUp(self):
        super(TestProtectedSubjectRepoProxy, self).setUp()
        self.set_property_protections()
        self.policy = policy.Enforcer()
        self.property_rules = property_utils.PropertyRules(self.policy)
        self.subject_factory = subject.domain.SubjectFactory()
        extra_props = {'spl_create_prop': 'c',
                       'spl_read_prop': 'r',
                       'spl_update_prop': 'u',
                       'spl_delete_prop': 'd',
                       'forbidden': 'prop'}
        extra_props_2 = {'spl_read_prop': 'r', 'forbidden': 'prop'}
        self.fixtures = [
            self.subject_factory.new_subject(subject_id='1', owner=TENANT1,
                                           extra_properties=extra_props),
            self.subject_factory.new_subject(owner=TENANT2, visibility='public'),
            self.subject_factory.new_subject(subject_id='3', owner=TENANT1,
                                           extra_properties=extra_props_2),
        ]
        self.context = subject.context.RequestContext(roles=['spl_role'])
        subject_repo = self.SubjectRepoStub(self.fixtures)
        self.subject_repo = property_protections.ProtectedSubjectRepoProxy(
            subject_repo, self.context, self.property_rules)

    def test_get_subject(self):
        subject_id = '1'
        result_subject = self.subject_repo.get(subject_id)
        result_extra_props = result_subject.extra_properties
        self.assertEqual('c', result_extra_props['spl_create_prop'])
        self.assertEqual('r', result_extra_props['spl_read_prop'])
        self.assertEqual('u', result_extra_props['spl_update_prop'])
        self.assertEqual('d', result_extra_props['spl_delete_prop'])
        self.assertNotIn('forbidden', result_extra_props.keys())

    def test_list_subject(self):
        result_subjects = self.subject_repo.list()
        self.assertEqual(3, len(result_subjects))
        result_extra_props = result_subjects[0].extra_properties
        self.assertEqual('c', result_extra_props['spl_create_prop'])
        self.assertEqual('r', result_extra_props['spl_read_prop'])
        self.assertEqual('u', result_extra_props['spl_update_prop'])
        self.assertEqual('d', result_extra_props['spl_delete_prop'])
        self.assertNotIn('forbidden', result_extra_props.keys())

        result_extra_props = result_subjects[1].extra_properties
        self.assertEqual({}, result_extra_props)

        result_extra_props = result_subjects[2].extra_properties
        self.assertEqual('r', result_extra_props['spl_read_prop'])
        self.assertNotIn('forbidden', result_extra_props.keys())


class TestProtectedSubjectProxy(utils.BaseTestCase):

    def setUp(self):
        super(TestProtectedSubjectProxy, self).setUp()
        self.set_property_protections()
        self.policy = policy.Enforcer()
        self.property_rules = property_utils.PropertyRules(self.policy)

    class SubjectStub(object):
        def __init__(self, extra_prop):
            self.extra_properties = extra_prop

    def test_read_subject_with_extra_prop(self):
        context = subject.context.RequestContext(roles=['spl_role'])
        extra_prop = {'spl_read_prop': 'read', 'spl_fake_prop': 'prop'}
        subject = self.SubjectStub(extra_prop)
        result_subject = property_protections.ProtectedSubjectProxy(
            subject, context, self.property_rules)
        result_extra_props = result_subject.extra_properties
        self.assertEqual('read', result_extra_props['spl_read_prop'])
        self.assertNotIn('spl_fake_prop', result_extra_props.keys())


class TestExtraPropertiesProxy(utils.BaseTestCase):

    def setUp(self):
        super(TestExtraPropertiesProxy, self).setUp()
        self.set_property_protections()
        self.policy = policy.Enforcer()
        self.property_rules = property_utils.PropertyRules(self.policy)

    def test_read_extra_property_as_admin_role(self):
        extra_properties = {'foo': 'bar', 'ping': 'pong'}
        context = subject.context.RequestContext(roles=['admin'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        test_result = extra_prop_proxy['foo']
        self.assertEqual('bar', test_result)

    def test_read_extra_property_as_unpermitted_role(self):
        extra_properties = {'foo': 'bar', 'ping': 'pong'}
        context = subject.context.RequestContext(roles=['unpermitted_role'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        self.assertRaises(KeyError, extra_prop_proxy.__getitem__, 'foo')

    def test_update_extra_property_as_permitted_role_after_read(self):
        extra_properties = {'foo': 'bar', 'ping': 'pong'}
        context = subject.context.RequestContext(roles=['admin'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        extra_prop_proxy['foo'] = 'par'
        self.assertEqual('par', extra_prop_proxy['foo'])

    def test_update_extra_property_as_unpermitted_role_after_read(self):
        extra_properties = {'spl_read_prop': 'bar'}
        context = subject.context.RequestContext(roles=['spl_role'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        self.assertRaises(exception.ReservedProperty,
                          extra_prop_proxy.__setitem__,
                          'spl_read_prop', 'par')

    def test_update_reserved_extra_property(self):
        extra_properties = {'spl_create_prop': 'bar'}
        context = subject.context.RequestContext(roles=['spl_role'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        self.assertRaises(exception.ReservedProperty,
                          extra_prop_proxy.__setitem__, 'spl_create_prop',
                          'par')

    def test_update_empty_extra_property(self):
        extra_properties = {'foo': ''}
        context = subject.context.RequestContext(roles=['admin'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        extra_prop_proxy['foo'] = 'bar'
        self.assertEqual('bar', extra_prop_proxy['foo'])

    def test_create_extra_property_admin(self):
        extra_properties = {}
        context = subject.context.RequestContext(roles=['admin'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        extra_prop_proxy['boo'] = 'doo'
        self.assertEqual('doo', extra_prop_proxy['boo'])

    def test_create_reserved_extra_property(self):
        extra_properties = {}
        context = subject.context.RequestContext(roles=['spl_role'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        self.assertRaises(exception.ReservedProperty,
                          extra_prop_proxy.__setitem__, 'boo',
                          'doo')

    def test_delete_extra_property_as_admin_role(self):
        extra_properties = {'foo': 'bar'}
        context = subject.context.RequestContext(roles=['admin'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        del extra_prop_proxy['foo']
        self.assertRaises(KeyError, extra_prop_proxy.__getitem__, 'foo')

    def test_delete_nonexistant_extra_property_as_admin_role(self):
        extra_properties = {}
        context = subject.context.RequestContext(roles=['admin'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        self.assertRaises(KeyError, extra_prop_proxy.__delitem__, 'foo')

    def test_delete_reserved_extra_property(self):
        extra_properties = {'spl_read_prop': 'r'}
        context = subject.context.RequestContext(roles=['spl_role'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        # Ensure property has been created and can be read
        self.assertEqual('r', extra_prop_proxy['spl_read_prop'])
        self.assertRaises(exception.ReservedProperty,
                          extra_prop_proxy.__delitem__, 'spl_read_prop')

    def test_delete_nonexistant_extra_property(self):
        extra_properties = {}
        roles = ['spl_role']
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            roles, extra_properties, self.property_rules)
        self.assertRaises(KeyError,
                          extra_prop_proxy.__delitem__, 'spl_read_prop')

    def test_delete_empty_extra_property(self):
        extra_properties = {'foo': ''}
        context = subject.context.RequestContext(roles=['admin'])
        extra_prop_proxy = property_protections.ExtraPropertiesProxy(
            context, extra_properties, self.property_rules)
        del extra_prop_proxy['foo']
        self.assertNotIn('foo', extra_prop_proxy)


class TestProtectedSubjectFactoryProxy(utils.BaseTestCase):
    def setUp(self):
        super(TestProtectedSubjectFactoryProxy, self).setUp()
        self.set_property_protections()
        self.policy = policy.Enforcer()
        self.property_rules = property_utils.PropertyRules(self.policy)
        self.factory = subject.domain.SubjectFactory()

    def test_create_subject_no_extra_prop(self):
        self.context = subject.context.RequestContext(tenant=TENANT1,
                                                      roles=['spl_role'])
        self.subject_factory = property_protections.ProtectedSubjectFactoryProxy(
            self.factory, self.context,
            self.property_rules)
        extra_props = {}
        subject = self.subject_factory.new_subject(extra_properties=extra_props)
        expected_extra_props = {}
        self.assertEqual(expected_extra_props, subject.extra_properties)

    def test_create_subject_extra_prop(self):
        self.context = subject.context.RequestContext(tenant=TENANT1,
                                                      roles=['spl_role'])
        self.subject_factory = property_protections.ProtectedSubjectFactoryProxy(
            self.factory, self.context,
            self.property_rules)
        extra_props = {'spl_create_prop': 'c'}
        subject = self.subject_factory.new_subject(extra_properties=extra_props)
        expected_extra_props = {'spl_create_prop': 'c'}
        self.assertEqual(expected_extra_props, subject.extra_properties)

    def test_create_subject_extra_prop_reserved_property(self):
        self.context = subject.context.RequestContext(tenant=TENANT1,
                                                      roles=['spl_role'])
        self.subject_factory = property_protections.ProtectedSubjectFactoryProxy(
            self.factory, self.context,
            self.property_rules)
        extra_props = {'foo': 'bar', 'spl_create_prop': 'c'}
        # no reg ex for property 'foo' is mentioned for spl_role in config
        self.assertRaises(exception.ReservedProperty,
                          self.subject_factory.new_subject,
                          extra_properties=extra_props)

    def test_create_subject_extra_prop_admin(self):
        self.context = subject.context.RequestContext(tenant=TENANT1,
                                                      roles=['admin'])
        self.subject_factory = property_protections.ProtectedSubjectFactoryProxy(
            self.factory, self.context,
            self.property_rules)
        extra_props = {'foo': 'bar', 'spl_create_prop': 'c'}
        subject = self.subject_factory.new_subject(extra_properties=extra_props)
        expected_extra_props = {'foo': 'bar', 'spl_create_prop': 'c'}
        self.assertEqual(expected_extra_props, subject.extra_properties)

    def test_create_subject_extra_prop_invalid_role(self):
        self.context = subject.context.RequestContext(tenant=TENANT1,
                                                      roles=['imaginary-role'])
        self.subject_factory = property_protections.ProtectedSubjectFactoryProxy(
            self.factory, self.context,
            self.property_rules)
        extra_props = {'foo': 'bar', 'spl_create_prop': 'c'}
        self.assertRaises(exception.ReservedProperty,
                          self.subject_factory.new_subject,
                          extra_properties=extra_props)
