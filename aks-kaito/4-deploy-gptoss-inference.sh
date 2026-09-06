
# Deploy ingress for GPT-OSS Workspace
kubectl apply -f kaito_workspace_gpt_oss_20b.yaml

#optional: kubectl delete -f kaito_workspace_gpt_oss_20b.yaml

# Check ingress rules only
kubectl get ingress gptoss-ingress -n default -o jsonpath='{.spec.rules}' | jq .

# Test endpoints via ingress
INGRESS_IP="${INGRESS_IP:-$(kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}')}"
if [ -z "$INGRESS_IP" ]; then
  echo "ERROR: INGRESS_IP is empty. Is ingress-nginx installed and has an external IP?" >&2
  kubectl get svc -n ingress-nginx -o wide >&2 || true
  exit 1
fi
export INGRESS_IP
echo "INGRESS_IP=$INGRESS_IP"

kubectl apply -f ingress-gptoss.yaml

# Test Workspace inference via ingress
curl -sS "http://$INGRESS_IP/gptoss/v1/chat/complet
