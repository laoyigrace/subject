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

"""
Simple client class to speak with any RESTful service that implements
the Glance Registry API
"""

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
import six

from subject.common.client import BaseClient
from subject.common import crypt
from subject.common import exception
from subject.i18n import _LE
from subject.registry.api.v1 import subjects

LOG = logging.getLogger(__name__)


class RegistryClient(BaseClient):

    """A client for the Registry subject metadata service."""

    DEFAULT_PORT = 9191

    def __init__(self, host=None, port=None, metadata_encryption_key=None,
                 identity_headers=None, **kwargs):
        """
        :param metadata_encryption_key: Key used to encrypt 'location' metadata
        """
        self.metadata_encryption_key = metadata_encryption_key
        # NOTE (dprince): by default base client overwrites host and port
        # settings when using keystone. configure_via_auth=False disables
        # this behaviour to ensure we still send requests to the Registry API
        self.identity_headers = identity_headers
        # store available passed request id for do_request call
        self._passed_request_id = kwargs.pop('request_id', None)
        BaseClient.__init__(self, host, port, configure_via_auth=False,
                            **kwargs)

    def decrypt_metadata(self, subject_metadata):
        if self.metadata_encryption_key:
            if subject_metadata.get('location'):
                location = crypt.urlsafe_decrypt(self.metadata_encryption_key,
                                                 subject_metadata['location'])
                subject_metadata['location'] = location
            if subject_metadata.get('location_data'):
                ld = []
                for loc in subject_metadata['location_data']:
                    url = crypt.urlsafe_decrypt(self.metadata_encryption_key,
                                                loc['url'])
                    ld.append({'id': loc['id'], 'url': url,
                               'metadata': loc['metadata'],
                               'status': loc['status']})
                subject_metadata['location_data'] = ld
        return subject_metadata

    def encrypt_metadata(self, subject_metadata):
        if self.metadata_encryption_key:
            location_url = subject_metadata.get('location')
            if location_url:
                location = crypt.urlsafe_encrypt(self.metadata_encryption_key,
                                                 location_url,
                                                 64)
                subject_metadata['location'] = location
            if subject_metadata.get('location_data'):
                ld = []
                for loc in subject_metadata['location_data']:
                    if loc['url'] == location_url:
                        url = location
                    else:
                        url = crypt.urlsafe_encrypt(
                            self.metadata_encryption_key, loc['url'], 64)
                    ld.append({'url': url, 'metadata': loc['metadata'],
                               'status': loc['status'],
                               # NOTE(zhiyan): New location has no ID field.
                               'id': loc.get('id')})
                subject_metadata['location_data'] = ld
        return subject_metadata

    def get_subjects(self, **kwargs):
        """
        Returns a list of subject id/name mappings from Registry

        :param filters: dict of keys & expected values to filter results
        :param marker: subject id after which to start page
        :param limit: max number of subjects to return
        :param sort_key: results will be ordered by this subject attribute
        :param sort_dir: direction in which to order results (asc, desc)
        """
        params = self._extract_params(kwargs, subjects.SUPPORTED_PARAMS)
        res = self.do_request("GET", "/subjects", params=params)
        subject_list = jsonutils.loads(res.read())['subjects']
        for subject in subject_list:
            subject = self.decrypt_metadata(subject)
        return subject_list

    def do_request(self, method, action, **kwargs):
        try:
            kwargs['headers'] = kwargs.get('headers', {})
            kwargs['headers'].update(self.identity_headers or {})
            if self._passed_request_id:
                request_id = self._passed_request_id
                if six.PY3 and isinstance(request_id, bytes):
                    request_id = request_id.decode('utf-8')
                kwargs['headers']['X-Openstack-Request-ID'] = request_id
            res = super(RegistryClient, self).do_request(method,
                                                         action,
                                                         **kwargs)
            status = res.status
            request_id = res.getheader('x-openstack-request-id')
            if six.PY3 and isinstance(request_id, bytes):
                request_id = request_id.decode('utf-8')
            LOG.debug("Registry request %(method)s %(action)s HTTP %(status)s"
                      " request id %(request_id)s",
                      {'method': method, 'action': action,
                       'status': status, 'request_id': request_id})

        # a 404 condition is not fatal, we shouldn't log at a fatal
        # level for it.
        except exception.NotFound:
            raise

        # The following exception logging should only really be used
        # in extreme and unexpected cases.
        except Exception as exc:
            with excutils.save_and_reraise_exception():
                exc_name = exc.__class__.__name__
                LOG.exception(_LE("Registry client request %(method)s "
                                  "%(action)s raised %(exc_name)s"),
                              {'method': method, 'action': action,
                               'exc_name': exc_name})
        return res

    def get_subjects_detailed(self, **kwargs):
        """
        Returns a list of detailed subject data mappings from Registry

        :param filters: dict of keys & expected values to filter results
        :param marker: subject id after which to start page
        :param limit: max number of subjects to return
        :param sort_key: results will be ordered by this subject attribute
        :param sort_dir: direction in which to order results (asc, desc)
        """
        params = self._extract_params(kwargs, subjects.SUPPORTED_PARAMS)
        res = self.do_request("GET", "/subjects/detail", params=params)
        subject_list = jsonutils.loads(res.read())['subjects']
        for subject in subject_list:
            subject = self.decrypt_metadata(subject)
        return subject_list

    def get_subject(self, subject_id):
        """Returns a mapping of subject metadata from Registry."""
        res = self.do_request("GET", "/subjects/%s" % subject_id)
        data = jsonutils.loads(res.read())['subject']
        return self.decrypt_metadata(data)

    def add_subject(self, subject_metadata):
        """
        Tells registry about an subject's metadata
        """
        headers = {
            'Content-Type': 'application/json',
        }

        if 'subject' not in subject_metadata:
            subject_metadata = dict(subject=subject_metadata)

        encrypted_metadata = self.encrypt_metadata(subject_metadata['subject'])
        subject_metadata['subject'] = encrypted_metadata
        body = jsonutils.dump_as_bytes(subject_metadata)

        res = self.do_request("POST", "/subjects", body=body, headers=headers)
        # Registry returns a JSONified dict(subject=subject_info)
        data = jsonutils.loads(res.read())
        subject = data['subject']
        return self.decrypt_metadata(subject)

    def update_subject(self, subject_id, subject_metadata, purge_props=False,
                     from_state=None):
        """
        Updates Registry's information about an subject
        """
        if 'subject' not in subject_metadata:
            subject_metadata = dict(subject=subject_metadata)

        encrypted_metadata = self.encrypt_metadata(subject_metadata['subject'])
        subject_metadata['subject'] = encrypted_metadata
        subject_metadata['from_state'] = from_state
        body = jsonutils.dump_as_bytes(subject_metadata)

        headers = {
            'Content-Type': 'application/json',
        }

        if purge_props:
            headers["X-Glance-Registry-Purge-Props"] = "true"

        res = self.do_request("PUT", "/subjects/%s" % subject_id, body=body,
                              headers=headers)
        data = jsonutils.loads(res.read())
        subject = data['subject']
        return self.decrypt_metadata(subject)

    def delete_subject(self, subject_id):
        """
        Deletes Registry's information about an subject
        """
        res = self.do_request("DELETE", "/subjects/%s" % subject_id)
        data = jsonutils.loads(res.read())
        subject = data['subject']
        return subject

    def get_subject_members(self, subject_id):
        """Return a list of membership associations from Registry."""
        res = self.do_request("GET", "/subjects/%s/members" % subject_id)
        data = jsonutils.loads(res.read())['members']
        return data

    def get_member_subjects(self, member_id):
        """Return a list of membership associations from Registry."""
        res = self.do_request("GET", "/shared-subjects/%s" % member_id)
        data = jsonutils.loads(res.read())['shared_subjects']
        return data

    def replace_members(self, subject_id, member_data):
        """Replace registry's information about subject membership."""
        if isinstance(member_data, (list, tuple)):
            member_data = dict(memberships=list(member_data))
        elif (isinstance(member_data, dict) and
              'memberships' not in member_data):
            member_data = dict(memberships=[member_data])

        body = jsonutils.dump_as_bytes(member_data)

        headers = {'Content-Type': 'application/json', }

        res = self.do_request("PUT", "/subjects/%s/members" % subject_id,
                              body=body, headers=headers)
        return self.get_status_code(res) == 204

    def add_member(self, subject_id, member_id, can_share=None):
        """Add to registry's information about subject membership."""
        body = None
        headers = {}
        # Build up a body if can_share is specified
        if can_share is not None:
            body = jsonutils.dump_as_bytes(
                dict(member=dict(can_share=can_share)))
            headers['Content-Type'] = 'application/json'

        url = "/subjects/%s/members/%s" % (subject_id, member_id)
        res = self.do_request("PUT", url, body=body,
                              headers=headers)
        return self.get_status_code(res) == 204

    def delete_member(self, subject_id, member_id):
        """Delete registry's information about subject membership."""
        res = self.do_request("DELETE", "/subjects/%s/members/%s" %
                              (subject_id, member_id))
        return self.get_status_code(res) == 204
