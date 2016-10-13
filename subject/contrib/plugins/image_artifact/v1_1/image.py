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


from subject.common.glare import definitions
import subject.contrib.plugins.subject_artifact.v1.subject as v1


class ImageAsAnArtifact(v1.ImageAsAnArtifact):
    __type_version__ = '1.1'

    icons = definitions.BinaryObjectList()

    similar_subjects = (definitions.
                      ArtifactReferenceList(references=definitions.
                                            ArtifactReference('Subject')))
