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
Base attribute driver class
"""

import os.path

from oslo_config import cfg
from oslo_log import log as logging

from subject.common import exception
from subject.common import utils
from subject.i18n import _

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class Driver(object):

    def configure(self):
        """
        Configure the driver to use the stored configuration options
        Any store that needs special configuration should implement
        this method. If the store was not able to successfully configure
        itself, it should raise `exception.BadDriverConfiguration`
        """
        # Here we set up the various file-based subject cache paths
        # that we need in order to find the files in different states
        # of cache management.
        self.set_paths()

    def set_paths(self):
        """
        Creates all necessary directories under the base cache directory
        """

        self.base_dir = CONF.subject_cache_dir
        if self.base_dir is None:
            msg = _('Failed to read %s from config') % 'subject_cache_dir'
            LOG.error(msg)
            driver = self.__class__.__module__
            raise exception.BadDriverConfiguration(driver_name=driver,
                                                   reason=msg)

        self.incomplete_dir = os.path.join(self.base_dir, 'incomplete')
        self.invalid_dir = os.path.join(self.base_dir, 'invalid')
        self.queue_dir = os.path.join(self.base_dir, 'queue')

        dirs = [self.incomplete_dir, self.invalid_dir, self.queue_dir]

        for path in dirs:
            utils.safe_mkdirs(path)

    def get_cache_size(self):
        """
        Returns the total size in bytes of the subject cache.
        """
        raise NotImplementedError

    def get_cached_subjects(self):
        """
        Returns a list of records about cached subjects.

        The list of records shall be ordered by subject ID and shall look like::

            [
                {
                'subject_id': <IMAGE_ID>,
                'hits': INTEGER,
                'last_modified': ISO_TIMESTAMP,
                'last_accessed': ISO_TIMESTAMP,
                'size': INTEGER
                }, ...
            ]

        """
        return NotImplementedError

    def is_cached(self, subject_id):
        """
        Returns True if the subject with the supplied ID has its subject
        file cached.

        :param subject_id: Subject ID
        """
        raise NotImplementedError

    def is_cacheable(self, subject_id):
        """
        Returns True if the subject with the supplied ID can have its
        subject file cached, False otherwise.

        :param subject_id: Subject ID
        """
        raise NotImplementedError

    def is_queued(self, subject_id):
        """
        Returns True if the subject identifier is in our cache queue.

        :param subject_id: Subject ID
        """
        raise NotImplementedError

    def delete_all_cached_subjects(self):
        """
        Removes all cached subject files and any attributes about the subjects
        and returns the number of cached subject files that were deleted.
        """
        raise NotImplementedError

    def delete_cached_subject(self, subject_id):
        """
        Removes a specific cached subject file and any attributes about the subject

        :param subject_id: Subject ID
        """
        raise NotImplementedError

    def delete_all_queued_subjects(self):
        """
        Removes all queued subject files and any attributes about the subjects
        and returns the number of queued subject files that were deleted.
        """
        raise NotImplementedError

    def delete_queued_subject(self, subject_id):
        """
        Removes a specific queued subject file and any attributes about the subject

        :param subject_id: Subject ID
        """
        raise NotImplementedError

    def queue_subject(self, subject_id):
        """
        Puts an subject identifier in a queue for caching. Return True
        on successful add to the queue, False otherwise...

        :param subject_id: Subject ID
        """

    def clean(self, stall_time=None):
        """
        Dependent on the driver, clean up and destroy any invalid or incomplete
        cached subjects
        """
        raise NotImplementedError

    def get_least_recently_accessed(self):
        """
        Return a tuple containing the subject_id and size of the least recently
        accessed cached file, or None if no cached files.
        """
        raise NotImplementedError

    def open_for_write(self, subject_id):
        """
        Open a file for writing the subject file for an subject
        with supplied identifier.

        :param subject_id: Subject ID
        """
        raise NotImplementedError

    def open_for_read(self, subject_id):
        """
        Open and yield file for reading the subject file for an subject
        with supplied identifier.

        :param subject_id: Subject ID
        """
        raise NotImplementedError

    def get_subject_filepath(self, subject_id, cache_status='active'):
        """
        This crafts an absolute path to a specific entry

        :param subject_id: Subject ID
        :param cache_status: Status of the subject in the cache
        """
        if cache_status == 'active':
            return os.path.join(self.base_dir, str(subject_id))
        return os.path.join(self.base_dir, cache_status, str(subject_id))

    def get_subject_size(self, subject_id):
        """
        Return the size of the subject file for an subject with supplied
        identifier.

        :param subject_id: Subject ID
        """
        path = self.get_subject_filepath(subject_id)
        return os.path.getsize(path)

    def get_queued_subjects(self):
        """
        Returns a list of subject IDs that are in the queue. The
        list should be sorted by the time the subject ID was inserted
        into the queue.
        """
        raise NotImplementedError
