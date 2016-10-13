# Copyright 2010-2011 OpenStack Foundation
# All Rights Reserved.
# Copyright 2013 IBM Corp.
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
Tests for database migrations run a series of test cases to ensure that
migrations work properly both upgrading and downgrading, and that no data loss
occurs if possible.
"""

from __future__ import print_function

import datetime
import os
import pickle
import uuid

from migrate.versioning import api as migration_api
from migrate.versioning.repository import Repository
from oslo_config import cfg
from oslo_db.sqlalchemy import test_base
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as db_utils
from oslo_serialization import jsonutils
from oslo_utils import uuidutils
# NOTE(jokke): simplified transition to py3, behaves like py2 xrange
from six.moves import range
import sqlalchemy
import sqlalchemy.types as types

from subject.common import crypt
from subject.common import exception
from subject.common import timeutils
from subject.db import migration
from subject.db.sqlalchemy import migrate_repo
from subject.db.sqlalchemy.migrate_repo.schema import from_migration_import
from subject.db.sqlalchemy.migrate_repo import versions
from subject.db.sqlalchemy import models
from subject.db.sqlalchemy import models_glare
from subject.db.sqlalchemy import models_metadef
import subject.tests.utils as test_utils

from subject.i18n import _

CONF = cfg.CONF
CONF.import_opt('metadata_encryption_key', 'subject.common.config')


def index_exist(index, table, engine):
    inspector = sqlalchemy.inspect(engine)
    return index in [i['name'] for i in inspector.get_indexes(table)]


def unique_constraint_exist(constraint, table, engine):
    inspector = sqlalchemy.inspect(engine)
    return constraint in [c['name'] for c in
                          inspector.get_unique_constraints(table)]


class MigrationsMixin(test_migrations.WalkVersionsMixin):
    @property
    def INIT_VERSION(self):
        return migration.INIT_VERSION

    @property
    def REPOSITORY(self):
        migrate_file = migrate_repo.__file__
        return Repository(os.path.abspath(os.path.dirname(migrate_file)))

    @property
    def migration_api(self):
        return migration_api

    @property
    def migrate_engine(self):
        return self.engine

    def test_walk_versions(self):
        # No more downgrades
        self._walk_versions(False, False)

    def _create_unversioned_001_db(self, engine):
        # Create the initial version of the subjects table
        meta = sqlalchemy.schema.MetaData()
        meta.bind = engine
        subjects_001 = sqlalchemy.Table('subjects', meta,
                                      sqlalchemy.Column('id', models.Integer,
                                                        primary_key=True),
                                      sqlalchemy.Column('name',
                                                        sqlalchemy.String(255)
                                                        ),
                                      sqlalchemy.Column('type',
                                                        sqlalchemy.String(30)),
                                      sqlalchemy.Column('size',
                                                        sqlalchemy.Integer),
                                      sqlalchemy.Column('status',
                                                        sqlalchemy.String(30)),
                                      sqlalchemy.Column('is_public',
                                                        sqlalchemy.Boolean,
                                                        default=False),
                                      sqlalchemy.Column('location',
                                                        sqlalchemy.Text),
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
                                                        default=False),
                                      mysql_engine='InnoDB',
                                      mysql_charset='utf8')
        subjects_001.create()

    def test_version_control_existing_db(self):
        """
        Creates a DB without version control information, places it
        under version control and checks that it can be upgraded
        without errors.
        """
        self._create_unversioned_001_db(self.migrate_engine)

        old_version = migration.INIT_VERSION
        # we must start from version 1
        migration.INIT_VERSION = 1
        self.addCleanup(setattr, migration, 'INIT_VERSION', old_version)

        self._walk_versions(False, False)

    def _pre_upgrade_003(self, engine):
        now = datetime.datetime.now()
        subjects = db_utils.get_table(engine, 'subjects')
        data = {'deleted': False, 'created_at': now, 'updated_at': now,
                'type': 'kernel', 'status': 'active', 'is_public': True}
        subjects.insert().values(data).execute()
        return data

    def _check_003(self, engine, data):
        subjects = db_utils.get_table(engine, 'subjects')
        self.assertNotIn('type', subjects.c,
                         "'type' column found in subjects table columns! "
                         "subjects table columns reported by metadata: %s\n"
                         % subjects.c.keys())
        subjects_prop = db_utils.get_table(engine, 'subject_properties')
        result = subjects_prop.select().execute()
        types = []
        for row in result:
            if row['key'] == 'type':
                types.append(row['value'])
        self.assertIn(data['type'], types)

    def _pre_upgrade_004(self, engine):
        """Insert checksum data sample to check if migration goes fine with
        data.
        """
        now = timeutils.utcnow()
        subjects = db_utils.get_table(engine, 'subjects')
        data = [
            {
                'deleted': False, 'created_at': now, 'updated_at': now,
                'type': 'kernel', 'status': 'active', 'is_public': True,
            }
        ]
        engine.execute(subjects.insert(), data)
        return data

    def _check_004(self, engine, data):
        """Assure that checksum data is present on table"""
        subjects = db_utils.get_table(engine, 'subjects')
        self.assertIn('checksum', subjects.c)
        self.assertEqual(32, subjects.c['checksum'].type.length)

    def _pre_upgrade_005(self, engine):
        now = timeutils.utcnow()
        subjects = db_utils.get_table(engine, 'subjects')
        data = [
            {
                'deleted': False, 'created_at': now, 'updated_at': now,
                'type': 'kernel', 'status': 'active', 'is_public': True,
                # Integer type signed size limit
                'size': 2147483647
            }
        ]
        engine.execute(subjects.insert(), data)
        return data

    def _check_005(self, engine, data):

        subjects = db_utils.get_table(engine, 'subjects')
        select = subjects.select().execute()

        sizes = [row['size'] for row in select if row['size'] is not None]
        migrated_data_sizes = [element['size'] for element in data]

        for migrated in migrated_data_sizes:
            self.assertIn(migrated, sizes)

    def _pre_upgrade_006(self, engine):
        now = timeutils.utcnow()
        subjects = db_utils.get_table(engine, 'subjects')
        subject_data = [
            {
                'deleted': False, 'created_at': now, 'updated_at': now,
                'type': 'kernel', 'status': 'active', 'is_public': True,
                'id': 9999,
            }
        ]
        engine.execute(subjects.insert(), subject_data)

        subjects_properties = db_utils.get_table(engine, 'subject_properties')
        properties_data = [
            {
                'id': 10, 'subject_id': 9999, 'updated_at': now,
                'created_at': now, 'deleted': False, 'key': 'subject_name'
            }
        ]
        engine.execute(subjects_properties.insert(), properties_data)
        return properties_data

    def _check_006(self, engine, data):
        subjects_properties = db_utils.get_table(engine, 'subject_properties')
        select = subjects_properties.select().execute()

        # load names from name collumn
        subject_names = [row['name'] for row in select]

        # check names from data in subject names from name column
        for element in data:
            self.assertIn(element['key'], subject_names)

    def _pre_upgrade_010(self, engine):
        """Test rows in subjects with NULL updated_at get updated to equal
        created_at.
        """

        initial_values = [
            (datetime.datetime(1999, 1, 2, 4, 10, 20),
             datetime.datetime(1999, 1, 2, 4, 10, 30)),
            (datetime.datetime(1999, 2, 4, 6, 15, 25),
             datetime.datetime(1999, 2, 4, 6, 15, 35)),
            (datetime.datetime(1999, 3, 6, 8, 20, 30),
             None),
            (datetime.datetime(1999, 4, 8, 10, 25, 35),
             None),
        ]

        subjects = db_utils.get_table(engine, 'subjects')
        for created_at, updated_at in initial_values:
            row = dict(deleted=False,
                       created_at=created_at,
                       updated_at=updated_at,
                       status='active',
                       is_public=True,
                       min_disk=0,
                       min_ram=0)
            subjects.insert().values(row).execute()

        return initial_values

    def _check_010(self, engine, data):
        values = {c: u for c, u in data}

        subjects = db_utils.get_table(engine, 'subjects')
        for row in subjects.select().execute():
            if row['created_at'] in values:
                # updated_at should be unchanged if not previous NULL, or
                # set to created_at if previously NULL
                updated_at = values.pop(row['created_at']) or row['created_at']
                self.assertEqual(row['updated_at'], updated_at)

        # No initial values should be remaining
        self.assertEqual(0, len(values))

    def _pre_upgrade_012(self, engine):
        """Test rows in subjects have id changes from int to varchar(32) and
        value changed from int to UUID. Also test subject_members and
        subject_properties gets updated to point to new UUID keys.
        """

        subjects = db_utils.get_table(engine, 'subjects')
        subject_members = db_utils.get_table(engine, 'subject_members')
        subject_properties = db_utils.get_table(engine, 'subject_properties')

        # Insert kernel, ramdisk and normal subjects
        now = timeutils.utcnow()
        data = {'created_at': now, 'updated_at': now,
                'status': 'active', 'deleted': False,
                'is_public': True, 'min_disk': 0, 'min_ram': 0}

        test_data = {}
        for name in ('kernel', 'ramdisk', 'normal'):
            data['name'] = '%s migration 012 test' % name
            result = subjects.insert().values(data).execute()
            test_data[name] = result.inserted_primary_key[0]

        # Insert subject_members and subject_properties rows
        data = {'created_at': now, 'updated_at': now, 'deleted': False,
                'subject_id': test_data['normal'], 'member': 'foobar',
                'can_share': False}
        result = subject_members.insert().values(data).execute()
        test_data['member'] = result.inserted_primary_key[0]

        data = {'created_at': now, 'updated_at': now, 'deleted': False,
                'subject_id': test_data['normal'], 'name': 'ramdisk_id',
                'value': test_data['ramdisk']}
        result = subject_properties.insert().values(data).execute()
        test_data['properties'] = [result.inserted_primary_key[0]]

        data.update({'name': 'kernel_id', 'value': test_data['kernel']})
        result = subject_properties.insert().values(data).execute()
        test_data['properties'].append(result.inserted_primary_key)

        return test_data

    def _check_012(self, engine, test_data):
        subjects = db_utils.get_table(engine, 'subjects')
        subject_members = db_utils.get_table(engine, 'subject_members')
        subject_properties = db_utils.get_table(engine, 'subject_properties')

        # Find kernel, ramdisk and normal subjects. Make sure id has been
        # changed to a uuid
        uuids = {}
        for name in ('kernel', 'ramdisk', 'normal'):
            subject_name = '%s migration 012 test' % name
            rows = subjects.select().where(
                subjects.c.name == subject_name).execute().fetchall()

            self.assertEqual(1, len(rows))

            row = rows[0]
            self.assertTrue(uuidutils.is_uuid_like(row['id']))

            uuids[name] = row['id']

        # Find all subject_members to ensure subject_id has been updated
        results = subject_members.select().where(
            subject_members.c.subject_id == uuids['normal']).execute().fetchall()
        self.assertEqual(1, len(results))

        # Find all subject_properties to ensure subject_id has been updated
        # as well as ensure kernel_id and ramdisk_id values have been
        # updated too
        results = subject_properties.select().where(
            subject_properties.c.subject_id == uuids['normal']
        ).execute().fetchall()
        self.assertEqual(2, len(results))
        for row in results:
            self.assertIn(row['name'], ('kernel_id', 'ramdisk_id'))

            if row['name'] == 'kernel_id':
                self.assertEqual(row['value'], uuids['kernel'])
            if row['name'] == 'ramdisk_id':
                self.assertEqual(row['value'], uuids['ramdisk'])

    def _assert_invalid_swift_uri_raises_bad_store_uri(self,
                                                       legacy_parse_uri_fn):
        invalid_uri = ('swift://http://acct:usr:pass@example.com'
                       '/container/obj-id')
        # URI cannot contain more than one occurrence of a scheme.
        self.assertRaises(exception.BadStoreUri,
                          legacy_parse_uri_fn,
                          invalid_uri,
                          True)

        invalid_scheme_uri = ('http://acct:usr:pass@example.com'
                              '/container/obj-id')
        self.assertRaises(exception.BadStoreUri,
                          legacy_parse_uri_fn,
                          invalid_scheme_uri,
                          True)

        invalid_account_missing_uri = 'swift+http://container/obj-id'
        # Badly formed Swift URI: swift+http://container/obj-id
        self.assertRaises(exception.BadStoreUri,
                          legacy_parse_uri_fn,
                          invalid_account_missing_uri,
                          True)

        invalid_container_missing_uri = ('swift+http://'
                                         'acct:usr:pass@example.com/obj-id')
        # Badly formed Swift URI: swift+http://acct:usr:pass@example.com/obj-id
        self.assertRaises(exception.BadStoreUri,
                          legacy_parse_uri_fn,
                          invalid_container_missing_uri,
                          True)

        invalid_object_missing_uri = ('swift+http://'
                                      'acct:usr:pass@example.com/container')
        # Badly formed Swift URI:
        # swift+http://acct:usr:pass@example.com/container
        self.assertRaises(exception.BadStoreUri,
                          legacy_parse_uri_fn,
                          invalid_object_missing_uri,
                          True)

        invalid_user_without_pass_uri = ('swift://acctusr@example.com'
                                         '/container/obj-id')
        # Badly formed credentials '%(creds)s' in Swift URI
        self.assertRaises(exception.BadStoreUri,
                          legacy_parse_uri_fn,
                          invalid_user_without_pass_uri,
                          True)

        # Badly formed credentials in Swift URI.
        self.assertRaises(exception.BadStoreUri,
                          legacy_parse_uri_fn,
                          invalid_user_without_pass_uri,
                          False)

    def test_legacy_parse_swift_uri_015(self):
        (legacy_parse_uri,) = from_migration_import(
            '015_quote_swift_credentials', ['legacy_parse_uri'])

        uri = legacy_parse_uri(
            'swift://acct:usr:pass@example.com/container/obj-id',
            True)
        self.assertTrue(uri, 'swift://acct%3Ausr:pass@example.com'
                             '/container/obj-id')

        self._assert_invalid_swift_uri_raises_bad_store_uri(legacy_parse_uri)

    def _pre_upgrade_015(self, engine):
        subjects = db_utils.get_table(engine, 'subjects')
        unquoted_locations = [
            'swift://acct:usr:pass@example.com/container/obj-id',
            'file://foo',
        ]
        now = datetime.datetime.now()
        temp = dict(deleted=False,
                    created_at=now,
                    updated_at=now,
                    status='active',
                    is_public=True,
                    min_disk=0,
                    min_ram=0)
        data = []
        for i, location in enumerate(unquoted_locations):
            temp.update(location=location, id=str(uuid.uuid4()))
            data.append(temp)
            subjects.insert().values(temp).execute()
        return data

    def _check_015(self, engine, data):
        subjects = db_utils.get_table(engine, 'subjects')
        quoted_locations = [
            'swift://acct%3Ausr:pass@example.com/container/obj-id',
            'file://foo',
        ]
        result = subjects.select().execute()
        locations = list(map(lambda x: x['location'], result))
        for loc in quoted_locations:
            self.assertIn(loc, locations)

    def _pre_upgrade_016(self, engine):
        subjects = db_utils.get_table(engine, 'subjects')
        now = datetime.datetime.now()
        temp = dict(deleted=False,
                    created_at=now,
                    updated_at=now,
                    status='active',
                    is_public=True,
                    min_disk=0,
                    min_ram=0,
                    id='fake-subject-id1')
        subjects.insert().values(temp).execute()
        subject_members = db_utils.get_table(engine, 'subject_members')
        now = datetime.datetime.now()
        data = {'deleted': False,
                'created_at': now,
                'member': 'fake-member',
                'updated_at': now,
                'can_share': False,
                'subject_id': 'fake-subject-id1'}
        subject_members.insert().values(data).execute()
        return data

    def _check_016(self, engine, data):
        subject_members = db_utils.get_table(engine, 'subject_members')
        self.assertIn('status', subject_members.c,
                      "'status' column found in subject_members table "
                      "columns! subject_members table columns: %s"
                      % subject_members.c.keys())

    def test_legacy_parse_swift_uri_017(self):
        metadata_encryption_key = 'a' * 16
        CONF.set_override('metadata_encryption_key', metadata_encryption_key,
                          enforce_type=True)
        self.addCleanup(CONF.reset)
        (legacy_parse_uri, encrypt_location) = from_migration_import(
            '017_quote_encrypted_swift_credentials', ['legacy_parse_uri',
                                                      'encrypt_location'])

        uri = legacy_parse_uri('swift://acct:usr:pass@example.com'
                               '/container/obj-id', True)
        self.assertTrue(uri, encrypt_location(
            'swift://acct%3Ausr:pass@example.com/container/obj-id'))

        self._assert_invalid_swift_uri_raises_bad_store_uri(legacy_parse_uri)

    def _pre_upgrade_017(self, engine):
        metadata_encryption_key = 'a' * 16
        CONF.set_override('metadata_encryption_key', metadata_encryption_key,
                          enforce_type=True)
        self.addCleanup(CONF.reset)
        subjects = db_utils.get_table(engine, 'subjects')
        unquoted = 'swift://acct:usr:pass@example.com/container/obj-id'
        encrypted_unquoted = crypt.urlsafe_encrypt(
            metadata_encryption_key,
            unquoted, 64)
        data = []
        now = datetime.datetime.now()
        temp = dict(deleted=False,
                    created_at=now,
                    updated_at=now,
                    status='active',
                    is_public=True,
                    min_disk=0,
                    min_ram=0,
                    location=encrypted_unquoted,
                    id='fakeid1')
        subjects.insert().values(temp).execute()

        locations = [
            'file://ab',
            'file://abc',
            'swift://acct3A%foobar:pass@example.com/container/obj-id2'
        ]

        now = datetime.datetime.now()
        temp = dict(deleted=False,
                    created_at=now,
                    updated_at=now,
                    status='active',
                    is_public=True,
                    min_disk=0,
                    min_ram=0)
        for i, location in enumerate(locations):
            temp.update(location=location, id=str(uuid.uuid4()))
            data.append(temp)
            subjects.insert().values(temp).execute()
        return data

    def _check_017(self, engine, data):
        metadata_encryption_key = 'a' * 16
        quoted = 'swift://acct%3Ausr:pass@example.com/container/obj-id'
        subjects = db_utils.get_table(engine, 'subjects')
        result = subjects.select().execute()
        locations = list(map(lambda x: x['location'], result))
        actual_location = []
        for location in locations:
            if location:
                try:
                    temp_loc = crypt.urlsafe_decrypt(metadata_encryption_key,
                                                     location)
                    actual_location.append(temp_loc)
                except TypeError:
                    actual_location.append(location)
                except ValueError:
                    actual_location.append(location)

        self.assertIn(quoted, actual_location)
        loc_list = ['file://ab',
                    'file://abc',
                    'swift://acct3A%foobar:pass@example.com/container/obj-id2']

        for location in loc_list:
            if location not in actual_location:
                self.fail(_("location: %s data lost") % location)

    def _pre_upgrade_019(self, engine):
        subjects = db_utils.get_table(engine, 'subjects')
        now = datetime.datetime.now()
        base_values = {
            'deleted': False,
            'created_at': now,
            'updated_at': now,
            'status': 'active',
            'is_public': True,
            'min_disk': 0,
            'min_ram': 0,
        }
        data = [
            {'id': 'fake-19-1', 'location': 'http://subject.example.com'},
            # NOTE(bcwaldon): subjects with a location of None should
            # not be migrated
            {'id': 'fake-19-2', 'location': None},
        ]
        for subject in data:
            subject.update(base_values)
            subjects.insert().values(subject).execute()
        return data

    def _check_019(self, engine, data):
        subject_locations = db_utils.get_table(engine, 'subject_locations')
        records = subject_locations.select().execute().fetchall()
        locations = {il.subject_id: il.value for il in records}
        self.assertEqual('http://subject.example.com',
                         locations.get('fake-19-1'))

    def _check_020(self, engine, data):
        subjects = db_utils.get_table(engine, 'subjects')
        self.assertNotIn('location', subjects.c)

    def _pre_upgrade_026(self, engine):
        subject_locations = db_utils.get_table(engine, 'subject_locations')

        now = datetime.datetime.now()
        subject_id = 'fake_id'
        url = 'file:///some/place/onthe/fs'

        subjects = db_utils.get_table(engine, 'subjects')
        temp = dict(deleted=False,
                    created_at=now,
                    updated_at=now,
                    status='active',
                    is_public=True,
                    min_disk=0,
                    min_ram=0,
                    id=subject_id)
        subjects.insert().values(temp).execute()

        temp = dict(deleted=False,
                    created_at=now,
                    updated_at=now,
                    subject_id=subject_id,
                    value=url)
        subject_locations.insert().values(temp).execute()
        return subject_id

    def _check_026(self, engine, data):
        subject_locations = db_utils.get_table(engine, 'subject_locations')
        results = subject_locations.select().where(
            subject_locations.c.subject_id == data).execute()

        r = list(results)
        self.assertEqual(1, len(r))
        self.assertEqual('file:///some/place/onthe/fs', r[0]['value'])
        self.assertIn('meta_data', r[0])
        x = pickle.loads(r[0]['meta_data'])
        self.assertEqual({}, x)

    def _check_027(self, engine, data):
        table = "subjects"
        index = "checksum_subject_idx"
        columns = ["checksum"]

        meta = sqlalchemy.MetaData()
        meta.bind = engine

        new_table = sqlalchemy.Table(table, meta, autoload=True)

        index_data = [(idx.name, idx.columns.keys())
                      for idx in new_table.indexes]

        self.assertIn((index, columns), index_data)

    def _check_028(self, engine, data):
        owner_index = "owner_subject_idx"
        columns = ["owner"]

        subjects_table = db_utils.get_table(engine, 'subjects')

        index_data = [(idx.name, idx.columns.keys())
                      for idx in subjects_table.indexes
                      if idx.name == owner_index]

        self.assertIn((owner_index, columns), index_data)

    def _pre_upgrade_029(self, engine):
        subject_locations = db_utils.get_table(engine, 'subject_locations')

        meta_data = {'somelist': ['a', 'b', 'c'], 'avalue': 'hello',
                     'adict': {}}

        now = datetime.datetime.now()
        subject_id = 'fake_029_id'
        url = 'file:///some/place/onthe/fs029'

        subjects = db_utils.get_table(engine, 'subjects')
        temp = dict(deleted=False,
                    created_at=now,
                    updated_at=now,
                    status='active',
                    is_public=True,
                    min_disk=0,
                    min_ram=0,
                    id=subject_id)
        subjects.insert().values(temp).execute()

        pickle_md = pickle.dumps(meta_data)
        temp = dict(deleted=False,
                    created_at=now,
                    updated_at=now,
                    subject_id=subject_id,
                    value=url,
                    meta_data=pickle_md)
        subject_locations.insert().values(temp).execute()

        return meta_data, subject_id

    def _check_029(self, engine, data):
        meta_data = data[0]
        subject_id = data[1]
        subject_locations = db_utils.get_table(engine, 'subject_locations')

        records = subject_locations.select().where(
            subject_locations.c.subject_id == subject_id).execute().fetchall()

        for r in records:
            d = jsonutils.loads(r['meta_data'])
            self.assertEqual(d, meta_data)

    def _check_030(self, engine, data):
        table = "tasks"
        index_type = ('ix_tasks_type', ['type'])
        index_status = ('ix_tasks_status', ['status'])
        index_owner = ('ix_tasks_owner', ['owner'])
        index_deleted = ('ix_tasks_deleted', ['deleted'])
        index_updated_at = ('ix_tasks_updated_at', ['updated_at'])

        meta = sqlalchemy.MetaData()
        meta.bind = engine

        tasks_table = sqlalchemy.Table(table, meta, autoload=True)

        index_data = [(idx.name, idx.columns.keys())
                      for idx in tasks_table.indexes]

        self.assertIn(index_type, index_data)
        self.assertIn(index_status, index_data)
        self.assertIn(index_owner, index_data)
        self.assertIn(index_deleted, index_data)
        self.assertIn(index_updated_at, index_data)

        expected = [u'id',
                    u'type',
                    u'status',
                    u'owner',
                    u'input',
                    u'result',
                    u'message',
                    u'expires_at',
                    u'created_at',
                    u'updated_at',
                    u'deleted_at',
                    u'deleted']

        # NOTE(flwang): Skip the column type checking for now since Jenkins is
        # using sqlalchemy.dialects.postgresql.base.TIMESTAMP instead of
        # DATETIME which is using by mysql and sqlite.
        col_data = [col.name for col in tasks_table.columns]
        self.assertEqual(expected, col_data)

    def _pre_upgrade_031(self, engine):
        subjects = db_utils.get_table(engine, 'subjects')
        now = datetime.datetime.now()
        subject_id = 'fake_031_id'
        temp = dict(deleted=False,
                    created_at=now,
                    updated_at=now,
                    status='active',
                    is_public=True,
                    min_disk=0,
                    min_ram=0,
                    id=subject_id)
        subjects.insert().values(temp).execute()

        locations_table = db_utils.get_table(engine, 'subject_locations')
        locations = [
            ('file://ab', '{"a": "yo yo"}'),
            ('file://ab', '{}'),
            ('file://ab', '{}'),
            ('file://ab1', '{"a": "that one, please"}'),
            ('file://ab1', '{"a": "that one, please"}'),
        ]
        temp = dict(deleted=False,
                    created_at=now,
                    updated_at=now,
                    subject_id=subject_id)

        for location, metadata in locations:
            temp.update(value=location, meta_data=metadata)
            locations_table.insert().values(temp).execute()
        return subject_id

    def _check_031(self, engine, subject_id):
        locations_table = db_utils.get_table(engine, 'subject_locations')
        result = locations_table.select().where(
            locations_table.c.subject_id == subject_id).execute().fetchall()

        locations = set([(x['value'], x['meta_data']) for x in result])
        actual_locations = set([
            ('file://ab', '{"a": "yo yo"}'),
            ('file://ab', '{}'),
            ('file://ab1', '{"a": "that one, please"}'),
        ])
        self.assertFalse(actual_locations.symmetric_difference(locations))

    def _pre_upgrade_032(self, engine):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine, 'task_info')

        tasks = db_utils.get_table(engine, 'tasks')
        now = datetime.datetime.now()
        base_values = {
            'deleted': False,
            'created_at': now,
            'updated_at': now,
            'status': 'active',
            'owner': 'TENANT',
            'type': 'import',
        }
        data = [
            {
                'id': 'task-1',
                'input': 'some input',
                'message': None,
                'result': 'successful'
            },
            {
                'id': 'task-2',
                'input': None,
                'message': None,
                'result': None
            },
        ]
        for task in data:
            task.update(base_values)
            tasks.insert().values(task).execute()
        return data

    def _check_032(self, engine, data):
        task_info_table = db_utils.get_table(engine, 'task_info')

        task_info_refs = task_info_table.select().execute().fetchall()

        self.assertEqual(2, len(task_info_refs))

        for x in range(len(task_info_refs)):
            self.assertEqual(task_info_refs[x].task_id, data[x]['id'])
            self.assertEqual(task_info_refs[x].input, data[x]['input'])
            self.assertEqual(task_info_refs[x].result, data[x]['result'])
            self.assertIsNone(task_info_refs[x].message)

        tasks_table = db_utils.get_table(engine, 'tasks')
        self.assertNotIn('input', tasks_table.c)
        self.assertNotIn('result', tasks_table.c)
        self.assertNotIn('message', tasks_table.c)

    def _pre_upgrade_033(self, engine):
        subjects = db_utils.get_table(engine, 'subjects')
        subject_locations = db_utils.get_table(engine, 'subject_locations')

        now = datetime.datetime.now()
        subject_id = 'fake_id_028_%d'
        url = 'file:///some/place/onthe/fs_%d'
        status_list = ['active', 'saving', 'queued', 'killed',
                       'pending_delete', 'deleted']
        subject_id_list = []

        for (idx, status) in enumerate(status_list):
            temp = dict(deleted=False,
                        created_at=now,
                        updated_at=now,
                        status=status,
                        is_public=True,
                        min_disk=0,
                        min_ram=0,
                        id=subject_id % idx)
            subjects.insert().values(temp).execute()

            temp = dict(deleted=False,
                        created_at=now,
                        updated_at=now,
                        subject_id=subject_id % idx,
                        value=url % idx)
            subject_locations.insert().values(temp).execute()

            subject_id_list.append(subject_id % idx)
        return subject_id_list

    def _check_033(self, engine, data):
        subject_locations = db_utils.get_table(engine, 'subject_locations')

        self.assertIn('status', subject_locations.c)
        self.assertEqual(30, subject_locations.c['status'].type.length)

        status_list = ['active', 'active', 'active',
                       'deleted', 'pending_delete', 'deleted']

        for (idx, subject_id) in enumerate(data):
            results = subject_locations.select().where(
                subject_locations.c.subject_id == subject_id).execute()
            r = list(results)
            self.assertEqual(1, len(r))
            self.assertIn('status', r[0])
            self.assertEqual(status_list[idx], r[0]['status'])

    def _pre_upgrade_034(self, engine):
        subjects = db_utils.get_table(engine, 'subjects')

        now = datetime.datetime.now()
        subject_id = 'fake_id_034'
        temp = dict(deleted=False,
                    created_at=now,
                    status='active',
                    is_public=True,
                    min_disk=0,
                    min_ram=0,
                    id=subject_id)
        subjects.insert().values(temp).execute()

    def _check_034(self, engine, data):
        subjects = db_utils.get_table(engine, 'subjects')
        self.assertIn('virtual_size', subjects.c)

        result = (subjects.select()
                  .where(subjects.c.id == 'fake_id_034')
                  .execute().fetchone())
        self.assertIsNone(result.virtual_size)

    def _pre_upgrade_035(self, engine):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine, 'metadef_namespaces')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine, 'metadef_properties')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine, 'metadef_objects')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine, 'metadef_resource_types')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'metadef_namespace_resource_types')

    def _check_035(self, engine, data):
        meta = sqlalchemy.MetaData()
        meta.bind = engine

        # metadef_namespaces
        table = sqlalchemy.Table("metadef_namespaces", meta, autoload=True)
        index_namespace = ('ix_namespaces_namespace', ['namespace'])
        index_data = [(idx.name, idx.columns.keys())
                      for idx in table.indexes]
        self.assertIn(index_namespace, index_data)

        expected_cols = [u'id',
                         u'namespace',
                         u'display_name',
                         u'description',
                         u'visibility',
                         u'protected',
                         u'owner',
                         u'created_at',
                         u'updated_at']
        col_data = [col.name for col in table.columns]
        self.assertEqual(expected_cols, col_data)

        # metadef_objects
        table = sqlalchemy.Table("metadef_objects", meta, autoload=True)
        index_namespace_id_name = (
            'ix_objects_namespace_id_name', ['namespace_id', 'name'])
        index_data = [(idx.name, idx.columns.keys())
                      for idx in table.indexes]
        self.assertIn(index_namespace_id_name, index_data)

        expected_cols = [u'id',
                         u'namespace_id',
                         u'name',
                         u'description',
                         u'required',
                         u'schema',
                         u'created_at',
                         u'updated_at']
        col_data = [col.name for col in table.columns]
        self.assertEqual(expected_cols, col_data)

        # metadef_properties
        table = sqlalchemy.Table("metadef_properties", meta, autoload=True)
        index_namespace_id_name = (
            'ix_metadef_properties_namespace_id_name',
            ['namespace_id', 'name'])
        index_data = [(idx.name, idx.columns.keys())
                      for idx in table.indexes]
        self.assertIn(index_namespace_id_name, index_data)

        expected_cols = [u'id',
                         u'namespace_id',
                         u'name',
                         u'schema',
                         u'created_at',
                         u'updated_at']
        col_data = [col.name for col in table.columns]
        self.assertEqual(expected_cols, col_data)

        # metadef_resource_types
        table = sqlalchemy.Table(
            "metadef_resource_types", meta, autoload=True)
        index_resource_types_name = (
            'ix_metadef_resource_types_name', ['name'])
        index_data = [(idx.name, idx.columns.keys())
                      for idx in table.indexes]
        self.assertIn(index_resource_types_name, index_data)

        expected_cols = [u'id',
                         u'name',
                         u'protected',
                         u'created_at',
                         u'updated_at']
        col_data = [col.name for col in table.columns]
        self.assertEqual(expected_cols, col_data)

        # metadef_namespace_resource_types
        table = sqlalchemy.Table(
            "metadef_namespace_resource_types", meta, autoload=True)
        index_ns_res_types_res_type_id_ns_id = (
            'ix_metadef_ns_res_types_res_type_id_ns_id',
            ['resource_type_id', 'namespace_id'])
        index_data = [(idx.name, idx.columns.keys())
                      for idx in table.indexes]
        self.assertIn(index_ns_res_types_res_type_id_ns_id, index_data)

        expected_cols = [u'resource_type_id',
                         u'namespace_id',
                         u'properties_target',
                         u'prefix',
                         u'created_at',
                         u'updated_at']
        col_data = [col.name for col in table.columns]
        self.assertEqual(expected_cols, col_data)

    def _pre_upgrade_036(self, engine):
        meta = sqlalchemy.MetaData()
        meta.bind = engine

        # metadef_objects
        table = sqlalchemy.Table("metadef_objects", meta, autoload=True)
        expected_cols = [u'id',
                         u'namespace_id',
                         u'name',
                         u'description',
                         u'required',
                         u'schema',
                         u'created_at',
                         u'updated_at']
        col_data = [col.name for col in table.columns]
        self.assertEqual(expected_cols, col_data)

        # metadef_properties
        table = sqlalchemy.Table("metadef_properties", meta, autoload=True)
        expected_cols = [u'id',
                         u'namespace_id',
                         u'name',
                         u'schema',
                         u'created_at',
                         u'updated_at']
        col_data = [col.name for col in table.columns]
        self.assertEqual(expected_cols, col_data)

    def _check_036(self, engine, data):
        meta = sqlalchemy.MetaData()
        meta.bind = engine

        # metadef_objects
        table = sqlalchemy.Table("metadef_objects", meta, autoload=True)
        expected_cols = [u'id',
                         u'namespace_id',
                         u'name',
                         u'description',
                         u'required',
                         u'json_schema',
                         u'created_at',
                         u'updated_at']
        col_data = [col.name for col in table.columns]
        self.assertEqual(expected_cols, col_data)

        # metadef_properties
        table = sqlalchemy.Table("metadef_properties", meta, autoload=True)
        expected_cols = [u'id',
                         u'namespace_id',
                         u'name',
                         u'json_schema',
                         u'created_at',
                         u'updated_at']
        col_data = [col.name for col in table.columns]
        self.assertEqual(expected_cols, col_data)

    def _check_037(self, engine, data):
        if engine.name == 'mysql':
            self.assertFalse(unique_constraint_exist('subject_id',
                                                     'subject_properties',
                                                     engine))

            self.assertTrue(unique_constraint_exist(
                'ix_subject_properties_subject_id_name',
                'subject_properties',
                engine))

        subject_members = db_utils.get_table(engine, 'subject_members')
        subjects = db_utils.get_table(engine, 'subjects')

        self.assertFalse(subject_members.c.status.nullable)
        self.assertFalse(subjects.c.protected.nullable)

        now = datetime.datetime.now()
        temp = dict(
            deleted=False,
            created_at=now,
            status='active',
            is_public=True,
            min_disk=0,
            min_ram=0,
            id='fake_subject_035'
        )
        subjects.insert().values(temp).execute()

        subject = (subjects.select()
                 .where(subjects.c.id == 'fake_subject_035')
                 .execute().fetchone())

        self.assertFalse(subject['protected'])

        temp = dict(
            deleted=False,
            created_at=now,
            subject_id='fake_subject_035',
            member='fake_member',
            can_share=True,
            id=3
        )

        subject_members.insert().values(temp).execute()

        subject_member = (subject_members.select()
                        .where(subject_members.c.id == 3)
                        .execute().fetchone())

        self.assertEqual('pending', subject_member['status'])

    def _pre_upgrade_038(self, engine):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine, 'metadef_tags')

    def _check_038(self, engine, data):
        meta = sqlalchemy.MetaData()
        meta.bind = engine

        # metadef_tags
        table = sqlalchemy.Table("metadef_tags", meta, autoload=True)
        expected_cols = [u'id',
                         u'namespace_id',
                         u'name',
                         u'created_at',
                         u'updated_at']
        col_data = [col.name for col in table.columns]
        self.assertEqual(expected_cols, col_data)

    def _check_039(self, engine, data):
        meta = sqlalchemy.MetaData()
        meta.bind = engine

        metadef_namespaces = sqlalchemy.Table('metadef_namespaces', meta,
                                              autoload=True)
        metadef_properties = sqlalchemy.Table('metadef_properties', meta,
                                              autoload=True)
        metadef_objects = sqlalchemy.Table('metadef_objects', meta,
                                           autoload=True)
        metadef_ns_res_types = sqlalchemy.Table(
            'metadef_namespace_resource_types',
            meta, autoload=True)
        metadef_resource_types = sqlalchemy.Table('metadef_resource_types',
                                                  meta, autoload=True)

        tables = [metadef_namespaces, metadef_properties, metadef_objects,
                  metadef_ns_res_types, metadef_resource_types]

        for table in tables:
            for index_name in ['ix_namespaces_namespace',
                               'ix_objects_namespace_id_name',
                               'ix_metadef_properties_namespace_id_name']:
                self.assertFalse(index_exist(index_name, table.name, engine))
            for uc_name in ['resource_type_id', 'namespace', 'name',
                            'namespace_id',
                            'metadef_objects_namespace_id_name_key',
                            'metadef_properties_namespace_id_name_key']:
                self.assertFalse(unique_constraint_exist(uc_name, table.name,
                                                         engine))

        self.assertTrue(index_exist('ix_metadef_ns_res_types_namespace_id',
                                    metadef_ns_res_types.name, engine))

        self.assertTrue(index_exist('ix_metadef_namespaces_namespace',
                                    metadef_namespaces.name, engine))

        self.assertTrue(index_exist('ix_metadef_namespaces_owner',
                                    metadef_namespaces.name, engine))

        self.assertTrue(index_exist('ix_metadef_objects_name',
                                    metadef_objects.name, engine))

        self.assertTrue(index_exist('ix_metadef_objects_namespace_id',
                                    metadef_objects.name, engine))

        self.assertTrue(index_exist('ix_metadef_properties_name',
                                    metadef_properties.name, engine))

        self.assertTrue(index_exist('ix_metadef_properties_namespace_id',
                                    metadef_properties.name, engine))

    def _check_040(self, engine, data):
        meta = sqlalchemy.MetaData()
        meta.bind = engine
        metadef_tags = sqlalchemy.Table('metadef_tags', meta, autoload=True)

        if engine.name == 'mysql':
            self.assertFalse(index_exist('namespace_id',
                             metadef_tags.name, engine))

    def _pre_upgrade_041(self, engine):
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'artifacts')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'artifact_tags')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'artifact_properties')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'artifact_blobs')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'artifact_dependencies')
        self.assertRaises(sqlalchemy.exc.NoSuchTableError,
                          db_utils.get_table, engine,
                          'artifact_locations')

    def _check_041(self, engine, data):
        artifacts_indices = [('ix_artifact_name_and_version',
                              ['name', 'version_prefix', 'version_suffix']),
                             ('ix_artifact_type',
                              ['type_name',
                               'type_version_prefix',
                               'type_version_suffix']),
                             ('ix_artifact_state', ['state']),
                             ('ix_artifact_visibility', ['visibility']),
                             ('ix_artifact_owner', ['owner'])]
        artifacts_columns = ['id',
                             'name',
                             'type_name',
                             'type_version_prefix',
                             'type_version_suffix',
                             'type_version_meta',
                             'version_prefix',
                             'version_suffix',
                             'version_meta',
                             'description',
                             'visibility',
                             'state',
                             'owner',
                             'created_at',
                             'updated_at',
                             'deleted_at',
                             'published_at']
        self.assert_table(engine, 'artifacts', artifacts_indices,
                          artifacts_columns)

        tags_indices = [('ix_artifact_tags_artifact_id', ['artifact_id']),
                        ('ix_artifact_tags_artifact_id_tag_value',
                         ['artifact_id',
                          'value'])]
        tags_columns = ['id',
                        'artifact_id',
                        'value',
                        'created_at',
                        'updated_at']
        self.assert_table(engine, 'artifact_tags', tags_indices, tags_columns)

        prop_indices = [
            ('ix_artifact_properties_artifact_id', ['artifact_id']),
            ('ix_artifact_properties_name', ['name'])]
        prop_columns = ['id',
                        'artifact_id',
                        'name',
                        'string_value',
                        'int_value',
                        'numeric_value',
                        'bool_value',
                        'text_value',
                        'created_at',
                        'updated_at',
                        'position']
        self.assert_table(engine, 'artifact_properties', prop_indices,
                          prop_columns)

        blobs_indices = [
            ('ix_artifact_blobs_artifact_id', ['artifact_id']),
            ('ix_artifact_blobs_name', ['name'])]
        blobs_columns = ['id',
                         'artifact_id',
                         'size',
                         'checksum',
                         'name',
                         'item_key',
                         'position',
                         'created_at',
                         'updated_at']
        self.assert_table(engine, 'artifact_blobs', blobs_indices,
                          blobs_columns)

        dependencies_indices = [
            ('ix_artifact_dependencies_source_id', ['artifact_source']),
            ('ix_artifact_dependencies_direct_dependencies',
             ['artifact_source', 'is_direct']),
            ('ix_artifact_dependencies_dest_id', ['artifact_dest']),
            ('ix_artifact_dependencies_origin_id', ['artifact_origin'])]
        dependencies_columns = ['id',
                                'artifact_source',
                                'artifact_dest',
                                'artifact_origin',
                                'is_direct',
                                'position',
                                'name',
                                'created_at',
                                'updated_at']
        self.assert_table(engine, 'artifact_dependencies',
                          dependencies_indices,
                          dependencies_columns)

        locations_indices = [
            ('ix_artifact_blob_locations_blob_id', ['blob_id'])]
        locations_columns = ['id',
                             'blob_id',
                             'value',
                             'created_at',
                             'updated_at',
                             'position',
                             'status']
        self.assert_table(engine, 'artifact_blob_locations', locations_indices,
                          locations_columns)

    def _pre_upgrade_042(self, engine):
        meta = sqlalchemy.MetaData()
        meta.bind = engine

        metadef_namespaces = sqlalchemy.Table('metadef_namespaces', meta,
                                              autoload=True)
        metadef_objects = sqlalchemy.Table('metadef_objects', meta,
                                           autoload=True)
        metadef_properties = sqlalchemy.Table('metadef_properties', meta,
                                              autoload=True)
        metadef_tags = sqlalchemy.Table('metadef_tags', meta, autoload=True)
        metadef_resource_types = sqlalchemy.Table('metadef_resource_types',
                                                  meta, autoload=True)
        metadef_ns_res_types = sqlalchemy.Table(
            'metadef_namespace_resource_types',
            meta, autoload=True)

        # These will be dropped and recreated as unique constraints.
        self.assertTrue(index_exist('ix_metadef_namespaces_namespace',
                                    metadef_namespaces.name, engine))
        self.assertTrue(index_exist('ix_metadef_objects_namespace_id',
                                    metadef_objects.name, engine))
        self.assertTrue(index_exist('ix_metadef_properties_namespace_id',
                                    metadef_properties.name, engine))
        self.assertTrue(index_exist('ix_metadef_tags_namespace_id',
                                    metadef_tags.name, engine))
        self.assertTrue(index_exist('ix_metadef_resource_types_name',
                                    metadef_resource_types.name, engine))

        # This one will be dropped - not needed
        self.assertTrue(index_exist(
            'ix_metadef_ns_res_types_res_type_id_ns_id',
            metadef_ns_res_types.name, engine))

        # The rest must remain
        self.assertTrue(index_exist('ix_metadef_namespaces_owner',
                                    metadef_namespaces.name, engine))
        self.assertTrue(index_exist('ix_metadef_objects_name',
                                    metadef_objects.name, engine))
        self.assertTrue(index_exist('ix_metadef_properties_name',
                                    metadef_properties.name, engine))
        self.assertTrue(index_exist('ix_metadef_tags_name',
                                    metadef_tags.name, engine))
        self.assertTrue(index_exist('ix_metadef_ns_res_types_namespace_id',
                                    metadef_ns_res_types.name, engine))

        # To be created
        self.assertFalse(unique_constraint_exist
                         ('uq_metadef_objects_namespace_id_name',
                          metadef_objects.name, engine)
                         )
        self.assertFalse(unique_constraint_exist
                         ('uq_metadef_properties_namespace_id_name',
                          metadef_properties.name, engine)
                         )
        self.assertFalse(unique_constraint_exist
                         ('uq_metadef_tags_namespace_id_name',
                          metadef_tags.name, engine)
                         )
        self.assertFalse(unique_constraint_exist
                         ('uq_metadef_namespaces_namespace',
                          metadef_namespaces.name, engine)
                         )
        self.assertFalse(unique_constraint_exist
                         ('uq_metadef_resource_types_name',
                          metadef_resource_types.name, engine)
                         )

    def _check_042(self, engine, data):
        meta = sqlalchemy.MetaData()
        meta.bind = engine

        metadef_namespaces = sqlalchemy.Table('metadef_namespaces', meta,
                                              autoload=True)
        metadef_objects = sqlalchemy.Table('metadef_objects', meta,
                                           autoload=True)
        metadef_properties = sqlalchemy.Table('metadef_properties', meta,
                                              autoload=True)
        metadef_tags = sqlalchemy.Table('metadef_tags', meta, autoload=True)
        metadef_resource_types = sqlalchemy.Table('metadef_resource_types',
                                                  meta, autoload=True)
        metadef_ns_res_types = sqlalchemy.Table(
            'metadef_namespace_resource_types',
            meta, autoload=True)

        # Dropped for unique constraints
        self.assertFalse(index_exist('ix_metadef_namespaces_namespace',
                                     metadef_namespaces.name, engine))
        self.assertFalse(index_exist('ix_metadef_objects_namespace_id',
                                     metadef_objects.name, engine))
        self.assertFalse(index_exist('ix_metadef_properties_namespace_id',
                                     metadef_properties.name, engine))
        self.assertFalse(index_exist('ix_metadef_tags_namespace_id',
                                     metadef_tags.name, engine))
        self.assertFalse(index_exist('ix_metadef_resource_types_name',
                                     metadef_resource_types.name, engine))

        # Dropped - not needed because of the existing primary key
        self.assertFalse(index_exist(
            'ix_metadef_ns_res_types_res_type_id_ns_id',
            metadef_ns_res_types.name, engine))

        # Still exist as before
        self.assertTrue(index_exist('ix_metadef_namespaces_owner',
                                    metadef_namespaces.name, engine))
        self.assertTrue(index_exist('ix_metadef_ns_res_types_namespace_id',
                                    metadef_ns_res_types.name, engine))
        self.assertTrue(index_exist('ix_metadef_objects_name',
                                    metadef_objects.name, engine))
        self.assertTrue(index_exist('ix_metadef_properties_name',
                                    metadef_properties.name, engine))
        self.assertTrue(index_exist('ix_metadef_tags_name',
                                    metadef_tags.name, engine))

        self.assertTrue(unique_constraint_exist
                        ('uq_metadef_namespaces_namespace',
                         metadef_namespaces.name, engine)
                        )
        self.assertTrue(unique_constraint_exist
                        ('uq_metadef_objects_namespace_id_name',
                         metadef_objects.name, engine)
                        )
        self.assertTrue(unique_constraint_exist
                        ('uq_metadef_properties_namespace_id_name',
                         metadef_properties.name, engine)
                        )
        self.assertTrue(unique_constraint_exist
                        ('uq_metadef_tags_namespace_id_name',
                         metadef_tags.name, engine)
                        )
        self.assertTrue(unique_constraint_exist
                        ('uq_metadef_resource_types_name',
                         metadef_resource_types.name, engine)
                        )

    def assert_table(self, engine, table_name, indices, columns):
        table = db_utils.get_table(engine, table_name)
        index_data = [(index.name, index.columns.keys()) for index in
                      table.indexes]
        column_data = [column.name for column in table.columns]
        self.assertItemsEqual(columns, column_data)
        self.assertItemsEqual(indices, index_data)


class TestMigrations(test_base.DbTestCase, test_utils.BaseTestCase):

    def test_no_downgrade(self):
        migrate_file = versions.__path__[0]
        for parent, dirnames, filenames in os.walk(migrate_file):
            for filename in filenames:
                if filename.split('.')[1] == 'py':
                    model_name = filename.split('.')[0]
                    model = __import__(
                        'subject.db.sqlalchemy.migrate_repo.versions.' +
                        model_name)
                    obj = getattr(getattr(getattr(getattr(getattr(
                        model, 'db'), 'sqlalchemy'), 'migrate_repo'),
                        'versions'), model_name)
                    func = getattr(obj, 'downgrade', None)
                    self.assertIsNone(func)


class TestMysqlMigrations(test_base.MySQLOpportunisticTestCase,
                          MigrationsMixin):

    def test_mysql_innodb_tables(self):
        migration.db_sync(engine=self.migrate_engine)

        total = self.migrate_engine.execute(
            "SELECT COUNT(*) "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA='%s'"
            % self.migrate_engine.url.database)
        self.assertGreater(total.scalar(), 0, "No tables found. Wrong schema?")

        noninnodb = self.migrate_engine.execute(
            "SELECT count(*) "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA='%s' "
            "AND ENGINE!='InnoDB' "
            "AND TABLE_NAME!='migrate_version'"
            % self.migrate_engine.url.database)
        count = noninnodb.scalar()
        self.assertEqual(0, count, "%d non InnoDB tables created" % count)


class TestPostgresqlMigrations(test_base.PostgreSQLOpportunisticTestCase,
                               MigrationsMixin):
    pass


class TestSqliteMigrations(test_base.DbTestCase,
                           MigrationsMixin):
    def test_walk_versions(self):
        # No more downgrades
        self._walk_versions(False, False)


class ModelsMigrationSyncMixin(object):

    def get_metadata(self):
        for table in models_metadef.BASE_DICT.metadata.sorted_tables:
            models.BASE.metadata._add_table(table.name, table.schema, table)
        for table in models_glare.BASE.metadata.sorted_tables:
            models.BASE.metadata._add_table(table.name, table.schema, table)
        return models.BASE.metadata

    def get_engine(self):
        return self.engine

    def db_sync(self, engine):
        migration.db_sync(engine=engine)

    # TODO(akamyshikova): remove this method as soon as comparison with Variant
    # will be implemented in oslo.db or alembic
    def compare_type(self, ctxt, insp_col, meta_col, insp_type, meta_type):
        if isinstance(meta_type, types.Variant):
            meta_orig_type = meta_col.type
            insp_orig_type = insp_col.type
            meta_col.type = meta_type.impl
            insp_col.type = meta_type.impl

            try:
                return self.compare_type(ctxt, insp_col, meta_col, insp_type,
                                         meta_type.impl)
            finally:
                meta_col.type = meta_orig_type
                insp_col.type = insp_orig_type
        else:
            ret = super(ModelsMigrationSyncMixin, self).compare_type(
                ctxt, insp_col, meta_col, insp_type, meta_type)
            if ret is not None:
                return ret
            return ctxt.impl.compare_type(insp_col, meta_col)

    def include_object(self, object_, name, type_, reflected, compare_to):
        if name in ['migrate_version'] and type_ == 'table':
            return False
        return True


class ModelsMigrationsSyncMysql(ModelsMigrationSyncMixin,
                                test_migrations.ModelsMigrationsSync,
                                test_base.MySQLOpportunisticTestCase):
    pass


class ModelsMigrationsSyncPostgres(ModelsMigrationSyncMixin,
                                   test_migrations.ModelsMigrationsSync,
                                   test_base.PostgreSQLOpportunisticTestCase):
    pass


class ModelsMigrationsSyncSQLite(ModelsMigrationSyncMixin,
                                 test_migrations.ModelsMigrationsSync,
                                 test_base.DbTestCase):
    pass
