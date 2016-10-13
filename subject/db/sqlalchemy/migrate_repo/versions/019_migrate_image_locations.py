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


def get_subjects_table(meta):
    return sqlalchemy.Table('subjects', meta, autoload=True)


def get_subject_locations_table(meta):
    return sqlalchemy.Table('subject_locations', meta, autoload=True)


def upgrade(migrate_engine):
    meta = sqlalchemy.schema.MetaData(migrate_engine)

    subjects_table = get_subjects_table(meta)
    subject_locations_table = get_subject_locations_table(meta)

    subject_records = subjects_table.select().execute().fetchall()
    for subject in subject_records:
        if subject.location is not None:
            values = {
                'subject_id': subject.id,
                'value': subject.location,
                'created_at': subject.created_at,
                'updated_at': subject.updated_at,
                'deleted': subject.deleted,
                'deleted_at': subject.deleted_at,
            }
            subject_locations_table.insert(values=values).execute()
