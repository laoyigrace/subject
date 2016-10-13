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

from subject.db.sqlalchemy.migrate_repo.schema import from_migration_import


def get_subjects_table(meta):
    """
    No changes to the subjects table from 008...
    """
    (get_subjects_table,) = from_migration_import(
        '008_add_subject_members_table', ['get_subjects_table'])

    subjects = get_subjects_table(meta)
    return subjects


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    subjects_table = get_subjects_table(meta)

    # set updated_at to created_at if equal to None
    conn = migrate_engine.connect()
    conn.execute(
        subjects_table.update(
            subjects_table.c.updated_at == None,
            {subjects_table.c.updated_at: subjects_table.c.created_at}))
