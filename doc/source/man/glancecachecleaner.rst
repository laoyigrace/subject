====================
subject-cache-cleaner
====================

----------------------------------------------------------------
Glance Subject Cache Invalid Cache Entry and Stalled Subject cleaner
----------------------------------------------------------------

:Author: subject@lists.launchpad.net
:Date:   2016-10-6
:Copyright: OpenStack Foundation
:Version: 13.0.0
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

subject-cache-cleaner [options]

DESCRIPTION
===========

This is meant to be run as a periodic task from cron.

If something goes wrong while we're caching an subject (for example the fetch
times out, or an exception is raised), we create an 'invalid' entry. These
entries are left around for debugging purposes. However, after some period of
time, we want to clean these up.

Also, if an incomplete subject hangs around past the subject_cache_stall_time
period, we automatically sweep it up.

OPTIONS
=======

  **General options**

  .. include:: general_options.rst

FILES
=====

  **/etc/subject/subject-cache.conf**
    Default configuration file for the Glance Cache

.. include:: footer.rst
