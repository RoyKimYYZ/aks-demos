# Streamlit Chatbot (KAITO Workspaces)

A simple Streamlit chat UI that calls an OpenAI-compatible Chat Completions API (e.g., KAITO workspace inference endpoints and KAITO RAGEngine endpoints).

## Quickstart (local)

```bash
cd aks-kaito/streamlit-chatbot
uv venv --python 3.13.0 .venv
uv sync --extra dev
uv run streamlit run app.py
```

## Configure endpoints + models

The app reads a catalog from [kaito_catalog.yaml](kaito_catalog.yaml). You can:

- Edit the YAML directly, or
- Point to a different file with `KAITO_CATALOG_PATH=/path/to/catalog.yaml`.

The left sidebar lets you select:
- API endpoint (e.g., Ingress `/phi4` vs `/rag` vs port-forward)
- Model

### Ingress routing (recommended)

This repo’s ingress routes are defined in [aks-kaito/ingress-nginx-kaito.yaml](../ingress-nginx-kaito.yaml):
- `/phi4/*` → `workspace-phi-4-mini`
- `/rag/*` → `ragengine-with-storage`

Set:

```bash
export KAITO_INGRESS_BASE="http://<INGRESS_IP>"
```

Then pick **Phi-4 (Ingress /phi4)** or **RAGEngine (Ingress /rag)** in the sidebar.

To get the ingress IP:

```bash
kubectl get svc ingress-nginx-controller -n ingress-nginx \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

### Port-forward (no ingress)

```bash
kubectl port-forward -n default svc/workspace-phi-4-mini 8080:80
```

Then select **Phi-4 (Port-forward localhost:8080)**.

## Notes

- KAITO endpoints in these demos typically don’t require an API key; the sidebar supports one anyway.
- The **Extra JSON payload** box is merged into the request body. This is handy for RAGEngine fields like `index_name` or `context_token_ratio`.
