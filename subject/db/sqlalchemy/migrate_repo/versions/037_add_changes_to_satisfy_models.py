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

import sqlalchemy
from sqlalchemy import Table, Index, UniqueConstraint
from sqlalchemy.schema import (AddConstraint, DropConstraint,
                               ForeignKeyConstraint)
from sqlalchemy import sql
from sqlalchemy import update


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    if migrate_engine.name not in ['mysql', 'postgresql']:
        return

    subject_properties = Table('subject_properties', meta, autoload=True)
    subject_members = Table('subject_members', meta, autoload=True)
    subjects = Table('subjects', meta, autoload=True)

    # We have to ensure that we doesn't have `nulls` values since we are going
    # to set nullable=False
    migrate_engine.execute(
        update(subject_members)
        .where(subject_members.c.status == sql.expression.null())
        .values(status='pending'))

    migrate_engine.execute(
        update(subjects)
        .where(subjects.c.protected == sql.expression.null())
        .values(protected=sql.expression.false()))

    subject_members.c.status.alter(nullable=False, server_default='pending')
    subjects.c.protected.alter(
        nullable=False, server_default=sql.expression.false())

    if migrate_engine.name == 'postgresql':
        Index('ix_subject_properties_subject_id_name',
              subject_properties.c.subject_id,
              subject_properties.c.name).drop()

        # We have different names of this constraint in different versions of
        # postgresql. Since we have only one constraint on this table, we can
        # get it in the following way.
        name = migrate_engine.execute(
            """SELECT conname
               FROM pg_constraint
               WHERE conrelid =
                   (SELECT oid
                    FROM pg_class
                    WHERE relname LIKE 'subject_properties')
                  AND contype = 'u';""").scalar()

        constraint = UniqueConstraint(subject_properties.c.subject_id,
                                      subject_properties.c.name,
                                      name='%s' % name)
        migrate_engine.execute(DropConstraint(constraint))

        constraint = UniqueConstraint(subject_properties.c.subject_id,
                                      subject_properties.c.name,
                                      name='ix_subject_properties_subject_id_name')
        migrate_engine.execute(AddConstraint(constraint))

        subjects.c.id.alter(server_default=None)
    if migrate_engine.name == 'mysql':
        constraint = UniqueConstraint(subject_properties.c.subject_id,
                                      subject_properties.c.name,
                                      name='subject_id')
        migrate_engine.execute(DropConstraint(constraint))
        subject_locations = Table('subject_locations', meta, autoload=True)
        if len(subject_locations.foreign_keys) == 0:
            migrate_engine.execute(AddConstraint(ForeignKeyConstraint(
                [subject_locations.c.subject_id], [subjects.c.id])))
