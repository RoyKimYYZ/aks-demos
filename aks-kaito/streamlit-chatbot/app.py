from __future__ import annotations

import json
import os
import datetime as dt
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
from prompt_library_store import load_prompts
from sidebar_nav import render_sidebar_nav

st.set_page_config(page_title="KAITO Chatbot", layout="wide")


def _init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "system", "content": "You are a helpful assistant."}]
    if "prompt_history" not in st.session_state:
        st.session_state.prompt_history = []
    if "app_logs" not in st.session_state:
        st.session_state.app_logs = []


def _append_app_log(level: str, event: str, details: str = "") -> None:
    logs = st.session_state.get("app_logs", [])
    logs.append(
        {
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "level": str(level).upper(),
            "event": event,
            "details": details,
        }
    )
    st.session_state.app_logs = logs[-200:]


@st.cache_data(show_spinner=False)
def _load_catalog_cached(path: str):
    return load_catalog(path)


def _build_technical_data(
    *,
    resp,
    stream: bool,
    request_payload: dict[str, Any],
    rag_enforcement: dict[str, Any] | None = None,
    groundedness_validation: dict[str, Any] | None = None,
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
    if groundedness_validation:
        data["groundedness_validation"] = groundedness_validation

    return data


def _render_response_tabs(
    message: dict[str, Any],
    key_suffix: str,
    *,
    expanded: bool = False,
) -> None:
    technical = message.get("technical")
    app_logs = st.session_state.get("app_logs", [])
    if not technical and not app_logs:
        return

    tech_tab, explain_tab, logs_tab = st.tabs(
        ["Technical response data", "Technical explanation", "Application logs & errors"]
    )
    with tech_tab:
        if technical:
            st.json(technical, expanded=False)
        else:
            st.info("No technical data captured for this response.")
    with explain_tab:
        if technical:
            _render_technical_explanation(technical)
        else:
            st.info("No technical data available to explain.")
    with logs_tab:
        if app_logs:
            rows = list(reversed(app_logs))
            st.dataframe(
                [
                    {
                        "Timestamp": item.get("timestamp", ""),
                        "Level": item.get("level", ""),
                        "Event": item.get("event", ""),
                        "Details": item.get("details", ""),
                    }
                    for item in rows
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No application logs yet.")


def _render_technical_explanation(technical: dict[str, Any]) -> None:
    request_payload = technical.get("request_payload") if isinstance(technical, dict) else {}
    if not isinstance(request_payload, dict):
        request_payload = {}

    response_json = technical.get("response_json") if isinstance(technical, dict) else {}
    if not isinstance(response_json, dict):
        response_json = {}

    rag_enforcement = technical.get("rag_token_enforcement") if isinstance(technical, dict) else {}
    if not isinstance(rag_enforcement, dict):
        rag_enforcement = {}

    st.markdown("### Request controls")
    temperature = request_payload.get("temperature")
    max_tokens = request_payload.get("max_tokens")
    context_token_ratio = request_payload.get("context_token_ratio")
    index_name = request_payload.get("index_name")

    if index_name:
        st.write(f"- **RAG index**: `{index_name}`. Retrieval is attempted from this vector index.")
    else:
        st.write("- **RAG index**: Not set in payload. Request behaves like non-RAG generation.")

    if context_token_ratio is not None:
        st.write(
            "- **context_token_ratio**: "
            f"`{context_token_ratio}`. Higher values generally reserve more context window for retrieved chunks and less for generated output. "
            "If retrieval is weak, increasing this may help; if answers are too short, lowering it may help."
        )
    else:
        st.write("- **context_token_ratio**: Not provided by client payload.")

    if temperature is not None:
        st.write(
            f"- **temperature**: `{temperature}`. Lower values (around 0.0-0.2) are more deterministic and grounded; "
            "higher values increase creativity but can raise hallucination risk."
        )
    else:
        st.write("- **temperature**: Not provided in payload.")

    if max_tokens is not None:
        st.write(
            f"- **max_tokens**: `{max_tokens}`. Caps response length. In this deployment, retrieval can degrade when this is too low for RAG queries."
        )
    else:
        st.write("- **max_tokens**: Not provided in payload.")

    st.markdown("### RAG token enforcement")
    if rag_enforcement:
        enabled = rag_enforcement.get("enabled")
        min_tokens = rag_enforcement.get("min_max_tokens")
        effective = rag_enforcement.get("effective_max_tokens")
        auto_adjusted = rag_enforcement.get("auto_adjusted")

        st.write(
            f"- **enabled**: `{enabled}`. When true, app applies RAG safety controls before sending request."
        )
        st.write(
            f"- **min_max_tokens**: `{min_tokens}`. Configured lower bound for RAG max tokens."
        )
        st.write(
            f"- **effective_max_tokens**: `{effective}`. Actual value sent after enforcement."
        )
        st.write(
            f"- **auto_adjusted**: `{auto_adjusted}`. True means app raised max_tokens to satisfy the RAG minimum."
        )
    else:
        st.write("- No `rag_token_enforcement` metadata captured for this response.")

    st.markdown("### Response interpretation")
    source_nodes = response_json.get("source_nodes")
    usage = response_json.get("usage") if isinstance(response_json.get("usage"), dict) else {}

    if isinstance(source_nodes, list) and source_nodes:
        st.write(
            f"- **source_nodes**: `{len(source_nodes)}` retrieved chunk(s). RAG retrieval succeeded for this request."
        )
    elif source_nodes is None:
        st.write(
            "- **source_nodes**: `null`. Backend returned no retrieval chunks; answer may come from model prior knowledge. "
            "Check index content, question wording, and token settings."
        )
    else:
        st.write("- **source_nodes**: Present but empty/unexpected format.")

    total_tokens = usage.get("total_tokens")
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if total_tokens is not None or prompt_tokens is not None or completion_tokens is not None:
        st.write(
            "- **usage**: "
            f"prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}. "
            "Useful for latency/cost tuning and comparing prompt/response size behavior."
        )

    elapsed_ms = technical.get("elapsed_ms")
    if elapsed_ms is not None:
        st.write(
            f"- **elapsed_ms**: `{elapsed_ms}` ms end-to-end HTTP latency. "
            "Use this with token usage to evaluate throughput and tuning impact."
        )

    st.markdown("### Troubleshooting quick guide")
    st.write("- If `source_nodes` is null in RAG mode, first verify endpoint + index, then try higher `max_tokens` (for this stack, 2048+ is often safer).")
    st.write("- If answer is generic despite chunks, lower `temperature` and use a stricter system instruction focused on retrieved context.")
    st.write("- If response is too short or cut off, increase `max_tokens`; if latency is too high, reduce `max_tokens` or simplify prompt scope.")


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


def _apply_system_prompt_override(
    *,
    messages: list[dict[str, Any]],
    system_prompt_override: str | None,
) -> list[dict[str, Any]]:
    override = (system_prompt_override or "").strip()
    if not override:
        return messages

    updated: list[dict[str, Any]] = []
    replaced = False
    for message in messages:
        if not replaced and str(message.get("role", "")).lower() == "system":
            updated.append({"role": "system", "content": override})
            replaced = True
        else:
            updated.append(message)

    if not replaced:
        updated.insert(0, {"role": "system", "content": override})

    return updated


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


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None

    candidates: list[str] = [raw]
    if "```" in raw:
        blocks = raw.split("```")
        for block in blocks:
            trimmed = block.strip()
            if not trimmed:
                continue
            if trimmed.lower().startswith("json"):
                trimmed = trimmed[4:].strip()
            candidates.append(trimmed)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

    return None


def _to_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass
        return [text]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    return []


def _apply_post_response_groundedness_validation(
    *,
    response_text: str,
    source_nodes: list[dict[str, Any]],
    user_prompt: str,
) -> tuple[str, dict[str, Any] | None]:
    parsed = _extract_first_json_object(response_text)
    if not parsed:
        return response_text, None

    source_texts = [str(node.get("text", "")) for node in source_nodes if isinstance(node, dict)]
    source_corpus = "\n\n".join(source_texts)

    source_filenames: list[str] = []
    seen: set[str] = set()
    for node in source_nodes:
        if not isinstance(node, dict):
            continue
        md = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        filename = str((md or {}).get("filename", "")).strip()
        if filename and filename not in seen:
            source_filenames.append(filename)
            seen.add(filename)

    evidence_quotes = _to_string_list(parsed.get("evidence_quotes"))
    raw_evidence_quotes = parsed.get("evidence_quotes")
    validation_errors: list[str] = []
    if raw_evidence_quotes is not None and not isinstance(raw_evidence_quotes, (str, list)):
        validation_errors.append("evidence_quotes must be a string or an array of strings")
    if isinstance(raw_evidence_quotes, list):
        non_string_items = [item for item in raw_evidence_quotes if not isinstance(item, str)]
        if non_string_items:
            validation_errors.append("evidence_quotes array may only contain strings")
    if len(evidence_quotes) == 0:
        validation_errors.append("No evidence quotes were provided")

    quote_checks: list[dict[str, Any]] = []
    for quote in evidence_quotes:
        normalized_quote = quote.strip()
        quote_found = normalized_quote in source_corpus if normalized_quote else False
        quote_checks.append({"quote": normalized_quote, "found": bool(quote_found)})

    missing_quotes = [item["quote"] for item in quote_checks if not item["found"]]
    if missing_quotes:
        validation_errors.append("One or more evidence quotes were not found exactly in retrieved source text")

    failed_groundedness = len(validation_errors) > 0

    if source_filenames:
        parsed["source_filenames"] = source_filenames
    else:
        parsed["source_filenames"] = []

    total_quotes = len(evidence_quotes)
    matched_quotes = total_quotes - len(missing_quotes)
    quote_ratio = (matched_quotes / total_quotes) if total_quotes > 0 else 0.0
    derived_confidence = round(0.2 + (0.7 * quote_ratio), 2)
    if failed_groundedness:
        derived_confidence = min(derived_confidence, 0.49)
    parsed["confidence"] = derived_confidence
    parsed["failed_groundedness"] = failed_groundedness

    broad_prompt_markers = [
        "what are",
        "list",
        "overview",
        "summarize",
        "summary",
        "controls",
        "all",
        "key",
    ]
    prompt_lower = (user_prompt or "").strip().lower()
    broad_prompt_intent = any(marker in prompt_lower for marker in broad_prompt_markers)
    scope_adequacy_failed = bool(broad_prompt_intent and matched_quotes < 3)

    if failed_groundedness:
        parsed["groundedness_reasons"] = {
            "missing_quotes": missing_quotes,
            "errors": validation_errors,
            "message": (
                "Groundedness failed. Use exact verbatim evidence_quotes copied from retrieved chunks. "
                "Do not paraphrase quote text."
            ),
        }

    parsed["scope_adequacy"] = {
        "broad_prompt_intent": broad_prompt_intent,
        "quotes_required_for_broad_prompt": 3,
        "quotes_matched": matched_quotes,
        "failed": scope_adequacy_failed,
    }

    validation = {
        "applied": True,
        "failed_groundedness": failed_groundedness,
        "quotes_total": total_quotes,
        "quotes_matched": matched_quotes,
        "missing_quotes": missing_quotes,
        "errors": validation_errors,
        "derived_confidence": derived_confidence,
        "enforced_source_filenames": source_filenames,
        "scope_adequacy_failed": scope_adequacy_failed,
        "broad_prompt_intent": broad_prompt_intent,
    }

    validated_text = json.dumps(parsed, indent=2, ensure_ascii=False)
    return validated_text, validation


def _enable_chat_prompt_history_hotkeys(prompt_history: list[str]) -> None:
    history_json = json.dumps(prompt_history)
    components.html(
        f"""
        <script>
        (function() {{
            const root = window.parent;
            root.__kaitoPromptHistory = {history_json};
            if (typeof root.__kaitoPromptHistoryIdx !== "number") {{
                root.__kaitoPromptHistoryIdx = root.__kaitoPromptHistory.length;
            }}
            if (typeof root.__kaitoPromptHistoryDraft !== "string") {{
                root.__kaitoPromptHistoryDraft = "";
            }}

            function setValue(el, value) {{
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype,
                    "value"
                )?.set;
                if (setter) {{
                    setter.call(el, value);
                }} else {{
                    el.value = value;
                }}
                el.dispatchEvent(new Event("input", {{ bubbles: true }}));
                el.dispatchEvent(new Event("change", {{ bubbles: true }}));
                const end = (value || "").length;
                try {{
                    el.setSelectionRange(end, end);
                }} catch (e) {{
                }}
                el.focus();
            }}

            function getChatInput() {{
                return (
                    root.document.querySelector('textarea[data-testid="stChatInputTextArea"]') ||
                    root.document.querySelector('textarea[aria-label="Ask anything…"]') ||
                    root.document.querySelector('textarea[aria-label="Ask anything..."]') ||
                    root.document.querySelector('textarea[placeholder="Ask anything…"]') ||
                    root.document.querySelector('textarea[placeholder="Ask anything..."]') ||
                    root.document.querySelector('[data-testid="stChatInput"] textarea')
                );
            }}

            function isChatInput(el) {{
                if (!el || el.tagName !== "TEXTAREA") return false;
                if (el.getAttribute("data-testid") === "stChatInputTextArea") return true;
                const aria = el.getAttribute("aria-label") || "";
                const placeholder = el.getAttribute("placeholder") || "";
                if (aria.includes("Ask anything") || placeholder.includes("Ask anything")) return true;
                if (el.closest('[data-testid="stChatInput"]')) return true;
                return false;
            }}

            if (!root.__kaitoPromptHistoryListenerBound) {{
                root.__kaitoPromptHistoryListenerBound = true;
                root.document.addEventListener(
                    "keydown",
                    function (e) {{
                        if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
                        if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;

                        const el = e.target && e.target.tagName === "TEXTAREA" ? e.target : getChatInput();
                        if (!isChatInput(el)) return;

                        const history = root.__kaitoPromptHistory || [];
                        if (!history.length) return;

                        e.preventDefault();
                        e.stopPropagation();

                        if (e.key === "ArrowUp") {{
                            if (root.__kaitoPromptHistoryIdx >= history.length) {{
                                root.__kaitoPromptHistoryDraft = el.value || "";
                                root.__kaitoPromptHistoryIdx = history.length;
                            }}
                            root.__kaitoPromptHistoryIdx = Math.max(0, root.__kaitoPromptHistoryIdx - 1);
                            setValue(el, history[root.__kaitoPromptHistoryIdx] || "");
                        }} else if (e.key === "ArrowDown") {{
                            root.__kaitoPromptHistoryIdx = Math.min(history.length, root.__kaitoPromptHistoryIdx + 1);
                            const nextValue =
                                root.__kaitoPromptHistoryIdx === history.length
                                    ? (root.__kaitoPromptHistoryDraft || "")
                                    : (history[root.__kaitoPromptHistoryIdx] || "");
                            setValue(el, nextValue);
                        }}
                    }},
                    true
                );
            }}
        }})();
        </script>
        """,
        height=0,
    )


def _prefill_chat_input_once(text: str) -> None:
        value = (text or "").strip()
        if not value:
                return
        st.session_state["chat_input_text"] = value


def _sidebar_config() -> dict[str, Any]:
    st.sidebar.title("KAITO Chat")

    catalog_path = resolve_catalog_path()
    catalog = _load_catalog_cached(catalog_path)
    prompt_library_items = load_prompts()
    prompt_by_name = {item["name"]: item["prompt"] for item in prompt_library_items}

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
            index=1,
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

    if api.models:
        model = st.sidebar.selectbox("Model", api.models, index=0)
    else:
        model = st.sidebar.text_input("Model", value="phi-4-mini-instruct")

    prompt_options = ["(No library prompt)", *prompt_by_name.keys()]
    selected_prompt_name = st.sidebar.selectbox(
        "Prompt library",
        prompt_options,
        index=0,
        help="Select a saved prompt from Prompt Library to use as the system instruction for this request.",
    )
    selected_prompt_text = ""
    if selected_prompt_name != "(No library prompt)":
        selected_prompt_text = prompt_by_name.get(selected_prompt_name, "")

    use_selected_prompt_as_system = st.sidebar.checkbox(
        "Use selected prompt as system instruction",
        value=False,
        help=(
            "When enabled, the selected Prompt Library text is sent as the system message. "
            "When disabled, selection is used to prefill the Ask box only."
        ),
    )

    last_prompt_selection = st.session_state.get("_last_prompt_selection_name", "(No library prompt)")
    if (
        selected_prompt_name != last_prompt_selection
        and selected_prompt_name != "(No library prompt)"
        and not use_selected_prompt_as_system
    ):
        st.session_state["_pending_chat_input_prefill"] = selected_prompt_text
    st.session_state["_last_prompt_selection_name"] = selected_prompt_name

    system_prompt_override = selected_prompt_text if use_selected_prompt_as_system else ""

    active_system_prompt = system_prompt_override or "You are a helpful assistant."
    system_prompt_source = (
        f"Prompt Library: {selected_prompt_name}"
        if use_selected_prompt_as_system and selected_prompt_name != "(No library prompt)"
        else "Default"
    )
    with st.sidebar.expander("Active system prompt preview", expanded=False):
        st.caption(f"Source: {system_prompt_source}")
        st.code(active_system_prompt, language="text")

    with st.sidebar.expander("Generation", expanded=True):
        temperature = st.slider(
            "Temperature",
            0.0,
            1.5,
            0.1,
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
                "Maximum response length requested from the model. "
                "In RAGEngine mode, this value is compared against `RAG min max_tokens`: "
                "the effective value sent is `max(Max tokens, RAG min max_tokens)`. "
                "If Max tokens is set lower than the RAG minimum, the app automatically raises it to the minimum. "
                "Practical guidance: for short factual answers use 2048; for broader summaries/comparisons use 2560-4096. "
                "Higher values can improve retrieval reliability on some backends but may increase latency/cost."
            ),
        )
        rag_min_tokens = 2048
        if is_ragengine:
            rag_min_tokens = int(
                st.number_input(
                    "RAG min max_tokens",
                    min_value=1,
                    max_value=8192,
                    value=2048,
                    step=1,
                    help=(
                        "RAG-only floor for the outgoing `max_tokens`. "
                        "Final value sent to backend is `max(Max tokens, RAG min max_tokens)`. "
                        "Use this to prevent too-small generations that can correlate with missing `source_nodes` on some endpoints. "
                        "Recommended baseline: 2048. Increase to 2560-4096 for long, multi-part questions; "
                        "reduce only if latency is a priority and retrieval remains stable."
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

        if int(extra_payload.get("max_tokens", max_tokens)) < 2048:
            st.sidebar.info(
                "This endpoint appears to retrieve more reliably with max_tokens >= 2048 for RAG queries."
            )

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
        "selected_prompt_name": selected_prompt_name,
        "selected_prompt_text": selected_prompt_text,
        "system_prompt_override": system_prompt_override,
        "use_selected_prompt_as_system": bool(use_selected_prompt_as_system),
        "active_system_prompt": active_system_prompt,
        "active_system_prompt_source": system_prompt_source,
        "rag_enforcement": rag_enforcement,
        "expand_technical": bool(expand_technical),
        "catalog_path": catalog_path,
    }


def main() -> None:
    _init_state()

    render_sidebar_nav(current="home")

    cfg = _sidebar_config()
    api = cfg["api"]
    expand_technical = cfg["expand_technical"]
    _enable_chat_prompt_history_hotkeys(st.session_state.get("prompt_history", []))
    pending_prefill = st.session_state.pop("_pending_chat_input_prefill", None)
    if isinstance(pending_prefill, str) and pending_prefill.strip():
        _prefill_chat_input_once(pending_prefill)

    st.title("Streamlit Chatbot (KAITO / OpenAI-compatible)")

    # Render existing chat
    for i, m in enumerate(st.session_state.messages):
        if m["role"] == "system":
            continue
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m["role"] == "assistant":
                _render_response_tabs(
                    m,
                    key_suffix=f"history-{i}",
                    expanded=expand_technical,
                )

    prompt = st.chat_input("Ask anything…", key="chat_input_text")
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
        groundedness_validation: dict[str, Any] | None = None
        base_request_messages = _select_request_messages(
            messages=st.session_state.messages,
            is_ragengine=bool(cfg.get("is_ragengine")),
        )
        request_messages = _apply_system_prompt_override(
            messages=base_request_messages,
            system_prompt_override=str(cfg.get("system_prompt_override", "")),
        )
        request_payload_preview = _build_request_payload_preview(
            model=cfg["model"],
            messages=request_messages,
            stream=cfg["stream"],
            extra_payload=cfg["extra_payload"],
        )
        try:
            _append_app_log(
                "info",
                "chat_request_started",
                f"url={api.chat_completions_url} model={cfg['model']} stream={cfg['stream']}",
            )
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
            _append_app_log(
                "info",
                "chat_response_received",
                f"status={resp.status_code} elapsed_ms={round(resp.elapsed.total_seconds()*1000,2) if resp.elapsed else 'n/a'}",
            )

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
                        _append_app_log(
                            "warning",
                            "empty_response_retry",
                            "Backend returned empty assistant text and no source_nodes; retrying once with temperature=0.0.",
                        )
                        retry_messages = list(request_messages)
                        retry_extra_payload = dict(cfg["extra_payload"])
                        retry_extra_payload["temperature"] = 0.0
                        retry_extra_payload["max_tokens"] = max(256, int(retry_extra_payload.get("max_tokens", 256)))

                        try:
                            retry_resp = chat_completions(
                                url=api.chat_completions_url,
                                model=cfg["model"],
                                messages=retry_messages,
                                api_key=cfg["api_key"],
                                timeout_s=cfg["timeout_s"],
                                stream=False,
                                extra_payload=retry_extra_payload,
                            )
                            raise_for_status_with_body(retry_resp)
                            retry_json = retry_resp.json()
                            retry_text = parse_chat_completion_text(retry_json)
                            resp = retry_resp
                            resp_json = retry_json
                            full_text = retry_text
                            request_payload_preview = _build_request_payload_preview(
                                model=cfg["model"],
                                messages=retry_messages,
                                stream=False,
                                extra_payload=retry_extra_payload,
                            )
                            _append_app_log(
                                "info",
                                "empty_response_retry_succeeded",
                                "Retry produced non-empty assistant text.",
                            )
                        except Exception as retry_error:  # noqa: BLE001
                            _append_app_log(
                                "error",
                                "empty_response_retry_failed",
                                str(retry_error),
                            )
                            full_text = (
                                "The backend returned an empty answer and no retrieval chunks. "
                                "Try correcting typos in your question, lowering temperature, or verifying that "
                                "the selected index contains matching documents."
                            )

                source_nodes = resp_json.get("source_nodes")
                if (
                    bool(cfg.get("is_ragengine"))
                    and isinstance(source_nodes, list)
                    and source_nodes
                    and _is_low_quality_answer(full_text)
                ):
                    _append_app_log(
                        "warning",
                        "low_quality_response_retry",
                        "Initial RAG answer was low quality; retrying once with deterministic grounded instruction.",
                    )
                    retry_messages = _apply_system_prompt_override(
                        messages=request_messages,
                        system_prompt_override=(
                            "You are a grounded assistant. Answer clearly in 5 concise bullet points, "
                            "strictly using retrieved context. Do not paraphrase as questions."
                        ),
                    )
                    retry_extra_payload = dict(cfg["extra_payload"])
                    retry_extra_payload["temperature"] = 0.0

                    try:
                        retry_resp = chat_completions(
                            url=api.chat_completions_url,
                            model=cfg["model"],
                            messages=retry_messages,
                            api_key=cfg["api_key"],
                            timeout_s=cfg["timeout_s"],
                            stream=False,
                            extra_payload=retry_extra_payload,
                        )
                        raise_for_status_with_body(retry_resp)
                        retry_json = retry_resp.json()
                        retry_text = parse_chat_completion_text(retry_json)
                        if not _is_low_quality_answer(retry_text):
                            resp = retry_resp
                            resp_json = retry_json
                            full_text = retry_text
                            source_nodes = resp_json.get("source_nodes")
                            request_payload_preview = _build_request_payload_preview(
                                model=cfg["model"],
                                messages=retry_messages,
                                stream=False,
                                extra_payload=retry_extra_payload,
                            )
                            _append_app_log(
                                "info",
                                "low_quality_response_retry_succeeded",
                                "Retry produced a higher-quality response.",
                            )
                        else:
                            _append_app_log(
                                "warning",
                                "low_quality_response_retry_still_low",
                                "Retry response still looked low quality; using source fallback.",
                            )
                    except Exception as retry_error:  # noqa: BLE001
                        _append_app_log(
                            "warning",
                            "low_quality_response_retry_failed",
                            str(retry_error),
                        )

                if isinstance(source_nodes, list) and source_nodes:
                    latest_user_prompt = ""
                    for msg in reversed(request_messages):
                        if str(msg.get("role", "")).lower() == "user":
                            latest_user_prompt = str(msg.get("content", ""))
                            break
                    full_text, groundedness_validation = _apply_post_response_groundedness_validation(
                        response_text=full_text,
                        source_nodes=source_nodes,
                        user_prompt=latest_user_prompt,
                    )
                    if groundedness_validation and groundedness_validation.get("applied"):
                        _append_app_log(
                            "warning" if groundedness_validation.get("failed_groundedness") else "info",
                            "groundedness_validation",
                            (
                                f"failed={groundedness_validation.get('failed_groundedness')} "
                                f"matched_quotes={groundedness_validation.get('quotes_matched')}/"
                                f"{groundedness_validation.get('quotes_total')}"
                            ),
                        )

                if (
                    bool(cfg.get("is_ragengine"))
                    and isinstance(source_nodes, list)
                    and source_nodes
                    and _is_low_quality_answer(full_text)
                ):
                    fallback_text = _build_source_nodes_fallback(source_nodes)
                    if fallback_text:
                        _append_app_log(
                            "warning",
                            "low_quality_response_fallback",
                            "Used source_nodes fallback due to low-quality model output.",
                        )
                        full_text = fallback_text
                elif bool(cfg.get("is_ragengine")) and source_nodes is None:
                    _append_app_log(
                        "warning",
                        "rag_no_source_nodes",
                        "RAG response returned source_nodes=null. Retrieval may be skipped by backend; try max_tokens >= 2048.",
                    )
                    st.warning(
                        "No retrieval chunks were returned (`source_nodes` is null). "
                        "Try increasing max_tokens to 2048+ and retry."
                    )

                placeholder.markdown(full_text)
                technical_data = _build_technical_data(
                    resp=resp,
                    stream=False,
                    request_payload=request_payload_preview,
                    rag_enforcement=cfg.get("rag_enforcement"),
                    groundedness_validation=groundedness_validation,
                    resp_json=resp_json,
                )

            if technical_data:
                _render_response_tabs(
                    {"technical": technical_data},
                    key_suffix="latest",
                    expanded=expand_technical,
                )

        except ChatCompletionError as e:
            _append_app_log("error", "chat_completion_error", str(e))
            st.error(str(e))
            return
        except Exception as e:  # noqa: BLE001
            _append_app_log("error", "unexpected_error", str(e))
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
