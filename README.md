# Hawkular Metrics Prometheus exporter

## Description

Authenticates to Hawkular Metrics using a service account and grabs metrics for tenants specified in it's ConfigMap.
Set ''debug: True'' in the ConfigMap to see if there are any errors, by default no errors are logged.

## Install instructions

1. Create secret for Hawkular Metrics endpoint trusted CA certificate
```
oc -n hawkular-exporter secrets new hawkular-exporter-cacert ca.pem=/var/lib/origin/openshift.local.config/master/ca.crt
```

2. Install the template
```
oc process -f hawkular-exporter-openshift-tpl.yaml | oc -n hawkular-exporter apply -f -
```

3. Add view permission to the service account on the projects you want to collect data from
```
oc -n myproject policy add-role-to-user view system:serviceaccount:myproject:hawkular-exporter
```
