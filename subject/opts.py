# Copyright (c) 2014 OpenStack Foundation.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

__all__ = [
    'list_api_opts',
    'list_registry_opts',
    'list_scrubber_opts',
    'list_cache_opts',
    'list_manage_opts',
    'list_artifacts_opts'
]

import copy
import itertools

from osprofiler import opts as profiler

import subject.api.middleware.context
import subject.api.versions
import subject.async.flows.convert
import subject.async.taskflow_executor
import subject.common.config
import subject.common.location_strategy
import subject.common.location_strategy.store_type
import subject.common.property_utils
import subject.common.rpc
import subject.common.wsgi
import subject.subject_cache
import subject.subject_cache.drivers.sqlite
import subject.notifier
import subject.registry
import subject.registry.client
import subject.registry.client.v1.api
import subject.scrubber


_api_opts = [
    (None, list(itertools.chain(
        subject.api.middleware.context.context_opts,
        subject.api.versions.versions_opts,
        subject.common.config.common_opts,
        subject.common.location_strategy.location_strategy_opts,
        subject.common.property_utils.property_opts,
        subject.common.rpc.rpc_opts,
        subject.common.wsgi.bind_opts,
        subject.common.wsgi.eventlet_opts,
        subject.common.wsgi.socket_opts,
        subject.common.wsgi.wsgi_opts,
        subject.subject_cache.drivers.sqlite.sqlite_opts,
        subject.subject_cache.subject_cache_opts,
        subject.notifier.notifier_opts,
        subject.registry.registry_addr_opts,
        subject.registry.client.registry_client_ctx_opts,
        subject.registry.client.registry_client_opts,
        subject.registry.client.v1.api.registry_client_ctx_opts,
        subject.scrubber.scrubber_opts))),
    ('subject_format', subject.common.config.subject_format_opts),
    ('task', subject.common.config.task_opts),
    ('taskflow_executor', list(itertools.chain(
        subject.async.taskflow_executor.taskflow_executor_opts,
        subject.async.flows.convert.convert_task_opts))),
    ('store_type_location_strategy',
     subject.common.location_strategy.store_type.store_type_opts),
    profiler.list_opts()[0],
    ('paste_deploy', subject.common.config.paste_deploy_opts)
]
_registry_opts = [
    (None, list(itertools.chain(
        subject.api.middleware.context.context_opts,
        subject.common.config.common_opts,
        subject.common.wsgi.bind_opts,
        subject.common.wsgi.socket_opts,
        subject.common.wsgi.wsgi_opts,
        subject.common.wsgi.eventlet_opts))),
    profiler.list_opts()[0],
    ('paste_deploy', subject.common.config.paste_deploy_opts)
]
_scrubber_opts = [
    (None, list(itertools.chain(
        subject.common.config.common_opts,
        subject.scrubber.scrubber_opts,
        subject.scrubber.scrubber_cmd_opts,
        subject.scrubber.scrubber_cmd_cli_opts,
        subject.registry.client.registry_client_opts,
        subject.registry.client.registry_client_ctx_opts,
        subject.registry.registry_addr_opts))),
]
_cache_opts = [
    (None, list(itertools.chain(
        subject.common.config.common_opts,
        subject.subject_cache.drivers.sqlite.sqlite_opts,
        subject.subject_cache.subject_cache_opts,
        subject.registry.registry_addr_opts,
        subject.registry.client.registry_client_opts,
        subject.registry.client.registry_client_ctx_opts))),
]
_manage_opts = [
    (None, [])
]
_artifacts_opts = [
    (None, list(itertools.chain(
        subject.api.middleware.context.context_opts,
        subject.api.versions.versions_opts,
        subject.common.wsgi.bind_opts,
        subject.common.wsgi.eventlet_opts,
        subject.common.wsgi.socket_opts,
        subject.notifier.notifier_opts))),
    profiler.list_opts()[0],
    ('paste_deploy', subject.common.config.paste_deploy_opts)
]


def list_api_opts():
    """Return a list of oslo_config options available in Glance API service.

    Each element of the list is a tuple. The first element is the name of the
    group under which the list of elements in the second element will be
    registered. A group name of None corresponds to the [DEFAULT] group in
    config files.

    This function is also discoverable via the 'subject.api' entry point
    under the 'oslo_config.opts' namespace.

    The purpose of this is to allow tools like the Oslo sample config file
    generator to discover the options exposed to users by Glance.

    :returns: a list of (group_name, opts) tuples
    """

    return [(g, copy.deepcopy(o)) for g, o in _api_opts]


def list_registry_opts():
    """Return a list of oslo_config options available in Glance Registry
    service.
    """
    return [(g, copy.deepcopy(o)) for g, o in _registry_opts]


def list_scrubber_opts():
    """Return a list of oslo_config options available in Glance Scrubber
    service.
    """
    return [(g, copy.deepcopy(o)) for g, o in _scrubber_opts]


def list_cache_opts():
    """Return a list of oslo_config options available in Glance Cache
    service.
    """
    return [(g, copy.deepcopy(o)) for g, o in _cache_opts]


def list_manage_opts():
    """Return a list of oslo_config options available in Glance manage."""
    return [(g, copy.deepcopy(o)) for g, o in _manage_opts]


def list_artifacts_opts():
    """Return a list of oslo_config options available in Glance artifacts"""
    return [(g, copy.deepcopy(o)) for g, o in _artifacts_opts]
