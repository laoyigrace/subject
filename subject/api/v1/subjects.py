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

import re

import subject_store
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils as json
from oslo_utils import encodeutils
import six
import six.moves.urllib.parse as urlparse
import webob.exc

from subject.api import policy
from subject.common import exception
from subject.common import location_strategy
from subject.common import timeutils
from subject.common import utils
from subject.common import wsgi
import subject.db
import subject.gateway
from subject.i18n import _, _LW
import subject.notifier
import subject.schema

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.import_opt('tar_formats', 'subject.common.config', group='subject_format')
CONF.import_opt('subject_formats', 'subject.common.config',
                group='subject_format')
CONF.import_opt('show_multiple_locations', 'subject.common.config')


class SubjectsController(object):
    def __init__(self, db_api=None, policy_enforcer=None, notifier=None,
                 store_api=None):
        self.db_api = db_api or subject.db.get_api()
        self.policy = policy_enforcer or policy.Enforcer()
        self.notifier = notifier or subject.notifier.Notifier()
        self.store_api = store_api or subject_store
        self.gateway = subject.gateway.Gateway(self.db_api, self.store_api,
                                               self.notifier, self.policy)

    @utils.mutating
    def create(self, req, subject, extra_properties, tags):
        subject_factory = self.gateway.get_subject_factory(req.context)
        subject_repo = self.gateway.get_repo(req.context)
        try:
            LOG.debug("+++oj, subject = %s, extra_properties = %s", subject, extra_properties)
            subject = subject_factory.new_subject(extra_properties=extra_properties,
                                            tags=tags, **subject)
            subject_repo.add(subject)
        except (exception.DuplicateLocation,
                exception.Invalid) as e:
            raise webob.exc.HTTPBadRequest(explanation=e.msg)
        except (exception.ReservedProperty,
                exception.ReadonlyProperty) as e:
            raise webob.exc.HTTPForbidden(explanation=e.msg)
        except exception.Forbidden as e:
            LOG.debug("User not permitted to create subject")
            raise webob.exc.HTTPForbidden(explanation=e.msg)
        except exception.LimitExceeded as e:
            LOG.warn(encodeutils.exception_to_unicode(e))
            raise webob.exc.HTTPRequestEntityTooLarge(
                explanation=e.msg, request=req, content_type='text/plain')
        except exception.Duplicate as e:
            raise webob.exc.HTTPConflict(explanation=e.msg)
        except exception.NotAuthenticated as e:
            raise webob.exc.HTTPUnauthorized(explanation=e.msg)
        except TypeError as e:
            LOG.exception(encodeutils.exception_to_unicode(e))
            raise webob.exc.HTTPBadRequest(explanation=e)

        return subject

    def index(self, req, marker=None, limit=None, sort_key=None,
              sort_dir=None, filters=None, member_status='accepted'):
        sort_key = ['created_at'] if not sort_key else sort_key

        sort_dir = ['desc'] if not sort_dir else sort_dir

        result = {}
        if filters is None:
            filters = {}
        filters['deleted'] = False

        if limit is None:
            limit = CONF.limit_param_default
        limit = min(CONF.api_limit_max, limit)

        subject_repo = self.gateway.get_repo(req.context)
        try:
            subjects = subject_repo.list(marker=marker, limit=limit,
                                     sort_key=sort_key,
                                     sort_dir=sort_dir,
                                     filters=filters,
                                     member_status=member_status)
            if len(subjects) != 0 and len(subjects) == limit:
                result['next_marker'] = subjects[-1].subject_id
        except (exception.NotFound, exception.InvalidSortKey,
                exception.InvalidFilterRangeValue,
                exception.InvalidParameterValue,
                exception.InvalidFilterOperatorValue) as e:
            raise webob.exc.HTTPBadRequest(explanation=e.msg)
        except exception.Forbidden as e:
            LOG.debug("User not permitted to retrieve subjects index")
            raise webob.exc.HTTPForbidden(explanation=e.msg)
        except exception.NotAuthenticated as e:
            raise webob.exc.HTTPUnauthorized(explanation=e.msg)
        result['subjects'] = subjects
        return result

    def show(self, req, subject_id):
        subject_repo = self.gateway.get_repo(req.context)
        try:
            return subject_repo.get(subject_id)
        except exception.Forbidden as e:
            LOG.debug("User not permitted to show subject '%s'", subject_id)
            raise webob.exc.HTTPForbidden(explanation=e.msg)
        except exception.NotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.msg)
        except exception.NotAuthenticated as e:
            raise webob.exc.HTTPUnauthorized(explanation=e.msg)

    @utils.mutating
    def update(self, req, subject_id, changes):
        subject_repo = self.gateway.get_repo(req.context)
        try:
            subject = subject_repo.get(subject_id)

            for change in changes:
                change_method_name = '_do_%s' % change['op']
                change_method = getattr(self, change_method_name)
                change_method(req, subject, change)

            if changes:
                subject_repo.save(subject)
        except exception.NotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.msg)
        except (exception.Invalid, exception.BadStoreUri) as e:
            raise webob.exc.HTTPBadRequest(explanation=e.msg)
        except exception.Forbidden as e:
            LOG.debug("User not permitted to update subject '%s'", subject_id)
            raise webob.exc.HTTPForbidden(explanation=e.msg)
        except exception.StorageQuotaFull as e:
            msg = (_("Denying attempt to upload subject because it exceeds the"
                     " quota: %s") % encodeutils.exception_to_unicode(e))
            LOG.warn(msg)
            raise webob.exc.HTTPRequestEntityTooLarge(
                explanation=msg, request=req, content_type='text/plain')
        except exception.LimitExceeded as e:
            LOG.exception(encodeutils.exception_to_unicode(e))
            raise webob.exc.HTTPRequestEntityTooLarge(
                explanation=e.msg, request=req, content_type='text/plain')
        except exception.NotAuthenticated as e:
            raise webob.exc.HTTPUnauthorized(explanation=e.msg)

        return subject

    def _do_replace(self, req, subject, change):
        path = change['path']
        path_root = path[0]
        value = change['value']
        if path_root == 'locations' and value == []:
            msg = _("Cannot set locations to empty list.")
            raise webob.exc.HTTPForbidden(msg)
        elif path_root == 'locations' and value != []:
            self._do_replace_locations(subject, value)
        elif path_root == 'owner' and req.context.is_admin == False:
            msg = _("Owner can't be updated by non admin.")
            raise webob.exc.HTTPForbidden(msg)
        else:
            if hasattr(subject, path_root):
                setattr(subject, path_root, value)
            elif path_root in subject.extra_properties:
                subject.extra_properties[path_root] = value
            else:
                msg = _("Property %s does not exist.")
                raise webob.exc.HTTPConflict(msg % path_root)

    def _do_add(self, req, subject, change):
        path = change['path']
        path_root = path[0]
        value = change['value']
        json_schema_version = change.get('json_schema_version', 10)
        if path_root == 'locations':
            self._do_add_locations(subject, path[1], value)
        else:
            if ((hasattr(subject, path_root) or
                    path_root in subject.extra_properties)
                    and json_schema_version == 4):
                msg = _("Property %s already present.")
                raise webob.exc.HTTPConflict(msg % path_root)
            if hasattr(subject, path_root):
                setattr(subject, path_root, value)
            else:
                subject.extra_properties[path_root] = value

    def _do_remove(self, req, subject, change):
        path = change['path']
        path_root = path[0]
        if path_root == 'locations':
            try:
                self._do_remove_locations(subject, path[1])
            except exception.Forbidden as e:
                raise webob.exc.HTTPForbidden(e.msg)
        else:
            if hasattr(subject, path_root):
                msg = _("Property %s may not be removed.")
                raise webob.exc.HTTPForbidden(msg % path_root)
            elif path_root in subject.extra_properties:
                del subject.extra_properties[path_root]
            else:
                msg = _("Property %s does not exist.")
                raise webob.exc.HTTPConflict(msg % path_root)

    @utils.mutating
    def delete(self, req, subject_id):
        subject_repo = self.gateway.get_repo(req.context)
        try:
            subject = subject_repo.get(subject_id)
            subject.delete()
            subject_repo.remove(subject)
        except (subject_store.Forbidden, exception.Forbidden) as e:
            LOG.debug("User not permitted to delete subject '%s'", subject_id)
            raise webob.exc.HTTPForbidden(explanation=e.msg)
        except (subject_store.NotFound, exception.NotFound) as e:
            msg = (_("Failed to find subject %(subject_id)s to delete") %
                   {'subject_id': subject_id})
            LOG.warn(msg)
            raise webob.exc.HTTPNotFound(explanation=msg)
        except subject_store.exceptions.InUseByStore as e:
            msg = (_("Subject %(id)s could not be deleted "
                     "because it is in use: %(exc)s") %
                   {"id": subject_id,
                    "exc": e.msg})
            LOG.warn(msg)
            raise webob.exc.HTTPConflict(explanation=msg)
        except subject_store.exceptions.HasSnapshot as e:
            raise webob.exc.HTTPConflict(explanation=e.msg)
        except exception.InvalidSubjectStatusTransition as e:
            raise webob.exc.HTTPBadRequest(explanation=e.msg)
        except exception.NotAuthenticated as e:
            raise webob.exc.HTTPUnauthorized(explanation=e.msg)

    def _get_locations_op_pos(self, path_pos, max_pos, allow_max):
        if path_pos is None or max_pos is None:
            return None
        pos = max_pos if allow_max else max_pos - 1
        if path_pos.isdigit():
            pos = int(path_pos)
        elif path_pos != '-':
            return None
        if not (allow_max or 0 <= pos < max_pos):
            return None
        return pos

    def _do_replace_locations(self, subject, value):
        if CONF.show_multiple_locations == False:
            msg = _("It's not allowed to update locations if locations are "
                    "invisible.")
            raise webob.exc.HTTPForbidden(explanation=msg)

        try:
            # NOTE(flwang): _locations_proxy's setattr method will check if
            # the update is acceptable.
            subject.locations = value
            if subject.status == 'queued':
                subject.status = 'active'
        except (exception.BadStoreUri, exception.DuplicateLocation) as e:
            raise webob.exc.HTTPBadRequest(explanation=e.msg)
        except ValueError as ve:    # update subject status failed.
            raise webob.exc.HTTPBadRequest(
                explanation=encodeutils.exception_to_unicode(ve))

    def _do_add_locations(self, subject, path_pos, value):
        if CONF.show_multiple_locations == False:
            msg = _("It's not allowed to add locations if locations are "
                    "invisible.")
            raise webob.exc.HTTPForbidden(explanation=msg)

        if subject.status not in ('active', 'queued'):
            msg = _("It's not allowed to add locations if subject status is "
                    "%s.") % subject.status
            raise webob.exc.HTTPConflict(explanation=msg)

        pos = self._get_locations_op_pos(path_pos,
                                         len(subject.locations), True)
        if pos is None:
            msg = _("Invalid position for adding a location.")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        try:
            subject.locations.insert(pos, value)
            if subject.status == 'queued':
                subject.status = 'active'
        except (exception.BadStoreUri, exception.DuplicateLocation) as e:
            raise webob.exc.HTTPBadRequest(explanation=e.msg)
        except ValueError as e:    # update subject status failed.
            raise webob.exc.HTTPBadRequest(
                explanation=encodeutils.exception_to_unicode(e))

    def _do_remove_locations(self, subject, path_pos):
        if CONF.show_multiple_locations == False:
            msg = _("It's not allowed to remove locations if locations are "
                    "invisible.")
            raise webob.exc.HTTPForbidden(explanation=msg)

        if len(subject.locations) == 1:
            LOG.debug("User forbidden to remove last location of subject %s",
                      subject.subject_id)
            msg = _("Cannot remove last location in the subject.")
            raise exception.Forbidden(msg)
        pos = self._get_locations_op_pos(path_pos,
                                         len(subject.locations), False)
        if pos is None:
            msg = _("Invalid position for removing a location.")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        try:
            # NOTE(zhiyan): this actually deletes the location
            # from the backend store.
            subject.locations.pop(pos)
        # TODO(jokke): Fix this, we should catch what store throws and
        # provide definitely something else than IternalServerError to user.
        except Exception as e:
            raise webob.exc.HTTPInternalServerError(
                explanation=encodeutils.exception_to_unicode(e))


class RequestDeserializer(wsgi.JSONRequestDeserializer):

    _disallowed_properties = ('direct_url', 'self', 'file', 'schema')
    _readonly_properties = ('created_at', 'updated_at', 'status', 'checksum',
                            'size', 'virtual_size', 'direct_url', 'self',
                            'file', 'schema', 'id')
    _reserved_properties = ('location', 'deleted', 'deleted_at')
    _base_properties = ('checksum', 'created_at', 'subject_format',
                        'disk_format', 'id', 'min_disk', 'min_ram', 'name',
                        'size', 'virtual_size', 'status', 'tags', 'owner',
                        'updated_at', 'visibility', 'protected')
    _available_sort_keys = ('name', 'status', 'subject_format',
                            'disk_format', 'size', 'id', 'created_at',
                            'updated_at')

    _default_sort_key = 'created_at'

    _default_sort_dir = 'desc'

    _path_depth_limits = {'locations': {'add': 2, 'remove': 2, 'replace': 1}}

    _supported_operations = ('add', 'remove', 'replace')

    def __init__(self, schema=None):
        super(RequestDeserializer, self).__init__()
        self.schema = schema or get_schema()

    def _get_request_body(self, request):
        output = super(RequestDeserializer, self).default(request)
        if 'body' not in output:
            msg = _('Body expected in request.')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return output['body']

    @classmethod
    def _check_allowed(cls, subject):
        for key in cls._disallowed_properties:
            if key in subject:
                msg = _("Attribute '%s' is read-only.") % key
                raise webob.exc.HTTPForbidden(
                    explanation=six.text_type(msg))

    def create(self, request):
        body = self._get_request_body(request)
        body = body['subject']
        self._check_allowed(body)
        try:
            self.schema.validate(body)
        except exception.InvalidObject as e:
            LOG.exception("schema failed! ex = %s", e)
            raise webob.exc.HTTPBadRequest(explanation=e.msg)
        subject = {}
        properties = body
        tags = properties.pop('tags', [])
        for key in self._base_properties:
            try:
                # NOTE(flwang): Instead of changing the _check_unexpected
                # of SubjectFactory. It would be better to do the mapping
                # at here.
                if key == 'id':
                    subject['subject_id'] = properties.pop(key)
                else:
                    subject[key] = properties.pop(key)
            except KeyError:
                pass
        return dict(subject=subject, extra_properties=properties, tags=tags)

    def _get_change_operation_d10(self, raw_change):
        op = raw_change.get('op')
        if op is None:
            msg = (_('Unable to find `op` in JSON Schema change. '
                     'It must be one of the following: %(available)s.') %
                   {'available': ', '.join(self._supported_operations)})
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if op not in self._supported_operations:
            msg = (_('Invalid operation: `%(op)s`. '
                     'It must be one of the following: %(available)s.') %
                   {'op': op,
                    'available': ', '.join(self._supported_operations)})
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return op

    def _get_change_operation_d4(self, raw_change):
        op = None
        for key in self._supported_operations:
            if key in raw_change:
                if op is not None:
                    msg = _('Operation objects must contain only one member'
                            ' named "add", "remove", or "replace".')
                    raise webob.exc.HTTPBadRequest(explanation=msg)
                op = key
        if op is None:
            msg = _('Operation objects must contain exactly one member'
                    ' named "add", "remove", or "replace".')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return op

    def _get_change_path_d10(self, raw_change):
        try:
            return raw_change['path']
        except KeyError:
            msg = _("Unable to find '%s' in JSON Schema change") % 'path'
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_change_path_d4(self, raw_change, op):
        return raw_change[op]

    def _decode_json_pointer(self, pointer):
        """Parse a json pointer.

        Json Pointers are defined in
        http://tools.ietf.org/html/draft-pbryan-zyp-json-pointer .
        The pointers use '/' for separation between object attributes, such
        that '/A/B' would evaluate to C in {"A": {"B": "C"}}. A '/' character
        in an attribute name is encoded as "~1" and a '~' character is encoded
        as "~0".
        """
        self._validate_json_pointer(pointer)
        ret = []
        for part in pointer.lstrip('/').split('/'):
            ret.append(part.replace('~1', '/').replace('~0', '~').strip())
        return ret

    def _validate_json_pointer(self, pointer):
        """Validate a json pointer.

        We only accept a limited form of json pointers.
        """
        if not pointer.startswith('/'):
            msg = _('Pointer `%s` does not start with "/".') % pointer
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if re.search('/\s*?/', pointer[1:]):
            msg = _('Pointer `%s` contains adjacent "/".') % pointer
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if len(pointer) > 1 and pointer.endswith('/'):
            msg = _('Pointer `%s` end with "/".') % pointer
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if pointer[1:].strip() == '/':
            msg = _('Pointer `%s` does not contains valid token.') % pointer
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if re.search('~[^01]', pointer) or pointer.endswith('~'):
            msg = _('Pointer `%s` contains "~" not part of'
                    ' a recognized escape sequence.') % pointer
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_change_value(self, raw_change, op):
        if 'value' not in raw_change:
            msg = _('Operation "%s" requires a member named "value".')
            raise webob.exc.HTTPBadRequest(explanation=msg % op)
        return raw_change['value']

    def _validate_change(self, change):
        path_root = change['path'][0]
        if path_root in self._readonly_properties:
            msg = _("Attribute '%s' is read-only.") % path_root
            raise webob.exc.HTTPForbidden(explanation=six.text_type(msg))
        if path_root in self._reserved_properties:
            msg = _("Attribute '%s' is reserved.") % path_root
            raise webob.exc.HTTPForbidden(explanation=six.text_type(msg))

        if change['op'] == 'remove':
            return

        partial_subject = None
        if len(change['path']) == 1:
            partial_subject = {path_root: change['value']}
        elif ((path_root in get_base_properties().keys()) and
              (get_base_properties()[path_root].get('type', '') == 'array')):
            # NOTE(zhiyan): client can use the PATCH API to add an element
            # directly to an existing property
            # Such as: 1. using '/locations/N' path to add a location
            #             to the subject's 'locations' list at position N.
            #             (implemented)
            #          2. using '/tags/-' path to append a tag to the
            #             subject's 'tags' list at the end. (Not implemented)
            partial_subject = {path_root: [change['value']]}

        if partial_subject:
            try:
                self.schema.validate(partial_subject)
            except exception.InvalidObject as e:
                raise webob.exc.HTTPBadRequest(explanation=e.msg)

    def _validate_path(self, op, path):
        path_root = path[0]
        limits = self._path_depth_limits.get(path_root, {})
        if len(path) != limits.get(op, 1):
            msg = _("Invalid JSON pointer for this resource: "
                    "'/%s'") % '/'.join(path)
            raise webob.exc.HTTPBadRequest(explanation=six.text_type(msg))

    def _parse_json_schema_change(self, raw_change, draft_version):
        if draft_version == 10:
            op = self._get_change_operation_d10(raw_change)
            path = self._get_change_path_d10(raw_change)
        elif draft_version == 4:
            op = self._get_change_operation_d4(raw_change)
            path = self._get_change_path_d4(raw_change, op)
        else:
            msg = _('Unrecognized JSON Schema draft version')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        path_list = self._decode_json_pointer(path)
        return op, path_list

    def update(self, request):
        changes = []
        content_types = {
            'application/openstack-subjects-v1.0-json-patch': 4,
            'application/openstack-subjects-v1.1-json-patch': 10,
        }
        if request.content_type not in content_types:
            headers = {'Accept-Patch':
                       ', '.join(sorted(content_types.keys()))}
            raise webob.exc.HTTPUnsupportedMediaType(headers=headers)

        json_schema_version = content_types[request.content_type]

        body = self._get_request_body(request)

        if not isinstance(body, list):
            msg = _('Request body must be a JSON array of operation objects.')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        for raw_change in body:
            if not isinstance(raw_change, dict):
                msg = _('Operations must be JSON objects.')
                raise webob.exc.HTTPBadRequest(explanation=msg)

            (op, path) = self._parse_json_schema_change(raw_change,
                                                        json_schema_version)

            # NOTE(zhiyan): the 'path' is a list.
            self._validate_path(op, path)
            change = {'op': op, 'path': path,
                      'json_schema_version': json_schema_version}

            if not op == 'remove':
                change['value'] = self._get_change_value(raw_change, op)

            self._validate_change(change)

            changes.append(change)

        return {'changes': changes}

    def _validate_limit(self, limit):
        try:
            limit = int(limit)
        except ValueError:
            msg = _("limit param must be an integer")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if limit < 0:
            msg = _("limit param must be positive")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return limit

    def _validate_sort_key(self, sort_key):
        if sort_key not in self._available_sort_keys:
            msg = _('Invalid sort key: %(sort_key)s. '
                    'It must be one of the following: %(available)s.') % (
                {'sort_key': sort_key,
                 'available': ', '.join(self._available_sort_keys)})
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return sort_key

    def _validate_sort_dir(self, sort_dir):
        if sort_dir not in ['asc', 'desc']:
            msg = _('Invalid sort direction: %s') % sort_dir
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return sort_dir

    def _validate_member_status(self, member_status):
        if member_status not in ['pending', 'accepted', 'rejected', 'all']:
            msg = _('Invalid status: %s') % member_status
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return member_status

    def _get_filters(self, filters):
        visibility = filters.get('visibility')
        if visibility:
            if visibility not in ['public', 'private', 'shared']:
                msg = _('Invalid visibility value: %s') % visibility
                raise webob.exc.HTTPBadRequest(explanation=msg)
        changes_since = filters.get('changes-since', None)
        if changes_since:
            msg = _('The "changes-since" filter is no longer available on v1.')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return filters

    def _get_sorting_params(self, params):
        """
        Process sorting params.
        Currently subject supports two sorting syntax: classic and new one,
        that is uniform for all OpenStack projects.
        Classic syntax: sort_key=name&sort_dir=asc&sort_key=size&sort_dir=desc
        New syntax: sort=name:asc,size:desc
        """
        sort_keys = []
        sort_dirs = []

        if 'sort' in params:
            # use new sorting syntax here
            if 'sort_key' in params or 'sort_dir' in params:
                msg = _('Old and new sorting syntax cannot be combined')
                raise webob.exc.HTTPBadRequest(explanation=msg)
            for sort_param in params.pop('sort').strip().split(','):
                key, _sep, dir = sort_param.partition(':')
                if not dir:
                    dir = self._default_sort_dir
                sort_keys.append(self._validate_sort_key(key.strip()))
                sort_dirs.append(self._validate_sort_dir(dir.strip()))
        else:
            # continue with classic syntax
            # NOTE(mfedosin): we have 3 options here:
            # 1. sort_dir wasn't passed: we use default one - 'desc'.
            # 2. Only one sort_dir was passed: use it for every sort_key
            # in the list.
            # 3. Multiple sort_dirs were passed: consistently apply each one to
            # the corresponding sort_key.
            # If number of sort_dirs and sort_keys doesn't match then raise an
            # exception.
            while 'sort_key' in params:
                sort_keys.append(self._validate_sort_key(
                    params.pop('sort_key').strip()))

            while 'sort_dir' in params:
                sort_dirs.append(self._validate_sort_dir(
                    params.pop('sort_dir').strip()))

            if sort_dirs:
                dir_len = len(sort_dirs)
                key_len = len(sort_keys)

                if dir_len > 1 and dir_len != key_len:
                    msg = _('Number of sort dirs does not match the number '
                            'of sort keys')
                    raise webob.exc.HTTPBadRequest(explanation=msg)

        if not sort_keys:
            sort_keys = [self._default_sort_key]

        if not sort_dirs:
            sort_dirs = [self._default_sort_dir]

        return sort_keys, sort_dirs

    def index(self, request):
        params = request.params.copy()
        limit = params.pop('limit', None)
        marker = params.pop('marker', None)
        member_status = params.pop('member_status', 'accepted')

        # NOTE (flwang) To avoid using comma or any predefined chars to split
        # multiple tags, now we allow user specify multiple 'tag' parameters
        # in URL, such as v1/subjects?tag=x86&tag=64bit.
        tags = []
        while 'tag' in params:
            tags.append(params.pop('tag').strip())

        query_params = {
            'filters': self._get_filters(params),
            'member_status': self._validate_member_status(member_status),
        }

        if marker is not None:
            query_params['marker'] = marker

        if limit is not None:
            query_params['limit'] = self._validate_limit(limit)

        if tags:
            query_params['filters']['tags'] = tags

        # NOTE(mfedosin): param is still called sort_key and sort_dir,
        # instead of sort_keys and sort_dirs respectively.
        # It's done because in v1 it's still a single value.

        query_params['sort_key'], query_params['sort_dir'] = (
            self._get_sorting_params(params))

        return query_params


class ResponseSerializer(wsgi.JSONResponseSerializer):
    def __init__(self, schema=None):
        super(ResponseSerializer, self).__init__()
        self.schema = schema or get_schema()

    def _get_subject_href(self, subject, subcollection=''):
        base_href = '/v1/subjects/%s' % subject.subject_id
        if subcollection:
            base_href = '%s/%s' % (base_href, subcollection)
        return base_href

    def _format_subject(self, subject):

        def _get_subject_locations(subject):
            try:
                return list(subject.locations)
            except exception.Forbidden:
                return []

        try:
            subject_view = dict(subject.extra_properties)
            attributes = ['name', 'type', 'tar_format', 'subject_format',
                          'visibility', 'size', 'contributor', 'status',
                          'checksum', 'protected', 'phase', 'language',
                          'score', 'knowledge', 'description', 'subject_desc',
                          'owner']
            for key in attributes:
                subject_view[key] = getattr(subject, key)
            subject_view['id'] = subject.subject_id
            subject_view['created_at'] = timeutils.isotime(subject.created_at)
            subject_view['updated_at'] = timeutils.isotime(subject.updated_at)

            if CONF.show_multiple_locations:
                locations = _get_subject_locations(subject)
                if locations:
                    subject_view['locations'] = []
                    for loc in locations:
                        tmp = dict(loc)
                        tmp.pop('id', None)
                        tmp.pop('status', None)
                        subject_view['locations'].append(tmp)
                else:
                    # NOTE (flwang): We will still show "locations": [] if
                    # subject.locations is None to indicate it's allowed to show
                    # locations but it's just non-existent.
                    subject_view['locations'] = []
                    LOG.debug("There is not available location "
                              "for subject %s", subject.subject_id)

            if CONF.show_subject_direct_url:
                locations = _get_subject_locations(subject)
                if locations:
                    # Choose best location configured strategy
                    l = location_strategy.choose_best_location(locations)
                    subject_view['direct_url'] = l['url']
                else:
                    LOG.debug("There is not available location "
                              "for subject %s", subject.subject_id)

            subject_view['tags'] = list(subject.tags)
            subject_view['self'] = self._get_subject_href(subject)
            subject_view['file'] = self._get_subject_href(subject, 'file')
            subject_view['schema'] = '/v1/schemas/subject'
            subject_view = self.schema.filter(subject_view)  # domain
            return {'subject': subject_view}
        except exception.Forbidden as e:
            raise webob.exc.HTTPForbidden(explanation=e.msg)

    def create(self, response, subject):
        response.status_int = 201
        self.show(response, subject)
        response.location = self._get_subject_href(subject)

    def show(self, response, subject):
        subject_view = self._format_subject(subject)
        body = json.dumps(subject_view, ensure_ascii=False)
        response.unicode_body = six.text_type(body)
        response.content_type = 'application/json'

    def update(self, response, subject):
        subject_view = self._format_subject(subject)
        body = json.dumps(subject_view, ensure_ascii=False)
        response.unicode_body = six.text_type(body)
        response.content_type = 'application/json'

    def index(self, response, result):
        params = dict(response.request.params)
        params.pop('marker', None)
        query = urlparse.urlencode(params)
        body = {
            'subjects': [self._format_subject(i) for i in result['subjects']],
            'first': '/v1/subjects',
            'schema': '/v1/schemas/subjects',
        }
        if query:
            body['first'] = '%s?%s' % (body['first'], query)
        if 'next_marker' in result:
            params['marker'] = result['next_marker']
            next_query = urlparse.urlencode(params)
            body['next'] = '/v1/subjects?%s' % next_query
        response.unicode_body = six.text_type(json.dumps(body,
                                                         ensure_ascii=False))
        response.content_type = 'application/json'

    def delete(self, response, result):
        response.status_int = 204


def get_base_properties():
    return {
        'id': {
            'type': 'string',
            'description': _('An identifier for the subject'),
            'pattern': ('^([0-9a-fA-F]){8}-([0-9a-fA-F]){4}-([0-9a-fA-F]){4}'
                        '-([0-9a-fA-F]){4}-([0-9a-fA-F]){12}$'),
        },
        'name': {
            'type': ['null', 'string'],
            'description': _('Descriptive name for the subject'),
            'maxLength': 255,
        },
        'size': {
            'type': ['null', 'integer'],
            'readOnly': True,
            'description': _('Size of subject file in bytes'),
        },
        'status': {
            'type': 'string',
            'readOnly': True,
            'description': _('Status of the subject'),
            'enum': ['queued', 'saving', 'active', 'killed',
                     'deleted', 'pending_delete', 'deactivated'],
        },
        'type': {
            'type': ['null', 'string'],
            'description': _('type of subject'),
            'enum': ['program', 'choice', 'judge'],
        },
        'subject_format': {
            'type': ['null', 'string'],
            'description': _('format of subject'),
            'enum': [None] + CONF.subject_format.subject_formats,
        },
        'tar_format': {
            'type': ['null', 'string'],
            'description': _('Format of the disk'),
            'enum': [None] + CONF.subject_format.tar_formats,
        },
        'owner': {
            'type': ['null', 'string'],
            'description': _('Owner of the subject'),
            'maxLength': 255,
        },
        'checksum': {
            'type': ['null', 'string'],
            'readOnly': True,
            'description': _('md5 hash of subject contents.'),
            'maxLength': 32,
        },
        'contributor': {
            'type': ['null', 'string'],
            'description': _('contributor of the subject'),
            'maxLength': 255,
        },
        'phase': {
            'type': ['null', 'string'],
            'description': _('phase of the subject'),
            'maxLength': 255,
        },
        'language': {
            'type': ['null', 'string'],
            'description': _('phase of the subject'),
            'maxLength': 255,
        },
        'score': {
            'type': ['null', 'integer'],
            'description': _('score of subject'),
        },
        'knowledge': {
            'type': ['null', 'string'],
            'description': _('knowledge of the subject'),
            'maxLength': 255,
        },
        'visibility': {
            'type': 'string',
            'description': _('Scope of subject accessibility'),
            'enum': ['public', 'private'],
        },
        'protected': {
            'type': 'boolean',
            'description': _('If true, subject will not be deletable.'),
        },
        'subject_desc': {
            'type': ['null', 'string'],
            'description': _('info of the subject'),
            'maxLength': 1024,
        },
        'created_at': {
            'type': 'string',
            'readOnly': True,
            'description': _('Date and time of subject registration'
                             ),
            # TODO(bcwaldon): our jsonschema library doesn't seem to like the
            # format attribute, figure out why!
            # 'format': 'date-time',
        },
        'updated_at': {
            'type': 'string',
            'readOnly': True,
            'description': _('Date and time of the last subject modification'
                             ),
            # 'format': 'date-time',
        },
        'tags': {
            'type': 'array',
            'description': _('List of strings related to the subject'),
            'items': {
                'type': 'string',
                'maxLength': 255,
            },
        },
        'direct_url': {
            'type': 'string',
            'readOnly': True,
            'description': _('URL to access the subject file kept in external '
                             'store'),
        },
        'self': {
            'type': 'string',
            'readOnly': True,
            'description': _('An subject self url'),
        },
        'file': {
            'type': 'string',
            'readOnly': True,
            'description': _('An subject file url'),
        },
        'locations': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'url': {
                        'type': 'string',
                        'maxLength': 255,
                    },
                    'metadata': {
                        'type': 'object',
                    },
                },
                'required': ['url', 'metadata'],
            },
            'description': _('A set of URLs to access the subject file kept in '
                             'external store'),
        },
    }


def _get_base_links():
    return [
        {'rel': 'self', 'href': '{self}'},
        {'rel': 'enclosure', 'href': '{file}'},
        {'rel': 'describedby', 'href': '{schema}'},
    ]


def get_schema(custom_properties=None):
    properties = get_base_properties()
    links = _get_base_links()
    if CONF.allow_additional_subject_properties:
        schema = subject.schema.PermissiveSchema('subject', properties, links)
    else:
        schema = subject.schema.Schema('subject', properties)

    if custom_properties:
        for property_value in custom_properties.values():
            property_value['is_base'] = False
        schema.merge_properties(custom_properties)
    return schema


def get_collection_schema(custom_properties=None):
    subject_schema = get_schema(custom_properties)
    return subject.schema.CollectionSchema('subjects', subject_schema)


def load_custom_properties():
    """Find the schema properties files and load them into a dict."""
    filename = 'schema-subject.json'
    match = CONF.find_file(filename)
    if match:
        with open(match, 'r') as schema_file:
            schema_data = schema_file.read()
        return json.loads(schema_data)
    else:
        msg = (_LW('Could not find schema properties file %s. Continuing '
                   'without custom properties') % filename)
        LOG.warn(msg)
        return {}


def create_resource(custom_properties=None):
    """Subjects resource factory method"""
    schema = get_schema(custom_properties)
    deserializer = RequestDeserializer(schema)
    serializer = ResponseSerializer(schema)
    controller = SubjectsController()
    return wsgi.Resource(controller, deserializer, serializer)
