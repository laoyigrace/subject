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

Subject Statuses
==============

Images in Glance can be in one the following statuses:

* ``queued``

  The subject identifier has been reserved for an subject in the Glance
  registry. No subject data has been uploaded to Glance and the subject
  size was not explicitly set to zero on creation.

* ``saving``

  Denotes that an subject's raw data is currently being uploaded to Glance.
  When an subject is registered with a call to `POST /subjects` and there
  is an `x-subject-meta-location` header present, that subject will never be in
  the `saving` status (as the subject data is already available in some other
  location).

* ``active``

  Denotes an subject that is fully available in Glance. This occurs when
  the subject data is uploaded, or the subject size is explicitly set to
  zero on creation.

* ``deactivated``

  Denotes that access to subject data is not allowed to any non-admin user.
  Prohibiting downloads of an subject also prohibits operations like subject
  export and subject cloning that may require subject data.

* ``killed``

  Denotes that an error occurred during the uploading of an subject's data,
  and that the subject is not readable.

* ``deleted``

  Glance has retained the information about the subject, but it is no longer
  available to use. An subject in this state will be removed automatically
  at a later date.

* ``pending_delete``

  This is similar to `deleted`, however, Glance has not yet removed the
  subject data. An subject in this state is not recoverable.


.. figure:: /subjects/subject_status_transition.png
   :figwidth: 100%
   :align: center
   :alt: The states consist of:
         "queued", "saving", "active", "pending_delete", "deactivated",
         "killed", and "deleted".
         The transitions consist of:
         An initial transition to the "queued" state called "create subject".
         A transition from the "queued" state to the "active" state
         called "add location".
         A transition from the "queued" state to the "saving" state
         called "upload".
         A transition from the "queued" state to the "deleted" state
         called "delete".
         A transition from the "saving" state to the "active" state
         called "upload succeeded".
         A transition from the "saving" state to the "deleted" state
         called "delete".
         A transition from the "saving" state to the "killed" state
         called "[v1] upload fail".
         A transition from the "saving" state to the "queued" state
         called "[v2] upload fail".
         A transition from the "active" state to the "deleted" state
         called "delete".
         A transition from the "active" state to the "pending_delete" state
         called "delayed delete".
         A transition from the "active" state to the "deactivated" state
         called "deactivate".
         A transition from the "killed" state to the "deleted" state
         called "deleted".
         A transition from the "pending_delete" state to the "deleted" state
         called "after scrub time".
         A transition from the "deactivated" state to the "deleted" state
         called "delete".
         A transition from the "deactivated" state to the "active" state
         called "reactivate".
         There are no transitions out of the "deleted" state.


   This is a representation of how the subject move from one status to the next.

   * Add location from zero to more than one.

Task Statuses
=============

Tasks in Glance can be in one the following statuses:

* ``pending``

  The task identifier has been reserved for a task in the Glance.
  No processing has begun on it yet.

* ``processing``

  The task has been picked up by the underlying executor and is being run
  using the backend Glance execution logic for that task type.

* ``success``

  Denotes that the task has had a successful run within Glance. The ``result``
  field of the task shows more details about the outcome.

* ``failure``

  Denotes that an error occurred during the execution of the task and it
  cannot continue processing. The ``message`` field of the task shows what the
  error was.
