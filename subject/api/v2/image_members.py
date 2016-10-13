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

import copy

import glance_store
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
import six
import webob

from subject.api import policy
from subject.common import exception
from subject.common import timeutils
from subject.common import utils
from subject.common import wsgi
import subject.db
import subject.gateway
from subject.i18n import _
import subject.notifier
import subject.schema


LOG = logging.getLogger(__name__)


class ImageMembersController(object):
    def __init__(self, db_api=None, policy_enforcer=None, notifier=None,
                 store_api=None):
        self.db_api = db_api or subject.db.get_api()
        self.policy = policy_enforcer or policy.Enforcer()
        self.notifier = notifier or subject.notifier.Notifier()
        self.store_api = store_api or glance_store
        self.gateway = subject.gateway.Gateway(self.db_api, self.store_api,
                                               self.notifier, self.policy)

    def _get_member_repo(self, req, subject):
        try:
            # For public subjects, a forbidden exception with message
            # "Public subjects do not have members" is thrown.
            return self.gateway.get_member_repo(subject, req.context)
        except exception.Forbidden as e:
            msg = (_("Error fetching members of subject %(subject_id)s: "
                     "%(inner_msg)s") % {"subject_id": subject.subject_id,
                                         "inner_msg": e.msg})
            LOG.warning(msg)
            raise webob.exc.HTTPForbidden(explanation=msg)

    def _lookup_subject(self, req, subject_id):
        subject_repo = self.gateway.get_repo(req.context)
        try:
            return subject_repo.get(subject_id)
        except (exception.NotFound):
            msg = _("Subject %s not found.") % subject_id
            LOG.warning(msg)
            raise webob.exc.HTTPNotFound(explanation=msg)
        except exception.Forbidden:
            msg = _("You are not authorized to lookup subject %s.") % subject_id
            LOG.warning(msg)
            raise webob.exc.HTTPForbidden(explanation=msg)

    def _lookup_member(self, req, subject, member_id):
        member_repo = self._get_member_repo(req, subject)
        try:
            return member_repo.get(member_id)
        except (exception.NotFound):
            msg = (_("%(m_id)s not found in the member list of the subject "
                     "%(i_id)s.") % {"m_id": member_id,
                                     "i_id": subject.subject_id})
            LOG.warning(msg)
            raise webob.exc.HTTPNotFound(explanation=msg)
        except exception.Forbidden:
            msg = (_("You are not authorized to lookup the members of the "
                     "subject %s.") % subject.subject_id)
            LOG.warning(msg)
            raise webob.exc.HTTPForbidden(explanation=msg)

    @utils.mutating
    def create(self, req, subject_id, member_id):
        """
        Adds a membership to the subject.
        :param req: the Request object coming from the wsgi layer
        :param subject_id: the subject identifier
        :param member_id: the member identifier
        :returns: The response body is a mapping of the following form

        .. code-block:: json

            {'member_id': <MEMBER>,
             'subject_id': <IMAGE>,
             'status': <MEMBER_STATUS>
             'created_at': ..,
             'updated_at': ..}

        """
        subject = self._lookup_subject(req, subject_id)
        member_repo = self._get_member_repo(req, subject)
        subject_member_factory = self.gateway.get_subject_member_factory(
            req.context)
        try:
            new_member = subject_member_factory.new_subject_member(subject,
                                                               member_id)
            member_repo.add(new_member)
            return new_member
        except exception.Forbidden:
            msg = _("Not allowed to create members for subject %s.") % subject_id
            LOG.warning(msg)
            raise webob.exc.HTTPForbidden(explanation=msg)
        except exception.Duplicate:
            msg = _("Member %(member_id)s is duplicated for subject "
                    "%(subject_id)s") % {"member_id": member_id,
                                       "subject_id": subject_id}
            LOG.warning(msg)
            raise webob.exc.HTTPConflict(explanation=msg)
        except exception.ImageMemberLimitExceeded as e:
            msg = (_("Subject member limit exceeded for subject %(id)s: %(e)s:")
                   % {"id": subject_id,
                      "e": encodeutils.exception_to_unicode(e)})
            LOG.warning(msg)
            raise webob.exc.HTTPRequestEntityTooLarge(explanation=msg)

    @utils.mutating
    def update(self, req, subject_id, member_id, status):
        """
        Adds a membership to the subject.
        :param req: the Request object coming from the wsgi layer
        :param subject_id: the subject identifier
        :param member_id: the member identifier
        :returns: The response body is a mapping of the following form

        .. code-block:: json

            {'member_id': <MEMBER>,
             'subject_id': <IMAGE>,
             'status': <MEMBER_STATUS>,
             'created_at': ..,
             'updated_at': ..}

        """
        subject = self._lookup_subject(req, subject_id)
        member_repo = self._get_member_repo(req, subject)
        member = self._lookup_member(req, subject, member_id)
        try:
            member.status = status
            member_repo.save(member)
            return member
        except exception.Forbidden:
            msg = _("Not allowed to update members for subject %s.") % subject_id
            LOG.warning(msg)
            raise webob.exc.HTTPForbidden(explanation=msg)
        except ValueError as e:
            msg = (_("Incorrect request: %s")
                   % encodeutils.exception_to_unicode(e))
            LOG.warning(msg)
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def index(self, req, subject_id):
        """
        Return a list of dictionaries indicating the members of the
        subject, i.e., those tenants the subject is shared with.

        :param req: the Request object coming from the wsgi layer
        :param subject_id: The subject identifier
        :returns: The response body is a mapping of the following form

        .. code-block:: json

            {'members': [
                {'member_id': <MEMBER>,
                 'subject_id': <IMAGE>,
                 'status': <MEMBER_STATUS>,
                 'created_at': ..,
                 'updated_at': ..}, ..
            ]}

        """
        subject = self._lookup_subject(req, subject_id)
        member_repo = self._get_member_repo(req, subject)
        members = []
        try:
            for member in member_repo.list():
                members.append(member)
        except exception.Forbidden:
            msg = _("Not allowed to list members for subject %s.") % subject_id
            LOG.warning(msg)
            raise webob.exc.HTTPForbidden(explanation=msg)
        return dict(members=members)

    def show(self, req, subject_id, member_id):
        """
        Returns the membership of the tenant wrt to the subject_id specified.

        :param req: the Request object coming from the wsgi layer
        :param subject_id: The subject identifier
        :returns: The response body is a mapping of the following form

        .. code-block:: json

            {'member_id': <MEMBER>,
             'subject_id': <IMAGE>,
             'status': <MEMBER_STATUS>
             'created_at': ..,
             'updated_at': ..}

        """
        try:
            subject = self._lookup_subject(req, subject_id)
            return self._lookup_member(req, subject, member_id)
        except webob.exc.HTTPForbidden as e:
            # Convert Forbidden to NotFound to prevent information
            # leakage.
            raise webob.exc.HTTPNotFound(explanation=e.explanation)

    @utils.mutating
    def delete(self, req, subject_id, member_id):
        """
        Removes a membership from the subject.
        """
        subject = self._lookup_subject(req, subject_id)
        member_repo = self._get_member_repo(req, subject)
        member = self._lookup_member(req, subject, member_id)
        try:
            member_repo.remove(member)
            return webob.Response(body='', status=204)
        except exception.Forbidden:
            msg = _("Not allowed to delete members for subject %s.") % subject_id
            LOG.warning(msg)
            raise webob.exc.HTTPForbidden(explanation=msg)


class RequestDeserializer(wsgi.JSONRequestDeserializer):

    def __init__(self):
        super(RequestDeserializer, self).__init__()

    def _get_request_body(self, request):
        output = super(RequestDeserializer, self).default(request)
        if 'body' not in output:
            msg = _('Body expected in request.')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return output['body']

    def create(self, request):
        body = self._get_request_body(request)
        try:
            member_id = body['member']
            if not member_id:
                raise ValueError()
        except KeyError:
            msg = _("Member to be added not specified")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except ValueError:
            msg = _("Member can't be empty")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except TypeError:
            msg = _('Expected a member in the form: '
                    '{"member": "subject_id"}')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return dict(member_id=member_id)

    def update(self, request):
        body = self._get_request_body(request)
        try:
            status = body['status']
        except KeyError:
            msg = _("Status not specified")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except TypeError:
            msg = _('Expected a status in the form: '
                    '{"status": "status"}')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return dict(status=status)


class ResponseSerializer(wsgi.JSONResponseSerializer):
    def __init__(self, schema=None):
        super(ResponseSerializer, self).__init__()
        self.schema = schema or get_schema()

    def _format_subject_member(self, member):
        member_view = {}
        attributes = ['member_id', 'subject_id', 'status']
        for key in attributes:
            member_view[key] = getattr(member, key)
        member_view['created_at'] = timeutils.isotime(member.created_at)
        member_view['updated_at'] = timeutils.isotime(member.updated_at)
        member_view['schema'] = '/v1/schemas/member'
        member_view = self.schema.filter(member_view)
        return member_view

    def create(self, response, subject_member):
        subject_member_view = self._format_subject_member(subject_member)
        body = jsonutils.dumps(subject_member_view, ensure_ascii=False)
        response.unicode_body = six.text_type(body)
        response.content_type = 'application/json'

    def update(self, response, subject_member):
        subject_member_view = self._format_subject_member(subject_member)
        body = jsonutils.dumps(subject_member_view, ensure_ascii=False)
        response.unicode_body = six.text_type(body)
        response.content_type = 'application/json'

    def index(self, response, subject_members):
        subject_members = subject_members['members']
        subject_members_view = []
        for subject_member in subject_members:
            subject_member_view = self._format_subject_member(subject_member)
            subject_members_view.append(subject_member_view)
        totalview = dict(members=subject_members_view)
        totalview['schema'] = '/v1/schemas/members'
        body = jsonutils.dumps(totalview, ensure_ascii=False)
        response.unicode_body = six.text_type(body)
        response.content_type = 'application/json'

    def show(self, response, subject_member):
        subject_member_view = self._format_subject_member(subject_member)
        body = jsonutils.dumps(subject_member_view, ensure_ascii=False)
        response.unicode_body = six.text_type(body)
        response.content_type = 'application/json'


_MEMBER_SCHEMA = {
    'member_id': {
        'type': 'string',
        'description': _('An identifier for the subject member (tenantId)')
    },
    'subject_id': {
        'type': 'string',
        'description': _('An identifier for the subject'),
        'pattern': ('^([0-9a-fA-F]){8}-([0-9a-fA-F]){4}-([0-9a-fA-F]){4}'
                    '-([0-9a-fA-F]){4}-([0-9a-fA-F]){12}$'),
    },
    'created_at': {
        'type': 'string',
        'description': _('Date and time of subject member creation'),
        # TODO(brian-rosmaita): our jsonschema library doesn't seem to like the
        # format attribute, figure out why (and also fix in subjects.py)
        # 'format': 'date-time',
    },
    'updated_at': {
        'type': 'string',
        'description': _('Date and time of last modification of subject member'),
        # 'format': 'date-time',
    },
    'status': {
        'type': 'string',
        'description': _('The status of this subject member'),
        'enum': [
            'pending',
            'accepted',
            'rejected'
        ]
    },
    'schema': {
        'readOnly': True,
        'type': 'string'
    }
}


def get_schema():
    properties = copy.deepcopy(_MEMBER_SCHEMA)
    schema = subject.schema.Schema('member', properties)
    return schema


def get_collection_schema():
    member_schema = get_schema()
    return subject.schema.CollectionSchema('members', member_schema)


def create_resource():
    """Subject Members resource factory method"""
    deserializer = RequestDeserializer()
    serializer = ResponseSerializer()
    controller = ImageMembersController()
    return wsgi.Resource(controller, deserializer, serializer)
