# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2010-2011 OpenStack Foundation
# Copyright 2012 Justin Santa Barbara
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


"""Defines interface for DB access."""

import datetime
import threading

from oslo_config import cfg
from oslo_db import exception as db_exception
from oslo_db.sqlalchemy import session
from oslo_log import log as logging
import osprofiler.sqlalchemy
from retrying import retry
import six
# NOTE(jokke): simplified transition to py3, behaves like py2 xrange
from six.moves import range
import sqlalchemy
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import MetaData, Table
import sqlalchemy.orm as sa_orm
from sqlalchemy import sql
import sqlalchemy.sql as sa_sql

from subject.common import exception
from subject.common import timeutils
from subject.common import utils
from subject.db.sqlalchemy import models
from subject import glare as ga
from subject.i18n import _, _LW, _LI

sa_logger = None
LOG = logging.getLogger(__name__)

STATUSES = ['active', 'saving', 'queued', 'killed', 'pending_delete',
            'deleted', 'deactivated']

CONF = cfg.CONF
CONF.import_group("profiler", "subject.common.wsgi")

_FACADE = None
_LOCK = threading.Lock()


def _retry_on_deadlock(exc):
    """Decorator to retry a DB API call if Deadlock was received."""

    if isinstance(exc, db_exception.DBDeadlock):
        LOG.warn(_LW("Deadlock detected. Retrying..."))
        return True
    return False


def _create_facade_lazily():
    global _LOCK, _FACADE
    if _FACADE is None:
        with _LOCK:
            if _FACADE is None:
                _FACADE = session.EngineFacade.from_config(CONF)

                if CONF.profiler.enabled and CONF.profiler.trace_sqlalchemy:
                    osprofiler.sqlalchemy.add_tracing(sqlalchemy,
                                                      _FACADE.get_engine(),
                                                      "db")
    return _FACADE


def get_engine():
    facade = _create_facade_lazily()
    return facade.get_engine()


def get_session(autocommit=True, expire_on_commit=False):
    facade = _create_facade_lazily()
    return facade.get_session(autocommit=autocommit,
                              expire_on_commit=expire_on_commit)


def _validate_db_int(**kwargs):
    """Make sure that all arguments are less than or equal to 2 ** 31 - 1.

    This limitation is introduced because databases stores INT in 4 bytes.
    If the validation fails for some argument, exception.Invalid is raised with
    appropriate information.
    """
    max_int = (2 ** 31) - 1

    for param_key, param_value in kwargs.items():
        if param_value and param_value > max_int:
            msg = _("'%(param)s' value out of range, "
                    "must not exceed %(max)d.") % {"param": param_key,
                                                   "max": max_int}
            raise exception.Invalid(msg)


def clear_db_env():
    """
    Unset global configuration variables for database.
    """
    global _FACADE
    _FACADE = None


def _check_mutate_authorization(context, subject_ref):
    if not is_subject_mutable(context, subject_ref):
        LOG.warn(_LW("Attempted to modify subject user did not own."))
        msg = _("You do not own this subject")
        if subject_ref.is_public:
            exc_class = exception.ForbiddenPublicSubject
        else:
            exc_class = exception.Forbidden

        raise exc_class(msg)


def subject_create(context, values):
    """Create an subject from the values dictionary."""
    return _subject_update(context, values, None, purge_props=False)


def subject_update(context, subject_id, values, purge_props=False,
                   from_state=None):
    """
    Set the given properties on an subject and update it.

    :raises: SubjectNotFound if subject does not exist.
    """
    return _subject_update(context, values, subject_id, purge_props,
                           from_state=from_state)


@retry(retry_on_exception=_retry_on_deadlock, wait_fixed=500,
       stop_max_attempt_number=50)
def subject_destroy(context, subject_id):
    """Destroy the subject or raise if it does not exist."""
    session = get_session()
    with session.begin():
        subject_ref = _subject_get(context, subject_id, session=session)

        # Perform authorization check
        _check_mutate_authorization(context, subject_ref)

        subject_ref.delete(session=session)
        delete_time = subject_ref.deleted_at

        _subject_locations_delete_all(context, subject_id, delete_time, session)

        _subject_property_delete_all(context, subject_id, delete_time, session)

        _subject_member_delete_all(context, subject_id, delete_time, session)

        _subject_tag_delete_all(context, subject_id, delete_time, session)

    return _normalize_locations(context, subject_ref)


def _normalize_locations(context, subject, force_show_deleted=False):
    """
    Generate suitable dictionary list for locations field of subject.

    We don't need to set other data fields of location record which return
    from subject query.
    """

    if subject['status'] == 'deactivated' and not context.is_admin:
        # Locations are not returned for a deactivated subject for non-admin user
        subject['locations'] = []
        return subject

    if force_show_deleted:
        locations = subject['locations']
    else:
        locations = [x for x in subject['locations'] if not x.deleted]
    subject['locations'] = [{'id': loc['id'],
                             'url': loc['value'],
                             'metadata': loc['meta_data'],
                             'status': loc['status']}
                            for loc in locations]
    return subject


def _normalize_tags(subject):
    undeleted_tags = [x for x in subject['tags'] if not x.deleted]
    subject['tags'] = [tag['value'] for tag in undeleted_tags]
    return subject


def subject_get(context, subject_id, session=None, force_show_deleted=False):
    subject = _subject_get(context, subject_id, session=session,
                           force_show_deleted=force_show_deleted)
    subject = _normalize_locations(context, subject.to_dict(),
                                   force_show_deleted=force_show_deleted)
    return subject


def _check_subject_id(subject_id):
    """
    check if the given subject id is valid before executing operations. For
    now, we only check its length. The original purpose of this method is
    wrapping the different behaviors between MySql and DB2 when the subject id
    length is longer than the defined length in database model.
    :param subject_id: The id of the subject we want to check
    :returns: Raise NoFound exception if given subject id is invalid
    """
    if (subject_id and
                len(subject_id) > models.Subject.id.property.columns[
                0].type.length):
        raise exception.SubjectNotFound()


def _subject_get(context, subject_id, session=None, force_show_deleted=False):
    """Get an subject or raise if it does not exist."""
    _check_subject_id(subject_id)
    session = session or get_session()

    try:
        query = session.query(models.Subject).options(
            sa_orm.joinedload(models.Subject.properties)).options(
            sa_orm.joinedload(
                models.Subject.locations)).filter_by(id=subject_id)

        # filter out deleted subjects if context disallows it
        if not force_show_deleted and not context.can_see_deleted:
            query = query.filter_by(deleted=False)

        subject = query.one()

    except sa_orm.exc.NoResultFound:
        msg = "No subject found with ID %s" % subject_id
        LOG.debug(msg)
        raise exception.SubjectNotFound(msg)

    # Make sure they can look at it
    if not is_subject_visible(context, subject):
        msg = "Forbidding request, subject %s not visible" % subject_id
        LOG.debug(msg)
        raise exception.Forbidden(msg)

    return subject


def is_subject_mutable(context, subject):
    """Return True if the subject is mutable in this context."""
    # Is admin == subject mutable
    if context.is_admin:
        return True

    # No owner == subject not mutable
    if subject['owner'] is None or context.owner is None:
        return False

    # Subject only mutable by its owner
    return subject['owner'] == context.owner


def is_subject_visible(context, subject, status=None):
    """Return True if the subject is visible in this context."""
    # Is admin == subject visible
    if context.is_admin:
        return True

    # No owner == subject visible
    if subject['owner'] is None:
        return True

    # Subject is_public == subject visible
    if subject['is_public']:
        return True

    # Perform tests based on whether we have an owner
    if context.owner is not None:
        if context.owner == subject['owner']:
            return True

        # Figure out if this subject is shared with that tenant
        members = subject_member_find(context,
                                      subject_id=subject['id'],
                                      member=context.owner,
                                      status=status)
        if members:
            return True

    # Private subject
    return False


def _get_default_column_value(column_type):
    """Return the default value of the columns from DB table

    In postgreDB case, if no right default values are being set, an
    psycopg2.DataError will be thrown.
    """
    type_schema = {
        'datetime': None,
        'big_integer': 0,
        'integer': 0,
        'string': ''
    }

    if isinstance(column_type, sa_sql.type_api.Variant):
        return _get_default_column_value(column_type.impl)

    return type_schema[column_type.__visit_name__]


def _paginate_query(query, model, limit, sort_keys, marker=None,
                    sort_dir=None, sort_dirs=None):
    """Returns a query with sorting / pagination criteria added.

    Pagination works by requiring a unique sort_key, specified by sort_keys.
    (If sort_keys is not unique, then we risk looping through values.)
    We use the last row in the previous page as the 'marker' for pagination.
    So we must return values that follow the passed marker in the order.
    With a single-valued sort_key, this would be easy: sort_key > X.
    With a compound-values sort_key, (k1, k2, k3) we must do this to repeat
    the lexicographical ordering:
    (k1 > X1) or (k1 == X1 && k2 > X2) or (k1 == X1 && k2 == X2 && k3 > X3)

    We also have to cope with different sort_directions.

    Typically, the id of the last row is used as the client-facing pagination
    marker, then the actual marker object must be fetched from the db and
    passed in to us as marker.

    :param query: the query object to which we should add paging/sorting
    :param model: the ORM model class
    :param limit: maximum number of items to return
    :param sort_keys: array of attributes by which results should be sorted
    :param marker: the last item of the previous page; we returns the next
                    results after this value.
    :param sort_dir: direction in which results should be sorted (asc, desc)
    :param sort_dirs: per-column array of sort_dirs, corresponding to sort_keys

    :rtype: sqlalchemy.orm.query.Query
    :returns: The query with sorting/pagination added.
    """

    if 'id' not in sort_keys:
        # TODO(justinsb): If this ever gives a false-positive, check
        # the actual primary key, rather than assuming its id
        LOG.warn(_LW('Id not in sort_keys; is sort_keys unique?'))

    assert (not (sort_dir and sort_dirs))  # nosec
    # nosec: This function runs safely if the assertion fails.

    # Default the sort direction to ascending
    if sort_dir is None:
        sort_dir = 'asc'

    # Ensure a per-column sort direction
    if sort_dirs is None:
        sort_dirs = [sort_dir] * len(sort_keys)

    assert (len(sort_dirs) == len(sort_keys))  # nosec
    # nosec: This function runs safely if the assertion fails.
    if len(sort_dirs) < len(sort_keys):
        sort_dirs += [sort_dir] * (len(sort_keys) - len(sort_dirs))

    # Add sorting
    for current_sort_key, current_sort_dir in zip(sort_keys, sort_dirs):
        sort_dir_func = {
            'asc': sqlalchemy.asc,
            'desc': sqlalchemy.desc,
        }[current_sort_dir]

        try:
            sort_key_attr = getattr(model, current_sort_key)
        except AttributeError:
            raise exception.InvalidSortKey()
        query = query.order_by(sort_dir_func(sort_key_attr))

    default = ''  # Default to an empty string if NULL

    # Add pagination
    if marker is not None:
        marker_values = []
        for sort_key in sort_keys:
            v = getattr(marker, sort_key)
            if v is None:
                v = default
            marker_values.append(v)

        # Build up an array of sort criteria as in the docstring
        criteria_list = []
        for i in range(len(sort_keys)):
            crit_attrs = []
            for j in range(i):
                model_attr = getattr(model, sort_keys[j])
                default = _get_default_column_value(
                    model_attr.property.columns[0].type)
                attr = sa_sql.expression.case([(model_attr != None,
                                                model_attr), ],
                                              else_=default)
                crit_attrs.append((attr == marker_values[j]))

            model_attr = getattr(model, sort_keys[i])
            default = _get_default_column_value(
                model_attr.property.columns[0].type)
            attr = sa_sql.expression.case([(model_attr != None,
                                            model_attr), ],
                                          else_=default)
            if sort_dirs[i] == 'desc':
                crit_attrs.append((attr < marker_values[i]))
            elif sort_dirs[i] == 'asc':
                crit_attrs.append((attr > marker_values[i]))
            else:
                raise ValueError(_("Unknown sort direction, "
                                   "must be 'desc' or 'asc'"))

            criteria = sa_sql.and_(*crit_attrs)
            criteria_list.append(criteria)

        f = sa_sql.or_(*criteria_list)
        query = query.filter(f)

    if limit is not None:
        query = query.limit(limit)

    return query


def _make_conditions_from_filters(filters, is_public=None):
    # NOTE(venkatesh) make copy of the filters are to be altered in this
    # method.
    filters = filters.copy()

    subject_conditions = []
    prop_conditions = []
    tag_conditions = []

    if is_public is not None:
        subject_conditions.append(models.Subject.is_public == is_public)

    if 'checksum' in filters:
        checksum = filters.pop('checksum')
        subject_conditions.append(models.Subject.checksum == checksum)

    if 'is_public' in filters:
        key = 'is_public'
        value = filters.pop('is_public')
        prop_filters = _make_subject_property_condition(key=key, value=value)
        prop_conditions.append(prop_filters)

    for (k, v) in filters.pop('properties', {}).items():
        prop_filters = _make_subject_property_condition(key=k, value=v)
        prop_conditions.append(prop_filters)

    if 'changes-since' in filters:
        # normalize timestamp to UTC, as sqlalchemy doesn't appear to
        # respect timezone offsets
        changes_since = timeutils.normalize_time(filters.pop('changes-since'))
        subject_conditions.append(models.Subject.updated_at > changes_since)

    if 'deleted' in filters:
        deleted_filter = filters.pop('deleted')
        subject_conditions.append(models.Subject.deleted == deleted_filter)
        # TODO(bcwaldon): handle this logic in registry server
        if not deleted_filter:
            subject_statuses = [s for s in STATUSES if s != 'killed']
            subject_conditions.append(
                models.Subject.status.in_(subject_statuses))

    if 'tags' in filters:
        tags = filters.pop('tags')
        for tag in tags:
            tag_filters = [models.SubjectTag.deleted == False]
            tag_filters.extend([models.SubjectTag.value == tag])
            tag_conditions.append(tag_filters)

    filters = {k: v for k, v in filters.items() if v is not None}

    # need to copy items because filters is modified in the loop body
    # (filters.pop(k))
    keys = list(filters.keys())
    for k in keys:
        key = k
        if k.endswith('_min') or k.endswith('_max'):
            key = key[0:-4]
            try:
                v = int(filters.pop(k))
            except ValueError:
                msg = _("Unable to filter on a range "
                        "with a non-numeric value.")
                raise exception.InvalidFilterRangeValue(msg)

            if k.endswith('_min'):
                subject_conditions.append(getattr(models.Subject, key) >= v)
            if k.endswith('_max'):
                subject_conditions.append(getattr(models.Subject, key) <= v)
        elif k in ['created_at', 'updated_at']:
            attr_value = getattr(models.Subject, key)
            operator, isotime = utils.split_filter_op(filters.pop(k))
            try:
                parsed_time = timeutils.parse_isotime(isotime)
                threshold = timeutils.normalize_time(parsed_time)
            except ValueError:
                msg = (_("Bad \"%s\" query filter format. "
                         "Use ISO 8601 DateTime notation.") % k)
                raise exception.InvalidParameterValue(msg)

            comparison = utils.evaluate_filter_op(attr_value, operator,
                                                  threshold)
            subject_conditions.append(comparison)

        elif k in ['name', 'id', 'status', 'container_format', 'disk_format']:
            attr_value = getattr(models.Subject, key)
            operator, list_value = utils.split_filter_op(filters.pop(k))
            if operator == 'in':
                threshold = utils.split_filter_value_for_quotes(list_value)
                comparison = attr_value.in_(threshold)
                subject_conditions.append(comparison)
            elif operator == 'eq':
                subject_conditions.append(attr_value == list_value)
            else:
                msg = (_("Unable to filter by unknown operator '%s'.")
                       % operator)
                raise exception.InvalidFilterOperatorValue(msg)

    for (k, value) in filters.items():
        if hasattr(models.Subject, k):
            subject_conditions.append(getattr(models.Subject, k) == value)
        else:
            prop_filters = _make_subject_property_condition(key=k, value=value)
            prop_conditions.append(prop_filters)

    return subject_conditions, prop_conditions, tag_conditions


def _make_subject_property_condition(key, value):
    prop_filters = [models.SubjectProperty.deleted == False]
    prop_filters.extend([models.SubjectProperty.name == key])
    prop_filters.extend([models.SubjectProperty.value == value])
    return prop_filters


def _select_subjects_query(context, subject_conditions, admin_as_user,
                           member_status, visibility):
    session = get_session()

    img_conditional_clause = sa_sql.and_(*subject_conditions)

    regular_user = (not context.is_admin) or admin_as_user

    query_member = session.query(models.Subject).join(
        models.Subject.members).filter(img_conditional_clause)
    if regular_user:
        member_filters = [models.SubjectMember.deleted == False]
        if context.owner is not None:
            member_filters.extend(
                [models.SubjectMember.member == context.owner])
            if member_status != 'all':
                member_filters.extend([
                    models.SubjectMember.status == member_status])
        query_member = query_member.filter(sa_sql.and_(*member_filters))

    # NOTE(venkatesh) if the 'visibility' is set to 'shared', we just
    # query the subject members table. No union is required.
    if visibility is not None and visibility == 'shared':
        return query_member

    query_subject = session.query(models.Subject).filter(img_conditional_clause)
    if regular_user:
        query_subject = query_subject.filter(models.Subject.is_public == True)
        query_subject_owner = None
        if context.owner is not None:
            query_subject_owner = session.query(models.Subject).filter(
                models.Subject.owner == context.owner).filter(
                img_conditional_clause)
        if query_subject_owner is not None:
            query = query_subject.union(query_subject_owner, query_member)
        else:
            query = query_subject.union(query_member)
        return query
    else:
        # Admin user
        return query_subject


def subject_get_all(context, filters=None, marker=None, limit=None,
                    sort_key=None, sort_dir=None,
                    member_status='accepted', is_public=None,
                    admin_as_user=False, return_tag=False):
    """
    Get all subjects that match zero or more filters.

    :param filters: dict of filter keys and values. If a 'properties'
                    key is present, it is treated as a dict of key/value
                    filters on the subject properties attribute
    :param marker: subject id after which to start page
    :param limit: maximum number of subjects to return
    :param sort_key: list of subject attributes by which results should be sorted
    :param sort_dir: directions in which results should be sorted (asc, desc)
    :param member_status: only return shared subjects that have this membership
                          status
    :param is_public: If true, return only public subjects. If false, return
                      only private and shared subjects.
    :param admin_as_user: For backwards compatibility. If true, then return to
                      an admin the equivalent set of subjects which it would see
                      if it was a regular user
    :param return_tag: To indicates whether subject entry in result includes it
                       relevant tag entries. This could improve upper-layer
                       query performance, to prevent using separated calls
    """
    sort_key = ['created_at'] if not sort_key else sort_key

    default_sort_dir = 'desc'

    if not sort_dir:
        sort_dir = [default_sort_dir] * len(sort_key)
    elif len(sort_dir) == 1:
        default_sort_dir = sort_dir[0]
        sort_dir *= len(sort_key)

    filters = filters or {}

    visibility = filters.pop('visibility', None)
    showing_deleted = 'changes-since' in filters or filters.get('deleted',
                                                                False)

    img_cond, prop_cond, tag_cond = _make_conditions_from_filters(
        filters, is_public)

    query = _select_subjects_query(context,
                                   img_cond,
                                   admin_as_user,
                                   member_status,
                                   visibility)

    if visibility is not None:
        if visibility == 'public':
            query = query.filter(models.Subject.is_public == True)
        elif visibility == 'private':
            query = query.filter(models.Subject.is_public == False)

    if prop_cond:
        for prop_condition in prop_cond:
            query = query.join(models.SubjectProperty, aliased=True).filter(
                sa_sql.and_(*prop_condition))

    if tag_cond:
        for tag_condition in tag_cond:
            query = query.join(models.SubjectTag, aliased=True).filter(
                sa_sql.and_(*tag_condition))

    marker_subject = None
    if marker is not None:
        marker_subject = _subject_get(context,
                                      marker,
                                      force_show_deleted=showing_deleted)

    for key in ['created_at', 'id']:
        if key not in sort_key:
            sort_key.append(key)
            sort_dir.append(default_sort_dir)

    query = _paginate_query(query, models.Subject, limit,
                            sort_key,
                            marker=marker_subject,
                            sort_dir=None,
                            sort_dirs=sort_dir)

    query = query.options(sa_orm.joinedload(
        models.Subject.properties)).options(
        sa_orm.joinedload(models.Subject.locations))
    if return_tag:
        query = query.options(sa_orm.joinedload(models.Subject.tags))

    subjects = []
    for subject in query.all():
        subject_dict = subject.to_dict()
        subject_dict = _normalize_locations(context, subject_dict,
                                            force_show_deleted=showing_deleted)
        if return_tag:
            subject_dict = _normalize_tags(subject_dict)
        subjects.append(subject_dict)
    return subjects


def _drop_protected_attrs(model_class, values):
    """
    Removed protected attributes from values dictionary using the models
    __protected_attributes__ field.
    """
    for attr in model_class.__protected_attributes__:
        if attr in values:
            del values[attr]


def _subject_get_disk_usage_by_owner(owner, session, subject_id=None):
    query = session.query(models.Subject)
    query = query.filter(models.Subject.owner == owner)
    if subject_id is not None:
        query = query.filter(models.Subject.id != subject_id)
    query = query.filter(models.Subject.size > 0)
    query = query.filter(~models.Subject.status.in_(['killed', 'deleted']))
    subjects = query.all()

    total = 0
    for i in subjects:
        locations = [l for l in i.locations if l['status'] != 'deleted']
        total += (i.size * len(locations))
    return total


def _validate_subject(values, mandatory_status=True):
    """
    Validates the incoming data and raises a Invalid exception
    if anything is out of order.

    :param values: Mapping of subject metadata to check
    :param mandatory_status: Whether to validate status from values
    """

    if mandatory_status:
        status = values.get('status')
        if not status:
            msg = "Subject status is required."
            raise exception.Invalid(msg)

        if status not in STATUSES:
            msg = "Invalid subject status '%s' for subject." % status
            raise exception.Invalid(msg)

    # validate integer values to eliminate DBError on save
    _validate_db_int(min_disk=values.get('min_disk'),
                     min_ram=values.get('min_ram'))

    return values


def _update_values(subject_ref, values):
    for k in values:
        if getattr(subject_ref, k) != values[k]:
            setattr(subject_ref, k, values[k])


@retry(retry_on_exception=_retry_on_deadlock, wait_fixed=500,
       stop_max_attempt_number=50)
@utils.no_4byte_params
def _subject_update(context, values, subject_id, purge_props=False,
                    from_state=None):
    """
    Used internally by subject_create and subject_update

    :param context: Request context
    :param values: A dict of attributes to set
    :param subject_id: If None, create the subject, otherwise, find and update it
    """

    # NOTE(jbresnah) values is altered in this so a copy is needed
    values = values.copy()

    session = get_session()
    with session.begin():

        # Remove the properties passed in the values mapping. We
        # handle properties separately from base subject attributes,
        # and leaving properties in the values mapping will cause
        # a SQLAlchemy model error because SQLAlchemy expects the
        # properties attribute of an Subject model to be a list and
        # not a dict.
        properties = values.pop('properties', {})

        location_data = values.pop('locations', None)

        new_status = values.get('status', None)
        if subject_id:
            subject_ref = _subject_get(context, subject_id, session=session)
            current = subject_ref.status
            # Perform authorization check
            _check_mutate_authorization(context, subject_ref)
        else:
            if values.get('size') is not None:
                values['size'] = int(values['size'])

            if 'min_ram' in values:
                values['min_ram'] = int(values['min_ram'] or 0)

            if 'min_disk' in values:
                values['min_disk'] = int(values['min_disk'] or 0)

            values['is_public'] = bool(values.get('is_public', False))
            values['protected'] = bool(values.get('protected', False))
            subject_ref = models.Subject()

        # Need to canonicalize ownership
        if 'owner' in values and not values['owner']:
            values['owner'] = None

        if subject_id:
            # Don't drop created_at if we're passing it in...
            _drop_protected_attrs(models.Subject, values)
            # NOTE(iccha-sethi): updated_at must be explicitly set in case
            #                   only SubjectProperty table was modifited
            values['updated_at'] = timeutils.utcnow()

        if subject_id:
            query = session.query(models.Subject).filter_by(id=subject_id)
            if from_state:
                query = query.filter_by(status=from_state)

            mandatory_status = True if new_status else False
            _validate_subject(values, mandatory_status=mandatory_status)

            # Validate fields for Subjects table. This is similar to what is done
            # for the query result update except that we need to do it prior
            # in this case.
            values = {key: values[key] for key in values
                      if key in subject_ref.to_dict()}
            updated = query.update(values, synchronize_session='fetch')

            if not updated:
                msg = (_('cannot transition from %(current)s to '
                         '%(next)s in update (wanted '
                         'from_state=%(from)s)') %
                       {'current': current, 'next': new_status,
                        'from': from_state})
                raise exception.Conflict(msg)

            subject_ref = _subject_get(context, subject_id, session=session)
        else:
            subject_ref.update(values)
            # Validate the attributes before we go any further. From my
            # investigation, the @validates decorator does not validate
            # on new records, only on existing records, which is, well,
            # idiotic.
            values = _validate_subject(subject_ref.to_dict())
            _update_values(subject_ref, values)

            try:
                subject_ref.save(session=session)
            except db_exception.DBDuplicateEntry:
                raise exception.Duplicate("Subject ID %s already exists!"
                                          % values['id'])

        _set_properties_for_subject(context, subject_ref, properties,
                                    purge_props,
                                    session)

        if location_data:
            _subject_locations_set(context, subject_ref.id, location_data,
                                   session=session)

    return subject_get(context, subject_ref.id)


@utils.no_4byte_params
def subject_location_add(context, subject_id, location, session=None):
    deleted = location['status'] in ('deleted', 'pending_delete')
    delete_time = timeutils.utcnow() if deleted else None
    location_ref = models.SubjectLocation(subject_id=subject_id,
                                          value=location['url'],
                                          meta_data=location['metadata'],
                                          status=location['status'],
                                          deleted=deleted,
                                          deleted_at=delete_time)
    session = session or get_session()
    location_ref.save(session=session)


@utils.no_4byte_params
def subject_location_update(context, subject_id, location, session=None):
    loc_id = location.get('id')
    if loc_id is None:
        msg = _("The location data has an invalid ID: %d") % loc_id
        raise exception.Invalid(msg)

    try:
        session = session or get_session()
        location_ref = session.query(models.SubjectLocation).filter_by(
            id=loc_id).filter_by(subject_id=subject_id).one()

        deleted = location['status'] in ('deleted', 'pending_delete')
        updated_time = timeutils.utcnow()
        delete_time = updated_time if deleted else None

        location_ref.update({"value": location['url'],
                             "meta_data": location['metadata'],
                             "status": location['status'],
                             "deleted": deleted,
                             "updated_at": updated_time,
                             "deleted_at": delete_time})
        location_ref.save(session=session)
    except sa_orm.exc.NoResultFound:
        msg = (_("No location found with ID %(loc)s from subject %(img)s") %
               dict(loc=loc_id, img=subject_id))
        LOG.warn(msg)
        raise exception.NotFound(msg)


def subject_location_delete(context, subject_id, location_id, status,
                            delete_time=None, session=None):
    if status not in ('deleted', 'pending_delete'):
        msg = _("The status of deleted subject location can only be set to "
                "'pending_delete' or 'deleted'")
        raise exception.Invalid(msg)

    try:
        session = session or get_session()
        location_ref = session.query(models.SubjectLocation).filter_by(
            id=location_id).filter_by(subject_id=subject_id).one()

        delete_time = delete_time or timeutils.utcnow()

        location_ref.update({"deleted": True,
                             "status": status,
                             "updated_at": delete_time,
                             "deleted_at": delete_time})
        location_ref.save(session=session)
    except sa_orm.exc.NoResultFound:
        msg = (_("No location found with ID %(loc)s from subject %(img)s") %
               dict(loc=location_id, img=subject_id))
        LOG.warn(msg)
        raise exception.NotFound(msg)


def _subject_locations_set(context, subject_id, locations, session=None):
    # NOTE(zhiyan): 1. Remove records from DB for deleted locations
    session = session or get_session()
    query = session.query(models.SubjectLocation).filter_by(
        subject_id=subject_id).filter_by(deleted=False)

    loc_ids = [loc['id'] for loc in locations if loc.get('id')]
    if loc_ids:
        query = query.filter(~models.SubjectLocation.id.in_(loc_ids))

    for loc_id in [loc_ref.id for loc_ref in query.all()]:
        subject_location_delete(context, subject_id, loc_id, 'deleted',
                                session=session)

    # NOTE(zhiyan): 2. Adding or update locations
    for loc in locations:
        if loc.get('id') is None:
            subject_location_add(context, subject_id, loc, session=session)
        else:
            subject_location_update(context, subject_id, loc, session=session)


def _subject_locations_delete_all(context, subject_id,
                                  delete_time=None, session=None):
    """Delete all subject locations for given subject"""
    session = session or get_session()
    location_refs = session.query(models.SubjectLocation).filter_by(
        subject_id=subject_id).filter_by(deleted=False).all()

    for loc_id in [loc_ref.id for loc_ref in location_refs]:
        subject_location_delete(context, subject_id, loc_id, 'deleted',
                                delete_time=delete_time, session=session)


@utils.no_4byte_params
def _set_properties_for_subject(context, subject_ref, properties,
                                purge_props=False, session=None):
    """
    Create or update a set of subject_properties for a given subject

    :param context: Request context
    :param subject_ref: An Subject object
    :param properties: A dict of properties to set
    :param session: A SQLAlchemy session to use (if present)
    """
    orig_properties = {}
    for prop_ref in subject_ref.properties:
        orig_properties[prop_ref.name] = prop_ref

    for name, value in six.iteritems(properties):
        prop_values = {'subject_id': subject_ref.id,
                       'name': name,
                       'value': value}
        if name in orig_properties:
            prop_ref = orig_properties[name]
            _subject_property_update(context, prop_ref, prop_values,
                                     session=session)
        else:
            subject_property_create(context, prop_values, session=session)

    if purge_props:
        for key in orig_properties.keys():
            if key not in properties:
                prop_ref = orig_properties[key]
                subject_property_delete(context, prop_ref.name,
                                        subject_ref.id, session=session)


def _subject_child_entry_delete_all(child_model_cls, subject_id,
                                    delete_time=None,
                                    session=None):
    """Deletes all the child entries for the given subject id.

    Deletes all the child entries of the given child entry ORM model class
    using the parent subject's id.

    The child entry ORM model class can be one of the following:
    model.SubjectLocation, model.SubjectProperty, model.SubjectMember and
    model.SubjectTag.

    :param child_model_cls: the ORM model class.
    :param subject_id: id of the subject whose child entries are to be deleted.
    :param delete_time: datetime of deletion to be set.
                        If None, uses current datetime.
    :param session: A SQLAlchemy session to use (if present)

    :rtype: int
    :returns: The number of child entries got soft-deleted.
    """
    session = session or get_session()

    query = session.query(child_model_cls).filter_by(
        subject_id=subject_id).filter_by(deleted=False)

    delete_time = delete_time or timeutils.utcnow()

    count = query.update({"deleted": True, "deleted_at": delete_time})
    return count


def subject_property_create(context, values, session=None):
    """Create an SubjectProperty object."""
    prop_ref = models.SubjectProperty()
    prop = _subject_property_update(context, prop_ref, values, session=session)
    return prop.to_dict()


def _subject_property_update(context, prop_ref, values, session=None):
    """
    Used internally by subject_property_create and subject_property_update.
    """
    _drop_protected_attrs(models.SubjectProperty, values)
    values["deleted"] = False
    prop_ref.update(values)
    prop_ref.save(session=session)
    return prop_ref


def subject_property_delete(context, prop_ref, subject_ref, session=None):
    """
    Used internally by subject_property_create and subject_property_update.
    """
    session = session or get_session()
    prop = session.query(models.SubjectProperty).filter_by(
        subject_id=subject_ref,
        name=prop_ref).one()
    prop.delete(session=session)
    return prop


def _subject_property_delete_all(context, subject_id, delete_time=None,
                                 session=None):
    """Delete all subject properties for given subject"""
    props_updated_count = _subject_child_entry_delete_all(
        models.SubjectProperty,
        subject_id,
        delete_time,
        session)
    return props_updated_count


def subject_member_create(context, values, session=None):
    """Create an SubjectMember object."""
    memb_ref = models.SubjectMember()
    _subject_member_update(context, memb_ref, values, session=session)
    return _subject_member_format(memb_ref)


def _subject_member_format(member_ref):
    """Format a member ref for consumption outside of this module."""
    return {
        'id': member_ref['id'],
        'subject_id': member_ref['subject_id'],
        'member': member_ref['member'],
        'can_share': member_ref['can_share'],
        'status': member_ref['status'],
        'created_at': member_ref['created_at'],
        'updated_at': member_ref['updated_at'],
        'deleted': member_ref['deleted']
    }


def subject_member_update(context, memb_id, values):
    """Update an SubjectMember object."""
    session = get_session()
    memb_ref = _subject_member_get(context, memb_id, session)
    _subject_member_update(context, memb_ref, values, session)
    return _subject_member_format(memb_ref)


def _subject_member_update(context, memb_ref, values, session=None):
    """Apply supplied dictionary of values to a Member object."""
    _drop_protected_attrs(models.SubjectMember, values)
    values["deleted"] = False
    values.setdefault('can_share', False)
    memb_ref.update(values)
    memb_ref.save(session=session)
    return memb_ref


def subject_member_delete(context, memb_id, session=None):
    """Delete an SubjectMember object."""
    session = session or get_session()
    member_ref = _subject_member_get(context, memb_id, session)
    _subject_member_delete(context, member_ref, session)


def _subject_member_delete(context, memb_ref, session):
    memb_ref.delete(session=session)


def _subject_member_delete_all(context, subject_id, delete_time=None,
                               session=None):
    """Delete all subject members for given subject"""
    members_updated_count = _subject_child_entry_delete_all(
        models.SubjectMember,
        subject_id,
        delete_time,
        session)
    return members_updated_count


def _subject_member_get(context, memb_id, session):
    """Fetch an SubjectMember entity by id."""
    query = session.query(models.SubjectMember)
    query = query.filter_by(id=memb_id)
    return query.one()


def subject_member_find(context, subject_id=None, member=None,
                        status=None, include_deleted=False):
    """Find all members that meet the given criteria.

    Note, currently include_deleted should be true only when create a new
    subject membership, as there may be a deleted subject membership between
    the same subject and tenant, the membership will be reused in this case.
    It should be false in other cases.

    :param subject_id: identifier of subject entity
    :param member: tenant to which membership has been granted
    :include_deleted: A boolean indicating whether the result should include
                      the deleted record of subject member
    """
    session = get_session()
    members = _subject_member_find(context, session, subject_id,
                                   member, status, include_deleted)
    return [_subject_member_format(m) for m in members]


def _subject_member_find(context, session, subject_id=None,
                         member=None, status=None, include_deleted=False):
    query = session.query(models.SubjectMember)
    if not include_deleted:
        query = query.filter_by(deleted=False)

    if not context.is_admin:
        query = query.join(models.Subject)
        filters = [
            models.Subject.owner == context.owner,
            models.SubjectMember.member == context.owner,
        ]
        query = query.filter(sa_sql.or_(*filters))

    if subject_id is not None:
        query = query.filter(models.SubjectMember.subject_id == subject_id)
    if member is not None:
        query = query.filter(models.SubjectMember.member == member)
    if status is not None:
        query = query.filter(models.SubjectMember.status == status)

    return query.all()


def subject_member_count(context, subject_id):
    """Return the number of subject members for this subject

    :param subject_id: identifier of subject entity
    """
    session = get_session()

    if not subject_id:
        msg = _("Subject id is required.")
        raise exception.Invalid(msg)

    query = session.query(models.SubjectMember)
    query = query.filter_by(deleted=False)
    query = query.filter(models.SubjectMember.subject_id == str(subject_id))

    return query.count()


def subject_tag_set_all(context, subject_id, tags):
    # NOTE(kragniz): tag ordering should match exactly what was provided, so a
    # subsequent call to subject_tag_get_all returns them in the correct order

    session = get_session()
    existing_tags = subject_tag_get_all(context, subject_id, session)

    tags_created = []
    for tag in tags:
        if tag not in tags_created and tag not in existing_tags:
            tags_created.append(tag)
            subject_tag_create(context, subject_id, tag, session)

    for tag in existing_tags:
        if tag not in tags:
            subject_tag_delete(context, subject_id, tag, session)


@utils.no_4byte_params
def subject_tag_create(context, subject_id, value, session=None):
    """Create an subject tag."""
    session = session or get_session()
    tag_ref = models.SubjectTag(subject_id=subject_id, value=value)
    tag_ref.save(session=session)
    return tag_ref['value']


def subject_tag_delete(context, subject_id, value, session=None):
    """Delete an subject tag."""
    _check_subject_id(subject_id)
    session = session or get_session()
    query = session.query(models.SubjectTag).filter_by(
        subject_id=subject_id).filter_by(
        value=value).filter_by(deleted=False)
    try:
        tag_ref = query.one()
    except sa_orm.exc.NoResultFound:
        raise exception.NotFound()

    tag_ref.delete(session=session)


def _subject_tag_delete_all(context, subject_id, delete_time=None,
                            session=None):
    """Delete all subject tags for given subject"""
    tags_updated_count = _subject_child_entry_delete_all(models.SubjectTag,
                                                         subject_id,
                                                         delete_time,
                                                         session)
    return tags_updated_count


def subject_tag_get_all(context, subject_id, session=None):
    """Get a list of tags for a specific subject."""
    _check_subject_id(subject_id)
    session = session or get_session()
    tags = session.query(models.SubjectTag.value).filter_by(
        subject_id=subject_id).filter_by(deleted=False).all()
    return [tag[0] for tag in tags]


class DeleteFromSelect(sa_sql.expression.UpdateBase):
    def __init__(self, table, select, column):
        self.table = table
        self.select = select
        self.column = column


# NOTE(abhishekk): MySQL doesn't yet support subquery with
# 'LIMIT & IN/ALL/ANY/SOME' We need work around this with nesting select.
@compiles(DeleteFromSelect)
def visit_delete_from_select(element, compiler, **kw):
    return "DELETE FROM %s WHERE %s in (SELECT T1.%s FROM (%s) as T1)" % (
        compiler.process(element.table, asfrom=True),
        compiler.process(element.column),
        element.column.name,
        compiler.process(element.select))


def purge_deleted_rows(context, age_in_days, max_rows, session=None):
    """Purges soft deleted rows

    Deletes rows of table subjects, table tasks and all dependent tables
    according to given age for relevant models.
    """
    # check max_rows for its maximum limit
    _validate_db_int(max_rows=max_rows)

    session = session or get_session()
    metadata = MetaData(get_engine())
    deleted_age = timeutils.utcnow() - datetime.timedelta(days=age_in_days)

    tables = []
    for model_class in models.__dict__.values():
        if not hasattr(model_class, '__tablename__'):
            continue
        if hasattr(model_class, 'deleted'):
            tables.append(model_class.__tablename__)
    # get rid of FX constraints
    for tbl in ('subjects', 'tasks'):
        try:
            tables.remove(tbl)
        except ValueError:
            LOG.warning(_LW('Expected table %(tbl)s was not found in DB.'),
                        {'tbl': tbl})
        else:
            tables.append(tbl)

    for tbl in tables:
        tab = Table(tbl, metadata, autoload=True)
        LOG.info(
            _LI('Purging deleted rows older than %(age_in_days)d day(s) '
                'from table %(tbl)s'),
            {'age_in_days': age_in_days, 'tbl': tbl})

        column = tab.c.id
        deleted_at_column = tab.c.deleted_at

        query_delete = sql.select(
            [column], deleted_at_column < deleted_age).order_by(
            deleted_at_column).limit(max_rows)

        delete_statement = DeleteFromSelect(tab, query_delete, column)

        with session.begin():
            result = session.execute(delete_statement)

        rows = result.rowcount
        LOG.info(_LI('Deleted %(rows)d row(s) from table %(tbl)s'),
                 {'rows': rows, 'tbl': tbl})


def user_get_storage_usage(context, owner_id, subject_id=None, session=None):
    _check_subject_id(subject_id)
    session = session or get_session()
    total_size = _subject_get_disk_usage_by_owner(
        owner_id, session, subject_id=subject_id)
    return total_size


def _task_info_format(task_info_ref):
    """Format a task info ref for consumption outside of this module"""
    if task_info_ref is None:
        return {}
    return {
        'task_id': task_info_ref['task_id'],
        'input': task_info_ref['input'],
        'result': task_info_ref['result'],
        'message': task_info_ref['message'],
    }


def _task_info_create(context, task_id, values, session=None):
    """Create an TaskInfo object"""
    session = session or get_session()
    task_info_ref = models.TaskInfo()
    task_info_ref.task_id = task_id
    task_info_ref.update(values)
    task_info_ref.save(session=session)
    return _task_info_format(task_info_ref)


def _task_info_update(context, task_id, values, session=None):
    """Update an TaskInfo object"""
    session = session or get_session()
    task_info_ref = _task_info_get(context, task_id, session=session)
    if task_info_ref:
        task_info_ref.update(values)
        task_info_ref.save(session=session)
    return _task_info_format(task_info_ref)


def _task_info_get(context, task_id, session=None):
    """Fetch an TaskInfo entity by task_id"""
    session = session or get_session()
    query = session.query(models.TaskInfo)
    query = query.filter_by(task_id=task_id)
    try:
        task_info_ref = query.one()
    except sa_orm.exc.NoResultFound:
        LOG.debug("TaskInfo was not found for task with id %(task_id)s",
                  {'task_id': task_id})
        task_info_ref = None

    return task_info_ref


def task_create(context, values, session=None):
    """Create a task object"""

    values = values.copy()
    session = session or get_session()
    with session.begin():
        task_info_values = _pop_task_info_values(values)

        task_ref = models.Task()
        _task_update(context, task_ref, values, session=session)

        _task_info_create(context,
                          task_ref.id,
                          task_info_values,
                          session=session)

    return task_get(context, task_ref.id, session)


def _pop_task_info_values(values):
    task_info_values = {}
    for k, v in values.items():
        if k in ['input', 'result', 'message']:
            values.pop(k)
            task_info_values[k] = v

    return task_info_values


def task_update(context, task_id, values, session=None):
    """Update a task object"""

    session = session or get_session()

    with session.begin():
        task_info_values = _pop_task_info_values(values)

        task_ref = _task_get(context, task_id, session)
        _drop_protected_attrs(models.Task, values)

        values['updated_at'] = timeutils.utcnow()

        _task_update(context, task_ref, values, session)

        if task_info_values:
            _task_info_update(context,
                              task_id,
                              task_info_values,
                              session)

    return task_get(context, task_id, session)


def task_get(context, task_id, session=None, force_show_deleted=False):
    """Fetch a task entity by id"""
    task_ref = _task_get(context, task_id, session=session,
                         force_show_deleted=force_show_deleted)
    return _task_format(task_ref, task_ref.info)


def task_delete(context, task_id, session=None):
    """Delete a task"""
    session = session or get_session()
    task_ref = _task_get(context, task_id, session=session)
    task_ref.delete(session=session)
    return _task_format(task_ref, task_ref.info)


def _task_soft_delete(context, session=None):
    """Scrub task entities which are expired """
    expires_at = models.Task.expires_at
    session = session or get_session()
    query = session.query(models.Task)

    query = (query.filter(models.Task.owner == context.owner)
             .filter_by(deleted=0)
             .filter(expires_at <= timeutils.utcnow()))
    values = {'deleted': 1, 'deleted_at': timeutils.utcnow()}

    with session.begin():
        query.update(values)


def task_get_all(context, filters=None, marker=None, limit=None,
                 sort_key='created_at', sort_dir='desc', admin_as_user=False):
    """
    Get all tasks that match zero or more filters.

    :param filters: dict of filter keys and values.
    :param marker: task id after which to start page
    :param limit: maximum number of tasks to return
    :param sort_key: task attribute by which results should be sorted
    :param sort_dir: direction in which results should be sorted (asc, desc)
    :param admin_as_user: For backwards compatibility. If true, then return to
                      an admin the equivalent set of tasks which it would see
                      if it were a regular user
    :returns: tasks set
    """
    filters = filters or {}

    session = get_session()
    query = session.query(models.Task)

    if not (context.is_admin or admin_as_user) and context.owner is not None:
        query = query.filter(models.Task.owner == context.owner)

    _task_soft_delete(context, session=session)

    showing_deleted = False

    if 'deleted' in filters:
        deleted_filter = filters.pop('deleted')
        query = query.filter_by(deleted=deleted_filter)
        showing_deleted = deleted_filter

    for (k, v) in filters.items():
        if v is not None:
            key = k
            if hasattr(models.Task, key):
                query = query.filter(getattr(models.Task, key) == v)

    marker_task = None
    if marker is not None:
        marker_task = _task_get(context, marker,
                                force_show_deleted=showing_deleted)

    sort_keys = ['created_at', 'id']
    if sort_key not in sort_keys:
        sort_keys.insert(0, sort_key)

    query = _paginate_query(query, models.Task, limit,
                            sort_keys,
                            marker=marker_task,
                            sort_dir=sort_dir)

    task_refs = query.all()

    tasks = []
    for task_ref in task_refs:
        tasks.append(_task_format(task_ref, task_info_ref=None))

    return tasks


def _is_task_visible(context, task):
    """Return True if the task is visible in this context."""
    # Is admin == task visible
    if context.is_admin:
        return True

    # No owner == task visible
    if task['owner'] is None:
        return True

    # Perform tests based on whether we have an owner
    if context.owner is not None:
        if context.owner == task['owner']:
            return True

    return False


def _task_get(context, task_id, session=None, force_show_deleted=False):
    """Fetch a task entity by id"""
    session = session or get_session()
    query = session.query(models.Task).options(
        sa_orm.joinedload(models.Task.info)
    ).filter_by(id=task_id)

    if not force_show_deleted and not context.can_see_deleted:
        query = query.filter_by(deleted=False)
    try:
        task_ref = query.one()
    except sa_orm.exc.NoResultFound:
        LOG.debug("No task found with ID %s", task_id)
        raise exception.TaskNotFound(task_id=task_id)

    # Make sure the task is visible
    if not _is_task_visible(context, task_ref):
        msg = "Forbidding request, task %s is not visible" % task_id
        LOG.debug(msg)
        raise exception.Forbidden(msg)

    return task_ref


def _task_update(context, task_ref, values, session=None):
    """Apply supplied dictionary of values to a task object."""
    if 'deleted' not in values:
        values["deleted"] = False
    task_ref.update(values)
    task_ref.save(session=session)
    return task_ref


def _task_format(task_ref, task_info_ref=None):
    """Format a task ref for consumption outside of this module"""
    task_dict = {
        'id': task_ref['id'],
        'type': task_ref['type'],
        'status': task_ref['status'],
        'owner': task_ref['owner'],
        'expires_at': task_ref['expires_at'],
        'created_at': task_ref['created_at'],
        'updated_at': task_ref['updated_at'],
        'deleted_at': task_ref['deleted_at'],
        'deleted': task_ref['deleted']
    }

    if task_info_ref:
        task_info_dict = {
            'input': task_info_ref['input'],
            'result': task_info_ref['result'],
            'message': task_info_ref['message'],
        }
        task_dict.update(task_info_dict)

    return task_dict
