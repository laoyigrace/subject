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

import copy

from subject.common import exception
import subject.domain.proxy
from subject.i18n import _


def is_subject_mutable(context, subject):
    """Return True if the subject is mutable in this context."""
    if context.is_admin:
        return True

    if subject.owner is None or context.owner is None:
        return False

    return subject.owner == context.owner


def proxy_subject(context, subject):
    if is_subject_mutable(context, subject):
        return ImageProxy(subject, context)
    else:
        return ImmutableImageProxy(subject, context)


def is_member_mutable(context, member):
    """Return True if the subject is mutable in this context."""
    if context.is_admin:
        return True

    if context.owner is None:
        return False

    return member.member_id == context.owner


def proxy_member(context, member):
    if is_member_mutable(context, member):
        return member
    else:
        return ImmutableMemberProxy(member)


def is_task_mutable(context, task):
    """Return True if the task is mutable in this context."""
    if context.is_admin:
        return True

    if context.owner is None:
        return False

    return task.owner == context.owner


def is_task_stub_mutable(context, task_stub):
    """Return True if the task stub is mutable in this context."""
    if context.is_admin:
        return True

    if context.owner is None:
        return False

    return task_stub.owner == context.owner


def proxy_task(context, task):
    if is_task_mutable(context, task):
        return task
    else:
        return ImmutableTaskProxy(task)


def proxy_task_stub(context, task_stub):
    if is_task_stub_mutable(context, task_stub):
        return task_stub
    else:
        return ImmutableTaskStubProxy(task_stub)


class SubjectRepoProxy(subject.domain.proxy.Repo):

    def __init__(self, subject_repo, context):
        self.context = context
        self.subject_repo = subject_repo
        proxy_kwargs = {'context': self.context}
        super(SubjectRepoProxy, self).__init__(subject_repo,
                                               item_proxy_class=ImageProxy,
                                               item_proxy_kwargs=proxy_kwargs)

    def get(self, subject_id):
        subject = self.subject_repo.get(subject_id)
        return proxy_subject(self.context, subject)

    def list(self, *args, **kwargs):
        subjects = self.subject_repo.list(*args, **kwargs)
        return [proxy_subject(self.context, i) for i in subjects]


class ImageMemberRepoProxy(subject.domain.proxy.MemberRepo):

    def __init__(self, member_repo, subject, context):
        self.member_repo = member_repo
        self.subject = subject
        self.context = context
        proxy_kwargs = {'context': self.context}
        super(ImageMemberRepoProxy, self).__init__(
            subject,
            member_repo,
            member_proxy_class=ImageMemberProxy,
            member_proxy_kwargs=proxy_kwargs)
        self._check_subject_visibility()

    def _check_subject_visibility(self):
        if self.subject.visibility == 'public':
            message = _("Public subjects do not have members.")
            raise exception.Forbidden(message)

    def get(self, member_id):
        if (self.context.is_admin or
                self.context.owner in (self.subject.owner, member_id)):
            member = self.member_repo.get(member_id)
            return proxy_member(self.context, member)
        else:
            message = _("You cannot get subject member for %s")
            raise exception.Forbidden(message % member_id)

    def list(self, *args, **kwargs):
        members = self.member_repo.list(*args, **kwargs)
        if (self.context.is_admin or
                self.context.owner == self.subject.owner):
            return [proxy_member(self.context, m) for m in members]
        for member in members:
            if member.member_id == self.context.owner:
                return [proxy_member(self.context, member)]
        message = _("You cannot get subject member for %s")
        raise exception.Forbidden(message % self.subject.subject_id)

    def remove(self, subject_member):
        if (self.subject.owner == self.context.owner or
                self.context.is_admin):
            self.member_repo.remove(subject_member)
        else:
            message = _("You cannot delete subject member for %s")
            raise exception.Forbidden(message
                                      % self.subject.subject_id)

    def add(self, subject_member):
        if (self.subject.owner == self.context.owner or
                self.context.is_admin):
            self.member_repo.add(subject_member)
        else:
            message = _("You cannot add subject member for %s")
            raise exception.Forbidden(message
                                      % self.subject.subject_id)

    def save(self, subject_member, from_state=None):
        if (self.context.is_admin or
                self.context.owner == subject_member.member_id):
            self.member_repo.save(subject_member, from_state=from_state)
        else:
            message = _("You cannot update subject member %s")
            raise exception.Forbidden(message % subject_member.member_id)


class SubjectFactoryProxy(subject.domain.proxy.SubjectFactory):

    def __init__(self, subject_factory, context):
        self.subject_factory = subject_factory
        self.context = context
        kwargs = {'context': self.context}
        super(SubjectFactoryProxy, self).__init__(subject_factory,
                                                  proxy_class=ImageProxy,
                                                  proxy_kwargs=kwargs)

    def new_subject(self, **kwargs):
        owner = kwargs.pop('owner', self.context.owner)

        if not self.context.is_admin:
            if owner is None or owner != self.context.owner:
                message = _("You are not permitted to create subjects "
                            "owned by '%s'.")
                raise exception.Forbidden(message % owner)

        return super(SubjectFactoryProxy, self).new_subject(owner=owner, **kwargs)


class ImageMemberFactoryProxy(subject.domain.proxy.ImageMembershipFactory):

    def __init__(self, subject_member_factory, context):
        self.subject_member_factory = subject_member_factory
        self.context = context
        kwargs = {'context': self.context}
        super(ImageMemberFactoryProxy, self).__init__(
            subject_member_factory,
            proxy_class=ImageMemberProxy,
            proxy_kwargs=kwargs)

    def new_subject_member(self, subject, member_id):
        owner = subject.owner

        if not self.context.is_admin:
            if owner is None or owner != self.context.owner:
                message = _("You are not permitted to create subject members "
                            "for the subject.")
                raise exception.Forbidden(message)

        if subject.visibility == 'public':
            message = _("Public subjects do not have members.")
            raise exception.Forbidden(message)

        return self.subject_member_factory.new_subject_member(subject, member_id)


def _immutable_attr(target, attr, proxy=None):

    def get_attr(self):
        value = getattr(getattr(self, target), attr)
        if proxy is not None:
            value = proxy(value)
        return value

    def forbidden(self, *args, **kwargs):
        resource = getattr(self, 'resource_name', 'resource')
        message = _("You are not permitted to modify '%(attr)s' on this "
                    "%(resource)s.")
        raise exception.Forbidden(message % {'attr': attr,
                                             'resource': resource})

    return property(get_attr, forbidden, forbidden)


class ImmutableLocations(list):
    def forbidden(self, *args, **kwargs):
        message = _("You are not permitted to modify locations "
                    "for this subject.")
        raise exception.Forbidden(message)

    def __deepcopy__(self, memo):
        return ImmutableLocations(copy.deepcopy(list(self), memo))

    append = forbidden
    extend = forbidden
    insert = forbidden
    pop = forbidden
    remove = forbidden
    reverse = forbidden
    sort = forbidden
    __delitem__ = forbidden
    __delslice__ = forbidden
    __iadd__ = forbidden
    __imul__ = forbidden
    __setitem__ = forbidden
    __setslice__ = forbidden


class ImmutableProperties(dict):
    def forbidden_key(self, key, *args, **kwargs):
        message = _("You are not permitted to modify '%s' on this subject.")
        raise exception.Forbidden(message % key)

    def forbidden(self, *args, **kwargs):
        message = _("You are not permitted to modify this subject.")
        raise exception.Forbidden(message)

    __delitem__ = forbidden_key
    __setitem__ = forbidden_key
    pop = forbidden
    popitem = forbidden
    setdefault = forbidden
    update = forbidden


class ImmutableTags(set):
    def forbidden(self, *args, **kwargs):
        message = _("You are not permitted to modify tags on this subject.")
        raise exception.Forbidden(message)

    add = forbidden
    clear = forbidden
    difference_update = forbidden
    intersection_update = forbidden
    pop = forbidden
    remove = forbidden
    symmetric_difference_update = forbidden
    update = forbidden


class ImmutableImageProxy(object):
    def __init__(self, base, context):
        self.base = base
        self.context = context
        self.resource_name = 'subject'

    name = _immutable_attr('base', 'name')
    subject_id = _immutable_attr('base', 'subject_id')
    status = _immutable_attr('base', 'status')
    created_at = _immutable_attr('base', 'created_at')
    updated_at = _immutable_attr('base', 'updated_at')
    visibility = _immutable_attr('base', 'visibility')
    min_disk = _immutable_attr('base', 'min_disk')
    min_ram = _immutable_attr('base', 'min_ram')
    protected = _immutable_attr('base', 'protected')
    locations = _immutable_attr('base', 'locations', proxy=ImmutableLocations)
    checksum = _immutable_attr('base', 'checksum')
    owner = _immutable_attr('base', 'owner')
    disk_format = _immutable_attr('base', 'disk_format')
    container_format = _immutable_attr('base', 'container_format')
    size = _immutable_attr('base', 'size')
    virtual_size = _immutable_attr('base', 'virtual_size')
    extra_properties = _immutable_attr('base', 'extra_properties',
                                       proxy=ImmutableProperties)
    tags = _immutable_attr('base', 'tags', proxy=ImmutableTags)

    def delete(self):
        message = _("You are not permitted to delete this subject.")
        raise exception.Forbidden(message)

    def get_data(self, *args, **kwargs):
        return self.base.get_data(*args, **kwargs)

    def set_data(self, *args, **kwargs):
        message = _("You are not permitted to upload data for this subject.")
        raise exception.Forbidden(message)

    def deactivate(self, *args, **kwargs):
        message = _("You are not permitted to deactivate this subject.")
        raise exception.Forbidden(message)

    def reactivate(self, *args, **kwargs):
        message = _("You are not permitted to reactivate this subject.")
        raise exception.Forbidden(message)


class ImmutableMemberProxy(object):
    def __init__(self, base):
        self.base = base
        self.resource_name = 'subject member'

    id = _immutable_attr('base', 'id')
    subject_id = _immutable_attr('base', 'subject_id')
    member_id = _immutable_attr('base', 'member_id')
    status = _immutable_attr('base', 'status')
    created_at = _immutable_attr('base', 'created_at')
    updated_at = _immutable_attr('base', 'updated_at')


class ImmutableTaskProxy(object):
    def __init__(self, base):
        self.base = base
        self.resource_name = 'task'

    task_id = _immutable_attr('base', 'task_id')
    type = _immutable_attr('base', 'type')
    status = _immutable_attr('base', 'status')
    owner = _immutable_attr('base', 'owner')
    expires_at = _immutable_attr('base', 'expires_at')
    created_at = _immutable_attr('base', 'created_at')
    updated_at = _immutable_attr('base', 'updated_at')
    input = _immutable_attr('base', 'input')
    message = _immutable_attr('base', 'message')
    result = _immutable_attr('base', 'result')

    def run(self, executor):
        self.base.run(executor)

    def begin_processing(self):
        message = _("You are not permitted to set status on this task.")
        raise exception.Forbidden(message)

    def succeed(self, result):
        message = _("You are not permitted to set status on this task.")
        raise exception.Forbidden(message)

    def fail(self, message):
        message = _("You are not permitted to set status on this task.")
        raise exception.Forbidden(message)


class ImmutableTaskStubProxy(object):
    def __init__(self, base):
        self.base = base
        self.resource_name = 'task stub'

    task_id = _immutable_attr('base', 'task_id')
    type = _immutable_attr('base', 'type')
    status = _immutable_attr('base', 'status')
    owner = _immutable_attr('base', 'owner')
    expires_at = _immutable_attr('base', 'expires_at')
    created_at = _immutable_attr('base', 'created_at')
    updated_at = _immutable_attr('base', 'updated_at')


class ImageProxy(subject.domain.proxy.Subject):

    def __init__(self, subject, context):
        self.subject = subject
        self.context = context
        super(ImageProxy, self).__init__(subject)


class ImageMemberProxy(subject.domain.proxy.ImageMember):

    def __init__(self, subject_member, context):
        self.subject_member = subject_member
        self.context = context
        super(ImageMemberProxy, self).__init__(subject_member)


class TaskProxy(subject.domain.proxy.Task):

    def __init__(self, task):
        self.task = task
        super(TaskProxy, self).__init__(task)


class TaskFactoryProxy(subject.domain.proxy.TaskFactory):

    def __init__(self, task_factory, context):
        self.task_factory = task_factory
        self.context = context
        super(TaskFactoryProxy, self).__init__(
            task_factory,
            task_proxy_class=TaskProxy)

    def new_task(self, **kwargs):
        owner = kwargs.get('owner', self.context.owner)

        # NOTE(nikhil): Unlike Images, Tasks are expected to have owner.
        # We currently do not allow even admins to set the owner to None.
        if owner is not None and (owner == self.context.owner
                                  or self.context.is_admin):
            return super(TaskFactoryProxy, self).new_task(**kwargs)
        else:
            message = _("You are not permitted to create this task with "
                        "owner as: %s")
            raise exception.Forbidden(message % owner)


class TaskRepoProxy(subject.domain.proxy.TaskRepo):

    def __init__(self, task_repo, context):
        self.task_repo = task_repo
        self.context = context
        super(TaskRepoProxy, self).__init__(task_repo)

    def get(self, task_id):
        task = self.task_repo.get(task_id)
        return proxy_task(self.context, task)


class TaskStubRepoProxy(subject.domain.proxy.TaskStubRepo):

    def __init__(self, task_stub_repo, context):
        self.task_stub_repo = task_stub_repo
        self.context = context
        super(TaskStubRepoProxy, self).__init__(task_stub_repo)

    def list(self, *args, **kwargs):
        task_stubs = self.task_stub_repo.list(*args, **kwargs)
        return [proxy_task_stub(self.context, t) for t in task_stubs]


# Metadef Namespace classes
def is_namespace_mutable(context, namespace):
    """Return True if the namespace is mutable in this context."""
    if context.is_admin:
        return True

    if context.owner is None:
        return False

    return namespace.owner == context.owner


def proxy_namespace(context, namespace):
    if is_namespace_mutable(context, namespace):
        return namespace
    else:
        return ImmutableMetadefNamespaceProxy(namespace)


class ImmutableMetadefNamespaceProxy(object):

    def __init__(self, base):
        self.base = base
        self.resource_name = 'namespace'

    namespace_id = _immutable_attr('base', 'namespace_id')
    namespace = _immutable_attr('base', 'namespace')
    display_name = _immutable_attr('base', 'display_name')
    description = _immutable_attr('base', 'description')
    owner = _immutable_attr('base', 'owner')
    visibility = _immutable_attr('base', 'visibility')
    protected = _immutable_attr('base', 'protected')
    created_at = _immutable_attr('base', 'created_at')
    updated_at = _immutable_attr('base', 'updated_at')

    def delete(self):
        message = _("You are not permitted to delete this namespace.")
        raise exception.Forbidden(message)

    def save(self):
        message = _("You are not permitted to update this namespace.")
        raise exception.Forbidden(message)


class MetadefNamespaceProxy(subject.domain.proxy.MetadefNamespace):

    def __init__(self, namespace):
        self.namespace_input = namespace
        super(MetadefNamespaceProxy, self).__init__(namespace)


class MetadefNamespaceFactoryProxy(
        subject.domain.proxy.MetadefNamespaceFactory):

    def __init__(self, meta_namespace_factory, context):
        self.meta_namespace_factory = meta_namespace_factory
        self.context = context
        super(MetadefNamespaceFactoryProxy, self).__init__(
            meta_namespace_factory,
            meta_namespace_proxy_class=MetadefNamespaceProxy)

    def new_namespace(self, **kwargs):
        owner = kwargs.pop('owner', self.context.owner)

        if not self.context.is_admin:
            if owner is None or owner != self.context.owner:
                message = _("You are not permitted to create namespace "
                            "owned by '%s'")
                raise exception.Forbidden(message % (owner))

        return super(MetadefNamespaceFactoryProxy, self).new_namespace(
            owner=owner, **kwargs)


class MetadefNamespaceRepoProxy(subject.domain.proxy.MetadefNamespaceRepo):

    def __init__(self, namespace_repo, context):
        self.namespace_repo = namespace_repo
        self.context = context
        super(MetadefNamespaceRepoProxy, self).__init__(namespace_repo)

    def get(self, namespace):
        namespace_obj = self.namespace_repo.get(namespace)
        return proxy_namespace(self.context, namespace_obj)

    def list(self, *args, **kwargs):
        namespaces = self.namespace_repo.list(*args, **kwargs)
        return [proxy_namespace(self.context, namespace) for
                namespace in namespaces]


# Metadef Object classes
def is_object_mutable(context, object):
    """Return True if the object is mutable in this context."""
    if context.is_admin:
        return True

    if context.owner is None:
        return False

    return object.namespace.owner == context.owner


def proxy_object(context, object):
    if is_object_mutable(context, object):
        return object
    else:
        return ImmutableMetadefObjectProxy(object)


class ImmutableMetadefObjectProxy(object):

    def __init__(self, base):
        self.base = base
        self.resource_name = 'object'

    object_id = _immutable_attr('base', 'object_id')
    name = _immutable_attr('base', 'name')
    required = _immutable_attr('base', 'required')
    description = _immutable_attr('base', 'description')
    properties = _immutable_attr('base', 'properties')
    created_at = _immutable_attr('base', 'created_at')
    updated_at = _immutable_attr('base', 'updated_at')

    def delete(self):
        message = _("You are not permitted to delete this object.")
        raise exception.Forbidden(message)

    def save(self):
        message = _("You are not permitted to update this object.")
        raise exception.Forbidden(message)


class MetadefObjectProxy(subject.domain.proxy.MetadefObject):

    def __init__(self, meta_object):
        self.meta_object = meta_object
        super(MetadefObjectProxy, self).__init__(meta_object)


class MetadefObjectFactoryProxy(subject.domain.proxy.MetadefObjectFactory):

    def __init__(self, meta_object_factory, context):
        self.meta_object_factory = meta_object_factory
        self.context = context
        super(MetadefObjectFactoryProxy, self).__init__(
            meta_object_factory,
            meta_object_proxy_class=MetadefObjectProxy)

    def new_object(self, **kwargs):
        owner = kwargs.pop('owner', self.context.owner)

        if not self.context.is_admin:
            if owner is None or owner != self.context.owner:
                message = _("You are not permitted to create object "
                            "owned by '%s'")
                raise exception.Forbidden(message % (owner))

        return super(MetadefObjectFactoryProxy, self).new_object(**kwargs)


class MetadefObjectRepoProxy(subject.domain.proxy.MetadefObjectRepo):

    def __init__(self, object_repo, context):
        self.object_repo = object_repo
        self.context = context
        super(MetadefObjectRepoProxy, self).__init__(object_repo)

    def get(self, namespace, object_name):
        meta_object = self.object_repo.get(namespace, object_name)
        return proxy_object(self.context, meta_object)

    def list(self, *args, **kwargs):
        objects = self.object_repo.list(*args, **kwargs)
        return [proxy_object(self.context, meta_object) for
                meta_object in objects]


# Metadef ResourceType classes
def is_meta_resource_type_mutable(context, meta_resource_type):
    """Return True if the meta_resource_type is mutable in this context."""
    if context.is_admin:
        return True

    if context.owner is None:
        return False

    # (lakshmiS): resource type can exist without an association with
    # namespace and resource type cannot be created/update/deleted directly(
    # they have to be associated/de-associated from namespace)
    if meta_resource_type.namespace:
        return meta_resource_type.namespace.owner == context.owner
    else:
        return False


def proxy_meta_resource_type(context, meta_resource_type):
    if is_meta_resource_type_mutable(context, meta_resource_type):
        return meta_resource_type
    else:
        return ImmutableMetadefResourceTypeProxy(meta_resource_type)


class ImmutableMetadefResourceTypeProxy(object):

    def __init__(self, base):
        self.base = base
        self.resource_name = 'meta_resource_type'

    namespace = _immutable_attr('base', 'namespace')
    name = _immutable_attr('base', 'name')
    prefix = _immutable_attr('base', 'prefix')
    properties_target = _immutable_attr('base', 'properties_target')
    created_at = _immutable_attr('base', 'created_at')
    updated_at = _immutable_attr('base', 'updated_at')

    def delete(self):
        message = _("You are not permitted to delete this meta_resource_type.")
        raise exception.Forbidden(message)


class MetadefResourceTypeProxy(subject.domain.proxy.MetadefResourceType):

    def __init__(self, meta_resource_type):
        self.meta_resource_type = meta_resource_type
        super(MetadefResourceTypeProxy, self).__init__(meta_resource_type)


class MetadefResourceTypeFactoryProxy(
        subject.domain.proxy.MetadefResourceTypeFactory):

    def __init__(self, resource_type_factory, context):
        self.meta_resource_type_factory = resource_type_factory
        self.context = context
        super(MetadefResourceTypeFactoryProxy, self).__init__(
            resource_type_factory,
            resource_type_proxy_class=MetadefResourceTypeProxy)

    def new_resource_type(self, **kwargs):
        owner = kwargs.pop('owner', self.context.owner)

        if not self.context.is_admin:
            if owner is None or owner != self.context.owner:
                message = _("You are not permitted to create resource_type "
                            "owned by '%s'")
                raise exception.Forbidden(message % (owner))

        return super(MetadefResourceTypeFactoryProxy, self).new_resource_type(
            **kwargs)


class MetadefResourceTypeRepoProxy(
        subject.domain.proxy.MetadefResourceTypeRepo):

    def __init__(self, meta_resource_type_repo, context):
        self.meta_resource_type_repo = meta_resource_type_repo
        self.context = context
        super(MetadefResourceTypeRepoProxy, self).__init__(
            meta_resource_type_repo)

    def list(self, *args, **kwargs):
        meta_resource_types = self.meta_resource_type_repo.list(
            *args, **kwargs)
        return [proxy_meta_resource_type(self.context, meta_resource_type) for
                meta_resource_type in meta_resource_types]

    def get(self, *args, **kwargs):
        meta_resource_type = self.meta_resource_type_repo.get(*args, **kwargs)
        return proxy_meta_resource_type(self.context, meta_resource_type)


# Metadef namespace properties classes
def is_namespace_property_mutable(context, namespace_property):
    """Return True if the object is mutable in this context."""
    if context.is_admin:
        return True

    if context.owner is None:
        return False

    return namespace_property.namespace.owner == context.owner


def proxy_namespace_property(context, namespace_property):
    if is_namespace_property_mutable(context, namespace_property):
        return namespace_property
    else:
        return ImmutableMetadefPropertyProxy(namespace_property)


class ImmutableMetadefPropertyProxy(object):

    def __init__(self, base):
        self.base = base
        self.resource_name = 'namespace_property'

    property_id = _immutable_attr('base', 'property_id')
    name = _immutable_attr('base', 'name')
    schema = _immutable_attr('base', 'schema')

    def delete(self):
        message = _("You are not permitted to delete this property.")
        raise exception.Forbidden(message)

    def save(self):
        message = _("You are not permitted to update this property.")
        raise exception.Forbidden(message)


class MetadefPropertyProxy(subject.domain.proxy.MetadefProperty):

    def __init__(self, namespace_property):
        self.meta_object = namespace_property
        super(MetadefPropertyProxy, self).__init__(namespace_property)


class MetadefPropertyFactoryProxy(subject.domain.proxy.MetadefPropertyFactory):

    def __init__(self, namespace_property_factory, context):
        self.meta_object_factory = namespace_property_factory
        self.context = context
        super(MetadefPropertyFactoryProxy, self).__init__(
            namespace_property_factory,
            property_proxy_class=MetadefPropertyProxy)

    def new_namespace_property(self, **kwargs):
        owner = kwargs.pop('owner', self.context.owner)

        if not self.context.is_admin:
            if owner is None or owner != self.context.owner:
                message = _("You are not permitted to create property "
                            "owned by '%s'")
                raise exception.Forbidden(message % (owner))

        return super(MetadefPropertyFactoryProxy, self).new_namespace_property(
            **kwargs)


class MetadefPropertyRepoProxy(subject.domain.proxy.MetadefPropertyRepo):

    def __init__(self, namespace_property_repo, context):
        self.namespace_property_repo = namespace_property_repo
        self.context = context
        super(MetadefPropertyRepoProxy, self).__init__(namespace_property_repo)

    def get(self, namespace, object_name):
        namespace_property = self.namespace_property_repo.get(namespace,
                                                              object_name)
        return proxy_namespace_property(self.context, namespace_property)

    def list(self, *args, **kwargs):
        namespace_properties = self.namespace_property_repo.list(
            *args, **kwargs)
        return [proxy_namespace_property(self.context, namespace_property) for
                namespace_property in namespace_properties]


# Metadef Tag classes
def is_tag_mutable(context, tag):
    """Return True if the tag is mutable in this context."""
    if context.is_admin:
        return True

    if context.owner is None:
        return False

    return tag.namespace.owner == context.owner


def proxy_tag(context, tag):
    if is_tag_mutable(context, tag):
        return tag
    else:
        return ImmutableMetadefTagProxy(tag)


class ImmutableMetadefTagProxy(object):

    def __init__(self, base):
        self.base = base
        self.resource_name = 'tag'

    tag_id = _immutable_attr('base', 'tag_id')
    name = _immutable_attr('base', 'name')
    created_at = _immutable_attr('base', 'created_at')
    updated_at = _immutable_attr('base', 'updated_at')

    def delete(self):
        message = _("You are not permitted to delete this tag.")
        raise exception.Forbidden(message)

    def save(self):
        message = _("You are not permitted to update this tag.")
        raise exception.Forbidden(message)


class MetadefTagProxy(subject.domain.proxy.MetadefTag):
    pass


class MetadefTagFactoryProxy(subject.domain.proxy.MetadefTagFactory):

    def __init__(self, meta_tag_factory, context):
        self.meta_tag_factory = meta_tag_factory
        self.context = context
        super(MetadefTagFactoryProxy, self).__init__(
            meta_tag_factory,
            meta_tag_proxy_class=MetadefTagProxy)

    def new_tag(self, **kwargs):
        owner = kwargs.pop('owner', self.context.owner)
        if not self.context.is_admin:
            if owner is None:
                message = _("Owner must be specified to create a tag.")
                raise exception.Forbidden(message)
            elif owner != self.context.owner:
                message = _("You are not permitted to create a tag"
                            " in the namespace owned by '%s'")
                raise exception.Forbidden(message % (owner))

        return super(MetadefTagFactoryProxy, self).new_tag(**kwargs)


class MetadefTagRepoProxy(subject.domain.proxy.MetadefTagRepo):

    def __init__(self, tag_repo, context):
        self.tag_repo = tag_repo
        self.context = context
        super(MetadefTagRepoProxy, self).__init__(tag_repo)

    def get(self, namespace, tag_name):
        meta_tag = self.tag_repo.get(namespace, tag_name)
        return proxy_tag(self.context, meta_tag)

    def list(self, *args, **kwargs):
        tags = self.tag_repo.list(*args, **kwargs)
        return [proxy_tag(self.context, meta_tag) for
                meta_tag in tags]
