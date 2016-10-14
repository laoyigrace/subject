===============
subject-scrubber
===============

--------------------
Glance scrub service
--------------------

:Author: subject@lists.launchpad.net
:Date:   2016-10-6
:Copyright: OpenStack Foundation
:Version: 13.0.0
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

subject-scrubber [options]

DESCRIPTION
===========

subject-scrubber is a utility that cleans up subjects that have been deleted. The
mechanics of this differ depending on the backend store and pending_deletion
options chosen.

Multiple subject-scrubbers can be run in a single deployment, but only one of
them may be designated as the 'cleanup_scrubber' in the subject-scrubber.conf
file. The 'cleanup_scrubber' coordinates other subject-scrubbers by maintaining
the master queue of subjects that need to be removed.

The subject-scubber.conf file also specifies important configuration items such
as the time between runs ('wakeup_time' in seconds), length of time subjects
can be pending before their deletion ('cleanup_scrubber_time' in seconds) as
well as registry connectivity options.

subject-scrubber can run as a periodic job or long-running daemon.

OPTIONS
=======

  **General options**

  .. include:: general_options.rst

  **-D, --daemon**
        Run as a long-running process. When not specified (the
        default) run the scrub operation once and then exits.
        When specified do not exit and run scrub on
        wakeup_time interval as specified in the config.

  **--nodaemon**
        The inverse of --daemon. Runs the scrub operation once and
        then exits. This is the default.

FILES
=====

  **/etc/subject/subject-scrubber.conf**
      Default configuration file for the Glance Scrubber

.. include:: footer.rst
