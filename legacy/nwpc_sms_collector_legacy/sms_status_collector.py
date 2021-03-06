# coding=utf-8
import argparse
import subprocess
import string
import re
from datetime import datetime, time, timedelta
import json
import gzip

import requests

# default settings

config_file_name = 'sms_status_collector.config'

SMS_STATUS_POST_HOST = "10.28.32.175"
SMS_STATUS_POST_PORT = 5101
SMS_STATUS_POST_URL = "http://{host}:{port}/api/v1/hpc/sms/status"
POST_HEADERS = {}


default_sms_variable_list = [
    {
        'variable_name': 'SMSDATE',
        'variable_pattern': r"^.*SMSDATE '([0-9]+)'",  # TODO: gen var or edit var
        'variable_value_group_index': 0
    }
]


def get_config(config_file_path):
    """
    读取配置文件信息，配置文件为 json 格式
    :param config_file_path:
    :return:
    """
    global SMS_STATUS_POST_HOST, SMS_STATUS_POST_PORT, SMS_STATUS_POST_URL, POST_HEADERS
    f = open(config_file_path, 'r')
    config = json.load(f)
    f.close()

    SMS_STATUS_POST_HOST = config['post']['host']
    SMS_STATUS_POST_PORT = config['post']['port']
    SMS_STATUS_POST_URL = config['post']['url']
    if 'headers' in config['post']:
        POST_HEADERS = config['post']['headers']

    return config


def get_sms_variable(sms_name, sms_user, sms_password, node_path, variable_list=default_sms_variable_list):
    """
    获取 node_path 节点的变量
    :param sms_name:
    :param sms_user:
    :param sms_password:
    :param node_path: 节点路径，形如 /obs_reg
    :param variable_list: 变量列表
    :return:
    """
    command_string = "login {sms_name} {sms_user}  {sms_password};status;show -f -K {node_path};quit".format(
        sms_name=sms_name,
        sms_user=sms_user,
        sms_password=sms_password,
        node_path=node_path
    )
    echo_pipe = subprocess.Popen(
        ['echo', command_string],
        stdout=subprocess.PIPE,
        encoding='utf-8'
    )
    cdp_pipe = subprocess.Popen(
        ['/cma/u/app/sms/bin/cdp'],
        stdin=echo_pipe.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding='utf-8'
    )
    echo_pipe.stdout.close()
    (cdp_output, cdp_error) = cdp_pipe.communicate()
    return_code = cdp_pipe.returncode
    if return_code != 0:
        current_time = datetime.utcnow().isoformat()
        result = {
            'app': 'sms_status_collector',
            'timestamp': current_time,
            'error': 'command_return_code_error',
            'error-msg': cdp_error
        }
        return result
    cdp_output_lines = cdp_output.split('\n')

    variable_map = {}

    for a_variable in variable_list:
        a_variable['re_line'] = re.compile(a_variable['variable_pattern'])

    for line in cdp_output_lines:
        for a_variable in variable_list:
            m = a_variable['re_line'].match(line)
            if m is not None:
                g = m.groups()
                variable_value = g[a_variable['variable_value_group_index']]
                variable_map[a_variable['variable_name']] = variable_value
    return variable_map


def get_sms_status(sms_name, sms_user, sms_password, verbose=False):
    """
    获取 sms 服务器状态
    :param sms_name:
    :param sms_user:
    :param sms_password:
    :param verbose:
    :return:
    """
    command_string = "login {sms_name} {sms_user}  {sms_password};status;quit".format(
        sms_name=sms_name,
        sms_user=sms_user,
        sms_password=sms_password
    )
    echo_pipe = subprocess.Popen(
        ['echo', command_string],
        stdout=subprocess.PIPE,
        encoding='utf-8')
    cdp_pipe = subprocess.Popen(
        ['/cma/u/app/sms/bin/cdp'],
        stdin=echo_pipe.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding='utf-8')
    echo_pipe.stdout.close()
    (cdp_output, cdp_error) = cdp_pipe.communicate()
    # print cdp_output
    return_code = cdp_pipe.returncode
    if return_code != 0:
        current_time = datetime.utcnow().isoformat()
        result = {
            'app': 'sms_status_collector',
            'timestamp': current_time,
            'error': 'command_return_code_error',
            'error-msg': cdp_error
        }
        return result

    cdp_output_lines = cdp_output.split('\n')

    status_lines = []
    for line in cdp_output_lines:
        if line.startswith('Welcome') or line.startswith('#') or line == '' or line.startswith('Goodbye'):
            # print "[ ] ", line
            pass
        else:
            status_lines.append(line)
            # print "[x] ", line

    first_line = re.compile(r"^/(\[|\{)([a-z]+)(\]|\}) *([a-zA-z0-9_]*) *(\[|\{)([a-z]+)(\]|\}) *")
    none_first_line = re.compile(r"^ *([a-zA-z0-9_]*) *(\[|\{)([a-z]+)(\]|\}) *")

    node_status_list = []
    for a_status_line in status_lines:
        m = first_line.match(a_status_line)
        if m is None:
            m2 = none_first_line.match(a_status_line)
            if m2 is None:
                if verbose:
                    print("LINE: ",a_status_line.split())
            else:
                g = m2.groups()
                node_name = g[0]
                node_path = "/{node_name}".format(sms_name=sms_name, node_name=node_name)
                node_status = g[2]
                node_status_list.append({
                    'name': node_name,
                    'path': node_path,
                    'status': node_status,
                    'node_type': 'suite'
                })
                if verbose:
                    print("  |-",g[2], g[0])

        else:
            g = m.groups()
            if verbose:
                print("/{sms_name}".format(sms_name=sms_name), g[1])
            node_name = sms_name
            node_path = "/"
            node_status = g[1]
            node_status_list.append({
                'name': node_name,
                'path': node_path,
                'status': node_status,
                'node_type': 'server'
            })

            if verbose:
                print("  |-",g[5], g[3])
            node_name = g[3]
            node_path = "/{node_name}".format(sms_name=sms_name, node_name=node_name)
            node_status = g[5]
            node_status_list.append({
                'name': node_name,
                'path': node_path,
                'status': node_status,
                'node_type': 'suite'
            })

    for a_node_status in node_status_list:
        if a_node_status['node_type'] == 'suite':
            # print 'suite:',a_node_status['path']
            variable_result = get_sms_variable(sms_name, sms_user, sms_password, a_node_status['path'])
            if 'error' in variable_result:
                continue
            else:
                a_node_status['variable'] = variable_result

    current_time = (datetime.utcnow() + timedelta(hours=8)).isoformat()  # 北京时间
    result = {
        'app': 'sms_status_collector',
        'type': 'sms_status',
        'timestamp': current_time,
        'data': {
            'sms_name': sms_name,
            'sms_user': sms_user,
            'time': current_time,
            'status': node_status_list
        }
    }
    return result


##############################
# get whole status
##############################

class Node(object):
    def __int__(self):
        self.parent = None
        self.children = list()
        self.name = ''
        self.status = 'unknown'

    def to_dict(self):
        ret = dict()
        ret['name'] = self.name
        ret['children'] = list()
        ret['status'] = self.status
        ret['path'] = self.get_node_path()
        for a_child in self.children:
            ret['children'].append(a_child.to_dict())
        return ret

    def add_child(self, node):
        self.children.append(node)

    def get_node_path(self):
        cur_node = self
        node_list = []
        while cur_node is not None:
            node_list.insert(0, cur_node.name)
            cur_node = cur_node.parent
        node_path = "/".join(node_list)
        if node_path == "":
            node_path = "/"
        return node_path


class Bunch(Node):
    def __init__(self):
        Node.__init__(self)
        self.parent = None
        self.children = list()
        self.name = ''
        self.status = 'unknown'

    def add_node_status(self, node_status_object):

        node_path = node_status_object['path']
        node_status = node_status_object['status']
        node_name = node_status_object['name']

        if node_path == '/':
            self.status = node_status
            return self

        node = None
        if node_path[0] != '/':
            return node

        node_path = node_path[1:]
        tokens = node_path.split("/")
        cur_node = self
        for a_token in tokens:
            t_node = None
            for a_child in cur_node.children:
                if a_child.name == a_token:
                    t_node = a_child
                    break
            if t_node is None:
                t_node = Node()
                t_node.parent = cur_node
                t_node.name = node_name
                t_node.status = node_status
                t_node.children = list()
                cur_node.add_child(t_node)
            cur_node = t_node
        return cur_node


class SmsStatusAnalyzer(object):
    def __init__(self):
        self.cur_level = 0
        self.cur_node_path = ''

        # level_mapper 结构示例：
        # { level_start_position: level_no }
        self.level_mapper = dict()
        self.level_mapper[0] = 0

        # node_status 结构示例：
        # {
        #   'path': '/obs_reg'
        #   'name': 'obs_reg'
        #   'status': 'com'
        # }
        self.node_status_list = []

    def analytic_tokens(self, line_start_pos, line_tokens):
        cur_pos = line_start_pos
        for i in range(0, len(line_tokens)-1, 4):
            node_name_part = line_tokens[i]
            blank_part_one = line_tokens[i + 1]
            status_part = line_tokens[i + 2]
            blank_part_two = line_tokens[i + 3]
            if cur_pos not in self.level_mapper:
                self.level_mapper[cur_pos] = self.cur_level
            else:
                level_no = self.level_mapper[cur_pos]
                self.cur_level = level_no
                cur_node_path_tokens = self.cur_node_path.split('/')
                new_node_path_tokens = cur_node_path_tokens[0: level_no+1]
                self.cur_node_path = '/'.join(new_node_path_tokens)
            self.cur_level += 1
            node_path = self.cur_node_path + '/' + node_name_part
            if self.cur_level == 1:
                node_type = 'suite'
            elif blank_part_one[-1] == '{':
                node_type = 'family'
            elif blank_part_one[-1] == '[':
                node_type = 'task'
            else:
                node_type = 'unknown'
            status_item = {
                'path': node_path,
                'name': node_name_part,
                'status': status_part,
                'node_type': node_type
            }
            self.node_status_list.append(status_item)
            self.cur_node_path = node_path
            cur_pos += len(node_name_part) + len(blank_part_one) + len(status_part) + len(blank_part_two)

    def analyse_node_status(self, contents):
        lines = contents.split('\n')
        lines_length = len(lines)
        cur_line_no = 0
        while cur_line_no < lines_length and not lines[cur_line_no].startswith('/'):
            cur_line_no += 1

        if cur_line_no == lines_length:
            # 没有获取的数据
            return None

        # 分析第一行，示例
        # /{act}   obs_reg         [que]   aob       [que]   00E      [com]   getgmf              {com}
        cur_line = lines[cur_line_no].rstrip(' ')
        first_level = {
            'path': '/',
            'name': '/',
            'status': cur_line[2:5],
            'node_type': 'server'
        }
        self.node_status_list.append(first_level)
        tokens = re.split('(\W+|\{[a-z]{3}\}|\[[a-z]{3}\])', cur_line)
        start_pos = len(tokens[0]) + len(tokens[1]) + len(tokens[2]) + len(tokens[3])
        self.analytic_tokens(start_pos, tokens[4:])
        cur_line_no += 1
        while not lines[cur_line_no].startswith("# "):
            cur_line = lines[cur_line_no].rstrip(' ')
            # 使用 re.split('( +)', cur_line) 无法处理如下的特殊情况
            # 特殊情况：make_aob_rens_oracle{com}
            tokens = re.split('(\W+|\{[a-z]{3}\}|\[[a-z]{3}\])', cur_line)
            if len(tokens) <= 5:
                cur_line_no += 1
                continue
            start_pos = len(tokens[0]) + len(tokens[1])
            self.analytic_tokens(start_pos, tokens[2:])
            cur_line_no += 1
        return self.node_status_list


def get_sms_whole_status(owner, repo, sms_name, sms_user, sms_password, verbose=False):
    command_string = "login {sms_name} {sms_user}  {sms_password};status -f;exit".format(
        sms_name=sms_name,
        sms_user=sms_user,
        sms_password=sms_password
    )
    echo_pipe = subprocess.Popen(
        ['echo', command_string],
        stdout=subprocess.PIPE,
        encoding='utf-8')
    cdp_pipe = subprocess.Popen(
        ['/cma/u/app/sms/bin/cdp'],
        stdin=echo_pipe.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding='utf-8')
    echo_pipe.stdout.close()
    (cdp_output, cdp_error) = cdp_pipe.communicate()
    # print cdp_output
    # TODO: not login error
    return_code = cdp_pipe.returncode
    if return_code != 0:
        current_time = datetime.utcnow().isoformat()
        result = {
            'app': 'sms_status_collector',
            'timestamp': current_time,
            'error': 'command_return_code_error',
            'data':{
                'message': cdp_error
            }
        }
        return result

    tool = SmsStatusAnalyzer()
    node_status_list = tool.analyse_node_status(cdp_output)
    if node_status_list is None:
        """
        SMS没有启动时，返回错误消息
            /-CDP> # ERR:RPC:nwpc_wangdp: RPC: 1832-016 Unknown host\n\n# ERR:SMS-CLIENT-LOGIN:Client creation failed for host nwpc_wangdp.\n
        """
        current_time = datetime.utcnow().isoformat()
        result = {
            'app': 'sms_status_collector',
            'timestamp': current_time,
            'error': 'cdp_cannot_get_satus',
            'data': {
                'message': cdp_error
            }
        }
        return result
    bunch = Bunch()
    for a_status in node_status_list:
        bunch.add_node_status(a_status)
    bunch_dict = bunch.to_dict()
    bunch_dict['name'] = sms_name

    current_time = (datetime.utcnow() + timedelta(hours=8)).isoformat() # 北京时间
    result = {
        'app': 'sms_status_collector',
        'type': 'sms_status',
        'timestamp': current_time,
        'data': {
            'owner': owner,
            'repo': repo,
            'sms_name': sms_name,
            'sms_user': sms_user,
            'time': current_time,
            'status': bunch_dict
        }
    }
    return result


def collect_handler(args):
    # BUG: There is a bug for os.path.dirname on the python 2.7 compiled by me on AIX.
    # config_file_path = os.path.dirname(__file__) + "/" + config_file_name
    config_file_path = "./conf/" + config_file_name

    if args.config:
        config_file_path = args.config
    get_config(config_file_path)

    sms_name = args.name
    sms_user = args.user
    sms_password = "1"
    if args.password:
        sms_password = args.password

    if args.owner:
        owner = args.owner
    else:
        owner = sms_user

    if args.repo:
        repo = args.repo
    else:
        repo = sms_name

    verbose = False
    if args.verbose:
        verbose = True

    print('Getting sms status for {owner}/{repo}'.format(owner=owner, repo=repo))
    result = get_sms_whole_status(owner, repo, sms_name, sms_user, sms_password, verbose)
    print('Getting sms status for {owner}/{repo}...Done'.format(owner=owner, repo=repo))

    post_data = {
        'message': json.dumps(result)
    }

    if verbose:
        if 'error' in result:
            print(result)
        else:
            print("""result:
    app: {app},
    type: {type},
    timestamp: {timestamp},
    data: ...
""".format(
                app=result['app'],
                type=result['type'],
                timestamp=result['timestamp']))

    if not args.disable_post:
        if verbose:
            print("Posting sms status for {owner}/{repo}...".format(owner=owner, repo=repo))
        host = SMS_STATUS_POST_HOST
        port = SMS_STATUS_POST_PORT
        url = SMS_STATUS_POST_URL.format(host=host, port=port)

        if 'content-encoding' in POST_HEADERS:
            content_encoding = POST_HEADERS['content-encoding']
        else:
            content_encoding = ''

        if content_encoding == 'gzip':
            gzipped_data = gzip.compress(bytes(json.dumps(post_data), 'utf-8'))

            requests.post(url, data=gzipped_data, headers={
                'content-encoding': 'gzip'
            })
        else:
            requests.post(url, data=post_data)

        if verbose:
            print("Posting sms status for {owner}/{repo}...done".format(owner=owner, repo=repo))


def show_handler(args):
    # BUG: There is a bug for os.path.dirname on the python 2.7 compiled by me on AIX.
    # config_file_path = os.path.dirname(__file__) + "/" + config_file_name
    config_file_path = "./conf/" + config_file_name

    if args.config:
        config_file_path = args.config
    get_config(config_file_path)

    sms_name = args.name
    sms_user = args.user
    sms_password = "1"
    if args.password:
        sms_password = args.password

    if args.owner:
        owner = args.owner
    else:
        owner = sms_user

    if args.repo:
        repo = args.repo
    else:
        repo = sms_name

    result = get_sms_whole_status(owner, repo, sms_name, sms_user, sms_password, verbose=False)
    print(json.dumps(result))
    return 0


def sms_status_command_line_tool():
    default_sms_password = "1"

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
DESCRIPTION
    Get sms suites' status.""")

    sub_parsers = parser.add_subparsers(title="sub commands", dest="sub_command")

    collect_parser = sub_parsers.add_parser('collect',description="collect sms status from sms server.")
    collect_parser.add_argument("-o", "--owner", help="owner name, default is same as sms server user name")
    collect_parser.add_argument("-r", "--repo", help="repo name, default is same as sms server name")
    collect_parser.add_argument("-n", "--name", help="sms server name", required=True)
    collect_parser.add_argument("-u", "--user", help="sms server user name", required=True)
    collect_parser.add_argument(
        "-p", "--password",
        help="sms server password, default is {default_sms_password}".format(
            default_sms_password=default_sms_password)
    )
    collect_parser.add_argument("--disable-post", help="disable post to agent.", action='store_true')
    collect_parser.add_argument("--verbose", help="show more outputs", action='store_true')
    collect_parser.add_argument("-c", "--config", help="config file, default config file is ./conf/{config_file_name}".format(
        config_file_name=config_file_name
    ))

    show_parser = sub_parsers.add_parser('show', description="show sms status information.")
    show_parser.add_argument("-o", "--owner", help="owner name, default is same as sms server user name")
    show_parser.add_argument("-r", "--repo", help="repo name, default is same as sms server name")
    show_parser.add_argument("-n", "--name", help="sms server name", required=True)
    show_parser.add_argument("-u", "--user", help="sms server user name", required=True)
    show_parser.add_argument(
        "-p", "--password",
        help="sms server password, default is {default_sms_password}".format(
            default_sms_password=default_sms_password)
    )
    show_parser.add_argument("--verbose", help="show more outputs", action='store_true')
    show_parser.add_argument("-c", "--config", help="config file, default config file is ./conf/{config_file_name}".format(
        config_file_name=config_file_name
    ))

    args = parser.parse_args()

    if args.sub_command == "collect":
        collect_handler(args)
    elif args.sub_command == "show":
        show_handler(args)

    return 0


if __name__ == "__main__":
    sms_status_command_line_tool()
