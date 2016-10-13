# Copyright 2011 OpenStack Foundation
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

from sqlalchemy import *  # noqa

from subject.db.sqlalchemy.migrate_repo.schema import (
    Boolean, DateTime, Integer, String, create_tables,
    from_migration_import)  # noqa


def get_subjects_table(meta):
    """
    No changes to the subjects table from 007...
    """
    (get_subjects_table,) = from_migration_import(
        '007_add_owner', ['get_subjects_table'])

    subjects = get_subjects_table(meta)
    return subjects


def get_subject_members_table(meta):
    subjects = get_subjects_table(meta)  # noqa

    subject_members = Table('subject_members',
                          meta,
                          Column('id',
                                 Integer(),
                                 primary_key=True,
                                 nullable=False),
                          Column('subject_id',
                                 Integer(),
                                 ForeignKey('subjects.id'),
                                 nullable=False,
                                 index=True),
                          Column('member', String(255), nullable=False),
                          Column('can_share',
                                 Boolean(),
                                 nullable=False,
                                 default=False),
                          Column('created_at', DateTime(), nullable=False),
                          Column('updated_at', DateTime()),
                          Column('deleted_at', DateTime()),
                          Column('deleted',
                                 Boolean(),
                                 nullable=False,
                                 default=False,
                                 index=True),
                          UniqueConstraint('subject_id', 'member'),
                          mysql_charset='utf8',
                          mysql_engine='InnoDB',
                          extend_existing=True)

    # DB2: an index has already been created for the UniqueConstraint option
    # specified on the Table() statement above.
    if meta.bind.name != "ibm_db_sa":
        Index('ix_subject_members_subject_id_member', subject_members.c.subject_id,
              subject_members.c.member)

    return subject_members


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    tables = [get_subject_members_table(meta)]
    create_tables(tables)
