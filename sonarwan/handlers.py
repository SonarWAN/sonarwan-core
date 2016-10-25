from models import Device, DeviceLess, AuthorlessService, ServiceLess
from constants import Transport

import random
import streams


def is_dns_response(pkg):
    return hasattr(pkg.dns, 'a')


def is_request(pkg):
    return hasattr(pkg.http, 'request')


def get_dns_answers(pkg):
    ret = []
    for field_line in pkg.dns._get_all_field_lines():
        if ':' in field_line:
            field_name, field_line = field_line.split(':', 1)
            if (field_name.strip() == 'Address'):
                ret.append(field_line.strip())
    return ret


def is_client_hello(pkg):
    return (hasattr(pkg.ssl, 'record') and
            pkg.ssl.record.split(': ')[-1] == 'Client Hello')


def create_stream_dict(pkg):
    transport_pkg = pkg.udp if hasattr(pkg, 'udp') else pkg.tcp
    return {
        'ip_src': pkg.ip.src,
        'ip_dst': pkg.ip.dst,
        'port_src': transport_pkg.srcport,
        'port_dst': transport_pkg.dstport
    }


def get_cipher_suite(pkg):
    l = pkg.ssl._get_all_fields_with_alternates()
    cipher_suite = [x for x in l if x.name == 'ssl.handshake.ciphersuite']
    return list(map(lambda x: (x.raw_value, x.showname_value), cipher_suite))


class Handler(object):
    def __init__(self, environment):
        self.environment = environment


class DNSHandler(Handler):
    def process(self, pkg):
        if self.needs_processing(pkg):
            answers = get_dns_answers(pkg)
            for each in answers:
                self.environment.address_host[each] = pkg.dns.qry_name

    def needs_processing(self, pkg):
        return is_dns_response(pkg)


class TCPHandler(Handler):
    def process(self, pkg):

        if self.needs_processing(pkg):
            self.process_new_stream(pkg)
        else:
            self.process_existing_stream(pkg)

    def process_existing_stream(self, pkg):

        if self.environment.has_service_from_stream(pkg):
            service = self.environment.locate_service(pkg)
            service.add_activity(pkg.sniff_time, pkg.length)

        if self.environment.has_device_from_stream(pkg):
            device, stream = self.environment.locate_device(pkg)
            device.add_activity(pkg.sniff_time, pkg.length)
            service = device.stream_to_service.get(stream.number)
            if service:
                service.add_activity(pkg.sniff_time, pkg.length)

        elif self.environment.has_temporal_stream(pkg):
            self.environment.temporal_stream_map[Transport.TCP][
                pkg.tcp.stream].append((pkg.sniff_time, pkg.length))

    def process_service(self, service_name, pkg, stream):
        service = self.environment.get_existing_authorless_service(
            service_name)
        if not service:
            service = AuthorlessService()
            service.characteristics['name'] = service_name
            self.environment.authorless_services.append(service)

        service.add_activity(pkg.sniff_time, pkg.length)

        service.add_stream(stream)

        self.environment.service_stream_map[Transport.TCP][
            pkg.tcp.stream] = service

    def process_new_stream(self, pkg):
        stream = streams.TCPStream(pkg.tcp.stream, **create_stream_dict(pkg))

        service_name = self.environment.ip_analyzer.find_service(pkg.ip.dst)
        host = self.environment.find_host(pkg.ip.dst)

        if service_name:
            self.process_service(service_name, pkg, stream)
        elif host:
            self.process_service(host, pkg, stream)
        else:
            self.environment.temporal_stream_map[Transport.TCP][
                pkg.tcp.stream] = [(pkg.sniff_time, pkg.length)]

    def needs_processing(self, pkg):
        return not self.environment.previously_analized_stream(pkg)


class HTTPHandler(Handler):
    def process(self, pkg):

        self.remove_unnecessary_services(pkg)

        t = self.environment.locate_device(pkg)
        if t:
            device, stream = t[0], t[1]
            self.process_existing_stream(pkg, device, stream)
        else:
            if is_request(pkg):
                self.process_new_stream(pkg)

    def remove_unnecessary_services(self, pkg):
        if self.environment.has_service_from_stream(pkg):
            service = self.environment.locate_service(pkg)
            self.environment.authorless_services.remove(service)

            d_copy = dict(self.environment.service_stream_map[Transport.TCP])
            for k, v in self.environment.service_stream_map[
                    Transport.TCP].items():
                if v == service:
                    del d_copy[k]
            self.environment.service_stream_map[Transport.TCP] = d_copy

    def process_existing_stream(self, pkg, device, stream):
        if hasattr(pkg.http, 'user_agent'):
            user_agent = pkg.http.user_agent
            self.analyze_user_agent(user_agent, stream, pkg, device)
        else:
            device.add_activity(pkg.sniff_time, pkg.length)
            service = device.stream_to_service.get(stream.number)
            if service:
                service.add_activity(pkg.sniff_time, pkg.length)

    def process_new_stream(self, pkg):
        stream = streams.HTTPStream(pkg.tcp.stream, **create_stream_dict(pkg))

        if hasattr(pkg.http, 'user_agent'):
            user_agent = pkg.http.user_agent
            self.analyze_user_agent(user_agent, stream, pkg)

    def analyze_user_agent(self, user_agent, stream, pkg, device_param=None):

        matchers = self.environment.ua_analyzer.get_best_match(user_agent)

        device_args = matchers.get('device_args')
        app_args = matchers.get('app_args')

        if device_args or app_args:

            if not device_param:
                device = self.create_or_update_device(device_args, app_args,
                                                      pkg, stream)
                device.streams.append(stream)
                self.environment.device_stream_map[Transport.TCP][
                    stream.number] = (device, stream)

            else:
                device_param.update(device_args, app_args,
                                    [(pkg.sniff_time, pkg.length)], stream)

    def create_or_update_device(self, device_args, app_args, pkg, stream):
        devices = []
        max_score = 0
        for d in self.environment.devices:
            score = d.match_score(device_args, app_args)
            if max_score > 0 and score == max_score:
                devices.append(d)
            elif score > max_score:
                max_score, devices = score, [d]

        if devices:
            device = random.choice(devices)
        else:
            device = self.environment.create_device()

        tuple_list = [(pkg.sniff_time, pkg.length)]
        if self.environment.has_temporal_stream(pkg):
            for each in self.environment.locate_temporal(pkg):
                tuple_list.append((each[0], each[1]))

        device.update(device_args, app_args, tuple_list, stream)

        return device
