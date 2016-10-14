..
      Copyright 2011 OpenStack Foundation
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Basic Configuration
===================

Glance has a number of options that you can use to configure the Glance API
server, the Glance Registry server, and the various storage backends that
Glance can use to store subjects.

Most configuration is done via configuration files, with the Glance API
server and Glance Registry server using separate configuration files.

When starting up a Glance server, you can specify the configuration file to
use (see :doc:`the documentation on controller Glance servers <controllingservers>`).
If you do **not** specify a configuration file, Glance will look in the following
directories for a configuration file, in order:

* ``~/.subject``
* ``~/``
* ``/etc/subject``
* ``/etc``

The Glance API server configuration file should be named ``subject-api.conf``.
Similarly, the Glance Registry server configuration file should be named
``subject-registry.conf``. There are many other configuration files also
since Glance maintains a configuration file for each of its services. If you
installed Glance via your operating system's package management system, it
is likely that you will have sample configuration files installed in
``/etc/subject``.

In addition, sample configuration files for each server application with
detailed comments are available in the :doc:`Glance Sample Configuration
<sample-configuration>` section.

The PasteDeploy configuration (controlling the deployment of the WSGI
application for each component) may be found by default in
<component>-paste.ini alongside the main configuration file, <component>.conf.
For example, ``subject-api-paste.ini`` corresponds to ``subject-api.conf``.
This pathname for the paste config is configurable, as follows::

  [paste_deploy]
  config_file = /path/to/paste/config


Common Configuration Options in Glance
--------------------------------------

Glance has a few command-line options that are common to all Glance programs:

* ``--verbose``

Optional. Default: ``False``

Can be specified on the command line and in configuration files.

Turns on the INFO level in logging and prints more verbose command-line
interface printouts.

* ``--debug``

Optional. Default: ``False``

Can be specified on the command line and in configuration files.

Turns on the DEBUG level in logging.

* ``--config-file=PATH``

Optional. Default: See below for default search order.

Specified on the command line only.

Takes a path to a configuration file to use when running the program. If this
CLI option is not specified, then we check to see if the first argument is a
file. If it is, then we try to use that as the configuration file. If there is
no file or there were no arguments, we search for a configuration file in the
following order:

* ``~/.subject``
* ``~/``
* ``/etc/subject``
* ``/etc``

The filename that is searched for depends on the server application name. So,
if you are starting up the API server, ``subject-api.conf`` is searched for,
otherwise ``subject-registry.conf``.

* ``--config-dir=DIR``

Optional. Default: ``None``

Specified on the command line only.

Takes a path to a configuration directory from which all \*.conf fragments
are loaded. This provides an alternative to multiple --config-file options
when it is inconvenient to explicitly enumerate all the configuration files,
for example when an unknown number of config fragments are being generated
by a deployment framework.

If --config-dir is set, then --config-file is ignored.

An example usage would be:

  $ subject-api --config-dir=/etc/subject/subject-api.d

  $ ls /etc/subject/subject-api.d
   00-core.conf
   01-swift.conf
   02-ssl.conf
   ... etc.

The numeric prefixes in the example above are only necessary if a specific
parse ordering is required (i.e. if an individual config option set in an
earlier fragment is overridden in a later fragment).

Note that ``subject-manage`` currently loads configuration from three files:

* ``subject-registry.conf``
* ``subject-api.conf``
* ``subject-manage.conf``

By default ``subject-manage.conf`` only specifies a custom logging file but
other configuration options for ``subject-manage`` should be migrated in there.
**Warning**: Options set in ``subject-manage.conf`` will override options of
the same section and name set in the other two. Similarly, options in
``subject-api.conf`` will override options set in ``subject-registry.conf``.
This tool is planning to stop loading ``subject-registry.conf`` and
``subject-api.conf`` in a future cycle.

Configuring Server Startup Options
----------------------------------

You can put the following options in the ``subject-api.conf`` and
``subject-registry.conf`` files, under the ``[DEFAULT]`` section. They enable
startup and binding behaviour for the API and registry servers, respectively.

* ``bind_host=ADDRESS``

The address of the host to bind to.

Optional. Default: ``0.0.0.0``

* ``bind_port=PORT``

The port the server should bind to.

Optional. Default: ``9191`` for the registry server, ``9292`` for the API server

* ``backlog=REQUESTS``

Number of backlog requests to configure the socket with.

Optional. Default: ``4096``

* ``tcp_keepidle=SECONDS``

Sets the value of TCP_KEEPIDLE in seconds for each server socket.
Not supported on OS X.

Optional. Default: ``600``

* ``client_socket_timeout=SECONDS``

Timeout for client connections' socket operations.  If an incoming
connection is idle for this period it will be closed.  A value of `0`
means wait forever.

Optional. Default: ``900``


* ``workers=PROCESSES``

Number of Glance API or Registry worker processes to start. Each worker
process will listen on the same port. Increasing this value may increase
performance (especially if using SSL with compression enabled). Typically
it is recommended to have one worker process per CPU. The value `0`
will prevent any new processes from being created.

Optional. Default: The number of CPUs available will be used by default.

* ``max_request_id_length=LENGTH``

Limits the maximum size of the x-openstack-request-id header which is
logged. Affects only if context middleware is configured in pipeline.

Optional. Default: ``64`` (Limited by max_header_line default: 16384)

Configuring SSL Support
~~~~~~~~~~~~~~~~~~~~~~~

* ``cert_file=PATH``

Path to the certificate file the server should use when binding to an
SSL-wrapped socket.

Optional. Default: not enabled.

* ``key_file=PATH``

Path to the private key file the server should use when binding to an
SSL-wrapped socket.

Optional. Default: not enabled.

* ``ca_file=PATH``

Path to the CA certificate file the server should use to validate client
certificates provided during an SSL handshake. This is ignored if
``cert_file`` and ''key_file`` are not set.

Optional. Default: not enabled.

Configuring Registry Access
~~~~~~~~~~~~~~~~~~~~~~~~~~~

There are a number of configuration options in Glance that control how
the API server accesses the registry server.

* ``registry_client_protocol=PROTOCOL``

If you run a secure Registry server, you need to set this value to ``https``
and also set ``registry_client_key_file`` and optionally
``registry_client_cert_file``.

Optional. Default: http

* ``registry_client_key_file=PATH``

The path to the key file to use in SSL connections to the
registry server, if any. Alternately, you may set the
``GLANCE_CLIENT_KEY_FILE`` environ variable to a filepath of the key file

Optional. Default: Not set.

* ``registry_client_cert_file=PATH``

Optional. Default: Not set.

The path to the cert file to use in SSL connections to the
registry server, if any. Alternately, you may set the
``GLANCE_CLIENT_CERT_FILE`` environ variable to a filepath of the cert file

* ``registry_client_ca_file=PATH``

Optional. Default: Not set.

The path to a Certifying Authority's cert file to use in SSL connections to the
registry server, if any. Alternately, you may set the
``GLANCE_CLIENT_CA_FILE`` environ variable to a filepath of the CA cert file

* ``registry_client_insecure=False``

Optional. Default: False.

When using SSL in connections to the registry server, do not require
validation via a certifying authority. This is the registry's equivalent of
specifying --insecure on the command line using subjectclient for the API

* ``registry_client_timeout=SECONDS``

Optional. Default: ``600``.

The period of time, in seconds, that the API server will wait for a registry
request to complete. A value of '0' implies no timeout.

.. note::
   ``use_user_token``, ``admin_user``, ``admin_password``,
   ``admin_tenant_name``, ``auth_url``, ``auth_strategy`` and ``auth_region``
   options were considered harmful and have been deprecated in M release.
   They will be removed in O release. For more information read
   `OSSN-0060 <https://wiki.openstack.org/wiki/OSSN/OSSN-0060>`_.
   Related functionality with uploading big subjects has been implemented with
   Keystone trusts support.

* ``use_user_token=True``

Optional. Default: True

DEPRECATED. This option will be removed in O release.

Pass the user token through for API requests to the registry.

If 'use_user_token' is not in effect then admin credentials can be
specified (see below). If admin credentials are specified then they are
used to generate a token; this token rather than the original user's
token is used for requests to the registry.

* ``admin_user=USER``

DEPRECATED. This option will be removed in O release.

If 'use_user_token' is not in effect then admin credentials can be
specified. Use this parameter to specify the username.

Optional. Default: None

* ``admin_password=PASSWORD``

DEPRECATED. This option will be removed in O release.

If 'use_user_token' is not in effect then admin credentials can be
specified. Use this parameter to specify the password.

Optional. Default: None

* ``admin_tenant_name=TENANTNAME``

DEPRECATED. This option will be removed in O release.

If 'use_user_token' is not in effect then admin credentials can be
specified. Use this parameter to specify the tenant name.

Optional. Default: None

* ``auth_url=URL``

DEPRECATED. This option will be removed in O release.

If 'use_user_token' is not in effect then admin credentials can be
specified. Use this parameter to specify the Keystone endpoint.

Optional. Default: None

* ``auth_strategy=STRATEGY``

DEPRECATED. This option will be removed in O release.

If 'use_user_token' is not in effect then admin credentials can be
specified. Use this parameter to specify the auth strategy.

Optional. Default: noauth

* ``auth_region=REGION``

DEPRECATED. This option will be removed in O release.

If 'use_user_token' is not in effect then admin credentials can be
specified. Use this parameter to specify the region.

Optional. Default: None


Configuring Logging in Glance
-----------------------------

There are a number of configuration options in Glance that control how Glance
servers log messages.

* ``--log-config=PATH``

Optional. Default: ``None``

Specified on the command line only.

Takes a path to a configuration file to use for configuring logging.

Logging Options Available Only in Configuration Files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You will want to place the different logging options in the **[DEFAULT]** section
in your application configuration file. As an example, you might do the following
for the API server, in a configuration file called ``etc/subject-api.conf``::

  [DEFAULT]
  log_file = /var/log/subject/api.log

* ``log_file``

The filepath of the file to use for logging messages from Glance's servers. If
missing, the default is to output messages to ``stdout``, so if you are running
Glance servers in a daemon mode (using ``subject-control``) you should make
sure that the ``log_file`` option is set appropriately.

* ``log_dir``

The filepath of the directory to use for log files. If not specified (the default)
the ``log_file`` is used as an absolute filepath.

* ``log_date_format``

The format string for timestamps in the log output.

Defaults to ``%Y-%m-%d %H:%M:%S``. See the
`logging module <http://docs.python.org/library/logging.html>`_ documentation for
more information on setting this format string.

* ``log_use_syslog``

Use syslog logging functionality.

Defaults to False.

Configuring Glance Storage Backends
-----------------------------------

There are a number of configuration options in Glance that control how Glance
stores disk subjects. These configuration options are specified in the
``subject-api.conf`` configuration file in the section ``[subject_store]``.

* ``default_store=STORE``

Optional. Default: ``file``

Can only be specified in configuration files.

Sets the storage backend to use by default when storing subjects in Glance.
Available options for this option are (``file``, ``swift``, ``rbd``,
``sheepdog``, ``cinder`` or ``vsphere``). In order to select a default store
it must also be listed in the ``stores`` list described below.

* ``stores=STORES``

Optional. Default: ``file, http``

A comma separated list of enabled subject stores. Some available options for
this option are (``filesystem``, ``http``, ``rbd``, ``swift``,
``sheepdog``, ``cinder``, ``vmware_datastore``)

Configuring the Filesystem Storage Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``filesystem_store_datadir=PATH``

Optional. Default: ``/var/lib/subject/subjects/``

Can only be specified in configuration files.

`This option is specific to the filesystem storage backend.`

Sets the path where the filesystem storage backend write disk subjects. Note that
the filesystem storage backend will attempt to create this directory if it does
not exist. Ensure that the user that ``subject-api`` runs under has write
permissions to this directory.

* ``filesystem_store_file_perm=PERM_MODE``

Optional. Default: ``0``

Can only be specified in configuration files.

`This option is specific to the filesystem storage backend.`

The required permission value, in octal representation, for the created subject file.
You can use this value to specify the user of the consuming service (such as Nova) as
the only member of the group that owns the created files. To keep the default value,
assign a permission value that is less than or equal to 0.  Note that the file owner
must maintain read permission; if this value removes that permission an error message
will be logged and the BadStoreConfiguration exception will be raised.  If the Glance
service has insufficient privileges to change file access permissions, a file will still
be saved, but a warning message will appear in the Glance log.

Configuring the Filesystem Storage Backend with multiple stores
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``filesystem_store_datadirs=PATH:PRIORITY``

Optional. Default: ``/var/lib/subject/subjects/:1``

Example::

  filesystem_store_datadirs = /var/subject/store
  filesystem_store_datadirs = /var/subject/store1:100
  filesystem_store_datadirs = /var/subject/store2:200

This option can only be specified in configuration file and is specific
to the filesystem storage backend only.

filesystem_store_datadirs option allows administrators to configure
multiple store directories to save subject subject in filesystem storage backend.
Each directory can be coupled with its priority.

**NOTE**:

* This option can be specified multiple times to specify multiple stores.
* Either filesystem_store_datadir or filesystem_store_datadirs option must be
  specified in subject-api.conf
* Store with priority 200 has precedence over store with priority 100.
* If no priority is specified, default priority '0' is associated with it.
* If two filesystem stores have same priority store with maximum free space
  will be chosen to store the subject.
* If same store is specified multiple times then BadStoreConfiguration
  exception will be raised.

Configuring the Swift Storage Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``swift_store_auth_address=URL``

Required when using the Swift storage backend.

Can only be specified in configuration files.

Deprecated. Use ``auth_address`` in the Swift back-end configuration file instead.

`This option is specific to the Swift storage backend.`

Sets the authentication URL supplied to Swift when making calls to its storage
system. For more information about the Swift authentication system, please
see the `Swift auth <http://swift.openstack.org/overview_auth.html>`_
documentation and the
`overview of Swift authentication <http://docs.openstack.org/openstack-object-storage/admin/content/ch02s02.html>`_.

**IMPORTANT NOTE**: Swift authentication addresses use HTTPS by default. This
means that if you are running Swift with authentication over HTTP, you need
to set your ``swift_store_auth_address`` to the full URL, including the ``http://``.

* ``swift_store_user=USER``

Required when using the Swift storage backend.

Can only be specified in configuration files.

Deprecated. Use ``user`` in the Swift back-end configuration file instead.

`This option is specific to the Swift storage backend.`

Sets the user to authenticate against the ``swift_store_auth_address`` with.

* ``swift_store_key=KEY``

Required when using the Swift storage backend.

Can only be specified in configuration files.

Deprecated. Use ``key`` in the Swift back-end configuration file instead.

`This option is specific to the Swift storage backend.`

Sets the authentication key to authenticate against the
``swift_store_auth_address`` with for the user ``swift_store_user``.

* ``swift_store_container=CONTAINER``

Optional. Default: ``subject``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

Sets the name of the container to use for Glance subjects in Swift.

* ``swift_store_create_container_on_put``

Optional. Default: ``False``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

If true, Glance will attempt to create the container ``swift_store_container``
if it does not exist.

* ``swift_store_large_object_size=SIZE_IN_MB``

Optional. Default: ``5120``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

What size, in MB, should Glance start chunking subject files
and do a large object manifest in Swift? By default, this is
the maximum object size in Swift, which is 5GB

* ``swift_store_large_object_chunk_size=SIZE_IN_MB``

Optional. Default: ``200``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

When doing a large object manifest, what size, in MB, should
Glance write chunks to Swift?  The default is 200MB.

* ``swift_store_multi_tenant=False``

Optional. Default: ``False``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

If set to True enables multi-tenant storage mode which causes Glance subjects
to be stored in tenant specific Swift accounts. When set to False Glance
stores all subjects in a single Swift account.

* ``swift_store_multiple_containers_seed``

Optional. Default: ``0``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

When set to 0, a single-tenant store will only use one container to store all
subjects. When set to an integer value between 1 and 32, a single-tenant store
will use multiple containers to store subjects, and this value will determine
how many characters from an subject UUID are checked when determining what
container to place the subject in. The maximum number of containers that will be
created is approximately equal to 16^N. This setting is used only when
swift_store_multi_tenant is disabled.

Example: if this config option is set to 3 and
swift_store_container = 'subject', then an subject with UUID
'fdae39a1-bac5-4238-aba4-69bcc726e848' would be placed in the container
'subject_fda'. All dashes in the UUID are included when creating the container
name but do not count toward the character limit, so in this example with N=10
the container name would be 'subject_fdae39a1-ba'.

When choosing the value for swift_store_multiple_containers_seed, deployers
should discuss a suitable value with their swift operations team. The authors
of this option recommend that large scale deployments use a value of '2',
which will create a maximum of ~256 containers. Choosing a higher number than
this, even in extremely large scale deployments, may not have any positive
impact on performance and could lead to a large number of empty, unused
containers. The largest of deployments could notice an increase in performance
if swift rate limits are throttling on single container. Note: If dynamic
container creation is turned off, any value for this configuration option
higher than '1' may be unreasonable as the deployer would have to manually
create each container.

* ``swift_store_admin_tenants``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

Optional. Default: Not set.

A list of swift ACL strings that will be applied as both read and
write ACLs to the containers created by Glance in multi-tenant
mode. This grants the specified tenants/users read and write access
to all newly created subject objects. The standard swift ACL string
formats are allowed, including:

<tenant_id>:<username>
<tenant_name>:<username>
\*:<username>

Multiple ACLs can be combined using a comma separated list, for
example: swift_store_admin_tenants = service:subject,*:admin

* ``swift_store_auth_version``

Can only be specified in configuration files.

Deprecated. Use ``auth_version`` in the Swift back-end configuration
file instead.

`This option is specific to the Swift storage backend.`

Optional. Default: ``2``

A string indicating which version of Swift OpenStack authentication
to use. See the project
`python-swiftclient <http://docs.openstack.org/developer/python-swiftclient/>`_
for more details.

* ``swift_store_service_type``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

Optional. Default: ``object-store``

A string giving the service type of the swift service to use. This
setting is only used if swift_store_auth_version is ``2``.

* ``swift_store_region``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

Optional. Default: Not set.

A string giving the region of the swift service endpoint to use. This
setting is only used if swift_store_auth_version is ``2``. This
setting is especially useful for disambiguation if multiple swift
services might appear in a service catalog during authentication.

* ``swift_store_endpoint_type``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

Optional. Default: ``publicURL``

A string giving the endpoint type of the swift service endpoint to
use. This setting is only used if swift_store_auth_version is ``2``.

* ``swift_store_ssl_compression``

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

Optional. Default: True.

If set to False, disables SSL layer compression of https swift
requests. Setting to 'False' may improve performance for subjects which
are already in a compressed format, e.g. qcow2. If set to True then
compression will be enabled (provided it is supported by the swift
proxy).

* ``swift_store_cacert``

Can only be specified in configuration files.

Optional. Default: ``None``

A string giving the path to a CA certificate bundle that will allow Glance's
services to perform SSL verification when communicating with Swift.

* ``swift_store_retry_get_count``

The number of times a Swift download will be retried before the request
fails.
Optional. Default: ``0``

Configuring Multiple Swift Accounts/Stores
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In order to not store Swift account credentials in the database, and to
have support for multiple accounts (or multiple Swift backing stores), a
reference is stored in the database and the corresponding configuration
(credentials/ parameters) details are stored in the configuration file.
Optional.  Default: not enabled.

The location for this file is specified using the ``swift_store_config_file``
configuration file in the section ``[DEFAULT]``. **If an incorrect value is
specified, Glance API Swift store service will not be configured.**
* ``swift_store_config_file=PATH``

`This option is specific to the Swift storage backend.`

* ``default_swift_reference=DEFAULT_REFERENCE``

Required when multiple Swift accounts/backing stores are configured.

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

It is the default swift reference that is used to add any new subjects.
* ``swift_store_auth_insecure``

If True, bypass SSL certificate verification for Swift.

Can only be specified in configuration files.

`This option is specific to the Swift storage backend.`

Optional. Default: ``False``

Configuring Swift configuration file
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If ``swift_store_config_file`` is set, Glance will use information
from the file specified under this parameter.

.. note::
   The ``swift_store_config_file`` is currently used only for single-tenant
   Swift store configurations. If you configure a multi-tenant Swift store
   back end (``swift_store_multi_tenant=True``), ensure that both
   ``swift_store_config_file`` and ``default_swift_reference`` are *not* set.

The file contains a set of references like:

.. code-block:: ini

    [ref1]
    user = tenant:user1
    key = key1
    auth_version = 2
    auth_address = http://localhost:5000/v2.0

    [ref2]
    user = project_name:user_name2
    key = key2
    user_domain_id = default
    project_domain_id = default
    auth_version = 3
    auth_address = http://localhost:5000/v3

A default reference must be configured. Its parameters will be used when
creating new subjects. For example, to specify ``ref2`` as the default
reference, add the following value to the [subject_store] section of
:file:`subject-api.conf` file:

.. code-block:: ini

    default_swift_reference = ref2

In the reference, a user can specify the following parameters:

* ``user``

  A *project_name user_name* pair in the ``project_name:user_name`` format
  to authenticate against the Swift authentication service.

* ``key``

  An authentication key for a user authenticating against the Swift
  authentication service.

* ``auth_address``

  An address where the Swift authentication service is located.

* ``auth_version``

  A version of the authentication service to use.
  Valid versions are ``2`` and ``3`` for Keystone and ``1``
  (deprecated) for Swauth and Rackspace.

  Optional. Default: ``2``

* ``project_domain_id``

  A domain ID of the project which is the requested project-level
  authorization scope.

  Optional. Default: ``None``

  `This option can be specified if ``auth_version`` is ``3`` .`

* ``project_domain_name``

  A domain name of the project which is the requested project-level
  authorization scope.

  Optional. Default: ``None``

  `This option can be specified if ``auth_version`` is ``3`` .`

* ``user_domain_id``

  A domain ID of the user which is the requested domain-level
  authorization scope.

  Optional. Default: ``None``

  `This option can be specified if ``auth_version`` is ``3`` .`

* ``user_domain_name``

  A domain name of the user which is the requested domain-level
  authorization scope.

  Optional. Default: ``None``

  `This option can be specified if ``auth_version`` is ``3``. `

Configuring the RBD Storage Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Note**: the RBD storage backend requires the python bindings for
librados and librbd. These are in the python-ceph package on
Debian-based distributions.

* ``rbd_store_pool=POOL``

Optional. Default: ``rbd``

Can only be specified in configuration files.

`This option is specific to the RBD storage backend.`

Sets the RADOS pool in which subjects are stored.

* ``rbd_store_chunk_size=CHUNK_SIZE_MB``

Optional. Default: ``4``

Can only be specified in configuration files.

`This option is specific to the RBD storage backend.`

Subjects will be chunked into objects of this size (in megabytes).
For best performance, this should be a power of two.

* ``rados_connect_timeout``

Optional. Default: ``0``

Can only be specified in configuration files.

`This option is specific to the RBD storage backend.`

Prevents subject-api hangups during the connection to RBD. Sets the time
to wait (in seconds) for subject-api before closing the connection.
Setting ``rados_connect_timeout<=0`` means no timeout.

* ``rbd_store_ceph_conf=PATH``

Optional. Default: ``/etc/ceph/ceph.conf``, ``~/.ceph/config``, and
``./ceph.conf``

Can only be specified in configuration files.

`This option is specific to the RBD storage backend.`

Sets the Ceph configuration file to use.

* ``rbd_store_user=NAME``

Optional. Default: ``admin``

Can only be specified in configuration files.

`This option is specific to the RBD storage backend.`

Sets the RADOS user to authenticate as. This is only needed
when `RADOS authentication <http://ceph.newdream.net/wiki/Cephx>`_
is `enabled. <http://ceph.newdream.net/wiki/Cluster_configuration#Cephx_auth>`_

A keyring must be set for this user in the Ceph
configuration file, e.g. with a user ``subject``::

  [client.subject]
  keyring=/etc/subject/rbd.keyring

To set up a user named ``subject`` with minimal permissions, using a pool called
``subjects``, run::

  rados mkpool subjects
  ceph-authtool --create-keyring /etc/subject/rbd.keyring
  ceph-authtool --gen-key --name client.subject --cap mon 'allow r' --cap osd 'allow rwx pool=subjects' /etc/subject/rbd.keyring
  ceph auth add client.subject -i /etc/subject/rbd.keyring

Configuring the Sheepdog Storage Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``sheepdog_store_address=ADDR``

Optional. Default: ``localhost``

Can only be specified in configuration files.

`This option is specific to the Sheepdog storage backend.`

Sets the IP address of the sheep daemon

* ``sheepdog_store_port=PORT``

Optional. Default: ``7000``

Can only be specified in configuration files.

`This option is specific to the Sheepdog storage backend.`

Sets the IP port of the sheep daemon

* ``sheepdog_store_chunk_size=SIZE_IN_MB``

Optional. Default: ``64``

Can only be specified in configuration files.

`This option is specific to the Sheepdog storage backend.`

Subjects will be chunked into objects of this size (in megabytes).
For best performance, this should be a power of two.

Configuring the Cinder Storage Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Note**: Currently Cinder store is experimental. Current deployers should be
aware that the use of it in production right now may be risky. It is expected
to work well with most iSCSI Cinder backends such as LVM iSCSI, but will not
work with some backends especially if they don't support host-attach.

**Note**: To create a Cinder volume from an subject in this store quickly, additional
settings are required. Please see the
`Volume-backed subject <http://docs.openstack.org/admin-guide/blockstorage_volume_backed_subject.html>`_
documentation for more information.

* ``cinder_catalog_info=<service_type>:<service_name>:<endpoint_type>``

Optional. Default: ``volumev2::publicURL``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

Sets the info to match when looking for cinder in the service catalog.
Format is : separated values of the form: <service_type>:<service_name>:<endpoint_type>

* ``cinder_endpoint_template=http://ADDR:PORT/VERSION/%(tenant)s``

Optional. Default: ``None``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

Override service catalog lookup with template for cinder endpoint.
``%(...)s`` parts are replaced by the value in the request context.
e.g. http://localhost:8776/v2/%(tenant)s

* ``os_region_name=REGION_NAME``

Optional. Default: ``None``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

Region name of this node.

Deprecated. Use ``cinder_os_region_name`` instead.

* ``cinder_os_region_name=REGION_NAME``

Optional. Default: ``None``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

Region name of this node.  If specified, it is used to locate cinder from
the service catalog.

* ``cinder_ca_certificates_file=CA_FILE_PATH``

Optional. Default: ``None``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

Location of ca certificates file to use for cinder client requests.

* ``cinder_http_retries=TIMES``

Optional. Default: ``3``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

Number of cinderclient retries on failed http calls.

* ``cinder_state_transition_timeout``

Optional. Default: ``300``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

Time period, in seconds, to wait for a cinder volume transition to complete.

* ``cinder_api_insecure=ON_OFF``

Optional. Default: ``False``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

Allow to perform insecure SSL requests to cinder.

* ``cinder_store_user_name=NAME``

Optional. Default: ``None``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

User name to authenticate against Cinder. If <None>, the user of current
context is used.

**NOTE**: This option is applied only if all of ``cinder_store_user_name``,
``cinder_store_password``, ``cinder_store_project_name`` and
``cinder_store_auth_address`` are set.
These options are useful to put subject volumes into the internal service
project in order to hide the volume from users, and to make the subject
sharable among projects.

* ``cinder_store_password=PASSWORD``

Optional. Default: ``None``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

Password for the user authenticating against Cinder. If <None>, the current
context auth token is used.

* ``cinder_store_project_name=NAME``

Optional. Default: ``None``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

Project name where the subject is stored in Cinder. If <None>, the project
in current context is used.

* ``cinder_store_auth_address=URL``

Optional. Default: ``None``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

The address where the Cinder authentication service is listening. If <None>,
the cinder endpoint in the service catalog is used.

* ``rootwrap_config=NAME``

Optional. Default: ``/etc/subject/rootwrap.conf``

Can only be specified in configuration files.

`This option is specific to the Cinder storage backend.`

Path to the rootwrap configuration file to use for running commands as root.

Configuring the VMware Storage Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``vmware_server_host=ADDRESS``

Required when using the VMware storage backend.

Can only be specified in configuration files.

Sets the address of the ESX/ESXi or vCenter Server target system.
The address can contain an IP (``127.0.0.1``), an IP and port
(``127.0.0.1:443``), a DNS name (``www.my-domain.com``) or DNS and port.

`This option is specific to the VMware storage backend.`

* ``vmware_server_username=USERNAME``

Required when using the VMware storage backend.

Can only be specified in configuration files.

Username for authenticating with VMware ESX/ESXi or vCenter Server.

* ``vmware_server_password=PASSWORD``

Required when using the VMware storage backend.

Can only be specified in configuration files.

Password for authenticating with VMware ESX/ESXi or vCenter Server.

* ``vmware_datacenter_path=DC_PATH``

Optional. Default: ``ha-datacenter``

Can only be specified in configuration files.

Inventory path to a datacenter. If the ``vmware_server_host`` specified
is an ESX/ESXi, the ``vmware_datacenter_path`` is optional. If specified,
it should be ``ha-datacenter``.

* ``vmware_datastore_name=DS_NAME``

Required when using the VMware storage backend.

Can only be specified in configuration files.

Datastore name associated with the ``vmware_datacenter_path``

* ``vmware_datastores``

Optional. Default: Not set.

This option can only be specified in configuration file and is specific
to the VMware storage backend.

vmware_datastores allows administrators to configure multiple datastores to
save subject subject in the VMware store backend. The required format for the
option is: <datacenter_path>:<datastore_name>:<optional_weight>.

where datacenter_path is the inventory path to the datacenter where the
datastore is located. An optional weight can be given to specify the priority.

Example::

  vmware_datastores = datacenter1:datastore1
  vmware_datastores = dc_folder/datacenter2:datastore2:100
  vmware_datastores = datacenter1:datastore3:200

**NOTE**:

  - This option can be specified multiple times to specify multiple datastores.
  - Either vmware_datastore_name or vmware_datastores option must be specified
    in subject-api.conf
  - Datastore with weight 200 has precedence over datastore with weight 100.
  - If no weight is specified, default weight '0' is associated with it.
  - If two datastores have same weight, the datastore with maximum free space
    will be chosen to store the subject.
  - If the datacenter path or datastore name contains a colon (:) symbol, it
    must be escaped with a backslash.

* ``vmware_api_retry_count=TIMES``

Optional. Default: ``10``

Can only be specified in configuration files.

The number of times VMware ESX/VC server API must be
retried upon connection related issues.

* ``vmware_task_poll_interval=SECONDS``

Optional. Default: ``5``

Can only be specified in configuration files.

The interval used for polling remote tasks invoked on VMware ESX/VC server.

* ``vmware_store_subject_dir``

Optional. Default: ``/openstack_subject``

Can only be specified in configuration files.

The path to access the folder where the subjects will be stored in the datastore.

* ``vmware_api_insecure=ON_OFF``

Optional. Default: ``False``

Can only be specified in configuration files.

Allow to perform insecure SSL requests to ESX/VC server.

Configuring the Storage Endpoint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``swift_store_endpoint=URL``

Optional. Default: ``None``

Can only be specified in configuration files.

Overrides the storage URL returned by auth. The URL should include the
path up to and excluding the container. The location of an object is
obtained by appending the container and object to the configured URL.
e.g. ``https://www.my-domain.com/v1/path_up_to_container``

Configuring Glance Subject Size Limit
-----------------------------------

The following configuration option is specified in the
``subject-api.conf`` configuration file in the section ``[DEFAULT]``.

* ``subject_size_cap=SIZE``

Optional. Default: ``1099511627776`` (1 TB)

Maximum subject size, in bytes, which can be uploaded through the Glance API server.

**IMPORTANT NOTE**: this value should only be increased after careful consideration
and must be set to a value under 8 EB (9223372036854775808).

Configuring Glance User Storage Quota
-------------------------------------

The following configuration option is specified in the
``subject-api.conf`` configuration file in the section ``[DEFAULT]``.

* ``user_storage_quota``

Optional. Default: 0 (Unlimited).

This value specifies the maximum amount of storage that each user can use
across all storage systems. Optionally unit can be specified for the value.
Values are accepted in B, KB, MB, GB or TB which are for Bytes, KiloBytes,
MegaBytes, GigaBytes and TeraBytes respectively. Default unit is Bytes.

Example values would be,
    user_storage_quota=20GB

Configuring the Subject Cache
---------------------------

Glance API servers can be configured to have a local subject cache. Caching of
subject files is transparent and happens using a piece of middleware that can
optionally be placed in the server application pipeline.

This pipeline is configured in the PasteDeploy configuration file,
<component>-paste.ini. You should not generally have to edit this file
directly, as it ships with ready-made pipelines for all common deployment
flavors.

Enabling the Subject Cache Middleware
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable the subject cache middleware, the cache middleware must occur in
the application pipeline **after** the appropriate context middleware.

The cache middleware should be in your ``subject-api-paste.ini`` in a section
titled ``[filter:cache]``. It should look like this::

  [filter:cache]
  paste.filter_factory = subject.api.middleware.cache:CacheFilter.factory

A ready-made application pipeline including this filter is defined in
the ``subject-api-paste.ini`` file, looking like so::

  [pipeline:subject-api-caching]
  pipeline = versionnegotiation context cache apiv1app

To enable the above application pipeline, in your main ``subject-api.conf``
configuration file, select the appropriate deployment flavor like so::

  [paste_deploy]
  flavor = caching

Enabling the Subject Cache Management Middleware
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There is an optional ``cachemanage`` middleware that allows you to
directly interact with cache subjects. Use this flavor in place of the
``cache`` flavor in your API configuration file. There are three types you
can chose: ``cachemanagement``, ``keystone+cachemanagement`` and
``trusted-auth+cachemanagement``.::

  [paste_deploy]
  flavor = keystone+cachemanagement

Configuration Options Affecting the Subject Cache
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. note::

  These configuration options must be set in both the subject-cache
  and subject-api configuration files.


One main configuration file option affects the subject cache.

 * ``subject_cache_dir=PATH``

Required when subject cache middleware is enabled.

Default: ``/var/lib/subject/subject-cache``

This is the base directory the subject cache can write files to.
Make sure the directory is writable by the user running the
``subject-api`` server

 * ``subject_cache_driver=DRIVER``

Optional. Choice of ``sqlite`` or ``xattr``

Default: ``sqlite``

The default ``sqlite`` cache driver has no special dependencies, other
than the ``python-sqlite3`` library, which is installed on virtually
all operating systems with modern versions of Python. It stores
information about the cached files in a SQLite database.

The ``xattr`` cache driver required the ``python-xattr>=0.6.0`` library
and requires that the filesystem containing ``subject_cache_dir`` have
access times tracked for all files (in other words, the noatime option
CANNOT be set for that filesystem). In addition, ``user_xattr`` must be
set on the filesystem's description line in fstab. Because of these
requirements, the ``xattr`` cache driver is not available on Windows.

 * ``subject_cache_sqlite_db=DB_FILE``

Optional.

Default: ``cache.db``

When using the ``sqlite`` cache driver, you can set the name of the database
that will be used to store the cached subjects information. The database
is always contained in the ``subject_cache_dir``.

 * ``subject_cache_max_size=SIZE``

Optional.

Default: ``10737418240`` (10 GB)

Size, in bytes, that the subject cache should be constrained to. Subjects files
are cached automatically in the local subject cache, even if the writing of that
subject file would put the total cache size over this size. The
``subject-cache-pruner`` executable is what prunes the subject cache to be equal
to or less than this value. The ``subject-cache-pruner`` executable is designed
to be run via cron on a regular basis. See more about this executable in
:doc:`Controlling the Growth of the Subject Cache <cache>`

.. _configuring-the-subject-registry:

Configuring the Glance Registry
-------------------------------

There are a number of configuration options in Glance that control how
this registry server operates. These configuration options are specified in the
``subject-registry.conf`` configuration file in the section ``[DEFAULT]``.

**IMPORTANT NOTE**: The subject-registry service is only used in conjunction
with the subject-api service when clients are using the v1 REST API. See
`Configuring Glance APIs`_ for more info.

* ``sql_connection=CONNECTION_STRING`` (``--sql-connection`` when specified
  on command line)

Optional. Default: ``None``

Can be specified in configuration files. Can also be specified on the
command-line for the ``subject-manage`` program.

Sets the SQLAlchemy connection string to use when connecting to the registry
database. Please see the documentation for
`SQLAlchemy connection strings <http://www.sqlalchemy.org/docs/05/reference/sqlalchemy/connections.html>`_
online. You must urlencode any special characters in CONNECTION_STRING.

* ``sql_timeout=SECONDS``
  on command line)

Optional. Default: ``3600``

Can only be specified in configuration files.

Sets the number of seconds after which SQLAlchemy should reconnect to the
datastore if no activity has been made on the connection.

* ``enable_v1_registry=<True|False>``

Optional. Default: ``True``

* ``enable_v2_registry=<True|False>``

Optional. Default: ``True``

Defines which version(s) of the Registry API will be enabled.
If the Glance API server parameter ``enable_v1_api`` has been set to ``True`` the
``enable_v1_registry`` has to be ``True`` as well.
If the Glance API server parameter ``enable_v2_api`` has been
set to ``True`` and the parameter ``data_api`` has been set to
``subject.db.registry.api`` the ``enable_v2_registry`` has to be set to ``True``


Configuring Notifications
-------------------------

Glance can optionally generate notifications to be logged or sent to a message
queue. The configuration options are specified in the ``subject-api.conf``
configuration file.

* ``[oslo_messaging_notifications]/driver``

Optional. Default: ``noop``

Sets the notification driver used by oslo.messaging. Options include
``messaging``, ``messagingv2``, ``log`` and ``routing``.

**NOTE**
In M release, the``[DEFAULT]/notification_driver`` option has been deprecated in favor
of ``[oslo_messaging_notifications]/driver``.

For more information see :doc:`Glance notifications <notifications>` and
`oslo.messaging <http://docs.openstack.org/developer/oslo.messaging/>`_.

* ``[DEFAULT]/disabled_notifications``

Optional. Default: ``[]``

List of disabled notifications. A notification can be given either as a
notification type to disable a single event, or as a notification group prefix
to disable all events within a group.

Example: if this config option is set to ["subject.create", "metadef_namespace"],
then "subject.create" notification will not be sent after subject is created and
none of the notifications for metadefinition namespaces will be sent.

Configuring Glance Property Protections
---------------------------------------

Access to subject meta properties may be configured using a
:doc:`Property Protections Configuration file <property-protections>`.  The
location for this file can be specified in the ``subject-api.conf``
configuration file in the section ``[DEFAULT]``. **If an incorrect value is
specified, subject API service will not start.**

* ``property_protection_file=PATH``

Optional. Default: not enabled.

If property_protection_file is set, the file may use either roles or policies
to specify property protections.

* ``property_protection_rule_format=<roles|policies>``

Optional. Default: ``roles``.

Configuring Glance APIs
-----------------------

The subject-api service implements versions 1 and 2 of
the OpenStack Subjects API. Disable any version of
the Subjects API using the following options:

* ``enable_v1_api=<True|False>``

Optional. Default: ``True``

* ``enable_v2_api=<True|False>``

Optional. Default: ``True``

**IMPORTANT NOTE**: To use v2 registry in v2 API, you must set
``data_api`` to subject.db.registry.api in subject-api.conf.

Configuring Glance Tasks
------------------------

Glance Tasks are implemented only for version 2 of the OpenStack Subjects API.

The config value ``task_time_to_live`` is used to determine how long a task
would be visible to the user after transitioning to either the ``success`` or
the ``failure`` state.

* ``task_time_to_live=<Time_in_hours>``

Optional. Default: ``48``

The config value ``task_executor`` is used to determine which executor
should be used by the Glance service to process the task. The currently
available implementation is: ``taskflow``.

* ``task_executor=<executor_type>``

Optional. Default: ``taskflow``

The ``taskflow`` engine has its own set of configuration options,
under the ``taskflow_executor`` section, that can be tuned to improve
the task execution process. Among the available options, you may find
``engine_mode`` and ``max_workers``. The former allows for selecting
an execution model and the available options are ``serial``,
``parallel`` and ``worker-based``. The ``max_workers`` option,
instead, allows for controlling the number of workers that will be
instantiated per executor instance.

The default value for the ``engine_mode`` is ``parallel``, whereas
the default number of ``max_workers`` is ``10``.

Configuring Glance performance profiling
----------------------------------------

Glance supports using osprofiler to trace the performance of each key internal
handling, including RESTful API calling, DB operation and etc.

``Please be aware that Glance performance profiling is currently a work in
progress feature.`` Although, some trace points is available, e.g. API
execution profiling at wsgi main entry and SQL execution profiling at DB
module, the more fine-grained trace point is being worked on.

The config value ``enabled`` is used to determine whether fully enable
profiling feature for subject-api and subject-registry service.

* ``enabled=<True|False>``

Optional. Default: ``False``

There is one more configuration option that needs to be defined to enable
Glance services profiling. The config value ``hmac_keys`` is used for
encrypting context data for performance profiling.

* ``hmac_keys=<secret_key_string>``

Optional. Default: ``SECRET_KEY``

**IMPORTANT NOTE**: in order to make profiling work as designed operator needs
to make those values of HMAC key be consistent for all services in their
deployment. Without HMAC key the profiling will not be triggered even profiling
feature is enabled.

**IMPORTANT NOTE**: previously HMAC keys (as well as enabled parameter) were
placed at `/etc/subject/api-paste.ini` and `/etc/subject/registry-paste.ini` files
for Glance API and Glance Registry services respectively. Starting with
osprofiler 0.3.1 release there is no need to set these arguments in the
`*-paste.ini` files. This functionality is still supported, although the
config values are having larger priority.

The config value ``trace_sqlalchemy`` is used to determine whether fully enable
sqlalchemy engine based SQL execution profiling feature for subject-api and
subject-registry services.

* ``trace_sqlalchemy=<True|False>``

Optional. Default: ``False``

Configuring Glance public endpoint
----------------------------------

This setting allows an operator to configure the endpoint URL that will
appear in the Glance "versions" response (that is, the response to
``GET /``\  ).  This can be necessary when the Glance API service is run
behind a proxy because the default endpoint displayed in the versions
response is that of the host actually running the API service.  If
Glance is being run behind a load balancer, for example, direct access
to individual hosts running the Glance API may not be allowed, hence the
load balancer URL would be used for this value.

* ``public_endpoint=<None|URL>``

Optional. Default: ``None``

Configuring Glance digest algorithm
-----------------------------------

Digest algorithm that will be used for digital signature. The default
is sha256. Use the command::

  openssl list-message-digest-algorithms

to get the available algorithms supported by the version of OpenSSL on the
platform. Examples are "sha1", "sha256", "sha512", etc. If an invalid
digest algorithm is configured, all digital signature operations will fail and
return a ValueError exception with "No such digest method" error.

* ``digest_algorithm=<algorithm>``

Optional. Default: ``sha256``

Configuring http_keepalive option
---------------------------------

* ``http_keepalive=<True|False>``

If False, server will return the header "Connection: close", If True, server
will return "Connection: Keep-Alive" in its responses. In order to close the
client socket connection explicitly after the response is sent and read
successfully by the client, you simply have to set this option to False when
you create a wsgi server.

Configuring the Health Check
----------------------------

This setting allows an operator to configure the endpoint URL that will
provide information to load balancer if given API endpoint at the node should
be available or not. Both Glance API and Glance Registry servers can be
configured to expose a health check URL.

To enable the health check middleware, it must occur in the beginning of the
application pipeline.

The health check middleware should be placed in your
``subject-api-paste.ini`` / ``subject-registry-paste.ini`` in a section
titled ``[filter:healthcheck]``. It should look like this::

  [filter:healthcheck]
  paste.filter_factory = oslo_middleware:Healthcheck.factory
  backends = disable_by_file
  disable_by_file_path = /etc/subject/healthcheck_disable

A ready-made application pipeline including this filter is defined e.g. in
the ``subject-api-paste.ini`` file, looking like so::

  [pipeline:subject-api]
  pipeline = healthcheck versionnegotiation osprofiler unauthenticated-context rootapp

For more information see
`oslo.middleware <http://docs.openstack.org/developer/oslo.middleware/api.html#oslo_middleware.Healthcheck>`_.

Configuring supported disk formats
----------------------------------

Each subject in Glance has an associated disk format property.
When creating an subject the user specifies a disk format. They must
select a format from the set that the Glance service supports. This
supported set can be seen by querying the ``/v2/schemas/subjects`` resource.
An operator can add or remove disk formats to the supported set.  This is
done by setting the ``disk_formats`` parameter which is found in the
``[subject_formats]`` section of ``subject-api.conf``.

* ``disk_formats=<Comma separated list of disk formats>``

Optional. Default: ``ami,ari,aki,vhd,vmdk,raw,qcow2,vdi,iso``
