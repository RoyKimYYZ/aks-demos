# aks-demos

Hands-on Azure Kubernetes (AKS) demos for learning and technical presentations.

This repository is designed for a technical audience that wants to learn how to:

- provision AKS and related Azure resources,
- run KAITO model workspaces,
- deploy and test RAGEngine,
- expose services via ingress,
- build practical chat/RAG demo workflows.

---

## Repository table of contents

### [aks-kaito](aks-kaito)

Main end-to-end AKS + KAITO + RAG demo project.

- [aks-kaito/README.md](aks-kaito/README.md): Full runbook and demo flow.
- Infrastructure and setup scripts:
	- [aks-kaito/1-setup-aks-kaito-v0.80.sh](aks-kaito/1-setup-aks-kaito-v0.80.sh)
	- [aks-kaito/2-setup-nginx-ingress-controller.sh](aks-kaito/2-setup-nginx-ingress-controller.sh)
	- [aks-kaito/3-setup-kaito-rag.sh](aks-kaito/3-setup-kaito-rag.sh)
	- [aks-kaito/4-streamlitapp-demo.sh](aks-kaito/4-streamlitapp-demo.sh)
	- [aks-kaito/4-deploy-gptoss-inference.sh](aks-kaito/4-deploy-gptoss-inference.sh)
	- [aks-kaito/test-kaitochatdemo.sh](aks-kaito/test-kaitochatdemo.sh)
- Key manifests:
	- `ingress-*.yaml` (routing)
	- `*-workspace*.yaml` (workspace deployments)
	- `bge-small-ragengine.yaml` (RAG engine)

Nested subprojects in `aks-kaito`:

- [aks-kaito/ragengine-ingest-docs](aks-kaito/ragengine-ingest-docs)
	- [aks-kaito/ragengine-ingest-docs/README.md](aks-kaito/ragengine-ingest-docs/README.md)
	- CLI for document ingestion, index management, and RAG chat/query.
	- Includes sample docs in [aks-kaito/ragengine-ingest-docs/docs](aks-kaito/ragengine-ingest-docs/docs).

- [aks-kaito/streamlit-chatbot](aks-kaito/streamlit-chatbot)
	- [aks-kaito/streamlit-chatbot/README.md](aks-kaito/streamlit-chatbot/README.md)
	- Streamlit UI for OpenAI-compatible chat + RAG diagnostics.
	- Multipage app components in [aks-kaito/streamlit-chatbot/pages](aks-kaito/streamlit-chatbot/pages).

- [aks-kaito/kaito-rag-app](aks-kaito/kaito-rag-app)
	- Additional app workspace for KAITO/RAG experimentation.

### [aks-keyvault](aks-keyvault)

AKS + Azure Key Vault integration demos.

- [aks-keyvault/README.md](aks-keyvault/README.md): Scenario walkthrough and references.
- Scripts:
	- [aks-keyvault/aks-keyvault.sh](aks-keyvault/aks-keyvault.sh)
	- [aks-keyvault/aks-keyvault-secret-polling.sh](aks-keyvault/aks-keyvault-secret-polling.sh)

---

## Suggested learning path

1. Start with [aks-kaito/README.md](aks-kaito/README.md) for the full AKS + KAITO + RAG deployment flow.
2. Use [aks-kaito/ragengine-ingest-docs](aks-kaito/ragengine-ingest-docs) to ingest test documents and run RAG queries.
3. Use [aks-kaito/streamlit-chatbot](aks-kaito/streamlit-chatbot) for interactive demos and troubleshooting visibility.
4. Explore [aks-keyvault](aks-keyvault) to add secrets management patterns for production-like scenarios.

---

## Notes

- This repo is intentionally demo-focused and optimized for teaching concepts.
- GPU-backed workloads can incur cloud cost; remember to clean up resources after labs/demos.
