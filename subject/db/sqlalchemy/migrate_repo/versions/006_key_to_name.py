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
    No changes to the subject properties table from 002...
    """
    (get_subjects_table,) = from_migration_import(
        '004_add_checksum', ['get_subjects_table'])

    subjects = get_subjects_table(meta)
    return subjects


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    (get_subject_properties_table,) = from_migration_import(
        '004_add_checksum', ['get_subject_properties_table'])
    subject_properties = get_subject_properties_table(meta)

    if migrate_engine.name == "ibm_db_sa":
        # NOTE(dperaza) ibm db2 does not allow ALTER INDEX so we will drop
        # the index, rename the column, then re-create the index
        sql_commands = [
            """ALTER TABLE subject_properties DROP UNIQUE
                ix_subject_properties_subject_id_key;""",
            """ALTER TABLE subject_properties RENAME COLUMN \"key\" to name;""",
            """ALTER TABLE subject_properties ADD CONSTRAINT
                ix_subject_properties_subject_id_name UNIQUE(subject_id, name);""",
        ]
        for command in sql_commands:
            meta.bind.execute(command)
    else:
        index = Index('ix_subject_properties_subject_id_key',
                      subject_properties.c.subject_id,
                      subject_properties.c.key)
        index.rename('ix_subject_properties_subject_id_name')

        subject_properties = get_subject_properties_table(meta)
        subject_properties.columns['key'].alter(name="name")
