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

from oslo_config import cfg
from oslo_serialization import jsonutils
# NOTE(jokke): simplified transition to py3, behaves like py2 xrange
from six.moves import range

from subject.tests.integration.v2 import base

CONF = cfg.CONF


class TestPropertyQuotaViolations(base.ApiTest):
    def __init__(self, *args, **kwargs):
        super(TestPropertyQuotaViolations, self).__init__(*args, **kwargs)
        self.api_flavor = 'noauth'
        self.registry_flavor = 'fakeauth'

    def _headers(self, custom_headers=None):
        base_headers = {
            'X-Identity-Status': 'Confirmed',
            'X-Auth-Token': '932c5c84-02ac-4fe5-a9ba-620af0e2bb96',
            'X-User-Id': 'f9a41d13-0c13-47e9-bee2-ce4e8bfe958e',
            'X-Tenant-Id': "foo",
            'X-Roles': 'member',
        }
        base_headers.update(custom_headers or {})
        return base_headers

    def _get(self, subject_id=""):
        path = ('/v1/subjects/%s' % subject_id).rstrip('/')
        rsp, content = self.http.request(path, 'GET', headers=self._headers())
        self.assertEqual(200, rsp.status)
        content = jsonutils.loads(content)
        return content

    def _create_subject(self, body):
        path = '/v1/subjects'
        headers = self._headers({'content-type': 'application/json'})
        rsp, content = self.http.request(path, 'POST', headers=headers,
                                         body=jsonutils.dumps(body))
        self.assertEqual(201, rsp.status)
        return jsonutils.loads(content)

    def _patch(self, subject_id, body, expected_status):
        path = '/v1/subjects/%s' % subject_id
        media_type = 'application/openstack-subjects-v1.1-json-patch'
        headers = self._headers({'content-type': media_type})
        rsp, content = self.http.request(path, 'PATCH', headers=headers,
                                         body=jsonutils.dumps(body))
        self.assertEqual(expected_status, rsp.status, content)
        return content

    def test_property_ops_when_quota_violated(self):
        # Subject list must be empty to begin with
        subject_list = self._get()['subjects']
        self.assertEqual(0, len(subject_list))

        orig_property_quota = 10
        CONF.set_override('subject_property_quota', orig_property_quota,
                          enforce_type=True)

        # Create an subject (with deployer-defined properties)
        req_body = {'name': 'testimg',
                    'disk_format': 'aki',
                    'container_format': 'aki'}
        for i in range(orig_property_quota):
            req_body['k_%d' % i] = 'v_%d' % i
        subject = self._create_subject(req_body)
        subject_id = subject['id']
        for i in range(orig_property_quota):
            self.assertEqual('v_%d' % i, subject['k_%d' % i])

        # Now reduce property quota. We should be allowed to modify/delete
        # existing properties (even if the result still exceeds property quota)
        # but not add new properties nor replace existing properties with new
        # properties (as long as we're over the quota)
        self.config(subject_property_quota=2)

        patch_body = [{'op': 'replace', 'path': '/k_4', 'value': 'v_4.new'}]
        subject = jsonutils.loads(self._patch(subject_id, patch_body, 200))
        self.assertEqual('v_4.new', subject['k_4'])

        patch_body = [{'op': 'remove', 'path': '/k_7'}]
        subject = jsonutils.loads(self._patch(subject_id, patch_body, 200))
        self.assertNotIn('k_7', subject)

        patch_body = [{'op': 'add', 'path': '/k_100', 'value': 'v_100'}]
        self._patch(subject_id, patch_body, 413)
        subject = self._get(subject_id)
        self.assertNotIn('k_100', subject)

        patch_body = [
            {'op': 'remove', 'path': '/k_5'},
            {'op': 'add', 'path': '/k_100', 'value': 'v_100'},
        ]
        self._patch(subject_id, patch_body, 413)
        subject = self._get(subject_id)
        self.assertNotIn('k_100', subject)
        self.assertIn('k_5', subject)

        # temporary violations to property quota should be allowed as long as
        # it's within one PATCH request and the end result does not violate
        # quotas.
        patch_body = [{'op': 'add', 'path': '/k_100', 'value': 'v_100'},
                      {'op': 'add', 'path': '/k_99', 'value': 'v_99'}]
        to_rm = ['k_%d' % i for i in range(orig_property_quota) if i != 7]
        patch_body.extend([{'op': 'remove', 'path': '/%s' % k} for k in to_rm])
        subject = jsonutils.loads(self._patch(subject_id, patch_body, 200))
        self.assertEqual('v_99', subject['k_99'])
        self.assertEqual('v_100', subject['k_100'])
        for k in to_rm:
            self.assertNotIn(k, subject)
