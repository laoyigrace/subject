#!/usr/bin/env python

# Copyright 2011-2012 OpenStack Foundation
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
Glance Subject Cache Pre-fetcher

This is meant to be run from the command line after queueing
subjects to be pretched.
"""

import os
import sys

# If ../subject/__init__.py exists, add ../ to Python search path, so that
# it will override what happens to be installed in /usr/(local/)lib/python...
possible_topdir = os.path.normpath(os.path.join(os.path.abspath(sys.argv[0]),
                                   os.pardir,
                                   os.pardir))
if os.path.exists(os.path.join(possible_topdir, 'subject', '__init__.py')):
    sys.path.insert(0, possible_topdir)

import subject_store
from oslo_log import log as logging

from subject.common import config
from subject.subject_cache import prefetcher

CONF = config.CONF
logging.register_options(CONF)


def main():
    try:
        config.parse_cache_args()
        logging.setup(CONF, 'subject')

        subject_store.register_opts(config.CONF)
        subject_store.create_stores(config.CONF)
        subject_store.verify_default_store()

        app = prefetcher.Prefetcher()
        app.run()
    except RuntimeError as e:
        sys.exit("ERROR: %s" % e)


if __name__ == '__main__':
    main()
