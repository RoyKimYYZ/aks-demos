# Reference MS Article
# https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-driver
# https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-identity-access

# Assumptions
# - AKS resource exists
# - Key Vault exists

az login

rgName='aks-solution'
aksName='rkaksdev'

keyVaultName='rkimKeyVault'
keyVaultRG='Enterprise'
keyVaultSubName='Enterprise'
# Kubernetes
# key vault demo namespace
keyVaultDemoNamespace=keyvault-demo

az account show -o table

az aks list -g $rgName -o table 
az aks get-credentials -g $rgName -n $aksName --admin --overwrite-existing

# Check if azure kyvault secrets provider addon is enabled
az aks addon list -g $rgName -n $aksName -o table | grep keyvault

# Show list of key vaults
az keyvault list -g $keyVaultRG --subscription $keyVaultSubName -o table
# Show specific key vault exists
az keyvault show -g $keyVaultRG -n $keyVaultName --subscription $keyVaultSubName -o table --query name

# Enable addon Secrets Store CSI Driver and the Azure Key Vault Provider into given AKS resource
az aks enable-addons --addons azure-keyvault-secrets-provider --name $aksName --resource-group $rgName

# Verify that the installation is finished by listing all pods that have the secrets-store-csi-driver and secrets-store-provider-azure labels in the kube-system namespace
kubectl get pods -n kube-system -l 'app in (secrets-store-csi-driver, secrets-store-provider-azure)'

# Create a secret into an existing Key Vault
az keyvault secret set --vault-name $keyVaultName -n ExampleSecret --value s3cr3tV@lue 
# Show secret value
az keyvault secret show --name ExampleSecret --vault-name $keyVaultName 

# Create and assign workload identity
# Reference MSFT Article https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-identity-access

# Ensure to add k8s-extension to the AKS cluster
az k8s-extension list --cluster-name $aksName -g $rgName --cluster-type managedClusters
az extension add --name k8s-extension

# Create a user assigned managed identity to assign to VMSS and set permissions to Azure Key Vault secrets
aks2kvUserassignedidentityname='aks2kv-uami'
echo $aks2kvUserassignedidentityname
az identity create -g $rgName -n $aks2kvUserassignedidentityname

export identityResourceId=$(az identity show -g $rgName -n $aks2kvUserassignedidentityname --query id -o tsv)
echo $identityResourceId
export identityClientId=$(az identity show -g $rgName -n $aks2kvUserassignedidentityname --query clientId --output tsv)
echo $identityClientId
export identityPrincipalId=$(az identity show -g $rgName -n $aks2kvUserassignedidentityname --query principalId -o tsv)
echo $identityPrincipalId

# Set agent pool VMSS name by going to the AKS infrastructure resource group to find the VMSS resource
agentPoolVMSS='aks-agentpool-19975385-vmss'
agentPoolVMSSRG='MC_aks-solution_rkaksdev_canadacentral'
az vmss identity assign -g $agentPoolVMSSRG -n $agentPoolVMSS --identities $identityResourceId

# set policy to access secrets in your key vault or set in Azure Portal in Key Vault > Access Policies
az keyvault set-policy -g $keyVaultRG -n $keyVaultName  --subscription $keyVaultSubName --secret-permissions get --spn $identityClientId 


# Create namespace for key vault demo
kubectl create namespace $keyVaultDemoNamespace

kubectl config set-context --current --namespace=$keyVaultDemoNamespace

# Find key vault tenant ID
export keyvaultTenantId=$(az keyvault show  -g $keyVaultRG -n $keyVaultName --subscription $keyVaultSubName -o tsv --query properties.tenantId)
echo $keyvaultTenantId

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

cat << EOF | kubectl apply -f -
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: azure-sync
  namespace: $keyVaultDemoNamespace
spec:
  provider: azure                             
  secretObjects:                              # [OPTIONAL] SecretObjects defines the desired state of synced Kubernetes secret objects
  - data:
    - key: examplesecretkey                   # data field to populate
      objectName: foo1                        # name of the mounted content to sync; this could be the object name or the object alias
    secretName: example-secret                # name of the Kubernetes secret object
    type: Opaque                              # type of Kubernetes secret object (for example, Opaque, kubernetes.io/tls)
EOF

kubectl get SecretProviderClass -n $keyVaultDemoNamespace

# Create a Pod that mounts the secret from Azure Key Vault as a file and environment variable
cat << EOF | kubectl apply -f -
kind: Pod
apiVersion: v1
metadata:
  name: busybox-secrets-store-inline-uami
  namespace: $keyVaultDemoNamespace
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

podname=$(kubectl get pods | grep busybox | awk '{print $1}')
podname=busybox-deployment-secrets-store-inline-uami-5d49c57444-54cd7
echo $podname
## show secrets held in secrets-store
kubectl exec $podname -n $keyVaultDemoNamespace -- ls /mnt/secrets-store/ 
## print a test secret 'ExampleSecret' held in secrets-store
kubectl exec $podname -n $keyVaultDemoNamespace -- cat /mnt/secrets-store/ExampleSecret; echo
## Display the environment variables that includes the secret
kubectl exec $podname -n $keyVaultDemoNamespace -- printenv
kubectl exec busybox-secrets-store-inline-uami -n $keyVaultDemoNamespace -- env $EXAMPLE_SECRET



# refresh pod secret mount by deleting and then redeploy YAML manifest of pod defined above.
kubectl delete pod/busybox-secrets-store-inline-uami -n $keyVaultDemoNamespace
kubectl delete SecretProviderClass --all -n $keyVaultDemoNamespace


# Troubleshooting
# Reference: https://learn.microsoft.com/en-us/troubleshoot/azure/azure-kubernetes/troubleshoot-key-vault-csi-secrets-store-csi-driver

kubectl get pods -l app=secrets-store-provider-azure -n kube-system -o wide
kubectl logs -l app=secrets-store-provider-azure -n kube-system --since=1h | grep ^E

kubectl get pods -l app=secrets-store-csi-driver -n kube-system -o wide
kubectl logs -l app=secrets-store-csi-driver -n kube-system --since=1h | grep ^E


# Clean up and uninstall demo

kubectl delete --all -n keyvault-demo
kubectl delete ns keyvault-demo
az keyvault delete-policy -g $keyVaultRG -n $keyVaultName --spn $identityClientId 
az keyvault secret delete --vault-name $keyVaultName -n ExampleSecret 
az vmss identity remove -g $agentPoolVMSSRG -n $agentPoolVMSS --identities $identityResourceId
az aks disable-addons --addons azure-keyvault-secrets-provider --name $aksName --resource-group $rgName
az identity delete -g $rgName -n $aks2kvUserassignedidentityname
