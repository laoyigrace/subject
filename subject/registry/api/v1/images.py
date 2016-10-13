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

"""
Reference implementation registry server WSGI controller
"""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import strutils
from oslo_utils import uuidutils
from webob import exc

from subject.common import exception
from subject.common import timeutils
from subject.common import utils
from subject.common import wsgi
import subject.db
from subject.i18n import _, _LE, _LI, _LW


LOG = logging.getLogger(__name__)

CONF = cfg.CONF

DISPLAY_FIELDS_IN_INDEX = ['id', 'name', 'size',
                           'disk_format', 'container_format',
                           'checksum']

SUPPORTED_FILTERS = ['name', 'status', 'container_format', 'disk_format',
                     'min_ram', 'min_disk', 'size_min', 'size_max',
                     'changes-since', 'protected']

SUPPORTED_SORT_KEYS = ('name', 'status', 'container_format', 'disk_format',
                       'size', 'id', 'created_at', 'updated_at')

SUPPORTED_SORT_DIRS = ('asc', 'desc')

SUPPORTED_PARAMS = ('limit', 'marker', 'sort_key', 'sort_dir')


def _normalize_subject_location_for_db(subject_data):
    """
    This function takes the legacy locations field and the newly added
    location_data field from the subject_data values dictionary which flows
    over the wire between the registry and API servers and converts it
    into the location_data format only which is then consumable by the
    Subject object.

    :param subject_data: a dict of values representing information in the subject
    :returns: a new subject data dict
    """
    if 'locations' not in subject_data and 'location_data' not in subject_data:
        subject_data['locations'] = None
        return subject_data

    locations = subject_data.pop('locations', [])
    location_data = subject_data.pop('location_data', [])

    location_data_dict = {}
    for l in locations:
        location_data_dict[l] = {}
    for l in location_data:
        location_data_dict[l['url']] = {'metadata': l['metadata'],
                                        'status': l['status'],
                                        # Note(zhiyan): New location has no ID.
                                        'id': l['id'] if 'id' in l else None}

    # NOTE(jbresnah) preserve original order.  tests assume original order,
    # should that be defined functionality
    ordered_keys = locations[:]
    for ld in location_data:
        if ld['url'] not in ordered_keys:
            ordered_keys.append(ld['url'])

    location_data = []
    for loc in ordered_keys:
        data = location_data_dict[loc]
        if data:
            location_data.append({'url': loc,
                                  'metadata': data['metadata'],
                                  'status': data['status'],
                                  'id': data['id']})
        else:
            location_data.append({'url': loc,
                                  'metadata': {},
                                  'status': 'active',
                                  'id': None})

    subject_data['locations'] = location_data
    return subject_data


class Controller(object):

    def __init__(self):
        self.db_api = subject.db.get_api()

    def _get_subjects(self, context, filters, **params):
        """Get subjects, wrapping in exception if necessary."""
        # NOTE(markwash): for backwards compatibility, is_public=True for
        # admins actually means "treat me as if I'm not an admin and show me
        # all my subjects"
        if context.is_admin and params.get('is_public') is True:
            params['admin_as_user'] = True
            del params['is_public']
        try:
            return self.db_api.subject_get_all(context, filters=filters,
                                             **params)
        except exception.ImageNotFound:
            LOG.warn(_LW("Invalid marker. Subject %(id)s could not be "
                         "found.") % {'id': params.get('marker')})
            msg = _("Invalid marker. Subject could not be found.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.Forbidden:
            LOG.warn(_LW("Access denied to subject %(id)s but returning "
                         "'not found'") % {'id': params.get('marker')})
            msg = _("Invalid marker. Subject could not be found.")
            raise exc.HTTPBadRequest(explanation=msg)
        except Exception:
            LOG.exception(_LE("Unable to get subjects"))
            raise

    def index(self, req):
        """Return a basic filtered list of public, non-deleted subjects

        :param req: the Request object coming from the wsgi layer
        :returns: a mapping of the following form

        .. code-block:: python

            dict(subjects=[subject_list])

        Where subject_list is a sequence of mappings

        .. code-block:: json

            {
                'id': <ID>,
                'name': <NAME>,
                'size': <SIZE>,
                'disk_format': <DISK_FORMAT>,
                'container_format': <CONTAINER_FORMAT>,
                'checksum': <CHECKSUM>
            }

        """
        params = self._get_query_params(req)
        subjects = self._get_subjects(req.context, **params)

        results = []
        for subject in subjects:
            result = {}
            for field in DISPLAY_FIELDS_IN_INDEX:
                result[field] = subject[field]
            results.append(result)

        LOG.debug("Returning subject list")
        return dict(subjects=results)

    def detail(self, req):
        """Return a filtered list of public, non-deleted subjects in detail

        :param req: the Request object coming from the wsgi layer
        :returns: a mapping of the following form

        .. code-block:: json

            {'subjects':
                [{
                    'id': <ID>,
                    'name': <NAME>,
                    'size': <SIZE>,
                    'disk_format': <DISK_FORMAT>,
                    'container_format': <CONTAINER_FORMAT>,
                    'checksum': <CHECKSUM>,
                    'min_disk': <MIN_DISK>,
                    'min_ram': <MIN_RAM>,
                    'store': <STORE>,
                    'status': <STATUS>,
                    'created_at': <TIMESTAMP>,
                    'updated_at': <TIMESTAMP>,
                    'deleted_at': <TIMESTAMP>|<NONE>,
                    'properties': {'distro': 'Ubuntu 10.04 LTS', {...}}
                }, {...}]
            }

        """
        params = self._get_query_params(req)

        subjects = self._get_subjects(req.context, **params)
        subject_dicts = [make_subject_dict(i) for i in subjects]
        LOG.debug("Returning detailed subject list")
        return dict(subjects=subject_dicts)

    def _get_query_params(self, req):
        """Extract necessary query parameters from http request.

        :param req: the Request object coming from the wsgi layer
        :returns: dictionary of filters to apply to list of subjects
        """
        params = {
            'filters': self._get_filters(req),
            'limit': self._get_limit(req),
            'sort_key': [self._get_sort_key(req)],
            'sort_dir': [self._get_sort_dir(req)],
            'marker': self._get_marker(req),
        }

        if req.context.is_admin:
            # Only admin gets to look for non-public subjects
            params['is_public'] = self._get_is_public(req)

        # need to coy items because the params is modified in the loop body
        items = list(params.items())
        for key, value in items:
            if value is None:
                del params[key]

        # Fix for LP Bug #1132294
        # Ensure all shared subjects are returned in v1
        params['member_status'] = 'all'
        return params

    def _get_filters(self, req):
        """Return a dictionary of query param filters from the request

        :param req: the Request object coming from the wsgi layer
        :returns: a dict of key/value filters
        """
        filters = {}
        properties = {}

        for param in req.params:
            if param in SUPPORTED_FILTERS:
                filters[param] = req.params.get(param)
            if param.startswith('property-'):
                _param = param[9:]
                properties[_param] = req.params.get(param)

        if 'changes-since' in filters:
            isotime = filters['changes-since']
            try:
                filters['changes-since'] = timeutils.parse_isotime(isotime)
            except ValueError:
                raise exc.HTTPBadRequest(_("Unrecognized changes-since value"))

        if 'protected' in filters:
            value = self._get_bool(filters['protected'])
            if value is None:
                raise exc.HTTPBadRequest(_("protected must be True, or "
                                           "False"))

            filters['protected'] = value

        # only allow admins to filter on 'deleted'
        if req.context.is_admin:
            deleted_filter = self._parse_deleted_filter(req)
            if deleted_filter is not None:
                filters['deleted'] = deleted_filter
            elif 'changes-since' not in filters:
                filters['deleted'] = False
        elif 'changes-since' not in filters:
            filters['deleted'] = False

        if properties:
            filters['properties'] = properties

        return filters

    def _get_limit(self, req):
        """Parse a limit query param into something usable."""
        try:
            limit = int(req.params.get('limit', CONF.limit_param_default))
        except ValueError:
            raise exc.HTTPBadRequest(_("limit param must be an integer"))

        if limit < 0:
            raise exc.HTTPBadRequest(_("limit param must be positive"))

        return min(CONF.api_limit_max, limit)

    def _get_marker(self, req):
        """Parse a marker query param into something usable."""
        marker = req.params.get('marker', None)

        if marker and not uuidutils.is_uuid_like(marker):
            msg = _('Invalid marker format')
            raise exc.HTTPBadRequest(explanation=msg)

        return marker

    def _get_sort_key(self, req):
        """Parse a sort key query param from the request object."""
        sort_key = req.params.get('sort_key', 'created_at')
        if sort_key is not None and sort_key not in SUPPORTED_SORT_KEYS:
            _keys = ', '.join(SUPPORTED_SORT_KEYS)
            msg = _("Unsupported sort_key. Acceptable values: %s") % (_keys,)
            raise exc.HTTPBadRequest(explanation=msg)
        return sort_key

    def _get_sort_dir(self, req):
        """Parse a sort direction query param from the request object."""
        sort_dir = req.params.get('sort_dir', 'desc')
        if sort_dir is not None and sort_dir not in SUPPORTED_SORT_DIRS:
            _keys = ', '.join(SUPPORTED_SORT_DIRS)
            msg = _("Unsupported sort_dir. Acceptable values: %s") % (_keys,)
            raise exc.HTTPBadRequest(explanation=msg)
        return sort_dir

    def _get_bool(self, value):
        value = value.lower()
        if value == 'true' or value == '1':
            return True
        elif value == 'false' or value == '0':
            return False

        return None

    def _get_is_public(self, req):
        """Parse is_public into something usable."""
        is_public = req.params.get('is_public', None)

        if is_public is None:
            # NOTE(vish): This preserves the default value of showing only
            #             public subjects.
            return True
        elif is_public.lower() == 'none':
            return None

        value = self._get_bool(is_public)
        if value is None:
            raise exc.HTTPBadRequest(_("is_public must be None, True, or "
                                       "False"))

        return value

    def _parse_deleted_filter(self, req):
        """Parse deleted into something usable."""
        deleted = req.params.get('deleted')
        if deleted is None:
            return None
        return strutils.bool_from_string(deleted)

    def show(self, req, id):
        """Return data about the given subject id."""
        try:
            subject = self.db_api.subject_get(req.context, id)
            LOG.debug("Successfully retrieved subject %(id)s", {'id': id})
        except exception.ImageNotFound:
            LOG.info(_LI("Subject %(id)s not found"), {'id': id})
            raise exc.HTTPNotFound()
        except exception.Forbidden:
            # If it's private and doesn't belong to them, don't let on
            # that it exists
            LOG.info(_LI("Access denied to subject %(id)s but returning"
                         " 'not found'"), {'id': id})
            raise exc.HTTPNotFound()
        except Exception:
            LOG.exception(_LE("Unable to show subject %s") % id)
            raise

        return dict(subject=make_subject_dict(subject))

    @utils.mutating
    def delete(self, req, id):
        """Deletes an existing subject with the registry.

        :param req: wsgi Request object
        :param id:  The opaque internal identifier for the subject

        :returns: 200 if delete was successful, a fault if not. On
            success, the body contains the deleted subject
            information as a mapping.
        """
        try:
            deleted_subject = self.db_api.subject_destroy(req.context, id)
            LOG.info(_LI("Successfully deleted subject %(id)s"), {'id': id})
            return dict(subject=make_subject_dict(deleted_subject))
        except exception.ForbiddenPublicImage:
            LOG.info(_LI("Delete denied for public subject %(id)s"), {'id': id})
            raise exc.HTTPForbidden()
        except exception.Forbidden:
            # If it's private and doesn't belong to them, don't let on
            # that it exists
            LOG.info(_LI("Access denied to subject %(id)s but returning"
                         " 'not found'"), {'id': id})
            return exc.HTTPNotFound()
        except exception.ImageNotFound:
            LOG.info(_LI("Subject %(id)s not found"), {'id': id})
            return exc.HTTPNotFound()
        except Exception:
            LOG.exception(_LE("Unable to delete subject %s") % id)
            raise

    @utils.mutating
    def create(self, req, body):
        """Registers a new subject with the registry.

        :param req: wsgi Request object
        :param body: Dictionary of information about the subject

        :returns: The newly-created subject information as a mapping,
            which will include the newly-created subject's internal id
            in the 'id' field
        """
        subject_data = body['subject']

        # Ensure the subject has a status set
        subject_data.setdefault('status', 'active')

        # Set up the subject owner
        if not req.context.is_admin or 'owner' not in subject_data:
            subject_data['owner'] = req.context.owner

        subject_id = subject_data.get('id')
        if subject_id and not uuidutils.is_uuid_like(subject_id):
            LOG.info(_LI("Rejecting subject creation request for invalid subject "
                         "id '%(bad_id)s'"), {'bad_id': subject_id})
            msg = _("Invalid subject id format")
            return exc.HTTPBadRequest(explanation=msg)

        if 'location' in subject_data:
            subject_data['locations'] = [subject_data.pop('location')]

        try:
            subject_data = _normalize_subject_location_for_db(subject_data)
            subject_data = self.db_api.subject_create(req.context, subject_data)
            subject_data = dict(subject=make_subject_dict(subject_data))
            LOG.info(_LI("Successfully created subject %(id)s"),
                     {'id': subject_data['subject']['id']})
            return subject_data
        except exception.Duplicate:
            msg = _("Subject with identifier %s already exists!") % subject_id
            LOG.warn(msg)
            return exc.HTTPConflict(msg)
        except exception.Invalid as e:
            msg = (_("Failed to add subject metadata. "
                     "Got error: %s") % encodeutils.exception_to_unicode(e))
            LOG.error(msg)
            return exc.HTTPBadRequest(msg)
        except Exception:
            LOG.exception(_LE("Unable to create subject %s"), subject_id)
            raise

    @utils.mutating
    def update(self, req, id, body):
        """Updates an existing subject with the registry.

        :param req: wsgi Request object
        :param body: Dictionary of information about the subject
        :param id:  The opaque internal identifier for the subject

        :returns: Returns the updated subject information as a mapping,
        """
        subject_data = body['subject']
        from_state = body.get('from_state', None)

        # Prohibit modification of 'owner'
        if not req.context.is_admin and 'owner' in subject_data:
            del subject_data['owner']

        if 'location' in subject_data:
            subject_data['locations'] = [subject_data.pop('location')]

        purge_props = req.headers.get("X-Glance-Registry-Purge-Props", "false")
        try:
            # These fields hold sensitive data, which should not be printed in
            # the logs.
            sensitive_fields = ['locations', 'location_data']
            LOG.debug("Updating subject %(id)s with metadata: %(subject_data)r",
                      {'id': id,
                       'subject_data': {k: v for k, v in subject_data.items()
                                      if k not in sensitive_fields}})
            subject_data = _normalize_subject_location_for_db(subject_data)
            if purge_props == "true":
                purge_props = True
            else:
                purge_props = False

            updated_subject = self.db_api.subject_update(req.context, id,
                                                     subject_data,
                                                     purge_props=purge_props,
                                                     from_state=from_state)

            LOG.info(_LI("Updating metadata for subject %(id)s"), {'id': id})
            return dict(subject=make_subject_dict(updated_subject))
        except exception.Invalid as e:
            msg = (_("Failed to update subject metadata. "
                     "Got error: %s") % encodeutils.exception_to_unicode(e))
            LOG.error(msg)
            return exc.HTTPBadRequest(msg)
        except exception.ImageNotFound:
            LOG.info(_LI("Subject %(id)s not found"), {'id': id})
            raise exc.HTTPNotFound(body='Subject not found',
                                   request=req,
                                   content_type='text/plain')
        except exception.ForbiddenPublicImage:
            LOG.info(_LI("Update denied for public subject %(id)s"), {'id': id})
            raise exc.HTTPForbidden()
        except exception.Forbidden:
            # If it's private and doesn't belong to them, don't let on
            # that it exists
            LOG.info(_LI("Access denied to subject %(id)s but returning"
                         " 'not found'"), {'id': id})
            raise exc.HTTPNotFound(body='Subject not found',
                                   request=req,
                                   content_type='text/plain')
        except exception.Conflict as e:
            LOG.info(encodeutils.exception_to_unicode(e))
            raise exc.HTTPConflict(body='Subject operation conflicts',
                                   request=req,
                                   content_type='text/plain')
        except Exception:
            LOG.exception(_LE("Unable to update subject %s") % id)
            raise


def _limit_locations(subject):
    locations = subject.pop('locations', [])
    subject['location_data'] = locations
    subject['location'] = None
    for loc in locations:
        if loc['status'] == 'active':
            subject['location'] = loc['url']
            break


def make_subject_dict(subject):
    """Create a dict representation of an subject which we can use to
    serialize the subject.
    """

    def _fetch_attrs(d, attrs):
        return {a: d[a] for a in attrs if a in d.keys()}

    # TODO(sirp): should this be a dict, or a list of dicts?
    # A plain dict is more convenient, but list of dicts would provide
    # access to created_at, etc
    properties = {p['name']: p['value'] for p in subject['properties']
                  if not p['deleted']}

    subject_dict = _fetch_attrs(subject, subject.db.IMAGE_ATTRS)
    subject_dict['properties'] = properties
    _limit_locations(subject_dict)

    return subject_dict


def create_resource():
    """Images resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(Controller(), deserializer, serializer)
