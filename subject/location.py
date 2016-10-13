# Copyright 2014 OpenStack Foundation
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

import collections
import copy

from cryptography import exceptions as crypto_exception
from cursive import exception as cursive_exception
from cursive import signature_utils
import subject_store as store
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils

from subject.common import exception
from subject.common import utils
import subject.domain.proxy
from subject.i18n import _, _LE, _LI, _LW


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class SubjectRepoProxy(subject.domain.proxy.Repo):

    def __init__(self, subject_repo, context, store_api, store_utils):
        self.context = context
        self.store_api = store_api
        proxy_kwargs = {'context': context, 'store_api': store_api,
                        'store_utils': store_utils}
        super(SubjectRepoProxy, self).__init__(subject_repo,
                                               item_proxy_class=SubjectProxy,
                                               item_proxy_kwargs=proxy_kwargs)

        self.db_api = subject.db.get_api()

    def _set_acls(self, subject):
        public = subject.visibility == 'public'
        member_ids = []
        if subject.locations and not public:
            member_repo = _get_member_repo_for_store(subject,
                                                     self.context,
                                                     self.db_api,
                                                     self.store_api)
            member_ids = [m.member_id for m in member_repo.list()]
        for location in subject.locations:
            self.store_api.set_acls(location['url'], public=public,
                                    read_tenants=member_ids,
                                    context=self.context)

    def add(self, subject):
        result = super(SubjectRepoProxy, self).add(subject)
        self._set_acls(subject)
        return result

    def save(self, subject, from_state=None):
        result = super(SubjectRepoProxy, self).save(subject, from_state=from_state)
        self._set_acls(subject)
        return result


def _get_member_repo_for_store(subject, context, db_api, store_api):
        subject_member_repo = subject.db.SubjectMemberRepo(
            context, db_api, subject)
        store_subject_repo = subject.location.SubjectMemberRepoProxy(
            subject_member_repo, subject, context, store_api)

        return store_subject_repo


def _check_location_uri(context, store_api, store_utils, uri):
    """Check if an subject location is valid.

    :param context: Glance request context
    :param store_api: store API module
    :param store_utils: store utils module
    :param uri: location's uri string
    """

    try:
        # NOTE(zhiyan): Some stores return zero when it catch exception
        is_ok = (store_utils.validate_external_location(uri) and
                 store_api.get_size_from_backend(uri, context=context) > 0)
    except (store.UnknownScheme, store.NotFound, store.BadStoreUri):
        is_ok = False
    if not is_ok:
        reason = _('Invalid location')
        raise exception.BadStoreUri(message=reason)


def _check_subject_location(context, store_api, store_utils, location):
    _check_location_uri(context, store_api, store_utils, location['url'])
    store_api.check_location_metadata(location['metadata'])


def _set_subject_size(context, subject, locations):
    if not subject.size:
        for location in locations:
            size_from_backend = store.get_size_from_backend(
                location['url'], context=context)

            if size_from_backend:
                # NOTE(flwang): This assumes all locations have the same size
                subject.size = size_from_backend
                break


def _count_duplicated_locations(locations, new):
    """
    To calculate the count of duplicated locations for new one.

    :param locations: The exiting subject location set
    :param new: The new subject location
    :returns: The count of duplicated locations
    """

    ret = 0
    for loc in locations:
        if loc['url'] == new['url'] and loc['metadata'] == new['metadata']:
            ret += 1
    return ret


class SubjectFactoryProxy(subject.domain.proxy.SubjectFactory):
    def __init__(self, factory, context, store_api, store_utils):
        self.context = context
        self.store_api = store_api
        self.store_utils = store_utils
        proxy_kwargs = {'context': context, 'store_api': store_api,
                        'store_utils': store_utils}
        super(SubjectFactoryProxy, self).__init__(factory,
                                                  proxy_class=SubjectProxy,
                                                  proxy_kwargs=proxy_kwargs)

    def new_subject(self, **kwargs):
        locations = kwargs.get('locations', [])
        for loc in locations:
            _check_subject_location(self.context,
                                  self.store_api,
                                  self.store_utils,
                                  loc)
            loc['status'] = 'active'
            if _count_duplicated_locations(locations, loc) > 1:
                raise exception.DuplicateLocation(location=loc['url'])
        return super(SubjectFactoryProxy, self).new_subject(**kwargs)


class StoreLocations(collections.MutableSequence):
    """
    The proxy for store location property. It takes responsibility for::

        1. Location uri correctness checking when adding a new location.
        2. Remove the subject data from the store when a location is removed
           from an subject.

    """
    def __init__(self, subject_proxy, value):
        self.subject_proxy = subject_proxy
        if isinstance(value, list):
            self.value = value
        else:
            self.value = list(value)

    def append(self, location):
        # NOTE(flaper87): Insert this
        # location at the very end of
        # the value list.
        self.insert(len(self.value), location)

    def extend(self, other):
        if isinstance(other, StoreLocations):
            locations = other.value
        else:
            locations = list(other)

        for location in locations:
            self.append(location)

    def insert(self, i, location):
        _check_subject_location(self.subject_proxy.context,
                              self.subject_proxy.store_api,
                              self.subject_proxy.store_utils,
                              location)
        location['status'] = 'active'
        if _count_duplicated_locations(self.value, location) > 0:
            raise exception.DuplicateLocation(location=location['url'])

        self.value.insert(i, location)
        _set_subject_size(self.subject_proxy.context,
                        self.subject_proxy,
                        [location])

    def pop(self, i=-1):
        location = self.value.pop(i)
        try:
            self.subject_proxy.store_utils.delete_subject_location_from_backend(
                self.subject_proxy.context,
                self.subject_proxy.subject.subject_id,
                location)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.value.insert(i, location)
        return location

    def count(self, location):
        return self.value.count(location)

    def index(self, location, *args):
        return self.value.index(location, *args)

    def remove(self, location):
        if self.count(location):
            self.pop(self.index(location))
        else:
            self.value.remove(location)

    def reverse(self):
        self.value.reverse()

    # Mutable sequence, so not hashable
    __hash__ = None

    def __getitem__(self, i):
        return self.value.__getitem__(i)

    def __setitem__(self, i, location):
        _check_subject_location(self.subject_proxy.context,
                              self.subject_proxy.store_api,
                              self.subject_proxy.store_utils,
                              location)
        location['status'] = 'active'
        self.value.__setitem__(i, location)
        _set_subject_size(self.subject_proxy.context,
                        self.subject_proxy,
                        [location])

    def __delitem__(self, i):
        if isinstance(i, slice):
            if i.step not in (None, 1):
                raise NotImplementedError("slice with step")
            self.__delslice__(i.start, i.stop)
            return
        location = None
        try:
            location = self.value[i]
        except Exception:
            del self.value[i]
            return
        self.subject_proxy.store_utils.delete_subject_location_from_backend(
            self.subject_proxy.context,
            self.subject_proxy.subject.subject_id,
            location)
        del self.value[i]

    def __delslice__(self, i, j):
        i = 0 if i is None else max(i, 0)
        j = len(self) if j is None else max(j, 0)
        locations = []
        try:
            locations = self.value[i:j]
        except Exception:
            del self.value[i:j]
            return
        for location in locations:
            self.subject_proxy.store_utils.delete_subject_location_from_backend(
                self.subject_proxy.context,
                self.subject_proxy.subject.subject_id,
                location)
            del self.value[i]

    def __iadd__(self, other):
        self.extend(other)
        return self

    def __contains__(self, location):
        return location in self.value

    def __len__(self):
        return len(self.value)

    def __cast(self, other):
        if isinstance(other, StoreLocations):
            return other.value
        else:
            return other

    def __cmp__(self, other):
        return cmp(self.value, self.__cast(other))

    def __eq__(self, other):
        return self.value == self.__cast(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __iter__(self):
        return iter(self.value)

    def __copy__(self):
        return type(self)(self.subject_proxy, self.value)

    def __deepcopy__(self, memo):
        # NOTE(zhiyan): Only copy location entries, others can be reused.
        value = copy.deepcopy(self.value, memo)
        self.subject_proxy.subject.locations = value
        return type(self)(self.subject_proxy, value)


def _locations_proxy(target, attr):
    """
    Make a location property proxy on the subject object.

    :param target: the subject object on which to add the proxy
    :param attr: the property proxy we want to hook
    """
    def get_attr(self):
        value = getattr(getattr(self, target), attr)
        return StoreLocations(self, value)

    def set_attr(self, value):
        if not isinstance(value, (list, StoreLocations)):
            reason = _('Invalid locations')
            raise exception.BadStoreUri(message=reason)
        ori_value = getattr(getattr(self, target), attr)
        if ori_value != value:
            # NOTE(flwang): If all the URL of passed-in locations are same as
            # current subject locations, that means user would like to only
            # update the metadata, not the URL.
            ordered_value = sorted([loc['url'] for loc in value])
            ordered_ori = sorted([loc['url'] for loc in ori_value])
            if len(ori_value) > 0 and ordered_value != ordered_ori:
                raise exception.Invalid(_('Original locations is not empty: '
                                          '%s') % ori_value)
            # NOTE(zhiyan): Check locations are all valid
            # NOTE(flwang): If all the URL of passed-in locations are same as
            # current subject locations, then it's not necessary to verify those
            # locations again. Otherwise, if there is any restricted scheme in
            # existing locations. _check_subject_location will fail.
            if ordered_value != ordered_ori:
                for loc in value:
                    _check_subject_location(self.context,
                                          self.store_api,
                                          self.store_utils,
                                          loc)
                    loc['status'] = 'active'
                    if _count_duplicated_locations(value, loc) > 1:
                        raise exception.DuplicateLocation(location=loc['url'])
                _set_subject_size(self.context, getattr(self, target), value)
            else:
                for loc in value:
                    loc['status'] = 'active'
            return setattr(getattr(self, target), attr, list(value))

    def del_attr(self):
        value = getattr(getattr(self, target), attr)
        while len(value):
            self.store_utils.delete_subject_location_from_backend(
                self.context,
                self.subject.subject_id,
                value[0])
            del value[0]
            setattr(getattr(self, target), attr, value)
        return delattr(getattr(self, target), attr)

    return property(get_attr, set_attr, del_attr)


class SubjectProxy(subject.domain.proxy.Subject):

    locations = _locations_proxy('subject', 'locations')

    def __init__(self, subject, context, store_api, store_utils):
        self.subject = subject
        self.context = context
        self.store_api = store_api
        self.store_utils = store_utils
        proxy_kwargs = {
            'context': context,
            'subject': self,
            'store_api': store_api,
        }
        super(SubjectProxy, self).__init__(
            subject, member_repo_proxy_class=SubjectMemberRepoProxy,
            member_repo_proxy_kwargs=proxy_kwargs)

    def delete(self):
        self.subject.delete()
        if self.subject.locations:
            for location in self.subject.locations:
                self.store_utils.delete_subject_location_from_backend(
                    self.context,
                    self.subject.subject_id,
                    location)

    def set_data(self, data, size=None):
        if size is None:
            size = 0  # NOTE(markwash): zero -> unknown size

        # Create the verifier for signature verification (if correct properties
        # are present)
        extra_props = self.subject.extra_properties
        if (signature_utils.should_create_verifier(extra_props)):
            # NOTE(bpoulos): if creating verifier fails, exception will be
            # raised
            img_signature = extra_props[signature_utils.SIGNATURE]
            hash_method = extra_props[signature_utils.HASH_METHOD]
            key_type = extra_props[signature_utils.KEY_TYPE]
            cert_uuid = extra_props[signature_utils.CERT_UUID]
            verifier = signature_utils.get_verifier(
                context=self.context,
                img_signature_certificate_uuid=cert_uuid,
                img_signature_hash_method=hash_method,
                img_signature=img_signature,
                img_signature_key_type=key_type
            )
        else:
            verifier = None

        location, size, checksum, loc_meta = self.store_api.add_to_backend(
            CONF,
            self.subject.subject_id,
            utils.LimitingReader(utils.CooperativeReader(data),
                                 CONF.subject_size_cap),
            size,
            context=self.context,
            verifier=verifier)

        # NOTE(bpoulos): if verification fails, exception will be raised
        if verifier:
            try:
                verifier.verify()
                LOG.info(_LI("Successfully verified signature for subject %s"),
                         self.subject.subject_id)
            except crypto_exception.InvalidSignature:
                raise cursive_exception.SignatureVerificationError(
                    _('Signature verification failed')
                )

        self.subject.locations = [{'url': location, 'metadata': loc_meta,
                                 'status': 'active'}]
        self.subject.size = size
        self.subject.checksum = checksum
        self.subject.status = 'active'

    def get_data(self, offset=0, chunk_size=None):
        if not self.subject.locations:
            # NOTE(mclaren): This is the only set of arguments
            # which work with this exception currently, see:
            # https://bugs.launchpad.net/glance-store/+bug/1501443
            # When the above subject_store bug is fixed we can
            # add a msg as usual.
            raise store.NotFound(subject=None)
        err = None
        for loc in self.subject.locations:
            try:
                data, size = self.store_api.get_from_backend(
                    loc['url'],
                    offset=offset,
                    chunk_size=chunk_size,
                    context=self.context)

                return data
            except Exception as e:
                LOG.warn(_LW('Get subject %(id)s data failed: '
                             '%(err)s.')
                         % {'id': self.subject.subject_id,
                            'err': encodeutils.exception_to_unicode(e)})
                err = e
        # tried all locations
        LOG.error(_LE('Glance tried all active locations to get data for '
                      'subject %s but all have failed.') % self.subject.subject_id)
        raise err


class SubjectMemberRepoProxy(subject.domain.proxy.Repo):
    def __init__(self, repo, subject, context, store_api):
        self.repo = repo
        self.subject = subject
        self.context = context
        self.store_api = store_api
        super(SubjectMemberRepoProxy, self).__init__(repo)

    def _set_acls(self):
        public = self.subject.visibility == 'public'
        if self.subject.locations and not public:
            member_ids = [m.member_id for m in self.repo.list()]
            for location in self.subject.locations:
                self.store_api.set_acls(location['url'], public=public,
                                        read_tenants=member_ids,
                                        context=self.context)

    def add(self, member):
        super(SubjectMemberRepoProxy, self).add(member)
        self._set_acls()

    def remove(self, member):
        super(SubjectMemberRepoProxy, self).remove(member)
        self._set_acls()
