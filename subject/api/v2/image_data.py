# Copyright 2012 OpenStack Foundation.
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
from cursive import exception as cursive_exception
import glance_store
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils
import webob.exc

import subject.api.policy
from subject.common import exception
from subject.common import trust_auth
from subject.common import utils
from subject.common import wsgi
import subject.db
import subject.gateway
from subject.i18n import _, _LE, _LI
import subject.notifier


LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class ImageDataController(object):
    def __init__(self, db_api=None, store_api=None,
                 policy_enforcer=None, notifier=None,
                 gateway=None):
        if gateway is None:
            db_api = db_api or subject.db.get_api()
            store_api = store_api or glance_store
            policy = policy_enforcer or subject.api.policy.Enforcer()
            notifier = notifier or subject.notifier.Notifier()
            gateway = subject.gateway.Gateway(db_api, store_api,
                                              notifier, policy)
        self.gateway = gateway

    def _restore(self, subject_repo, subject):
        """
        Restore the subject to queued status.

        :param subject_repo: The instance of SubjectRepo
        :param subject: The subject will be restored
        """
        try:
            if subject_repo and subject:
                subject.status = 'queued'
                subject_repo.save(subject)
        except Exception as e:
            msg = (_LE("Unable to restore subject %(subject_id)s: %(e)s") %
                   {'subject_id': subject.subject_id,
                    'e': encodeutils.exception_to_unicode(e)})
            LOG.exception(msg)

    def _delete(self, subject_repo, subject):
        """Delete the subject.

        :param subject_repo: The instance of SubjectRepo
        :param subject: The subject that will be deleted
        """
        try:
            if subject_repo and subject:
                subject.status = 'killed'
                subject_repo.save(subject)
        except Exception as e:
            msg = (_LE("Unable to delete subject %(subject_id)s: %(e)s") %
                   {'subject_id': subject.subject_id,
                    'e': encodeutils.exception_to_unicode(e)})
            LOG.exception(msg)

    @utils.mutating
    def upload(self, req, subject_id, data, size):
        subject_repo = self.gateway.get_repo(req.context)
        subject = None
        refresher = None
        cxt = req.context
        try:
            subject = subject_repo.get(subject_id)
            subject.status = 'saving'
            try:
                if CONF.data_api == 'subject.db.registry.api':
                    # create a trust if backend is registry
                    try:
                        # request user plugin for current token
                        user_plugin = req.environ.get('keystone.token_auth')
                        roles = []
                        # use roles from request environment because they
                        # are not transformed to lower-case unlike cxt.roles
                        for role_info in req.environ.get(
                                'keystone.token_info')['token']['roles']:
                            roles.append(role_info['name'])
                        refresher = trust_auth.TokenRefresher(user_plugin,
                                                              cxt.tenant,
                                                              roles)
                    except Exception as e:
                        LOG.info(_LI("Unable to create trust: %s "
                                     "Use the existing user token."),
                                 encodeutils.exception_to_unicode(e))

                subject_repo.save(subject, from_state='queued')
                subject.set_data(data, size)

                try:
                    subject_repo.save(subject, from_state='saving')
                except exception.NotAuthenticated:
                    if refresher is not None:
                        # request a new token to update an subject in database
                        cxt.auth_token = refresher.refresh_token()
                        subject_repo = self.gateway.get_repo(req.context)
                        subject_repo.save(subject, from_state='saving')
                    else:
                        raise

                try:
                    # release resources required for re-auth
                    if refresher is not None:
                        refresher.release_resources()
                except Exception as e:
                    LOG.info(_LI("Unable to delete trust %(trust)s: %(msg)s"),
                             {"trust": refresher.trust_id,
                              "msg": encodeutils.exception_to_unicode(e)})

            except (glance_store.NotFound,
                    exception.ImageNotFound,
                    exception.Conflict):
                msg = (_("Subject %s could not be found after upload. "
                         "The subject may have been deleted during the "
                         "upload, cleaning up the chunks uploaded.") %
                       subject_id)
                LOG.warn(msg)
                # NOTE(sridevi): Cleaning up the uploaded chunks.
                try:
                    subject.delete()
                except exception.ImageNotFound:
                    # NOTE(sridevi): Ignore this exception
                    pass
                raise webob.exc.HTTPGone(explanation=msg,
                                         request=req,
                                         content_type='text/plain')
            except exception.NotAuthenticated:
                msg = (_("Authentication error - the token may have "
                         "expired during file upload. Deleting subject data for "
                         "%s.") % subject_id)
                LOG.debug(msg)
                try:
                    subject.delete()
                except exception.NotAuthenticated:
                    # NOTE: Ignore this exception
                    pass
                raise webob.exc.HTTPUnauthorized(explanation=msg,
                                                 request=req,
                                                 content_type='text/plain')
        except ValueError as e:
            LOG.debug("Cannot save data for subject %(id)s: %(e)s",
                      {'id': subject_id,
                       'e': encodeutils.exception_to_unicode(e)})
            self._restore(subject_repo, subject)
            raise webob.exc.HTTPBadRequest(
                explanation=encodeutils.exception_to_unicode(e))

        except glance_store.StoreAddDisabled:
            msg = _("Error in store configuration. Adding subjects to store "
                    "is disabled.")
            LOG.exception(msg)
            self._restore(subject_repo, subject)
            raise webob.exc.HTTPGone(explanation=msg, request=req,
                                     content_type='text/plain')

        except exception.InvalidImageStatusTransition as e:
            msg = encodeutils.exception_to_unicode(e)
            LOG.exception(msg)
            raise webob.exc.HTTPConflict(explanation=e.msg, request=req)

        except exception.Forbidden as e:
            msg = ("Not allowed to upload subject data for subject %s" %
                   subject_id)
            LOG.debug(msg)
            raise webob.exc.HTTPForbidden(explanation=msg, request=req)

        except exception.NotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.msg)

        except glance_store.StorageFull as e:
            msg = _("Subject storage media "
                    "is full: %s") % encodeutils.exception_to_unicode(e)
            LOG.error(msg)
            self._restore(subject_repo, subject)
            raise webob.exc.HTTPRequestEntityTooLarge(explanation=msg,
                                                      request=req)

        except exception.StorageQuotaFull as e:
            msg = _("Subject exceeds the storage "
                    "quota: %s") % encodeutils.exception_to_unicode(e)
            LOG.error(msg)
            self._restore(subject_repo, subject)
            raise webob.exc.HTTPRequestEntityTooLarge(explanation=msg,
                                                      request=req)

        except exception.ImageSizeLimitExceeded as e:
            msg = _("The incoming subject is "
                    "too large: %s") % encodeutils.exception_to_unicode(e)
            LOG.error(msg)
            self._restore(subject_repo, subject)
            raise webob.exc.HTTPRequestEntityTooLarge(explanation=msg,
                                                      request=req)

        except glance_store.StorageWriteDenied as e:
            msg = _("Insufficient permissions on subject "
                    "storage media: %s") % encodeutils.exception_to_unicode(e)
            LOG.error(msg)
            self._restore(subject_repo, subject)
            raise webob.exc.HTTPServiceUnavailable(explanation=msg,
                                                   request=req)

        except cursive_exception.SignatureVerificationError as e:
            msg = (_LE("Signature verification failed for subject %(id)s: %(e)s")
                   % {'id': subject_id,
                      'e': encodeutils.exception_to_unicode(e)})
            LOG.error(msg)
            self._delete(subject_repo, subject)
            raise webob.exc.HTTPBadRequest(explanation=msg)

        except webob.exc.HTTPGone as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to upload subject data due to HTTP error"))

        except webob.exc.HTTPError as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to upload subject data due to HTTP error"))
                self._restore(subject_repo, subject)

        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Failed to upload subject data due to "
                                  "internal error"))
                self._restore(subject_repo, subject)

    def download(self, req, subject_id):
        subject_repo = self.gateway.get_repo(req.context)
        try:
            subject = subject_repo.get(subject_id)
            if subject.status == 'deactivated' and not req.context.is_admin:
                msg = _('The requested subject has been deactivated. '
                        'Subject data download is forbidden.')
                raise exception.Forbidden(message=msg)
        except exception.NotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.msg)
        except exception.Forbidden as e:
            LOG.debug("User not permitted to download subject '%s'", subject_id)
            raise webob.exc.HTTPForbidden(explanation=e.msg)

        return subject


class RequestDeserializer(wsgi.JSONRequestDeserializer):

    def upload(self, request):
        try:
            request.get_content_type(('application/octet-stream',))
        except exception.InvalidContentType as e:
            raise webob.exc.HTTPUnsupportedMediaType(explanation=e.msg)

        subject_size = request.content_length or None
        return {'size': subject_size, 'data': request.body_file}


class ResponseSerializer(wsgi.JSONResponseSerializer):

    def download(self, response, subject):
        offset, chunk_size = 0, None
        range_val = response.request.get_content_range()

        if range_val:
            # NOTE(flaper87): if not present, both, start
            # and stop, will be None.
            if range_val.start is not None:
                offset = range_val.start

            if range_val.stop is not None:
                chunk_size = range_val.stop - offset

        response.headers['Content-Type'] = 'application/octet-stream'

        try:
            # NOTE(markwash): filesystem store (and maybe others?) cause a
            # problem with the caching middleware if they are not wrapped in
            # an iterator very strange
            response.app_iter = iter(subject.get_data(offset=offset,
                                                    chunk_size=chunk_size))
        except glance_store.NotFound as e:
            raise webob.exc.HTTPNoContent(explanation=e.msg)
        except glance_store.RemoteServiceUnavailable as e:
            raise webob.exc.HTTPServiceUnavailable(explanation=e.msg)
        except (glance_store.StoreGetNotSupported,
                glance_store.StoreRandomGetNotSupported) as e:
            raise webob.exc.HTTPBadRequest(explanation=e.msg)
        except exception.Forbidden as e:
            LOG.debug("User not permitted to download subject '%s'", subject)
            raise webob.exc.HTTPForbidden(explanation=e.msg)
        # NOTE(saschpe): "response.app_iter = ..." currently resets Content-MD5
        # (https://github.com/Pylons/webob/issues/86), so it should be set
        # afterwards for the time being.
        if subject.checksum:
            response.headers['Content-MD5'] = subject.checksum
        # NOTE(markwash): "response.app_iter = ..." also erroneously resets the
        # content-length
        response.headers['Content-Length'] = str(subject.size)

    def upload(self, response, result):
        response.status_int = 204


def create_resource():
    """Subject data resource factory method"""
    deserializer = RequestDeserializer()
    serializer = ResponseSerializer()
    controller = ImageDataController()
    return wsgi.Resource(controller, deserializer, serializer)
