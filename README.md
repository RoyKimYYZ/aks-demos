# aks-demos
Azure Kubernetes Demos for the purposes of sharing my knowledge to the technology community

## AKS + ingress-nginx health probe

For AKS (Azure Standard Load Balancer), the ingress-nginx `LoadBalancer` Service must have a working health probe.
This repo configures a dedicated, always-200 endpoint served by ingress-nginx itself:

- `GET /healthz` returns `200`
- Azure LB probe path is set to `/healthz`

See the Helm flags in [aks-kaito/setup-kaito-rag.sh](aks-kaito/setup-kaito-rag.sh).
