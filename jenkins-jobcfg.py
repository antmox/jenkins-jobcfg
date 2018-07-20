#!/usr/bin/env python
#
# The Unlicense
#
# This is free and unencumbered software released into the public domain.
#
# Anyone is free to copy, modify, publish, use, compile, sell, or
# distribute this software, either in source code form or as a compiled
# binary, for any purpose, commercial or non-commercial, and by any
# means.
#
# In jurisdictions that recognize copyright laws, the author or authors
# of this software dedicate any and all copyright interest in the
# software to the public domain. We make this dedication for the benefit
# of the public at large and to the detriment of our heirs and
# successors. We intend this dedication to be an overt act of
# relinquishment in perpetuity of all present and future rights to this
# software under copyright law.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
# For more information, please refer to <https://unlicense.org>

import sys, os, re, getpass, json, collections, warnings, base64

try:
    assert 0x02070000 <= sys.hexversion < 0x03000000
except:
    print >>sys.stderr, 'error: python-2.7 only'
    sys.exit(1)

try:
    import yaml, requests, xmltodict
except ImportError as e:
    print >>sys.stderr, 'error: ' + e.message
    sys.exit(1)


# ####################################################################
#
# jenkins-jobcfg
#

# Configure jenkins jobs by editing human friendly yaml description files

# TODO
#   create / copy / delete / enable / disable / ... jobs
#   enable / disable crumb usage
#   README file
#   tests


# ####################################################################

def xml2yaml(in_str):
    def dict_representer(dumper, data):
        return dumper.represent_dict(data.iteritems())

    # use block literals for multiline strings
    # https://stackoverflow.com/a/33300001
    def str_presenter(dumper, data):
        if len(data.splitlines()) > 1:  # check for multiline string
            # remove special characters or block style wont be allowed by yaml
            # module :( there is surely other chars to replace (cf emitter.py)
            data = data.replace('\r', '')
            return dumper.represent_scalar(
                'tag:yaml.org,2002:str', data, style='|')
        return dumper.represent_scalar('tag:yaml.org,2002:str', data)

    yaml.add_representer(collections.OrderedDict, dict_representer)
    yaml.add_representer(unicode, str_presenter)

    return yaml.dump(
        xmltodict.parse(in_str), allow_unicode=True, default_flow_style=False)

def ordered_load(
        stream, Loader=yaml.Loader, object_pairs_hook=collections.OrderedDict):
    # load in ordered dict to keep fields ordered
    # https://stackoverflow.com/a/21912744
    class OrderedLoader(Loader): pass

    def construct_mapping(loader, node):
        loader.flatten_mapping(node)
        return object_pairs_hook(loader.construct_pairs(node))

    OrderedLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping)
    return yaml.load(stream, OrderedLoader)

def yaml2xml(in_str):
    return xmltodict.unparse(ordered_load(in_str), pretty=True)


# ####################################################################

def jenkins_check_config(config):
    (jenkins_url, jenkins_user, jenkins_pass) = config
    assert jenkins_url and jenkins_user and jenkins_pass
    response = jenkins_request(config, 'GET', '/api/json')
    assert response.status_code == 200

def jenkins_configs(config_file):
    all_configs = os.path.isfile(config_file) and yaml.safe_load(
        open(config_file, 'r').read()) or []
    return all_configs

def jenkins_config(config_file, config_id=None):
    # get all configurations from config_file
    #   [{cfg1: {'url': 'xxx', 'username': 'xxx', ...}}, {cfg2: {...}}]
    all_configs = jenkins_configs(config_file)

    # use an OrderedDict to keep the first config first (used by default)
    #   OrderedDict({'cfg1': {...}, 'cfg2': {...}})
    all_configs = collections.OrderedDict(
        sum(map(lambda d: d.items(), all_configs), []))

    # use the given config id, or the first one in config_file, or 'default'
    config_id = (
        config_id or (all_configs and all_configs.keys()[0]) or 'default')

    # get existing config values
    config_dict = all_configs.get(config_id, {})
    config_url = config_dict.get('url', None)
    config_usr = config_dict.get('username', None)
    config_pwd = config_dict.get('password', None)

    # try this config
    try:
        jenkins_check_config((config_url, config_usr, config_pwd))
        return (config_url, config_usr, config_pwd)
    except: pass

    # try to ask user on failure (missing or wrong config)
    try:
        # take default values from previous cfg or from envvars
        def_config_url = config_url or os.getenv('JENKINS_URL')
        def_config_usr = config_usr or os.getenv('USER')

        config_url = (
            raw_input('jenkins url [%s]: ' % def_config_url)
            or def_config_url)
        config_usr = (
            raw_input('jenkins username [%s]: ' % def_config_usr)
            or def_config_usr)
        config_pwd = base64.b64encode(getpass.getpass(
            'jenkins password for %s: ' % config_usr))

        jenkins_check_config((config_url, config_usr, config_pwd))

        # update config file on success
        all_configs[config_id] = {
            'url': config_url, 'username': config_usr, 'password': config_pwd}
        open(config_file, 'wb').write(yaml.dump(
            map(lambda (k, v): {k: v}, all_configs.items()),
            default_flow_style=False))
        os.chmod(config_file, 0600)

        return (config_url, config_usr, config_pwd)

    except Exception as e:
        print >>sys.stderr, 'error: config check failure'
        sys.exit(1)

def jenkins_request(
        config, req_type, req_url, params=None, data=None, headers=None):
    request_funcs = {'GET': requests.get, 'POST': requests.post}
    assert req_type in request_funcs
    request_func = request_funcs[req_type]

    (jenkins_url, jenkins_user, jenkins_pass) = config

    params = params or {}

    headers = headers and dict(headers) or {}
    if req_type == 'POST':
        headers.update(jenkins_crumb(config))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        response = request_func(
            jenkins_url + req_url, auth=(jenkins_user, base64.b64decode(jenkins_pass)),
            params=params, data=data, headers=headers, verify=False)
    return response

def jenkins_crumb(config):
    response = jenkins_request(
        config, 'GET',
        '/crumbIssuer/api/xml?xpath=concat(//crumbRequestField,":",//crumb)')
    if response.status_code == 404:
        # assume that we have no crumb to issue if crumbIssuer is not found
        return {}
    assert response.status_code == 200
    return dict([tuple(response.content.split(':'))])


# ####################################################################

def jenkins_job_list(config):
    response = jenkins_request(config, 'GET', '/api/json')
    assert response.status_code == 200
    return map(lambda x: x['name'], json.loads(response.content)['jobs'])

def jenkins_fetch_config(config, job_name):
    try:
        response = jenkins_request(
            config, 'GET', '/job/%s/config.xml' % (job_name))
        assert response.status_code == 200
    except:
        print >>sys.stderr, (
            'warning: unable to fetch config for job %s' % job_name)
        return
    if False:  # also dump xml config file
        xml_config = 'config-%s.xml' % (job_name)
        with open(xml_config, 'wb') as outf:
            outf.write(response.content)
        print xml_config
    yaml_config = 'config-%s.yaml' % (job_name)
    with open(yaml_config, 'wb') as outf:
        outf.write(xml2yaml(response.content))
    print yaml_config

def jenkins_push_config(config, job_name, job_config_file):
    data = open(job_config_file, 'r').read()
    try:
        if job_config_file.endswith('.yaml'):
            data = yaml2xml(data)
        response = jenkins_request(
            config, 'POST', '/job/%s/config.xml' % (job_name),
            data=data, headers={'Content-Type': 'application/xml'})
        assert response.status_code == 200
    except:
        print >>sys.stderr, (
            'warning: unable to push config for job %s' % job_name)
        return
    print job_config_file

def jenkins_create_job(config, job_name, job_config_file):
    data = open(job_config_file, 'r').read()
    try:
        if job_config_file.endswith('.yaml'):
            data = yaml2xml(data)
        response = jenkins_request(
            config, 'POST', '/createItem',
            params={'name': job_name},
            data=data, headers={'Content-Type': 'application/xml'})
        assert response.status_code == 200
    except:
        print >>sys.stderr, (
            'warning: unable to create job %s' % job_name)
        return
    print job_config_file

def jenkins_delete_job(config, job_name):
    try:
        response = jenkins_request(
            config, 'POST', '/job/%s/doDelete' % (job_name))
        assert response.status_code == 200
    except:
        print >>sys.stderr, (
            'warning: unable to delete job %s' % job_name)
        return
    print job_name, 'deleted'


# ####################################################################

if __name__ == '__main__':

    import argparse

    default_cfg_file = os.path.join(
        '~', '.' + os.path.splitext(os.path.basename(sys.argv[0]))[0])

    parser = argparse.ArgumentParser(
        description='jenkins job configuration',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument(
        '-f', dest='cfg_file', default=default_cfg_file, action='store',
        type=str, help='configuration file')
    parser.add_argument(
        '-c', dest='cfg_id', default=None, action='store', type=str,
        help='configuration identifier')
    subparsers = parser.add_subparsers(title='subcommands', dest='action')

    parser_list = subparsers.add_parser(
        'list', help='list jenkins jobs')

    parser_fetch = subparsers.add_parser(
        'fetch', description='fetch jenkins job configuration',
        help='fetch jenkins job configuration')
    parser_fetch.add_argument(
        'job_names', help='jenkins job names', nargs='*')

    parser_push = subparsers.add_parser(
        'push', description='push jenkins job configuration',
        help='push jenkins job configuration')
    parser_push.add_argument(
        'config_files', help='jenkins config files', nargs='*')

    parser_create = subparsers.add_parser(
        'create', description='create jenkins job from configuration',
        help='create jenkins job')
    parser_create.add_argument(
        'config_files', help='jenkins config files', nargs='*')

    parser_delete = subparsers.add_parser(
        'delete', description='delete jenkins job',
        help='delete jenkins job')
    parser_delete.add_argument(
        'job_names', help='jenkins job names', nargs='*')

    parser_list = subparsers.add_parser(
        'config', help='configure jenkins-config tool')

    args = parser.parse_args()

    args.cfg_file = os.path.expanduser(args.cfg_file)

    config = jenkins_config(args.cfg_file, args.cfg_id)

    if args.action == 'list':
        print '\n'.join(jenkins_job_list(config))

    elif args.action == 'fetch':
        if args.job_names == ['all']:
            args.job_names = jenkins_job_list(config)
        for jobname in args.job_names:
            jenkins_fetch_config(config, jobname)

    elif args.action == 'push':
        for job_config in args.config_files:
            re_obj = re.match('^config-(.*)\.[^.]*$', job_config)
            if not re_obj:
                print >>sys.stderr, 'warning: ignored config file', job_config
                print >>sys.stderr, '(expected "config-<jobname>.(xml|yaml)")'
                continue
            jenkins_push_config(config, re_obj.group(1), job_config)

    elif args.action == 'create':
        for job_config in args.config_files:
            re_obj = re.match('^config-(.*)\.[^.]*$', job_config)
            if not re_obj:
                print >>sys.stderr, 'warning: ignored config file', job_config
                print >>sys.stderr, '(expected "config-<jobname>.(xml|yaml)")'
                continue
            jenkins_create_job(config, re_obj.group(1), job_config)

    elif args.action == 'delete':
        for jobname in args.job_names:
            jenkins_delete_job(config, jobname)

    elif args.action == 'config':
        all_configs = yaml.dump(
            jenkins_configs(args.cfg_file), default_flow_style=False)
        print '#'
        print '#', args.cfg_file
        print '#'
        print
        print re.sub('password: .*', 'password: *****', all_configs)

    else: assert 0


# ####################################################################
