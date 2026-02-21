from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from ragengine_ingest_adapter import ingest_raw_text, list_documents, list_indexes
from sidebar_nav import render_sidebar_nav

st.set_page_config(page_title="Document Ingestion", layout="wide")
render_sidebar_nav(current="document-ingestion")

st.title("Document Ingestion & Index Management")
st.caption("Upload or paste content, ingest into RagEngine, and manage indexes.")


def _parse_index_names(payload: Any) -> list[str]:
    names: set[str] = set()

    def add_from_item(item: Any) -> None:
        if isinstance(item, str) and item.strip():
            names.add(item.strip())
            return
        if isinstance(item, dict):
            for key in ("index_name", "name", "id"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    names.add(val.strip())
                    return

    if isinstance(payload, list):
        for item in payload:
            add_from_item(item)
    elif isinstance(payload, dict):
        for key in ("indexes", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    add_from_item(item)

    return sorted(names)


def _parse_metadata_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Metadata JSON must be an object")
    return parsed


def _extract_documents(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("documents", "items", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _normalize_text_name(name_hint: str) -> str:
    base = (name_hint or "pasted-text").strip()
    if not base:
        base = "pasted-text"
    if not Path(base).suffix:
        base = f"{base}.md"
    return base


def _derive_paste_status_label(result: Any, mode: str) -> str:
    if isinstance(result, dict):
        ingestion_status = str(result.get("ingestion_status", "")).strip().lower()
        if ingestion_status == "created":
            return "Created"
        if ingestion_status == "updated":
            return "Updated"
    if isinstance(result, dict) and result.get("skipped") and result.get("reason") == "filename_exists":
        return "Skipped: filename exists"
    return "Updated" if mode == "update" else "Created"


def _extract_paste_filename(result: Any, text_name_hint: str) -> str:
    if isinstance(result, dict):
        direct = result.get("filename")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
    return _normalize_text_name(text_name_hint)


def _render_status_badge(label: str) -> None:
    icon = "✅" if label == "Created" else ("🔄" if label == "Updated" else "⚠️")
    badge_text = f"{icon} {label}"
    st.markdown(
        (
            "<span style=\"display:inline-block;padding:0.2rem 0.65rem;"
            "border-radius:999px;border:1px solid var(--text-color);font-weight:600;\">"
            f"{badge_text}</span>"
        ),
        unsafe_allow_html=True,
    )


if "ingest_last_indexes" not in st.session_state:
    st.session_state.ingest_last_indexes = []
if "ingest_last_indexes_raw" not in st.session_state:
    st.session_state.ingest_last_indexes_raw = None
if "ingest_last_endpoint" not in st.session_state:
    st.session_state.ingest_last_endpoint = ""
if "ingest_index_refresh_error" not in st.session_state:
    st.session_state.ingest_index_refresh_error = ""
if "index_browser_result" not in st.session_state:
    st.session_state.index_browser_result = None
if "index_browser_error" not in st.session_state:
    st.session_state.index_browser_error = ""
if "index_browser_request_key" not in st.session_state:
    st.session_state.index_browser_request_key = ""
if "index_browser_filename_filter" not in st.session_state:
    st.session_state.index_browser_filename_filter = ""
if "ingest_active_section" not in st.session_state:
    st.session_state.ingest_active_section = "Upload documents"
if "paste_last_status" not in st.session_state:
    st.session_state.paste_last_status = ""
if "paste_last_filename" not in st.session_state:
    st.session_state.paste_last_filename = ""
if "paste_last_index" not in st.session_state:
    st.session_state.paste_last_index = ""

with st.sidebar.expander("RagEngine connection", expanded=True):
    endpoint = st.text_input(
        "RagEngine base URL",
        value=st.session_state.get("ingest_endpoint", "http://ai.roykim.ca/rag-nostorage"),
        help="Base URL for RagEngine, e.g. http://ai.roykim.ca/rag-nostorage",
    )
    st.session_state.ingest_endpoint = endpoint

    connect_timeout = int(
        st.number_input("Connect timeout (s)", min_value=1, max_value=120, value=5, step=1)
    )
    timeout = int(st.number_input("Request timeout (s)", min_value=5, max_value=600, value=60, step=5))
    retries = int(st.number_input("Retries", min_value=1, max_value=10, value=3, step=1))

    refresh_clicked = st.button("Refresh index list", type="secondary")

auto_refresh_needed = (
    not st.session_state.get("ingest_last_indexes")
    or st.session_state.get("ingest_last_endpoint", "") != endpoint.strip()
)

if refresh_clicked or auto_refresh_needed:
    try:
        response = list_indexes(
            base_url=endpoint,
            connect_timeout_s=connect_timeout,
            timeout_s=timeout,
            retries=retries,
        )
        st.session_state.ingest_last_indexes_raw = response
        st.session_state.ingest_last_indexes = _parse_index_names(response)
        st.session_state.ingest_last_endpoint = endpoint.strip()
        st.session_state.ingest_index_refresh_error = ""
        if refresh_clicked:
            st.success("Index list refreshed")
    except Exception as e:  # noqa: BLE001
        st.session_state.ingest_last_indexes = []
        st.session_state.ingest_last_indexes_raw = None
        st.session_state.ingest_last_endpoint = endpoint.strip()
        st.session_state.ingest_index_refresh_error = str(e)
        if refresh_clicked:
            st.error(f"Failed to list indexes: {e}")

if st.session_state.get("ingest_index_refresh_error"):
    st.warning(
        "Could not auto-load index list from the selected endpoint. "
        f"Error: {st.session_state['ingest_index_refresh_error']}"
    )

existing_indexes = st.session_state.get("ingest_last_indexes", [])
index_options = ["Create new index", *existing_indexes]
selected_index_mode = st.selectbox(
    "Target index",
    index_options,
    index=0,
    help="Select an existing index or create a new one.",
)

if selected_index_mode == "Create new index":
    index_name = st.text_input("New index name", value="rag_index")
    ingest_mode = "create"
else:
    index_name = selected_index_mode
    ingest_mode = st.selectbox(
        "Ingestion mode",
        ["update", "create"],
        index=0,
        help="Use update for existing index documents; create can create/rebuild by endpoint behavior.",
    )

with st.expander("Chunking & metadata", expanded=False):
    max_chars = int(st.number_input("Max chars per chunk", min_value=200, max_value=10000, value=3000, step=100))
    overlap_chars = int(st.number_input("Overlap chars", min_value=0, max_value=2000, value=200, step=50))
    metadata_json = st.text_area(
        "Metadata JSON (optional)",
        value='{"source":"streamlit-ui"}',
        height=120,
        help="JSON object merged into metadata for each ingested chunk.",
    )

source_sections = ["Upload documents", "Paste text", "Index operations", "Index browser"]
source_section = st.radio(
    "Section",
    source_sections,
    key="ingest_active_section",
    horizontal=True,
)

if source_section == "Upload documents":
    uploaded_files = st.file_uploader(
        "Select documents",
        type=["txt", "md", "markdown"],
        accept_multiple_files=True,
    )

    if st.button("Ingest uploaded files", type="primary", disabled=not uploaded_files):
        if not index_name.strip():
            st.error("Index name is required")
        else:
            try:
                metadata = _parse_metadata_json(metadata_json)
            except Exception as e:  # noqa: BLE001
                st.error(f"Invalid metadata JSON: {e}")
            else:
                results: list[dict[str, Any]] = []
                skipped_messages: list[str] = []
                overwritten_messages: list[str] = []
                for file in uploaded_files or []:
                    try:
                        file_text = file.getvalue().decode("utf-8")
                    except Exception as decode_error:  # noqa: BLE001
                        results.append(
                            {
                                "file": file.name,
                                "error": f"Failed to decode as UTF-8 text: {decode_error}",
                            }
                        )
                        continue

                    result = ingest_raw_text(
                        text=file_text,
                        name_hint=file.name,
                        base_url=endpoint,
                        index_name=index_name.strip(),
                        mode=ingest_mode,
                        max_chars=max_chars,
                        overlap_chars=overlap_chars,
                        metadata=metadata,
                        connect_timeout_s=connect_timeout,
                        timeout_s=timeout,
                        retries=retries,
                    )

                    if (
                        ingest_mode == "create"
                        and isinstance(result, dict)
                        and result.get("skipped")
                        and result.get("reason") == "filename_exists"
                    ):
                        overwrite_result = ingest_raw_text(
                            text=file_text,
                            name_hint=file.name,
                            base_url=endpoint,
                            index_name=index_name.strip(),
                            mode="update",
                            max_chars=max_chars,
                            overlap_chars=overlap_chars,
                            metadata=metadata,
                            connect_timeout_s=connect_timeout,
                            timeout_s=timeout,
                            retries=retries,
                        )
                        result = {
                            "overwritten": True,
                            "overwrite_mode": "update",
                            "original_create_result": result,
                            "overwrite_result": overwrite_result,
                        }
                        overwritten_messages.append(
                            f"Overwrote existing document for filename '{file.name}' in index '{index_name.strip()}'."
                        )

                    results.append({"file": file.name, "result": result})
                    if isinstance(result, dict) and result.get("skipped"):
                        skipped_messages.append(str(result.get("message", "Skipped")))

                    st.session_state.index_browser_request_key = ""
                    st.session_state.index_browser_result = None
                    st.session_state.index_browser_error = ""
                created_count = len([r for r in results if not (isinstance(r.get("result"), dict) and r["result"].get("skipped"))])
                if created_count > 0:
                    st.success(f"Ingested {created_count} file(s) into '{index_name.strip()}'.")
                if overwritten_messages:
                    for msg in overwritten_messages:
                        st.info(msg)
                if skipped_messages:
                    for msg in skipped_messages:
                        st.info(msg)
                st.json(results, expanded=False)

if source_section == "Paste text":
    text_name_hint = st.text_input("Text name", value="pasted-text")
    pasted_text = st.text_area("Paste text to ingest", height=260)

    if st.button("Ingest pasted text", type="primary"):
        if not pasted_text.strip():
            st.error("Please paste some text to ingest.")
        elif not index_name.strip():
            st.error("Index name is required")
        else:
            try:
                metadata = _parse_metadata_json(metadata_json)
                result = ingest_raw_text(
                    text=pasted_text,
                    name_hint=text_name_hint,
                    base_url=endpoint,
                    index_name=index_name.strip(),
                    mode=ingest_mode,
                    max_chars=max_chars,
                    overlap_chars=overlap_chars,
                    metadata=metadata,
                    connect_timeout_s=connect_timeout,
                    timeout_s=timeout,
                    retries=retries,
                )

                if (
                    ingest_mode == "create"
                    and isinstance(result, dict)
                    and result.get("skipped")
                    and result.get("reason") == "filename_exists"
                ):
                    overwrite_result = ingest_raw_text(
                        text=pasted_text,
                        name_hint=text_name_hint,
                        base_url=endpoint,
                        index_name=index_name.strip(),
                        mode="update",
                        max_chars=max_chars,
                        overlap_chars=overlap_chars,
                        metadata=metadata,
                        connect_timeout_s=connect_timeout,
                        timeout_s=timeout,
                        retries=retries,
                    )
                    result = {
                        "overwritten": True,
                        "overwrite_mode": "update",
                        "ingestion_status": "updated",
                        "filename": _normalize_text_name(text_name_hint),
                        "original_create_result": result,
                        "overwrite_result": overwrite_result,
                    }

                st.session_state.index_browser_request_key = ""
                st.session_state.index_browser_result = None
                st.session_state.index_browser_error = ""
                status_label = _derive_paste_status_label(result, ingest_mode)
                filename_for_action = _extract_paste_filename(result, text_name_hint)
                st.session_state.paste_last_status = status_label
                st.session_state.paste_last_filename = filename_for_action
                st.session_state.paste_last_index = index_name.strip()

                if status_label == "Skipped: filename exists":
                    st.info(str(result.get("message", "Document already exists; skipped.")))
                else:
                    st.success(f"{status_label} pasted text in '{index_name.strip()}'.")
                    if isinstance(result, dict) and result.get("overwritten"):
                        st.info(
                            f"Overwrote existing document for filename '{filename_for_action}' in index '{index_name.strip()}'."
                        )
                st.json(result, expanded=False)
            except Exception as e:  # noqa: BLE001
                st.error(f"Ingestion failed: {e}")

    if st.session_state.get("paste_last_status"):
        st.write("Status")
        _render_status_badge(st.session_state.paste_last_status)

        last_filename = st.session_state.get("paste_last_filename", "").strip()
        if last_filename:
            st.caption(f"Filename: {last_filename}")
            if st.button(
                "Switch to Index browser for this filename",
                type="secondary",
                key="switch_to_browser_for_filename",
            ):
                st.session_state.index_browser_filename_filter = last_filename
                st.session_state.index_browser_offset = 0
                st.session_state.index_browser_request_key = ""
                st.session_state.ingest_active_section = "Index browser"
                st.rerun()

if source_section == "Index operations":
    left, right = st.columns(2)
    with left:
        if st.button("List indexes", type="secondary"):
            try:
                response = list_indexes(
                    base_url=endpoint,
                    connect_timeout_s=connect_timeout,
                    timeout_s=timeout,
                    retries=retries,
                )
                parsed = _parse_index_names(response)
                st.session_state.ingest_last_indexes = parsed
                st.session_state.ingest_last_indexes_raw = response
                st.success(f"Found {len(parsed)} index(es).")
                if parsed:
                    st.write(parsed)
                st.json(response, expanded=False)
            except Exception as e:  # noqa: BLE001
                st.error(f"Failed to list indexes: {e}")

    with right:
        docs_limit = int(st.number_input("List documents limit", min_value=1, max_value=200, value=10))
        docs_offset = int(st.number_input("Offset", min_value=0, max_value=10000, value=0))
        docs_max_len = int(st.number_input("Max text length", min_value=50, max_value=10000, value=600, step=50))

        if st.button("List documents", type="secondary"):
            if not index_name.strip():
                st.error("Choose or enter an index name first.")
            else:
                try:
                    response = list_documents(
                        base_url=endpoint,
                        index_name=index_name.strip(),
                        limit=docs_limit,
                        offset=docs_offset,
                        max_text_length=docs_max_len,
                        connect_timeout_s=connect_timeout,
                        timeout_s=timeout,
                        retries=retries,
                    )
                    st.json(response, expanded=False)
                except Exception as e:  # noqa: BLE001
                    st.error(f"Failed to list documents: {e}")

if source_section == "Index browser":
    st.subheader("Index browser")
    st.caption("Browse chunks and metadata for the currently selected target index.")

    browser_filename_filter = st.text_input(
        "Filename filter",
        key="index_browser_filename_filter",
        help="Optional exact filename match (metadata.filename).",
    )

    browse_limit = int(
        st.number_input(
            "Browse limit",
            min_value=1,
            max_value=500,
            value=50,
            key="index_browser_limit",
            help="Maximum number of chunks loaded for browsing.",
        )
    )
    browse_offset = int(
        st.number_input(
            "Browse offset",
            min_value=0,
            max_value=100000,
            value=0,
            key="index_browser_offset",
            help="Pagination offset for chunk browsing.",
        )
    )
    browse_max_text = int(
        st.number_input(
            "Browse max text length",
            min_value=50,
            max_value=20000,
            value=3000,
            step=50,
            key="index_browser_max_text",
            help="Maximum text length returned per chunk in browser mode.",
        )
    )

    if not index_name.strip() or selected_index_mode == "Create new index":
        st.info("Select an existing index in Target index to browse chunks.")
    else:
        filter_value = browser_filename_filter.strip()
        request_key = "|".join(
            [
                endpoint.strip(),
                index_name.strip(),
                str(browse_limit),
                str(browse_offset),
                str(browse_max_text),
                filter_value,
            ]
        )

        should_refresh = st.button("Refresh browser data", type="secondary")
        auto_refresh = st.session_state.get("index_browser_request_key") != request_key

        if should_refresh or auto_refresh:
            try:
                response = list_documents(
                    base_url=endpoint,
                    index_name=index_name.strip(),
                    limit=browse_limit,
                    offset=browse_offset,
                    max_text_length=browse_max_text,
                    metadata_filter={"filename": filter_value} if filter_value else None,
                    connect_timeout_s=connect_timeout,
                    timeout_s=timeout,
                    retries=retries,
                )
                st.session_state.index_browser_result = response
                st.session_state.index_browser_error = ""
                st.session_state.index_browser_request_key = request_key
            except Exception as e:  # noqa: BLE001
                st.session_state.index_browser_result = None
                st.session_state.index_browser_error = str(e)
                st.session_state.index_browser_request_key = request_key

        if st.session_state.index_browser_error:
            st.error(f"Failed to load index data: {st.session_state.index_browser_error}")

        payload = st.session_state.get("index_browser_result")
        docs = _extract_documents(payload)
        if not docs:
            st.info("No documents/chunks returned for this index and range.")
        else:
            filename_count = len(
                {
                    str((doc.get("metadata") or {}).get("filename", "")).strip()
                    for doc in docs
                    if str((doc.get("metadata") or {}).get("filename", "")).strip()
                }
            )
            c1, c2 = st.columns(2)
            c1.metric("Chunks loaded", len(docs))
            c2.metric("Unique files", filename_count)

            table_rows: list[dict[str, Any]] = []
            for i, doc in enumerate(docs):
                metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
                text = str(doc.get("text", ""))
                table_rows.append(
                    {
                        "#": i,
                        "doc_id": str(doc.get("doc_id", "")),
                        "filename": str((metadata or {}).get("filename", "")),
                        "chunk": (metadata or {}).get("chunk_index"),
                        "chunks_total": (metadata or {}).get("chunk_count"),
                        "text_chars": len(text),
                    }
                )

            table_event = st.dataframe(
                table_rows,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="index_browser_table",
            )

            selected_row = 0
            try:
                selected_rows = (table_event.selection or {}).get("rows", [])
                if isinstance(selected_rows, list) and selected_rows:
                    selected_row = int(selected_rows[0])
            except Exception:
                selected_row = 0

            selected_row = max(0, min(selected_row, len(docs) - 1))
            st.caption(f"Selected chunk row: {selected_row}")

            selected_doc = docs[selected_row]
            selected_md = (
                selected_doc.get("metadata")
                if isinstance(selected_doc.get("metadata"), dict)
                else {}
            )
            selected_text = str(selected_doc.get("text", ""))

            detail_tab_text, detail_tab_meta, detail_tab_raw = st.tabs(["Chunk text", "Metadata", "Raw"])
            with detail_tab_text:
                st.caption("Chunk content")
                st.code(selected_text, language="text")
            with detail_tab_meta:
                st.json(selected_md, expanded=True)
            with detail_tab_raw:
                st.json(selected_doc, expanded=False)

st.divider()
st.caption("This page is designed for extensibility. Add new management actions as additional tabs/actions using ragengine_ingest_adapter.py.")
