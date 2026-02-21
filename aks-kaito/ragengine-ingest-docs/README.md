# Document Ingestion CLI (`ragengine-ingest-docs.py`)

This script ingests text documents into RagEngine and can also list indexed documents or run RAG chat queries.

## What this CLI supports

- **Create** an index and ingest documents: `POST /rag/index`
- **Update** existing docs in an index: `POST /indexes/{index}/documents`
- **List** documents in an index (paginated): `GET /indexes/{index}/documents`
- **Chat/Query** using OpenAI-compatible endpoint: `POST /v1/chat/completions`

---

## Prerequisites

- Python 3.10+ (matches `pyproject.toml`)
- `uv` installed: https://docs.astral.sh/uv/getting-started/installation/
- Network access to RagEngine endpoint

Initialize the project environment:

```bash
uv sync
```

---

## Basic usage

```bash
INDEX_NAME='rag_index'
uv run python ragengine-ingest-docs.py --index $INDEX_NAME --mode <create|update|list|chat|query> [options]
```

Run help:

```bash
uv run python ragengine-ingest-docs.py --help
```

---

## Base URL resolution

The CLI resolves the RagEngine URL in this order:

1. `--base-url`
2. `RAGENGINE_URL`
3. `http://$INGRESS_IP`

If you set `INGRESS_IP` but still see requests going to another host, check and unset `RAGENGINE_URL`:

```bash
unset RAGENGINE_URL
```

Examples:

```bash
export INGRESS_IP="ai.roykim.ca" # or public ip address
# or
export RAGENGINE_URL="http://ai.roykim.ca/rag-nostorage"
```

Force a one-off explicit target (bypasses env ambiguity):

```bash
uv run python ragengine-ingest-docs.py --base-url http://ai.roykim.ca/rag-nostorage --index rag_index --mode create --file ./docs/cra-tax-rules.txt
```

---

## Common workflows

### 1) Create index + ingest a `.txt` file

```bash
uv run python ragengine-ingest-docs.py \
  --file ./docs/cra-tax-rules.txt \
  --index rag_index \
  --mode create \
  --metadata subject=tax \
  --metadata jurisdiction='"Canada"' \
  --connect-timeout 5 \
  --timeout 20 \
  --retries 1


```

With JSON metadata:

```bash
uv run python ragengine-ingest-docs.py \
  --file ./docs/cra-tax-rules.txt \
  --index rag_index \
  --mode create \
  --metadata-json '{"author":"kaito","year":2025,"tags":["tax","demo"]}'

  ```

  Additional metadata examples:

  ```bash
  # Single metadata key-value
  uv run python ragengine-ingest-docs.py \
    --file ./docs/fantasia-citizen-laws.md \
    --index rag_index \
    --mode create \
    --metadata subject=law

  # Mix simple and JSON metadata
  uv run python ragengine-ingest-docs.py \
    --file ./docs/soc2-azure-networking-security-controls.md \
    --index rag_index \
    --mode create \
    --metadata subject=soc2 \
    --metadata-json '{"tags":["cloud","azure"],"reviewed":true}'

  # Complex JSON with nested structures
  uv run python ragengine-ingest-docs.py \
    --file ./document.txt \
    --index rag_index \
    --mode create \
    --metadata-json '{"department":"finance","classifications":["confidential","audit"],"created":"2025-01-15"}'
  ```


```

### 2) Update documents in an existing index

```bash
uv run python ragengine-ingest-docs.py \
  --file ./docs/cra-tax-rules.txt \
  --index rag_index \
  --mode update
```

### 3) List documents

```bash
uv run python ragengine-ingest-docs.py \
  --index rag_index \
  --mode list \
  --limit 50 \
  --offset 0 \
  --max-text-length 500
```

With metadata filter:

```bash
uv run python ragengine-ingest-docs.py \
  --index rag_index \
  --mode list \
  --metadata-filter '{"filename":"cra-tax-rules.txt"}'


uv run python ragengine-ingest-docs.py \
  --index rag_index \
  --mode list \
  --metadata-filter '{"author":"kaito","year":2025}'
```

### 4) Ask a question (RAG)

```bash
uv run python ragengine-ingest-docs.py \
  --index rag_index \
  --mode chat \
  --question "According to CRA rules, What benefits are income-tested for families?" \
  --model phi-4-mini-instruct \
  --show-sources

uv run python ragengine-ingest-docs.py \
  --index rag_index \
  --mode chat \
  --question "What is the Fantasia Citizen Code (FCC)?" \
  --model phi-4-mini-instruct \
  --show-sources

uv run python ragengine-ingest-docs.py \
  --index rag_index \
  --mode chat \
  --question "What are the Northwind Corporation SOC 2-Aligned Azure Networking Security Controls?" \
  --model phi-4-mini-instruct \
  --show-sources

uv run python ragengine-ingest-docs.py \
  --index rag_index \
  --mode chat \
  --question "what are tags for the document Northwind Corporation SOC 2-Aligned Azure Networking Security Controls?" \
  --model phi-4-mini-instruct \
  --show-sources
  


```

Question from file:

```bash
uv run python ragengine-ingest-docs.py \
  --index rag_index \
  --mode chat \
  --model phi-4-mini-instruct \
  --question-file ./my-question.txt
```

---

## Package as a standalone executable

If you want a single-file executable (no separate Python environment at runtime), use `PyInstaller`.

Build:

```bash
uv run --with pyinstaller pyinstaller \
  --onefile \
  --name ragengine-ingest-docs \
  ragengine-ingest-docs.py
```

Output binary:

- Linux/macOS: `dist/ragengine-ingest-docs`
- Windows: `dist/ragengine-ingest-docs.exe`

Run:

```bash
./dist/ragengine-ingest-docs --help
```

Notes:

- Build on the same OS/architecture you plan to run on.
- Rebuild after script/dependency changes.
- Environment variables like `RAGENGINE_URL`, `RAGENGINE_MODEL`, and `INGRESS_IP` still work the same.

### Optional: package as an installable CLI command

If you prefer a Python package CLI (not a single binary), expose an importable module and add a console entry point.

1) Rename `ragengine-ingest-docs.py` to `ragengine_ingest_docs.py`.

2) Add this in `pyproject.toml`:

```toml
[project.scripts]
ragengine-ingest-docs = "ragengine_ingest_docs:cli"
```

Then run with:

```bash
uv run ragengine-ingest-docs --help
```

---

## Important options

### Ingestion options (`create` / `update`)

- `--file` path to source `.txt` (required)
- `--max-chars` max characters per chunk (default: `3000`)
- `--overlap-chars` overlap between chunks (default: `200`)
- `--metadata` metadata `key=value` (repeatable)
- `--metadata-json` metadata JSON object string (merged with `--metadata`)

### Listing options (`list`)

- `--limit` max docs returned (default: `10`)
- `--offset` pagination offset (default: `0`)
- `--max-text-length` max returned text per doc (default: `1000`)
- `--metadata-filter` JSON object string

### Chat/query options (`chat` / `query`)

- `--question` question text
- `--question-file` read question from file
- `--system` system prompt (default: `You are a helpful assistant.`)
- `--model` model name (or `RAGENGINE_MODEL`; if omitted, auto-detected from `/v1/models`, else fallback `phi-4-mini-instruct` or `RAGENGINE_DEFAULT_MODEL`)
- `--temperature` (default: `0.7`)
- `--max-tokens` (default: `2048`)
- `--context-token-ratio` (default: `0.5`)
- `--json` print full JSON response
- `--show-sources` print `source_nodes` if returned

### Networking/retry options

- `--connect-timeout` HTTP connect timeout in seconds (default: `5`)
- `--timeout` HTTP timeout in seconds (default: `60`)
- `--retries` HTTP retry count (default: `3`)

---

## Notes

- The script chunks text by paragraphs and applies optional overlap for better retrieval.
- In `update` mode, document IDs are deterministic per absolute file path + chunk index, so re-ingesting updates stable IDs.
- `metadata_filter` must be valid JSON object text.

---

## Troubleshooting

- **Missing dependency error**: run `uv sync` in this directory
- **Missing base URL**: set `--base-url`, `RAGENGINE_URL`, or `INGRESS_IP`
- **No chat output text shown**: use `--json` to inspect full model response
