## DEMO 1

Scenario: You require a pod to mount a secret stored in an Azure Key Vault. So that an application running in the pod can access the secret as a file and environment variable. Also manage the access security between the AKS cluster to the key vault using a user assigned managed identity.


Background:

To integrate Azure Key Vault to AKS, this requires an add-on called azure-keyvault-secrets-provider

There are two pieces of this add on. One is the Secrets Store CSI Driver for Kubernetes secrets – Integrates secrets stores with Kubernetes via a Container Storage Interface (CSI) volume.

The Secrets Store CSI Driver secrets-store.csi.k8s.io allows Kubernetes to mount multiple secrets, keys, and certs stored in enterprise-grade external secrets stores into their pods as a volume. Once the Volume is attached, the data in it is mounted into the container’s file system.

The second is the Azure Key Vault Provider for Secrets Store CSI Driver which allows for the integration of an Azure key vault with an Azure Kubernetes Service (AKS) cluster.

The following steps are mainly taken from the following articles, but I will walk through in implementing the scenario outlined above.

https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-driver
https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-identity-access
Assumptions

An existing AKS Cluster. My demo Kubernetes version is 1.23.12
An existing Azure Key Vault (in a different resource group and subscription than the AKS cluster)

References:

* https://github.com/kubernetes-sigs/secrets-store-csi-driver
* https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-driver
* https://learn.microsoft.com/en-us/azure/aks/csi-secrets-store-identity-access