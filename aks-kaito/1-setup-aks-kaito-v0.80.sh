export RESOURCE_GROUP="aks-solution"
export CLUSTER_NAME="rkaksdev"
export LOCATION="canadacentral"

az login --use-device-code
az account set --subscription "Applications"
export AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)

# Create AKS Cluster
az group create --name $RESOURCE_GROUP --location $LOCATION
az aks create --resource-group $RESOURCE_GROUP --name $CLUSTER_NAME --node-count 1 \
  --enable-oidc-issuer --enable-workload-identity --enable-managed-identity 

# Get AKS credentials to login to the cluster
az aks get-credentials --resource-group $RESOURCE_GROUP --name $CLUSTER_NAME

# Verify cluster nodes
kubectl get nodes -o wide

# Install KAITO Workspace Controller
helm repo add kaito https://kaito-project.github.io/kaito/charts/kaito
helm repo update
helm upgrade --install kaito-workspace kaito/workspace \
  --namespace kaito-workspace \
  --create-namespace \
  --set clusterName="$CLUSTER_NAME" \
  --wait

# Verify installation
helm list -n kaito-workspace
kubectl get pods -n kaito-workspace
kubectl describe deploy kaito-workspace -n kaito-workspace

kubectl get nodes -l accelerator=nvidia # no nodes yet


# https://kaito-project.github.io/kaito/docs/azure#setup-auto-provisioning

##################################################################################
# Create Managed Identity for the GPU provisioner with the necessary permissions #
##################################################################################
export SUBSCRIPTION=$(az account show --query id -o tsv)
echo "Subscription ID: $SUBSCRIPTION"
export IDENTITY_NAME="kaitoprovisioner"
echo "Creating Managed Identity: $IDENTITY_NAME"
az identity create --name $IDENTITY_NAME -g $RESOURCE_GROUP

# Get the principal ID for role assignment
export IDENTITY_PRINCIPAL_ID=$(az identity show --name $IDENTITY_NAME -g $RESOURCE_GROUP --subscription $SUBSCRIPTION --query 'principalId' -o tsv)
echo "Managed Identity Principal ID: $IDENTITY_PRINCIPAL_ID"

# Assign Contributor role to the cluster
az role assignment create \
  --assignee $IDENTITY_PRINCIPAL_ID \
  --scope /subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ContainerService/managedClusters/$CLUSTER_NAME \
  --role "Contributor"

# verify role assignment
az role assignment list --assignee $IDENTITY_PRINCIPAL_ID --scope /subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ContainerService/managedClusters/$CLUSTER_NAME

##############################
# Install GPU Provisioner  #
##############################
export GPU_PROVISIONER_VERSION=0.3.8
# Download and configure Helm values
curl -sO https://raw.githubusercontent.com/Azure/gpu-provisioner/main/hack/deploy/configure-helm-values.sh
# This will create/update gpu-provisioner-values.yaml in order to customize the gpu provisioner installation
chmod +x ./configure-helm-values.sh && ./configure-helm-values.sh $CLUSTER_NAME $RESOURCE_GROUP $IDENTITY_NAME

# Install GPU provisioner
# Ensure values in gpu-provisioner-values.yaml are correct before proceeding
helm install gpu-provisioner \
  --values gpu-provisioner-values.yaml \
  --set settings.azure.clusterName=$CLUSTER_NAME \
  --wait \
  https://github.com/Azure/gpu-provisioner/raw/gh-pages/charts/gpu-provisioner-$GPU_PROVISIONER_VERSION.tgz \
  --namespace gpu-provisioner \
  --create-namespace

# NOTE: the gpu-provisioner controller container will CrashLoop with AADSTS700211 until the federated credential exists and matches your cluster’s OIDC issuer.

# Create Federated Credential
# Federated credential links the managed identity to the service account in the AKS cluster
export AKS_OIDC_ISSUER=$(az aks show -n $CLUSTER_NAME -g $RESOURCE_GROUP --subscription $SUBSCRIPTION --query "oidcIssuerProfile.issuerUrl" -o tsv)
echo "AKS OIDC Issuer: $AKS_OIDC_ISSUER"

az identity federated-credential create \
  --name kaito-federatedcredential-$CLUSTER_NAME \
  --identity-name $IDENTITY_NAME \
  -g $RESOURCE_GROUP \
  --issuer $AKS_OIDC_ISSUER \
  --subject system:serviceaccount:"gpu-provisioner:gpu-provisioner" \
  --audience api://AzureADTokenExchange \
  --subscription $SUBSCRIPTION

# Ensure the Managed Identity has permissions to create agent pools
AKS_ID=$(az aks show -g "$RESOURCE_GROUP" -n "$CLUSTER_NAME" --query id -o tsv)
echo "AKS Cluster ID: $AKS_ID"

# Restart GPU provisioner to pick up credentials/permissions
kubectl rollout restart deploy/gpu-provisioner -n gpu-provisioner || true

#####################
# Verify Setup
#####################

# Check Helm installations
helm list -n gpu-provisioner
helm list -n kaito-workspace

# Check GPU provisioner status
kubectl describe deploy gpu-provisioner -n gpu-provisioner
kubectl get pods -n gpu-provisioner
kubectl logs --selector=app.kubernetes.io/name=gpu-provisioner -n gpu-provisioner

# Deploy a KAITO Workspace with GPU (phi-4-mini)
kubectl apply -f phi-4-workspace.yaml

# kubectl delete -f phi-4-workspace.yaml

# verify 
kubectl get workspace workspace-phi-4-mini -w

kubectl logs -n default workspace-phi-4-mini-0 --all-containers --tail=200 || true
kubectl get pods -n default -o wide

# Check node pools
az aks nodepool list -g "$RESOURCE_GROUP" --cluster-name "$CLUSTER_NAME" -o table

kubectl get workspace
kubectl get job -n default

kubectl get workspace workspace-phi-4-mini -n default -o yaml
kubectl get svc -n default -o wide
kubectl get pods -n default -o wide

# Test inference api with port-forwarding
kubectl port-forward -n default svc/workspace-phi-4-mini 8080:80

# Test Workspace inference via port-forwarding in another terminal
curl -sS "http://localhost:8080/phi4/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "phi-4-mini-instruct",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Hello! Briefly introduce yourself. What is KAITO for AKS?"}
    ],
    "temperature": 0.2,
    "max_tokens": 256
  }' | jq -C '.choices[0].message.content'


# Test RAGEngine route via ingress (/rag)
# NOTE: /rag/index expects POST (GET may return 405 with Allow: POST)
curl -sS -X POST "http://$INGRESS_IP/rag/index" \
  -H "Content-Type: application/json" \
  -d '{}' | head
  


# Streamlit App
# https://github.com/pauldotyu/kaitochat

workspace_name="workspace-phi-4-mini"
service_name="${workspace_name}.default.svc.cluster.local"
model_name="phi-4-mini-instruct"

kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  labels:
    app: kaitochatdemo
  name: kaitochatdemo
spec:
  replicas: 1
  selector:
    matchLabels:
      app: kaitochatdemo
  template:
    metadata:
      labels:
        app: kaitochatdemo
    spec:
      containers:
      - name: kaitochatdemo
        image: ghcr.io/pauldotyu/kaitochat/kaitochatdemo:latest
        resources: {}
        env:
        - name: MODEL_ENDPOINT
          value: "http://$service_name:80/v1/chat/completions"
        - name: MODEL_NAME
          value: "$model_name"
        ports:
        - containerPort: 8501
---
apiVersion: v1
kind: Service
metadata:
  labels:
    app: kaitochatdemo
  name: kaitochatdemo
spec:
  type: ClusterIP
  ports:
  - port: 80
    protocol: TCP
    targetPort: 8501
  selector:
    app: kaitochatdemo
EOF

# Use the ingress controller public IP for access, e.g. http://<INGRESS_IP>/chat
echo "http://$(kubectl get ingress kaito-ingress -n default -o jsonpath='{.status.loadBalancer.ingress[0].ip}')/chat"
