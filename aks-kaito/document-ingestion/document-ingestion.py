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

import argparse
import datetime as dt
import hashlib
import os
import sys
import time
import uuid
from typing import List, Dict, Any, Iterable, Tuple
from urllib.parse import urljoin

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


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest a .txt file into RagEngine.")
    ap.add_argument("--file", help="Path to .txt file (required for create/update)")
    ap.add_argument("--index", required=True, help="Index name (e.g., rag_index)")
    ap.add_argument(
        "--mode",
        choices=["create", "update", "list", "chat", "query"],
        default="create",
        help=(
            "create: POST /rag/index (create index + add docs). "
            "update: POST /indexes/{index}/documents. "
            "list: GET /indexes/{index}/documents. "
            "chat/query: POST /v1/chat/completions (OpenAI-compatible)"
        ),
    )
    ap.add_argument(
        "--base-url",
        default=None,
        help='Base URL to RagEngine (e.g., "http://1.2.3.4"). If omitted, uses $RAGENGINE_URL or http://$INGRESS_IP',
    )
    ap.add_argument("--max-chars", type=int, default=3000, help="Max characters per chunk")
    ap.add_argument("--overlap-chars", type=int, default=200, help="Overlap characters between chunks")
    ap.add_argument("--limit", type=int, default=10, help="List mode: max docs to return (default 10, max 100)")
    ap.add_argument("--offset", type=int, default=0, help="List mode: offset (default 0)")
    ap.add_argument(
        "--max-text-length",
        type=int,
        default=1000,
        help="List mode: max text length returned per doc (default 1000)",
    )
    ap.add_argument(
        "--metadata-filter",
        default=None,
        help='List mode: JSON string to filter by metadata, e.g. {"author":"kaito"}',
    )

    ap.add_argument("--question", default=None, help="Chat mode: user question/prompt")
    ap.add_argument("--question-file", default=None, help="Chat mode: read question from a text file")
    ap.add_argument(
        "--system",
        default="You are a helpful assistant.",
        help="Chat mode: system message (optional)",
    )
    ap.add_argument(
        "--model",
        default=None,
        help=(
            "Chat mode: model identifier (compatibility field). "
            "If omitted, uses $RAGENGINE_MODEL, else 'example_model'."
        ),
    )
    ap.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Chat mode: sampling temperature (0.0 to 1.0)",
    )
    ap.add_argument(
        "--max-tokens",
        type=int,
        default=2048,
        help="Chat mode: max tokens to generate",
    )
    ap.add_argument(
        "--context-token-ratio",
        type=float,
        default=0.5,
        help="Chat mode: percentage of context tokens reserved for RAG documents",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Chat mode: print full JSON response (otherwise prints just assistant text)",
    )
    ap.add_argument(
        "--show-sources",
        action="store_true",
        help="Chat mode: include source_nodes (if returned) in output",
    )
    ap.add_argument("--timeout", type=int, default=60, help="HTTP timeout seconds")
    ap.add_argument("--retries", type=int, default=3, help="HTTP retries")

    args = ap.parse_args()

    if args.mode in {"create", "update"}:
        if not args.file:
            print("--file is required for create/update.", file=sys.stderr)
            return 2
        if not os.path.isfile(args.file):
            print(f"File not found: {args.file}", file=sys.stderr)
            return 2

    base_url = args.base_url or os.environ.get("RAGENGINE_URL")
    if not base_url:
        ingress_ip = os.environ.get("INGRESS_IP")
        if not ingress_ip:
            print(
                "Missing base URL. Provide --base-url or set $RAGENGINE_URL, or set $INGRESS_IP.",
                file=sys.stderr,
            )
            return 2
        base_url = f"http://{ingress_ip}"

    # Ensure trailing slash for urljoin behavior
    if not base_url.endswith("/"):
        base_url += "/"

    if args.mode == "list":
        endpoint = urljoin(base_url, f"indexes/{args.index}/documents")
        params: Dict[str, Any] = {
            "limit": args.limit,
            "offset": args.offset,
            "max_text_length": args.max_text_length,
        }
        if args.metadata_filter:
            try:
                params["metadata_filter"] = _parse_metadata_filter(args.metadata_filter)
            except Exception as e:
                print(f"Invalid --metadata-filter JSON: {e}", file=sys.stderr)
                return 2
        result = request_json_with_retries(
            "GET",
            endpoint,
            params=params,
            timeout_s=args.timeout,
            retries=args.retries,
        )
    elif args.mode in {"chat", "query"}:
        question = args.question
        if args.question_file:
            try:
                question = _read_text_file(args.question_file).strip()
            except Exception as e:
                print(f"Failed to read --question-file: {e}", file=sys.stderr)
                return 2
        if not question:
            print("Chat mode requires --question or --question-file.", file=sys.stderr)
            return 2

        model_name = args.model or os.environ.get("RAGENGINE_MODEL") or "example_model"

        endpoint = urljoin(base_url, "v1/chat/completions")
        payload = {
            "index_name": args.index,
            "model": model_name,
            "messages": [
                {"role": "system", "content": args.system},
                {"role": "user", "content": question},
            ],
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "context_token_ratio": args.context_token_ratio,
        }
        result = request_json_with_retries(
            "POST",
            endpoint,
            payload=payload,
            timeout_s=args.timeout,
            retries=args.retries,
        )
    else:
        docs = build_documents(
            args.file,
            max_chars=args.max_chars,
            overlap_chars=args.overlap_chars,
            extra_metadata={"index_name": args.index},
        )

        if args.mode == "create":
            endpoint = urljoin(base_url, "rag/index")
            payload = {
                "index_name": args.index,
                "documents": [{"text": text, "metadata": md} for (_doc_id, text, md) in docs],
            }
        else:
            endpoint = urljoin(base_url, f"indexes/{args.index}/documents")
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
            timeout_s=args.timeout,
            retries=args.retries,
        )

    # Print output (no external deps)
    import json

    if args.mode in {"chat", "query"} and not args.json:
        text_out = ""
        try:
            choices = result.get("choices") or []
            if choices:
                msg = (choices[0] or {}).get("message") or {}
                text_out = msg.get("content") or ""
        except Exception:
            text_out = ""

        if text_out:
            print(text_out)
        else:
            # Fallback: show full response if shape is unexpected
            print(json.dumps(result, indent=2, sort_keys=True))

        if args.show_sources and isinstance(result, dict) and result.get("source_nodes"):
            print("\n---\nsource_nodes:")
            print(json.dumps(result.get("source_nodes"), indent=2, sort_keys=True))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())