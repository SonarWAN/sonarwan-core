import paths
import errors
import re
import csv
import ipaddress
import yaml

from os import listdir
from os.path import isfile, join

from ua_parser import user_agent_parser

from tools.mobile_detector import MobileDetector

from models import Service


class InferenceEngine(object):
    def __init__(self, user_inference_directory):
        self.load_inference_files(user_inference_directory)

    def load_inference_files(self, user_inference_directory):
        self.inference_list = []
        self.load_files(paths.INFERENCE_DIR)

        if user_inference_directory:
            self.load_files(user_inference_directory)

    def load_files(self, path):
        try:
            onlycsv = [f for f in listdir(path) if isfile(join(path, f))]
            onlycsv = filter(lambda x: x[-4:] == '.csv', onlycsv)
            onlycsv = map(lambda x: path + x, onlycsv)
            for each in onlycsv:
                with open(each) as f:
                    csvreader = csv.DictReader(f, delimiter=";")
                    self.inference_list.extend(list(csvreader))

        except FileNotFoundError:
            raise errors.InferenceDirectoryNotFoundError()

        except Exception:
            raise errors.InvalidCSVInferenceFile()

    def analyze_inference(self, characteristics):
        candidates = [
            InferenceEngine.useful_data(characteristics, x)
            for x in self.inference_list
            if InferenceEngine.match_characteristic(characteristics, x)
        ]
        non_deterministic = set()
        ret = {}
        for each in candidates:
            for k, v in each.items():
                if k in ret.keys():
                    common = InferenceEngine.common_initial_substring(v,
                                                                      ret[k])
                    if common:
                        ret[k] = common
                    else:
                        non_deterministic.add(k)
                else:
                    ret[k] = v
        for each in non_deterministic:
            del ret[each]

        return ret

    def common_initial_substring(s1, s2):
        min_len = min(len(s1), len(s2))
        ret = ''
        for i in range(min_len):
            if s1[i].upper() != s2[i].upper():
                return ret
            else:
                ret += s1[i]
        return ret

    def useful_data(characteristics, base):
        return {
            k: v
            for k, v in base.items() if k not in (characteristics.keys())
        }

    def match_characteristic(characteristics, base):
        common = set(characteristics.keys()).intersection(set(base.keys()))
        if not common:
            return False

        for c in common:
            if characteristics[c] != base[c]:
                return False

        return True


class ComplementaryUAAnalyzers(object):
    def __init__(self):
        self.mobile_detector = MobileDetector()

    def get_additional_data(self, user_agent, device_args, app_args):
        self.run_ua_parser(user_agent, device_args, app_args)
        self.run_mobile_detector(user_agent, device_args, app_args)

    def run_ua_parser(self, user_agent, device_args, app_args):
        parsed_string = user_agent_parser.Parse(user_agent)

        os_family = None

        if parsed_string.get('device'):
            brand = parsed_string.get('device').get('brand')

            if brand and ComplementaryUAAnalyzers.has_useful_data(
                    brand) and 'brand' not in device_args:
                device_args['brand'] = brand

        if parsed_string.get('os'):
            os_family = parsed_string.get('os').get('family')

            if os_family and ComplementaryUAAnalyzers.has_useful_data(
                    os_family) and 'os_family' not in device_args:
                device_args['os_family'] = os_family

        if 'os_version' not in device_args and parsed_string.get('os'):
            version = ComplementaryUAAnalyzers.get_version_from_ua_parser(
                parsed_string['os'])

            if version:
                device_args['os_version'] = version

        if parsed_string.get('user_agent'):
            agent = parsed_string.get('user_agent').get('family')

            # Most times os_family is the same as agent (example: Android)
            # Only add service if is not the same as os

            if os_family and agent and os_family != agent and not app_args:
                app_args['name'] = agent
                version = ComplementaryUAAnalyzers.get_version_from_ua_parser(
                    parsed_string['user_agent'])

                if version:
                    app_args['version'] = version

    def has_useful_data(data):
        return data != 'Other' and data != 'Generic'

    def get_version_from_ua_parser(ua_parser_os):
        ret = ''

        major = ua_parser_os.get('major')
        if major:
            ret += major
        else:
            return ret
        minor = ua_parser_os.get('minor')
        if minor:
            ret += '.' + minor
        else:
            return ret
        patch = ua_parser_os.get('patch')
        if patch:
            ret += '.' + patch
        else:
            return ret
        patch_minor = ua_parser_os.get('patch_minor')
        if patch_minor:
            ret += '.' + patch_minor
        else:
            return ret

        return ret

    def run_mobile_detector(self, user_agent, device_args, app_args):
        response = self.mobile_detector.parse(user_agent)
        if response.get('model') and 'model' not in device_args:
            device_args['model'] = response['model']
        if response.get('os_family') and 'os_family' not in device_args:
            device_args['os_family'] = response['os_family']
        if response.get('app_name') and 'name' not in app_args:
            app_args['name'] = response['app_name']


class UserAgentAnalyzer(object):
    def __init__(self, user_patterns_file):
        self.load_pattern_files(user_patterns_file)
        self.load_linux_distributions_file()
        self.complement = ComplementaryUAAnalyzers()

    def load_linux_distributions_file(self):
        self.linux_distributions = []
        try:
            with open(paths.LINUX_DISTRIBUTION_FILE) as f:
                for each in f.read().splitlines():
                    if each and each[0] != '#':
                        self.linux_distributions.append(each.lower())

        except:
            raise errors.LinuxDistributionListError()

    def load_pattern_files(self, user_patterns_file):
        self.user_agents = []
        self.load_file(paths.USER_AGENT_PATTERNS_FILE)

        if user_patterns_file:
            self.load_file(user_patterns_file)

    def load_file(self, path):
        try:
            with open(path) as f:
                for each in f.read().splitlines():
                    if each and each[0] != '#':
                        self.user_agents.append(each)

        except:
            raise errors.PatternFileNotFileError()

    def get_best_match(self, user_agent):
        max_size = -1
        best_match = None
        for pattern in self.user_agents:
            match = re.match(pattern, user_agent)
            if match:
                groups = match.groupdict()
                if (len(groups) > max_size):
                    max_size = len(groups)
                    best_match = groups

        device_args, app_args = {}, {}
        if best_match:
            for k in best_match:
                if best_match[k]:
                    if k.startswith('APP_'):
                        app_args[k[4:]] = best_match[k]
                    elif k.startswith('DEV_'):
                        device_args[k[4:]] = best_match[k]

        self.complement.get_additional_data(user_agent, device_args, app_args)

        if device_args.get('os_family') and device_args['os_family'].lower(
        ) in self.linux_distributions:
            device_args['os_distribution'] = device_args['os_family']
            device_args['os_family'] = 'Linux'

        device_args = {
            k: v.replace('%20', ' ')
            for k, v in device_args.items()
        }
        app_args = {k: v.replace('%20', ' ') for k, v in app_args.items()}

        for k, v in device_args.items():
            other = '.' if 'version' in k or 'kit' in k else ' ' 
            device_args[k] = "".join([ c if c.isalnum() else other for c in v ])

        for k, v in app_args.items():
            other = '.' if 'version' in k or 'kit' in k else ' ' 
            app_args[k] = "".join([ c if c.isalnum() else other for c in v ])


        return {'device_args': device_args, 'app_args': app_args}


class ServiceAnalyzer(object):
    def __init__(self, user_services_directory):

        self.service_info_map = {}

        self.url_analyzer = URLAnalyzer()
        self.ip_analyzer = IPAnalyzer()

        self.load_files(paths.SERVICES_DIRECTORY_PATH)

        if user_services_directory:
            self.load_files(user_services_directory)

    def load_service(self, content, full_path):
        try:
            name = content['name']

            self.service_info_map[name] = {
                k: v
                for k, v in content.items()
                if k not in ['urls', 'ips', 'absolute-urls']
            }

            if content.get('absolute-urls'):
                self.url_analyzer.absolute_service_map[name] = set(content[
                    'absolute-urls'])

            if content.get('urls'):
                self.url_analyzer.service_map[name] = set(content['urls'])

            if content.get('ips'):
                self.ip_analyzer.service_map[name] = set()
                for each in content['ips']:
                    self.ip_analyzer.service_map[name].add(
                        ipaddress.ip_network(each))

        except TypeError:
            raise errors.InvalidYAMLServiceFile(full_path)

    def load_files(self, path):
        try:
            files = [f for f in listdir(path) if isfile(join(path, f))]
            files = filter(lambda x: x[-5:] == '.yaml', files)

            for each in files:
                full_path = path + each
                with open(full_path) as f:
                    content = yaml.load(f)

                if type(content) is list:
                    for each in content:
                        self.load_service(each, full_path)
                else:
                    self.load_service(content, full_path)

        except FileNotFoundError:
            raise errors.ServiceDirectoryNotFoundError()
        except errors.InvalidYAMLServiceFile:
            raise
        except Exception:
            raise

    def find_service_from_ip(self, ipaddr):
        return self._generic_find(ipaddr, self.ip_analyzer.find_service)

    def find_service_from_absolute_url(self, url):
        return self._generic_find(url, self.url_analyzer.absolute_find_service)

    def find_service_from_url(self, url):
        return self._generic_find(url,
                                  self.url_analyzer.intensive_find_service)

    def _generic_find(self, parameter, function):
        name = function(parameter)
        if name:
            return Service.from_characteristics(self.service_info_map[name])
        return None


class URLAnalyzer(object):
    def __init__(self):
        self.service_map = {}
        self.absolute_service_map = {}

        self.not_found_cache = set()
        self.found_cache = {}

    def absolute_find_service(self, url):
        if url in self.not_found_cache:
            return None

        name = self.found_cache.get(url)
        if name:
            return name
        else:
            for k, v in self.absolute_service_map.items():
                if url in v:
                    self.found_cache[url] = k
                    return k

            self.not_found_cache.add(url)
            return None

    def intensive_find_service(self, url):
        for k, v in self.service_map.items():
            for each in v:
                dif = len(url) - len(each)
                if dif < 0:
                    continue
                match = True
                for i in range(len(each) - 1, -1, -1):
                    if each[i] != url[i + dif]:
                        match = False
                if match:
                    return k
        return None


class IPAnalyzer(object):
    def __init__(self):
        self.service_map = {}

        self.not_found_cache = set()
        self.found_cache = {}

    def find_service(self, ipaddr):
        if ipaddr in self.not_found_cache:
            return None

        name = self.found_cache.get(ipaddr)
        if name:
            return name
        else:
            for k, v in self.service_map.items():
                for each in v:
                    if ipaddress.ip_address(ipaddr) in each:
                        self.found_cache[ipaddr] = k
                        return k

            self.not_found_cache.add(ipaddr)
            return None
