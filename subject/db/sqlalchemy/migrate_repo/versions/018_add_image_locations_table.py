# Copyright 2013 OpenStack Foundation
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

from subject.db.sqlalchemy.migrate_repo import schema


def upgrade(migrate_engine):
    meta = sqlalchemy.schema.MetaData(migrate_engine)

    # NOTE(bcwaldon): load the subjects table for the ForeignKey below
    sqlalchemy.Table('subjects', meta, autoload=True)

    subject_locations_table = sqlalchemy.Table(
        'subject_locations', meta,
        sqlalchemy.Column('id',
                          schema.Integer(),
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('subject_id',
                          schema.String(36),
                          sqlalchemy.ForeignKey('subjects.id'),
                          nullable=False,
                          index=True),
        sqlalchemy.Column('value',
                          schema.Text(),
                          nullable=False),
        sqlalchemy.Column('created_at',
                          schema.DateTime(),
                          nullable=False),
        sqlalchemy.Column('updated_at',
                          schema.DateTime()),
        sqlalchemy.Column('deleted_at',
                          schema.DateTime()),
        sqlalchemy.Column('deleted',
                          schema.Boolean(),
                          nullable=False,
                          default=False,
                          index=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    schema.create_tables([subject_locations_table])
