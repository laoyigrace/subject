# Copyright (c) 2014 Mirantis, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from subject.common import exception
from subject.common.glare import definitions
import subject.contrib.plugins.subject_artifact.v1_1.subject as v1_1

# Since this is not in the test-requirements.txt and the class below,
# SubjectAsAnArtifact, is pending removal a try except is added to prevent
# an ImportError when module docs are generated
try:
    import subjectclient
except ImportError:
    subjectclient = None


from subject.i18n import _


class SubjectAsAnArtifact(v1_1.SubjectAsAnArtifact):
    __type_version__ = '2.0'

    file = definitions.BinaryObject(required=False)
    legacy_subject_id = definitions.String(required=False, mutable=False,
                                         pattern=R'[0-9a-f]{8}-[0-9a-f]{4}'
                                                 R'-4[0-9a-f]{3}-[89ab]'
                                                 R'[0-9a-f]{3}-[0-9a-f]{12}')

    def __pre_publish__(self, context, *args, **kwargs):
        super(SubjectAsAnArtifact, self).__pre_publish__(*args, **kwargs)
        if self.file is None and self.legacy_subject_id is None:
            raise exception.InvalidArtifactPropertyValue(
                message=_("Either a file or a legacy_subject_id has to be "
                          "specified")
            )
        if self.file is not None and self.legacy_subject_id is not None:
            raise exception.InvalidArtifactPropertyValue(
                message=_("Both file and legacy_subject_id may not be "
                          "specified at the same time"))

        if self.legacy_subject_id:
            subject_endpoint = next(service['endpoints'][0]['publicURL']
                                   for service in context.service_catalog
                                   if service['name'] == 'subject')
            # Ensure subjectclient is imported correctly since we are catching
            # the ImportError on initialization
            if subjectclient == None:
                raise ImportError(_("Glance client not installed"))

            try:
                client = subjectclient.Client(version=2,
                                              endpoint=subject_endpoint,
                                              token=context.auth_token)
                legacy_subject = client.subjects.get(self.legacy_subject_id)
            except Exception:
                raise exception.InvalidArtifactPropertyValue(
                    message=_('Unable to get legacy subject')
                )
            if legacy_subject is not None:
                self.file = definitions.Blob(size=legacy_subject.size,
                                             locations=[
                                                 {
                                                     "status": "active",
                                                     "value":
                                                     legacy_subject.direct_url
                                                 }],
                                             checksum=legacy_subject.checksum,
                                             item_key=legacy_subject.id)
            else:
                raise exception.InvalidArtifactPropertyValue(
                    message=_("Legacy subject was not found")
                )
