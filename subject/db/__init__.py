# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2010-2012 OpenStack Foundation
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

from oslo_config import cfg
from oslo_utils import importutils
from wsme.rest import json

from subject.common import crypt
from subject.common import exception
#from subject.common.glare import serialization
from subject.common import location_strategy
import subject.domain
import subject.domain.proxy
from subject.i18n import _

CONF = cfg.CONF
CONF.import_opt('subject_size_cap', 'subject.common.config')
CONF.import_opt('metadata_encryption_key', 'subject.common.config')


def get_api():
    api = importutils.import_module(CONF.data_api)
    if hasattr(api, 'configure'):
        api.configure()
    return api


def unwrap(db_api):
    return db_api


# attributes common to all models
BASE_MODEL_ATTRS = set(['id', 'created_at', 'updated_at', 'deleted_at',
                        'deleted'])


IMAGE_ATTRS = BASE_MODEL_ATTRS | set(['name', 'status', 'size', 'virtual_size',
                                      'disk_format', 'container_format',
                                      'min_disk', 'min_ram', 'is_public',
                                      'locations', 'checksum', 'owner',
                                      'protected'])


class SubjectRepo(object):

    def __init__(self, context, db_api):
        self.context = context
        self.db_api = db_api

    def get(self, subject_id):
        try:
            db_api_subject = dict(self.db_api.subject_get(self.context, subject_id))
            if db_api_subject['deleted']:
                raise exception.SubjectNotFound()
        except (exception.SubjectNotFound, exception.Forbidden):
            msg = _("No subject found with ID %s") % subject_id
            raise exception.SubjectNotFound(msg)
        tags = self.db_api.subject_tag_get_all(self.context, subject_id)
        subject = self._format_subject_from_db(db_api_subject, tags)
        return SubjectProxy(subject, self.context, self.db_api)

    def list(self, marker=None, limit=None, sort_key=None,
             sort_dir=None, filters=None, member_status='accepted'):
        sort_key = ['created_at'] if not sort_key else sort_key
        sort_dir = ['desc'] if not sort_dir else sort_dir
        db_api_subjects = self.db_api.subject_get_all(
            self.context, filters=filters, marker=marker, limit=limit,
            sort_key=sort_key, sort_dir=sort_dir,
            member_status=member_status, return_tag=True)
        subjects = []
        for db_api_subject in db_api_subjects:
            db_subject = dict(db_api_subject)
            subject = self._format_subject_from_db(db_subject, db_subject['tags'])
            subjects.append(subject)
        return subjects

    def _format_subject_from_db(self, db_subject, db_tags):
        visibility = 'public' if db_subject['is_public'] else 'private'
        properties = {}
        for prop in db_subject.pop('properties'):
            # NOTE(markwash) db api requires us to filter deleted
            if not prop['deleted']:
                properties[prop['name']] = prop['value']
        locations = [loc for loc in db_subject['locations']
                     if loc['status'] == 'active']
        if CONF.metadata_encryption_key:
            key = CONF.metadata_encryption_key
            for l in locations:
                l['url'] = crypt.urlsafe_decrypt(key, l['url'])
        return subject.domain.Subject(
            subject_id=db_subject['id'],
            name=db_subject['name'],
            status=db_subject['status'],
            created_at=db_subject['created_at'],
            updated_at=db_subject['updated_at'],
            visibility=visibility,
            type=db_subject['type'],
            subject_format=db_subject['subject_format'],
            protected=db_subject['protected'],
            locations=location_strategy.get_ordered_locations(locations),
            checksum=db_subject['checksum'],
            owner=db_subject['owner'],
            tar_format=db_subject['tar_format'],
            contributor=db_subject['contributor'],
            size=db_subject['size'],
            phase=db_subject['phase'],
            language=db_subject['language'],
            score=db_subject['score'],
            knowledge=db_subject['knowledge'],
            description=db_subject['description'],
            subject=db_subject['subject'],
            extra_properties=properties,
            tags=db_tags
        )

    def _format_subject_to_db(self, subject):
        locations = subject.locations
        if CONF.metadata_encryption_key:
            key = CONF.metadata_encryption_key
            ld = []
            for loc in locations:
                url = crypt.urlsafe_encrypt(key, loc['url'])
                ld.append({'url': url, 'metadata': loc['metadata'],
                           'status': loc['status'],
                           # NOTE(zhiyan): New location has no ID field.
                           'id': loc.get('id')})
            locations = ld
        return {
            'id': subject.subject_id,
            'name': subject.name,
            'status': subject.status,
            'created_at': subject.created_at,
            'type': subject.type,
            'subject_format': subject.subject_format,
            'protected': subject.protected,
            'locations': locations,
            'checksum': subject.checksum,
            'owner': subject.owner,
            'tar_format': subject.tar_format,
            'contributor': subject.contributor,
            'size': subject.size,
            'phase': subject.phase,
            'language': subject.language,
            'score': subject.score,
            'knowledge': subject.knowledge,
            'description': subject.description,
            'subject': subject.subject,
            'is_public': subject.visibility == 'public',
            'properties': dict(subject.extra_properties),
        }

    def add(self, subject):
        subject_values = self._format_subject_to_db(subject)
        if (subject_values['size'] is not None
           and subject_values['size'] > CONF.subject_size_cap):
            raise exception.SubjectSizeLimitExceeded
        # the updated_at value is not set in the _format_subject_to_db
        # function since it is specific to subject create
        subject_values['updated_at'] = subject.updated_at
        new_values = self.db_api.subject_create(self.context, subject_values)
        self.db_api.subject_tag_set_all(self.context,
                                      subject.subject_id, subject.tags)
        subject.created_at = new_values['created_at']
        subject.updated_at = new_values['updated_at']

    def save(self, subject, from_state=None):
        subject_values = self._format_subject_to_db(subject)
        if (subject_values['size'] is not None
           and subject_values['size'] > CONF.subject_size_cap):
            raise exception.SubjectSizeLimitExceeded
        try:
            new_values = self.db_api.subject_update(self.context,
                                                  subject.subject_id,
                                                  subject_values,
                                                  purge_props=True,
                                                  from_state=from_state)
        except (exception.SubjectNotFound, exception.Forbidden):
            msg = _("No subject found with ID %s") % subject.subject_id
            raise exception.SubjectNotFound(msg)
        self.db_api.subject_tag_set_all(self.context, subject.subject_id,
                                      subject.tags)
        subject.updated_at = new_values['updated_at']

    def remove(self, subject):
        try:
            self.db_api.subject_update(self.context, subject.subject_id,
                                     {'status': subject.status},
                                     purge_props=True)
        except (exception.SubjectNotFound, exception.Forbidden):
            msg = _("No subject found with ID %s") % subject.subject_id
            raise exception.SubjectNotFound(msg)
        # NOTE(markwash): don't update tags?
        new_values = self.db_api.subject_destroy(self.context, subject.subject_id)
        subject.updated_at = new_values['updated_at']


class SubjectProxy(subject.domain.proxy.Subject):

    def __init__(self, subject, context, db_api):
        self.context = context
        self.db_api = db_api
        self.subject = subject
        super(SubjectProxy, self).__init__(subject)


class SubjectMemberRepo(object):

    def __init__(self, context, db_api, subject):
        self.context = context
        self.db_api = db_api
        self.subject = subject

    def _format_subject_member_from_db(self, db_subject_member):
        return subject.domain.SubjectMembership(
            id=db_subject_member['id'],
            subject_id=db_subject_member['subject_id'],
            member_id=db_subject_member['member'],
            status=db_subject_member['status'],
            created_at=db_subject_member['created_at'],
            updated_at=db_subject_member['updated_at']
        )

    def _format_subject_member_to_db(self, subject_member):
        subject_member = {'subject_id': self.subject.subject_id,
                        'member': subject_member.member_id,
                        'status': subject_member.status,
                        'created_at': subject_member.created_at}
        return subject_member

    def list(self):
        db_members = self.db_api.subject_member_find(
            self.context, subject_id=self.subject.subject_id)
        subject_members = []
        for db_member in db_members:
            subject_members.append(self._format_subject_member_from_db(db_member))
        return subject_members

    def add(self, subject_member):
        try:
            self.get(subject_member.member_id)
        except exception.NotFound:
            pass
        else:
            msg = _('The target member %(member_id)s is already '
                    'associated with subject %(subject_id)s.') % {
                        'member_id': subject_member.member_id,
                        'subject_id': self.subject.subject_id}
            raise exception.Duplicate(msg)

        subject_member_values = self._format_subject_member_to_db(subject_member)
        # Note(shalq): find the subject member including the member marked with
        # deleted. We will use only one record to represent membership between
        # the same subject and member. The record of the deleted subject member
        # will be reused, if it exists, update its properties instead of
        # creating a new one.
        members = self.db_api.subject_member_find(self.context,
                                                subject_id=self.subject.subject_id,
                                                member=subject_member.member_id,
                                                include_deleted=True)
        if members:
            new_values = self.db_api.subject_member_update(self.context,
                                                         members[0]['id'],
                                                         subject_member_values)
        else:
            new_values = self.db_api.subject_member_create(self.context,
                                                         subject_member_values)
        subject_member.created_at = new_values['created_at']
        subject_member.updated_at = new_values['updated_at']
        subject_member.id = new_values['id']

    def remove(self, subject_member):
        try:
            self.db_api.subject_member_delete(self.context, subject_member.id)
        except (exception.NotFound, exception.Forbidden):
            msg = _("The specified member %s could not be found")
            raise exception.NotFound(msg % subject_member.id)

    def save(self, subject_member, from_state=None):
        subject_member_values = self._format_subject_member_to_db(subject_member)
        try:
            new_values = self.db_api.subject_member_update(self.context,
                                                         subject_member.id,
                                                         subject_member_values)
        except (exception.NotFound, exception.Forbidden):
            raise exception.NotFound()
        subject_member.updated_at = new_values['updated_at']

    def get(self, member_id):
        try:
            db_api_subject_member = self.db_api.subject_member_find(
                self.context,
                self.subject.subject_id,
                member_id)
            if not db_api_subject_member:
                raise exception.NotFound()
        except (exception.NotFound, exception.Forbidden):
            raise exception.NotFound()

        subject_member = self._format_subject_member_from_db(
            db_api_subject_member[0])
        return subject_member


class TaskRepo(object):

    def __init__(self, context, db_api):
        self.context = context
        self.db_api = db_api

    def _format_task_from_db(self, db_task):
        return subject.domain.Task(
            task_id=db_task['id'],
            task_type=db_task['type'],
            status=db_task['status'],
            owner=db_task['owner'],
            expires_at=db_task['expires_at'],
            created_at=db_task['created_at'],
            updated_at=db_task['updated_at'],
            task_input=db_task['input'],
            result=db_task['result'],
            message=db_task['message'],
        )

    def _format_task_stub_from_db(self, db_task):
        return subject.domain.TaskStub(
            task_id=db_task['id'],
            task_type=db_task['type'],
            status=db_task['status'],
            owner=db_task['owner'],
            expires_at=db_task['expires_at'],
            created_at=db_task['created_at'],
            updated_at=db_task['updated_at'],
        )

    def _format_task_to_db(self, task):
        task = {'id': task.task_id,
                'type': task.type,
                'status': task.status,
                'input': task.task_input,
                'result': task.result,
                'owner': task.owner,
                'message': task.message,
                'expires_at': task.expires_at,
                'created_at': task.created_at,
                'updated_at': task.updated_at,
                }
        return task

    def get(self, task_id):
        try:
            db_api_task = self.db_api.task_get(self.context, task_id)
        except (exception.NotFound, exception.Forbidden):
            msg = _('Could not find task %s') % task_id
            raise exception.NotFound(msg)
        return self._format_task_from_db(db_api_task)

    def list(self, marker=None, limit=None, sort_key='created_at',
             sort_dir='desc', filters=None):
        db_api_tasks = self.db_api.task_get_all(self.context,
                                                filters=filters,
                                                marker=marker,
                                                limit=limit,
                                                sort_key=sort_key,
                                                sort_dir=sort_dir)
        return [self._format_task_stub_from_db(task) for task in db_api_tasks]

    def save(self, task):
        task_values = self._format_task_to_db(task)
        try:
            updated_values = self.db_api.task_update(self.context,
                                                     task.task_id,
                                                     task_values)
        except (exception.NotFound, exception.Forbidden):
            msg = _('Could not find task %s') % task.task_id
            raise exception.NotFound(msg)
        task.updated_at = updated_values['updated_at']

    def add(self, task):
        task_values = self._format_task_to_db(task)
        updated_values = self.db_api.task_create(self.context, task_values)
        task.created_at = updated_values['created_at']
        task.updated_at = updated_values['updated_at']

    def remove(self, task):
        task_values = self._format_task_to_db(task)
        try:
            self.db_api.task_update(self.context, task.task_id, task_values)
            updated_values = self.db_api.task_delete(self.context,
                                                     task.task_id)
        except (exception.NotFound, exception.Forbidden):
            msg = _('Could not find task %s') % task.task_id
            raise exception.NotFound(msg)
        task.updated_at = updated_values['updated_at']
        task.deleted_at = updated_values['deleted_at']
