..
      Copyright 2015 OpenStack Foundation
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

============================
Glance database architecture
============================

Glance Database Public API
~~~~~~~~~~~~~~~~~~~~~~~~~~

The Glance Database API contains several methods for moving subject metadata to
and from persistent storage. You can find a list of public methods grouped by
category below.

Common parameters for subject methods
-----------------------------------

The following parameters can be applied to all of the subject methods below:
 - ``context`` — corresponds to a glance.context.RequestContext
   object, which stores the information on how a user accesses
   the system, as well as additional request information.
 - ``subject_id`` — a string corresponding to the subject identifier.
 - ``memb_id`` — a string corresponding to the member identifier
   of the subject.

Subject basic methods
-------------------

**Subject processing methods:**

#. ``subject_create(context, values)`` — creates a new subject record
   with parameters listed in the *values* dictionary. Returns a
   dictionary representation of a newly created
   *glance.db.sqlalchemy.models.Subject* object.
#. ``subject_update(context, subject_id, values, purge_props=False,
   from_state=None)`` — updates the existing subject with the identifier
   *subject_id* with the values listed in the *values* dictionary. Returns a
   dictionary representation of the updated *Subject* object.

 Optional parameters are:
     - ``purge_props`` — a flag indicating that all the existing
       properties not listed in the *values['properties']* should be
       deleted;
     - ``from_state`` — a string filter indicating that the updated
       subject must be in the specified state.

#. ``subject_destroy(context, subject_id)`` — deletes all database
   records of an subject with the identifier *subject_id* (like tags,
   properties, and members) and sets a 'deleted' status on all the
   subject locations.
#. ``subject_get(context, subject_id, force_show_deleted=False)`` —
   gets an subject with the identifier *subject_id* and returns its
   dictionary representation. The parameter *force_show_deleted* is
   a flag that indicates to show subject info even if it was
   'deleted', or its 'pending_delete' statuses.
#. ``subject_get_all(context, filters=None, marker=None, limit=None,
   sort_key=None, sort_dir=None, member_status='accepted',
   is_public=None, admin_as_user=False, return_tag=False)`` — gets
   all the subjects that match zero or more filters.

 Optional parameters are:
     - ``filters`` — dictionary of filter keys and values. If a 'properties'
       key is present, it is treated as a dictionary of key/value filters in
       the attribute of the subject properties.
     - ``marker`` — subject id after which a page should start.
     - ``limit`` — maximum number of subjects to return.
     - ``sort_key`` — list of subject attributes by which results should
       be sorted.
     - ``sort_dir`` — direction in which results should be sorted
       (asc, desc).
     - ``member_status`` — only returns shared subjects that have this
       membership status.
     - ``is_public`` — if true, returns only public subjects. If false,
       returns only private and shared subjects.
     - ``admin_as_user`` — for backwards compatibility. If true, an admin
       sees the same set of subjects that would be seen by a regular user.
     - ``return_tag`` — indicates whether an subject entry in the result
       includes its relevant tag entries. This can improve upper-layer
       query performance and avoid using separate calls.

Subject location methods
----------------------

**Subject location processing methods:**

#. ``subject_location_add(context, subject_id, location)`` —
   adds a new location to an subject with the identifier *subject_id*. This
   location contains values listed in the dictionary *location*.
#. ``subject_location_update(context, subject_id, location)`` — updates
   an existing location with the identifier *location['id']*
   for an subject with the identifier *subject_id* with values listed in
   the dictionary *location*.
#. ``subject_location_delete(context, subject_id, location_id, status,
   delete_time=None)`` — sets a 'deleted' or 'pending_delete'
   *status* to an existing location record with the identifier
   *location_id* for an subject with the identifier *subject_id*.

Subject property methods
----------------------

.. warning:: There is no public property update method.
   So if you want to modify it, you have to delete it first
   and then create a new one.

**Subject property processing methods:**

#. ``subject_property_create(context, values)`` — creates
   a property record with parameters listed in the *values* dictionary
   for an subject with *values['id']*. Returns a dictionary representation
   of a newly created *SubjectProperty* object.
#. ``subject_property_delete(context, prop_ref, subject_ref)`` — deletes an
   existing property record with a name *prop_ref* for an subject with
   the identifier *subject_ref*.

Subject member methods
--------------------

**Methods to handle subject memberships:**

#. ``subject_member_create(context, values)`` — creates a member record
   with properties listed in the *values* dictionary for an subject
   with *values['id']*. Returns a dictionary representation
   of a newly created *SubjectMember* object.
#. ``subject_member_update(context, memb_id, values)`` — updates an
   existing member record with properties listed in the *values*
   dictionary for an subject with *values['id']*. Returns a dictionary
   representation of an updated member record.
#. ``subject_member_delete(context, memb_id)`` — deletes  an existing
   member record with *memb_id*.
#. ``subject_member_find(context, subject_id=None, member=None, status=None)``
   — returns all members for a given context with optional subject
   identifier (*subject_id*), member name (*member*), and member status
   (*status*) parameters.
#. ``subject_member_count(context, subject_id)`` — returns a number of subject
   members for an subject with *subject_id*.

Subject tag methods
-----------------

**Methods to process subjects tags:**

#. ``subject_tag_set_all(context, subject_id, tags)`` — changes all the
   existing tags for an subject with *subject_id* to the tags listed
   in the *tags* param. To remove all tags, a user just should provide
   an empty list.
#. ``subject_tag_create(context, subject_id, value)`` — adds a *value*
   to tags for an subject with *subject_id*. Returns the value of a
   newly created tag.
#. ``subject_tag_delete(context, subject_id, value)`` — removes a *value*
   from tags for an subject with *subject_id*.
#. ``subject_tag_get_all(context, subject_id)`` — returns a list of tags
   for a specific subject.

Subject info methods
------------------

The next two methods inform a user about his or her ability to modify
and view an subject. The *subject* parameter here is a dictionary representation
of an *Subject* object.

#. ``is_subject_mutable(context, subject)`` — informs a user
   about the possibility to modify an subject with the given context.
   Returns True if the subject is mutable in this context.
#. ``is_subject_visible(context, subject, status=None)`` — informs about
   the possibility to see the subject details with the given context
   and optionally with a status. Returns True if the subject is visible
   in this context.

**Glance database schema**

.. figure:: /subjects/glance_db.png
   :figwidth: 100%
   :align: center
   :alt: The glance database schema is depicted by 5 tables.
         The table named Subjects has the following columns:
         id: varchar(36);
         name: varchar(255), nullable;
         size: bigint(20), nullable;
         status: varchar(30);
         is_public: tinyint(1);
         created_at: datetime;
         updated_at: datetime, nullable;
         deleted_at: datetime, nullable;
         deleted: tinyint(1);
         disk_format: varchar(20), nullable;
         container_format: varchar(20), nullable;
         checksum: varchar(32), nullable;
         owner: varchar(255), nullable
         min_disk: int(11);
         min_ram: int(11);
         protected: tinyint(1); and
         virtual_size: bigint(20), nullable;.
         The table named subject_locations has the following columns:
         id: int(11), primary;
         subject_id: varchar(36), refers to column named id in table Subjects;
         value: text;
         created_at: datetime;
         updated_at: datetime, nullable;
         deleted_at: datetime, nullable;
         deleted: tinyint(1);
         meta_data: text, nullable; and
         status: varchar(30);.
         The table named subject_members has the following columns:
         id: int(11), primary;
         subject_id: varchar(36), refers to column named id in table Subjects;
         member: varchar(255);
         can_share: tinyint(1);
         created_at: datetime;
         updated_at: datetime, nullable;
         deleted_at: datetime, nullable;
         deleted: tinyint(1); and
         status: varchar(20;.
         The table named subject_tags has the following columns:
         id: int(11), primary;
         subject_id: varchar(36), refers to column named id in table Subjects;
         value: varchar(255);
         created_at: datetime;
         updated_at: datetime, nullable;
         deleted_at: datetime, nullable; and
         deleted: tinyint(1);.
         The table named subject_properties has the following columns:
         id: int(11), primary;
         subject_id: varchar(36), refers to column named id in table Subjects;
         name: varchar(255);
         value: text, nullable;
         created_at: datetime;
         updated_at: datetime, nullable;
         deleted_at: datetime, nullable; and
         deleted: tinyint(1);.


.. centered:: Subject 1. Glance subjects DB schema


Glance Database Backends
~~~~~~~~~~~~~~~~~~~~~~~~

Migration Backends
------------------

.. list-plugins:: glance.database.migration_backend
   :detailed:

Metadata Backends
-----------------

.. list-plugins:: glance.database.metadata_backend
   :detailed:
