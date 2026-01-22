#!/usr/bin/env python3
"""
Ingest a .txt file into RagEngine over HTTP.

Supports:
- Create index + add documents: POST {base_url}/rag/index
- Update existing docs in an index: POST {base_url}/indexes/{index_name}/documents
- List documents in an index (paginated): GET {base_url}/indexes/{index_name}/documents
- Ask questions against an index (OpenAI-compatible): POST {base_url}/v1/chat/completions

Examples:
  export INGRESS_IP=1.2.3.4
  python3 document-ingestion.py --file ./cra-tax-rules.txt --index rag_index --mode create

  python3 document-ingestion.py --file ./cra-tax-rules.txt --index rag_index --mode update

    # List documents
    python3 document-ingestion.py --index rag_index --mode list --limit 5 --offset 0 --max-text-length 500

    # Ask a question (RAG)
    python3 document-ingestion.py --base-url http://$INGRESS_IP/rag --index rag_index --mode chat \
        --question "What benefits are income-tested for families?" --show-sources

Notes:
- This script chunks large text into multiple documents (by paragraphs) to improve retrieval.
- doc_id is deterministic per (absolute file path + chunk index) so re-ingesting updates the same IDs.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import sys
import time
import uuid
from typing import List, Dict, Any, Iterable, Tuple
from urllib.parse import urljoin

try:
    import click  # type: ignore
except ImportError:
    print("Missing dependency: click. Install with: python3 -m pip install click", file=sys.stderr)
    raise

try:
    import requests  # type: ignore
except ImportError:
    print("Missing dependency: requests. Install with: python3 -m pip install requests", file=sys.stderr)
    raise


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iter_paragraphs(text: str) -> Iterable[str]:
    # Normalize newlines and split on blank lines.
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    for p in t.split("\n\n"):
        p = p.strip()
        if p:
            yield p


def chunk_text(text: str, *, max_chars: int, overlap_chars: int) -> List[str]:
    """
    Chunk by paragraphs up to max_chars. If a single paragraph exceeds max_chars,
    it will be split hard with overlap.
    """
    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0

    def flush_buf():
        nonlocal buf, buf_len
        if buf:
            chunks.append("\n\n".join(buf).strip())
            buf = []
            buf_len = 0

    for para in _iter_paragraphs(text):
        if len(para) > max_chars:
            # Flush current buffer first
            flush_buf()
            # Split long paragraph
            start = 0
            while start < len(para):
                end = min(start + max_chars, len(para))
                piece = para[start:end].strip()
                if piece:
                    chunks.append(piece)
                if end >= len(para):
                    break
                start = max(0, end - overlap_chars)
            continue

        # Try to add paragraph to buffer
        extra = (2 if buf else 0) + len(para)  # account for "\n\n"
        if buf_len + extra <= max_chars:
            buf.append(para)
            buf_len += extra
        else:
            flush_buf()
            buf.append(para)
            buf_len = len(para)

    flush_buf()

    # Optional overlap between chunks (soft overlap)
    if overlap_chars > 0 and len(chunks) > 1:
        overlapped: List[str] = []
        prev_tail = ""
        for c in chunks:
            if prev_tail:
                overlapped.append((prev_tail + "\n\n" + c).strip())
            else:
                overlapped.append(c)
            prev_tail = c[-overlap_chars:] if len(c) > overlap_chars else c
        chunks = overlapped

    return [c for c in chunks if c.strip()]


def make_doc_id(file_abs: str, chunk_index: int) -> str:
    # Deterministic UUID based on file path + chunk index
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"file://{file_abs}#chunk={chunk_index}"))


def request_json_with_retries(
    method: str,
    url: str,
    *,
    payload: Dict[str, Any] | None = None,
    params: Dict[str, Any] | None = None,
    timeout_s: int = 60,
    retries: int = 3,
    backoff_s: float = 1.0,
) -> Dict[str, Any]:
    method_u = method.upper().strip()
    if method_u not in {"GET", "POST"}:
        raise ValueError(f"Unsupported method: {method}")

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if method_u == "POST":
                resp = requests.post(url, json=payload, timeout=timeout_s)
            else:
                resp = requests.get(url, params=params, timeout=timeout_s)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text}")
            # Try JSON, otherwise return raw text
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text}
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(backoff_s * attempt)
            else:
                break
    raise RuntimeError(f"Request failed after {retries} attempts: {last_err}") from last_err


def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _parse_metadata_filter(raw: str) -> str:
    """Validate JSON and return canonical JSON string (for server query param)."""
    import json

    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("metadata_filter must be a JSON object (key-value pairs)")
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def build_documents(
    file_path: str,
    *,
    max_chars: int,
    overlap_chars: int,
    extra_metadata: Dict[str, Any] | None = None,
) -> List[Tuple[str, str, Dict[str, Any]]]:
    """
    Returns list of (doc_id, text, metadata).
    """
    file_abs = os.path.abspath(file_path)
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    chunks = chunk_text(text, max_chars=max_chars, overlap_chars=overlap_chars)
    meta_base: Dict[str, Any] = {
        "source_type": "txt",
        "filename": os.path.basename(file_abs),
        "path": file_abs,
        "ingested_at": _now_iso(),
    }
    if extra_metadata:
        meta_base.update(extra_metadata)

    docs: List[Tuple[str, str, Dict[str, Any]]] = []
    for i, chunk in enumerate(chunks):
        doc_id = make_doc_id(file_abs, i)
        md = dict(meta_base)
        md["chunk_index"] = i
        md["chunk_count"] = len(chunks)
        docs.append((doc_id, chunk, md))
    return docs


def _resolve_base_url(base_url: str | None) -> str:
    base_url_eff = base_url or os.environ.get("RAGENGINE_URL")
    if not base_url_eff:
        ingress_ip = os.environ.get("INGRESS_IP")
        if not ingress_ip:
            raise click.ClickException(
                "Missing base URL. Provide --base-url or set $RAGENGINE_URL, or set $INGRESS_IP."
            )
        base_url_eff = f"http://{ingress_ip}"

    if not base_url_eff.endswith("/"):
        base_url_eff += "/"
    return base_url_eff


def _print_result(result: Dict[str, Any], *, mode: str, json_out: bool, show_sources: bool) -> None:
    import json

    if mode in {"chat", "query"} and not json_out:
        text_out = ""
        try:
            choices = result.get("choices") or []
            if choices:
                msg = (choices[0] or {}).get("message") or {}
                text_out = msg.get("content") or ""
        except Exception:
            text_out = ""

        if text_out:
            click.echo(text_out)
        else:
            click.echo(json.dumps(result, indent=2, sort_keys=True))

        if show_sources and isinstance(result, dict) and result.get("source_nodes"):
            click.echo("\n---\nsource_nodes:")
            click.echo(json.dumps(result.get("source_nodes"), indent=2, sort_keys=True))
    else:
        click.echo(json.dumps(result, indent=2, sort_keys=True))


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--file", "file_path", type=click.Path(exists=True, dir_okay=False), help="Path to .txt file (required for create/update)")
@click.option("--index", required=True, help="Index name (e.g., rag_index)")
@click.option(
    "--mode",
    type=click.Choice(["create", "update", "list", "chat", "query"], case_sensitive=False),
    default="create",
    show_default=True,
    help=(
        "create: POST /rag/index (create index + add docs). "
        "update: POST /indexes/{index}/documents. "
        "list: GET /indexes/{index}/documents. "
        "chat/query: POST /v1/chat/completions (OpenAI-compatible)"
    ),
)
@click.option(
    "--base-url",
    default=None,
    envvar="RAGENGINE_URL",
    show_envvar=True,
    help='Base URL to RagEngine (e.g., "http://1.2.3.4/rag"). If omitted, uses $RAGENGINE_URL or http://$INGRESS_IP.',
)
@click.option("--max-chars", type=int, default=3000, show_default=True, help="Max characters per chunk")
@click.option("--overlap-chars", type=int, default=200, show_default=True, help="Overlap characters between chunks")
@click.option("--limit", type=int, default=10, show_default=True, help="List mode: max docs to return (default 10, max 100)")
@click.option("--offset", type=int, default=0, show_default=True, help="List mode: offset (default 0)")
@click.option(
    "--max-text-length",
    type=int,
    default=1000,
    show_default=True,
    help="List mode: max text length returned per doc",
)
@click.option(
    "--metadata-filter",
    default=None,
    help='List mode: JSON string to filter by metadata, e.g. {"author":"kaito"}',
)
@click.option("--question", default=None, help="Chat mode: user question/prompt")
@click.option("--question-file", type=click.Path(exists=True, dir_okay=False), default=None, help="Chat mode: read question from a text file")
@click.option("--system", default="You are a helpful assistant.", show_default=True, help="Chat mode: system message")
@click.option(
    "--model",
    default=None,
    envvar="RAGENGINE_MODEL",
    show_envvar=True,
    help="Chat mode: model identifier (compatibility field). If omitted, uses $RAGENGINE_MODEL, else 'example_model'.",
)
@click.option("--temperature", type=float, default=0.7, show_default=True, help="Chat mode: sampling temperature (0.0 to 1.0)")
@click.option("--max-tokens", type=int, default=2048, show_default=True, help="Chat mode: max tokens to generate")
@click.option(
    "--context-token-ratio",
    type=float,
    default=0.5,
    show_default=True,
    help="Chat mode: percentage of context tokens reserved for RAG documents",
)
@click.option("--json", "json_out", is_flag=True, help="Chat mode: print full JSON response (otherwise prints just assistant text)")
@click.option("--show-sources", is_flag=True, help="Chat mode: include source_nodes (if returned) in output")
@click.option("--timeout", type=int, default=60, show_default=True, help="HTTP timeout seconds")
@click.option("--retries", type=int, default=3, show_default=True, help="HTTP retries")
def cli(
    file_path: str | None,
    index: str,
    mode: str,
    base_url: str | None,
    max_chars: int,
    overlap_chars: int,
    limit: int,
    offset: int,
    max_text_length: int,
    metadata_filter: str | None,
    question: str | None,
    question_file: str | None,
    system: str,
    model: str | None,
    temperature: float,
    max_tokens: int,
    context_token_ratio: float,
    json_out: bool,
    show_sources: bool,
    timeout: int,
    retries: int,
) -> None:
    """Ingest a .txt file into RagEngine and query it via OpenAI-compatible endpoints."""

    mode_l = mode.lower().strip()

    if mode_l in {"create", "update"} and not file_path:
        raise click.ClickException("--file is required for create/update.")

    base_url_eff = _resolve_base_url(base_url)

    if mode_l == "list":
        endpoint = urljoin(base_url_eff, f"indexes/{index}/documents")
        params: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "max_text_length": max_text_length,
        }
        if metadata_filter:
            try:
                params["metadata_filter"] = _parse_metadata_filter(metadata_filter)
            except Exception as e:
                raise click.ClickException(f"Invalid --metadata-filter JSON: {e}")

        result = request_json_with_retries(
            "GET",
            endpoint,
            params=params,
            timeout_s=timeout,
            retries=retries,
        )
        _print_result(result, mode=mode_l, json_out=True, show_sources=False)
        return

    if mode_l in {"chat", "query"}:
        q = question
        if question_file:
            try:
                q = _read_text_file(question_file).strip()
            except Exception as e:
                raise click.ClickException(f"Failed to read --question-file: {e}")
        if not q:
            raise click.ClickException("Chat/query mode requires --question or --question-file.")

        model_name = model or "example_model"
        endpoint = urljoin(base_url_eff, "v1/chat/completions")
        payload = {
            "index_name": index,
            "model": model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": q},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "context_token_ratio": context_token_ratio,
        }
        result = request_json_with_retries(
            "POST",
            endpoint,
            payload=payload,
            timeout_s=timeout,
            retries=retries,
        )
        _print_result(result, mode=mode_l, json_out=json_out, show_sources=show_sources)
        return

    # create/update
    assert file_path is not None
    docs = build_documents(
        file_path,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        extra_metadata={"index_name": index},
    )

    if mode_l == "create":
        endpoint = urljoin(base_url_eff, "rag/index")
        payload = {
            "index_name": index,
            "documents": [{"text": text, "metadata": md} for (_doc_id, text, md) in docs],
        }
    else:
        endpoint = urljoin(base_url_eff, f"indexes/{index}/documents")
        payload = {
            "documents": [
                {
                    "doc_id": doc_id,
                    "text": text,
                    "hash_value": _sha256_hex(text),
                    "metadata": md,
                }
                for (doc_id, text, md) in docs
            ]
        }

    result = request_json_with_retries(
        "POST",
        endpoint,
        payload=payload,
        timeout_s=timeout,
        retries=retries,
    )
    _print_result(result, mode=mode_l, json_out=True, show_sources=False)


if __name__ == "__main__":
    cli()