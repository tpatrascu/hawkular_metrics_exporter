#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml
import os
import time
from collections import OrderedDict

from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY

from hawkular.metrics import HawkularMetricsClient, MetricType

import concurrent.futures
from collections import deque


hawkular_hostname = os.environ['HAWKULAR_HOSTNAME']

with open('/etc/config.yaml') as f:
    config = yaml.load(f)
with open('/var/run/secrets/kubernetes.io/serviceaccount/token') as f:
    sa_token = f.read()


def hawkular_client(tenant_id='default'):
    return HawkularMetricsClient(
        tenant_id=tenant_id,
        scheme=config['hawkular_client']['scheme'],
        host=hawkular_hostname,
        port=config['hawkular_client']['port'],
        path=config['hawkular_client']['path'],
        token=sa_token)

def ensure_prometheus_format(prometheus_name):
    """ Remove invalid characters from prometheus metric and label names """
    # TODO replace all characters that don't conform to
    # metrics names: [a-zA-Z_:]([a-zA-Z0-9_:])*
    # labels: [a-zA-Z_]([a-zA-Z0-9_])*
    return prometheus_name.replace('/', '_').replace('-', '_').replace('.', '_')

def get_metric_definitions(tenant_id):
    hawkular_resp = hawkular_client(tenant_id).query_metric_definitions()
    metric_definitions = [x for x in hawkular_resp
                          if x['tags']['type'] == 'pod'
                          and x['tags']['descriptor_name'] in config['collect_metrics']]
    return metric_definitions


def get_metric_data(metric_definition):
    hawkular_resp = hawkular_client(metric_definition['tags']['namespace_name']).query_metric(
        MetricType.Gauge, metric_definition['id'], limit=1)
        
    # parse hawkular labels
    try:
        metric_definition_labels = metric_definition['tags']['labels'].split(',')
        metric_meta_labels = OrderedDict((k, v) for (k, v) in zip(
                [x.split(':')[0] for x in metric_definition_labels],
                [x.split(':')[1] for x in metric_definition_labels]))
    except IndexError:
        metric_meta_labels = {}

    prometheus_metric_name = metric_definition['tags']['descriptor_name']
    if metric_definition['tags']['descriptor_name'] in config['metric_units']:
        prometheus_metric_name = '{}_{}'.format(
            metric_definition['tags']['descriptor_name'],
            config['metric_units'][metric_definition['tags']['descriptor_name']]
        )

    default_labels = OrderedDict([
        ('pod_name', metric_definition['tags']['pod_name']),
        ('namespace_name', metric_definition['tags']['namespace_name']),
        ('nodename', metric_definition['tags']['nodename']),
    ])

    metric_family = GaugeMetricFamily(
        config['prometheus_client']['namespace'] + ensure_prometheus_format(prometheus_metric_name),
        '',
        labels=list(default_metric_labels.keys()) + list(metric_meta_labels.keys())
    )
    metric_family.add_metric(
        list(default_metric_labels.values()) + list(metric_meta_labels.values()), hawkular_resp[0]['value'])
    return metric_family


class CAdvisorCollector(object):
    def collect(self):
        metric_definitions_queue = deque()

        with concurrent.futures.ThreadPoolExecutor(max_workers=config['hawkular_client']['concurrency']) as executor:
            # get metric definitions in parallel
            future_to_metric_definitions = {executor.submit(get_metric_definitions, tenant_id):
                tenant_id for tenant_id in config['projects']
            }
            for future in concurrent.futures.as_completed(future_to_metric_definitions):
                tenant_name = future_to_metric_definitions[future]
                try:
                    data = future.result()
                except Exception as exc:
                    if config['debug']:
                        print('Error getting metrics definitions for tenant_name %r: %s' % (tenant_name, exc))
                    response_code = 500
                else:
                    for item in data:
                        metric_definitions_queue.append(item)

            # get metric data in parallel
            if config['debug']:
                print("Getting data for metric definitions: {}", list(metric_definitions_queue))
            future_to_metric_data = {executor.submit(get_metric_data, metric_definition):
                metric_definition for metric_definition in list(metric_definitions_queue)
            }
            for future in concurrent.futures.as_completed(future_to_metric_data):
                metric_definition_name = future_to_metric_data[future]['id']
                try:
                    metric = future.result()
                except Exception as exc:
                    if config['debug']:
                        print('Error getting metrics for %r: %s' % (metric_definition_name, exc))
                    response_code = 500
                else:
                    yield metric


if __name__ == "__main__":
    start_http_server(config['prometheus_client']['port'])
    print('Listening on port {}'.format(config['prometheus_client']['port']))
    REGISTRY.register(CAdvisorCollector())
    while True: time.sleep(1)
