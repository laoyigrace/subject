# Copyright (c) 2011 OpenStack Foundation
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

"""Policy Engine For Glance"""

import copy

from oslo_config import cfg
from oslo_log import log as logging
from oslo_policy import policy

from subject.common import exception
import subject.domain.proxy
from subject.i18n import _


LOG = logging.getLogger(__name__)
CONF = cfg.CONF

DEFAULT_RULES = policy.Rules.from_dict({
    'context_is_admin': 'role:admin',
    'default': '@',
    'manage_subject_cache': 'role:admin',
})


class Enforcer(policy.Enforcer):
    """Responsible for loading and enforcing rules"""

    def __init__(self):
        if CONF.find_file(CONF.oslo_policy.policy_file):
            kwargs = dict(rules=None, use_conf=True)
        else:
            kwargs = dict(rules=DEFAULT_RULES, use_conf=False)
        super(Enforcer, self).__init__(CONF, overwrite=False, **kwargs)

    def add_rules(self, rules):
        """Add new rules to the Rules object"""
        self.set_rules(rules, overwrite=False, use_conf=self.use_conf)

    def enforce(self, context, action, target):
        """Verifies that the action is valid on the target in this context.

           :param context: Glance request context
           :param action: String representing the action to be checked
           :param target: Dictionary representing the object of the action.
           :raises: `subject.common.exception.Forbidden`
           :returns: A non-False value if access is allowed.
        """
        return super(Enforcer, self).enforce(action, target,
                                             context.to_policy_values(),
                                             do_raise=True,
                                             exc=exception.Forbidden,
                                             action=action)

    def check(self, context, action, target):
        """Verifies that the action is valid on the target in this context.

           :param context: Glance request context
           :param action: String representing the action to be checked
           :param target: Dictionary representing the object of the action.
           :returns: A non-False value if access is allowed.
        """
        return super(Enforcer, self).enforce(action,
                                             target,
                                             context.to_policy_values())

    def check_is_admin(self, context):
        """Check if the given context is associated with an admin role,
           as defined via the 'context_is_admin' RBAC rule.

           :param context: Glance request context
           :returns: A non-False value if context role is admin.
        """
        return self.check(context, 'context_is_admin', context.to_dict())


class SubjectRepoProxy(subject.domain.proxy.Repo):

    def __init__(self, subject_repo, context, policy):
        self.context = context
        self.policy = policy
        self.subject_repo = subject_repo
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(SubjectRepoProxy, self).__init__(subject_repo,
                                               item_proxy_class=SubjectProxy,
                                               item_proxy_kwargs=proxy_kwargs)

    def get(self, subject_id):
        try:
            subject = super(SubjectRepoProxy, self).get(subject_id)
        except exception.NotFound:
            self.policy.enforce(self.context, 'get_subject', {})
            raise
        else:
            self.policy.enforce(self.context, 'get_subject', SubjectTarget(subject))
        return subject

    def list(self, *args, **kwargs):
        self.policy.enforce(self.context, 'get_subjects', {})
        return super(SubjectRepoProxy, self).list(*args, **kwargs)

    def save(self, subject, from_state=None):
        self.policy.enforce(self.context, 'modify_subject', subject.target)
        return super(SubjectRepoProxy, self).save(subject, from_state=from_state)

    def add(self, subject):
        self.policy.enforce(self.context, 'add_subject', subject.target)
        return super(SubjectRepoProxy, self).add(subject)


class SubjectProxy(subject.domain.proxy.Subject):

    def __init__(self, subject, context, policy):
        self.subject = subject
        self.target = SubjectTarget(subject)
        self.context = context
        self.policy = policy
        super(SubjectProxy, self).__init__(subject)

    @property
    def visibility(self):
        return self.subject.visibility

    @visibility.setter
    def visibility(self, value):
        if value == 'public':
            self.policy.enforce(self.context, 'publicize_subject', self.target)
        self.subject.visibility = value

    @property
    def locations(self):
        return SubjectLocationsProxy(self.subject.locations,
                                   self.context, self.policy)

    @locations.setter
    def locations(self, value):
        if not isinstance(value, (list, SubjectLocationsProxy)):
            raise exception.Invalid(_('Invalid locations: %s') % value)
        self.policy.enforce(self.context, 'set_subject_location', self.target)
        new_locations = list(value)
        if (set([loc['url'] for loc in self.subject.locations]) -
                set([loc['url'] for loc in new_locations])):
            self.policy.enforce(self.context, 'delete_subject_location',
                                self.target)
        self.subject.locations = new_locations

    def delete(self):
        self.policy.enforce(self.context, 'delete_subject', self.target)
        return self.subject.delete()

    def deactivate(self):
        LOG.debug('Attempting deactivate')
        target = SubjectTarget(self.subject)
        self.policy.enforce(self.context, 'deactivate', target=target)
        LOG.debug('Deactivate allowed, continue')
        self.subject.deactivate()

    def reactivate(self):
        LOG.debug('Attempting reactivate')
        target = SubjectTarget(self.subject)
        self.policy.enforce(self.context, 'reactivate', target=target)
        LOG.debug('Reactivate allowed, continue')
        self.subject.reactivate()

    def get_data(self, *args, **kwargs):
        self.policy.enforce(self.context, 'download_subject', self.target)
        return self.subject.get_data(*args, **kwargs)

    def set_data(self, *args, **kwargs):
        self.policy.enforce(self.context, 'upload_subject', self.target)
        return self.subject.set_data(*args, **kwargs)


class SubjectMemberProxy(subject.domain.proxy.SubjectMember):

    def __init__(self, subject_member, context, policy):
        super(SubjectMemberProxy, self).__init__(subject_member)
        self.subject_member = subject_member
        self.context = context
        self.policy = policy


class SubjectFactoryProxy(subject.domain.proxy.SubjectFactory):

    def __init__(self, subject_factory, context, policy):
        self.subject_factory = subject_factory
        self.context = context
        self.policy = policy
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(SubjectFactoryProxy, self).__init__(subject_factory,
                                                  proxy_class=SubjectProxy,
                                                  proxy_kwargs=proxy_kwargs)

    def new_subject(self, **kwargs):
        if kwargs.get('visibility') == 'public':
            self.policy.enforce(self.context, 'publicize_subject', {})
        return super(SubjectFactoryProxy, self).new_subject(**kwargs)


class SubjectMemberFactoryProxy(subject.domain.proxy.SubjectMembershipFactory):

    def __init__(self, member_factory, context, policy):
        super(SubjectMemberFactoryProxy, self).__init__(
            member_factory,
            proxy_class=SubjectMemberProxy,
            proxy_kwargs={'context': context, 'policy': policy})


class SubjectMemberRepoProxy(subject.domain.proxy.Repo):

    def __init__(self, member_repo, subject, context, policy):
        self.member_repo = member_repo
        self.subject = subject
        self.target = SubjectTarget(subject)
        self.context = context
        self.policy = policy

    def add(self, member):
        self.policy.enforce(self.context, 'add_member', self.target)
        self.member_repo.add(member)

    def get(self, member_id):
        self.policy.enforce(self.context, 'get_member', self.target)
        return self.member_repo.get(member_id)

    def save(self, member, from_state=None):
        self.policy.enforce(self.context, 'modify_member', self.target)
        self.member_repo.save(member, from_state=from_state)

    def list(self, *args, **kwargs):
        self.policy.enforce(self.context, 'get_members', self.target)
        return self.member_repo.list(*args, **kwargs)

    def remove(self, member):
        self.policy.enforce(self.context, 'delete_member', self.target)
        self.member_repo.remove(member)


class SubjectLocationsProxy(object):

    __hash__ = None

    def __init__(self, locations, context, policy):
        self.locations = locations
        self.context = context
        self.policy = policy

    def __copy__(self):
        return type(self)(self.locations, self.context, self.policy)

    def __deepcopy__(self, memo):
        # NOTE(zhiyan): Only copy location entries, others can be reused.
        return type(self)(copy.deepcopy(self.locations, memo),
                          self.context, self.policy)

    def _get_checker(action, func_name):
        def _checker(self, *args, **kwargs):
            self.policy.enforce(self.context, action, {})
            method = getattr(self.locations, func_name)
            return method(*args, **kwargs)
        return _checker

    count = _get_checker('get_subject_location', 'count')
    index = _get_checker('get_subject_location', 'index')
    __getitem__ = _get_checker('get_subject_location', '__getitem__')
    __contains__ = _get_checker('get_subject_location', '__contains__')
    __len__ = _get_checker('get_subject_location', '__len__')
    __cast = _get_checker('get_subject_location', '__cast')
    __cmp__ = _get_checker('get_subject_location', '__cmp__')
    __iter__ = _get_checker('get_subject_location', '__iter__')

    append = _get_checker('set_subject_location', 'append')
    extend = _get_checker('set_subject_location', 'extend')
    insert = _get_checker('set_subject_location', 'insert')
    reverse = _get_checker('set_subject_location', 'reverse')
    __iadd__ = _get_checker('set_subject_location', '__iadd__')
    __setitem__ = _get_checker('set_subject_location', '__setitem__')

    pop = _get_checker('delete_subject_location', 'pop')
    remove = _get_checker('delete_subject_location', 'remove')
    __delitem__ = _get_checker('delete_subject_location', '__delitem__')
    __delslice__ = _get_checker('delete_subject_location', '__delslice__')

    del _get_checker


class TaskProxy(subject.domain.proxy.Task):

    def __init__(self, task, context, policy):
        self.task = task
        self.context = context
        self.policy = policy
        super(TaskProxy, self).__init__(task)


class TaskStubProxy(subject.domain.proxy.TaskStub):

    def __init__(self, task_stub, context, policy):
        self.task_stub = task_stub
        self.context = context
        self.policy = policy
        super(TaskStubProxy, self).__init__(task_stub)


class TaskRepoProxy(subject.domain.proxy.TaskRepo):

    def __init__(self, task_repo, context, task_policy):
        self.context = context
        self.policy = task_policy
        self.task_repo = task_repo
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(TaskRepoProxy,
              self).__init__(task_repo,
                             task_proxy_class=TaskProxy,
                             task_proxy_kwargs=proxy_kwargs)

    def get(self, task_id):
        self.policy.enforce(self.context, 'get_task', {})
        return super(TaskRepoProxy, self).get(task_id)

    def add(self, task):
        self.policy.enforce(self.context, 'add_task', {})
        super(TaskRepoProxy, self).add(task)

    def save(self, task):
        self.policy.enforce(self.context, 'modify_task', {})
        super(TaskRepoProxy, self).save(task)


class TaskStubRepoProxy(subject.domain.proxy.TaskStubRepo):

    def __init__(self, task_stub_repo, context, task_policy):
        self.context = context
        self.policy = task_policy
        self.task_stub_repo = task_stub_repo
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(TaskStubRepoProxy,
              self).__init__(task_stub_repo,
                             task_stub_proxy_class=TaskStubProxy,
                             task_stub_proxy_kwargs=proxy_kwargs)

    def list(self, *args, **kwargs):
        self.policy.enforce(self.context, 'get_tasks', {})
        return super(TaskStubRepoProxy, self).list(*args, **kwargs)


class TaskFactoryProxy(subject.domain.proxy.TaskFactory):

    def __init__(self, task_factory, context, policy):
        self.task_factory = task_factory
        self.context = context
        self.policy = policy
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(TaskFactoryProxy, self).__init__(
            task_factory,
            task_proxy_class=TaskProxy,
            task_proxy_kwargs=proxy_kwargs)


class SubjectTarget(object):
    SENTINEL = object()

    def __init__(self, target):
        """Initialize the object

        :param target: Object being targeted
        """
        self.target = target

    def __getitem__(self, key):
        """Return the value of 'key' from the target.

        If the target has the attribute 'key', return it.

        :param key: value to retrieve
        """
        key = self.key_transforms(key)

        value = getattr(self.target, key, self.SENTINEL)
        if value is self.SENTINEL:
            extra_properties = getattr(self.target, 'extra_properties', None)
            if extra_properties is not None:
                value = extra_properties[key]
            else:
                value = None
        return value

    def key_transforms(self, key):
        if key == 'id':
            key = 'subject_id'

        return key


# Metadef Namespace classes
class MetadefNamespaceProxy(subject.domain.proxy.MetadefNamespace):

    def __init__(self, namespace, context, policy):
        self.namespace_input = namespace
        self.context = context
        self.policy = policy
        super(MetadefNamespaceProxy, self).__init__(namespace)


class MetadefNamespaceRepoProxy(subject.domain.proxy.MetadefNamespaceRepo):

    def __init__(self, namespace_repo, context, namespace_policy):
        self.context = context
        self.policy = namespace_policy
        self.namespace_repo = namespace_repo
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(MetadefNamespaceRepoProxy,
              self).__init__(namespace_repo,
                             namespace_proxy_class=MetadefNamespaceProxy,
                             namespace_proxy_kwargs=proxy_kwargs)

    def get(self, namespace):
        self.policy.enforce(self.context, 'get_metadef_namespace', {})
        return super(MetadefNamespaceRepoProxy, self).get(namespace)

    def list(self, *args, **kwargs):
        self.policy.enforce(self.context, 'get_metadef_namespaces', {})
        return super(MetadefNamespaceRepoProxy, self).list(*args, **kwargs)

    def save(self, namespace):
        self.policy.enforce(self.context, 'modify_metadef_namespace', {})
        return super(MetadefNamespaceRepoProxy, self).save(namespace)

    def add(self, namespace):
        self.policy.enforce(self.context, 'add_metadef_namespace', {})
        return super(MetadefNamespaceRepoProxy, self).add(namespace)


class MetadefNamespaceFactoryProxy(
        subject.domain.proxy.MetadefNamespaceFactory):

    def __init__(self, meta_namespace_factory, context, policy):
        self.meta_namespace_factory = meta_namespace_factory
        self.context = context
        self.policy = policy
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(MetadefNamespaceFactoryProxy, self).__init__(
            meta_namespace_factory,
            meta_namespace_proxy_class=MetadefNamespaceProxy,
            meta_namespace_proxy_kwargs=proxy_kwargs)


# Metadef Object classes
class MetadefObjectProxy(subject.domain.proxy.MetadefObject):

    def __init__(self, meta_object, context, policy):
        self.meta_object = meta_object
        self.context = context
        self.policy = policy
        super(MetadefObjectProxy, self).__init__(meta_object)


class MetadefObjectRepoProxy(subject.domain.proxy.MetadefObjectRepo):

    def __init__(self, object_repo, context, object_policy):
        self.context = context
        self.policy = object_policy
        self.object_repo = object_repo
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(MetadefObjectRepoProxy,
              self).__init__(object_repo,
                             object_proxy_class=MetadefObjectProxy,
                             object_proxy_kwargs=proxy_kwargs)

    def get(self, namespace, object_name):
        self.policy.enforce(self.context, 'get_metadef_object', {})
        return super(MetadefObjectRepoProxy, self).get(namespace, object_name)

    def list(self, *args, **kwargs):
        self.policy.enforce(self.context, 'get_metadef_objects', {})
        return super(MetadefObjectRepoProxy, self).list(*args, **kwargs)

    def save(self, meta_object):
        self.policy.enforce(self.context, 'modify_metadef_object', {})
        return super(MetadefObjectRepoProxy, self).save(meta_object)

    def add(self, meta_object):
        self.policy.enforce(self.context, 'add_metadef_object', {})
        return super(MetadefObjectRepoProxy, self).add(meta_object)


class MetadefObjectFactoryProxy(subject.domain.proxy.MetadefObjectFactory):

    def __init__(self, meta_object_factory, context, policy):
        self.meta_object_factory = meta_object_factory
        self.context = context
        self.policy = policy
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(MetadefObjectFactoryProxy, self).__init__(
            meta_object_factory,
            meta_object_proxy_class=MetadefObjectProxy,
            meta_object_proxy_kwargs=proxy_kwargs)


# Metadef ResourceType classes
class MetadefResourceTypeProxy(subject.domain.proxy.MetadefResourceType):

    def __init__(self, meta_resource_type, context, policy):
        self.meta_resource_type = meta_resource_type
        self.context = context
        self.policy = policy
        super(MetadefResourceTypeProxy, self).__init__(meta_resource_type)


class MetadefResourceTypeRepoProxy(
        subject.domain.proxy.MetadefResourceTypeRepo):

    def __init__(self, resource_type_repo, context, resource_type_policy):
        self.context = context
        self.policy = resource_type_policy
        self.resource_type_repo = resource_type_repo
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(MetadefResourceTypeRepoProxy, self).__init__(
            resource_type_repo,
            resource_type_proxy_class=MetadefResourceTypeProxy,
            resource_type_proxy_kwargs=proxy_kwargs)

    def list(self, *args, **kwargs):
        self.policy.enforce(self.context, 'list_metadef_resource_types', {})
        return super(MetadefResourceTypeRepoProxy, self).list(*args, **kwargs)

    def get(self, *args, **kwargs):
        self.policy.enforce(self.context, 'get_metadef_resource_type', {})
        return super(MetadefResourceTypeRepoProxy, self).get(*args, **kwargs)

    def add(self, resource_type):
        self.policy.enforce(self.context,
                            'add_metadef_resource_type_association', {})
        return super(MetadefResourceTypeRepoProxy, self).add(resource_type)


class MetadefResourceTypeFactoryProxy(
        subject.domain.proxy.MetadefResourceTypeFactory):

    def __init__(self, resource_type_factory, context, policy):
        self.resource_type_factory = resource_type_factory
        self.context = context
        self.policy = policy
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(MetadefResourceTypeFactoryProxy, self).__init__(
            resource_type_factory,
            resource_type_proxy_class=MetadefResourceTypeProxy,
            resource_type_proxy_kwargs=proxy_kwargs)


# Metadef namespace properties classes
class MetadefPropertyProxy(subject.domain.proxy.MetadefProperty):

    def __init__(self, namespace_property, context, policy):
        self.namespace_property = namespace_property
        self.context = context
        self.policy = policy
        super(MetadefPropertyProxy, self).__init__(namespace_property)


class MetadefPropertyRepoProxy(subject.domain.proxy.MetadefPropertyRepo):

    def __init__(self, property_repo, context, object_policy):
        self.context = context
        self.policy = object_policy
        self.property_repo = property_repo
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(MetadefPropertyRepoProxy, self).__init__(
            property_repo,
            property_proxy_class=MetadefPropertyProxy,
            property_proxy_kwargs=proxy_kwargs)

    def get(self, namespace, property_name):
        self.policy.enforce(self.context, 'get_metadef_property', {})
        return super(MetadefPropertyRepoProxy, self).get(namespace,
                                                         property_name)

    def list(self, *args, **kwargs):
        self.policy.enforce(self.context, 'get_metadef_properties', {})
        return super(MetadefPropertyRepoProxy, self).list(
            *args, **kwargs)

    def save(self, namespace_property):
        self.policy.enforce(self.context, 'modify_metadef_property', {})
        return super(MetadefPropertyRepoProxy, self).save(
            namespace_property)

    def add(self, namespace_property):
        self.policy.enforce(self.context, 'add_metadef_property', {})
        return super(MetadefPropertyRepoProxy, self).add(
            namespace_property)


class MetadefPropertyFactoryProxy(subject.domain.proxy.MetadefPropertyFactory):

    def __init__(self, namespace_property_factory, context, policy):
        self.namespace_property_factory = namespace_property_factory
        self.context = context
        self.policy = policy
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(MetadefPropertyFactoryProxy, self).__init__(
            namespace_property_factory,
            property_proxy_class=MetadefPropertyProxy,
            property_proxy_kwargs=proxy_kwargs)


# Metadef Tag classes
class MetadefTagProxy(subject.domain.proxy.MetadefTag):

    def __init__(self, meta_tag, context, policy):
        self.context = context
        self.policy = policy
        super(MetadefTagProxy, self).__init__(meta_tag)


class MetadefTagRepoProxy(subject.domain.proxy.MetadefTagRepo):

    def __init__(self, tag_repo, context, tag_policy):
        self.context = context
        self.policy = tag_policy
        self.tag_repo = tag_repo
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(MetadefTagRepoProxy,
              self).__init__(tag_repo,
                             tag_proxy_class=MetadefTagProxy,
                             tag_proxy_kwargs=proxy_kwargs)

    def get(self, namespace, tag_name):
        self.policy.enforce(self.context, 'get_metadef_tag', {})
        return super(MetadefTagRepoProxy, self).get(namespace, tag_name)

    def list(self, *args, **kwargs):
        self.policy.enforce(self.context, 'get_metadef_tags', {})
        return super(MetadefTagRepoProxy, self).list(*args, **kwargs)

    def save(self, meta_tag):
        self.policy.enforce(self.context, 'modify_metadef_tag', {})
        return super(MetadefTagRepoProxy, self).save(meta_tag)

    def add(self, meta_tag):
        self.policy.enforce(self.context, 'add_metadef_tag', {})
        return super(MetadefTagRepoProxy, self).add(meta_tag)

    def add_tags(self, meta_tags):
        self.policy.enforce(self.context, 'add_metadef_tags', {})
        return super(MetadefTagRepoProxy, self).add_tags(meta_tags)


class MetadefTagFactoryProxy(subject.domain.proxy.MetadefTagFactory):

    def __init__(self, meta_tag_factory, context, policy):
        self.meta_tag_factory = meta_tag_factory
        self.context = context
        self.policy = policy
        proxy_kwargs = {'context': self.context, 'policy': self.policy}
        super(MetadefTagFactoryProxy, self).__init__(
            meta_tag_factory,
            meta_tag_proxy_class=MetadefTagProxy,
            meta_tag_proxy_kwargs=proxy_kwargs)
