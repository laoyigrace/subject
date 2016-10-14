===================
subject-cache-manage
===================

------------------------
Cache management utility
------------------------

:Author: subject@lists.launchpad.net
:Date:   2016-10-6
:Copyright: OpenStack Foundation
:Version: 13.0.0
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  subject-cache-manage <command> [options] [args]

COMMANDS
========

  **help <command>**
        Output help for one of the commands below

  **list-cached**
        List all subjects currently cached

  **list-queued**
        List all subjects currently queued for caching

  **queue-subject**
        Queue an subject for caching

  **delete-cached-subject**
        Purges an subject from the cache

  **delete-all-cached-subjects**
        Removes all subjects from the cache

  **delete-queued-subject**
        Deletes an subject from the cache queue

  **delete-all-queued-subjects**
        Deletes all subjects from the cache queue

OPTIONS
=======

  **--version**
        show program's version number and exit

  **-h, --help**
        show this help message and exit

  **-v, --verbose**
        Print more verbose output

  **-d, --debug**
        Print more verbose output

  **-H ADDRESS, --host=ADDRESS**
        Address of Glance API host.
        Default: 0.0.0.0

  **-p PORT, --port=PORT**
        Port the Glance API host listens on.
        Default: 9292

  **-k, --insecure**
        Explicitly allow subject to perform "insecure" SSL
        (https) requests. The server's certificate will not be
        verified against any certificate authorities. This
        option should be used with caution.

  **-A TOKEN, --auth_token=TOKEN**
        Authentication token to use to identify the client to the subject server

  **-f, --force**
        Prevent select actions from requesting user confirmation

  **-S STRATEGY, --os-auth-strategy=STRATEGY**
        Authentication strategy (keystone or noauth)

  .. include:: openstack_options.rst

.. include:: footer.rst
