# Copyright 2013 Red Hat, Inc.
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

from migrate.changeset import UniqueConstraint
from oslo_db import exception as db_exception
from sqlalchemy import MetaData, Table
from sqlalchemy.exc import OperationalError, ProgrammingError


NEW_KEYNAME = 'subject_members_subject_id_member_deleted_at_key'
ORIGINAL_KEYNAME_RE = re.compile('subject_members_subject_id.*_key')


def upgrade(migrate_engine):
    subject_members = _get_subject_members_table(migrate_engine)

    if migrate_engine.name in ('mysql', 'postgresql'):
        try:
            UniqueConstraint('subject_id',
                             name=_get_original_keyname(migrate_engine.name),
                             table=subject_members).drop()
        except (OperationalError, ProgrammingError, db_exception.DBError):
            UniqueConstraint('subject_id',
                             name=_infer_original_keyname(subject_members),
                             table=subject_members).drop()
        UniqueConstraint('subject_id',
                         'member',
                         'deleted_at',
                         name=NEW_KEYNAME,
                         table=subject_members).create()


def _get_subject_members_table(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    return Table('subject_members', meta, autoload=True)


def _get_original_keyname(db):
    return {'mysql': 'subject_id',
            'postgresql': 'subject_members_subject_id_member_key'}[db]


def _infer_original_keyname(table):
    for i in table.indexes:
        if ORIGINAL_KEYNAME_RE.match(i.name):
            return i.name
