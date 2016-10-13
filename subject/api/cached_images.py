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
Controller for Subject Cache Management API
"""

from oslo_log import log as logging
import webob.exc

from subject.api import policy
from subject.api.v1 import controller
from subject.common import exception
from subject.common import wsgi
from subject import subject_cache

LOG = logging.getLogger(__name__)


class Controller(controller.BaseController):
    """
    A controller for managing cached subjects.
    """

    def __init__(self):
        self.cache = subject_cache.ImageCache()
        self.policy = policy.Enforcer()

    def _enforce(self, req):
        """Authorize request against 'manage_subject_cache' policy"""
        try:
            self.policy.enforce(req.context, 'manage_subject_cache', {})
        except exception.Forbidden:
            LOG.debug("User not permitted to manage the subject cache")
            raise webob.exc.HTTPForbidden()

    def get_cached_subjects(self, req):
        """
        GET /cached_subjects

        Returns a mapping of records about cached subjects.
        """
        self._enforce(req)
        subjects = self.cache.get_cached_subjects()
        return dict(cached_subjects=subjects)

    def delete_cached_subject(self, req, subject_id):
        """
        DELETE /cached_subjects/<IMAGE_ID>

        Removes an subject from the cache.
        """
        self._enforce(req)
        self.cache.delete_cached_subject(subject_id)

    def delete_cached_subjects(self, req):
        """
        DELETE /cached_subjects - Clear all active cached subjects

        Removes all subjects from the cache.
        """
        self._enforce(req)
        return dict(num_deleted=self.cache.delete_all_cached_subjects())

    def get_queued_subjects(self, req):
        """
        GET /queued_subjects

        Returns a mapping of records about queued subjects.
        """
        self._enforce(req)
        subjects = self.cache.get_queued_subjects()
        return dict(queued_subjects=subjects)

    def queue_subject(self, req, subject_id):
        """
        PUT /queued_subjects/<IMAGE_ID>

        Queues an subject for caching. We do not check to see if
        the subject is in the registry here. That is done by the
        prefetcher...
        """
        self._enforce(req)
        self.cache.queue_subject(subject_id)

    def delete_queued_subject(self, req, subject_id):
        """
        DELETE /queued_subjects/<IMAGE_ID>

        Removes an subject from the cache.
        """
        self._enforce(req)
        self.cache.delete_queued_subject(subject_id)

    def delete_queued_subjects(self, req):
        """
        DELETE /queued_subjects - Clear all active queued subjects

        Removes all subjects from the cache.
        """
        self._enforce(req)
        return dict(num_deleted=self.cache.delete_all_queued_subjects())


class CachedImageDeserializer(wsgi.JSONRequestDeserializer):
    pass


class CachedImageSerializer(wsgi.JSONResponseSerializer):
    pass


def create_resource():
    """Cached Images resource factory method"""
    deserializer = CachedImageDeserializer()
    serializer = CachedImageSerializer()
    return wsgi.Resource(Controller(), deserializer, serializer)
