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

import sqlalchemy
from sqlalchemy import func
from sqlalchemy import orm
from sqlalchemy import sql
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = sqlalchemy.schema.MetaData(migrate_engine)
    subject_locations = Table('subject_locations', meta, autoload=True)

    if migrate_engine.name == "ibm_db_sa":
        il = orm.aliased(subject_locations)
        # NOTE(wenchma): Get all duplicated rows.
        qry = (sql.select([il.c.id])
               .where(il.c.id > (sql.select([func.min(subject_locations.c.id)])
                      .where(subject_locations.c.subject_id == il.c.subject_id)
                      .where(subject_locations.c.value == il.c.value)
                      .where(subject_locations.c.meta_data == il.c.meta_data)
                      .where(subject_locations.c.deleted == False)))
               .where(il.c.deleted == False)
               .execute()
               )

        for row in qry:
            stmt = (subject_locations.delete()
                    .where(subject_locations.c.id == row[0])
                    .where(subject_locations.c.deleted == False))
            stmt.execute()

    else:
        session = orm.sessionmaker(bind=migrate_engine)()

        # NOTE(flaper87): Lets group by
        # subject_id, location and metadata.
        grp = [subject_locations.c.subject_id,
               subject_locations.c.value,
               subject_locations.c.meta_data]

        # NOTE(flaper87): Get all duplicated rows
        qry = (session.query(*grp)
                      .filter(subject_locations.c.deleted == False)
                      .group_by(*grp)
                      .having(func.count() > 1))

        for row in qry:
            # NOTE(flaper87): Not the fastest way to do it.
            # This is the best way to do it since sqlalchemy
            # has a bug around delete + limit.
            s = (sql.select([subject_locations.c.id])
                 .where(subject_locations.c.subject_id == row[0])
                 .where(subject_locations.c.value == row[1])
                 .where(subject_locations.c.meta_data == row[2])
                 .where(subject_locations.c.deleted == False)
                 .limit(1).execute())
            stmt = (subject_locations.delete()
                    .where(subject_locations.c.id == s.first()[0]))
            stmt.execute()

        session.close()
