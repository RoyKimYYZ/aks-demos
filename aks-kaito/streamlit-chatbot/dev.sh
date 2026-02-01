#!/usr/bin/env bash
# dev.sh (runbook)
#
# This file is intentionally *not* a CLI wrapper.
# It is a set of raw commands you can run line-by-line.
#
# To prevent accidental full execution, the script exits immediately.
# Copy/paste the sections you need, or temporarily comment out `exit 0`.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

exit 0

### Prereq: install uv (once)
# curl -LsSf https://astral.sh/uv/install.sh | sh
# or see: https://docs.astral.sh/uv/

### 1) Setup venv + install deps
uv --version
uv venv --python 3.13.0 .venv

# Install deps from pyproject.toml
uv sync --extra dev

### 2) Sync deps (re-run after edits)
uv sync --extra dev

### 3) Format (auto-fix)
uv run python -m ruff format .
uv run python -m ruff check --fix .

### 4) Lint (no changes)
uv run python -m ruff format --check .
uv run python -m ruff check .

### 5) Typecheck
uv run python -m mypy .

### 6) Run Streamlit
# Optional (ingress): export KAITO_INGRESS_BASE="http://<INGRESS_IP>"
# Optional: export STREAMLIT_SERVER_PORT=8501
uv run streamlit run app.py --server.port "${STREAMLIT_SERVER_PORT:-8501}"

### 7) Clean
rm -rf .venv .mypy_cache .ruff_cache __pycache__
find . -name "__pycache__" -type d -prune -exec rm -rf {} + || true


### 8) Docker build (from project root)
# NOTE: context must be a directory (.), not .dockerignore.
# If you see: "docker-buildx: no such file or directory", install buildx:
#   sudo apt-get update && sudo apt-get install -y docker-buildx-plugin
# Or quick workaround (legacy builder):
#   DOCKER_BUILDKIT=0 docker build -t streamlit-chatbot:latest -f Dockerfile .
docker build -t streamlit-chatbot:latest -f Dockerfile .

### 9) Docker run (local test)
# The image CMD already starts Streamlit; this just publishes the port.
docker run -it --rm -p 8501:8501 streamlit-chatbot:latest
# Then open http://localhost:8501 in your browser
### 10) Push to container registry (after docker build)

# You need an Azure login that has AcrPush on the registry.
#   az login
az account set --subscription "Enterprise Shared Services"

ACR_NAME="rkimacr"
ACR_LOGIN_SERVER="$(az acr show --name "${ACR_NAME}" --query loginServer -o tsv --subscription "Enterprise Shared Services")"
echo "ACR Login Server: ${ACR_LOGIN_SERVER}"

# Avoid docker-credential-desktop.exe errors by using a temporary DOCKER_CONFIG.
export DOCKER_CONFIG="$(mktemp -d)"

# Login using an ACR access token (no admin user required)
ACR_TOKEN="$(az acr login --name "${ACR_NAME}" --expose-token --query accessToken -o tsv --subscription "Enterprise Shared Services")"
echo ACR_TOKEN first 10 chars: "${ACR_TOKEN:0:10}..."

docker tag streamlit-chatbot:latest "${ACR_LOGIN_SERVER}/streamlit-chatbot:latest"
printf "%s" "${ACR_TOKEN}" | docker login "${ACR_LOGIN_SERVER}" \
	--username 00000000-0000-0000-0000-000000000000 \
	--password-stdin

docker push "${ACR_LOGIN_SERVER}/streamlit-chatbot:latest"


# redeploy streamlit-chatbot in AKS to pick up the new image
kubectl get deployments -n default

kubectl apply -f k8s-streamlit-chatbot.yaml -n default
kubectl apply -f ingress-streamlit-chatbot.yaml -n default

kubectl rollout restart deployment streamlit-chatbot -n default
kubectl get pods -n default -l app=streamlit-chatbot