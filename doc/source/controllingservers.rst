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

Controlling Glance Servers
==========================

This section describes the ways to start, stop, and reload Glance's server
programs.

Starting a server
-----------------

There are two ways to start a Glance server (either the API server or the
registry server):

* Manually calling the server program

* Using the ``subject-control`` server daemon wrapper program

We recommend using the second method.

Manually starting the server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The first is by directly calling the server program, passing in command-line
options and a single argument for a ``paste.deploy`` configuration file to
use when configuring the server application.

.. note::

  Glance ships with an ``etc/`` directory that contains sample ``paste.deploy``
  configuration files that you can copy to a standard configuration directory and
  adapt for your own uses. Specifically, bind_host must be set properly.

If you do `not` specify a configuration file on the command line, Glance will
do its best to locate a configuration file in one of the
following directories, stopping at the first config file it finds:

* ``$CWD``
* ``~/.subject``
* ``~/``
* ``/etc/subject``
* ``/etc``

The filename that is searched for depends on the server application name. So,
if you are starting up the API server, ``subject-api.conf`` is searched for,
otherwise ``subject-registry.conf``.

If no configuration file is found, you will see an error, like::

  $> subject-api
  ERROR: Unable to locate any configuration file. Cannot load application subject-api

Here is an example showing how you can manually start the ``subject-api`` server and ``subject-registry`` in a shell.::

  $ sudo subject-api --config-file subject-api.conf --debug &
  jsuh@mc-ats1:~$ 2011-04-13 14:50:12    DEBUG [subject-api] ********************************************************************************
  2011-04-13 14:50:12    DEBUG [subject-api] Configuration options gathered from config file:
  2011-04-13 14:50:12    DEBUG [subject-api] /home/jsuh/subject-api.conf
  2011-04-13 14:50:12    DEBUG [subject-api] ================================================
  2011-04-13 14:50:12    DEBUG [subject-api] bind_host                      65.114.169.29
  2011-04-13 14:50:12    DEBUG [subject-api] bind_port                      9292
  2011-04-13 14:50:12    DEBUG [subject-api] debug                          True
  2011-04-13 14:50:12    DEBUG [subject-api] default_store                  file
  2011-04-13 14:50:12    DEBUG [subject-api] filesystem_store_datadir       /home/jsuh/subjects/
  2011-04-13 14:50:12    DEBUG [subject-api] registry_host                  65.114.169.29
  2011-04-13 14:50:12    DEBUG [subject-api] registry_port                  9191
  2011-04-13 14:50:12    DEBUG [subject-api] ********************************************************************************
  2011-04-13 14:50:12    DEBUG [routes.middleware] Initialized with method overriding = True, and path info altering = True
  2011-04-13 14:50:12    DEBUG [eventlet.wsgi.server] (21354) wsgi starting up on http://65.114.169.29:9292/

  $ sudo subject-registry --config-file subject-registry.conf &
  jsuh@mc-ats1:~$ 2011-04-13 14:51:16     INFO [sqlalchemy.engine.base.Engine.0x...feac] PRAGMA table_info("subjects")
  2011-04-13 14:51:16     INFO [sqlalchemy.engine.base.Engine.0x...feac] ()
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Col ('cid', 'name', 'type', 'notnull', 'dflt_value', 'pk')
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (0, u'created_at', u'DATETIME', 1, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (1, u'updated_at', u'DATETIME', 0, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (2, u'deleted_at', u'DATETIME', 0, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (3, u'deleted', u'BOOLEAN', 1, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (4, u'id', u'INTEGER', 1, None, 1)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (5, u'name', u'VARCHAR(255)', 0, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (6, u'disk_format', u'VARCHAR(20)', 0, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (7, u'container_format', u'VARCHAR(20)', 0, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (8, u'size', u'INTEGER', 0, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (9, u'status', u'VARCHAR(30)', 1, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (10, u'is_public', u'BOOLEAN', 1, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (11, u'location', u'TEXT', 0, None, 0)
  2011-04-13 14:51:16     INFO [sqlalchemy.engine.base.Engine.0x...feac] PRAGMA table_info("subject_properties")
  2011-04-13 14:51:16     INFO [sqlalchemy.engine.base.Engine.0x...feac] ()
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Col ('cid', 'name', 'type', 'notnull', 'dflt_value', 'pk')
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (0, u'created_at', u'DATETIME', 1, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (1, u'updated_at', u'DATETIME', 0, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (2, u'deleted_at', u'DATETIME', 0, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (3, u'deleted', u'BOOLEAN', 1, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (4, u'id', u'INTEGER', 1, None, 1)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (5, u'subject_id', u'INTEGER', 1, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (6, u'key', u'VARCHAR(255)', 1, None, 0)
  2011-04-13 14:51:16    DEBUG [sqlalchemy.engine.base.Engine.0x...feac] Row (7, u'value', u'TEXT', 0, None, 0)

  $ ps aux | grep subject
  root     20009  0.7  0.1  12744  9148 pts/1    S    12:47   0:00 /usr/bin/python /usr/bin/subject-api subject-api.conf --debug
  root     20012  2.0  0.1  25188 13356 pts/1    S    12:47   0:00 /usr/bin/python /usr/bin/subject-registry subject-registry.conf
  jsuh     20017  0.0  0.0   3368   744 pts/1    S+   12:47   0:00 grep subject

Simply supply the configuration file as the parameter to the ``--config-file`` option
(the ``etc/subject-api.conf`` and  ``etc/subject-registry.conf`` sample configuration
files were used in the above example) and then any other options
you want to use. (``--debug`` was used above to show some of the debugging
output that the server shows when starting up. Call the server program
with ``--help`` to see all available options you can specify on the
command line.)

For more information on configuring the server via the ``paste.deploy``
configuration files, see the section entitled
:doc:`Configuring Glance servers <configuring>`

Note that the server `daemonizes` itself by using the standard
shell backgrounding indicator, ``&``, in the previous example. For most use cases, we recommend
using the ``subject-control`` server daemon wrapper for daemonizing. See below
for more details on daemonization with ``subject-control``.

Using the ``subject-control`` program to start the server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The second way to start up a Glance server is to use the ``subject-control``
program. ``subject-control`` is a wrapper script that allows the user to
start, stop, restart, and reload the other Glance server programs in
a fashion that is more conducive to automation and scripting.

Servers started via the ``subject-control`` program are always `daemonized`,
meaning that the server program process runs in the background.

To start a Glance server with ``subject-control``, simply call
``subject-control`` with a server and the word "start", followed by
any command-line options you wish to provide. Start the server with ``subject-control``
in the following way::

  $> sudo subject-control [OPTIONS] <SERVER> start [CONFPATH]

.. note::

  You must use the ``sudo`` program to run ``subject-control`` currently, as the
  pid files for the server programs are written to /var/run/subject/

Here is an example that shows how to start the ``subject-registry`` server
with the ``subject-control`` wrapper script. ::


  $ sudo subject-control api start subject-api.conf
  Starting subject-api with /home/jsuh/subject.conf

  $ sudo subject-control registry start subject-registry.conf
  Starting subject-registry with /home/jsuh/subject.conf

  $ ps aux | grep subject
  root     20038  4.0  0.1  12728  9116 ?        Ss   12:51   0:00 /usr/bin/python /usr/bin/subject-api /home/jsuh/subject-api.conf
  root     20039  6.0  0.1  25188 13356 ?        Ss   12:51   0:00 /usr/bin/python /usr/bin/subject-registry /home/jsuh/subject-registry.conf
  jsuh     20042  0.0  0.0   3368   744 pts/1    S+   12:51   0:00 grep subject


The same configuration files are used by ``subject-control`` to start the
Glance server programs, and you can specify (as the example above shows)
a configuration file when starting the server.


In order for your launched subject service to be monitored for unexpected death
and respawned if necessary, use the following option:


  $ sudo subject-control [service] start --respawn ...


Note that this will cause ``subject-control`` itself to remain running. Also note
that deliberately stopped services are not respawned, neither are rapidly bouncing
services (where process death occurred within one second of the last launch).


By default, output from subject services is discarded when launched with ``subject-control``.
In order to capture such output via syslog, use the following option:


  $ sudo subject-control --capture-output ...


Stopping a server
-----------------

If you started a Glance server manually and did not use the ``&`` backgrounding
function, simply send a terminate signal to the server process by typing
``Ctrl-C``

If you started the Glance server using the ``subject-control`` program, you can
use the ``subject-control`` program to stop it. Simply do the following::

  $> sudo subject-control <SERVER> stop

as this example shows::

  $> sudo subject-control registry stop
  Stopping subject-registry  pid: 17602  signal: 15

Restarting a server
-------------------

You can restart a server with the ``subject-control`` program, as demonstrated
here::

  $> sudo subject-control registry restart etc/subject-registry.conf
  Stopping subject-registry  pid: 17611  signal: 15
  Starting subject-registry with /home/jpipes/repos/subject/trunk/etc/subject-registry.conf

Reloading a server
-------------------

You can reload a server with the ``subject-control`` program, as demonstrated
here::

  $> sudo subject-control api reload
  Reloading subject-api (pid 18506) with signal(1)

A reload sends a SIGHUP signal to the master process and causes new configuration
settings to be picked up without any interruption to the running service (provided
neither bind_host or bind_port has changed).
