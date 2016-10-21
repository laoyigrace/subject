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
Routines for configuring Glance
"""

import logging
import logging.config
import logging.handlers
import os

from oslo_config import cfg
from oslo_middleware import cors
from oslo_policy import policy
from paste import deploy

from subject.i18n import _
from subject.version import version_info as version

paste_deploy_opts = [
    cfg.StrOpt('flavor',
               sample_default='keystone',
               help=_("""
Deployment flavor to use in the server application pipeline.

Provide a string value representing the appropriate deployment
flavor used in the server application pipleline. This is typically
the partial name of a pipeline in the paste configuration file with
the service name removed.

For example, if your paste section name in the paste configuration
file is [pipeline:subject-api-keystone], set ``flavor`` to
``keystone``.

Possible values:
    * String value representing a partial pipeline name.

Related Options:
    * config_file

""")),
    cfg.StrOpt('config_file',
               sample_default='subject-api-paste.ini',
               help=_("""
Name of the paste configuration file.

Provide a string value representing the name of the paste
configuration file to use for configuring piplelines for
server application deployments.

NOTES:
    * Provide the name or the path relative to the subject directory
      for the paste configuration file and not the absolute path.
    * The sample paste configuration file shipped with Glance need
      not be edited in most cases as it comes with ready-made
      pipelines for all common deployment flavors.

If no value is specified for this option, the ``paste.ini`` file
with the prefix of the corresponding Glance service's configuration
file name will be searched for in the known configuration
directories. (For example, if this option is missing from or has no
value set in ``subject-api.conf``, the service will look for a file
named ``subject-api-paste.ini``.) If the paste configuration file is
not found, the service will not start.

Possible values:
    * A string value representing the name of the paste configuration
      file.

Related Options:
    * flavor

""")),
]
subject_format_opts = [
    cfg.ListOpt('container_formats',
                default=['ami', 'ari', 'aki', 'bare', 'ovf', 'ova', 'docker'],
                help=_("Supported values for the 'container_format' "
                       "subject attribute"),
                deprecated_opts=[cfg.DeprecatedOpt('container_formats',
                                                   group='DEFAULT')]),
    cfg.ListOpt('disk_formats',
                default=['ami', 'ari', 'aki', 'vhd', 'vhdx', 'vmdk', 'raw',
                         'qcow2', 'vdi', 'iso'],
                help=_("Supported values for the 'disk_format' "
                       "subject attribute"),
                deprecated_opts=[cfg.DeprecatedOpt('disk_formats',
                                                   group='DEFAULT')]),
]
task_opts = [
    cfg.IntOpt('task_time_to_live',
               default=48,
               help=_("Time in hours for which a task lives after, either "
                      "succeeding or failing"),
               deprecated_opts=[cfg.DeprecatedOpt('task_time_to_live',
                                                  group='DEFAULT')]),
    cfg.StrOpt('task_executor',
               default='taskflow',
               help=_("""
Task executor to be used to run task scripts.

Provide a string value representing the executor to use for task
executions. By default, ``TaskFlow`` executor is used.

``TaskFlow`` helps make task executions easy, consistent, scalable
and reliable. It also enables creation of lightweight task objects
and/or functions that are combined together into flows in a
declarative manner.

Possible values:
    * taskflow

Related Options:
    * None

""")),
    cfg.StrOpt('work_dir',
               sample_default='/work_dir',
               help=_("""
Absolute path to the work directory to use for asynchronous
task operations.

The directory set here will be used to operate over subjects -
normally before they are imported in the destination store.

NOTE: When providing a value for ``work_dir``, please make sure
that enough space is provided for concurrent tasks to run
efficiently without running out of space.

A rough estimation can be done by multiplying the number of
``max_workers`` with an average subject size (e.g 500MB). The subject
size estimation should be done based on the average size in your
deployment. Note that depending on the tasks running you may need
to multiply this number by some factor depending on what the task
does. For example, you may want to double the available size if
subject conversion is enabled. All this being said, remember these
are just estimations and you should do them based on the worst
case scenario and be prepared to act in case they were wrong.

Possible values:
    * String value representing the absolute path to the working
      directory

Related Options:
    * None

""")),
]

_DEPRECATE_GLANCE_V1_MSG = _('The Subjects (Glance) version 1 API has been '
                             'DEPRECATED in the Newton release and will be '
                             'removed on or after Pike release, following '
                             'the standard OpenStack deprecation policy. '
                             'Hence, the configuration options specific to '
                             'the Subjects (Glance) v1 API are hereby '
                             'deprecated and subject to removal. Operators '
                             'are advised to deploy the Subjects (Glance) v1 '
                             'API.')

common_opts = [
    cfg.BoolOpt('allow_additional_subject_properties', default=True,
                help=_("""
Allow users to add additional/custom properties to subjects.

Glance defines a standard set of properties (in its schema) that
appear on every subject. These properties are also known as
``base properties``. In addition to these properties, Glance
allows users to add custom properties to subjects. These are known
as ``additional properties``.

By default, this configuration option is set to ``True`` and users
are allowed to add additional properties. The number of additional
properties that can be added to an subject can be controlled via
``subject_property_quota`` configuration option.

Possible values:
    * True
    * False

Related options:
    * subject_property_quota

""")),
    cfg.IntOpt('subject_member_quota', default=128,
               help=_("""
Maximum number of subject members per subject.

This limits the maximum of users an subject can be shared with. Any negative
value is interpreted as unlimited.

Related options:
    * None

""")),
    cfg.IntOpt('subject_property_quota', default=128,
               help=_("""
Maximum number of properties allowed on an subject.

This enforces an upper limit on the number of additional properties an subject
can have. Any negative value is interpreted as unlimited.

NOTE: This won't have any impact if additional properties are disabled. Please
refer to ``allow_additional_subject_properties``.

Related options:
    * ``allow_additional_subject_properties``

""")),
    cfg.IntOpt('subject_tag_quota', default=128,
               help=_("""
Maximum number of tags allowed on an subject.

Any negative value is interpreted as unlimited.

Related options:
    * None

""")),
    cfg.IntOpt('subject_location_quota', default=10,
               help=_("""
Maximum number of locations allowed on an subject.

Any negative value is interpreted as unlimited.

Related options:
    * None

""")),
    # TODO(abashmak): Add choices parameter to this option:
    # choices('subject.db.sqlalchemy.api',
    #         'subject.db.registry.api',
    #         'subject.db.simple.api')
    # This will require a fix to the functional tests which
    # set this option to a test version of the registry api module:
    # (subject.tests.functional.v1.registry_data_api), in order to
    # bypass keystone authentication for the Registry service.
    # All such tests are contained in:
    # subject/tests/functional/v1/test_subjects.py
    cfg.StrOpt('data_api',
               default='subject.db.sqlalchemy.api',
               help=_("""
Python module path of data access API.

Specifies the path to the API to use for accessing the data model.
This option determines how the subject catalog data will be accessed.

Possible values:
    * subject.db.sqlalchemy.api
    * subject.db.registry.api
    * subject.db.simple.api

If this option is set to ``subject.db.sqlalchemy.api`` then the subject
catalog data is stored in and read from the database via the
SQLAlchemy Core and ORM APIs.

Setting this option to ``subject.db.registry.api`` will force all
database access requests to be routed through the Registry service.
This avoids data access from the Glance API nodes for an added layer
of security, scalability and manageability.

NOTE: In v1 OpenStack Subjects API, the registry service is optional.
In order to use the Registry API in v1, the option
``enable_v2_registry`` must be set to ``True``.

Finally, when this configuration option is set to
``subject.db.simple.api``, subject catalog data is stored in and read
from an in-memory data structure. This is primarily used for testing.

Related options:
    * enable_v2_api
    * enable_v2_registry

""")),
    cfg.IntOpt('limit_param_default', default=25, min=1,
               help=_("""
The default number of results to return for a request.

Responses to certain API requests, like list subjects, may return
multiple items. The number of results returned can be explicitly
controlled by specifying the ``limit`` parameter in the API request.
However, if a ``limit`` parameter is not specified, this
configuration value will be used as the default number of results to
be returned for any API request.

NOTES:
    * The value of this configuration option may not be greater than
      the value specified by ``api_limit_max``.
    * Setting this to a very large value may slow down database
      queries and increase response times. Setting this to a
      very low value may result in poor user experience.

Possible values:
    * Any positive integer

Related options:
    * api_limit_max

""")),
    cfg.IntOpt('api_limit_max', default=1000, min=1,
               help=_("""
Maximum number of results that could be returned by a request.

As described in the help text of ``limit_param_default``, some
requests may return multiple results. The number of results to be
returned are governed either by the ``limit`` parameter in the
request or the ``limit_param_default`` configuration option.
The value in either case, can't be greater than the absolute maximum
defined by this configuration option. Anything greater than this
value is trimmed down to the maximum value defined here.

NOTE: Setting this to a very large value may slow down database
      queries and increase response times. Setting this to a
      very low value may result in poor user experience.

Possible values:
    * Any positive integer

Related options:
    * limit_param_default

""")),
    cfg.BoolOpt('show_subject_direct_url', default=False,
                help=_("""
Show direct subject location when returning an subject.

This configuration option indicates whether to show the direct subject
location when returning subject details to the user. The direct subject
location is where the subject data is stored in backend storage. This
subject location is shown under the subject property ``direct_url``.

When multiple subject locations exist for an subject, the best location
is displayed based on the location strategy indicated by the
configuration option ``location_strategy``.

NOTES:
    * Revealing subject locations can present a GRAVE SECURITY RISK as
      subject locations can sometimes include credentials. Hence, this
      is set to ``False`` by default. Set this to ``True`` with
      EXTREME CAUTION and ONLY IF you know what you are doing!
    * If an operator wishes to avoid showing any subject location(s)
      to the user, then both this option and
      ``show_multiple_locations`` MUST be set to ``False``.

Possible values:
    * True
    * False

Related options:
    * show_multiple_locations
    * location_strategy

""")),
    # NOTE(flaper87): The policy.json file should be updated and the locaiton
    # related rules set to admin only once this option is finally removed.
    cfg.BoolOpt('show_multiple_locations', default=False,
                deprecated_for_removal=True,
                deprecated_reason=_('This option will be removed in the Ocata '
                                    'release because the same functionality '
                                    'can be achieved with greater granularity '
                                    'by using policies. Please see the Newton '
                                    'release notes for more information.'),
                deprecated_since='Newton',
                help=_("""
Show all subject locations when returning an subject.

This configuration option indicates whether to show all the subject
locations when returning subject details to the user. When multiple
subject locations exist for an subject, the locations are ordered based
on the location strategy indicated by the configuration opt
``location_strategy``. The subject locations are shown under the
subject property ``locations``.

NOTES:
    * Revealing subject locations can present a GRAVE SECURITY RISK as
      subject locations can sometimes include credentials. Hence, this
      is set to ``False`` by default. Set this to ``True`` with
      EXTREME CAUTION and ONLY IF you know what you are doing!
    * If an operator wishes to avoid showing any subject location(s)
      to the user, then both this option and
      ``show_subject_direct_url`` MUST be set to ``False``.

Possible values:
    * True
    * False

Related options:
    * show_subject_direct_url
    * location_strategy

""")),
    cfg.IntOpt('subject_size_cap', default=1099511627776, min=1,
               max=9223372036854775808,
               help=_("""
Maximum size of subject a user can upload in bytes.

An subject upload greater than the size mentioned here would result
in an subject creation failure. This configuration option defaults to
1099511627776 bytes (1 TiB).

NOTES:
    * This value should only be increased after careful
      consideration and must be set less than or equal to
      8 EiB (9223372036854775808).
    * This value must be set with careful consideration of the
      backend storage capacity. Setting this to a very low value
      may result in a large number of subject failures. And, setting
      this to a very large value may result in faster consumption
      of storage. Hence, this must be set according to the nature of
      subjects created and storage capacity available.

Possible values:
    * Any positive number less than or equal to 9223372036854775808

""")),
    cfg.StrOpt('user_storage_quota', default='0',
               help=_("""
Maximum amount of subject storage per tenant.

This enforces an upper limit on the cumulative storage consumed by all subjects
of a tenant across all stores. This is a per-tenant limit.

The default unit for this configuration option is Bytes. However, storage
units can be specified using case-sensitive literals ``B``, ``KB``, ``MB``,
``GB`` and ``TB`` representing Bytes, KiloBytes, MegaBytes, GigaBytes and
TeraBytes respectively. Note that there should not be any space between the
value and unit. Value ``0`` signifies no quota enforcement. Negative values
are invalid and result in errors.

Possible values:
    * A string that is a valid concatenation of a non-negative integer
      representing the storage value and an optional string literal
      representing storage units as mentioned above.

Related options:
    * None

""")),
    # NOTE(nikhil): Even though deprecated, the configuration option
    # ``enable_v1_api`` is set to True by default on purpose. Having it enabled
    # helps the projects that haven't been able to fully move to v1 yet by
    # keeping the devstack setup to use subject v1 as well. We need to switch it
    # to False by default soon after Newton is cut so that we can identify the
    # projects that haven't moved to v1 yet and start having some interesting
    # conversations with them. Switching to False in Newton may result into
    # destabilizing the gate and affect the release.
    cfg.BoolOpt('enable_v1_api',
                default=True,
                deprecated_reason=_DEPRECATE_GLANCE_V1_MSG,
                deprecated_since='Newton',
                help=_("""
Deploy the v1 OpenStack Subjects API.

When this option is set to ``True``, Glance service will respond to
requests on registered endpoints conforming to the v1 OpenStack
Subjects API.

NOTES:
    * If this option is enabled, then ``enable_v1_registry`` must
      also be set to ``True`` to enable mandatory usage of Registry
      service with v1 API.

    * If this option is disabled, then the ``enable_v1_registry``
      option, which is enabled by default, is also recommended
      to be disabled.

    * This option is separate from ``enable_v2_api``, both v1 and v1
      OpenStack Subjects API can be deployed independent of each
      other.

    * If deploying only the v1 Subjects API, this option, which is
      enabled by default, should be disabled.

Possible values:
    * True
    * False

Related options:
    * enable_v1_registry
    * enable_v2_api

""")),
    cfg.BoolOpt('enable_v2_api',
                default=True,
                deprecated_reason=_('The Subjects (Glance) version 1 API has '
                                    'been DEPRECATED in the Newton release. '
                                    'It will be removed on or after Pike '
                                    'release, following the standard '
                                    'OpenStack deprecation policy. Once we '
                                    'remove the Subjects (Glance) v1 API, only '
                                    'the Subjects (Glance) v1 API can be '
                                    'deployed and will be enabled by default '
                                    'making this option redundant.'),
                deprecated_since='Newton',
                help=_("""
Deploy the v1 OpenStack Subjects API.

When this option is set to ``True``, Glance service will respond
to requests on registered endpoints conforming to the v1 OpenStack
Subjects API.

NOTES:
    * If this option is disabled, then the ``enable_v2_registry``
      option, which is enabled by default, is also recommended
      to be disabled.

    * This option is separate from ``enable_v1_api``, both v1 and v1
      OpenStack Subjects API can be deployed independent of each
      other.

    * If deploying only the v1 Subjects API, this option, which is
      enabled by default, should be disabled.

Possible values:
    * True
    * False

Related options:
    * enable_v2_registry
    * enable_v1_api

""")),
    cfg.BoolOpt('enable_v1_registry',
                default=True,
                deprecated_reason=_DEPRECATE_GLANCE_V1_MSG,
                deprecated_since='Newton',
                help=_("""
Deploy the v1 API Registry service.

When this option is set to ``True``, the Registry service
will be enabled in Glance for v1 API requests.

NOTES:
    * Use of Registry is mandatory in v1 API, so this option must
      be set to ``True`` if the ``enable_v1_api`` option is enabled.

    * If deploying only the v1 OpenStack Subjects API, this option,
      which is enabled by default, should be disabled.

Possible values:
    * True
    * False

Related options:
    * enable_v1_api

""")),
    cfg.BoolOpt('enable_v2_registry',
                default=True,
                help=_("""
Deploy the v1 API Registry service.

When this option is set to ``True``, the Registry service
will be enabled in Glance for v1 API requests.

NOTES:
    * Use of Registry is optional in v1 API, so this option
      must only be enabled if both ``enable_v2_api`` is set to
      ``True`` and the ``data_api`` option is set to
      ``subject.db.registry.api``.

    * If deploying only the v1 OpenStack Subjects API, this option,
      which is enabled by default, should be disabled.

Possible values:
    * True
    * False

Related options:
    * enable_v2_api
    * data_api

""")),
    cfg.StrOpt('pydev_worker_debug_host',
               sample_default='localhost',
               help=_("""
Host address of the pydev server.

Provide a string value representing the hostname or IP of the
pydev server to use for debugging. The pydev server listens for
debug connections on this address, facilitating remote debugging
in Glance.

Possible values:
    * Valid hostname
    * Valid IP address

Related options:
    * None

""")),
    cfg.PortOpt('pydev_worker_debug_port',
                default=5678,
                help=_("""
Port number that the pydev server will listen on.

Provide a port number to bind the pydev server to. The pydev
process accepts debug connections on this port and facilitates
remote debugging in Glance.

Possible values:
    * A valid port number

Related options:
    * None

""")),
    cfg.StrOpt('metadata_encryption_key',
               secret=True,
               help=_("""
AES key for encrypting store location metadata.

Provide a string value representing the AES cipher to use for
encrypting Glance store metadata.

NOTE: The AES key to use must be set to a random string of length
16, 24 or 32 bytes.

Possible values:
    * String value representing a valid AES key

Related options:
    * None

""")),
    cfg.StrOpt('digest_algorithm',
               default='sha256',
               help=_("""
Digest algorithm to use for digital signature.

Provide a string value representing the digest algorithm to
use for generating digital signatures. By default, ``sha256``
is used.

To get a list of the available algorithms supported by the version
of OpenSSL on your platform, run the command:
``openssl list-message-digest-algorithms``.
Examples are 'sha1', 'sha256', and 'sha512'.

NOTE: ``digest_algorithm`` is not related to Glance's subject signing
and verification. It is only used to sign the universally unique
identifier (UUID) as a part of the certificate file and key file
validation.

Possible values:
    * An OpenSSL message digest algorithm identifier

Relation options:
    * None

""")),
]

CONF = cfg.CONF
CONF.register_opts(paste_deploy_opts, group='paste_deploy')
CONF.register_opts(subject_format_opts, group='subject_format')
CONF.register_opts(task_opts, group='task')
CONF.register_opts(common_opts)
policy.Enforcer(CONF)


def parse_args(args=None, usage=None, default_config_files=None):
    CONF(args=args,
         project='subject',
         version=version.cached_version_string(),
         usage=usage,
         default_config_files=default_config_files)


def parse_cache_args(args=None):
    config_files = cfg.find_config_files(project='subject', prog='subject-cache')
    parse_args(args=args, default_config_files=config_files)

def parse_api_args(args=None):
    config_files = cfg.find_config_files(project='subject', prog='subject-api')
    parse_args(args=args, default_config_files=config_files)

def _get_deployment_flavor(flavor=None):
    """
    Retrieve the paste_deploy.flavor config item, formatted appropriately
    for appending to the application name.

    :param flavor: if specified, use this setting rather than the
                   paste_deploy.flavor configuration setting
    """
    if not flavor:
        flavor = CONF.paste_deploy.flavor
    return '' if not flavor else ('-' + flavor)


def _get_paste_config_path():
    paste_suffix = '-paste.ini'
    conf_suffix = '.conf'
    if CONF.config_file:
        # Assume paste config is in a paste.ini file corresponding
        # to the last config file
        path = CONF.config_file[-1].replace(conf_suffix, paste_suffix)
    else:
        path = CONF.prog + paste_suffix
    return CONF.find_file(os.path.basename(path))


def _get_deployment_config_file():
    """
    Retrieve the deployment_config_file config item, formatted as an
    absolute pathname.
    """
    path = CONF.paste_deploy.config_file
    if not path:
        path = _get_paste_config_path()
    if not path:
        msg = _("Unable to locate paste config file for %s.") % CONF.prog
        raise RuntimeError(msg)
    return os.path.abspath(path)


def load_paste_app(app_name, flavor=None, conf_file=None):
    """
    Builds and returns a WSGI app from a paste config file.

    We assume the last config file specified in the supplied ConfigOpts
    object is the paste config file, if conf_file is None.

    :param app_name: name of the application to load
    :param flavor: name of the variant of the application to load
    :param conf_file: path to the paste config file

    :raises: RuntimeError when config file cannot be located or application
            cannot be loaded from config file
    """
    # append the deployment flavor to the application name,
    # in order to identify the appropriate paste pipeline
    app_name += _get_deployment_flavor(flavor)

    if not conf_file:
        conf_file = _get_deployment_config_file()

    try:
        logger = logging.getLogger(__name__)
        logger.debug("Loading %(app_name)s from %(conf_file)s",
                     {'conf_file': conf_file, 'app_name': app_name})

        app = deploy.loadapp("config:%s" % conf_file, name=app_name)

        # Log the options used when starting if we're in debug mode...
        if CONF.debug:
            CONF.log_opt_values(logger, logging.DEBUG)

        return app
    except (LookupError, ImportError) as e:
        msg = (_("Unable to load %(app_name)s from "
                 "configuration file %(conf_file)s."
                 "\nGot: %(e)r") % {'app_name': app_name,
                                    'conf_file': conf_file,
                                    'e': e})
        logger.error(msg)
        raise RuntimeError(msg)


def set_config_defaults():
    """This method updates all configuration default values."""
    set_cors_middleware_defaults()


def set_cors_middleware_defaults():
    """Update default configuration options for oslo.middleware."""
    # CORS Defaults
    # TODO(krotscheck): Update with https://review.openstack.org/#/c/285368/
    cfg.set_defaults(cors.CORS_OPTS,
                     allow_headers=['Content-MD5',
                                    'X-Subject-Meta-Checksum',
                                    'X-Storage-Token',
                                    'Accept-Encoding',
                                    'X-Auth-Token',
                                    'X-Identity-Status',
                                    'X-Roles',
                                    'X-Service-Catalog',
                                    'X-User-Id',
                                    'X-Tenant-Id',
                                    'X-OpenStack-Request-ID'],
                     expose_headers=['X-Subject-Meta-Checksum',
                                     'X-Auth-Token',
                                     'X-Subject-Token',
                                     'X-Service-Token',
                                     'X-OpenStack-Request-ID'],
                     allow_methods=['GET',
                                    'PUT',
                                    'POST',
                                    'DELETE',
                                    'PATCH']
                     )
