# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2010-2012 OpenStack Foundation
# Copyright 2013 IBM Corp.
# Copyright 2015 Mirantis, Inc.
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

from oslo_config import cfg
from oslo_utils import importutils
from wsme.rest import json

from subject.api.v2.model.metadef_property_type import PropertyType
from subject.common import crypt
from subject.common import exception
from subject.common.glare import serialization
from subject.common import location_strategy
import subject.domain
import subject.domain.proxy
from subject import glare as ga
from subject.i18n import _

CONF = cfg.CONF
CONF.import_opt('subject_size_cap', 'subject.common.config')
CONF.import_opt('metadata_encryption_key', 'subject.common.config')


def get_api():
    api = importutils.import_module(CONF.data_api)
    if hasattr(api, 'configure'):
        api.configure()
    return api


def unwrap(db_api):
    return db_api


# attributes common to all models
BASE_MODEL_ATTRS = set(['id', 'created_at', 'updated_at', 'deleted_at',
                        'deleted'])


IMAGE_ATTRS = BASE_MODEL_ATTRS | set(['name', 'status', 'size', 'virtual_size',
                                      'disk_format', 'container_format',
                                      'min_disk', 'min_ram', 'is_public',
                                      'locations', 'checksum', 'owner',
                                      'protected'])


class ArtifactRepo(object):
    fields = ['id', 'name', 'version', 'type_name', 'type_version',
              'visibility', 'state', 'owner', 'scope', 'created_at',
              'updated_at', 'tags', 'dependencies', 'blobs', 'properties']

    def __init__(self, context, db_api, plugins):
        self.context = context
        self.db_api = db_api
        self.plugins = plugins

    def get(self, artifact_id, type_name=None, type_version=None,
            show_level=None, include_deleted=False):
        if show_level is None:
            show_level = ga.Showlevel.BASIC
        try:
            db_api_artifact = self.db_api.artifact_get(self.context,
                                                       artifact_id,
                                                       type_name,
                                                       type_version,
                                                       show_level)
            if db_api_artifact["state"] == 'deleted' and not include_deleted:
                raise exception.ArtifactNotFound(artifact_id)
        except (exception.ArtifactNotFound, exception.ArtifactForbidden):
            msg = _("No artifact found with ID %s") % artifact_id
            raise exception.ArtifactNotFound(msg)
        return serialization.deserialize_from_db(db_api_artifact, self.plugins)

    def list(self, marker=None, limit=None,
             sort_keys=None, sort_dirs=None, filters=None,
             show_level=None):
        sort_keys = ['created_at'] if sort_keys is None else sort_keys
        sort_dirs = ['desc'] if sort_dirs is None else sort_dirs
        if show_level is None:
            show_level = ga.Showlevel.NONE
        db_api_artifacts = self.db_api.artifact_get_all(
            self.context, filters=filters, marker=marker, limit=limit,
            sort_keys=sort_keys, sort_dirs=sort_dirs, show_level=show_level)
        artifacts = []
        for db_api_artifact in db_api_artifacts:
            artifact = serialization.deserialize_from_db(db_api_artifact,
                                                         self.plugins)
            artifacts.append(artifact)
        return artifacts

    def _format_artifact_from_db(self, db_artifact):
        kwargs = {k: db_artifact.get(k, None) for k in self.fields}
        return subject.domain.Artifact(**kwargs)

    def add(self, artifact):
        artifact_values = serialization.serialize_for_db(artifact)
        artifact_values['updated_at'] = artifact.updated_at
        self.db_api.artifact_create(self.context, artifact_values,
                                    artifact.type_name, artifact.type_version)

    def save(self, artifact):
        artifact_values = serialization.serialize_for_db(artifact)
        try:
            db_api_artifact = self.db_api.artifact_update(
                self.context,
                artifact_values,
                artifact.id,
                artifact.type_name,
                artifact.type_version)
        except (exception.ArtifactNotFound,
                exception.ArtifactForbidden):
            msg = _("No artifact found with ID %s") % artifact.id
            raise exception.ArtifactNotFound(msg)
        return serialization.deserialize_from_db(db_api_artifact, self.plugins)

    def remove(self, artifact):
        try:
            self.db_api.artifact_delete(self.context, artifact.id,
                                        artifact.type_name,
                                        artifact.type_version)
        except (exception.NotFound, exception.Forbidden):
            msg = _("No artifact found with ID %s") % artifact.id
            raise exception.ArtifactNotFound(msg)

    def publish(self, artifact):
        try:
            artifact_changed = (
                self.db_api.artifact_publish(
                    self.context,
                    artifact.id,
                    artifact.type_name,
                    artifact.type_version))
            return serialization.deserialize_from_db(artifact_changed,
                                                     self.plugins)
        except (exception.NotFound, exception.Forbidden):
            msg = _("No artifact found with ID %s") % artifact.id
            raise exception.ArtifactNotFound(msg)


class SubjectRepo(object):

    def __init__(self, context, db_api):
        self.context = context
        self.db_api = db_api

    def get(self, subject_id):
        try:
            db_api_subject = dict(self.db_api.subject_get(self.context, subject_id))
            if db_api_subject['deleted']:
                raise exception.ImageNotFound()
        except (exception.ImageNotFound, exception.Forbidden):
            msg = _("No subject found with ID %s") % subject_id
            raise exception.ImageNotFound(msg)
        tags = self.db_api.subject_tag_get_all(self.context, subject_id)
        subject = self._format_subject_from_db(db_api_subject, tags)
        return ImageProxy(subject, self.context, self.db_api)

    def list(self, marker=None, limit=None, sort_key=None,
             sort_dir=None, filters=None, member_status='accepted'):
        sort_key = ['created_at'] if not sort_key else sort_key
        sort_dir = ['desc'] if not sort_dir else sort_dir
        db_api_subjects = self.db_api.subject_get_all(
            self.context, filters=filters, marker=marker, limit=limit,
            sort_key=sort_key, sort_dir=sort_dir,
            member_status=member_status, return_tag=True)
        subjects = []
        for db_api_subject in db_api_subjects:
            db_subject = dict(db_api_subject)
            subject = self._format_subject_from_db(db_subject, db_subject['tags'])
            subjects.append(subject)
        return subjects

    def _format_subject_from_db(self, db_subject, db_tags):
        visibility = 'public' if db_subject['is_public'] else 'private'
        properties = {}
        for prop in db_subject.pop('properties'):
            # NOTE(markwash) db api requires us to filter deleted
            if not prop['deleted']:
                properties[prop['name']] = prop['value']
        locations = [loc for loc in db_subject['locations']
                     if loc['status'] == 'active']
        if CONF.metadata_encryption_key:
            key = CONF.metadata_encryption_key
            for l in locations:
                l['url'] = crypt.urlsafe_decrypt(key, l['url'])
        return subject.domain.Subject(
            subject_id=db_subject['id'],
            name=db_subject['name'],
            status=db_subject['status'],
            created_at=db_subject['created_at'],
            updated_at=db_subject['updated_at'],
            visibility=visibility,
            min_disk=db_subject['min_disk'],
            min_ram=db_subject['min_ram'],
            protected=db_subject['protected'],
            locations=location_strategy.get_ordered_locations(locations),
            checksum=db_subject['checksum'],
            owner=db_subject['owner'],
            disk_format=db_subject['disk_format'],
            container_format=db_subject['container_format'],
            size=db_subject['size'],
            virtual_size=db_subject['virtual_size'],
            extra_properties=properties,
            tags=db_tags
        )

    def _format_subject_to_db(self, subject):
        locations = subject.locations
        if CONF.metadata_encryption_key:
            key = CONF.metadata_encryption_key
            ld = []
            for loc in locations:
                url = crypt.urlsafe_encrypt(key, loc['url'])
                ld.append({'url': url, 'metadata': loc['metadata'],
                           'status': loc['status'],
                           # NOTE(zhiyan): New location has no ID field.
                           'id': loc.get('id')})
            locations = ld
        return {
            'id': subject.subject_id,
            'name': subject.name,
            'status': subject.status,
            'created_at': subject.created_at,
            'min_disk': subject.min_disk,
            'min_ram': subject.min_ram,
            'protected': subject.protected,
            'locations': locations,
            'checksum': subject.checksum,
            'owner': subject.owner,
            'disk_format': subject.disk_format,
            'container_format': subject.container_format,
            'size': subject.size,
            'virtual_size': subject.virtual_size,
            'is_public': subject.visibility == 'public',
            'properties': dict(subject.extra_properties),
        }

    def add(self, subject):
        subject_values = self._format_subject_to_db(subject)
        if (subject_values['size'] is not None
           and subject_values['size'] > CONF.subject_size_cap):
            raise exception.ImageSizeLimitExceeded
        # the updated_at value is not set in the _format_subject_to_db
        # function since it is specific to subject create
        subject_values['updated_at'] = subject.updated_at
        new_values = self.db_api.subject_create(self.context, subject_values)
        self.db_api.subject_tag_set_all(self.context,
                                      subject.subject_id, subject.tags)
        subject.created_at = new_values['created_at']
        subject.updated_at = new_values['updated_at']

    def save(self, subject, from_state=None):
        subject_values = self._format_subject_to_db(subject)
        if (subject_values['size'] is not None
           and subject_values['size'] > CONF.subject_size_cap):
            raise exception.ImageSizeLimitExceeded
        try:
            new_values = self.db_api.subject_update(self.context,
                                                  subject.subject_id,
                                                  subject_values,
                                                  purge_props=True,
                                                  from_state=from_state)
        except (exception.ImageNotFound, exception.Forbidden):
            msg = _("No subject found with ID %s") % subject.subject_id
            raise exception.ImageNotFound(msg)
        self.db_api.subject_tag_set_all(self.context, subject.subject_id,
                                      subject.tags)
        subject.updated_at = new_values['updated_at']

    def remove(self, subject):
        try:
            self.db_api.subject_update(self.context, subject.subject_id,
                                     {'status': subject.status},
                                     purge_props=True)
        except (exception.ImageNotFound, exception.Forbidden):
            msg = _("No subject found with ID %s") % subject.subject_id
            raise exception.ImageNotFound(msg)
        # NOTE(markwash): don't update tags?
        new_values = self.db_api.subject_destroy(self.context, subject.subject_id)
        subject.updated_at = new_values['updated_at']


class ImageProxy(subject.domain.proxy.Subject):

    def __init__(self, subject, context, db_api):
        self.context = context
        self.db_api = db_api
        self.subject = subject
        super(ImageProxy, self).__init__(subject)


class ImageMemberRepo(object):

    def __init__(self, context, db_api, subject):
        self.context = context
        self.db_api = db_api
        self.subject = subject

    def _format_subject_member_from_db(self, db_subject_member):
        return subject.domain.ImageMembership(
            id=db_subject_member['id'],
            subject_id=db_subject_member['subject_id'],
            member_id=db_subject_member['member'],
            status=db_subject_member['status'],
            created_at=db_subject_member['created_at'],
            updated_at=db_subject_member['updated_at']
        )

    def _format_subject_member_to_db(self, subject_member):
        subject_member = {'subject_id': self.subject.subject_id,
                        'member': subject_member.member_id,
                        'status': subject_member.status,
                        'created_at': subject_member.created_at}
        return subject_member

    def list(self):
        db_members = self.db_api.subject_member_find(
            self.context, subject_id=self.subject.subject_id)
        subject_members = []
        for db_member in db_members:
            subject_members.append(self._format_subject_member_from_db(db_member))
        return subject_members

    def add(self, subject_member):
        try:
            self.get(subject_member.member_id)
        except exception.NotFound:
            pass
        else:
            msg = _('The target member %(member_id)s is already '
                    'associated with subject %(subject_id)s.') % {
                        'member_id': subject_member.member_id,
                        'subject_id': self.subject.subject_id}
            raise exception.Duplicate(msg)

        subject_member_values = self._format_subject_member_to_db(subject_member)
        # Note(shalq): find the subject member including the member marked with
        # deleted. We will use only one record to represent membership between
        # the same subject and member. The record of the deleted subject member
        # will be reused, if it exists, update its properties instead of
        # creating a new one.
        members = self.db_api.subject_member_find(self.context,
                                                subject_id=self.subject.subject_id,
                                                member=subject_member.member_id,
                                                include_deleted=True)
        if members:
            new_values = self.db_api.subject_member_update(self.context,
                                                         members[0]['id'],
                                                         subject_member_values)
        else:
            new_values = self.db_api.subject_member_create(self.context,
                                                         subject_member_values)
        subject_member.created_at = new_values['created_at']
        subject_member.updated_at = new_values['updated_at']
        subject_member.id = new_values['id']

    def remove(self, subject_member):
        try:
            self.db_api.subject_member_delete(self.context, subject_member.id)
        except (exception.NotFound, exception.Forbidden):
            msg = _("The specified member %s could not be found")
            raise exception.NotFound(msg % subject_member.id)

    def save(self, subject_member, from_state=None):
        subject_member_values = self._format_subject_member_to_db(subject_member)
        try:
            new_values = self.db_api.subject_member_update(self.context,
                                                         subject_member.id,
                                                         subject_member_values)
        except (exception.NotFound, exception.Forbidden):
            raise exception.NotFound()
        subject_member.updated_at = new_values['updated_at']

    def get(self, member_id):
        try:
            db_api_subject_member = self.db_api.subject_member_find(
                self.context,
                self.subject.subject_id,
                member_id)
            if not db_api_subject_member:
                raise exception.NotFound()
        except (exception.NotFound, exception.Forbidden):
            raise exception.NotFound()

        subject_member = self._format_subject_member_from_db(
            db_api_subject_member[0])
        return subject_member


class TaskRepo(object):

    def __init__(self, context, db_api):
        self.context = context
        self.db_api = db_api

    def _format_task_from_db(self, db_task):
        return subject.domain.Task(
            task_id=db_task['id'],
            task_type=db_task['type'],
            status=db_task['status'],
            owner=db_task['owner'],
            expires_at=db_task['expires_at'],
            created_at=db_task['created_at'],
            updated_at=db_task['updated_at'],
            task_input=db_task['input'],
            result=db_task['result'],
            message=db_task['message'],
        )

    def _format_task_stub_from_db(self, db_task):
        return subject.domain.TaskStub(
            task_id=db_task['id'],
            task_type=db_task['type'],
            status=db_task['status'],
            owner=db_task['owner'],
            expires_at=db_task['expires_at'],
            created_at=db_task['created_at'],
            updated_at=db_task['updated_at'],
        )

    def _format_task_to_db(self, task):
        task = {'id': task.task_id,
                'type': task.type,
                'status': task.status,
                'input': task.task_input,
                'result': task.result,
                'owner': task.owner,
                'message': task.message,
                'expires_at': task.expires_at,
                'created_at': task.created_at,
                'updated_at': task.updated_at,
                }
        return task

    def get(self, task_id):
        try:
            db_api_task = self.db_api.task_get(self.context, task_id)
        except (exception.NotFound, exception.Forbidden):
            msg = _('Could not find task %s') % task_id
            raise exception.NotFound(msg)
        return self._format_task_from_db(db_api_task)

    def list(self, marker=None, limit=None, sort_key='created_at',
             sort_dir='desc', filters=None):
        db_api_tasks = self.db_api.task_get_all(self.context,
                                                filters=filters,
                                                marker=marker,
                                                limit=limit,
                                                sort_key=sort_key,
                                                sort_dir=sort_dir)
        return [self._format_task_stub_from_db(task) for task in db_api_tasks]

    def save(self, task):
        task_values = self._format_task_to_db(task)
        try:
            updated_values = self.db_api.task_update(self.context,
                                                     task.task_id,
                                                     task_values)
        except (exception.NotFound, exception.Forbidden):
            msg = _('Could not find task %s') % task.task_id
            raise exception.NotFound(msg)
        task.updated_at = updated_values['updated_at']

    def add(self, task):
        task_values = self._format_task_to_db(task)
        updated_values = self.db_api.task_create(self.context, task_values)
        task.created_at = updated_values['created_at']
        task.updated_at = updated_values['updated_at']

    def remove(self, task):
        task_values = self._format_task_to_db(task)
        try:
            self.db_api.task_update(self.context, task.task_id, task_values)
            updated_values = self.db_api.task_delete(self.context,
                                                     task.task_id)
        except (exception.NotFound, exception.Forbidden):
            msg = _('Could not find task %s') % task.task_id
            raise exception.NotFound(msg)
        task.updated_at = updated_values['updated_at']
        task.deleted_at = updated_values['deleted_at']


class MetadefNamespaceRepo(object):

    def __init__(self, context, db_api):
        self.context = context
        self.db_api = db_api

    def _format_namespace_from_db(self, namespace_obj):
        return subject.domain.MetadefNamespace(
            namespace_id=namespace_obj['id'],
            namespace=namespace_obj['namespace'],
            display_name=namespace_obj['display_name'],
            description=namespace_obj['description'],
            owner=namespace_obj['owner'],
            visibility=namespace_obj['visibility'],
            protected=namespace_obj['protected'],
            created_at=namespace_obj['created_at'],
            updated_at=namespace_obj['updated_at']
        )

    def _format_namespace_to_db(self, namespace_obj):
        namespace = {
            'namespace': namespace_obj.namespace,
            'display_name': namespace_obj.display_name,
            'description': namespace_obj.description,
            'visibility': namespace_obj.visibility,
            'protected': namespace_obj.protected,
            'owner': namespace_obj.owner
        }
        return namespace

    def add(self, namespace):
        self.db_api.metadef_namespace_create(
            self.context,
            self._format_namespace_to_db(namespace)
        )

    def get(self, namespace):
        try:
            db_api_namespace = self.db_api.metadef_namespace_get(
                self.context, namespace)
        except (exception.NotFound, exception.Forbidden):
            msg = _('Could not find namespace %s') % namespace
            raise exception.NotFound(msg)
        return self._format_namespace_from_db(db_api_namespace)

    def list(self, marker=None, limit=None, sort_key='created_at',
             sort_dir='desc', filters=None):
        db_namespaces = self.db_api.metadef_namespace_get_all(
            self.context,
            marker=marker,
            limit=limit,
            sort_key=sort_key,
            sort_dir=sort_dir,
            filters=filters
        )
        return [self._format_namespace_from_db(namespace_obj)
                for namespace_obj in db_namespaces]

    def remove(self, namespace):
        try:
            self.db_api.metadef_namespace_delete(self.context,
                                                 namespace.namespace)
        except (exception.NotFound, exception.Forbidden):
            msg = _("The specified namespace %s could not be found")
            raise exception.NotFound(msg % namespace.namespace)

    def remove_objects(self, namespace):
        try:
            self.db_api.metadef_object_delete_namespace_content(
                self.context,
                namespace.namespace
            )
        except (exception.NotFound, exception.Forbidden):
            msg = _("The specified namespace %s could not be found")
            raise exception.NotFound(msg % namespace.namespace)

    def remove_properties(self, namespace):
        try:
            self.db_api.metadef_property_delete_namespace_content(
                self.context,
                namespace.namespace
            )
        except (exception.NotFound, exception.Forbidden):
            msg = _("The specified namespace %s could not be found")
            raise exception.NotFound(msg % namespace.namespace)

    def remove_tags(self, namespace):
        try:
            self.db_api.metadef_tag_delete_namespace_content(
                self.context,
                namespace.namespace
            )
        except (exception.NotFound, exception.Forbidden):
            msg = _("The specified namespace %s could not be found")
            raise exception.NotFound(msg % namespace.namespace)

    def object_count(self, namespace_name):
        return self.db_api.metadef_object_count(
            self.context,
            namespace_name
        )

    def property_count(self, namespace_name):
        return self.db_api.metadef_property_count(
            self.context,
            namespace_name
        )

    def save(self, namespace):
        try:
            self.db_api.metadef_namespace_update(
                self.context, namespace.namespace_id,
                self._format_namespace_to_db(namespace)
            )
        except exception.NotFound as e:
            raise exception.NotFound(explanation=e.msg)
        return namespace


class MetadefObjectRepo(object):

    def __init__(self, context, db_api):
        self.context = context
        self.db_api = db_api
        self.meta_namespace_repo = MetadefNamespaceRepo(context, db_api)

    def _format_metadef_object_from_db(self, metadata_object,
                                       namespace_entity):
        required_str = metadata_object['required']
        required_list = required_str.split(",") if required_str else []

        # Convert the persisted json schema to a dict of PropertyTypes
        property_types = {}
        json_props = metadata_object['json_schema']
        for id in json_props:
            property_types[id] = json.fromjson(PropertyType, json_props[id])

        return subject.domain.MetadefObject(
            namespace=namespace_entity,
            object_id=metadata_object['id'],
            name=metadata_object['name'],
            required=required_list,
            description=metadata_object['description'],
            properties=property_types,
            created_at=metadata_object['created_at'],
            updated_at=metadata_object['updated_at']
        )

    def _format_metadef_object_to_db(self, metadata_object):

        required_str = (",".join(metadata_object.required) if
                        metadata_object.required else None)

        # Convert the model PropertyTypes dict to a JSON string
        properties = metadata_object.properties
        db_schema = {}
        if properties:
            for k, v in properties.items():
                json_data = json.tojson(PropertyType, v)
                db_schema[k] = json_data

        db_metadata_object = {
            'name': metadata_object.name,
            'required': required_str,
            'description': metadata_object.description,
            'json_schema': db_schema
        }
        return db_metadata_object

    def add(self, metadata_object):
        self.db_api.metadef_object_create(
            self.context,
            metadata_object.namespace,
            self._format_metadef_object_to_db(metadata_object)
        )

    def get(self, namespace, object_name):
        try:
            namespace_entity = self.meta_namespace_repo.get(namespace)
            db_metadata_object = self.db_api.metadef_object_get(
                self.context,
                namespace,
                object_name)
        except (exception.NotFound, exception.Forbidden):
            msg = _('Could not find metadata object %s') % object_name
            raise exception.NotFound(msg)
        return self._format_metadef_object_from_db(db_metadata_object,
                                                   namespace_entity)

    def list(self, marker=None, limit=None, sort_key='created_at',
             sort_dir='desc', filters=None):
        namespace = filters['namespace']
        namespace_entity = self.meta_namespace_repo.get(namespace)
        db_metadata_objects = self.db_api.metadef_object_get_all(
            self.context, namespace)
        return [self._format_metadef_object_from_db(metadata_object,
                                                    namespace_entity)
                for metadata_object in db_metadata_objects]

    def remove(self, metadata_object):
        try:
            self.db_api.metadef_object_delete(
                self.context,
                metadata_object.namespace.namespace,
                metadata_object.name
            )
        except (exception.NotFound, exception.Forbidden):
            msg = _("The specified metadata object %s could not be found")
            raise exception.NotFound(msg % metadata_object.name)

    def save(self, metadata_object):
        try:
            self.db_api.metadef_object_update(
                self.context, metadata_object.namespace.namespace,
                metadata_object.object_id,
                self._format_metadef_object_to_db(metadata_object))
        except exception.NotFound as e:
            raise exception.NotFound(explanation=e.msg)
        return metadata_object


class MetadefResourceTypeRepo(object):

    def __init__(self, context, db_api):
        self.context = context
        self.db_api = db_api
        self.meta_namespace_repo = MetadefNamespaceRepo(context, db_api)

    def _format_resource_type_from_db(self, resource_type, namespace):
        return subject.domain.MetadefResourceType(
            namespace=namespace,
            name=resource_type['name'],
            prefix=resource_type['prefix'],
            properties_target=resource_type['properties_target'],
            created_at=resource_type['created_at'],
            updated_at=resource_type['updated_at']
        )

    def _format_resource_type_to_db(self, resource_type):
        db_resource_type = {
            'name': resource_type.name,
            'prefix': resource_type.prefix,
            'properties_target': resource_type.properties_target
        }
        return db_resource_type

    def add(self, resource_type):
        self.db_api.metadef_resource_type_association_create(
            self.context, resource_type.namespace,
            self._format_resource_type_to_db(resource_type)
        )

    def get(self, resource_type, namespace):
        namespace_entity = self.meta_namespace_repo.get(namespace)
        db_resource_type = (
            self.db_api.
            metadef_resource_type_association_get(
                self.context,
                namespace,
                resource_type
            )
        )
        return self._format_resource_type_from_db(db_resource_type,
                                                  namespace_entity)

    def list(self, filters=None):
        namespace = filters['namespace']
        if namespace:
            namespace_entity = self.meta_namespace_repo.get(namespace)
            db_resource_types = (
                self.db_api.
                metadef_resource_type_association_get_all_by_namespace(
                    self.context,
                    namespace
                )
            )
            return [self._format_resource_type_from_db(resource_type,
                                                       namespace_entity)
                    for resource_type in db_resource_types]
        else:
            db_resource_types = (
                self.db_api.
                metadef_resource_type_get_all(self.context)
            )
            return [subject.domain.MetadefResourceType(
                namespace=None,
                name=resource_type['name'],
                prefix=None,
                properties_target=None,
                created_at=resource_type['created_at'],
                updated_at=resource_type['updated_at']
            ) for resource_type in db_resource_types]

    def remove(self, resource_type):
        try:
            self.db_api.metadef_resource_type_association_delete(
                self.context, resource_type.namespace.namespace,
                resource_type.name)

        except (exception.NotFound, exception.Forbidden):
            msg = _("The specified resource type %s could not be found ")
            raise exception.NotFound(msg % resource_type.name)


class MetadefPropertyRepo(object):

    def __init__(self, context, db_api):
        self.context = context
        self.db_api = db_api
        self.meta_namespace_repo = MetadefNamespaceRepo(context, db_api)

    def _format_metadef_property_from_db(
            self,
            property,
            namespace_entity):

        return subject.domain.MetadefProperty(
            namespace=namespace_entity,
            property_id=property['id'],
            name=property['name'],
            schema=property['json_schema']
        )

    def _format_metadef_property_to_db(self, property):

        db_metadata_object = {
            'name': property.name,
            'json_schema': property.schema
        }
        return db_metadata_object

    def add(self, property):
        self.db_api.metadef_property_create(
            self.context,
            property.namespace,
            self._format_metadef_property_to_db(property)
        )

    def get(self, namespace, property_name):
        try:
            namespace_entity = self.meta_namespace_repo.get(namespace)
            db_property_type = self.db_api.metadef_property_get(
                self.context,
                namespace,
                property_name
            )
        except (exception.NotFound, exception.Forbidden):
            msg = _('Could not find property %s') % property_name
            raise exception.NotFound(msg)
        return self._format_metadef_property_from_db(
            db_property_type, namespace_entity)

    def list(self, marker=None, limit=None, sort_key='created_at',
             sort_dir='desc', filters=None):
        namespace = filters['namespace']
        namespace_entity = self.meta_namespace_repo.get(namespace)

        db_properties = self.db_api.metadef_property_get_all(
            self.context, namespace)
        return (
            [self._format_metadef_property_from_db(
                property, namespace_entity) for property in db_properties]
        )

    def remove(self, property):
        try:
            self.db_api.metadef_property_delete(
                self.context, property.namespace.namespace, property.name)
        except (exception.NotFound, exception.Forbidden):
            msg = _("The specified property %s could not be found")
            raise exception.NotFound(msg % property.name)

    def save(self, property):
        try:
            self.db_api.metadef_property_update(
                self.context, property.namespace.namespace,
                property.property_id,
                self._format_metadef_property_to_db(property)
            )
        except exception.NotFound as e:
            raise exception.NotFound(explanation=e.msg)
        return property


class MetadefTagRepo(object):

    def __init__(self, context, db_api):
        self.context = context
        self.db_api = db_api
        self.meta_namespace_repo = MetadefNamespaceRepo(context, db_api)

    def _format_metadef_tag_from_db(self, metadata_tag,
                                    namespace_entity):
        return subject.domain.MetadefTag(
            namespace=namespace_entity,
            tag_id=metadata_tag['id'],
            name=metadata_tag['name'],
            created_at=metadata_tag['created_at'],
            updated_at=metadata_tag['updated_at']
        )

    def _format_metadef_tag_to_db(self, metadata_tag):
        db_metadata_tag = {
            'name': metadata_tag.name
        }
        return db_metadata_tag

    def add(self, metadata_tag):
        self.db_api.metadef_tag_create(
            self.context,
            metadata_tag.namespace,
            self._format_metadef_tag_to_db(metadata_tag)
        )

    def add_tags(self, metadata_tags):
        tag_list = []
        namespace = None
        for metadata_tag in metadata_tags:
            tag_list.append(self._format_metadef_tag_to_db(metadata_tag))
            if namespace is None:
                namespace = metadata_tag.namespace

        self.db_api.metadef_tag_create_tags(
            self.context, namespace, tag_list)

    def get(self, namespace, name):
        try:
            namespace_entity = self.meta_namespace_repo.get(namespace)
            db_metadata_tag = self.db_api.metadef_tag_get(
                self.context,
                namespace,
                name)
        except (exception.NotFound, exception.Forbidden):
            msg = _('Could not find metadata tag %s') % name
            raise exception.NotFound(msg)
        return self._format_metadef_tag_from_db(db_metadata_tag,
                                                namespace_entity)

    def list(self, marker=None, limit=None, sort_key='created_at',
             sort_dir='desc', filters=None):
        namespace = filters['namespace']
        namespace_entity = self.meta_namespace_repo.get(namespace)

        db_metadata_tag = self.db_api.metadef_tag_get_all(
            self.context, namespace, filters, marker, limit, sort_key,
            sort_dir)

        return [self._format_metadef_tag_from_db(metadata_tag,
                                                 namespace_entity)
                for metadata_tag in db_metadata_tag]

    def remove(self, metadata_tag):
        try:
            self.db_api.metadef_tag_delete(
                self.context,
                metadata_tag.namespace.namespace,
                metadata_tag.name
            )
        except (exception.NotFound, exception.Forbidden):
            msg = _("The specified metadata tag %s could not be found")
            raise exception.NotFound(msg % metadata_tag.name)

    def save(self, metadata_tag):
        try:
            self.db_api.metadef_tag_update(
                self.context, metadata_tag.namespace.namespace,
                metadata_tag.tag_id,
                self._format_metadef_tag_to_db(metadata_tag))
        except exception.NotFound as e:
            raise exception.NotFound(explanation=e.msg)
        return metadata_tag