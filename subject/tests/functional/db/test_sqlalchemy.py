# Copyright 2012 OpenStack Foundation
# Copyright 2013 IBM Corp.
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

from oslo_config import cfg
from oslo_db import options

from subject.common import exception
import subject.db.sqlalchemy.api
from subject.db.sqlalchemy import models as db_models
from subject.db.sqlalchemy import models_glare as artifact_models
from subject.db.sqlalchemy import models_metadef as metadef_models
import subject.tests.functional.db as db_tests
from subject.tests.functional.db import base
from subject.tests.functional.db import base_glare
from subject.tests.functional.db import base_metadef

CONF = cfg.CONF


def get_db(config):
    options.set_defaults(CONF, connection='sqlite://')
    config(debug=False)
    db_api = subject.db.sqlalchemy.api
    return db_api


def reset_db(db_api):
    db_models.unregister_models(db_api.get_engine())
    db_models.register_models(db_api.get_engine())


def reset_db_metadef(db_api):
    metadef_models.unregister_models(db_api.get_engine())
    metadef_models.register_models(db_api.get_engine())


def reset_db_artifacts(db_api):
    artifact_models.unregister_models(db_api.get_engine())
    artifact_models.register_models(db_api.get_engine())


class TestSqlAlchemyDriver(base.TestDriver,
                           base.DriverTests,
                           base.FunctionalInitWrapper):

    def setUp(self):
        db_tests.load(get_db, reset_db)
        super(TestSqlAlchemyDriver, self).setUp()
        self.addCleanup(db_tests.reset)

    def test_get_subject_with_invalid_long_subject_id(self):
        subject_id = '343f9ba5-0197-41be-9543-16bbb32e12aa-xxxxxx'
        self.assertRaises(exception.NotFound, self.db_api._subject_get,
                          self.context, subject_id)

    def test_subject_tag_delete_with_invalid_long_subject_id(self):
        subject_id = '343f9ba5-0197-41be-9543-16bbb32e12aa-xxxxxx'
        self.assertRaises(exception.NotFound, self.db_api.subject_tag_delete,
                          self.context, subject_id, 'fake')

    def test_subject_tag_get_all_with_invalid_long_subject_id(self):
        subject_id = '343f9ba5-0197-41be-9543-16bbb32e12aa-xxxxxx'
        self.assertRaises(exception.NotFound, self.db_api.subject_tag_get_all,
                          self.context, subject_id)

    def test_user_get_storage_usage_with_invalid_long_subject_id(self):
        subject_id = '343f9ba5-0197-41be-9543-16bbb32e12aa-xxxxxx'
        self.assertRaises(exception.NotFound,
                          self.db_api.user_get_storage_usage,
                          self.context, 'fake_owner_id', subject_id)


class TestSqlAlchemyVisibility(base.TestVisibility,
                               base.VisibilityTests,
                               base.FunctionalInitWrapper):

    def setUp(self):
        db_tests.load(get_db, reset_db)
        super(TestSqlAlchemyVisibility, self).setUp()
        self.addCleanup(db_tests.reset)


class TestSqlAlchemyMembershipVisibility(base.TestMembershipVisibility,
                                         base.MembershipVisibilityTests,
                                         base.FunctionalInitWrapper):

    def setUp(self):
        db_tests.load(get_db, reset_db)
        super(TestSqlAlchemyMembershipVisibility, self).setUp()
        self.addCleanup(db_tests.reset)


class TestSqlAlchemyDBDataIntegrity(base.TestDriver,
                                    base.FunctionalInitWrapper):
    """Test class for checking the data integrity in the database.

    Helpful in testing scenarios specific to the sqlalchemy api.
    """

    def setUp(self):
        db_tests.load(get_db, reset_db)
        super(TestSqlAlchemyDBDataIntegrity, self).setUp()
        self.addCleanup(db_tests.reset)

    def test_paginate_redundant_sort_keys(self):
        original_method = self.db_api._paginate_query

        def fake_paginate_query(query, model, limit,
                                sort_keys, marker, sort_dir, sort_dirs):
            self.assertEqual(['created_at', 'id'], sort_keys)
            return original_method(query, model, limit,
                                   sort_keys, marker, sort_dir, sort_dirs)

        self.stubs.Set(self.db_api, '_paginate_query',
                       fake_paginate_query)
        self.db_api.subject_get_all(self.context, sort_key=['created_at'])

    def test_paginate_non_redundant_sort_keys(self):
        original_method = self.db_api._paginate_query

        def fake_paginate_query(query, model, limit,
                                sort_keys, marker, sort_dir, sort_dirs):
            self.assertEqual(['name', 'created_at', 'id'], sort_keys)
            return original_method(query, model, limit,
                                   sort_keys, marker, sort_dir, sort_dirs)

        self.stubs.Set(self.db_api, '_paginate_query',
                       fake_paginate_query)
        self.db_api.subject_get_all(self.context, sort_key=['name'])


class TestSqlAlchemyTask(base.TaskTests,
                         base.FunctionalInitWrapper):

    def setUp(self):
        db_tests.load(get_db, reset_db)
        super(TestSqlAlchemyTask, self).setUp()
        self.addCleanup(db_tests.reset)


class TestSqlAlchemyQuota(base.DriverQuotaTests,
                          base.FunctionalInitWrapper):

    def setUp(self):
        db_tests.load(get_db, reset_db)
        super(TestSqlAlchemyQuota, self).setUp()
        self.addCleanup(db_tests.reset)


class TestDBPurge(base.DBPurgeTests,
                  base.FunctionalInitWrapper):

    def setUp(self):
        db_tests.load(get_db, reset_db)
        super(TestDBPurge, self).setUp()
        self.addCleanup(db_tests.reset)


class TestArtifacts(base_glare.ArtifactsTestDriver,
                    base_glare.ArtifactTests):
    def setUp(self):
        db_tests.load(get_db, reset_db_artifacts)
        super(TestArtifacts, self).setUp()
        self.addCleanup(db_tests.reset)


class TestMetadefSqlAlchemyDriver(base_metadef.TestMetadefDriver,
                                  base_metadef.MetadefDriverTests,
                                  base.FunctionalInitWrapper):

    def setUp(self):
        db_tests.load(get_db, reset_db_metadef)
        super(TestMetadefSqlAlchemyDriver, self).setUp()
        self.addCleanup(db_tests.reset)
