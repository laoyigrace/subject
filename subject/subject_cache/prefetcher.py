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
Prefetches subjects into the Subject Cache
"""

import eventlet
import subject_store
from oslo_log import log as logging

from subject.common import exception
from subject import context
from subject.i18n import _LI, _LW
from subject.subject_cache import base
import subject.registry.client.v1.api as registry

LOG = logging.getLogger(__name__)


class Prefetcher(base.CacheApp):

    def __init__(self):
        super(Prefetcher, self).__init__()
        registry.configure_registry_client()
        registry.configure_registry_admin_creds()

    def fetch_subject_into_cache(self, subject_id):
        ctx = context.RequestContext(is_admin=True, show_deleted=True)

        try:
            subject_meta = registry.get_subject_metadata(ctx, subject_id)
            if subject_meta['status'] != 'active':
                LOG.warn(_LW("Subject '%s' is not active. Not caching.") %
                         subject_id)
                return False

        except exception.NotFound:
            LOG.warn(_LW("No metadata found for subject '%s'") % subject_id)
            return False

        location = subject_meta['location']
        subject_data, subject_size = subject_store.get_from_backend(location,
                                                               context=ctx)
        LOG.debug("Caching subject '%s'", subject_id)
        cache_tee_iter = self.cache.cache_tee_iter(subject_id, subject_data,
                                                   subject_meta['checksum'])
        # Subject is tee'd into cache and checksum verified
        # as we iterate
        list(cache_tee_iter)
        return True

    def run(self):

        subjects = self.cache.get_queued_subjects()
        if not subjects:
            LOG.debug("Nothing to prefetch.")
            return True

        num_subjects = len(subjects)
        LOG.debug("Found %d subjects to prefetch", num_subjects)

        pool = eventlet.GreenPool(num_subjects)
        results = pool.imap(self.fetch_subject_into_cache, subjects)
        successes = sum([1 for r in results if r is True])
        if successes != num_subjects:
            LOG.warn(_LW("Failed to successfully cache all "
                         "subjects in queue."))
            return False

        LOG.info(_LI("Successfully cached all %d subjects"), num_subjects)
        return True