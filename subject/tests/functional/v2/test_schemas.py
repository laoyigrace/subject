# Copyright 2012 OpenStack Foundation
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

from oslo_serialization import jsonutils
import requests

from subject.tests import functional


class TestSchemas(functional.FunctionalTest):

    def setUp(self):
        super(TestSchemas, self).setUp()
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

    def test_resource(self):
        # Ensure the subject link works and custom properties are loaded
        path = 'http://%s:%d/v1/schemas/subject' % ('127.0.0.1', self.api_port)
        response = requests.get(path)
        self.assertEqual(200, response.status_code)
        subject_schema = jsonutils.loads(response.text)
        expected = set([
            'id',
            'name',
            'visibility',
            'checksum',
            'created_at',
            'updated_at',
            'tags',
            'size',
            'virtual_size',
            'owner',
            'container_format',
            'disk_format',
            'self',
            'file',
            'status',
            'schema',
            'direct_url',
            'locations',
            'min_ram',
            'min_disk',
            'protected',
        ])
        self.assertEqual(expected, set(subject_schema['properties'].keys()))

        # Ensure the subjects link works and agrees with the subject schema
        path = 'http://%s:%d/v1/schemas/subjects' % ('127.0.0.1', self.api_port)
        response = requests.get(path)
        self.assertEqual(200, response.status_code)
        subjects_schema = jsonutils.loads(response.text)
        item_schema = subjects_schema['properties']['subjects']['items']
        self.assertEqual(item_schema, subject_schema)

        self.stop_servers()
