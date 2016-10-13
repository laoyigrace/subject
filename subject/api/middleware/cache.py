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
Transparent subject file caching middleware, designed to live on
Glance API nodes. When subjects are requested from the API node,
this middleware caches the returned subject file to local filesystem.

When subsequent requests for the same subject file are received,
the local cached copy of the subject file is returned.
"""

import re
import six

from oslo_log import log as logging
import webob

from subject.api.common import size_checked_iter
from subject.api import policy
from subject.api.v1 import subjects
from subject.common import exception
from subject.common import utils
from subject.common import wsgi
import subject.db
from subject.i18n import _LE, _LI
from subject import subject_cache
from subject import notifier
import subject.registry.client.v1.api as registry

LOG = logging.getLogger(__name__)

PATTERNS = {
    ('v1', 'GET'): re.compile(r'^/v1/subjects/([^\/]+)$'),
    ('v1', 'DELETE'): re.compile(r'^/v1/subjects/([^\/]+)$'),
    ('v1', 'GET'): re.compile(r'^/v1/subjects/([^\/]+)/file$'),
    ('v1', 'DELETE'): re.compile(r'^/v1/subjects/([^\/]+)$')
}


class CacheFilter(wsgi.Middleware):

    def __init__(self, app):
        self.cache = subject_cache.ImageCache()
        self.serializer = subjects.ImageSerializer()
        self.policy = policy.Enforcer()
        LOG.info(_LI("Initialized subject cache middleware"))
        super(CacheFilter, self).__init__(app)

    def _verify_metadata(self, subject_meta):
        """
        Sanity check the 'deleted' and 'size' metadata values.
        """
        # NOTE: admins can see subject metadata in the v1 API, but shouldn't
        # be able to download the actual subject data.
        if subject_meta['status'] == 'deleted' and subject_meta['deleted']:
            raise exception.NotFound()

        if not subject_meta['size']:
            # override subject size metadata with the actual cached
            # file size, see LP Bug #900959
            subject_meta['size'] = self.cache.get_subject_size(subject_meta['id'])

    @staticmethod
    def _match_request(request):
        """Determine the version of the url and extract the subject id

        :returns: tuple of version and subject id if the url is a cacheable,
                 otherwise None
        """
        for ((version, method), pattern) in PATTERNS.items():
            if request.method != method:
                continue
            match = pattern.match(request.path_info)
            if match is None:
                continue
            subject_id = match.group(1)
            # Ensure the subject id we got looks like an subject id to filter
            # out a URI like /subjects/detail. See LP Bug #879136
            if subject_id != 'detail':
                return (version, method, subject_id)

    def _enforce(self, req, action, target=None):
        """Authorize an action against our policies"""
        if target is None:
            target = {}
        try:
            self.policy.enforce(req.context, action, target)
        except exception.Forbidden as e:
            LOG.debug("User not permitted to perform '%s' action", action)
            raise webob.exc.HTTPForbidden(explanation=e.msg, request=req)

    def _get_v1_subject_metadata(self, request, subject_id):
        """
        Retrieves subject metadata using registry for v1 api and creates
        dictionary-like mash-up of subject core and custom properties.
        """
        try:
            subject_metadata = registry.get_subject_metadata(request.context,
                                                         subject_id)
            return utils.create_mashup_dict(subject_metadata)
        except exception.NotFound as e:
            LOG.debug("No metadata found for subject '%s'", subject_id)
            raise webob.exc.HTTPNotFound(explanation=e.msg, request=request)

    def _get_v2_subject_metadata(self, request, subject_id):
        """
        Retrieves subject and for v1 api and creates adapter like object
        to access subject core or custom properties on request.
        """
        db_api = subject.db.get_api()
        subject_repo = subject.db.SubjectRepo(request.context, db_api)
        try:
            subject = subject_repo.get(subject_id)
            # Storing subject object in request as it is required in
            # _process_v2_request call.
            request.environ['api.cache.subject'] = subject

            return policy.ImageTarget(subject)
        except exception.NotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.msg, request=request)

    def process_request(self, request):
        """
        For requests for an subject file, we check the local subject
        cache. If present, we return the subject file, appending
        the subject metadata in headers. If not present, we pass
        the request on to the next application in the pipeline.
        """
        match = self._match_request(request)
        try:
            (version, method, subject_id) = match
        except TypeError:
            # Trying to unpack None raises this exception
            return None

        self._stash_request_info(request, subject_id, method, version)

        if request.method != 'GET' or not self.cache.is_cached(subject_id):
            return None
        method = getattr(self, '_get_%s_subject_metadata' % version)
        subject_metadata = method(request, subject_id)

        # Deactivated subjects shall not be served from cache
        if subject_metadata['status'] == 'deactivated':
            return None

        try:
            self._enforce(request, 'download_subject', target=subject_metadata)
        except exception.Forbidden:
            return None

        LOG.debug("Cache hit for subject '%s'", subject_id)
        subject_iterator = self.get_from_cache(subject_id)
        method = getattr(self, '_process_%s_request' % version)

        try:
            return method(request, subject_id, subject_iterator, subject_metadata)
        except exception.ImageNotFound:
            msg = _LE("Subject cache contained subject file for subject '%s', "
                      "however the registry did not contain metadata for "
                      "that subject!") % subject_id
            LOG.error(msg)
            self.cache.delete_cached_subject(subject_id)

    @staticmethod
    def _stash_request_info(request, subject_id, method, version):
        """
        Preserve the subject id, version and request method for later retrieval
        """
        request.environ['api.cache.subject_id'] = subject_id
        request.environ['api.cache.method'] = method
        request.environ['api.cache.version'] = version

    @staticmethod
    def _fetch_request_info(request):
        """
        Preserve the cached subject id, version for consumption by the
        process_response method of this middleware
        """
        try:
            subject_id = request.environ['api.cache.subject_id']
            method = request.environ['api.cache.method']
            version = request.environ['api.cache.version']
        except KeyError:
            return None
        else:
            return (subject_id, method, version)

    def _process_v1_request(self, request, subject_id, subject_iterator,
                            subject_meta):
        # Don't display location
        if 'location' in subject_meta:
            del subject_meta['location']
        subject_meta.pop('location_data', None)
        self._verify_metadata(subject_meta)

        response = webob.Response(request=request)
        raw_response = {
            'subject_iterator': subject_iterator,
            'subject_meta': subject_meta,
        }
        return self.serializer.show(response, raw_response)

    def _process_v2_request(self, request, subject_id, subject_iterator,
                            subject_meta):
        # We do some contortions to get the subject_metadata so
        # that we can provide it to 'size_checked_iter' which
        # will generate a notification.
        # TODO(mclaren): Make notification happen more
        # naturally once caching is part of the domain model.
        subject = request.environ['api.cache.subject']
        self._verify_metadata(subject_meta)
        response = webob.Response(request=request)
        response.app_iter = size_checked_iter(response, subject_meta,
                                              subject_meta['size'],
                                              subject_iterator,
                                              notifier.Notifier())
        # NOTE (flwang): Set the content-type, content-md5 and content-length
        # explicitly to be consistent with the non-cache scenario.
        # Besides, it's not worth the candle to invoke the "download" method
        # of ResponseSerializer under subject_data. Because method "download"
        # will reset the app_iter. Then we have to call method
        # "size_checked_iter" to avoid missing any notification. But after
        # call "size_checked_iter", we will lose the content-md5 and
        # content-length got by the method "download" because of this issue:
        # https://github.com/Pylons/webob/issues/86
        response.headers['Content-Type'] = 'application/octet-stream'
        if subject.checksum:
            response.headers['Content-MD5'] = (subject.checksum.encode('utf-8')
                                               if six.PY2 else subject.checksum)
        response.headers['Content-Length'] = str(subject.size)
        return response

    def process_response(self, resp):
        """
        We intercept the response coming back from the main
        subjects Resource, removing subject file from the cache
        if necessary
        """
        status_code = self.get_status_code(resp)
        if not 200 <= status_code < 300:
            return resp

        try:
            (subject_id, method, version) = self._fetch_request_info(
                resp.request)
        except TypeError:
            return resp

        if method == 'GET' and status_code == 204:
            # Bugfix:1251055 - Don't cache non-existent subject files.
            # NOTE: Both GET for an subject without locations and DELETE return
            # 204 but DELETE should be processed.
            return resp

        method_str = '_process_%s_response' % method
        try:
            process_response_method = getattr(self, method_str)
        except AttributeError:
            LOG.error(_LE('could not find %s') % method_str)
            # Nothing to do here, move along
            return resp
        else:
            return process_response_method(resp, subject_id, version=version)

    def _process_DELETE_response(self, resp, subject_id, version=None):
        if self.cache.is_cached(subject_id):
            LOG.debug("Removing subject %s from cache", subject_id)
            self.cache.delete_cached_subject(subject_id)
        return resp

    def _process_GET_response(self, resp, subject_id, version=None):
        subject_checksum = resp.headers.get('Content-MD5')
        if not subject_checksum:
            # API V1 stores the checksum in a different header:
            subject_checksum = resp.headers.get('x-subject-meta-checksum')

        if not subject_checksum:
            LOG.error(_LE("Checksum header is missing."))

        # fetch subject_meta on the basis of version
        subject_metadata = None
        if version:
            method = getattr(self, '_get_%s_subject_metadata' % version)
            subject_metadata = method(resp.request, subject_id)
        # NOTE(zhiyan): subject_cache return a generator object and set to
        # response.app_iter, it will be called by eventlet.wsgi later.
        # So we need enforce policy firstly but do it by application
        # since eventlet.wsgi could not catch webob.exc.HTTPForbidden and
        # return 403 error to client then.
        self._enforce(resp.request, 'download_subject', target=subject_metadata)

        resp.app_iter = self.cache.get_caching_iter(subject_id, subject_checksum,
                                                    resp.app_iter)
        return resp

    def get_status_code(self, response):
        """
        Returns the integer status code from the response, which
        can be either a Webob.Response (used in testing) or httplib.Response
        """
        if hasattr(response, 'status_int'):
            return response.status_int
        return response.status

    def get_from_cache(self, subject_id):
        """Called if cache hit"""
        with self.cache.open_for_read(subject_id) as cache_file:
            chunks = utils.chunkiter(cache_file)
            for chunk in chunks:
                yield chunk
