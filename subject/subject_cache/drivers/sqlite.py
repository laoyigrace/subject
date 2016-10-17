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
Cache driver that uses SQLite to store information about cached subjects
"""

from __future__ import absolute_import
from contextlib import contextmanager
import os
import sqlite3
import stat
import time

from eventlet import sleep
from eventlet import timeout
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from subject.common import exception
from subject.i18n import _, _LE, _LI, _LW
from subject.subject_cache.drivers import base

LOG = logging.getLogger(__name__)

sqlite_opts = [
    cfg.StrOpt('subject_cache_sqlite_db', default='cache.db',
               help=_("""
The relative path to sqlite file database that will be used for subject cache
management.

This is a relative path to the sqlite file database that tracks the age and
usage statistics of subject cache. The path is relative to subject cache base
directory, specified by the configuration option ``subject_cache_dir``.

This is a lightweight database with just one table.

Possible values:
    * A valid relative path to sqlite file database

Related options:
    * ``subject_cache_dir``

""")),
]

CONF = cfg.CONF
CONF.register_opts(sqlite_opts)

DEFAULT_SQL_CALL_TIMEOUT = 2


class SqliteConnection(sqlite3.Connection):

    """
    SQLite DB Connection handler that plays well with eventlet,
    slightly modified from Swift's similar code.
    """

    def __init__(self, *args, **kwargs):
        self.timeout_seconds = kwargs.get('timeout', DEFAULT_SQL_CALL_TIMEOUT)
        kwargs['timeout'] = 0
        sqlite3.Connection.__init__(self, *args, **kwargs)

    def _timeout(self, call):
        with timeout.Timeout(self.timeout_seconds):
            while True:
                try:
                    return call()
                except sqlite3.OperationalError as e:
                    if 'locked' not in str(e):
                        raise
                sleep(0.05)

    def execute(self, *args, **kwargs):
        return self._timeout(lambda: sqlite3.Connection.execute(
            self, *args, **kwargs))

    def commit(self):
        return self._timeout(lambda: sqlite3.Connection.commit(self))


def dict_factory(cur, row):
    return {col[0]: row[idx] for idx, col in enumerate(cur.description)}


class Driver(base.Driver):

    """
    Cache driver that uses xattr file tags and requires a filesystem
    that has atimes set.
    """

    def configure(self):
        """
        Configure the driver to use the stored configuration options
        Any store that needs special configuration should implement
        this method. If the store was not able to successfully configure
        itself, it should raise `exception.BadDriverConfiguration`
        """
        super(Driver, self).configure()

        # Create the SQLite database that will hold our cache attributes
        self.initialize_db()

    def initialize_db(self):
        db = CONF.subject_cache_sqlite_db
        self.db_path = os.path.join(self.base_dir, db)
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False,
                                   factory=SqliteConnection)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cached_subjects (
                    subject_id TEXT PRIMARY KEY,
                    last_accessed REAL DEFAULT 0.0,
                    last_modified REAL DEFAULT 0.0,
                    size INTEGER DEFAULT 0,
                    hits INTEGER DEFAULT 0,
                    checksum TEXT
                );
            """)
            conn.close()
        except sqlite3.DatabaseError as e:
            msg = _("Failed to initialize the subject cache database. "
                    "Got error: %s") % e
            LOG.error(msg)
            raise exception.BadDriverConfiguration(driver_name='sqlite',
                                                   reason=msg)

    def get_cache_size(self):
        """
        Returns the total size in bytes of the subject cache.
        """
        sizes = []
        for path in self.get_cache_files(self.base_dir):
            if path == self.db_path:
                continue
            file_info = os.stat(path)
            sizes.append(file_info[stat.ST_SIZE])
        return sum(sizes)

    def get_hit_count(self, subject_id):
        """
        Return the number of hits that an subject has.

        :param subject_id: Opaque subject identifier
        """
        if not self.is_cached(subject_id):
            return 0

        hits = 0
        with self.get_db() as db:
            cur = db.execute("""SELECT hits FROM cached_subjects
                             WHERE subject_id = ?""",
                             (subject_id,))
            hits = cur.fetchone()[0]
        return hits

    def get_cached_subjects(self):
        """
        Returns a list of records about cached subjects.
        """
        LOG.debug("Gathering cached subject entries.")
        with self.get_db() as db:
            cur = db.execute("""SELECT
                             subject_id, hits, last_accessed, last_modified, size
                             FROM cached_subjects
                             ORDER BY subject_id""")
            cur.row_factory = dict_factory
            return [r for r in cur]

    def is_cached(self, subject_id):
        """
        Returns True if the subject with the supplied ID has its subject
        file cached.

        :param subject_id: Subject ID
        """
        return os.path.exists(self.get_subject_filepath(subject_id))

    def is_cacheable(self, subject_id):
        """
        Returns True if the subject with the supplied ID can have its
        subject file cached, False otherwise.

        :param subject_id: Subject ID
        """
        # Make sure we're not already cached or caching the subject
        return not (self.is_cached(subject_id) or
                    self.is_being_cached(subject_id))

    def is_being_cached(self, subject_id):
        """
        Returns True if the subject with supplied id is currently
        in the process of having its subject file cached.

        :param subject_id: Subject ID
        """
        path = self.get_subject_filepath(subject_id, 'incomplete')
        return os.path.exists(path)

    def is_queued(self, subject_id):
        """
        Returns True if the subject identifier is in our cache queue.

        :param subject_id: Subject ID
        """
        path = self.get_subject_filepath(subject_id, 'queue')
        return os.path.exists(path)

    def delete_all_cached_subjects(self):
        """
        Removes all cached subject files and any attributes about the subjects
        """
        deleted = 0
        with self.get_db() as db:
            for path in self.get_cache_files(self.base_dir):
                delete_cached_file(path)
                deleted += 1
            db.execute("""DELETE FROM cached_subjects""")
            db.commit()
        return deleted

    def delete_cached_subject(self, subject_id):
        """
        Removes a specific cached subject file and any attributes about the subject

        :param subject_id: Subject ID
        """
        path = self.get_subject_filepath(subject_id)
        with self.get_db() as db:
            delete_cached_file(path)
            db.execute("""DELETE FROM cached_subjects WHERE subject_id = ?""",
                       (subject_id, ))
            db.commit()

    def delete_all_queued_subjects(self):
        """
        Removes all queued subject files and any attributes about the subjects
        """
        files = [f for f in self.get_cache_files(self.queue_dir)]
        for file in files:
            os.unlink(file)
        return len(files)

    def delete_queued_subject(self, subject_id):
        """
        Removes a specific queued subject file and any attributes about the subject

        :param subject_id: Subject ID
        """
        path = self.get_subject_filepath(subject_id, 'queue')
        if os.path.exists(path):
            os.unlink(path)

    def clean(self, stall_time=None):
        """
        Delete any subject files in the invalid directory and any
        files in the incomplete directory that are older than a
        configurable amount of time.
        """
        self.delete_invalid_files()

        if stall_time is None:
            stall_time = CONF.subject_cache_stall_time

        now = time.time()
        older_than = now - stall_time
        self.delete_stalled_files(older_than)

    def get_least_recently_accessed(self):
        """
        Return a tuple containing the subject_id and size of the least recently
        accessed cached file, or None if no cached files.
        """
        with self.get_db() as db:
            cur = db.execute("""SELECT subject_id FROM cached_subjects
                             ORDER BY last_accessed LIMIT 1""")
            try:
                subject_id = cur.fetchone()[0]
            except TypeError:
                # There are no more cached subjects
                return None

        path = self.get_subject_filepath(subject_id)
        try:
            file_info = os.stat(path)
            size = file_info[stat.ST_SIZE]
        except OSError:
            size = 0
        return subject_id, size

    @contextmanager
    def open_for_write(self, subject_id):
        """
        Open a file for writing the subject file for an subject
        with supplied identifier.

        :param subject_id: Subject ID
        """
        incomplete_path = self.get_subject_filepath(subject_id, 'incomplete')

        def commit():
            with self.get_db() as db:
                final_path = self.get_subject_filepath(subject_id)
                LOG.debug("Fetch finished, moving "
                          "'%(incomplete_path)s' to '%(final_path)s'",
                          dict(incomplete_path=incomplete_path,
                               final_path=final_path))
                os.rename(incomplete_path, final_path)

                # Make sure that we "pop" the subject from the queue...
                if self.is_queued(subject_id):
                    os.unlink(self.get_subject_filepath(subject_id, 'queue'))

                filesize = os.path.getsize(final_path)
                now = time.time()

                db.execute("""INSERT INTO cached_subjects
                           (subject_id, last_accessed, last_modified, hits, size)
                           VALUES (?, ?, ?, 0, ?)""",
                           (subject_id, now, now, filesize))
                db.commit()

        def rollback(e):
            with self.get_db() as db:
                if os.path.exists(incomplete_path):
                    invalid_path = self.get_subject_filepath(subject_id, 'invalid')

                    LOG.warn(_LW("Fetch of cache file failed (%(e)s), rolling "
                                 "back by moving '%(incomplete_path)s' to "
                                 "'%(invalid_path)s'") %
                             {'e': e,
                              'incomplete_path': incomplete_path,
                              'invalid_path': invalid_path})
                    os.rename(incomplete_path, invalid_path)

                db.execute("""DELETE FROM cached_subjects
                           WHERE subject_id = ?""", (subject_id, ))
                db.commit()

        try:
            with open(incomplete_path, 'wb') as cache_file:
                yield cache_file
        except Exception as e:
            with excutils.save_and_reraise_exception():
                rollback(e)
        else:
            commit()
        finally:
            # if the generator filling the cache file neither raises an
            # exception, nor completes fetching all data, neither rollback
            # nor commit will have been called, so the incomplete file
            # will persist - in that case remove it as it is unusable
            # example: ^c from client fetch
            if os.path.exists(incomplete_path):
                rollback('incomplete fetch')

    @contextmanager
    def open_for_read(self, subject_id):
        """
        Open and yield file for reading the subject file for an subject
        with supplied identifier.

        :param subject_id: Subject ID
        """
        path = self.get_subject_filepath(subject_id)
        with open(path, 'rb') as cache_file:
            yield cache_file
        now = time.time()
        with self.get_db() as db:
            db.execute("""UPDATE cached_subjects
                       SET hits = hits + 1, last_accessed = ?
                       WHERE subject_id = ?""",
                       (now, subject_id))
            db.commit()

    @contextmanager
    def get_db(self):
        """
        Returns a context manager that produces a database connection that
        self-closes and calls rollback if an error occurs while using the
        database connection
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False,
                               factory=SqliteConnection)
        conn.row_factory = sqlite3.Row
        conn.text_factory = str
        conn.execute('PRAGMA synchronous = NORMAL')
        conn.execute('PRAGMA count_changes = OFF')
        conn.execute('PRAGMA temp_store = MEMORY')
        try:
            yield conn
        except sqlite3.DatabaseError as e:
            msg = _LE("Error executing SQLite call. Got error: %s") % e
            LOG.error(msg)
            conn.rollback()
        finally:
            conn.close()

    def queue_subject(self, subject_id):
        """
        This adds a subject to be cache to the queue.

        If the subject already exists in the queue or has already been
        cached, we return False, True otherwise

        :param subject_id: Subject ID
        """
        if self.is_cached(subject_id):
            LOG.info(_LI("Not queueing subject '%s'. Already cached."), subject_id)
            return False

        if self.is_being_cached(subject_id):
            LOG.info(_LI("Not queueing subject '%s'. Already being "
                         "written to cache"), subject_id)
            return False

        if self.is_queued(subject_id):
            LOG.info(_LI("Not queueing subject '%s'. Already queued."), subject_id)
            return False

        path = self.get_subject_filepath(subject_id, 'queue')

        # Touch the file to add it to the queue
        with open(path, "w"):
            pass

        return True

    def delete_invalid_files(self):
        """
        Removes any invalid cache entries
        """
        for path in self.get_cache_files(self.invalid_dir):
            os.unlink(path)
            LOG.info(_LI("Removed invalid cache file %s"), path)

    def delete_stalled_files(self, older_than):
        """
        Removes any incomplete cache entries older than a
        supplied modified time.

        :param older_than: Files written to on or before this timestamp
                           will be deleted.
        """
        for path in self.get_cache_files(self.incomplete_dir):
            if os.path.getmtime(path) < older_than:
                try:
                    os.unlink(path)
                    LOG.info(_LI("Removed stalled cache file %s"), path)
                except Exception as e:
                    msg = (_LW("Failed to delete file %(path)s. "
                               "Got error: %(e)s"),
                           dict(path=path, e=e))
                    LOG.warn(msg)

    def get_queued_subjects(self):
        """
        Returns a list of subject IDs that are in the queue. The
        list should be sorted by the time the subject ID was inserted
        into the queue.
        """
        files = [f for f in self.get_cache_files(self.queue_dir)]
        items = []
        for path in files:
            mtime = os.path.getmtime(path)
            items.append((mtime, os.path.basename(path)))

        items.sort()
        return [subject_id for (modtime, subject_id) in items]

    def get_cache_files(self, basepath):
        """
        Returns cache files in the supplied directory

        :param basepath: Directory to look in for cache files
        """
        for fname in os.listdir(basepath):
            path = os.path.join(basepath, fname)
            if path != self.db_path and os.path.isfile(path):
                yield path


def delete_cached_file(path):
    if os.path.exists(path):
        LOG.debug("Deleting subject cache file '%s'", path)
        os.unlink(path)
    else:
        LOG.warn(_LW("Cached subject file '%s' doesn't exist, unable to"
                     " delete") % path)
