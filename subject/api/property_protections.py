#    Copyright 2013 Rackspace
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

from subject.common import exception
import subject.domain.proxy


class ProtectedSubjectFactoryProxy(subject.domain.proxy.SubjectFactory):

    def __init__(self, subject_factory, context, property_rules):
        self.subject_factory = subject_factory
        self.context = context
        self.property_rules = property_rules
        kwargs = {'context': self.context,
                  'property_rules': self.property_rules}
        super(ProtectedSubjectFactoryProxy, self).__init__(
            subject_factory,
            proxy_class=ProtectedSubjectProxy,
            proxy_kwargs=kwargs)

    def new_subject(self, **kwargs):
        extra_props = kwargs.pop('extra_properties', {})

        extra_properties = {}
        for key in extra_props.keys():
            if self.property_rules.check_property_rules(key, 'create',
                                                        self.context):
                extra_properties[key] = extra_props[key]
            else:
                raise exception.ReservedProperty(property=key)
        return super(ProtectedSubjectFactoryProxy, self).new_subject(
            extra_properties=extra_properties, **kwargs)


class ProtectedSubjectRepoProxy(subject.domain.proxy.Repo):

    def __init__(self, subject_repo, context, property_rules):
        self.context = context
        self.subject_repo = subject_repo
        self.property_rules = property_rules
        proxy_kwargs = {'context': self.context}
        super(ProtectedSubjectRepoProxy, self).__init__(
            subject_repo, item_proxy_class=ProtectedSubjectProxy,
            item_proxy_kwargs=proxy_kwargs)

    def get(self, subject_id):
        return ProtectedSubjectProxy(self.subject_repo.get(subject_id),
                                   self.context, self.property_rules)

    def list(self, *args, **kwargs):
        subjects = self.subject_repo.list(*args, **kwargs)
        return [ProtectedSubjectProxy(subject, self.context, self.property_rules)
                for subject in subjects]


class ProtectedSubjectProxy(subject.domain.proxy.Subject):

    def __init__(self, subject, context, property_rules):
        self.subject = subject
        self.context = context
        self.property_rules = property_rules

        self.subject.extra_properties = ExtraPropertiesProxy(
            self.context,
            self.subject.extra_properties,
            self.property_rules)
        super(ProtectedSubjectProxy, self).__init__(self.subject)


class ExtraPropertiesProxy(subject.domain.ExtraProperties):

    def __init__(self, context, extra_props, property_rules):
        self.context = context
        self.property_rules = property_rules
        extra_properties = {}
        for key in extra_props.keys():
            if self.property_rules.check_property_rules(key, 'read',
                                                        self.context):
                extra_properties[key] = extra_props[key]
        super(ExtraPropertiesProxy, self).__init__(extra_properties)

    def __getitem__(self, key):
        if self.property_rules.check_property_rules(key, 'read', self.context):
            return dict.__getitem__(self, key)
        else:
            raise KeyError

    def __setitem__(self, key, value):
        # NOTE(isethi): Exceptions are raised only for actions update, delete
        # and create, where the user proactively interacts with the properties.
        # A user cannot request to read a specific property, hence reads do
        # raise an exception
        try:
            if self.__getitem__(key) is not None:
                if self.property_rules.check_property_rules(key, 'update',
                                                            self.context):
                    return dict.__setitem__(self, key, value)
                else:
                    raise exception.ReservedProperty(property=key)
        except KeyError:
            if self.property_rules.check_property_rules(key, 'create',
                                                        self.context):
                return dict.__setitem__(self, key, value)
            else:
                raise exception.ReservedProperty(property=key)

    def __delitem__(self, key):
        if key not in super(ExtraPropertiesProxy, self).keys():
            raise KeyError

        if self.property_rules.check_property_rules(key, 'delete',
                                                    self.context):
            return dict.__delitem__(self, key)
        else:
            raise exception.ReservedProperty(property=key)
