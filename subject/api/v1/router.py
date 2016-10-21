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

from subject.api.v1 import subject_data
from subject.api.v1 import subjects
from subject.common import wsgi


class API(wsgi.Router):

    """WSGI router for Glance v1 API requests."""

    def __init__(self, mapper):
        custom_subject_properties = subjects.load_custom_properties()
        reject_method_resource = wsgi.Resource(wsgi.RejectMethodController())

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

        super(API, self).__init__(mapper)
