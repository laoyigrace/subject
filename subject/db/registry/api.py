# Copyright 2013 Red Hat, Inc.
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

"""
This is the Registry's Driver API.

This API relies on the registry RPC client (version >= 2). The functions bellow
work as a proxy for the database back-end configured in the registry service,
which means that everything returned by that back-end will be also returned by
this API.


This API exists for supporting deployments not willing to put database
credentials in subject-api. Those deployments can rely on this registry driver
that will talk to a remote registry service, which will then access the
database back-end.
"""

import functools

from subject import glare
from subject.registry.client.v2 import api


def configure():
    api.configure_registry_client()


def _get_client(func):
    """Injects a client instance to the each function

    This decorator creates an instance of the Registry
    client and passes it as an argument to each function
    in this API.
    """
    @functools.wraps(func)
    def wrapper(context, *args, **kwargs):
        client = api.get_registry_client(context)
        return func(client, *args, **kwargs)
    return wrapper


@_get_client
def subject_create(client, values):
    """Create an subject from the values dictionary."""
    return client.subject_create(values=values)


@_get_client
def subject_update(client, subject_id, values, purge_props=False, from_state=None):
    """
    Set the given properties on an subject and update it.

    :raises: SubjectNotFound if subject does not exist.
    """
    return client.subject_update(values=values,
                               subject_id=subject_id,
                               purge_props=purge_props, from_state=from_state)


@_get_client
def subject_destroy(client, subject_id):
    """Destroy the subject or raise if it does not exist."""
    return client.subject_destroy(subject_id=subject_id)


@_get_client
def subject_get(client, subject_id, force_show_deleted=False):
    return client.subject_get(subject_id=subject_id,
                            force_show_deleted=force_show_deleted)


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


@_get_client
def subject_get_all(client, filters=None, marker=None, limit=None,
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
    :param sort_key: subject attribute by which results should be sorted
    :param sort_dir: direction in which results should be sorted (asc, desc)
    :param member_status: only return shared subjects that have this membership
                          status
    :param is_public: If true, return only public subjects. If false, return
                      only private and shared subjects.
    :param admin_as_user: For backwards compatibility. If true, then return to
                      an admin the equivalent set of subjects which it would see
                      if it were a regular user
    :param return_tag: To indicates whether subject entry in result includes it
                       relevant tag entries. This could improve upper-layer
                       query performance, to prevent using separated calls
    """
    sort_key = ['created_at'] if not sort_key else sort_key
    sort_dir = ['desc'] if not sort_dir else sort_dir
    return client.subject_get_all(filters=filters, marker=marker, limit=limit,
                                sort_key=sort_key, sort_dir=sort_dir,
                                member_status=member_status,
                                is_public=is_public,
                                admin_as_user=admin_as_user,
                                return_tag=return_tag)


@_get_client
def subject_property_create(client, values, session=None):
    """Create an SubjectProperty object"""
    return client.subject_property_create(values=values)


@_get_client
def subject_property_delete(client, prop_ref, subject_ref, session=None):
    """
    Used internally by _subject_property_create and subject_property_update
    """
    return client.subject_property_delete(prop_ref=prop_ref, subject_ref=subject_ref)


@_get_client
def subject_member_create(client, values, session=None):
    """Create an SubjectMember object"""
    return client.subject_member_create(values=values)


@_get_client
def subject_member_update(client, memb_id, values):
    """Update an SubjectMember object"""
    return client.subject_member_update(memb_id=memb_id, values=values)


@_get_client
def subject_member_delete(client, memb_id, session=None):
    """Delete an SubjectMember object"""
    client.subject_member_delete(memb_id=memb_id)


@_get_client
def subject_member_find(client, subject_id=None, member=None, status=None,
                      include_deleted=False):
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
    return client.subject_member_find(subject_id=subject_id,
                                    member=member,
                                    status=status,
                                    include_deleted=include_deleted)


@_get_client
def subject_member_count(client, subject_id):
    """Return the number of subject members for this subject

    :param subject_id: identifier of subject entity
    """
    return client.subject_member_count(subject_id=subject_id)


@_get_client
def subject_tag_set_all(client, subject_id, tags):
    client.subject_tag_set_all(subject_id=subject_id, tags=tags)


@_get_client
def subject_tag_create(client, subject_id, value, session=None):
    """Create an subject tag."""
    return client.subject_tag_create(subject_id=subject_id, value=value)


@_get_client
def subject_tag_delete(client, subject_id, value, session=None):
    """Delete an subject tag."""
    client.subject_tag_delete(subject_id=subject_id, value=value)


@_get_client
def subject_tag_get_all(client, subject_id, session=None):
    """Get a list of tags for a specific subject."""
    return client.subject_tag_get_all(subject_id=subject_id)


@_get_client
def subject_location_delete(client, subject_id, location_id, status, session=None):
    """Delete an subject location."""
    client.subject_location_delete(subject_id=subject_id, location_id=location_id,
                                 status=status)


@_get_client
def subject_location_update(client, subject_id, location, session=None):
    """Update subject location."""
    client.subject_location_update(subject_id=subject_id, location=location)


@_get_client
def user_get_storage_usage(client, owner_id, subject_id=None, session=None):
    return client.user_get_storage_usage(owner_id=owner_id, subject_id=subject_id)


@_get_client
def task_get(client, task_id, session=None, force_show_deleted=False):
    """Get a single task object
    :returns: task dictionary
    """
    return client.task_get(task_id=task_id, session=session,
                           force_show_deleted=force_show_deleted)


@_get_client
def task_get_all(client, filters=None, marker=None, limit=None,
                 sort_key='created_at', sort_dir='desc', admin_as_user=False):
    """Get all tasks that match zero or more filters.

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
    return client.task_get_all(filters=filters, marker=marker, limit=limit,
                               sort_key=sort_key, sort_dir=sort_dir,
                               admin_as_user=admin_as_user)


@_get_client
def task_create(client, values, session=None):
    """Create a task object"""
    return client.task_create(values=values, session=session)


@_get_client
def task_delete(client, task_id, session=None):
    """Delete a task object"""
    return client.task_delete(task_id=task_id, session=session)


@_get_client
def task_update(client, task_id, values, session=None):
    return client.task_update(task_id=task_id, values=values, session=session)


# Metadef
@_get_client
def metadef_namespace_get_all(
        client, marker=None, limit=None, sort_key='created_at',
        sort_dir=None, filters=None, session=None):
    return client.metadef_namespace_get_all(
        marker=marker, limit=limit,
        sort_key=sort_key, sort_dir=sort_dir, filters=filters)


@_get_client
def metadef_namespace_get(client, namespace_name, session=None):
    return client.metadef_namespace_get(namespace_name=namespace_name)


@_get_client
def metadef_namespace_create(client, values, session=None):
    return client.metadef_namespace_create(values=values)


@_get_client
def metadef_namespace_update(
        client, namespace_id, namespace_dict,
        session=None):
    return client.metadef_namespace_update(
        namespace_id=namespace_id, namespace_dict=namespace_dict)


@_get_client
def metadef_namespace_delete(client, namespace_name, session=None):
    return client.metadef_namespace_delete(
        namespace_name=namespace_name)


@_get_client
def metadef_object_get_all(client, namespace_name, session=None):
    return client.metadef_object_get_all(
        namespace_name=namespace_name)


@_get_client
def metadef_object_get(
        client,
        namespace_name, object_name, session=None):
    return client.metadef_object_get(
        namespace_name=namespace_name, object_name=object_name)


@_get_client
def metadef_object_create(
        client,
        namespace_name, object_dict, session=None):
    return client.metadef_object_create(
        namespace_name=namespace_name, object_dict=object_dict)


@_get_client
def metadef_object_update(
        client,
        namespace_name, object_id,
        object_dict, session=None):
    return client.metadef_object_update(
        namespace_name=namespace_name, object_id=object_id,
        object_dict=object_dict)


@_get_client
def metadef_object_delete(
        client,
        namespace_name, object_name,
        session=None):
    return client.metadef_object_delete(
        namespace_name=namespace_name, object_name=object_name)


@_get_client
def metadef_object_delete_namespace_content(
        client,
        namespace_name, session=None):
    return client.metadef_object_delete_namespace_content(
        namespace_name=namespace_name)


@_get_client
def metadef_object_count(
        client,
        namespace_name, session=None):
    return client.metadef_object_count(
        namespace_name=namespace_name)


@_get_client
def metadef_property_get_all(
        client,
        namespace_name, session=None):
    return client.metadef_property_get_all(
        namespace_name=namespace_name)


@_get_client
def metadef_property_get(
        client,
        namespace_name, property_name,
        session=None):
    return client.metadef_property_get(
        namespace_name=namespace_name, property_name=property_name)


@_get_client
def metadef_property_create(
        client,
        namespace_name, property_dict,
        session=None):
    return client.metadef_property_create(
        namespace_name=namespace_name, property_dict=property_dict)


@_get_client
def metadef_property_update(
        client,
        namespace_name, property_id,
        property_dict, session=None):
    return client.metadef_property_update(
        namespace_name=namespace_name, property_id=property_id,
        property_dict=property_dict)


@_get_client
def metadef_property_delete(
        client,
        namespace_name, property_name,
        session=None):
    return client.metadef_property_delete(
        namespace_name=namespace_name, property_name=property_name)


@_get_client
def metadef_property_delete_namespace_content(
        client,
        namespace_name, session=None):
    return client.metadef_property_delete_namespace_content(
        namespace_name=namespace_name)


@_get_client
def metadef_property_count(
        client,
        namespace_name, session=None):
    return client.metadef_property_count(
        namespace_name=namespace_name)


@_get_client
def metadef_resource_type_create(client, values, session=None):
    return client.metadef_resource_type_create(values=values)


@_get_client
def metadef_resource_type_get(
        client,
        resource_type_name, session=None):
    return client.metadef_resource_type_get(
        resource_type_name=resource_type_name)


@_get_client
def metadef_resource_type_get_all(client, session=None):
    return client.metadef_resource_type_get_all()


@_get_client
def metadef_resource_type_delete(
        client,
        resource_type_name, session=None):
    return client.metadef_resource_type_delete(
        resource_type_name=resource_type_name)


@_get_client
def metadef_resource_type_association_get(
        client,
        namespace_name, resource_type_name,
        session=None):
    return client.metadef_resource_type_association_get(
        namespace_name=namespace_name, resource_type_name=resource_type_name)


@_get_client
def metadef_resource_type_association_create(
        client,
        namespace_name, values, session=None):
    return client.metadef_resource_type_association_create(
        namespace_name=namespace_name, values=values)


@_get_client
def metadef_resource_type_association_delete(
        client,
        namespace_name, resource_type_name, session=None):
    return client.metadef_resource_type_association_delete(
        namespace_name=namespace_name, resource_type_name=resource_type_name)


@_get_client
def metadef_resource_type_association_get_all_by_namespace(
        client,
        namespace_name, session=None):
    return client.metadef_resource_type_association_get_all_by_namespace(
        namespace_name=namespace_name)


@_get_client
def metadef_tag_get_all(client, namespace_name, filters=None, marker=None,
                        limit=None, sort_key='created_at', sort_dir=None,
                        session=None):
    return client.metadef_tag_get_all(
        namespace_name=namespace_name, filters=filters, marker=marker,
        limit=limit, sort_key=sort_key, sort_dir=sort_dir, session=session)


@_get_client
def metadef_tag_get(client, namespace_name, name, session=None):
    return client.metadef_tag_get(
        namespace_name=namespace_name, name=name)


@_get_client
def metadef_tag_create(
        client, namespace_name, tag_dict, session=None):
    return client.metadef_tag_create(
        namespace_name=namespace_name, tag_dict=tag_dict)


@_get_client
def metadef_tag_create_tags(
        client, namespace_name, tag_list, session=None):
    return client.metadef_tag_create_tags(
        namespace_name=namespace_name, tag_list=tag_list)


@_get_client
def metadef_tag_update(
        client, namespace_name, id, tag_dict, session=None):
    return client.metadef_tag_update(
        namespace_name=namespace_name, id=id, tag_dict=tag_dict)


@_get_client
def metadef_tag_delete(
        client, namespace_name, name, session=None):
    return client.metadef_tag_delete(
        namespace_name=namespace_name, name=name)


@_get_client
def metadef_tag_delete_namespace_content(
        client, namespace_name, session=None):
    return client.metadef_tag_delete_namespace_content(
        namespace_name=namespace_name)


@_get_client
def metadef_tag_count(client, namespace_name, session=None):
    return client.metadef_tag_count(namespace_name=namespace_name)


@_get_client
def artifact_create(client, values,
                    type_name, type_version=None, session=None):
    return client.artifact_create(values=values,
                                  type_name=type_name,
                                  type_version=type_version)


@_get_client
def artifact_update(client, values, artifact_id,
                    type_name, type_version=None, session=None):
    return client.artifact_update(values=values, artifact_id=artifact_id,
                                  type_name=type_name,
                                  type_version=type_version)


@_get_client
def artifact_delete(client, artifact_id,
                    type_name, type_version=None, session=None):
    return client.artifact_delete(artifact_id=artifact_id,
                                  type_name=type_name,
                                  type_version=type_version)


@_get_client
def artifact_get(client, artifact_id,
                 type_name, type_version=None, session=None):
    return client.artifact_get(artifact_id=artifact_id,
                               type_name=type_name,
                               type_version=type_version)


@_get_client
def artifact_get_all(client, marker=None, limit=None, sort_key=None,
                     sort_dir=None, filters=None,
                     show_level=glare.Showlevel.NONE, session=None):
    if filters is None:
        filters = {}
    return client.artifact_create(marker, limit, sort_key,
                                  sort_dir, filters, show_level)


@_get_client
def artifact_publish(client, artifact_id,
                     type_name, type_version=None, session=None):
    return client.artifact_publish(artifact_id=artifact_id,
                                   type_name=type_name,
                                   type_version=type_version)
