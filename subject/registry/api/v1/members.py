# Copyright 2010-2011 OpenStack Foundation
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

from oslo_log import log as logging
from oslo_utils import encodeutils
import webob.exc

from subject.common import exception
from subject.common import utils
from subject.common import wsgi
import subject.db
from subject.i18n import _, _LI, _LW


LOG = logging.getLogger(__name__)


class Controller(object):

    def _check_can_access_subject_members(self, context):
        if context.owner is None and not context.is_admin:
            raise webob.exc.HTTPUnauthorized(_("No authenticated user"))

    def __init__(self):
        self.db_api = subject.db.get_api()

    def is_subject_sharable(self, context, subject):
        """Return True if the subject can be shared to others in this context."""
        # Is admin == subject sharable
        if context.is_admin:
            return True

        # Only allow sharing if we have an owner
        if context.owner is None:
            return False

        # If we own the subject, we can share it
        if context.owner == subject['owner']:
            return True

        members = self.db_api.subject_member_find(context,
                                                subject_id=subject['id'],
                                                member=context.owner)
        if members:
            return members[0]['can_share']

        return False

    def index(self, req, subject_id):
        """
        Get the members of an subject.
        """
        try:
            self.db_api.subject_get(req.context, subject_id)
        except exception.NotFound:
            msg = _("Subject %(id)s not found") % {'id': subject_id}
            LOG.warn(msg)
            raise webob.exc.HTTPNotFound(msg)
        except exception.Forbidden:
            # If it's private and doesn't belong to them, don't let on
            # that it exists
            msg = _LW("Access denied to subject %(id)s but returning"
                      " 'not found'") % {'id': subject_id}
            LOG.warn(msg)
            raise webob.exc.HTTPNotFound()

        members = self.db_api.subject_member_find(req.context, subject_id=subject_id)
        LOG.debug("Returning member list for subject %(id)s", {'id': subject_id})
        return dict(members=make_member_list(members,
                                             member_id='member',
                                             can_share='can_share'))

    @utils.mutating
    def update_all(self, req, subject_id, body):
        """
        Replaces the members of the subject with those specified in the
        body.  The body is a dict with the following format::

            {'memberships': [
                {'member_id': <MEMBER_ID>,
                 ['can_share': [True|False]]}, ...
            ]}
        """
        self._check_can_access_subject_members(req.context)

        # Make sure the subject exists
        try:
            subject = self.db_api.subject_get(req.context, subject_id)
        except exception.NotFound:
            msg = _("Subject %(id)s not found") % {'id': subject_id}
            LOG.warn(msg)
            raise webob.exc.HTTPNotFound(msg)
        except exception.Forbidden:
            # If it's private and doesn't belong to them, don't let on
            # that it exists
            msg = _LW("Access denied to subject %(id)s but returning"
                      " 'not found'") % {'id': subject_id}
            LOG.warn(msg)
            raise webob.exc.HTTPNotFound()

        # Can they manipulate the membership?
        if not self.is_subject_sharable(req.context, subject):
            msg = (_LW("User lacks permission to share subject %(id)s") %
                   {'id': subject_id})
            LOG.warn(msg)
            msg = _("No permission to share that subject")
            raise webob.exc.HTTPForbidden(msg)

        # Get the membership list
        try:
            memb_list = body['memberships']
        except Exception as e:
            # Malformed entity...
            msg = _LW("Invalid membership association specified for "
                      "subject %(id)s") % {'id': subject_id}
            LOG.warn(msg)
            msg = (_("Invalid membership association: %s") %
                   encodeutils.exception_to_unicode(e))
            raise webob.exc.HTTPBadRequest(explanation=msg)

        add = []
        existing = {}
        # Walk through the incoming memberships
        for memb in memb_list:
            try:
                datum = dict(subject_id=subject['id'],
                             member=memb['member_id'],
                             can_share=None)
            except Exception as e:
                # Malformed entity...
                msg = _LW("Invalid membership association specified for "
                          "subject %(id)s") % {'id': subject_id}
                LOG.warn(msg)
                msg = (_("Invalid membership association: %s") %
                       encodeutils.exception_to_unicode(e))
                raise webob.exc.HTTPBadRequest(explanation=msg)

            # Figure out what can_share should be
            if 'can_share' in memb:
                datum['can_share'] = bool(memb['can_share'])

            # Try to find the corresponding membership
            members = self.db_api.subject_member_find(req.context,
                                                    subject_id=datum['subject_id'],
                                                    member=datum['member'],
                                                    include_deleted=True)
            try:
                member = members[0]
            except IndexError:
                # Default can_share
                datum['can_share'] = bool(datum['can_share'])
                add.append(datum)
            else:
                # Are we overriding can_share?
                if datum['can_share'] is None:
                    datum['can_share'] = members[0]['can_share']

                existing[member['id']] = {
                    'values': datum,
                    'membership': member,
                }

        # We now have a filtered list of memberships to add and
        # memberships to modify.  Let's start by walking through all
        # the existing subject memberships...
        existing_members = self.db_api.subject_member_find(req.context,
                                                         subject_id=subject['id'],
                                                         include_deleted=True)
        for member in existing_members:
            if member['id'] in existing:
                # Just update the membership in place
                update = existing[member['id']]['values']
                self.db_api.subject_member_update(req.context,
                                                member['id'],
                                                update)
            else:
                if not member['deleted']:
                    # Outdated one; needs to be deleted
                    self.db_api.subject_member_delete(req.context, member['id'])

        # Now add the non-existent ones
        for memb in add:
            self.db_api.subject_member_create(req.context, memb)

        # Make an appropriate result
        LOG.info(_LI("Successfully updated memberships for subject %(id)s"),
                 {'id': subject_id})
        return webob.exc.HTTPNoContent()

    @utils.mutating
    def update(self, req, subject_id, id, body=None):
        """
        Adds a membership to the subject, or updates an existing one.
        If a body is present, it is a dict with the following format::

            {'member': {
                'can_share': [True|False]
            }}

        If `can_share` is provided, the member's ability to share is
        set accordingly.  If it is not provided, existing memberships
        remain unchanged and new memberships default to False.
        """
        self._check_can_access_subject_members(req.context)

        # Make sure the subject exists
        try:
            subject = self.db_api.subject_get(req.context, subject_id)
        except exception.NotFound:
            msg = _("Subject %(id)s not found") % {'id': subject_id}
            LOG.warn(msg)
            raise webob.exc.HTTPNotFound(msg)
        except exception.Forbidden:
            # If it's private and doesn't belong to them, don't let on
            # that it exists
            msg = _LW("Access denied to subject %(id)s but returning"
                      " 'not found'") % {'id': subject_id}
            LOG.warn(msg)
            raise webob.exc.HTTPNotFound()

        # Can they manipulate the membership?
        if not self.is_subject_sharable(req.context, subject):
            msg = (_LW("User lacks permission to share subject %(id)s") %
                   {'id': subject_id})
            LOG.warn(msg)
            msg = _("No permission to share that subject")
            raise webob.exc.HTTPForbidden(msg)

        # Determine the applicable can_share value
        can_share = None
        if body:
            try:
                can_share = bool(body['member']['can_share'])
            except Exception as e:
                # Malformed entity...
                msg = _LW("Invalid membership association specified for "
                          "subject %(id)s") % {'id': subject_id}
                LOG.warn(msg)
                msg = (_("Invalid membership association: %s") %
                       encodeutils.exception_to_unicode(e))
                raise webob.exc.HTTPBadRequest(explanation=msg)

        # Look up an existing membership...
        members = self.db_api.subject_member_find(req.context,
                                                subject_id=subject_id,
                                                member=id,
                                                include_deleted=True)
        if members:
            if can_share is not None:
                values = dict(can_share=can_share)
                self.db_api.subject_member_update(req.context,
                                                members[0]['id'],
                                                values)
        else:
            values = dict(subject_id=subject['id'], member=id,
                          can_share=bool(can_share))
            self.db_api.subject_member_create(req.context, values)

        LOG.info(_LI("Successfully updated a membership for subject %(id)s"),
                 {'id': subject_id})
        return webob.exc.HTTPNoContent()

    @utils.mutating
    def delete(self, req, subject_id, id):
        """
        Removes a membership from the subject.
        """
        self._check_can_access_subject_members(req.context)

        # Make sure the subject exists
        try:
            subject = self.db_api.subject_get(req.context, subject_id)
        except exception.NotFound:
            msg = _("Subject %(id)s not found") % {'id': subject_id}
            LOG.warn(msg)
            raise webob.exc.HTTPNotFound(msg)
        except exception.Forbidden:
            # If it's private and doesn't belong to them, don't let on
            # that it exists
            msg = _LW("Access denied to subject %(id)s but returning"
                      " 'not found'") % {'id': subject_id}
            LOG.warn(msg)
            raise webob.exc.HTTPNotFound()

        # Can they manipulate the membership?
        if not self.is_subject_sharable(req.context, subject):
            msg = (_LW("User lacks permission to share subject %(id)s") %
                   {'id': subject_id})
            LOG.warn(msg)
            msg = _("No permission to share that subject")
            raise webob.exc.HTTPForbidden(msg)

        # Look up an existing membership
        members = self.db_api.subject_member_find(req.context,
                                                subject_id=subject_id,
                                                member=id)
        if members:
            self.db_api.subject_member_delete(req.context, members[0]['id'])
        else:
            LOG.debug("%(id)s is not a member of subject %(subject_id)s",
                      {'id': id, 'subject_id': subject_id})
            msg = _("Membership could not be found.")
            raise webob.exc.HTTPNotFound(explanation=msg)

        # Make an appropriate result
        LOG.info(_LI("Successfully deleted a membership from subject %(id)s"),
                 {'id': subject_id})
        return webob.exc.HTTPNoContent()

    def default(self, req, *args, **kwargs):
        """This will cover the missing 'show' and 'create' actions"""
        LOG.debug("The method %s is not allowed for this resource",
                  req.environ['REQUEST_METHOD'])
        raise webob.exc.HTTPMethodNotAllowed(
            headers=[('Allow', 'PUT, DELETE')])

    def index_shared_subjects(self, req, id):
        """
        Retrieves subjects shared with the given member.
        """
        try:
            members = self.db_api.subject_member_find(req.context, member=id)
        except exception.NotFound:
            msg = _LW("Member %(id)s not found") % {'id': id}
            LOG.warn(msg)
            msg = _("Membership could not be found.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        LOG.debug("Returning list of subjects shared with member %(id)s",
                  {'id': id})
        return dict(shared_subjects=make_member_list(members,
                                                   subject_id='subject_id',
                                                   can_share='can_share'))


def make_member_list(members, **attr_map):
    """
    Create a dict representation of a list of members which we can use
    to serialize the members list.  Keyword arguments map the names of
    optional attributes to include to the database attribute.
    """

    def _fetch_memb(memb, attr_map):
        return {k: memb[v] for k, v in attr_map.items() if v in memb.keys()}

    # Return the list of members with the given attribute mapping
    return [_fetch_memb(memb, attr_map) for memb in members]


def create_resource():
    """Subject members resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(Controller(), deserializer, serializer)
