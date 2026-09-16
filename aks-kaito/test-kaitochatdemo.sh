
# !/bin/bash

# Describe the ingress to check its configuration
kubectl -n default describe ingress kaito-ingress | sed -n '1,120p'

INGRESS_IP=$(kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "INGRESS_IP: $INGRESS_IP"

echo "--- kaitochatdemo env ---"
kubectl -n default get deploy kaitochatdemo -o jsonpath='{range .spec.template.spec.containers[0].env[*]}{.name}={.value}{"\n"}{end}'

curl -i http://$INGRESS_IP/chat/

# Verify the kaitochatdemo service and endpoints
kubectl -n default get svc kaitochatdemo -o wide
kubectl -n default get endpoints kaitochatdemo -o wide

# Test connectivity to the kaitochatdemo service from within the cluster
kubectl -n default run -it --rm curl --image=curlimages/curl --restart=Never -- sh
# Inside the pod, run:
curl -i http://kaitochatdemo.default.svc.cluster.local/

# Check ingress controller pods status
kubectl -n ingress-nginx get pods -l app.kubernetes.io/component=controller
# View ingress controller logs for troubleshooting
kubectl -n ingress-nginx logs -l app.kubernetes.io/component=controller -f --tail=50

curl -i http://4.229.142.8/chat/