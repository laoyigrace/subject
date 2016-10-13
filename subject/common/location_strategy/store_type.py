# Copyright 2014 IBM Corp.
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

"""Storage preference based location strategy module"""

from oslo_config import cfg
from oslo_log import log as logging
import six
import six.moves.urllib.parse as urlparse

from subject.i18n import _, _LW

LOG = logging.getLogger(__name__)

store_type_opts = [
    cfg.ListOpt('store_type_preference',
                default=[],
                help=_("""
Preference order of storage backends.

Provide a comma separated list of store names in the order in
which subjects should be retrieved from storage backends.
These store names must be registered with the ``stores``
configuration option.

NOTE: The ``store_type_preference`` configuration option is applied
only if ``store_type`` is chosen as a value for the
``location_strategy`` configuration option. An empty list will not
change the location order.

Possible values:
    * Empty list
    * Comma separated list of registered store names. Legal values are:
        * file
        * http
        * rbd
        * swift
        * sheepdog
        * cinder
        * vmware

Related options:
    * location_strategy
    * stores

"""))
]

CONF = cfg.CONF
CONF.register_opts(store_type_opts, group='store_type_location_strategy')

_STORE_TO_SCHEME_MAP = {}


def get_strategy_name():
    """Return strategy module name."""
    return 'store_type'


def init():
    """Initialize strategy module."""
    # NOTE(zhiyan): We have a plan to do a reusable subject client library for
    # all clients like Nova and Cinder in near period, it would be able to
    # contains common code to provide uniform subject service interface for them,
    # just like Brick in Cinder, this code can be moved to there and shared
    # between Glance and client both side. So this implementation as far as
    # possible to prevent make relationships with Glance(server)-specific code,
    # for example: using functions within store module to validate
    # 'store_type_preference' option.
    mapping = {'file': ['file', 'filesystem'],
               'http': ['http', 'https'],
               'rbd': ['rbd'],
               'swift': ['swift', 'swift+https', 'swift+http'],
               'sheepdog': ['sheepdog'],
               'cinder': ['cinder'],
               'vmware': ['vsphere']}
    _STORE_TO_SCHEME_MAP.clear()
    _STORE_TO_SCHEME_MAP.update(mapping)


def get_ordered_locations(locations, uri_key='url', **kwargs):
    """
    Order subject location list.

    :param locations: The original subject location list.
    :param uri_key: The key name for location URI in subject location dictionary.
    :returns: The subject location list with preferred store type order.
    """
    def _foreach_store_type_preference():
        store_types = CONF.store_type_location_strategy.store_type_preference
        for preferred_store in store_types:
            preferred_store = str(preferred_store).strip()
            if not preferred_store:
                continue
            # NOTE(dharinic): The following conversion of ``filesystem`` and
            # ``vmware_datastore`` to ``file`` and ``vmware`` respectively
            # are to make store names consistent in Glance and glance_store
            # and also be backward compatible.
            # Reference: Bug 1615852
            if preferred_store == 'filesystem':
                preferred_store = 'file'
                msg = _LW('The value ``filesystem`` is DEPRECATED for use '
                          'with ``store_type_preference``. It will be '
                          'removed in the Pike release. Please use ``file`` '
                          'instead. Please see the Glance Newton release '
                          'notes for more information.')
                LOG.warn(msg)
            if preferred_store == 'vmware_datastore':
                preferred_store = 'vmware'
                msg = _LW('The value ``vmware_datastore`` is DEPRECATED for '
                          'use with ``store_type_preference``. It will be '
                          'removed in the Pike release. Please use ``vmware`` '
                          'instead. Please see the Glance Newton release '
                          'notes for more information.')
                LOG.warn(msg)
            yield preferred_store

    if not locations:
        return locations

    preferences = {}
    others = []
    for preferred_store in _foreach_store_type_preference():
        preferences[preferred_store] = []

    for location in locations:
        uri = location.get(uri_key)
        if not uri:
            continue
        pieces = urlparse.urlparse(uri.strip())

        store_name = None
        for store, schemes in six.iteritems(_STORE_TO_SCHEME_MAP):
            if pieces.scheme.strip() in schemes:
                store_name = store
                break

        if store_name in preferences:
            preferences[store_name].append(location)
        else:
            others.append(location)

    ret = []
    # NOTE(zhiyan): While configuration again since py26 does not support
    # ordereddict container.
    for preferred_store in _foreach_store_type_preference():
        ret.extend(preferences[preferred_store])

    ret.extend(others)

    return ret