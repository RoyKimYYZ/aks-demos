# Prequisites - Setup of AKS key vault integration via aks-keyvault.sh

# AKS Clust created
# AKS Key vault with secret mounted to a POD

rgName='aks-solution'
aksName='rkaksdev'
keyVaultName='rkimKeyVault'
keyVaultRG='Enterprise'
keyVaultSubName='Enterprise'

# Kubernetes
# key vault demo namespace
keyVaultDemoNamespace=keyvault-demo
kubectl create ns $keyVaultDemoNamespace
kubectl config set-context --current --namespace=$keyVaultDemoNamespace
# Without autorotation, the only way to update the secret mounted to the POD is to recreate the POD. This isn't ideal production scenarios. 

# Reference: https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-driver#enable-and-disable-autorotation

az aks addon update -g $rgName -n $aksName -a azure-keyvault-secrets-provider --enable-secret-rotation --rotation-poll-interval 1m
# default is 2m rotation poll

# Show secret value
az keyvault secret show --name ExampleSecret --vault-name $keyVaultName 
# Add new secret value
az keyvault secret set --name ExampleSecret --vault-name $keyVaultName  --value Secret16

# Create a Pod that mounts the secret from Azure Key Vault as a file and environment variable
cat << EOF | kubectl apply -f -
kind: Pod
apiVersion: v1
metadata:
  name: busybox-secrets-store-inline-uami
  namespace: $keyVaultDemoNamespace
  annotations:
    reloader.stakater.com/auto: "true"
spec:
  containers:
    - name: busybox
      image: k8s.gcr.io/e2e-test-images/busybox:1.29-1
      command:
        - "/bin/sleep"
        - "10000"
      volumeMounts:
      - name: secrets-store01-inline
        mountPath: "/mnt/secrets-store"
        readOnly: true
      env:
      - name: EXAMPLE_SECRET
        valueFrom:
          secretKeyRef:
            name: example-secret
            key: examplesecretkey
  volumes:
    - name: secrets-store01-inline
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes:
          secretProviderClass: "azure-rkimkv-secret-provider"
EOF


# Create a Pod that mounts the secret from Azure Key Vault as a file and environment variable
cat << EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: busybox-deployment-secrets-store-inline-uami
  namespace: $keyVaultDemoNamespace
  labels:
    app: busybox
  annotations:
    reloader.stakater.com/auto: "true"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: busybox
  template:
    metadata:
      labels:
        app: busybox
    spec:
      containers:
        - name: busybox
          image: k8s.gcr.io/e2e-test-images/busybox:1.29-1
          command:
            - "/bin/sleep"
            - "20000"
          volumeMounts:
          - name: secrets-store01-inline
            mountPath: "/mnt/secrets-store"
            readOnly: true
          env:
          - name: EXAMPLE_SECRET
            valueFrom:
              secretKeyRef:
                name: example-secret
                key: examplesecretkey
      volumes:
        - name: secrets-store01-inline
          csi:
            driver: secrets-store.csi.k8s.io
            readOnly: true
            volumeAttributes:
              secretProviderClass: "azure-rkimkv-secret-provider"
EOF


cat <<EOF | kubectl apply -f -
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: azure-rkimkv-secret-provider
  namespace: $keyVaultDemoNamespace
spec:
  provider: azure
  parameters:
    usePodIdentity: "false"
    useVMManagedIdentity: "true"    # Set to true for using managed identity
    userAssignedIdentityID: $identityClientId      # If empty, then defaults to use the system assigned identity on the VM
    keyvaultName: $keyVaultName
    cloudName: ""                   # [OPTIONAL for Azure] if not provided, the Azure environment defaults to AzurePublicCloud
    objects:  |
      array:
        - |
          objectName: ExampleSecret
          objectType: secret        # object types: secret, key, or cert
          objectVersion: ""         # [OPTIONAL] object versions, default to latest if empty
    tenantId: $keyvaultTenantId           # The tenant ID of the key vault
  secretObjects:                              # [OPTIONAL] SecretObjects defines the desired state of synced Kubernetes secret objects
  - data:
    - key: examplesecretkey                           # data field to populate
      objectName: ExampleSecret                        # name of the mounted content to sync; this could be the object name or the object alias
    secretName: example-secret                     # name of the Kubernetes secret object
    type: Opaque       
EOF

# View yaml of exsiting secretproviderclass
kubectl describe secretproviderclass azure-rkimkv-secret-provider 

kubectl get secrets

# Install Reloader as a helm chart
# Environment variable rolling update using https://github.com/stakater/Reloader
# https://github.com/stakater/Reloader
export PATH=/usr/local/bin:$PATH # sometimes needed when there is an error running helm command
helm repo add stakater https://stakater.github.io/stakater-charts
helm repo update
helm install stakater/reloader --generate-name # For helm3 add --generate-name flag or set the release name


kubectl get pods | grep busybox-deployment
kubectl get pods --watch

podname=busybox-deployment-secrets-store-inline-uami-d89f6558b-49vxk
## show secrets held in secrets-store mount path
kubectl exec $podname -n $keyVaultDemoNamespace -- ls /mnt/secrets-store/ 
## print a test secret 'ExampleSecret' held in secrets-store
kubectl exec $podname -n $keyVaultDemoNamespace -- cat /mnt/secrets-store/ExampleSecret; echo
## Display the environment variables sync'd with the mounted secret
kubectl exec $podname -n $keyVaultDemoNamespace -- printenv EXAMPLE_SECRET
kubectl describe secret example-secret 

# Uninstall or clean up
export PATH=$PATH:/usr/local/bin 
helm list
helm uninstall reloader-1673926878
kubectl delete deployment --all
kubectl delete ns $keyVaultDemoNamespace
kubectl get ns