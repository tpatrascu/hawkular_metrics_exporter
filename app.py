#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml, json
import os
import http.server
import socketserver
import concurrent.futures
from collections import deque
from hawkular.metrics import HawkularMetricsClient, MetricType


hawkular_hostname = os.environ['HAWKULAR_HOSTNAME']

with open('/etc/config.yaml') as f:
    config = yaml.load(f)
with open('/var/run/secrets/kubernetes.io/serviceaccount/token') as f:
    sa_token = f.read()


def hawkular_client(tenant_id=''):
    return HawkularMetricsClient(
        tenant_id=tenant_id,
        scheme=config['hawkular_client']['scheme'],
        host=hawkular_hostname,
        port=config['hawkular_client']['port'],
        path=config['hawkular_client']['path'],
        token=sa_token)


def get_metric_definitions(tenant_id):
    hawkular_resp = hawkular_client(tenant_id).query_metric_definitions()
    metric_definitions = [x for x in hawkular_resp
                          if x['tags']['type'] == 'pod'
                          and x['tags']['descriptor_name'] in config['collect_metrics']]
    return metric_definitions


def get_metric_data(metric_definition):
    hawkular_resp = hawkular_client(metric_definition['tags']['namespace_name']).query_metric(
        MetricType.Gauge, metric_definition['id'], limit=1)
        
    # parse hawkular labels and convert to prometheus format
    try:
        metric_definition_labels = metric_definition['tags']['labels'].split(',')
        labels = {k: v for (k, v) in zip(
                [x.split(':')[0] for x in metric_definition_labels],
                [x.split(':')[1] for x in metric_definition_labels])}

        prometheus_labels = ''
        for k, v in labels.items():
            prometheus_labels += '{}="{}",'.format(k, v)
        prometheus_labels = ',{},'.format(prometheus_labels[:-1])
    except IndexError:
        prometheus_labels = ''

    row = '{}{{pod_name="{}",namespace_name="{}",nodename="{}"{}}} {}\n'.format(
        metric_definition['tags']['descriptor_name'],
        metric_definition['tags']['pod_name'],
        metric_definition['tags']['namespace_name'],
        metric_definition['tags']['nodename'],
        prometheus_labels,
        hawkular_resp[0]['value'],
    )

    return row


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        response_code = 200

        tenant_ids = [x['id'] for x in hawkular_client().query_tenants()]
        if config['debug']:
            print("Scraping tenants: {}", tenant_ids)

        metric_definitions_queue = deque()
        metric_data_queue = deque()

        with concurrent.futures.ThreadPoolExecutor(max_workers=config['hawkular_client']['concurrency']) as executor:
            # get metric definitions in parallel
            future_to_metric_definitions = {executor.submit(get_metric_definitions, tenant_id):
                tenant_id for tenant_id in tenant_ids
            }
            for future in concurrent.futures.as_completed(future_to_metric_definitions):
                tenant_name = future_to_metric_definitions[future]
                try:
                    data = future.result()
                except Exception as exc:
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
                    data = future.result()
                except Exception as exc:
                    print('Error getting metrics for %r: %s' % (metric_definition_name, exc))
                    response_code = 500
                else:
                    metric_data_queue.append(data)

        http_response = ''.join(list(metric_data_queue))
        self.send_response(response_code)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.end_headers()
        self.wfile.write(http_response.encode())


class MyServer(socketserver.TCPServer):
    allow_reuse_address = True

print('Server listening on port {}...'.format(config['http_server']['port']))
httpd = MyServer(('', config['http_server']['port']), Handler)
httpd.serve_forever()
