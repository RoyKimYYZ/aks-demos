export RESOURCE_GROUP="aks-solution"
export CLUSTER_NAME="rkaksdev"

# Check services in default namespace
kubectl get svc -n default 
# Check if it's already a static IP resource
# Get the location of the AKS cluster
LOCATION=$(az aks show -g $RESOURCE_GROUP -n $CLUSTER_NAME --query location -o tsv)
# Construct the managed resource group name
MANAGED_RG="MC_${RESOURCE_GROUP}_${CLUSTER_NAME}_${LOCATION}"
echo "Managed Resource Group: $MANAGED_RG"
# Check if there is already a static IP resource
az network public-ip list -g $MANAGED_RG -o table

helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-health-probe-request-path"=/healthz \
  --set-string controller.config.server-snippet="location = /healthz { return 200; }"

# Deploy the ingress resource for kaito workspace and ragengine and streamlit apps
kubectl apply -f ingress-nginx-kaito.yaml

# List all ingresses
kubectl get ingress -A

# Check ingress controller service (external IP)
kubectl get svc -n ingress-nginx -o wide
kubectl get ingress kaito-ingress -n default -o wide
kubectl describe ingress kaito-ingress -n default | head -40

kubectl get svc -n ingress-nginx
INGRESS_IP=$(kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "INGRESS_IP: $INGRESS_IP"

# Sanity check: ingress-nginx itself serves an always-200 endpoint for the Azure LB probe
curl -sS -o /dev/null -w "healthz status: %{http_code}\n" "http://$INGRESS_IP/healthz"



# Test endpoint via ingress after setting up nginx ingress controller
# Ingress endpoint (single public IP)
INGRESS_IP=$(kubectl get ingress kaito-ingress -n default -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "INGRESS_IP=$INGRESS_IP"

# Test Workspace inference via ingress (/phi4 routes to workspace-phi-4-mini)
curl -sS "http://$INGRESS_IP/phi4/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "phi-4-mini-instruct",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "What are income tax brackets for Ontario residents in 2024?"}
    ],
    "temperature": 0.2,
    "max_tokens": 1024
  }' | jq -C '.choices[0].message.content'
