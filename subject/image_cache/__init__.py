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
LRU Cache for Subject Data
"""

import hashlib

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import units

from subject.common import exception
from subject.common import utils
from subject.i18n import _, _LE, _LI, _LW

LOG = logging.getLogger(__name__)

subject_cache_opts = [
    cfg.StrOpt('subject_cache_driver', default='sqlite',
               choices=('sqlite', 'xattr'), ignore_case=True,
               help=_("""
The driver to use for subject cache management.

This configuration option provides the flexibility to choose between the
different subject-cache drivers available. An subject-cache driver is responsible
for providing the essential functions of subject-cache like write subjects to/read
subjects from cache, track age and usage of cached subjects, provide a list of
cached subjects, fetch size of the cache, queue subjects for caching and clean up
the cache, etc.

The essential functions of a driver are defined in the base class
``subject.subject_cache.drivers.base.Driver``. All subject-cache drivers (existing
and prospective) must implement this interface. Currently available drivers
are ``sqlite`` and ``xattr``. These drivers primarily differ in the way they
store the information about cached subjects:
    * The ``sqlite`` driver uses a sqlite database (which sits on every subject
    node locally) to track the usage of cached subjects.
    * The ``xattr`` driver uses the extended attributes of files to store this
    information. It also requires a filesystem that sets ``atime`` on the files
    when accessed.

Possible values:
    * sqlite
    * xattr

Related options:
    * None

""")),

    cfg.IntOpt('subject_cache_max_size', default=10 * units.Gi,  # 10 GB
               min=0,
               help=_("""
The upper limit on cache size, in bytes, after which the cache-pruner cleans
up the subject cache.

NOTE: This is just a threshold for cache-pruner to act upon. It is NOT a
hard limit beyond which the subject cache would never grow. In fact, depending
on how often the cache-pruner runs and how quickly the cache fills, the subject
cache can far exceed the size specified here very easily. Hence, care must be
taken to appropriately schedule the cache-pruner and in setting this limit.

Glance caches an subject when it is downloaded. Consequently, the size of the
subject cache grows over time as the number of downloads increases. To keep the
cache size from becoming unmanageable, it is recommended to run the
cache-pruner as a periodic task. When the cache pruner is kicked off, it
compares the current size of subject cache and triggers a cleanup if the subject
cache grew beyond the size specified here. After the cleanup, the size of
cache is less than or equal to size specified here.

Possible values:
    * Any non-negative integer

Related options:
    * None

""")),

    cfg.IntOpt('subject_cache_stall_time', default=86400,  # 24 hours
               min=0,
               help=_("""
The amount of time, in seconds, an incomplete subject remains in the cache.

Incomplete subjects are subjects for which download is in progress. Please see the
description of configuration option ``subject_cache_dir`` for more detail.
Sometimes, due to various reasons, it is possible the download may hang and
the incompletely downloaded subject remains in the ``incomplete`` directory.
This configuration option sets a time limit on how long the incomplete subjects
should remain in the ``incomplete`` directory before they are cleaned up.
Once an incomplete subject spends more time than is specified here, it'll be
removed by cache-cleaner on its next run.

It is recommended to run cache-cleaner as a periodic task on the Glance API
nodes to keep the incomplete subjects from occupying disk space.

Possible values:
    * Any non-negative integer

Related options:
    * None

""")),

    cfg.StrOpt('subject_cache_dir',
               help=_("""
Base directory for subject cache.

This is the location where subject data is cached and served out of. All cached
subjects are stored directly under this directory. This directory also contains
three subdirectories, namely, ``incomplete``, ``invalid`` and ``queue``.

The ``incomplete`` subdirectory is the staging area for downloading subjects. An
subject is first downloaded to this directory. When the subject download is
successful it is moved to the base directory. However, if the download fails,
the partially downloaded subject file is moved to the ``invalid`` subdirectory.

The ``queue``subdirectory is used for queuing subjects for download. This is
used primarily by the cache-prefetcher, which can be scheduled as a periodic
task like cache-pruner and cache-cleaner, to cache subjects ahead of their usage.
Upon receiving the request to cache an subject, Glance touches a file in the
``queue`` directory with the subject id as the file name. The cache-prefetcher,
when running, polls for the files in ``queue`` directory and starts
downloading them in the order they were created. When the download is
successful, the zero-sized file is deleted from the ``queue`` directory.
If the download fails, the zero-sized file remains and it'll be retried the
next time cache-prefetcher runs.

Possible values:
    * A valid path

Related options:
    * ``subject_cache_sqlite_db``

""")),
]

CONF = cfg.CONF
CONF.register_opts(subject_cache_opts)


class ImageCache(object):

    """Provides an LRU cache for subject data."""

    def __init__(self):
        self.init_driver()

    def init_driver(self):
        """
        Create the driver for the cache
        """
        driver_name = CONF.subject_cache_driver
        driver_module = (__name__ + '.drivers.' + driver_name + '.Driver')
        try:
            self.driver_class = importutils.import_class(driver_module)
            LOG.info(_LI("Subject cache loaded driver '%s'."), driver_name)
        except ImportError as import_err:
            LOG.warn(_LW("Subject cache driver "
                         "'%(driver_name)s' failed to load. "
                         "Got error: '%(import_err)s."),
                     {'driver_name': driver_name,
                      'import_err': import_err})

            driver_module = __name__ + '.drivers.sqlite.Driver'
            LOG.info(_LI("Defaulting to SQLite driver."))
            self.driver_class = importutils.import_class(driver_module)
        self.configure_driver()

    def configure_driver(self):
        """
        Configure the driver for the cache and, if it fails to configure,
        fall back to using the SQLite driver which has no odd dependencies
        """
        try:
            self.driver = self.driver_class()
            self.driver.configure()
        except exception.BadDriverConfiguration as config_err:
            driver_module = self.driver_class.__module__
            LOG.warn(_LW("Subject cache driver "
                         "'%(driver_module)s' failed to configure. "
                         "Got error: '%(config_err)s"),
                     {'driver_module': driver_module,
                      'config_err': config_err})
            LOG.info(_LI("Defaulting to SQLite driver."))
            default_module = __name__ + '.drivers.sqlite.Driver'
            self.driver_class = importutils.import_class(default_module)
            self.driver = self.driver_class()
            self.driver.configure()

    def is_cached(self, subject_id):
        """
        Returns True if the subject with the supplied ID has its subject
        file cached.

        :param subject_id: Subject ID
        """
        return self.driver.is_cached(subject_id)

    def is_queued(self, subject_id):
        """
        Returns True if the subject identifier is in our cache queue.

        :param subject_id: Subject ID
        """
        return self.driver.is_queued(subject_id)

    def get_cache_size(self):
        """
        Returns the total size in bytes of the subject cache.
        """
        return self.driver.get_cache_size()

    def get_hit_count(self, subject_id):
        """
        Return the number of hits that an subject has

        :param subject_id: Opaque subject identifier
        """
        return self.driver.get_hit_count(subject_id)

    def get_cached_subjects(self):
        """
        Returns a list of records about cached subjects.
        """
        return self.driver.get_cached_subjects()

    def delete_all_cached_subjects(self):
        """
        Removes all cached subject files and any attributes about the subjects
        and returns the number of cached subject files that were deleted.
        """
        return self.driver.delete_all_cached_subjects()

    def delete_cached_subject(self, subject_id):
        """
        Removes a specific cached subject file and any attributes about the subject

        :param subject_id: Subject ID
        """
        self.driver.delete_cached_subject(subject_id)

    def delete_all_queued_subjects(self):
        """
        Removes all queued subject files and any attributes about the subjects
        and returns the number of queued subject files that were deleted.
        """
        return self.driver.delete_all_queued_subjects()

    def delete_queued_subject(self, subject_id):
        """
        Removes a specific queued subject file and any attributes about the subject

        :param subject_id: Subject ID
        """
        self.driver.delete_queued_subject(subject_id)

    def prune(self):
        """
        Removes all cached subject files above the cache's maximum
        size. Returns a tuple containing the total number of cached
        files removed and the total size of all pruned subject files.
        """
        max_size = CONF.subject_cache_max_size
        current_size = self.driver.get_cache_size()
        if max_size > current_size:
            LOG.debug("Subject cache has free space, skipping prune...")
            return (0, 0)

        overage = current_size - max_size
        LOG.debug("Subject cache currently %(overage)d bytes over max "
                  "size. Starting prune to max size of %(max_size)d ",
                  {'overage': overage, 'max_size': max_size})

        total_bytes_pruned = 0
        total_files_pruned = 0
        entry = self.driver.get_least_recently_accessed()
        while entry and current_size > max_size:
            subject_id, size = entry
            LOG.debug("Pruning '%(subject_id)s' to free %(size)d bytes",
                      {'subject_id': subject_id, 'size': size})
            self.driver.delete_cached_subject(subject_id)
            total_bytes_pruned = total_bytes_pruned + size
            total_files_pruned = total_files_pruned + 1
            current_size = current_size - size
            entry = self.driver.get_least_recently_accessed()

        LOG.debug("Pruning finished pruning. "
                  "Pruned %(total_files_pruned)d and "
                  "%(total_bytes_pruned)d.",
                  {'total_files_pruned': total_files_pruned,
                   'total_bytes_pruned': total_bytes_pruned})
        return total_files_pruned, total_bytes_pruned

    def clean(self, stall_time=None):
        """
        Cleans up any invalid or incomplete cached subjects. The cache driver
        decides what that means...
        """
        self.driver.clean(stall_time)

    def queue_subject(self, subject_id):
        """
        This adds a subject to be cache to the queue.

        If the subject already exists in the queue or has already been
        cached, we return False, True otherwise

        :param subject_id: Subject ID
        """
        return self.driver.queue_subject(subject_id)

    def get_caching_iter(self, subject_id, subject_checksum, subject_iter):
        """
        Returns an iterator that caches the contents of an subject
        while the subject contents are read through the supplied
        iterator.

        :param subject_id: Subject ID
        :param subject_checksum: checksum expected to be generated while
                               iterating over subject data
        :param subject_iter: Iterator that will read subject contents
        """
        if not self.driver.is_cacheable(subject_id):
            return subject_iter

        LOG.debug("Tee'ing subject '%s' into cache", subject_id)

        return self.cache_tee_iter(subject_id, subject_iter, subject_checksum)

    def cache_tee_iter(self, subject_id, subject_iter, subject_checksum):
        try:
            current_checksum = hashlib.md5()

            with self.driver.open_for_write(subject_id) as cache_file:
                for chunk in subject_iter:
                    try:
                        cache_file.write(chunk)
                    finally:
                        current_checksum.update(chunk)
                        yield chunk
                cache_file.flush()

                if (subject_checksum and
                        subject_checksum != current_checksum.hexdigest()):
                    msg = _("Checksum verification failed. Aborted "
                            "caching of subject '%s'.") % subject_id
                    raise exception.GlanceException(msg)

        except exception.GlanceException as e:
            with excutils.save_and_reraise_exception():
                # subject_iter has given us bad, (size_checked_iter has found a
                # bad length), or corrupt data (checksum is wrong).
                LOG.exception(encodeutils.exception_to_unicode(e))
        except Exception as e:
            LOG.exception(_LE("Exception encountered while tee'ing "
                              "subject '%(subject_id)s' into cache: %(error)s. "
                              "Continuing with response.") %
                          {'subject_id': subject_id,
                           'error': encodeutils.exception_to_unicode(e)})

            # If no checksum provided continue responding even if
            # caching failed.
            for chunk in subject_iter:
                yield chunk

    def cache_subject_iter(self, subject_id, subject_iter, subject_checksum=None):
        """
        Cache an subject with supplied iterator.

        :param subject_id: Subject ID
        :param subject_file: Iterator retrieving subject chunks
        :param subject_checksum: Checksum of subject

        :returns: True if subject file was cached, False otherwise
        """
        if not self.driver.is_cacheable(subject_id):
            return False

        for chunk in self.get_caching_iter(subject_id, subject_checksum,
                                           subject_iter):
            pass
        return True

    def cache_subject_file(self, subject_id, subject_file):
        """
        Cache an subject file.

        :param subject_id: Subject ID
        :param subject_file: Subject file to cache

        :returns: True if subject file was cached, False otherwise
        """
        CHUNKSIZE = 64 * units.Mi

        return self.cache_subject_iter(subject_id,
                                     utils.chunkiter(subject_file, CHUNKSIZE))

    def open_for_read(self, subject_id):
        """
        Open and yield file for reading the subject file for an subject
        with supplied identifier.

        :note Upon successful reading of the subject file, the subject's
              hit count will be incremented.

        :param subject_id: Subject ID
        """
        return self.driver.open_for_read(subject_id)

    def get_subject_size(self, subject_id):
        """
        Return the size of the subject file for an subject with supplied
        identifier.

        :param subject_id: Subject ID
        """
        return self.driver.get_subject_size(subject_id)

    def get_queued_subjects(self):
        """
        Returns a list of subject IDs that are in the queue. The
        list should be sorted by the time the subject ID was inserted
        into the queue.
        """
        return self.driver.get_queued_subjects()
