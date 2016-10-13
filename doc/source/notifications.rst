..
      Copyright 2011-2013 OpenStack Foundation
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

Notifications
=============

Notifications can be generated for several events in the subject lifecycle.
These can be used for auditing, troubleshooting, etc.

Notification Drivers
--------------------

* log

  This driver uses the standard Python logging infrastructure with
  the notifications ending up in file specified by the log_file
  configuration directive.

* messaging

  This strategy sends notifications to a message queue configured
  using oslo.messaging configuration options.

* noop

  This strategy produces no notifications. It is the default strategy.

Notification Types
------------------

* ``subject.create``

  Emitted when an subject record is created in Glance.  Subject record creation is
  independent of subject data upload.

* ``subject.prepare``

  Emitted when Glance begins uploading subject data to its store.

* ``subject.upload``

  Emitted when Glance has completed the upload of subject data to its store.

* ``subject.activate``

  Emitted when an subject goes to `active` status.  This occurs when Glance
  knows where the subject data is located.

* ``subject.send``

  Emitted upon completion of an subject being sent to a consumer.

* ``subject.update``

  Emitted when an subject record is updated in Glance.

* ``subject.delete``

  Emitted when an subject deleted from Glance.

* ``task.run``

  Emitted when a task is picked up by the executor to be run.

* ``task.processing``

  Emitted when a task is sent over to the executor to begin processing.

* ``task.success``

  Emitted when a task is successfully completed.

* ``task.failure``

  Emitted when a task fails.

Content
-------

Every message contains a handful of attributes.

* message_id

  UUID identifying the message.

* publisher_id

  The hostname of the glance instance that generated the message.

* event_type

  Event that generated the message.

* priority

  One of WARN, INFO or ERROR.

* timestamp

  UTC timestamp of when event was generated.

* payload

  Data specific to the event type.

Payload
-------

* subject.send

  The payload for INFO, WARN, and ERROR events contain the following:

  subject_id
    ID of the subject (UUID)
  owner_id
    Tenant or User ID that owns this subject (string)
  receiver_tenant_id
    Tenant ID of the account receiving the subject (string)
  receiver_user_id
    User ID of the account receiving the subject (string)
  destination_ip
    The receiver's IP address to which the subject was sent (string)
  bytes_sent
    The number of bytes actually sent

* subject.create

  For INFO events, it is the subject metadata.
  WARN and ERROR events contain a text message in the payload.

* subject.prepare

  For INFO events, it is the subject metadata.
  WARN and ERROR events contain a text message in the payload.

* subject.upload

  For INFO events, it is the subject metadata.
  WARN and ERROR events contain a text message in the payload.

* subject.activate

  For INFO events, it is the subject metadata.
  WARN and ERROR events contain a text message in the payload.

* subject.update

  For INFO events, it is the subject metadata.
  WARN and ERROR events contain a text message in the payload.

* subject.delete

  For INFO events, it is the subject id.
  WARN and ERROR events contain a text message in the payload.

* task.run

  The payload for INFO, WARN, and ERROR events contain the following:

  task_id
    ID of the task (UUID)
  owner
    Tenant or User ID that created this task (string)
  task_type
    Type of the task. Example, task_type is "import". (string)
  status,
    status of the task. Status can be "pending", "processing",
    "success" or "failure". (string)
  task_input
    Input provided by the user when attempting to create a task. (dict)
  result
    Resulting output from a successful task. (dict)
  message
    Message shown in the task if it fails. None if task succeeds. (string)
  expires_at
    UTC time at which the task would not be visible to the user. (string)
  created_at
    UTC time at which the task was created. (string)
  updated_at
    UTC time at which the task was latest updated. (string)

  The exceptions are:-
    For INFO events, it is the task dict with result and message as None.
    WARN and ERROR events contain a text message in the payload.

* task.processing

  For INFO events, it is the task dict with result and message as None.
  WARN and ERROR events contain a text message in the payload.

* task.success

  For INFO events, it is the task dict with message as None and result is a
  dict.
  WARN and ERROR events contain a text message in the payload.

* task.failure

  For INFO events, it is the task dict with result as None and message is
  text.
  WARN and ERROR events contain a text message in the payload.
