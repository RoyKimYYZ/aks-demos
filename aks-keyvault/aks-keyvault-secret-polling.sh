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
kubectl config set-context --current --namespace=$keyVaultDemoNamespace
# Without autorotation, the only way to update the secret mounted to the POD is to recreate the POD. This isn't ideal production scenarios. 

# Reference: https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-driver#enable-and-disable-autorotation

# Rotate secret mounted as a volume 


# Environment variable rolling update using https://github.com/stakater/Reloader

az aks addon update -g $rgName -n $aksName -a azure-keyvault-secrets-provider --enable-secret-rotation --rotation-poll-interval 1m
# default is 2m rotation poll

# Install Reloader as a helm chart
# https://github.com/stakater/Reloader
export PATH=/usr/local/bin:$PATH # sometimes needed when there is an error running helm command

helm repo add stakater https://stakater.github.io/stakater-charts
helm repo update
helm install stakater/reloader --generate-name # For helm3 add --generate-name flag or set the release name

# Show secret value
az keyvault secret show --name ExampleSecret --vault-name $keyVaultName 
# Add new secret value
az keyvault secret set --name ExampleSecret --vault-name $keyVaultName  --value Secret10

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
  #annotations:
  #  reloader.stakater.com/auto: "true"
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

# View yaml of exsiting secretproviderclass
kubectl describe secretproviderclass azure-rkimkv-secret-provider 

kubectl get pods | grep busybox-deployment
podname=busybox-deployment-secrets-store-inline-uami-7c9497d95b-mw54c
## show secrets held in secrets-store mount path
kubectl exec $podname -n $keyVaultDemoNamespace -- ls /mnt/secrets-store/ 
## print a test secret 'ExampleSecret' held in secrets-store
kubectl exec $podname -n $keyVaultDemoNamespace -- cat /mnt/secrets-store/ExampleSecret; echo
## Display the environment variables sync'd with the mounted secret
kubectl exec $podname -n $keyVaultDemoNamespace -- printenv EXAMPLE_SECRET
kubectl describe secret example-secret 

# Uninstall or clean up
helm list
helm uninstall stakater/reloader 
