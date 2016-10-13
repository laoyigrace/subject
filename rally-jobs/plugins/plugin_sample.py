# Copyright 2014 Mirantis Inc.
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

""" Sample of plugin for Glance.

For more Glance related benchmarks take a look here:
github.com/openstack/rally/tree/master/samples/tasks/scenarios/subject

About plugins: https://rally.readthedocs.org/en/latest/plugins.html

Rally concepts https://wiki.openstack.org/wiki/Rally/Concepts
"""

import os

from rally.plugins.openstack import scenario
from rally.task import atomic
from rally.task import utils


class GlancePlugin(scenario.OpenStackScenario):

    @atomic.action_timer("subject.create_subject_label")
    def _create_subject(self, subject_name, container_format,
                      subject_location, disk_format, **kwargs):
        """Create a new subject.

        :param subject_name: String used to name the subject
        :param container_format: Container format of subject.
        Acceptable formats: ami, ari, aki, bare, ovf, ova and docker.
        :param subject_location: subject file location used to upload
        :param disk_format: Disk format of subject. Acceptable formats:
        ami, ari, aki, vhd, vhdx, vmdk, raw, qcow2, vdi, and iso.
        :param **kwargs:  optional parameters to create subject

        returns: object of subject
        """

        kw = {
            "name": subject_name,
            "container_format": container_format,
            "disk_format": disk_format,
        }

        kw.update(kwargs)

        try:
            if os.path.isfile(os.path.expanduser(subject_location)):
                kw["data"] = open(os.path.expanduser(subject_location))
            else:
                kw["copy_from"] = subject_location

            subject = self.clients("subject").subjects.create(**kw)
            subject = utils.wait_for(subject,
                                   is_ready=utils.resource_is("active"),
                                   update_resource=utils.get_from_manager(),
                                   timeout=100,
                                   check_interval=0.5)
        finally:
            if "data" in kw:
                kw["data"].close()

        return subject

    @atomic.action_timer("subject.list_subjects_label")
    def _list_subjects(self):
        return list(self.clients("subject").subjects.list())

    @scenario.configure(context={"cleanup": ["subject"]})
    def create_and_list(self, container_format,
                        subject_location, disk_format, **kwargs):
        self._create_subject(self.generate_random_name(),
                           container_format,
                           subject_location,
                           disk_format,
                           **kwargs)
        self._list_subjects()
