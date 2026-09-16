from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin


def _load_ragengine_module():
    script_path = (
        Path(__file__).resolve().parent.parent / "ragengine-ingest-docs" / "ragengine-ingest-docs.py"
    )
    if not script_path.exists():
        raise FileNotFoundError(f"RagEngine module not found: {script_path}")

    spec = importlib.util.spec_from_file_location("ragengine_ingest_docs_module", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_RAGENGINE_MODULE = _load_ragengine_module()


def resolve_base_url(base_url: str) -> str:
    return _RAGENGINE_MODULE._resolve_base_url(base_url)


def list_indexes(
    *,
    base_url: str,
    connect_timeout_s: int,
    timeout_s: int,
    retries: int,
) -> dict[str, Any]:
    base_url_eff = resolve_base_url(base_url)
    endpoint = urljoin(base_url_eff, "indexes")
    return _RAGENGINE_MODULE.request_json_with_retries(
        "GET",
        endpoint,
        connect_timeout_s=connect_timeout_s,
        timeout_s=timeout_s,
        retries=retries,
    )


def list_documents(
    *,
    base_url: str,
    index_name: str,
    limit: int,
    offset: int,
    max_text_length: int,
    connect_timeout_s: int,
    timeout_s: int,
    retries: int,
    metadata_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_url_eff = resolve_base_url(base_url)
    endpoint = urljoin(base_url_eff, f"indexes/{index_name}/documents")
    params = {
        "limit": int(limit),
        "offset": int(offset),
        "max_text_length": int(max_text_length),
    }
    if metadata_filter:
        params["metadata_filter"] = json.dumps(metadata_filter, separators=(",", ":"), ensure_ascii=False)
    return _RAGENGINE_MODULE.request_json_with_retries(
        "GET",
        endpoint,
        params=params,
        connect_timeout_s=connect_timeout_s,
        timeout_s=timeout_s,
        retries=retries,
    )


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_documents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("documents", "items", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _filename_exists_in_index(
    *,
    base_url: str,
    index_name: str,
    filename: str,
    connect_timeout_s: int,
    timeout_s: int,
    retries: int,
) -> bool:
    try:
        result = list_documents(
            base_url=base_url,
            index_name=index_name,
            limit=1,
            offset=0,
            max_text_length=1,
            connect_timeout_s=connect_timeout_s,
            timeout_s=timeout_s,
            retries=retries,
            metadata_filter={"filename": filename},
        )
    except Exception as e:  # noqa: BLE001
        # If index doesn't exist yet, create flow should proceed.
        if "HTTP 404" in str(e):
            return False
        raise

    docs = _extract_documents(result)
    return len(docs) > 0


def _build_documents_from_text(
    *,
    text: str,
    logical_filename: str,
    max_chars: int,
    overlap_chars: int,
    extra_metadata: dict[str, Any] | None,
) -> list[tuple[str, str, dict[str, Any]]]:
    content = text.strip()
    if not content:
        return []

    chunks = _RAGENGINE_MODULE.chunk_text(content, max_chars=max_chars, overlap_chars=overlap_chars)
    virtual_path = f"virtual://streamlit/{logical_filename}"

    base_metadata: dict[str, Any] = {
        "source_type": "txt",
        "filename": logical_filename,
        "path": virtual_path,
        "ingested_at": _RAGENGINE_MODULE._now_iso(),
    }
    if extra_metadata:
        base_metadata.update(extra_metadata)

    docs: list[tuple[str, str, dict[str, Any]]] = []
    for i, chunk in enumerate(chunks):
        doc_id = _RAGENGINE_MODULE.make_doc_id(virtual_path, i)
        md = dict(base_metadata)
        md["chunk_index"] = i
        md["chunk_count"] = len(chunks)
        docs.append((doc_id, chunk, md))
    return docs


def _post_create_documents(
    *,
    base_url_eff: str,
    index_name: str,
    docs: list[tuple[str, str, dict[str, Any]]],
    connect_timeout_s: int,
    timeout_s: int,
    retries: int,
) -> dict[str, Any]:
    endpoint = urljoin(base_url_eff, _RAGENGINE_MODULE._create_endpoint_path(base_url_eff))
    payload = {
        "index_name": index_name,
        "documents": [{"text": text, "metadata": md} for (_doc_id, text, md) in docs],
    }
    return _RAGENGINE_MODULE.request_json_with_retries(
        "POST",
        endpoint,
        payload=payload,
        connect_timeout_s=connect_timeout_s,
        timeout_s=timeout_s,
        retries=retries,
    )


def _post_update_documents(
    *,
    base_url_eff: str,
    index_name: str,
    docs: list[tuple[str, str, dict[str, Any]]],
    connect_timeout_s: int,
    timeout_s: int,
    retries: int,
) -> dict[str, Any]:
    endpoint = urljoin(base_url_eff, f"indexes/{index_name}/documents")
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
    return _RAGENGINE_MODULE.request_json_with_retries(
        "POST",
        endpoint,
        payload=payload,
        connect_timeout_s=connect_timeout_s,
        timeout_s=timeout_s,
        retries=retries,
    )


def _update_with_create_fallback(
    *,
    base_url_eff: str,
    base_url: str,
    index_name: str,
    docs: list[tuple[str, str, dict[str, Any]]],
    connect_timeout_s: int,
    timeout_s: int,
    retries: int,
) -> dict[str, Any]:
    update_result = _post_update_documents(
        base_url_eff=base_url_eff,
        index_name=index_name,
        docs=docs,
        connect_timeout_s=connect_timeout_s,
        timeout_s=timeout_s,
        retries=retries,
    )

    not_found = update_result.get("not_found_documents") if isinstance(update_result, dict) else None
    if not isinstance(not_found, list) or not not_found:
        result = dict(update_result) if isinstance(update_result, dict) else {"update_result": update_result}
        result["ingestion_status"] = "updated"
        return result

    missing_doc_ids: set[str] = set()
    for item in not_found:
        if isinstance(item, dict):
            doc_id = item.get("doc_id")
            if isinstance(doc_id, str) and doc_id:
                missing_doc_ids.add(doc_id)

    missing_docs = [entry for entry in docs if entry[0] in missing_doc_ids]
    if not missing_docs:
        result = dict(update_result) if isinstance(update_result, dict) else {"update_result": update_result}
        result["ingestion_status"] = "updated"
        return result

    create_result = _post_create_documents(
        base_url_eff=base_url_eff,
        index_name=index_name,
        docs=missing_docs,
        connect_timeout_s=connect_timeout_s,
        timeout_s=timeout_s,
        retries=retries,
    )

    return {
        "ingestion_status": "created",
        "upsert_fallback_used": True,
        "upsert_created_documents": len(missing_docs),
        "update_result": update_result,
        "create_fallback_result": create_result,
        "index_name": index_name,
        "base_url": resolve_base_url(base_url),
    }


def _normalize_logical_filename(name_hint: str) -> str:
    base = (name_hint or "pasted-text").strip()
    if not base:
        base = "pasted-text"
    if not Path(base).suffix:
        base = f"{base}.md"
    return base


def ingest_file(
    *,
    file_path: str,
    base_url: str,
    index_name: str,
    mode: Literal["create", "update"],
    max_chars: int,
    overlap_chars: int,
    metadata: dict[str, Any] | None,
    connect_timeout_s: int,
    timeout_s: int,
    retries: int,
) -> dict[str, Any]:
    if mode not in {"create", "update"}:
        raise ValueError("mode must be 'create' or 'update'")

    base_url_eff = resolve_base_url(base_url)
    user_metadata: dict[str, Any] = dict(metadata or {})
    user_metadata["index_name"] = index_name

    docs = _RAGENGINE_MODULE.build_documents(
        file_path,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        extra_metadata=user_metadata,
    )

    if mode == "create" and docs:
        candidate_filename = str((docs[0][2] or {}).get("filename", "")).strip()
        if candidate_filename and _filename_exists_in_index(
            base_url=base_url,
            index_name=index_name,
            filename=candidate_filename,
            connect_timeout_s=connect_timeout_s,
            timeout_s=timeout_s,
            retries=retries,
        ):
            return {
                "skipped": True,
                "reason": "filename_exists",
                "filename": candidate_filename,
                "index_name": index_name,
                "message": (
                    f"A document with filename '{candidate_filename}' already exists in index '{index_name}'. "
                    "Create mode skipped without adding new documents."
                ),
            }

    if mode == "create":
        result = _post_create_documents(
            base_url_eff=base_url_eff,
            index_name=index_name,
            docs=docs,
            connect_timeout_s=connect_timeout_s,
            timeout_s=timeout_s,
            retries=retries,
        )
        if isinstance(result, dict):
            result = dict(result)
            result.setdefault("ingestion_status", "created")
        return result

    return _update_with_create_fallback(
        base_url_eff=base_url_eff,
        base_url=base_url,
        index_name=index_name,
        docs=docs,
        connect_timeout_s=connect_timeout_s,
        timeout_s=timeout_s,
        retries=retries,
    )


def ingest_raw_text(
    *,
    text: str,
    name_hint: str,
    base_url: str,
    index_name: str,
    mode: Literal["create", "update"],
    max_chars: int,
    overlap_chars: int,
    metadata: dict[str, Any] | None,
    connect_timeout_s: int,
    timeout_s: int,
    retries: int,
) -> dict[str, Any]:
    content = text.strip()
    if not content:
        raise ValueError("Text content is empty")

    base_url_eff = resolve_base_url(base_url)
    logical_filename = _normalize_logical_filename(name_hint)

    user_metadata: dict[str, Any] = dict(metadata or {})
    user_metadata["index_name"] = index_name
    user_metadata["filename"] = logical_filename
    user_metadata["path"] = f"virtual://streamlit/{logical_filename}"

    if mode == "create" and _filename_exists_in_index(
        base_url=base_url,
        index_name=index_name,
        filename=logical_filename,
        connect_timeout_s=connect_timeout_s,
        timeout_s=timeout_s,
        retries=retries,
    ):
        return {
            "skipped": True,
            "reason": "filename_exists",
            "filename": logical_filename,
            "index_name": index_name,
            "message": (
                f"A document with filename '{logical_filename}' already exists in index '{index_name}'. "
                "Create mode skipped without adding new documents."
            ),
        }

    docs = _build_documents_from_text(
        text=content,
        logical_filename=logical_filename,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        extra_metadata=user_metadata,
    )

    if mode == "create":
        result = _post_create_documents(
            base_url_eff=base_url_eff,
            index_name=index_name,
            docs=docs,
            connect_timeout_s=connect_timeout_s,
            timeout_s=timeout_s,
            retries=retries,
        )
        if isinstance(result, dict):
            result = dict(result)
            result.setdefault("ingestion_status", "created")
        return result

    return _update_with_create_fallback(
        base_url_eff=base_url_eff,
        base_url=base_url,
        index_name=index_name,
        docs=docs,
        connect_timeout_s=connect_timeout_s,
        timeout_s=timeout_s,
        retries=retries,
    )
