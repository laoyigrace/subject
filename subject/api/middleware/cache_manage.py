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
Subject Cache Management API
"""

from oslo_log import log as logging
import routes

from subject.api import cached_subjects
from subject.common import wsgi
from subject.i18n import _LI

LOG = logging.getLogger(__name__)


class CacheManageFilter(wsgi.Middleware):
    def __init__(self, app):
        mapper = routes.Mapper()
        resource = cached_subjects.create_resource()

        mapper.connect("/v1/cached_subjects",
                       controller=resource,
                       action="get_cached_subjects",
                       conditions=dict(method=["GET"]))

        mapper.connect("/v1/cached_subjects/{subject_id}",
                       controller=resource,
                       action="delete_cached_subject",
                       conditions=dict(method=["DELETE"]))

        mapper.connect("/v1/cached_subjects",
                       controller=resource,
                       action="delete_cached_subjects",
                       conditions=dict(method=["DELETE"]))

        mapper.connect("/v1/queued_subjects/{subject_id}",
                       controller=resource,
                       action="queue_subject",
                       conditions=dict(method=["PUT"]))

        mapper.connect("/v1/queued_subjects",
                       controller=resource,
                       action="get_queued_subjects",
                       conditions=dict(method=["GET"]))

        mapper.connect("/v1/queued_subjects/{subject_id}",
                       controller=resource,
                       action="delete_queued_subject",
                       conditions=dict(method=["DELETE"]))

        mapper.connect("/v1/queued_subjects",
                       controller=resource,
                       action="delete_queued_subjects",
                       conditions=dict(method=["DELETE"]))

        self._mapper = mapper
        self._resource = resource

        LOG.info(_LI("Initialized subject cache management middleware"))
        super(CacheManageFilter, self).__init__(app)

    def process_request(self, request):
        # Map request to our resource object if we can handle it
        match = self._mapper.match(request.path_info, request.environ)
        if match:
            request.environ['wsgiorg.routing_args'] = (None, match)
            return self._resource(request)
        # Pass off downstream if we don't match the request path
        else:
            return None
