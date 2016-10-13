# Copyright 2013 IBM Corp.
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

"""
While SQLAlchemy/sqlalchemy-migrate should abstract this correctly,
there are known issues with these libraries so SQLite and non-SQLite
migrations must be done separately.
"""

import uuid

import migrate
import sqlalchemy


and_ = sqlalchemy.and_
or_ = sqlalchemy.or_


def upgrade(migrate_engine):
    """
    Call the correct dialect-specific upgrade.
    """
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    t_subjects = _get_table('subjects', meta)
    t_subject_members = _get_table('subject_members', meta)
    t_subject_properties = _get_table('subject_properties', meta)

    dialect = migrate_engine.url.get_dialect().name
    if dialect == "sqlite":
        _upgrade_sqlite(meta, t_subjects, t_subject_members, t_subject_properties)
        _update_all_ids_to_uuids(t_subjects, t_subject_members, t_subject_properties)
    elif dialect == "ibm_db_sa":
        _upgrade_db2(meta, t_subjects, t_subject_members, t_subject_properties)
        _update_all_ids_to_uuids(t_subjects, t_subject_members, t_subject_properties)
        _add_db2_constraints(meta)
    else:
        _upgrade_other(t_subjects, t_subject_members, t_subject_properties, dialect)


def _upgrade_sqlite(meta, t_subjects, t_subject_members, t_subject_properties):
    """
    Upgrade 011 -> 012 with special SQLite-compatible logic.
    """

    sql_commands = [
        """CREATE TABLE subjects_backup (
           id VARCHAR(36) NOT NULL,
           name VARCHAR(255),
           size INTEGER,
           status VARCHAR(30) NOT NULL,
           is_public BOOLEAN NOT NULL,
           location TEXT,
           created_at DATETIME NOT NULL,
           updated_at DATETIME,
           deleted_at DATETIME,
           deleted BOOLEAN NOT NULL,
           disk_format VARCHAR(20),
           container_format VARCHAR(20),
           checksum VARCHAR(32),
           owner VARCHAR(255),
           min_disk INTEGER NOT NULL,
           min_ram INTEGER NOT NULL,
           PRIMARY KEY (id),
           CHECK (is_public IN (0, 1)),
           CHECK (deleted IN (0, 1))
        );""",
        """INSERT INTO subjects_backup
           SELECT * FROM subjects;""",
        """CREATE TABLE subject_members_backup (
            id INTEGER NOT NULL,
            subject_id VARCHAR(36) NOT NULL,
            member VARCHAR(255) NOT NULL,
            can_share BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME,
            deleted_at DATETIME,
            deleted BOOLEAN NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (subject_id, member),
            CHECK (can_share IN (0, 1)),
            CHECK (deleted IN (0, 1)),
            FOREIGN KEY(subject_id) REFERENCES subjects (id)
        );""",
        """INSERT INTO subject_members_backup
            SELECT * FROM subject_members;""",
        """CREATE TABLE subject_properties_backup (
            id INTEGER NOT NULL,
            subject_id VARCHAR(36) NOT NULL,
            name VARCHAR(255) NOT NULL,
            value TEXT,
            created_at DATETIME NOT NULL,
            updated_at DATETIME,
            deleted_at DATETIME,
            deleted BOOLEAN NOT NULL,
            PRIMARY KEY (id),
            CHECK (deleted IN (0, 1)),
            UNIQUE (subject_id, name),
            FOREIGN KEY(subject_id) REFERENCES subjects (id)
        );""",
        """INSERT INTO subject_properties_backup
            SELECT * FROM subject_properties;""",
    ]

    for command in sql_commands:
        meta.bind.execute(command)

    _sqlite_table_swap(meta, t_subject_members, t_subject_properties, t_subjects)


def _upgrade_db2(meta, t_subjects, t_subject_members, t_subject_properties):
    """
    Upgrade for DB2.
    """
    t_subjects.c.id.alter(sqlalchemy.String(36), primary_key=True)

    subject_members_backup = sqlalchemy.Table(
        'subject_members_backup',
        meta,
        sqlalchemy.Column('id',
                          sqlalchemy.Integer(),
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('subject_id',
                          sqlalchemy.String(36),
                          nullable=False,
                          index=True),
        sqlalchemy.Column('member',
                          sqlalchemy.String(255),
                          nullable=False),
        sqlalchemy.Column('can_share',
                          sqlalchemy.Boolean(),
                          nullable=False,
                          default=False),
        sqlalchemy.Column('created_at',
                          sqlalchemy.DateTime(),
                          nullable=False),
        sqlalchemy.Column('updated_at',
                          sqlalchemy.DateTime()),
        sqlalchemy.Column('deleted_at',
                          sqlalchemy.DateTime()),
        sqlalchemy.Column('deleted',
                          sqlalchemy.Boolean(),
                          nullable=False,
                          default=False,
                          index=True),
        sqlalchemy.UniqueConstraint('subject_id', 'member'),
        extend_existing=True)

    subject_properties_backup = sqlalchemy.Table(
        'subject_properties_backup',
        meta,
        sqlalchemy.Column('id',
                          sqlalchemy.Integer(),
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('subject_id',
                          sqlalchemy.String(36),
                          nullable=False,
                          index=True),
        sqlalchemy.Column('name',
                          sqlalchemy.String(255),
                          nullable=False),
        sqlalchemy.Column('value',
                          sqlalchemy.Text()),
        sqlalchemy.Column('created_at',
                          sqlalchemy.DateTime(),
                          nullable=False),
        sqlalchemy.Column('updated_at',
                          sqlalchemy.DateTime()),
        sqlalchemy.Column('deleted_at',
                          sqlalchemy.DateTime()),
        sqlalchemy.Column('deleted',
                          sqlalchemy.Boolean(),
                          nullable=False,
                          default=False,
                          index=True),
        sqlalchemy.UniqueConstraint(
            'subject_id', 'name',
            name='ix_subject_properties_subject_id_name'),
        extend_existing=True)

    subject_members_backup.create()
    subject_properties_backup.create()

    sql_commands = [
        """INSERT INTO subject_members_backup
            SELECT * FROM subject_members;""",
        """INSERT INTO subject_properties_backup
            SELECT * FROM subject_properties;""",
    ]

    for command in sql_commands:
        meta.bind.execute(command)

    t_subject_members.drop()
    t_subject_properties.drop()

    subject_members_backup.rename(name='subject_members')
    subject_properties_backup.rename(name='subject_properties')


def _add_db2_constraints(meta):
    # Create the foreign keys
    sql_commands = [
        """ALTER TABLE subject_members ADD CONSTRAINT member_subject_id
            FOREIGN KEY (subject_id)
            REFERENCES subjects (id);""",
        """ALTER TABLE subject_properties ADD CONSTRAINT property_subject_id
            FOREIGN KEY (subject_id)
            REFERENCES subjects (id);""",
    ]
    for command in sql_commands:
        meta.bind.execute(command)


def _upgrade_other(t_subjects, t_subject_members, t_subject_properties, dialect):
    """
    Upgrade 011 -> 012 with logic for non-SQLite databases.
    """
    foreign_keys = _get_foreign_keys(t_subjects,
                                     t_subject_members,
                                     t_subject_properties, dialect)

    for fk in foreign_keys:
        fk.drop()

    t_subjects.c.id.alter(sqlalchemy.String(36), primary_key=True)
    t_subject_members.c.subject_id.alter(sqlalchemy.String(36))
    t_subject_properties.c.subject_id.alter(sqlalchemy.String(36))

    _update_all_ids_to_uuids(t_subjects, t_subject_members, t_subject_properties)

    for fk in foreign_keys:
        fk.create()


def _sqlite_table_swap(meta, t_subject_members, t_subject_properties, t_subjects):
    t_subject_members.drop()
    t_subject_properties.drop()
    t_subjects.drop()

    meta.bind.execute("ALTER TABLE subjects_backup "
                      "RENAME TO subjects")
    meta.bind.execute("ALTER TABLE subject_members_backup "
                      "RENAME TO subject_members")
    meta.bind.execute("ALTER TABLE subject_properties_backup "
                      "RENAME TO subject_properties")
    meta.bind.execute("""CREATE INDEX ix_subject_properties_deleted
                          ON subject_properties (deleted);""")
    meta.bind.execute("""CREATE INDEX ix_subject_properties_name
                          ON subject_properties (name);""")


def _get_table(table_name, metadata):
    """Return a sqlalchemy Table definition with associated metadata."""
    return sqlalchemy.Table(table_name, metadata, autoload=True)


def _get_foreign_keys(t_subjects, t_subject_members, t_subject_properties, dialect):
    """Retrieve and return foreign keys for members/properties tables."""
    foreign_keys = []
    if t_subject_members.foreign_keys:
        img_members_fk_name = list(t_subject_members.foreign_keys)[0].name
        if dialect == 'mysql':
            fk1 = migrate.ForeignKeyConstraint([t_subject_members.c.subject_id],
                                               [t_subjects.c.id],
                                               name=img_members_fk_name)
        else:
            fk1 = migrate.ForeignKeyConstraint([t_subject_members.c.subject_id],
                                               [t_subjects.c.id])
        foreign_keys.append(fk1)

    if t_subject_properties.foreign_keys:
        img_properties_fk_name = list(t_subject_properties.foreign_keys)[0].name
        if dialect == 'mysql':
            fk2 = migrate.ForeignKeyConstraint([t_subject_properties.c.subject_id],
                                               [t_subjects.c.id],
                                               name=img_properties_fk_name)
        else:
            fk2 = migrate.ForeignKeyConstraint([t_subject_properties.c.subject_id],
                                               [t_subjects.c.id])
        foreign_keys.append(fk2)

    return foreign_keys


def _update_all_ids_to_uuids(t_subjects, t_subject_members, t_subject_properties):
    """Transition from INTEGER id to VARCHAR(36) id."""
    subjects = list(t_subjects.select().execute())

    for subject in subjects:
        old_id = subject["id"]
        new_id = str(uuid.uuid4())

        t_subjects.update().where(
            t_subjects.c.id == old_id).values(id=new_id).execute()

        t_subject_members.update().where(
            t_subject_members.c.subject_id == old_id).values(
                subject_id=new_id).execute()

        t_subject_properties.update().where(
            t_subject_properties.c.subject_id == old_id).values(
                subject_id=new_id).execute()

        t_subject_properties.update().where(
            and_(or_(t_subject_properties.c.name == 'kernel_id',
                     t_subject_properties.c.name == 'ramdisk_id'),
                 t_subject_properties.c.value == old_id)).values(
                     value=new_id).execute()


def _update_all_uuids_to_ids(t_subjects, t_subject_members, t_subject_properties):
    """Transition from VARCHAR(36) id to INTEGER id."""
    subjects = list(t_subjects.select().execute())

    new_id = 1
    for subject in subjects:
        old_id = subject["id"]

        t_subjects.update().where(
            t_subjects.c.id == old_id).values(
                id=str(new_id)).execute()

        t_subject_members.update().where(
            t_subject_members.c.subject_id == old_id).values(
                subject_id=str(new_id)).execute()

        t_subject_properties.update().where(
            t_subject_properties.c.subject_id == old_id).values(
                subject_id=str(new_id)).execute()

        t_subject_properties.update().where(
            and_(or_(t_subject_properties.c.name == 'kernel_id',
                     t_subject_properties.c.name == 'ramdisk_id'),
                 t_subject_properties.c.value == old_id)).values(
                     value=str(new_id)).execute()

        new_id += 1
