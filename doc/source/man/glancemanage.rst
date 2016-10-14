=============
subject-manage
=============

-------------------------
Glance Management Utility
-------------------------

:Author: subject@lists.launchpad.net
:Date:   2016-10-6
:Copyright: OpenStack Foundation
:Version: 13.0.0
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  subject-manage [options]

DESCRIPTION
===========

subject-manage is a utility for managing and configuring a Glance installation.
One important use of subject-manage is to setup the database. To do this run::

    subject-manage db_sync

Note: subject-manage commands can be run either like this::

    subject-manage db sync

or with the db commands concatenated, like this::

    subject-manage db_sync



COMMANDS
========

  **db**
        This is the prefix for the commands below when used with a space
        rather than a _. For example "db version".

  **db_version**
        This will print the current migration level of a subject database.

  **db_upgrade <VERSION>**
        This will take an existing database and upgrade it to the
        specified VERSION.

  **db_version_control**
        Place the database under migration control.

  **db_sync <VERSION> <CURRENT_VERSION>**
        Place a database under migration control and upgrade, creating
        it first if necessary.

  **db_export_metadefs**
        Export the metadata definitions into json format. By default the
        definitions are exported to /etc/subject/metadefs directory.

  **db_load_metadefs**
        Load the metadata definitions into subject database. By default the
        definitions are imported from /etc/subject/metadefs directory.

  **db_unload_metadefs**
        Unload the metadata definitions. Clears the contents of all the subject
        db tables including metadef_namespace_resource_types, metadef_tags,
        metadef_objects, metadef_resource_types, metadef_namespaces and
        metadef_properties.

OPTIONS
=======

  **General Options**

  .. include:: general_options.rst

  **--sql_connection=CONN_STRING**
        A proper SQLAlchemy connection string as described
        `here <http://www.sqlalchemy.org/docs/05/reference/sqlalchemy/connections.html?highlight=engine#sqlalchemy.create_engine>`_

.. include:: footer.rst

CONFIGURATION
=============

The following paths are searched for a ``subject-manage.conf`` file in the
following order:

* ``~/.subject``
* ``~/``
* ``/etc/subject``
* ``/etc``

All options set in ``subject-manage.conf`` override those set in
``subject-registry.conf`` and ``subject-api.conf``.
