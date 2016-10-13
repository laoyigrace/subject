#!/usr/bin/env python

# Copyright 2011 OpenStack Foundation
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
A simple cache management utility for Glance.
"""
from __future__ import print_function

import datetime
import functools
import optparse
import os
import sys
import time

from oslo_utils import encodeutils
import prettytable

from six.moves import input

# If ../subject/__init__.py exists, add ../ to Python search path, so that
# it will override what happens to be installed in /usr/(local/)lib/python...
possible_topdir = os.path.normpath(os.path.join(os.path.abspath(sys.argv[0]),
                                   os.pardir,
                                   os.pardir))
if os.path.exists(os.path.join(possible_topdir, 'subject', '__init__.py')):
    sys.path.insert(0, possible_topdir)

from subject.common import exception
import subject.subject_cache.client
from subject.version import version_info as version


SUCCESS = 0
FAILURE = 1


def catch_error(action):
    """Decorator to provide sensible default error handling for actions."""
    def wrap(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                ret = func(*args, **kwargs)
                return SUCCESS if ret is None else ret
            except exception.NotFound:
                options = args[0]
                print("Cache management middleware not enabled on host %s" %
                      options.host)
                return FAILURE
            except exception.Forbidden:
                print("Not authorized to make this request.")
                return FAILURE
            except Exception as e:
                options = args[0]
                if options.debug:
                    raise
                print("Failed to %s. Got error:" % action)
                pieces = encodeutils.exception_to_unicode(e).split('\n')
                for piece in pieces:
                    print(piece)
                return FAILURE

        return wrapper
    return wrap


@catch_error('show cached subjects')
def list_cached(options, args):
    """%(prog)s list-cached [options]

List all subjects currently cached.
    """
    client = get_client(options)
    subjects = client.get_cached_subjects()
    if not subjects:
        print("No cached subjects.")
        return SUCCESS

    print("Found %d cached subjects..." % len(subjects))

    pretty_table = prettytable.PrettyTable(("ID",
                                            "Last Accessed (UTC)",
                                            "Last Modified (UTC)",
                                            "Size",
                                            "Hits"))
    pretty_table.align['Size'] = "r"
    pretty_table.align['Hits'] = "r"

    for subject in subjects:
        last_accessed = subject['last_accessed']
        if last_accessed == 0:
            last_accessed = "N/A"
        else:
            last_accessed = datetime.datetime.utcfromtimestamp(
                last_accessed).isoformat()

        pretty_table.add_row((
            subject['subject_id'],
            last_accessed,
            datetime.datetime.utcfromtimestamp(
                subject['last_modified']).isoformat(),
            subject['size'],
            subject['hits']))

    print(pretty_table.get_string())


@catch_error('show queued subjects')
def list_queued(options, args):
    """%(prog)s list-queued [options]

List all subjects currently queued for caching.
    """
    client = get_client(options)
    subjects = client.get_queued_subjects()
    if not subjects:
        print("No queued subjects.")
        return SUCCESS

    print("Found %d queued subjects..." % len(subjects))

    pretty_table = prettytable.PrettyTable(("ID",))

    for subject in subjects:
        pretty_table.add_row((subject,))

    print(pretty_table.get_string())


@catch_error('queue the specified subject for caching')
def queue_subject(options, args):
    """%(prog)s queue-subject <IMAGE_ID> [options]

Queues an subject for caching
"""
    if len(args) == 1:
        subject_id = args.pop()
    else:
        print("Please specify one and only ID of the subject you wish to ")
        print("queue from the cache as the first argument")
        return FAILURE

    if (not options.force and
        not user_confirm("Queue subject %(subject_id)s for caching?" %
                         {'subject_id': subject_id}, default=False)):
        return SUCCESS

    client = get_client(options)
    client.queue_subject_for_caching(subject_id)

    if options.verbose:
        print("Queued subject %(subject_id)s for caching" %
              {'subject_id': subject_id})

    return SUCCESS


@catch_error('delete the specified cached subject')
def delete_cached_subject(options, args):
    """
%(prog)s delete-cached-subject <IMAGE_ID> [options]

Deletes an subject from the cache
    """
    if len(args) == 1:
        subject_id = args.pop()
    else:
        print("Please specify one and only ID of the subject you wish to ")
        print("delete from the cache as the first argument")
        return FAILURE

    if (not options.force and
        not user_confirm("Delete cached subject %(subject_id)s?" %
                         {'subject_id': subject_id}, default=False)):
        return SUCCESS

    client = get_client(options)
    client.delete_cached_subject(subject_id)

    if options.verbose:
        print("Deleted cached subject %(subject_id)s" % {'subject_id': subject_id})

    return SUCCESS


@catch_error('Delete all cached subjects')
def delete_all_cached_subjects(options, args):
    """%(prog)s delete-all-cached-subjects [options]

Remove all subjects from the cache.
    """
    if (not options.force and
            not user_confirm("Delete all cached subjects?", default=False)):
        return SUCCESS

    client = get_client(options)
    num_deleted = client.delete_all_cached_subjects()

    if options.verbose:
        print("Deleted %(num_deleted)s cached subjects" %
              {'num_deleted': num_deleted})

    return SUCCESS


@catch_error('delete the specified queued subject')
def delete_queued_subject(options, args):
    """
%(prog)s delete-queued-subject <IMAGE_ID> [options]

Deletes an subject from the cache
    """
    if len(args) == 1:
        subject_id = args.pop()
    else:
        print("Please specify one and only ID of the subject you wish to ")
        print("delete from the cache as the first argument")
        return FAILURE

    if (not options.force and
        not user_confirm("Delete queued subject %(subject_id)s?" %
                         {'subject_id': subject_id}, default=False)):
        return SUCCESS

    client = get_client(options)
    client.delete_queued_subject(subject_id)

    if options.verbose:
        print("Deleted queued subject %(subject_id)s" % {'subject_id': subject_id})

    return SUCCESS


@catch_error('Delete all queued subjects')
def delete_all_queued_subjects(options, args):
    """%(prog)s delete-all-queued-subjects [options]

Remove all subjects from the cache queue.
    """
    if (not options.force and
            not user_confirm("Delete all queued subjects?", default=False)):
        return SUCCESS

    client = get_client(options)
    num_deleted = client.delete_all_queued_subjects()

    if options.verbose:
        print("Deleted %(num_deleted)s queued subjects" %
              {'num_deleted': num_deleted})

    return SUCCESS


def get_client(options):
    """Return a new client object to a Glance server.

    specified by the --host and --port options
    supplied to the CLI
    """
    return subject.subject_cache.client.get_client(
        host=options.host,
        port=options.port,
        username=options.os_username,
        password=options.os_password,
        tenant=options.os_tenant_name,
        auth_url=options.os_auth_url,
        auth_strategy=options.os_auth_strategy,
        auth_token=options.os_auth_token,
        region=options.os_region_name,
        insecure=options.insecure)


def env(*vars, **kwargs):
    """Search for the first defined of possibly many env vars.

    Returns the first environment variable defined in vars, or
    returns the default defined in kwargs.
    """
    for v in vars:
        value = os.environ.get(v, None)
        if value:
            return value
    return kwargs.get('default', '')


def create_options(parser):
    """Set up the CLI and config-file options that may be
    parsed and program commands.

    :param parser: The option parser
    """
    parser.add_option('-v', '--verbose', default=False, action="store_true",
                      help="Print more verbose output.")
    parser.add_option('-d', '--debug', default=False, action="store_true",
                      help="Print debugging output.")
    parser.add_option('-H', '--host', metavar="ADDRESS", default="0.0.0.0",
                      help="Address of Glance API host. "
                           "Default: %default.")
    parser.add_option('-p', '--port', dest="port", metavar="PORT",
                      type=int, default=9292,
                      help="Port the Glance API host listens on. "
                           "Default: %default.")
    parser.add_option('-k', '--insecure', dest="insecure",
                      default=False, action="store_true",
                      help="Explicitly allow subject to perform \"insecure\" "
                      "SSL (https) requests. The server's certificate will "
                      "not be verified against any certificate authorities. "
                      "This option should be used with caution.")
    parser.add_option('-f', '--force', dest="force", metavar="FORCE",
                      default=False, action="store_true",
                      help="Prevent select actions from requesting "
                           "user confirmation.")

    parser.add_option('--os-auth-token',
                      dest='os_auth_token',
                      default=env('OS_AUTH_TOKEN'),
                      help='Defaults to env[OS_AUTH_TOKEN].')
    parser.add_option('-A', '--os_auth_token', '--auth_token',
                      dest='os_auth_token',
                      help=optparse.SUPPRESS_HELP)

    parser.add_option('--os-username',
                      dest='os_username',
                      default=env('OS_USERNAME'),
                      help='Defaults to env[OS_USERNAME].')
    parser.add_option('-I', '--os_username',
                      dest='os_username',
                      help=optparse.SUPPRESS_HELP)

    parser.add_option('--os-password',
                      dest='os_password',
                      default=env('OS_PASSWORD'),
                      help='Defaults to env[OS_PASSWORD].')
    parser.add_option('-K', '--os_password',
                      dest='os_password',
                      help=optparse.SUPPRESS_HELP)

    parser.add_option('--os-region-name',
                      dest='os_region_name',
                      default=env('OS_REGION_NAME'),
                      help='Defaults to env[OS_REGION_NAME].')
    parser.add_option('-R', '--os_region_name',
                      dest='os_region_name',
                      help=optparse.SUPPRESS_HELP)

    parser.add_option('--os-tenant-id',
                      dest='os_tenant_id',
                      default=env('OS_TENANT_ID'),
                      help='Defaults to env[OS_TENANT_ID].')
    parser.add_option('--os_tenant_id',
                      dest='os_tenant_id',
                      help=optparse.SUPPRESS_HELP)

    parser.add_option('--os-tenant-name',
                      dest='os_tenant_name',
                      default=env('OS_TENANT_NAME'),
                      help='Defaults to env[OS_TENANT_NAME].')
    parser.add_option('-T', '--os_tenant_name',
                      dest='os_tenant_name',
                      help=optparse.SUPPRESS_HELP)

    parser.add_option('--os-auth-url',
                      default=env('OS_AUTH_URL'),
                      help='Defaults to env[OS_AUTH_URL].')
    parser.add_option('-N', '--os_auth_url',
                      dest='os_auth_url',
                      help=optparse.SUPPRESS_HELP)

    parser.add_option('-S', '--os_auth_strategy', dest="os_auth_strategy",
                      metavar="STRATEGY",
                      help="Authentication strategy (keystone or noauth).")


def parse_options(parser, cli_args):
    """
    Returns the parsed CLI options, command to run and its arguments, merged
    with any same-named options found in a configuration file

    :param parser: The option parser
    """
    if not cli_args:
        cli_args.append('-h')  # Show options in usage output...

    (options, args) = parser.parse_args(cli_args)

    # HACK(sirp): Make the parser available to the print_help method
    # print_help is a command, so it only accepts (options, args); we could
    # one-off have it take (parser, options, args), however, for now, I think
    # this little hack will suffice
    options.__parser = parser

    if not args:
        parser.print_usage()
        sys.exit(0)

    command_name = args.pop(0)
    command = lookup_command(parser, command_name)

    return (options, command, args)


def print_help(options, args):
    """
    Print help specific to a command
    """
    parser = options.__parser

    if not args:
        parser.print_help()
    else:
        number_of_commands = len(args)
        if number_of_commands == 1:
            command_name = args.pop()
            command = lookup_command(parser, command_name)
            print(command.__doc__ % {'prog': os.path.basename(sys.argv[0])})
        else:
            sys.exit("Please specify one command")


def lookup_command(parser, command_name):
    BASE_COMMANDS = {'help': print_help}

    CACHE_COMMANDS = {
        'list-cached': list_cached,
        'list-queued': list_queued,
        'queue-subject': queue_subject,
        'delete-cached-subject': delete_cached_subject,
        'delete-all-cached-subjects': delete_all_cached_subjects,
        'delete-queued-subject': delete_queued_subject,
        'delete-all-queued-subjects': delete_all_queued_subjects,
    }

    commands = {}
    for command_set in (BASE_COMMANDS, CACHE_COMMANDS):
        commands.update(command_set)

    try:
        command = commands[command_name]
    except KeyError:
        parser.print_usage()
        sys.exit("Unknown command: %(cmd_name)s" % {'cmd_name': command_name})

    return command


def user_confirm(prompt, default=False):
    """Yes/No question dialog with user.

    :param prompt: question/statement to present to user (string)
    :param default: boolean value to return if empty string
                    is received as response to prompt

    """
    if default:
        prompt_default = "[Y/n]"
    else:
        prompt_default = "[y/N]"

    answer = input("%s %s " % (prompt, prompt_default))

    if answer == "":
        return default
    else:
        return answer.lower() in ("yes", "y")


def main():
    usage = """
%prog <command> [options] [args]

Commands:

    help <command> Output help for one of the commands below

    list-cached                 List all subjects currently cached

    list-queued                 List all subjects currently queued for caching

    queue-subject                 Queue an subject for caching

    delete-cached-subject         Purges an subject from the cache

    delete-all-cached-subjects    Removes all subjects from the cache

    delete-queued-subject         Deletes an subject from the cache queue

    delete-all-queued-subjects    Deletes all subjects from the cache queue
"""

    version_string = version.cached_version_string()
    oparser = optparse.OptionParser(version=version_string,
                                    usage=usage.strip())
    create_options(oparser)
    (options, command, args) = parse_options(oparser, sys.argv[1:])

    try:
        start_time = time.time()
        result = command(options, args)
        end_time = time.time()
        if options.verbose:
            print("Completed in %-0.4f sec." % (end_time - start_time))
        sys.exit(result)
    except (RuntimeError, NotImplementedError) as e:
        sys.exit("ERROR: %s" % e)

if __name__ == '__main__':
    main()
