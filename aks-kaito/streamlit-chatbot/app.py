from __future__ import annotations

import json
import os
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from catalog import KaitoApi, get_api_by_name, load_catalog, resolve_catalog_path
from kaito_openai_compat import (
    ChatCompletionError,
    chat_completions,
    iter_sse_chat_delta_text,
    parse_chat_completion_text,
    raise_for_status_with_body,
)

st.set_page_config(page_title="KAITO Chatbot", layout="wide")


def _init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "system", "content": "You are a helpful assistant."}]
    if "prompt_history" not in st.session_state:
        st.session_state.prompt_history = []


@st.cache_data(show_spinner=False)
def _load_catalog_cached(path: str):
    return load_catalog(path)


def _build_technical_data(
    *,
    resp,
    stream: bool,
    request_payload: dict[str, Any],
    rag_enforcement: dict[str, Any] | None = None,
    resp_json: dict[str, Any] | None = None,
    stream_chunks: list[str] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "request_url": resp.url,
        "request_payload": request_payload,
        "status_code": resp.status_code,
        "reason": resp.reason,
        "stream": stream,
        "response_headers": dict(resp.headers),
    }
    if resp.elapsed is not None:
        data["elapsed_ms"] = round(resp.elapsed.total_seconds() * 1000, 2)

    if stream:
        chunks = stream_chunks or []
        data["stream_chunks"] = chunks
        data["stream_chunk_count"] = len(chunks)
    else:
        data["response_json"] = resp_json or {}

    if rag_enforcement:
        data["rag_token_enforcement"] = rag_enforcement

    return data


def _render_technical_panel(
    message: dict[str, Any],
    key_suffix: str,
    *,
    expanded: bool = False,
) -> None:
    technical = message.get("technical")
    if not technical:
        return
    with st.expander("Technical response data", expanded=expanded):
        st.json(technical, expanded=False)


def _build_request_payload_preview(
    *,
    model: str,
    messages: list[dict[str, Any]],
    stream: bool,
    extra_payload: dict[str, Any],
) -> dict[str, Any]:
    payload_messages: list[dict[str, str]] = []
    for m in messages:
        payload_messages.append(
            {
                "role": str(m.get("role", "user")),
                "content": str(m.get("content", "")),
            }
        )

    payload: dict[str, Any] = {
        "model": model,
        "messages": payload_messages,
    }
    if extra_payload:
        payload.update(extra_payload)
    if stream:
        payload["stream"] = True
    return payload


def _select_request_messages(
    *,
    messages: list[dict[str, Any]],
    is_ragengine: bool,
) -> list[dict[str, Any]]:
    if not is_ragengine:
        return messages

    system_message: dict[str, Any] | None = None
    for message in messages:
        if str(message.get("role", "")).lower() == "system":
            system_message = message
            break

    latest_user: dict[str, Any] | None = None
    for message in reversed(messages):
        if str(message.get("role", "")).lower() == "user":
            latest_user = message
            break

    selected: list[dict[str, Any]] = []
    if system_message is not None:
        selected.append(system_message)
    if latest_user is not None:
        selected.append(latest_user)

    return selected or messages


def _is_low_quality_answer(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    words = [w for w in stripped.replace("\n", " ").split(" ") if w]
    if len(stripped) < 40:
        return True
    if stripped.startswith("/"):
        return True
    if stripped.endswith("?") and len(words) < 14:
        return True
    return False


def _build_source_nodes_fallback(source_nodes: list[dict[str, Any]]) -> str:
    if not source_nodes:
        return ""

    top = source_nodes[0]
    source_text = str(top.get("text", "")).strip()
    if not source_text:
        return ""

    bullet_lines: list[str] = []
    for line in source_text.splitlines():
        line = line.strip()
        if line.startswith("- ") and len(line) > 6:
            bullet_lines.append(line)
        if len(bullet_lines) >= 8:
            break

    title = "Model returned a low-quality answer; summarized from retrieved source:"
    if bullet_lines:
        return "\n".join([title, "", *bullet_lines])

    preview = source_text[:900].rstrip()
    return "\n".join([title, "", preview])


def _enable_chat_prompt_history_hotkeys(prompt_history: list[str]) -> None:
        history_json = json.dumps(prompt_history)
        components.html(
                f"""
                <script>
                (function() {{
                    const history = {history_json};
                    let idx = history.length;
                    let draft = "";

                    function setValue(el, value) {{
                        el.value = value;
                        el.dispatchEvent(new Event("input", {{ bubbles: true }}));
                        el.setSelectionRange(el.value.length, el.value.length);
                    }}

                    function bind() {{
                        const el = window.parent.document.querySelector('textarea[data-testid="stChatInputTextArea"]');
                        if (!el || el.dataset.promptHistoryBound === "1") return;
                        el.dataset.promptHistoryBound = "1";

                        el.addEventListener("keydown", function (e) {{
                            if (!history.length) return;

                            if (e.key === "ArrowUp") {{
                                if (el.selectionStart === 0 && el.selectionEnd === 0) {{
                                    e.preventDefault();
                                    if (idx === history.length) draft = el.value;
                                    idx = Math.max(0, idx - 1);
                                    setValue(el, history[idx] || "");
                                }}
                            }} else if (e.key === "ArrowDown") {{
                                if (el.selectionStart === el.value.length && el.selectionEnd === el.value.length) {{
                                    e.preventDefault();
                                    idx = Math.min(history.length, idx + 1);
                                    const nextValue = idx === history.length ? draft : (history[idx] || "");
                                    setValue(el, nextValue);
                                }}
                            }} else {{
                                idx = history.length;
                            }}
                        }});
                    }}

                    bind();
                    const observer = new MutationObserver(bind);
                    observer.observe(window.parent.document.body, {{ childList: true, subtree: true }});
                }})();
                </script>
                """,
                height=0,
        )


def _sidebar_config() -> dict[str, Any]:
    st.sidebar.title("KAITO Chat")

    catalog_path = resolve_catalog_path()
    catalog = _load_catalog_cached(catalog_path)

    with st.sidebar.expander("Ingress quick select", expanded=True):
        ingress_base = st.text_input(
            "Ingress base URL",
            value=os.environ.get("KAITO_INGRESS_BASE", "http://ai.roykim.ca"),
            placeholder="http://ai.roykim.ca",
        )
        use_ingress = st.checkbox(
            "Use ingress endpoint",
            value=bool(ingress_base),
        )
        ingress_service = st.selectbox(
            "Ingress service",
            [
                "Phi-4 (/phi4)",
                #"RAGEngine (/rag)",
                "RAGEngine (/rag-nostorage)",
            ],
            index=0,
            disabled=not use_ingress,
        )

    if use_ingress:
        if not ingress_base.strip():
            st.sidebar.error("Provide an ingress base URL to use ingress endpoints.")
            st.stop()

        if ingress_service.startswith("Phi-4"):
            chat_path = "/phi4/v1/chat/completions"
            extra_defaults: dict[str, Any] = {}
        elif "rag-nostorage" in ingress_service:
            chat_path = "/rag-nostorage/v1/chat/completions"
            extra_defaults = {"index_name": "rag_index", "context_token_ratio": 0.5}
        else:
            chat_path = "/rag/v1/chat/completions"
            extra_defaults = {"index_name": "rag_index", "context_token_ratio": 0.5}

        api = KaitoApi(
            name=f"Ingress: {ingress_service}",
            base_url=ingress_base.strip(),
            chat_completions_path=chat_path,
            models=["phi-4-mini-instruct"],
            extra_payload_defaults=extra_defaults,
        )
    else:
        api_names = [a.name for a in catalog.apis]
        default_api = st.sidebar.selectbox("API endpoint", api_names, index=0)
        api = get_api_by_name(catalog, default_api)
        if api is None:
            st.sidebar.error("Selected API not found in catalog")
            st.stop()

    st.sidebar.caption(f"Chat Completions: {api.chat_completions_url}")

    is_ragengine = "/rag" in api.chat_completions_path
    if is_ragengine:
        st.sidebar.info("RAGEngine replies are non-streaming; streaming is disabled.")
        with st.sidebar.expander("RAG presets", expanded=False):
            if st.button("Apply CLI chat defaults", type="secondary"):
                st.session_state["gen_temperature"] = 0.7
                st.session_state["gen_max_tokens"] = 2048
                st.session_state["extra_json_payload"] = json.dumps(
                    {
                        "index_name": str((api.extra_payload_defaults or {}).get("index_name", "rag_index")),
                        "context_token_ratio": (api.extra_payload_defaults or {}).get("context_token_ratio", 0.5),
                        "temperature": 0.7,
                        "max_tokens": 2048,
                    },
                    indent=2,
                )
                st.rerun()

    if api.models:
        model = st.sidebar.selectbox("Model", api.models, index=0)
    else:
        model = st.sidebar.text_input("Model", value="phi-4-mini-instruct")

    with st.sidebar.expander("Generation", expanded=True):
        temperature = st.slider(
            "Temperature",
            0.0,
            1.5,
            0.2,
            0.05,
            key="gen_temperature",
            help=(
                "Controls randomness in model output. Lower values are more deterministic and repeatable; "
                "higher values are more diverse but can be less stable."
            ),
        )
        default_max_tokens = 1280 if is_ragengine else 512
        max_tokens = st.number_input(
            "Max tokens",
            min_value=1,
            max_value=8192,
            value=default_max_tokens,
            step=1,
            key="gen_max_tokens",
            help=(
                "Maximum number of tokens the model can generate in the response. "
                "Higher values allow longer answers but increase latency/cost and may affect backend behavior."
            ),
        )
        rag_min_tokens = 1280
        if is_ragengine:
            rag_min_tokens = int(
                st.number_input(
                    "RAG min max_tokens",
                    min_value=1,
                    max_value=8192,
                    value=1280,
                    step=1,
                    help=(
                        "Minimum `max_tokens` enforced only in RAG mode. "
                        "If the effective `max_tokens` is lower, the app bumps it up to this value "
                        "to improve source retrieval/answer reliability."
                    ),
                )
            )
        stream = st.checkbox(
            "Stream",
            value=False if is_ragengine else True,
            disabled=is_ragengine,
            help=(
                "When enabled, tokens are shown incrementally as they arrive. "
                "RAG mode disables streaming to keep retrieval-compatible response handling."
            ),
        )

    with st.sidebar.expander("Auth & Advanced", expanded=False):
        api_key = st.text_input(
            "API key (optional)",
            type="password",
            help=(
                "Bearer token used for authenticated endpoints. "
                "Leave blank for open/internal endpoints that do not require auth."
            ),
        )
        timeout_s = st.number_input(
            "HTTP timeout (seconds)",
            min_value=5,
            max_value=600,
            value=120,
            step=5,
            help=(
                "Total request timeout for the chat API call. "
                "Increase for slower backends or larger generations."
            ),
        )
        expand_technical = st.checkbox(
            "Expand technical panels by default",
            value=False,
            help=(
                "Automatically opens the technical response section for each assistant message, "
                "including request payload and raw response JSON."
            ),
        )

        merged_defaults: dict[str, Any] = dict(api.extra_payload_defaults or {})
        # Good defaults for OpenAI-compatible servers
        merged_defaults.setdefault("temperature", float(temperature))
        merged_defaults.setdefault("max_tokens", int(max_tokens))

        extra_json = st.text_area(
            "Extra JSON payload (merged)",
            value=json.dumps(merged_defaults, indent=2),
            height=180,
            key="extra_json_payload",
            help=(
                "Advanced request fields merged into the outbound payload. "
                "Useful for endpoint-specific options. Generation controls still override `temperature` and `max_tokens`."
            ),
        )

        try:
            extra_payload = json.loads(extra_json) if extra_json.strip() else {}
            if not isinstance(extra_payload, dict):
                raise ValueError("Extra payload must be a JSON object")
        except Exception as e:  # noqa: BLE001
            st.error(f"Invalid extra JSON: {e}")
            st.stop()

    # Keep Generation controls authoritative for every request.
    extra_payload = dict(extra_payload)
    extra_payload["temperature"] = float(temperature)
    extra_payload["max_tokens"] = int(max_tokens)

    if is_ragengine:
        stream = False
        if "stream" in extra_payload:
            extra_payload = dict(extra_payload)
            extra_payload.pop("stream", None)
        if "index_name" not in extra_payload:
            extra_payload = dict(extra_payload)
            extra_payload["index_name"] = str((api.extra_payload_defaults or {}).get("index_name", "rag_index"))
        if "context_token_ratio" not in extra_payload:
            extra_payload = dict(extra_payload)
            extra_payload["context_token_ratio"] = (api.extra_payload_defaults or {}).get("context_token_ratio", 0.5)
        current_max_tokens = int(extra_payload.get("max_tokens", max_tokens))
        if current_max_tokens < rag_min_tokens:
            st.sidebar.warning(
                f"RAGEngine mode: max_tokens < {rag_min_tokens} may suppress source_nodes; using {rag_min_tokens}."
            )
            extra_payload = dict(extra_payload)
            extra_payload["max_tokens"] = rag_min_tokens

    rag_enforcement = {
        "enabled": is_ragengine,
        "min_max_tokens": int(rag_min_tokens) if is_ragengine else None,
        "effective_max_tokens": int(extra_payload.get("max_tokens", max_tokens)),
        "auto_adjusted": bool(is_ragengine and int(extra_payload.get("max_tokens", max_tokens)) != int(max_tokens)),
    }

    if st.sidebar.button("New chat", type="secondary"):
        st.session_state.messages = [{"role": "system", "content": "You are a helpful assistant."}]
        st.rerun()

    return {
        "api": api,
        "model": model,
        "api_key": api_key,
        "timeout_s": float(timeout_s),
        "stream": bool(stream),
        "extra_payload": extra_payload,
        "is_ragengine": bool(is_ragengine),
        "rag_enforcement": rag_enforcement,
        "expand_technical": bool(expand_technical),
        "catalog_path": catalog_path,
    }


def main() -> None:
    _init_state()

    cfg = _sidebar_config()
    api = cfg["api"]
    expand_technical = cfg["expand_technical"]
    _enable_chat_prompt_history_hotkeys(st.session_state.get("prompt_history", []))

    st.title("Streamlit Chatbot (KAITO / OpenAI-compatible)")

    # Render existing chat
    for i, m in enumerate(st.session_state.messages):
        if m["role"] == "system":
            continue
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m["role"] == "assistant":
                _render_technical_panel(
                    m,
                    key_suffix=f"history-{i}",
                    expanded=expand_technical,
                )

    prompt = st.chat_input("Ask anything…")
    if not prompt:
        return

    prompt_history = st.session_state.get("prompt_history", [])
    if prompt.strip() and (not prompt_history or prompt_history[-1] != prompt):
        prompt_history.append(prompt)
        st.session_state.prompt_history = prompt_history

    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_text = ""
        technical_data: dict[str, Any] | None = None
        request_messages = _select_request_messages(
            messages=st.session_state.messages,
            is_ragengine=bool(cfg.get("is_ragengine")),
        )
        request_payload_preview = _build_request_payload_preview(
            model=cfg["model"],
            messages=request_messages,
            stream=cfg["stream"],
            extra_payload=cfg["extra_payload"],
        )
        try:
            resp = chat_completions(
                url=api.chat_completions_url,
                model=cfg["model"],
                messages=request_messages,
                api_key=cfg["api_key"],
                timeout_s=cfg["timeout_s"],
                stream=cfg["stream"],
                extra_payload=cfg["extra_payload"],
            )
            raise_for_status_with_body(resp)

            if cfg["stream"]:
                stream_chunks: list[str] = []
                for chunk in iter_sse_chat_delta_text(resp):
                    stream_chunks.append(chunk)
                    full_text += chunk
                    placeholder.markdown(full_text)
                technical_data = _build_technical_data(
                    resp=resp,
                    stream=True,
                    request_payload=request_payload_preview,
                    rag_enforcement=cfg.get("rag_enforcement"),
                    stream_chunks=stream_chunks,
                )
            else:
                resp_json = resp.json()
                try:
                    full_text = parse_chat_completion_text(resp_json)
                except ChatCompletionError:
                    source_nodes = resp_json.get("source_nodes")
                    if isinstance(source_nodes, list) and source_nodes:
                        full_text = (
                            "No generated answer text was returned by the backend, "
                            "but retrieval sources were found. See technical response data."
                        )
                    else:
                        raise

                source_nodes = resp_json.get("source_nodes")
                if (
                    bool(cfg.get("is_ragengine"))
                    and isinstance(source_nodes, list)
                    and source_nodes
                    and _is_low_quality_answer(full_text)
                ):
                    fallback_text = _build_source_nodes_fallback(source_nodes)
                    if fallback_text:
                        full_text = fallback_text

                placeholder.markdown(full_text)
                technical_data = _build_technical_data(
                    resp=resp,
                    stream=False,
                    request_payload=request_payload_preview,
                    rag_enforcement=cfg.get("rag_enforcement"),
                    resp_json=resp_json,
                )

            if technical_data:
                _render_technical_panel(
                    {"technical": technical_data},
                    key_suffix="latest",
                    expanded=expand_technical,
                )

        except ChatCompletionError as e:
            st.error(str(e))
            return
        except Exception as e:  # noqa: BLE001
            st.error(f"Unexpected error: {e}")
            return

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": full_text,
            "technical": technical_data,
        }
    )


if __name__ == "__main__":
    main()
