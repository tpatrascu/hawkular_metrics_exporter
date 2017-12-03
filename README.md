# Create secret for Hawkular Metrics endpoint trusted CA certificate

oc -n hawkular-exporter secrets new hawkular-exporter-cacert ca.pem=/var/lib/origin/openshift.local.config/master/ca.crt

# Install the template

oc process -f hawkular-exporter-openshift-tpl.yaml | oc -n hawkular-exporter apply -f -
# Add view permission to the service account on the projects you want to collect data from

oc -n openshift-infra policy add-role-to-user view system:serviceaccount:hawkular-exporter:hawkular-exporter