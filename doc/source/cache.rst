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

The Glance Subject Cache
======================

The Glance API server may be configured to have an optional local subject cache.
A local subject cache stores a copy of subject files, essentially enabling multiple
API servers to serve the same subject file, resulting in an increase in
scalability due to an increased number of endpoints serving an subject file.

This local subject cache is transparent to the end user -- in other words, the
end user doesn't know that the Glance API is streaming an subject file from
its local cache or from the actual backend storage system.

Managing the Glance Subject Cache
-------------------------------

While subject files are automatically placed in the subject cache on successful
requests to ``GET /subjects/<IMAGE_ID>``, the subject cache is not automatically
managed. Here, we describe the basics of how to manage the local subject cache
on Glance API servers and how to automate this cache management.

Configuration options for the Subject Cache
-----------------------------------------

The Glance cache uses two files: one for configuring the server and
another for the utilities. The ``glance-api.conf`` is for the server
and the ``glance-cache.conf`` is for the utilities.

The following options are in both configuration files. These need the
same values otherwise the cache will potentially run into problems.

- ``subject_cache_dir`` This is the base directory where Glance stores
  the cache data (Required to be set, as does not have a default).
- ``subject_cache_sqlite_db`` Path to the sqlite file database that will
  be used for cache management. This is a relative path from the
  ``subject_cache_dir`` directory (Default:``cache.db``).
- ``subject_cache_driver`` The driver used for cache management.
  (Default:``sqlite``)
- ``subject_cache_max_size`` The size when the glance-cache-pruner will
  remove the oldest subjects, to reduce the bytes until under this value.
  (Default:``10 GB``)
- ``subject_cache_stall_time`` The amount of time an incomplete subject will
  stay in the cache, after this the incomplete subject will be deleted.
  (Default:``1 day``)

The following values are the ones that are specific to the
``glance-cache.conf`` and are only required for the prefetcher to run
correctly.

- ``admin_user`` The username for an admin account, this is so it can
  get the subject data into the cache.
- ``admin_password`` The password to the admin account.
- ``admin_tenant_name`` The tenant of the admin account.
- ``auth_url`` The URL used to authenticate to keystone. This will
  be taken from the environment variables if it exists.
- ``filesystem_store_datadir`` This is used if using the filesystem
  store, points to where the data is kept.
- ``filesystem_store_datadirs`` This is used to point to multiple
  filesystem stores.
- ``registry_host`` The URL to the Glance registry.

Controlling the Growth of the Subject Cache
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The subject cache has a configurable maximum size (the ``subject_cache_max_size``
configuration file option). The ``subject_cache_max_size`` is an upper limit
beyond which pruner, if running, starts cleaning the subjects cache.
However, when subjects are successfully returned from a call to
``GET /subjects/<IMAGE_ID>``, the subject cache automatically writes the subject
file to its cache, regardless of whether the resulting write would make the
subject cache's size exceed the value of ``subject_cache_max_size``.
In order to keep the subject cache at or below this maximum cache size,
you need to run the ``glance-cache-pruner`` executable.

The recommended practice is to use ``cron`` to fire ``glance-cache-pruner``
at a regular interval.

Cleaning the Subject Cache
~~~~~~~~~~~~~~~~~~~~~~~~

Over time, the subject cache can accumulate subject files that are either in
a stalled or invalid state. Stalled subject files are the result of an subject
cache write failing to complete. Invalid subject files are the result of an
subject file not being written properly to disk.

To remove these types of files, you run the ``glance-cache-cleaner``
executable.

The recommended practice is to use ``cron`` to fire ``glance-cache-cleaner``
at a semi-regular interval.

Prefetching Subjects into the Subject Cache
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some installations have base (sometimes called "golden") subjects that are
very commonly used to boot virtual machines. When spinning up a new API
server, administrators may wish to prefetch these subject files into the
local subject cache to ensure that reads of those popular subject files come
from a local cache.

To queue an subject for prefetching, you can use one of the following methods:

 * If the ``cache_manage`` middleware is enabled in the application pipeline,
   you may call ``PUT /queued-subjects/<IMAGE_ID>`` to queue the subject with
   identifier ``<IMAGE_ID>``

   Alternately, you can use the ``glance-cache-manage`` program to queue the
   subject. This program may be run from a different host than the host
   containing the subject cache. Example usage::

     $> glance-cache-manage --host=<HOST> queue-subject <IMAGE_ID>

   This will queue the subject with identifier ``<IMAGE_ID>`` for prefetching

Once you have queued the subjects you wish to prefetch, call the
``glance-cache-prefetcher`` executable, which will prefetch all queued subjects
concurrently, logging the results of the fetch for each subject.

Finding Which Subjects are in the Subject Cache
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can find out which subjects are in the subject cache using one of the
following methods:

  * If the ``cachemanage`` middleware is enabled in the application pipeline,
    you may call ``GET /cached-subjects`` to see a JSON-serialized list of
    mappings that show cached subjects, the number of cache hits on each subject,
    the size of the subject, and the times they were last accessed.

    Alternately, you can use the ``glance-cache-manage`` program. This program
    may be run from a different host than the host containing the subject cache.
    Example usage::

    $> glance-cache-manage --host=<HOST> list-cached

  * You can issue the following call on \*nix systems (on the host that contains
    the subject cache)::

      $> ls -lhR $IMAGE_CACHE_DIR

    where ``$IMAGE_CACHE_DIR`` is the value of the ``subject_cache_dir``
    configuration variable.

    Note that the subject's cache hit is not shown using this method.

Manually Removing Subjects from the Subject Cache
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If the ``cachemanage`` middleware is enabled, you may call
``DELETE /cached-subjects/<IMAGE_ID>`` to remove the subject file for subject
with identifier ``<IMAGE_ID>`` from the cache.

Alternately, you can use the ``glance-cache-manage`` program. Example usage::

  $> glance-cache-manage --host=<HOST> delete-cached-subject <IMAGE_ID>
