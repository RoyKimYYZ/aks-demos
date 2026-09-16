
# Reference: https://kaito-project.github.io/kaito/docs/azure
# Old script to setup AKS with Kaito back in 2024
# Also demonstrated fine-tuning and Streamlit app deployment.
# Use for reference.

export RESOURCE_GROUP="aks-solution"
export MY_CLUSTER="rkaksdev3"
export LOCATION="canadacentral"
export KAITO_WORKSPACE_VERSION=0.4.4

az login --use-device-code
az account set --subscription "Applications"

az group create --name $RESOURCE_GROUP --location $LOCATION
az aks create --resource-group $RESOURCE_GROUP --name $MY_CLUSTER --enable-oidc-issuer --enable-workload-identity --enable-managed-identity --generate-ssh-keys

# Get AKS credentials and configure kubelogin
az aks get-credentials --resource-group $RESOURCE_GROUP --name $MY_CLUSTER --overwrite-existing



helm install kaito-workspace  --set clusterName=$MY_CLUSTER --wait \
https://github.com/kaito-project/kaito/raw/gh-pages/charts/kaito/workspace-$KAITO_WORKSPACE_VERSION.tgz --namespace kaito-workspace --create-namespace

# Assign Contributor role to the managed identity on the AKS cluster
az role assignment create \
  --assignee $IDENTITY_PRINCIPAL_ID \
  --scope /subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ContainerService/managedClusters/$CLUSTER_NAME \
  --role "Contributor"


# Install gpu-provisioner controller
az aks update -g $RESOURCE_GROUP -n $MY_CLUSTER --enable-oidc-issuer --enable-workload-identity --enable-managed-identity

# Create an identity and assign permissions
export SUBSCRIPTION=$(az account show --query id -o tsv)
export IDENTITY_NAME="kaitoprovisioner"
az identity create --name $IDENTITY_NAME -g $RESOURCE_GROUP
export IDENTITY_PRINCIPAL_ID=$(az identity show --name $IDENTITY_NAME -g $RESOURCE_GROUP --subscription $SUBSCRIPTION --query 'principalId' -o tsv)
az role assignment create --assignee $IDENTITY_PRINCIPAL_ID --scope /subscriptions/$SUBSCRIPTION/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.ContainerService/managedClusters/$MY_CLUSTER  --role "Contributor"

# Install the Node provisioner controller helm chart
# get additional values for helm chart install
export GPU_PROVISIONER_VERSION=0.3.1

curl -sO https://raw.githubusercontent.com/Azure/gpu-provisioner/main/hack/deploy/configure-helm-values.sh
chmod +x ./configure-helm-values.sh && ./configure-helm-values.sh $MY_CLUSTER $RESOURCE_GROUP $IDENTITY_NAME

helm install gpu-provisioner --values gpu-provisioner-values.yaml --set settings.azure.clusterName=$MY_CLUSTER --wait \
https://github.com/Azure/gpu-provisioner/raw/gh-pages/charts/gpu-provisioner-$GPU_PROVISIONER_VERSION.tgz --namespace gpu-provisioner --create-namespace

# Create the federated credential
export AKS_OIDC_ISSUER=$(az aks show -n $MY_CLUSTER -g $RESOURCE_GROUP --subscription $SUBSCRIPTION --query "oidcIssuerProfile.issuerUrl" -o tsv)
az identity federated-credential create --name kaito-federatedcredential --identity-name $IDENTITY_NAME -g $RESOURCE_GROUP --issuer $AKS_OIDC_ISSUER --subject system:serviceaccount:"gpu-provisioner:gpu-provisioner" --audience api://AzureADTokenExchange --subscription $SUBSCRIPTION

# Verify installation
helm list -n kaito-workspace
helm list -n gpu-provisioner

kubectl describe deploy kaito-workspace -n kaito-workspace

kubectl describe deploy gpu-provisioner -n gpu-provisioner

kubectl logs --selector=app.kubernetes.io\/name=gpu-provisioner -n gpu-provisioner


## FINE TUNING


# Set the Azure subscription to 'Enterprise Shared Services'
az account set --subscription 'Enterprise Shared Services'

# Define the ACR name
ACR_NAME='rkimacr'

# Get the ACR login server
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --query loginServer --output tsv --subscription 'Enterprise Shared Services')
echo "ACR Login Server: $ACR_LOGIN_SERVER" 

# Get the admin username and password for the ACR
ACR_USERNAME=$(az acr credential show --name $ACR_NAME --query username --output tsv --subscription 'Enterprise Shared Services')
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query passwords[0].value --output tsv --subscription 'Enterprise Shared Services')
echo "ACR Username: $ACR_USERNAME"
echo "ACR Password: $ACR_PASSWORD"


# Create the Kubernetes secret for pulling images from the ACR
kubectl create secret docker-registry acr-secret --docker-server=$ACR_LOGIN_SERVER --docker-username=$ACR_USERNAME --docker-password=$ACR_PASSWORD --docker-email=your-email@example.com

# Example YAML to use the secret
apiVersion: v1
kind: Pod
metadata:
  name: mypod
spec:
  containers:
  - name: mycontainer
    image: rkimacr.azurecr.io/myimage:latest
  imagePullSecrets:
  - name: acr-secret

# kaito_workspace_phi_3_mini_128k.yaml
# https://github.com/kaito-project/kaito/blob/main/examples/inference/kaito_workspace_phi_3_mini_128k.yaml
# This is deploying an inference workspace with the name 'workspace-phi-3-mini-128k'
# This is used for text completions tasks and chatting applications.
kubectl apply -f - <<EOF
apiVersion: kaito.sh/v1alpha1
kind: Workspace
metadata:
  name: workspace-phi-3-mini
resource:
  instanceType: "Standard_NC8as_T4_v3"
  labelSelector:
    matchLabels:
      apps: phi-3
inference:
  preset:
    name: phi-3-mini-128k-instruct
EOF

# Model deepseek-r1-distill-qwen-14b
# https://github.com/kaito-project/kaito/blob/main/examples/inference/kaito_workspace_deepseek_r1_distill_qwen_14b.yaml
kubectl apply -f - <<EOF
apiVersion: kaito.sh/v1alpha1
kind: Workspace
metadata:
  name: workspace-deepseek-r1-distill-qwen-14b
resource:
  instanceType: "Standard_NC24ads_A100_v4"
  labelSelector:
    matchLabels:
      apps: deepseek-r1-distill-qwen-14b
inference:
  preset:
    name: "deepseek-r1-distill-qwen-14b"
EOF

# See workspace provisioning status. Expect RESOURCEREADY, INFERENCEREADY, and WOKRSPACESUCCEEDED to be true.
kubectl get workspace

# Get the cluster IP of the workspace
kubectl get svc workspace-deepseek-r1-distill-qwen-14b -n default -o jsonpath='{.spec.clusterIP}'
export SERVICE_IP=$(kubectl get svc workspace-deepseek-r1-distill-qwen-14b -n default -o jsonpath='{.spec.clusterIP}')
echo $SERVICE_IP


# Finetuning with dataset
kubectl apply -f - <<EOF
apiVersion: kaito.sh/v1alpha1
kind: Workspace
metadata:
  name: workspace-tuning-phi-3
  annotations:
    kaito.sh/enablelb: "True"
resource:
  instanceType: "Standard_NC24ads_A100_v4"
  labelSelector:
    matchLabels:
      app: tuning-phi-3
tuning:
  preset:
    name: phi-3-mini-128k-instruct
  method: qlora
  input:
    urls:
      - "https://huggingface.co/datasets/philschmid/dolly-15k-oai-style/resolve/main/data/train-00000-of-00001-54e3756291ca09c6.parquet?download=true"
  output:
    image: "$ACR_NAME.azurecr.io/finetuned:0.0.1"
    imagePushSecret: acr-secret
EOF


kubectl get workspace
kubectl get job -n default

# Check the logs of the job. Look for progress 
kubectl logs workspace-tuning-phi-3-nljpk workspace-tuning-phi-3 

kubectl apply -f - <<EOF
apiVersion: kaito.sh/v1alpha1
kind: Workspace
metadata:
  name: workspace-phi-3-mini-adapter
  #namespace: default
resource:
  instanceType: "Standard_NC8as_T4_v3"
  labelSelector:
    matchLabels:
      apps: phi-3-adapter
inference:
  preset:
    name: phi-3-mini-128k-instruct
  adapters:
    - source:
        name: "phi-3-adapter"
        image: "rkimacr.azurecr.io/finetunedph3:0.0.1"
        imagePullSecrets:
          - acr-secret
      strength: "1.0"
EOF

# Streamlit App
# https://github.com/pauldotyu/kaitochat

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
          value: "http://workspace-phi-4-mini.default.svc.cluster.local:80/v1/chat/completions"
        - name: MODEL_NAME
          value: "phi-4-mini-instruct"
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
