#!/usr/bin/env bash
set -euo pipefail

# Wrapper for document-ingestion.py using a uv-managed venv.
#
# Examples:
#   export INGRESS_IP=1.2.3.4
#   ./ingest.sh --file ./cra-tax-rules.txt --index rag_index --mode create
#   ./ingest.sh --file ./cra-tax-rules.txt --index rag_index --mode update
#
# Or provide base URL directly:
#   ./ingest.sh --base-url http://1.2.3.4 --file ./cra-tax-rules.txt --index rag_index

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PY="${VENV_DIR}/bin/python"

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: 'uv' is not installed or not on PATH." >&2
  echo "Install: https://docs.astral.sh/uv/" >&2
  exit 1
fi

# Create venv if missing
if [[ ! -d "${VENV_DIR}" ]]; then
  uv venv "${VENV_DIR}"
fi

# Ensure dependencies are installed inside this venv
uv pip -p "${PY}" install -q "click>=8.1.7" "requests>=2.31.0"

exec "${PY}" "${SCRIPT_DIR}/document-ingestion.py" "$@"

# Create venv (if you want to do it manually): 
uv venv

#Install/sync deps from pyproject.toml: 
uv sync
# Run the script without activating venv:
INGRESS_IP=$(kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "INGRESS_IP: $INGRESS_IP"
DOCUMENT_FILE="./cra-tax-rules.txt"
index_name="tax_index"
uv run python document-ingestion.py --base-url "http://$INGRESS_IP" --file "$DOCUMENT_FILE" --index "$index_name" --mode create

# Update docs in an existing index:
uv run python document-ingestion.py --base-url "http://$INGRESS_IP/rag" --file "$DOCUMENT_FILE" --index "$index_name" --mode update

# Update docs with max chars per document to chunk into smaller pieces. The benefit is more relevant for larger documents.
uv run python document-ingestion.py --base-url "http://$INGRESS_IP/rag" --file "$DOCUMENT_FILE" --index "$index_name" --mode update --max-chars 800

# List documents in an index:
uv run python document-ingestion.py --base-url "http://$INGRESS_IP/rag" --index "$index_name" --mode list   

uv run python document-ingestion.py --base-url "http://$INGRESS_IP/rag" --index "$index_name" --mode list --metadata author=kaito --max-text-length 2000    

# Query/Ask a question against an index:
uv run python document-ingestion.py --base-url "http://$INGRESS_IP/rag" --index "$index_name" --mode query \
    --question "what are tax credits available for families in Canada?" \
    --model "phi-4-mini-instruct" --temperature 0.7 --max-tokens 2048

uv run python document-ingestion.py --base-url "http://$INGRESS_IP/rag" --index "$index_name" --mode query \
    --question "What is the Ontario Trillium Benefit?" \
    --model "phi-4-mini-instruct" --temperature 0.7 --max-tokens 2048 \
    --system "Use only the indexed docs; if not present, reply NOT FOUND." --show-sources


uv run python document-ingestion.py --base-url "http://$INGRESS_IP/rag" --index "$index_name" --mode query \
        --question "What is the Ontario Trillium Benefit?" \
        --model "phi-4-mini-instruct" --temperature 0.7 --max-tokens 2048 \
        --system "You are a tax consultant for personal households. Use only the indexed docs; if not present, reply NOT FOUND." \
        --show-sources 

# Ask question with a topic not in the indexed documents:
uv run python document-ingestion.py --base-url "http://$INGRESS_IP/rag" --index "$index_name" --mode query \
    --question "What is the Narnia Trillium Benefit?" \
    --model "phi-4-mini-instruct" --temperature 0.7 --max-tokens 2048 \
    --system "You are a tax consultant for personal households. Use only the indexed docs; if not present, reply NOT FOUND." \
    --show-sources 


