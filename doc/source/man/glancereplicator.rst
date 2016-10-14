=================
subject-replicator
=================

---------------------------------------------
Replicate subjects across multiple data centers
---------------------------------------------

:Author: subject@lists.launchpad.net
:Date:   2016-10-6
:Copyright: OpenStack Foundation
:Version: 13.0.0
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

subject-replicator <command> [options] [args]

DESCRIPTION
===========

subject-replicator is a utility can be used to populate a new subject
server using the subjects stored in an existing subject server. The subjects
in the replicated subject server preserve the uuids, metadata, and subject
data from the original.

COMMANDS
========

  **help <command>**
        Output help for one of the commands below

  **compare**
        What is missing from the slave subject?

  **dump**
        Dump the contents of a subject instance to local disk.

  **livecopy**
       Load the contents of one subject instance into another.

  **load**
        Load the contents of a local directory into subject.

  **size**
        Determine the size of a subject instance if dumped to disk.

OPTIONS
=======

  **-h, --help**
        Show this help message and exit

  **-c CHUNKSIZE, --chunksize=CHUNKSIZE**
        Amount of data to transfer per HTTP write

  **-d, --debug**
        Print debugging information

  **-D DONTREPLICATE, --dontreplicate=DONTREPLICATE**
        List of fields to not replicate

  **-m, --metaonly**
        Only replicate metadata, not subjects

  **-l LOGFILE, --logfile=LOGFILE**
        Path of file to log to

  **-s, --syslog**
        Log to syslog instead of a file

  **-t TOKEN, --token=TOKEN**
        Pass in your authentication token if you have one. If
        you use this option the same token is used for both
        the master and the slave.

  **-M MASTERTOKEN, --mastertoken=MASTERTOKEN**
        Pass in your authentication token if you have one.
        This is the token used for the master.

  **-S SLAVETOKEN, --slavetoken=SLAVETOKEN**
        Pass in your authentication token if you have one.
        This is the token used for the slave.

  **-v, --verbose**
         Print more verbose output

.. include:: footer.rst
