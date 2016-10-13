..
      Copyright 2010 OpenStack Foundation
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

Using Glance's Subject Public APIs
================================

Glance is the reference implementation of the OpenStack Images API.  As such,
Glance fully implements versions 1 and 2 of the Images API.

.. include:: deprecation-note.inc

There used to be a sentence here saying, "The Images API specification is
developed alongside Glance, but is not considered part of the Glance project."
That's only partially true (or completely false, depending upon how strict you
are about these things).  Conceptually, the OpenStack Images API is an
independent definition of a REST API.  In practice, however, the only way
to participate in the evolution of the Images API is to work with the Glance
community to define the new functionality and provide its reference
implementation. Further, Glance falls under the "designated sections" provision
of the OpenStack DefCore Guidelines, which basically means that in order to
qualify as "OpenStack", a cloud exposing an OpenStack Images API must include
the Glance Images API implementation code.  Thus, although conceptually
independent, the OpenStack Images APIs are intimately associated with Glance.

**References**

* `Designated sections (definition) <http://git.openstack.org/cgit/openstack/defcore/tree/doc/source/process/Lexicon.rst#n54>`_

* `2014-04-02 DefCore Designated Sections Guidelines <https://governance.openstack.org/resolutions/20140402-defcore-designated-sections-guidelines.html>`_

* `OpenStack Core Definition <https://github.com/openstack/defcore/blob/master/doc/source/process/CoreDefinition.rst>`_

* `DefCore Guidelines Repository <https://github.com/openstack/defcore>`_

Glance and the Images APIs: Past, Present, and Future
-----------------------------------------------------

Here's a quick summary of the Images APIs that have been implemented by Glance.
If you're interested in more details, you can consult the Release Notes for all
the OpenStack releases (beginning with "Bexar") to follow the evolution of
features in Glance and the Images APIs.

Images v1 API
*************

The v1 API was originally designed as a service API for use by Nova and other
OpenStack services. In the Kilo release, the v1.1 API was downgraded from
CURRENT to SUPPORTED. In the Newton release, the version 1 API is officially
declared DEPRECATED.

During the deprecation period, the Images v1 API is closed to further
development.  The Glance code implementing the v1 API accepts only serious
bugfixes.

Since Folsom, it has been possible to deploy OpenStack without exposing the
Images v1 API to end users.  The Compute v2 API contains subject-related API
calls allowing users to list subjects, list subjects details, show subject details
for a specific subject, delete subjects, and manipulate subject metadata.  Nova acts
as a proxy to Glance for these subject-related calls.  It's important to note
that the subject-related calls in the Compute v2 API are a proper subset of the
calls available in the Images APIs.

In the Newton release, Nova (and other OpenStack services that consume subjects)
have been modified to use the Images v2 API by default.

**Reference**

* `OpenStack Standard Deprecation Requirements <https://governance.openstack.org/reference/tags/assert_follows-standard-deprecation.html#requirements>`_

Images v2 API
*************

The v2 API is the CURRENT OpenStack Images API.  It provides a more friendly
interface to consumers than did the v1 API, as it was specifically designed to
expose subjects-related functionality as a public-facing endpoint.  It's the
version that's currently open to development.

A common strategy is to deploy multiple Glance nodes: internal-facing nodes
providing the Images APIs for internal consumers like Nova, and external-facing
nodes providing the Images v2 API for public use.

The Future
**********

During the long and tumultuous design phase of what has since become an
independent service named "Glare" (the Glance Artifacts Repository), the Glance
community loosely spoke about the Artifacts API being "Glance v3".  This,
however, was only a shorthand way of speaking of the Artifacts effort.  The
Artifacts API can't be the Images v3 API since Artifacts are not the same as
Images.  Conceptually, a virtual machine subject could be an Artifact, and the
Glare code has been designed to be compatible with the Images v2 API.  But at
this time, there are no plans to implement an Images v3 API.

During the Newton development cycle, Glare became an independent OpenStack
project.  While it's evident that there's a need for an Artifact Repository in
OpenStack, whether it will be as ubiquitous as the need for an Images
Repository isn't clear.  On the other hand, industry trends could go in the
opposite direction where everyone needs Artifacts and deployers view subjects as
simply another type of digital artifact.  As Yogi Berra, an experienced
manager, once said, "It's tough to make predictions, especially about the
future."

Authentication
--------------

Glance depends on Keystone and the OpenStack Identity API to handle
authentication of clients. You must obtain an authentication token from
Keystone using and send it along with all API requests to Glance through
the ``X-Auth-Token`` header. Glance will communicate back to Keystone to
verify the token validity and obtain your identity credentials.

See :doc:`authentication` for more information on integrating with Keystone.

Using v1.X
----------

.. include:: deprecation-note.inc

For the purpose of examples, assume there is a Glance API server running
at the URL ``http://glance.openstack.example.org`` on the default port 80.

List Available Images
*********************

We want to see a list of available subjects that the authenticated user has
access to. This includes subjects owned by the user, subjects shared with the user
and public subjects.

We issue a ``GET`` request to ``http://glance.openstack.example.org/v1/subjects`` to
retrieve this list of available subjects. The data is returned as a JSON-encoded
mapping in the following format::

  {'subjects': [
    {'uri': 'http://glance.openstack.example.org/v1/subjects/71c675ab-d94f-49cd-a114-e12490b328d9',
     'name': 'Ubuntu 10.04 Plain',
     'disk_format': 'vhd',
     'container_format': 'ovf',
     'size': '5368709120'}
    ...]}


List Available Images in More Detail
************************************

We want to see a more detailed list of available subjects that the authenticated
user has access to. This includes subjects owned by the user, subjects shared with
the user and public subjects.

We issue a ``GET`` request to ``http://glance.openstack.example.org/v1/subjects/detail`` to
retrieve this list of available subjects. The data is returned as a
JSON-encoded mapping in the following format::

  {'subjects': [
    {'uri': 'http://glance.openstack.example.org/v1/subjects/71c675ab-d94f-49cd-a114-e12490b328d9',
     'name': 'Ubuntu 10.04 Plain 5GB',
     'disk_format': 'vhd',
     'container_format': 'ovf',
     'size': '5368709120',
     'checksum': 'c2e5db72bd7fd153f53ede5da5a06de3',
     'created_at': '2010-02-03 09:34:01',
     'updated_at': '2010-02-03 09:34:01',
     'deleted_at': '',
     'status': 'active',
     'is_public': true,
     'min_ram': 256,
     'min_disk': 5,
     'owner': null,
     'properties': {'distro': 'Ubuntu 10.04 LTS'}},
    ...]}

.. note::

  All timestamps returned are in UTC.

  The `updated_at` timestamp is the timestamp when an subject's metadata
  was last updated, not its subject data, as all subject data is immutable
  once stored in Glance.

  The `properties` field is a mapping of free-form key/value pairs that
  have been saved with the subject metadata.

  The `checksum` field is an MD5 checksum of the subject file data.

  The `is_public` field is a boolean indicating whether the subject is
  publicly available.

  The `min_ram` field is an integer specifying the minimum amount of
  RAM needed to run this subject on an instance, in megabytes.

  The `min_disk` field is an integer specifying the minimum amount of
  disk space needed to run this subject on an instance, in gigabytes.

  The `owner` field is a string which may either be null or which will
  indicate the owner of the subject.

Filtering Images Lists
**********************

Both the ``GET /v1/subjects`` and ``GET /v1/subjects/detail`` requests take query
parameters that serve to filter the returned list of subjects. The following
list details these query parameters.

* ``name=NAME``

  Filters subjects having a ``name`` attribute matching ``NAME``.

* ``container_format=FORMAT``

  Filters subjects having a ``container_format`` attribute matching ``FORMAT``

  For more information, see :doc:`About Disk and Container Formats <formats>`

* ``disk_format=FORMAT``

  Filters subjects having a ``disk_format`` attribute matching ``FORMAT``

  For more information, see :doc:`About Disk and Container Formats <formats>`

* ``status=STATUS``

  Filters subjects having a ``status`` attribute matching ``STATUS``

  For more information, see :doc:`About Subject Statuses <statuses>`

* ``size_min=BYTES``

  Filters subjects having a ``size`` attribute greater than or equal to ``BYTES``

* ``size_max=BYTES``

  Filters subjects having a ``size`` attribute less than or equal to ``BYTES``

These two resources also accept additional query parameters:

* ``sort_key=KEY``

  Results will be ordered by the specified subject attribute ``KEY``. Accepted
  values include ``id``, ``name``, ``status``, ``disk_format``,
  ``container_format``, ``size``, ``created_at`` (default) and ``updated_at``.

* ``sort_dir=DIR``

  Results will be sorted in the direction ``DIR``. Accepted values are ``asc``
  for ascending or ``desc`` (default) for descending.

* ``marker=ID``

  An subject identifier marker may be specified. When present, only subjects which
  occur after the identifier ``ID`` will be listed. (These are the subjects that
  have a `sort_key` later than that of the marker ``ID`` in the `sort_dir`
  direction.)

* ``limit=LIMIT``

  When present, the maximum number of results returned will not exceed ``LIMIT``.

.. note::

  If the specified ``LIMIT`` exceeds the operator defined limit (api_limit_max)
  then the number of results returned may be less than ``LIMIT``.

* ``is_public=PUBLIC``

  An admin user may use the `is_public` parameter to control which results are
  returned.

  When the `is_public` parameter is absent or set to `True` the following subjects
  will be listed: Images whose `is_public` field is `True`, owned subjects and
  shared subjects.

  When the `is_public` parameter is set to `False` the following subjects will be
  listed: Images (owned, shared, or non-owned) whose `is_public` field is `False`.

  When the `is_public` parameter is set to `None` all subjects will be listed
  irrespective of owner, shared status or the `is_public` field.

.. note::

  Use of the `is_public` parameter is restricted to admin users. For all other
  users it will be ignored.

Retrieve Subject Metadata
***********************

We want to see detailed information for a specific virtual machine subject
that the Glance server knows about.

We have queried the Glance server for a list of subjects and the
data returned includes the `uri` field for each available subject. This
`uri` field value contains the exact location needed to get the metadata
for a specific subject.

Continuing the example from above, in order to get metadata about the
first subject returned, we can issue a ``HEAD`` request to the Glance
server for the subject's URI.

We issue a ``HEAD`` request to
``http://glance.openstack.example.org/v1/subjects/71c675ab-d94f-49cd-a114-e12490b328d9`` to
retrieve complete metadata for that subject. The metadata is returned as a
set of HTTP headers that begin with the prefix ``x-subject-meta-``. The
following shows an example of the HTTP headers returned from the above
``HEAD`` request::

  x-subject-meta-uri              http://glance.openstack.example.org/v1/subjects/71c675ab-d94f-49cd-a114-e12490b328d9
  x-subject-meta-name             Ubuntu 10.04 Plain 5GB
  x-subject-meta-disk_format      vhd
  x-subject-meta-container_format ovf
  x-subject-meta-size             5368709120
  x-subject-meta-checksum         c2e5db72bd7fd153f53ede5da5a06de3
  x-subject-meta-created_at       2010-02-03 09:34:01
  x-subject-meta-updated_at       2010-02-03 09:34:01
  x-subject-meta-deleted_at
  x-subject-meta-status           available
  x-subject-meta-is_public        true
  x-subject-meta-min_ram          256
  x-subject-meta-min_disk         0
  x-subject-meta-owner            null
  x-subject-meta-property-distro  Ubuntu 10.04 LTS

.. note::

  All timestamps returned are in UTC.

  The `x-subject-meta-updated_at` timestamp is the timestamp when an
  subject's metadata was last updated, not its subject data, as all
  subject data is immutable once stored in Glance.

  There may be multiple headers that begin with the prefix
  `x-subject-meta-property-`. These headers are free-form key/value pairs
  that have been saved with the subject metadata. The key is the string
  after `x-subject-meta-property-` and the value is the value of the header.

  The response's `ETag` header will always be equal to the
  `x-subject-meta-checksum` value.

  The response's `x-subject-meta-is_public` value is a boolean indicating
  whether the subject is publicly available.

  The response's `x-subject-meta-owner` value is a string which may either
  be null or which will indicate the owner of the subject.


Retrieve Raw Subject Data
***********************

We want to retrieve that actual raw data for a specific virtual machine subject
that the Glance server knows about.

We have queried the Glance server for a list of subjects and the
data returned includes the `uri` field for each available subject. This
`uri` field value contains the exact location needed to get the metadata
for a specific subject.

Continuing the example from above, in order to get metadata about the
first subject returned, we can issue a ``HEAD`` request to the Glance
server for the subject's URI.

We issue a ``GET`` request to
``http://glance.openstack.example.org/v1/subjects/71c675ab-d94f-49cd-a114-e12490b328d9`` to
retrieve metadata for that subject as well as the subject itself encoded
into the response body.

The metadata is returned as a set of HTTP headers that begin with the
prefix ``x-subject-meta-``. The following shows an example of the HTTP headers
returned from the above ``GET`` request::

  x-subject-meta-uri              http://glance.openstack.example.org/v1/subjects/71c675ab-d94f-49cd-a114-e12490b328d9
  x-subject-meta-name             Ubuntu 10.04 Plain 5GB
  x-subject-meta-disk_format      vhd
  x-subject-meta-container_format ovf
  x-subject-meta-size             5368709120
  x-subject-meta-checksum         c2e5db72bd7fd153f53ede5da5a06de3
  x-subject-meta-created_at       2010-02-03 09:34:01
  x-subject-meta-updated_at       2010-02-03 09:34:01
  x-subject-meta-deleted_at
  x-subject-meta-status           available
  x-subject-meta-is_public        true
  x-subject-meta-min_ram          256
  x-subject-meta-min_disk         5
  x-subject-meta-owner            null
  x-subject-meta-property-distro  Ubuntu 10.04 LTS

.. note::

  All timestamps returned are in UTC.

  The `x-subject-meta-updated_at` timestamp is the timestamp when an
  subject's metadata was last updated, not its subject data, as all
  subject data is immutable once stored in Glance.

  There may be multiple headers that begin with the prefix
  `x-subject-meta-property-`. These headers are free-form key/value pairs
  that have been saved with the subject metadata. The key is the string
  after `x-subject-meta-property-` and the value is the value of the header.

  The response's `Content-Length` header shall be equal to the value of
  the `x-subject-meta-size` header.

  The response's `ETag` header will always be equal to the
  `x-subject-meta-checksum` value.

  The response's `x-subject-meta-is_public` value is a boolean indicating
  whether the subject is publicly available.

  The response's `x-subject-meta-owner` value is a string which may either
  be null or which will indicate the owner of the subject.

  The subject data itself will be the body of the HTTP response returned
  from the request, which will have content-type of
  `application/octet-stream`.


Add a New Subject
***************

We have created a new virtual machine subject in some way (created a
"golden subject" or snapshotted/backed up an existing subject) and we
wish to do two things:

 * Store the disk subject data in Glance
 * Store metadata about this subject in Glance

We can do the above two activities in a single call to the Glance API.
Assuming, like in the examples above, that a Glance API server is running
at ``http://glance.openstack.example.org``, we issue a ``POST`` request to add an subject to
Glance::

  POST http://glance.openstack.example.org/v1/subjects

The metadata about the subject is sent to Glance in HTTP headers. The body
of the HTTP request to the Glance API will be the MIME-encoded disk
subject data.


Reserve a New Subject
*******************

We can also perform the activities described in `Add a New Subject`_ using two
separate calls to the Subject API; the first to register the subject metadata, and
the second to add the subject disk data. This is known as "reserving" an subject.

The first call should be a ``POST`` to ``http://glance.openstack.example.org/v1/subjects``,
which will result in a new subject id being registered with a status of
``queued``::

  {'subject':
   {'status': 'queued',
    'id': '71c675ab-d94f-49cd-a114-e12490b328d9',
    ...}
   ...}

The subject data can then be added using a ``PUT`` to
``http://glance.openstack.example.org/v1/subjects/71c675ab-d94f-49cd-a114-e12490b328d9``.
The subject status will then be set to ``active`` by Glance.


**Subject Metadata in HTTP Headers**

Glance will view as subject metadata any HTTP header that it receives in a
``POST`` request where the header key is prefixed with the strings
``x-subject-meta-`` and ``x-subject-meta-property-``.

The list of metadata headers that Glance accepts are listed below.

* ``x-subject-meta-name``

  This header is required, unless reserving an subject. Its value should be the
  name of the subject.

  Note that the name of an subject *is not unique to a Glance node*. It
  would be an unrealistic expectation of users to know all the unique
  names of all other user's subjects.

* ``x-subject-meta-id``

  This header is optional.

  When present, Glance will use the supplied identifier for the subject.
  If the identifier already exists in that Glance node, then a
  **409 Conflict** will be returned by Glance. The value of the header
  must be a uuid in hexadecimal string notation
  (that is 71c675ab-d94f-49cd-a114-e12490b328d9).

  When this header is *not* present, Glance will generate an identifier
  for the subject and return this identifier in the response (see below).

* ``x-subject-meta-store``

  This header is optional. Valid values are one of ``file``, ``rbd``,
  ``swift``, ``cinder``, ``sheepdog`` or ``vsphere``.

  When present, Glance will attempt to store the disk subject data in the
  backing store indicated by the value of the header. If the Glance node
  does not support the backing store, Glance will return a **400 Bad Request**.

  When not present, Glance will store the disk subject data in the backing
  store that is marked as default. See the configuration option ``default_store``
  for more information.

* ``x-subject-meta-disk_format``

  This header is required, unless reserving an subject. Valid values are one of
  ``aki``, ``ari``, ``ami``, ``raw``, ``iso``, ``vhd``, ``vhdx``, ``vdi``,
  ``qcow2``, or ``vmdk``.

  For more information, see :doc:`About Disk and Container Formats <formats>`.

* ``x-subject-meta-container_format``

  This header is required, unless reserving an subject. Valid values are one of
  ``aki``, ``ari``, ``ami``, ``bare``, ``ova``, ``ovf``, or ``docker``.

  For more information, see :doc:`About Disk and Container Formats <formats>`.

* ``x-subject-meta-size``

  This header is optional.

  When present, Glance assumes that the expected size of the request body
  will be the value of this header. If the length in bytes of the request
  body *does not match* the value of this header, Glance will return a
  **400 Bad Request**.

  When not present, Glance will calculate the subject's size based on the size
  of the request body.

* ``x-subject-meta-checksum``

  This header is optional. When present, it specifies the **MD5** checksum
  of the subject file data.

  When present, Glance will verify the checksum generated from the back-end
  store while storing your subject against this value and return a
  **400 Bad Request** if the values do not match.

* ``x-subject-meta-is_public``

  This header is optional.

  When Glance finds the string "true" (case-insensitive), the subject is marked as
  a public one, meaning that any user may view its metadata and may read
  the disk subject from Glance.

  When not present, the subject is assumed to be *not public* and owned by
  a user.

* ``x-subject-meta-min_ram``

  This header is optional. When present, it specifies the minimum amount of
  RAM in megabytes required to run this subject on a server.

  When not present, the subject is assumed to have a minimum RAM requirement of 0.

* ``x-subject-meta-min_disk``

  This header is optional. When present, it specifies the expected minimum disk
  space in gigabytes required to run this subject on a server.

  When not present, the subject is assumed to have a minimum disk space
  requirement of 0.

* ``x-subject-meta-owner``

  This header is optional and only meaningful for admins.

  Glance normally sets the owner of an subject to be the tenant or user
  (depending on the "owner_is_tenant" configuration option) of the
  authenticated user issuing the request. However, if the authenticated user
  has the Admin role, this default may be overridden by setting this header to
  null or to a string identifying the owner of the subject.

* ``x-subject-meta-property-*``

  When Glance receives any HTTP header whose key begins with the string prefix
  ``x-subject-meta-property-``, Glance adds the key and value to a set of custom,
  free-form subject properties stored with the subject. The key is a
  lower-cased string following the prefix ``x-subject-meta-property-`` with dashes
  and punctuation replaced with underscores.

  For example, if the following HTTP header were sent::

    x-subject-meta-property-distro  Ubuntu 10.10

  then a key/value pair of "distro"/"Ubuntu 10.10" will be stored with the
  subject in Glance.

  There is no limit on the number of free-form key/value attributes that can
  be attached to the subject. However, keep in mind that the 8K limit on the
  size of all the HTTP headers sent in a request will effectively limit the
  number of subject properties.


Update an Subject
***************

Glance will consider any HTTP header that it receives in a ``PUT`` request
as an instance of subject metadata. In this case, the header key should be
prefixed with the strings ``x-subject-meta-`` and ``x-subject-meta-property-``.

If an subject was previously reserved, and thus is in the ``queued`` state, then
subject data can be added by including it as the request body. If the subject
already has data associated with it (for example, it is not in the ``queued``
state), then including a request body will result in a **409 Conflict**
exception.

On success, the ``PUT`` request will return the subject metadata encoded as HTTP
headers.

See more about subject statuses here: :doc:`Subject Statuses <statuses>`


List Subject Memberships
**********************

We want to see a list of the other system tenants (or users, if
"owner_is_tenant" is False) that may access a given virtual machine subject that
the Glance server knows about. We take the `uri` field of the subject data,
append ``/members`` to it, and issue a ``GET`` request on the resulting URL.

Continuing from the example above, in order to get the memberships for the
first subject returned, we can issue a ``GET`` request to the Glance
server for
``http://glance.openstack.example.org/v1/subjects/71c675ab-d94f-49cd-a114-e12490b328d9/members``.
And we will get back JSON data such as the following::

  {'members': [
   {'member_id': 'tenant1',
    'can_share': false}
   ...]}

The `member_id` field identifies a tenant with which the subject is shared. If
that tenant is authorized to further share the subject, the `can_share` field is
`true`.


List Shared Images
******************

We want to see a list of subjects which are shared with a given tenant. We issue
a ``GET`` request to ``http://glance.openstack.example.org/v1/shared-subjects/tenant1``. We
will get back JSON data such as the following::

  {'shared_subjects': [
   {'subject_id': '71c675ab-d94f-49cd-a114-e12490b328d9',
    'can_share': false}
   ...]}

The `subject_id` field identifies an subject shared with the tenant named by
*member_id*. If the tenant is authorized to further share the subject, the
`can_share` field is `true`.


Add a Member to an Subject
************************

We want to authorize a tenant to access a private subject. We issue a ``PUT``
request to
``http://glance.openstack.example.org/v1/subjects/71c675ab-d94f-49cd-a114-e12490b328d9/members/tenant1``.
With no body, this will add the membership to the subject, leaving existing
memberships unmodified and defaulting new memberships to have `can_share`
set to `false`. We may also optionally attach a body of the following form::

  {'member':
   {'can_share': true}
  }

If such a body is provided, both existing and new memberships will have
`can_share` set to the provided value (either `true` or `false`). This query
will return a 204 ("No Content") status code.


Remove a Member from an Subject
*****************************

We want to revoke a tenant's right to access a private subject. We issue a
``DELETE`` request to ``http://glance.openstack.example.org/v1/subjects/1/members/tenant1``.
This query will return a 204 ("No Content") status code.


Replace a Membership List for an Subject
**************************************

The full membership list for a given subject may be replaced. We issue a ``PUT``
request to
``http://glance.openstack.example.org/v1/subjects/71c675ab-d94f-49cd-a114-e12490b328d9/members``
with a body of the following form::

  {'memberships': [
   {'member_id': 'tenant1',
    'can_share': false}
   ...]}

All existing memberships which are not named in the replacement body are
removed, and those which are named have their `can_share` settings changed as
specified. (The `can_share` setting may be omitted, which will cause that
setting to remain unchanged in the existing memberships.) All new memberships
will be created, with `can_share` defaulting to `false` unless it is specified
otherwise.


Subject Membership Changes in Version 2.0
---------------------------------------

Version 2.0 of the Images API eliminates the ``can_share`` attribute of subject
membership. In the version 2.0 model, subject sharing is not transitive.

In version 2.0, subject members have a ``status`` attribute that reflects
how the subject should be treated with respect to that subject member's subject-list.

* The ``status`` attribute may have one of three values: ``pending``,
  ``accepted``, or ``rejected``.

* By default, only those shared subjects with status ``accepted`` are included in
  an subject member's subject-list.

* Only an subject member may change his/her own membership status.

* Only an subject owner may create members on an subject. The status of a newly
  created subject member is ``pending``. The subject owner cannot change the
  status of a member.


Distinctions from Version 1.x API Calls
***************************************

* The response to a request to list the members of an subject has changed.

  call: ``GET`` on ``/v2/subjects/{subjectId}/members``

  response: see the JSON schema at ``/v2/schemas/members``

* The request body in the call to create an subject member has changed.

  call: ``POST`` to ``/v2/subjects/{subjectId}/members``

  request body::

  { "member": "<MEMBER_ID>" }

  where the {memberId} is the tenant ID of the subject member.

  The member status of a newly created subject member is ``pending``.

New API Calls
*************

* Change the status of an subject member

  call: ``PUT`` on  ``/v2/subjects/{subjectId}/members/{memberId}``

  request body::

  { "status": "<STATUS_VALUE>" }

  where <STATUS_VALUE> is ``pending``, ``accepted``, or ``rejected``.
  The {memberId} is the tenant ID of the subject member.

Images v2 Tasks API
-------------------

Version 2 of the OpenStack Images API introduces a Task resource that is used
to create and monitor long-running asynchronous subject-related processes.  See
the :doc:`Tasks <tasks>` section of the Glance documentation for more
information.

The following Task calls are available:

Create a Task
*************

A user wants to initiate a task.  The user issues a ``POST`` request to
``/v2/tasks``.  The request body is of Content-type ``application/json`` and
must contain the following fields:

* ``type``: a string specified by the enumeration defined in the Task schema

* ``input``: a JSON object.  The content is defined by the cloud provider who
  has exposed the endpoint being contacted

The response is a Task entity as defined by the Task schema.  It includes an
``id`` field that can be used in a subsequent call to poll the task for status
changes.

A task is created in ``pending`` status.

Show a Task
***********

A user wants to see detailed information about a task the user owns.  The user
issues a ``GET`` request to ``/v2/tasks/{taskId}``.

The response is in ``application/json`` format.  The exact structure is given
by the task schema located at ``/v2/schemas/task``.

List Tasks
**********

A user wants to see what tasks have been created in his or her project.  The
user issues a ``GET`` request to ``/v2/tasks``.

The response is in ``application/json`` format.  The exact structure is given
by the task schema located at ``/v2/schemas/tasks``.

Note that, as indicated by the schema, the list of tasks is provided in a
sparse format.  To see more information about a particular task in the list,
the user would use the show task call described above.

Filtering and Sorting the Tasks List
************************************

The ``GET /v2/tasks`` request takes query parameters that server to filter the
returned list of tasks.  The following list details these query parameters.

* ``status={status}``

  Filters the list to display only those tasks in the specified status.  See
  the task schema or the :doc:`Task Statuses <statuses>` section of this
  documentation for the legal values to use for ``{status}``.

  For example, a request to ``GET /v2/tasks?status=pending`` would return only
  those tasks whose current status is ``pending``.

* ``type={type}``

  Filters the list to display only those tasks of the specified type.  See the
  enumeration defined in the task schema for the legal values to use for
  ``{type}``.

  For example, a request to ``GET /v2/tasks?type=import`` would return only
  import tasks.

* ``sort_dir={direction}``

  Sorts the list of tasks according to ``updated_at`` datetime.  Legal values
  are ``asc`` (ascending) and ``desc`` (descending).  By default, the task list
  is sorted by ``created_at`` time in descending chronological order.




API Message Localization
------------------------
Glance supports HTTP message localization. For example, an HTTP client can
receive API messages in Chinese even if the locale language of the server is
English.

How to use it
*************
To receive localized API messages, the HTTP client needs to specify the
**Accept-Language** header to indicate the language that will translate the
message. For more information about Accept-Language, please refer to http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html

A typical curl API request will be like below::

   curl -i -X GET -H 'Accept-Language: zh' -H 'Content-Type: application/json'
   http://glance.openstack.example.org/v2/subjects/aaa

Then the response will be like the following::

   HTTP/1.1 404 Not Found
   Content-Length: 234
   Content-Type: text/html; charset=UTF-8
   X-Openstack-Request-Id: req-54d403a0-064e-4544-8faf-4aeef086f45a
   Date: Sat, 22 Feb 2014 06:26:26 GMT

   <html>
   <head>
   <title>404 Not Found</title>
   </head>
   <body>
   <h1>404 Not Found</h1>
   &#25214;&#19981;&#21040;&#20219;&#20309;&#20855;&#26377;&#26631;&#35782; aaa &#30340;&#26144;&#20687;<br /><br />
   </body>
   </html>

.. note::
   Make sure to have a language package under /usr/share/locale-langpack/ on
   the target Glance server.
