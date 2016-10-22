import csv
import random


def similarity(base, k, v):
    if k in base:
        compare_value = base[k]
        length = min(len(compare_value), len(v))
        count = 0

        for i in range(length):
            if (not compare_value[i].isalnum() and not v[i].isalnum()
                ) or compare_value[i].upper() == v[i].upper():
                count += 1
            else:
                return -1
        return count / max(len(compare_value), len(v))
    return 0


class Service(object):
    def __init__(self):
        self.activity = {}
        self.characteristics = {}
        self.streams = []

    def update_service(self, app_args, stream):
        for k in app_args:
            current_value = self.characteristics.get(k)
            new_value = app_args.get(k)

            if (not current_value) or (new_value and
                                       len(new_value) > len(current_value)):
                self.characteristics[k] = new_value

        self.add_stream(stream)

    def add_stream(self, stream):
        if stream not in self.streams:
            self.streams.append(stream)

    def add_activity(self, time, bytes_count):
        time_string = time.strftime('%D %H:%M:%S')
        self.activity[time_string] = self.activity.get(time_string,
                                                       0) + int(bytes_count)

    def add_all_activity(self, tuple_list):
        for each in tuple_list:
            self.add_activity(each[0], each[1])


class AuthorlessService(Service):
    pass


class Device(object):
    def __init__(self, inference_engine):
        self.streams = []  # List of Streams
        self.services = []  # List of characteristics
        self.characteristics = {}
        self.activity = {}

        self.inference_engine = inference_engine

    def add_activity(self, time, bytes_count):
        time_string = time.strftime('%D %H:%M:%S')
        self.activity[time_string] = self.activity.get(time_string,
                                                       0) + int(bytes_count)

    def add_all_activity(self, tuple_list):
        for each in tuple_list:
            self.add_activity(each[0], each[1])

    def match_score(self, device_args, app_args):
        score = 0

        for k, v in device_args.items():
            sim = similarity(self.characteristics, k, v)
            if sim == -1:
                return -1
            score += sim

        for service in self.services:
            for k, v in app_args.items():
                sim = similarity(service.characteristics, k, v)
                if sim != -1:
                    score += sim

        return score

    def update(self, device_args, app_args, tuple_list, stream):
        # Tuple list contains (time, bytes)

        # Device
        self.update_device(device_args)
        self.add_all_activity(tuple_list)

        #Service
        service = self.update_services(app_args, stream)
        service.add_all_activity(tuple_list)

    def update_services(self, app_args, stream):
        services = []
        max_score = float('-inf')

        for service in self.services:
            score = 0
            incompatible = False
            for k, v in app_args.items():
                sim = similarity(service.characteristics, k, v)
                if sim == -1:
                    incompatible = True
                    break
                else:
                    score += sim
            if not incompatible:
                if score > 0:
                    if score == max_score:
                        services.append(service)
                    elif score > max_score:
                        max_score, services = score, [service]
        service = None
        if services:
            service = random.choice(services)
        elif app_args:
            service = Service()
            self.services.append(service)

        if service:
            service.update_service(app_args, stream)
            return service

    def update_device(self, device_args):
        for k in device_args:
            current_value = self.characteristics.get(k)
            new_value = device_args.get(k)

            if (not current_value) or (new_value and
                                       len(new_value) > len(current_value)):
                self.characteristics[k] = new_value

        inferences = self.inference_engine.analyze_inference(
            self.characteristics)
        if inferences:
            self.characteristics.update(inferences)


class DeviceLess():
    def __init__(self, services, characteristics, activity):
        self.services = services
        self.characteristics = characteristics
        self.activity = activity


class ServiceLess():
    def __init__(self, characteristics, activity):
        self.characteristics = characteristics
        self.activity = activity
