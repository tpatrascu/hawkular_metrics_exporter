#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import yaml, json
import argparse
import http.server
import socketserver
from hawkular.metrics import HawkularMetricsClient, MetricType


parser = argparse.ArgumentParser(description='Export hawkular pod metrics for specified tenants.')
parser.add_argument('-host', metavar='hostname', type=str, required=True, help='Hawkular Metrics enpoint hostname')
parser.add_argument('-port', metavar='port', default=8000, type=int, required=False, help='Port the exporter will listen on')
parser.add_argument('-tenants', metavar='tenant', type=str, required=True, nargs='+',
                   help='list of tenants')
parser.add_argument('-enable-metrics', metavar='metric', type=str, required=False, nargs='+',
                   help='list of metric descriptor names to include')
parser.add_argument('-disable-metrics', metavar='metric', type=str, required=False, nargs='+',
                   help='list of metric descriptor names to exclude')
args = parser.parse_args()


config = {}
with open('config.yaml') as f:
    config = yaml.load(f)

hawkular_client = HawkularMetricsClient(
    tenant_id='openshift-infra',
    scheme=config['hawkular_metrics_client']['scheme'],
    host=config['hawkular_metrics_client']['host'],
    port=config['hawkular_metrics_client']['port'],
    path=config['hawkular_metrics_client']['path'],
    token=config['hawkular_metrics_client']['token']
)


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        http_response = ''
        for tenant in args.tenants:
            hawkular_client.tenant(tenant)
            hawkular_resp = hawkular_client.query_metric_definitions()
            metric_definitions = [x for x in hawkular_resp
                                  if x['tags']['descriptor_name']
                                  in config['collect_metrics']]
            metrics_data = []
            for metric_definition in metric_definitions:
                hawkular_resp = hawkular_client.query_metric(
                    MetricType.Gauge, metric_definition['id'], limit=1)
                
                # parse labels and convert to prometheus format
                labels = {k: v for (k, v) in zip(
                            [x.split(':')[0] for x in metric_definition['tags']['labels'].split(',')],
                            [x.split(':')[1] for x in metric_definition['tags']['labels'].split(',')]
                         )}

                prometheus_labels = ''
                for k, v in labels.items():
                    prometheus_labels += '{}="{}",'.format(k, v)
                prometheus_labels = prometheus_labels[:-1]

                row = '{}{{pod_name="{}",descriptor_name="{}",namespace_name="{}",nodename="{}",{},}} {}\n'.format(
                    metric_definition['id'],
                    metric_definition['tags']['pod_name'],
                    metric_definition['tags']['descriptor_name'],
                    metric_definition['tags']['namespace_name'],
                    metric_definition['tags']['nodename'],
                    prometheus_labels,
                    hawkular_resp[0]['value'],
                )
            
                http_response += row

        # Construct a server response.
        self.send_response(200)
        self.end_headers()
        self.wfile.write(http_response.encode())


class MyServer(socketserver.TCPServer):
    allow_reuse_address = True

print('Server listening on port {}...'.format(args.port))
httpd = MyServer(('', args.port), Handler)
httpd.serve_forever()
