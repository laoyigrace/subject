# Copyright 2012 OpenStack Foundation.
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

from subject.api.v2 import subject_actions
from subject.api.v2 import subject_data
from subject.api.v2 import subject_members
from subject.api.v2 import subject_tags
from subject.api.v2 import subjects
from subject.api.v2 import metadef_namespaces
from subject.api.v2 import metadef_objects
from subject.api.v2 import metadef_properties
from subject.api.v2 import metadef_resource_types
from subject.api.v2 import metadef_tags
from subject.api.v2 import schemas
from subject.api.v2 import tasks
from subject.common import wsgi


class API(wsgi.Router):

    """WSGI router for Glance v1 API requests."""

    def __init__(self, mapper):
        custom_subject_properties = subjects.load_custom_properties()
        reject_method_resource = wsgi.Resource(wsgi.RejectMethodController())

        schemas_resource = schemas.create_resource(custom_subject_properties)
        mapper.connect('/schemas/subject',
                       controller=schemas_resource,
                       action='subject',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/subject',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')
        mapper.connect('/schemas/subjects',
                       controller=schemas_resource,
                       action='subjects',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/subjects',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')
        mapper.connect('/schemas/member',
                       controller=schemas_resource,
                       action='member',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/member',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/members',
                       controller=schemas_resource,
                       action='members',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/members',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/task',
                       controller=schemas_resource,
                       action='task',
                       conditions={'method': ['GET']})
        mapper.connect('/schemas/task',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')
        mapper.connect('/schemas/tasks',
                       controller=schemas_resource,
                       action='tasks',
                       conditions={'method': ['GET']})
        mapper.connect('/schemas/tasks',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/metadefs/namespace',
                       controller=schemas_resource,
                       action='metadef_namespace',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/metadefs/namespace',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/metadefs/namespaces',
                       controller=schemas_resource,
                       action='metadef_namespaces',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/metadefs/namespaces',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/metadefs/resource_type',
                       controller=schemas_resource,
                       action='metadef_resource_type',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/metadefs/resource_type',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/metadefs/resource_types',
                       controller=schemas_resource,
                       action='metadef_resource_types',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/metadefs/resource_types',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/metadefs/property',
                       controller=schemas_resource,
                       action='metadef_property',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/metadefs/property',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/metadefs/properties',
                       controller=schemas_resource,
                       action='metadef_properties',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/metadefs/properties',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/metadefs/object',
                       controller=schemas_resource,
                       action='metadef_object',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/metadefs/object',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/metadefs/objects',
                       controller=schemas_resource,
                       action='metadef_objects',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/metadefs/objects',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/metadefs/tag',
                       controller=schemas_resource,
                       action='metadef_tag',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/metadefs/tag',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/schemas/metadefs/tags',
                       controller=schemas_resource,
                       action='metadef_tags',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/schemas/metadefs/tags',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        # Metadef resource types
        metadef_resource_types_resource = (
            metadef_resource_types.create_resource())

        mapper.connect('/metadefs/resource_types',
                       controller=metadef_resource_types_resource,
                       action='index',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/metadefs/resource_types',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET')

        mapper.connect('/metadefs/namespaces/{namespace}/resource_types',
                       controller=metadef_resource_types_resource,
                       action='show',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/metadefs/namespaces/{namespace}/resource_types',
                       controller=metadef_resource_types_resource,
                       action='create',
                       conditions={'method': ['POST']})
        mapper.connect('/metadefs/namespaces/{namespace}/resource_types',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, POST')

        mapper.connect('/metadefs/namespaces/{namespace}/resource_types/'
                       '{resource_type}',
                       controller=metadef_resource_types_resource,
                       action='delete',
                       conditions={'method': ['DELETE']},
                       body_reject=True)
        mapper.connect('/metadefs/namespaces/{namespace}/resource_types/'
                       '{resource_type}',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='DELETE')

        # Metadef Namespaces
        metadef_namespace_resource = metadef_namespaces.create_resource()
        mapper.connect('/metadefs/namespaces',
                       controller=metadef_namespace_resource,
                       action='index',
                       conditions={'method': ['GET']})
        mapper.connect('/metadefs/namespaces',
                       controller=metadef_namespace_resource,
                       action='create',
                       conditions={'method': ['POST']})
        mapper.connect('/metadefs/namespaces',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, POST')

        mapper.connect('/metadefs/namespaces/{namespace}',
                       controller=metadef_namespace_resource,
                       action='show',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/metadefs/namespaces/{namespace}',
                       controller=metadef_namespace_resource,
                       action='update',
                       conditions={'method': ['PUT']})
        mapper.connect('/metadefs/namespaces/{namespace}',
                       controller=metadef_namespace_resource,
                       action='delete',
                       conditions={'method': ['DELETE']},
                       body_reject=True)
        mapper.connect('/metadefs/namespaces/{namespace}',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, PUT, DELETE')

        # Metadef namespace properties
        metadef_properties_resource = metadef_properties.create_resource()
        mapper.connect('/metadefs/namespaces/{namespace}/properties',
                       controller=metadef_properties_resource,
                       action='index',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/metadefs/namespaces/{namespace}/properties',
                       controller=metadef_properties_resource,
                       action='create',
                       conditions={'method': ['POST']})
        mapper.connect('/metadefs/namespaces/{namespace}/properties',
                       controller=metadef_namespace_resource,
                       action='delete_properties',
                       conditions={'method': ['DELETE']})
        mapper.connect('/metadefs/namespaces/{namespace}/properties',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, POST, DELETE')

        mapper.connect('/metadefs/namespaces/{namespace}/properties/{'
                       'property_name}',
                       controller=metadef_properties_resource,
                       action='show',
                       conditions={'method': ['GET']})
        mapper.connect('/metadefs/namespaces/{namespace}/properties/{'
                       'property_name}',
                       controller=metadef_properties_resource,
                       action='update',
                       conditions={'method': ['PUT']})
        mapper.connect('/metadefs/namespaces/{namespace}/properties/{'
                       'property_name}',
                       controller=metadef_properties_resource,
                       action='delete',
                       conditions={'method': ['DELETE']})
        mapper.connect('/metadefs/namespaces/{namespace}/properties/{'
                       'property_name}',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, PUT, DELETE')

        # Metadef objects
        metadef_objects_resource = metadef_objects.create_resource()
        mapper.connect('/metadefs/namespaces/{namespace}/objects',
                       controller=metadef_objects_resource,
                       action='index',
                       conditions={'method': ['GET']})
        mapper.connect('/metadefs/namespaces/{namespace}/objects',
                       controller=metadef_objects_resource,
                       action='create',
                       conditions={'method': ['POST']})
        mapper.connect('/metadefs/namespaces/{namespace}/objects',
                       controller=metadef_namespace_resource,
                       action='delete_objects',
                       conditions={'method': ['DELETE']})
        mapper.connect('/metadefs/namespaces/{namespace}/objects',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, POST, DELETE')

        mapper.connect('/metadefs/namespaces/{namespace}/objects/{'
                       'object_name}',
                       controller=metadef_objects_resource,
                       action='show',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/metadefs/namespaces/{namespace}/objects/{'
                       'object_name}',
                       controller=metadef_objects_resource,
                       action='update',
                       conditions={'method': ['PUT']})
        mapper.connect('/metadefs/namespaces/{namespace}/objects/{'
                       'object_name}',
                       controller=metadef_objects_resource,
                       action='delete',
                       conditions={'method': ['DELETE']},
                       body_reject=True)
        mapper.connect('/metadefs/namespaces/{namespace}/objects/{'
                       'object_name}',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, PUT, DELETE')

        # Metadef tags
        metadef_tags_resource = metadef_tags.create_resource()
        mapper.connect('/metadefs/namespaces/{namespace}/tags',
                       controller=metadef_tags_resource,
                       action='index',
                       conditions={'method': ['GET']})
        mapper.connect('/metadefs/namespaces/{namespace}/tags',
                       controller=metadef_tags_resource,
                       action='create_tags',
                       conditions={'method': ['POST']})
        mapper.connect('/metadefs/namespaces/{namespace}/tags',
                       controller=metadef_namespace_resource,
                       action='delete_tags',
                       conditions={'method': ['DELETE']})
        mapper.connect('/metadefs/namespaces/{namespace}/tags',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, POST, DELETE')

        mapper.connect('/metadefs/namespaces/{namespace}/tags/{tag_name}',
                       controller=metadef_tags_resource,
                       action='show',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/metadefs/namespaces/{namespace}/tags/{tag_name}',
                       controller=metadef_tags_resource,
                       action='create',
                       conditions={'method': ['POST']},
                       body_reject=True)
        mapper.connect('/metadefs/namespaces/{namespace}/tags/{tag_name}',
                       controller=metadef_tags_resource,
                       action='update',
                       conditions={'method': ['PUT']})
        mapper.connect('/metadefs/namespaces/{namespace}/tags/{tag_name}',
                       controller=metadef_tags_resource,
                       action='delete',
                       conditions={'method': ['DELETE']},
                       body_reject=True)
        mapper.connect('/metadefs/namespaces/{namespace}/tags/{tag_name}',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, POST, PUT, DELETE')

        subjects_resource = subjects.create_resource(custom_subject_properties)
        mapper.connect('/subjects',
                       controller=subjects_resource,
                       action='index',
                       conditions={'method': ['GET']})
        mapper.connect('/subjects',
                       controller=subjects_resource,
                       action='create',
                       conditions={'method': ['POST']})
        mapper.connect('/subjects',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, POST')

        mapper.connect('/subjects/{subject_id}',
                       controller=subjects_resource,
                       action='update',
                       conditions={'method': ['PATCH']})
        mapper.connect('/subjects/{subject_id}',
                       controller=subjects_resource,
                       action='show',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/subjects/{subject_id}',
                       controller=subjects_resource,
                       action='delete',
                       conditions={'method': ['DELETE']},
                       body_reject=True)
        mapper.connect('/subjects/{subject_id}',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, PATCH, DELETE')

        subject_actions_resource = subject_actions.create_resource()
        mapper.connect('/subjects/{subject_id}/actions/deactivate',
                       controller=subject_actions_resource,
                       action='deactivate',
                       conditions={'method': ['POST']},
                       body_reject=True)
        mapper.connect('/subjects/{subject_id}/actions/reactivate',
                       controller=subject_actions_resource,
                       action='reactivate',
                       conditions={'method': ['POST']},
                       body_reject=True)
        mapper.connect('/subjects/{subject_id}/actions/deactivate',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='POST')
        mapper.connect('/subjects/{subject_id}/actions/reactivate',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='POST')

        subject_data_resource = subject_data.create_resource()
        mapper.connect('/subjects/{subject_id}/file',
                       controller=subject_data_resource,
                       action='download',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/subjects/{subject_id}/file',
                       controller=subject_data_resource,
                       action='upload',
                       conditions={'method': ['PUT']})
        mapper.connect('/subjects/{subject_id}/file',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, PUT')

        subject_tags_resource = subject_tags.create_resource()
        mapper.connect('/subjects/{subject_id}/tags/{tag_value}',
                       controller=subject_tags_resource,
                       action='update',
                       conditions={'method': ['PUT']},
                       body_reject=True)
        mapper.connect('/subjects/{subject_id}/tags/{tag_value}',
                       controller=subject_tags_resource,
                       action='delete',
                       conditions={'method': ['DELETE']},
                       body_reject=True)
        mapper.connect('/subjects/{subject_id}/tags/{tag_value}',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='PUT, DELETE')

        subject_members_resource = subject_members.create_resource()
        mapper.connect('/subjects/{subject_id}/members',
                       controller=subject_members_resource,
                       action='index',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/subjects/{subject_id}/members',
                       controller=subject_members_resource,
                       action='create',
                       conditions={'method': ['POST']})
        mapper.connect('/subjects/{subject_id}/members',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, POST')

        mapper.connect('/subjects/{subject_id}/members/{member_id}',
                       controller=subject_members_resource,
                       action='show',
                       conditions={'method': ['GET']},
                       body_reject=True)
        mapper.connect('/subjects/{subject_id}/members/{member_id}',
                       controller=subject_members_resource,
                       action='update',
                       conditions={'method': ['PUT']})
        mapper.connect('/subjects/{subject_id}/members/{member_id}',
                       controller=subject_members_resource,
                       action='delete',
                       conditions={'method': ['DELETE']},
                       body_reject=True)
        mapper.connect('/subjects/{subject_id}/members/{member_id}',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, PUT, DELETE')

        tasks_resource = tasks.create_resource()
        mapper.connect('/tasks',
                       controller=tasks_resource,
                       action='create',
                       conditions={'method': ['POST']})
        mapper.connect('/tasks',
                       controller=tasks_resource,
                       action='index',
                       conditions={'method': ['GET']})
        mapper.connect('/tasks',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, POST')

        mapper.connect('/tasks/{task_id}',
                       controller=tasks_resource,
                       action='get',
                       conditions={'method': ['GET']})
        mapper.connect('/tasks/{task_id}',
                       controller=tasks_resource,
                       action='delete',
                       conditions={'method': ['DELETE']})
        mapper.connect('/tasks/{task_id}',
                       controller=reject_method_resource,
                       action='reject',
                       allowed_methods='GET, DELETE')

        super(API, self).__init__(mapper)
