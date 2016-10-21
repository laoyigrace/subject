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

from migrate.changeset import UniqueConstraint
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index
from sqlalchemy import Integer, MetaData, String, Table, Text, UniqueConstraint

from subject.db.sqlalchemy import models

def create_tables(tables):
    for table in tables:
        table.create()


def define_tables(meta):
    subjects = Table('subjects',
                     meta,
                     Column('created_at', DateTime, nullable=False),
                     Column('updated_at', DateTime),
                     Column('deleted_at', DateTime),
                     Column('deleted',
                            Boolean,
                            nullable=False,
                            default=False),
                     Column('id', String(36), primary_key=True, nullable=False),
                     Column('name', String(255)),
                     Column('size', Integer),
                     Column('type', String(30)),
                     Column('status', String(30), nullable=False),
                     Column('subject_format', String(20)),
                     Column('tar_format', String(20)),
                     Column('owner', String(255)),
                     Column('checksum', String(32)),
                     Column('contributor', String(32)),
                     Column('phase', String(32)),
                     Column('language', String(32)),
                     Column('score', Integer),
                     Column('knowledge', String(255)),
                     Column('is_public',
                            Boolean,
                            nullable=False,
                            default=False),
                     Column('protected',
                            Boolean,
                            nullable=False,
                            default=False,
                            index=True),
                     Column('subject', String(1024)),
                     Index('checksum_subject_idx', 'checksum'),
                     Index('ix_subjects_is_public', 'is_public'),
                     Index('ix_subjects_deleted', 'deleted'),
                     Index('owner_subject_idx', 'owner'),
                     Index('created_at_subject_idx', 'created_at'),
                     Index('updated_at_subject_idx', 'updated_at'),
                     mysql_engine='InnoDB',
                     mysql_charset='utf8',
                     extend_existing=True
                     )

    subject_properties = Table('subject_properties', meta,
                               Column('created_at', DateTime, nullable=False),
                               Column('updated_at', DateTime),
                               Column('deleted_at', DateTime),
                               Column('deleted',
                                      Boolean,
                                      nullable=False,
                                      default=False),
                               Column('id',
                                      Integer,
                                      primary_key=True,
                                      nullable=False),
                               Column('subject_id',
                                      String(36),
                                      ForeignKey('subjects.id'),
                                      nullable=False),
                               Column('name', String(255), nullable=False),
                               Column('value', Text()),
                               Index('ix_subject_properties_subject_id',
                                     'subject_id'),
                               Index('ix_subject_properties_deleted',
                                     'deleted'),
                               UniqueConstraint('subject_id', 'name',
                                                'deleted'),
                               mysql_engine='InnoDB',
                               mysql_charset='utf8',
                               extend_existing=True)

    subject_locations_table = Table('subject_locations', meta,
                                    Column('created_at',
                                           DateTime,
                                           nullable=False),
                                    Column('updated_at',
                                           DateTime),
                                    Column('deleted_at',
                                           DateTime),
                                    Column('deleted',
                                           Boolean,
                                           nullable=False,
                                           default=False),
                                    Column('id',
                                           Integer,
                                           primary_key=True,
                                           nullable=False),
                                    Column('subject_id',
                                           String(36),
                                           ForeignKey('subjects.id'),
                                           nullable=False),
                                    Column('value',
                                           Text(),
                                           nullable=False),
                                    Column('status', String(30),
                                           server_default='active',
                                           nullable=False),
                                    Column('meta_data',
                                           models.JSONEncodedDict,
                                           default={}),
                                    Index('ix_subject_locations_subject_id',
                                          'subject_id'),
                                    Index('ix_subject_locations_deleted',
                                          'deleted'),
                                    mysql_engine='InnoDB',
                                    mysql_charset='utf8',
                                    )
    subject_tags = Table('subject_tags',
                         meta,
                         Column('id',
                                Integer,
                                primary_key=True,
                                nullable=False),
                         Column('subject_id',
                                String(36),
                                ForeignKey('subjects.id'),
                                nullable=False),
                         Column('value',
                                String(255),
                                nullable=False),
                         Column('created_at',
                                DateTime,
                                nullable=False),
                         Column('updated_at',
                                DateTime),
                         Column('deleted_at',
                                DateTime),
                         Column('deleted',
                                Boolean,
                                nullable=False,
                                default=False),
                         Index('ix_subject_tags_subject_id', 'subject_id'),
                         Index('ix_subject_tags_subject_id_tag_value',
                               'subject_id',
                               'value'),
                         mysql_engine='InnoDB',
                         mysql_charset='utf8')

    return [subjects, subject_properties, subject_locations_table, subject_tags]


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    tables = define_tables(meta)
    create_tables(tables)
    if migrate_engine.name == "mysql":
        tables = ['subjects', 'subject_properties', 'subject_locations',
                  'subject_tags']

        migrate_engine.execute("SET foreign_key_checks = 0")
        for table in tables:
            migrate_engine.execute(
                "ALTER TABLE %s CONVERT TO CHARACTER SET utf8" % table)
        migrate_engine.execute("SET foreign_key_checks = 1")
        migrate_engine.execute(
            "ALTER DATABASE %s DEFAULT CHARACTER SET utf8" %
            migrate_engine.url.database)
        migrate_engine.execute("ALTER TABLE %s Engine=InnoDB" % table)
