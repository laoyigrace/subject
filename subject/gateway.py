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
import glance_store

from subject.api import authorization
from subject.api import policy
from subject.api import property_protections
from subject.common import property_utils
from subject.common import store_utils
import subject.db
import subject.domain
import subject.location
import subject.notifier
import subject.quota


class Gateway(object):
    def __init__(self, db_api=None, store_api=None, notifier=None,
                 policy_enforcer=None):
        self.db_api = db_api or subject.db.get_api()
        self.store_api = store_api or glance_store
        self.store_utils = store_utils
        self.notifier = notifier or subject.notifier.Notifier()
        self.policy = policy_enforcer or policy.Enforcer()

    def get_subject_factory(self, context):
        subject_factory = subject.domain.SubjectFactory()
        store_subject_factory = subject.location.SubjectFactoryProxy(
            subject_factory, context, self.store_api, self.store_utils)
        quota_subject_factory = subject.quota.SubjectFactoryProxy(
                store_subject_factory, context, self.db_api, self.store_utils)
        policy_subject_factory = policy.SubjectFactoryProxy(
            quota_subject_factory, context, self.policy)
        notifier_subject_factory = subject.notifier.SubjectFactoryProxy(
            policy_subject_factory, context, self.notifier)
        if property_utils.is_property_protection_enabled():
            property_rules = property_utils.PropertyRules(self.policy)
            pif = property_protections.ProtectedSubjectFactoryProxy(
                notifier_subject_factory, context, property_rules)
            authorized_subject_factory = authorization.SubjectFactoryProxy(
                pif, context)
        else:
            authorized_subject_factory = authorization.SubjectFactoryProxy(
                notifier_subject_factory, context)
        return authorized_subject_factory

    def get_subject_member_factory(self, context):
        subject_factory = subject.domain.ImageMemberFactory()
        quota_subject_factory = subject.quota.ImageMemberFactoryProxy(
            subject_factory, context, self.db_api, self.store_utils)
        policy_member_factory = policy.ImageMemberFactoryProxy(
            quota_subject_factory, context, self.policy)
        authorized_subject_factory = authorization.ImageMemberFactoryProxy(
            policy_member_factory, context)
        return authorized_subject_factory

    def get_repo(self, context):
        subject_repo = subject.db.SubjectRepo(context, self.db_api)
        store_subject_repo = subject.location.SubjectRepoProxy(
            subject_repo, context, self.store_api, self.store_utils)
        quota_subject_repo = subject.quota.SubjectRepoProxy(
            store_subject_repo, context, self.db_api, self.store_utils)
        policy_subject_repo = policy.SubjectRepoProxy(
            quota_subject_repo, context, self.policy)
        notifier_subject_repo = subject.notifier.SubjectRepoProxy(
            policy_subject_repo, context, self.notifier)
        if property_utils.is_property_protection_enabled():
            property_rules = property_utils.PropertyRules(self.policy)
            pir = property_protections.ProtectedSubjectRepoProxy(
                notifier_subject_repo, context, property_rules)
            authorized_subject_repo = authorization.SubjectRepoProxy(
                pir, context)
        else:
            authorized_subject_repo = authorization.SubjectRepoProxy(
                notifier_subject_repo, context)

        return authorized_subject_repo

    def get_member_repo(self, subject, context):
        subject_member_repo = subject.db.ImageMemberRepo(
            context, self.db_api, subject)
        store_subject_repo = subject.location.ImageMemberRepoProxy(
            subject_member_repo, subject, context, self.store_api)
        policy_member_repo = policy.ImageMemberRepoProxy(
            store_subject_repo, subject, context, self.policy)
        notifier_member_repo = subject.notifier.ImageMemberRepoProxy(
            policy_member_repo, subject, context, self.notifier)
        authorized_member_repo = authorization.ImageMemberRepoProxy(
            notifier_member_repo, subject, context)

        return authorized_member_repo

    def get_task_factory(self, context):
        task_factory = subject.domain.TaskFactory()
        policy_task_factory = policy.TaskFactoryProxy(
            task_factory, context, self.policy)
        notifier_task_factory = subject.notifier.TaskFactoryProxy(
            policy_task_factory, context, self.notifier)
        authorized_task_factory = authorization.TaskFactoryProxy(
            notifier_task_factory, context)
        return authorized_task_factory

    def get_task_repo(self, context):
        task_repo = subject.db.TaskRepo(context, self.db_api)
        policy_task_repo = policy.TaskRepoProxy(
            task_repo, context, self.policy)
        notifier_task_repo = subject.notifier.TaskRepoProxy(
            policy_task_repo, context, self.notifier)
        authorized_task_repo = authorization.TaskRepoProxy(
            notifier_task_repo, context)
        return authorized_task_repo

    def get_task_stub_repo(self, context):
        task_stub_repo = subject.db.TaskRepo(context, self.db_api)
        policy_task_stub_repo = policy.TaskStubRepoProxy(
            task_stub_repo, context, self.policy)
        notifier_task_stub_repo = subject.notifier.TaskStubRepoProxy(
            policy_task_stub_repo, context, self.notifier)
        authorized_task_stub_repo = authorization.TaskStubRepoProxy(
            notifier_task_stub_repo, context)
        return authorized_task_stub_repo

    def get_task_executor_factory(self, context):
        task_repo = self.get_task_repo(context)
        subject_repo = self.get_repo(context)
        subject_factory = self.get_subject_factory(context)
        return subject.domain.TaskExecutorFactory(task_repo,
                                                  subject_repo,
                                                  subject_factory)

    def get_metadef_namespace_factory(self, context):
        ns_factory = subject.domain.MetadefNamespaceFactory()
        policy_ns_factory = policy.MetadefNamespaceFactoryProxy(
            ns_factory, context, self.policy)
        notifier_ns_factory = subject.notifier.MetadefNamespaceFactoryProxy(
            policy_ns_factory, context, self.notifier)
        authorized_ns_factory = authorization.MetadefNamespaceFactoryProxy(
            notifier_ns_factory, context)
        return authorized_ns_factory

    def get_metadef_namespace_repo(self, context):
        ns_repo = subject.db.MetadefNamespaceRepo(context, self.db_api)
        policy_ns_repo = policy.MetadefNamespaceRepoProxy(
            ns_repo, context, self.policy)
        notifier_ns_repo = subject.notifier.MetadefNamespaceRepoProxy(
            policy_ns_repo, context, self.notifier)
        authorized_ns_repo = authorization.MetadefNamespaceRepoProxy(
            notifier_ns_repo, context)
        return authorized_ns_repo

    def get_metadef_object_factory(self, context):
        object_factory = subject.domain.MetadefObjectFactory()
        policy_object_factory = policy.MetadefObjectFactoryProxy(
            object_factory, context, self.policy)
        notifier_object_factory = subject.notifier.MetadefObjectFactoryProxy(
            policy_object_factory, context, self.notifier)
        authorized_object_factory = authorization.MetadefObjectFactoryProxy(
            notifier_object_factory, context)
        return authorized_object_factory

    def get_metadef_object_repo(self, context):
        object_repo = subject.db.MetadefObjectRepo(context, self.db_api)
        policy_object_repo = policy.MetadefObjectRepoProxy(
            object_repo, context, self.policy)
        notifier_object_repo = subject.notifier.MetadefObjectRepoProxy(
            policy_object_repo, context, self.notifier)
        authorized_object_repo = authorization.MetadefObjectRepoProxy(
            notifier_object_repo, context)
        return authorized_object_repo

    def get_metadef_resource_type_factory(self, context):
        resource_type_factory = subject.domain.MetadefResourceTypeFactory()
        policy_resource_type_factory = policy.MetadefResourceTypeFactoryProxy(
            resource_type_factory, context, self.policy)
        notifier_resource_type_factory = (
            subject.notifier.MetadefResourceTypeFactoryProxy(
                policy_resource_type_factory, context, self.notifier)
        )
        authorized_resource_type_factory = (
            authorization.MetadefResourceTypeFactoryProxy(
                notifier_resource_type_factory, context)
        )
        return authorized_resource_type_factory

    def get_metadef_resource_type_repo(self, context):
        resource_type_repo = subject.db.MetadefResourceTypeRepo(
            context, self.db_api)
        policy_object_repo = policy.MetadefResourceTypeRepoProxy(
            resource_type_repo, context, self.policy)
        notifier_object_repo = subject.notifier.MetadefResourceTypeRepoProxy(
            policy_object_repo, context, self.notifier)
        authorized_object_repo = authorization.MetadefResourceTypeRepoProxy(
            notifier_object_repo, context)
        return authorized_object_repo

    def get_metadef_property_factory(self, context):
        prop_factory = subject.domain.MetadefPropertyFactory()
        policy_prop_factory = policy.MetadefPropertyFactoryProxy(
            prop_factory, context, self.policy)
        notifier_prop_factory = subject.notifier.MetadefPropertyFactoryProxy(
            policy_prop_factory, context, self.notifier)
        authorized_prop_factory = authorization.MetadefPropertyFactoryProxy(
            notifier_prop_factory, context)
        return authorized_prop_factory

    def get_metadef_property_repo(self, context):
        prop_repo = subject.db.MetadefPropertyRepo(context, self.db_api)
        policy_prop_repo = policy.MetadefPropertyRepoProxy(
            prop_repo, context, self.policy)
        notifier_prop_repo = subject.notifier.MetadefPropertyRepoProxy(
            policy_prop_repo, context, self.notifier)
        authorized_prop_repo = authorization.MetadefPropertyRepoProxy(
            notifier_prop_repo, context)
        return authorized_prop_repo

    def get_metadef_tag_factory(self, context):
        tag_factory = subject.domain.MetadefTagFactory()
        policy_tag_factory = policy.MetadefTagFactoryProxy(
            tag_factory, context, self.policy)
        notifier_tag_factory = subject.notifier.MetadefTagFactoryProxy(
            policy_tag_factory, context, self.notifier)
        authorized_tag_factory = authorization.MetadefTagFactoryProxy(
            notifier_tag_factory, context)
        return authorized_tag_factory

    def get_metadef_tag_repo(self, context):
        tag_repo = subject.db.MetadefTagRepo(context, self.db_api)
        policy_tag_repo = policy.MetadefTagRepoProxy(
            tag_repo, context, self.policy)
        notifier_tag_repo = subject.notifier.MetadefTagRepoProxy(
            policy_tag_repo, context, self.notifier)
        authorized_tag_repo = authorization.MetadefTagRepoProxy(
            notifier_tag_repo, context)
        return authorized_tag_repo
