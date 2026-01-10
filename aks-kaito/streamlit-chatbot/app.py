from __future__ import annotations

import json
from typing import Any

import streamlit as st

from catalog import get_api_by_name, load_catalog, resolve_catalog_path
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
        st.session_state.messages = [
            {"role": "system", "content": "You are a helpful assistant."}
        ]


@st.cache_data(show_spinner=False)
def _load_catalog_cached(path: str):
    return load_catalog(path)


def _sidebar_config() -> dict[str, Any]:
    st.sidebar.title("KAITO Chat")

    catalog_path = resolve_catalog_path()
    catalog = _load_catalog_cached(catalog_path)

    api_names = [a.name for a in catalog.apis]
    default_api = st.sidebar.selectbox("API endpoint", api_names, index=0)
    api = get_api_by_name(catalog, default_api)
    if api is None:
        st.sidebar.error("Selected API not found in catalog")
        st.stop()

    st.sidebar.caption(f"Chat Completions: {api.chat_completions_url}")

    if api.models:
        model = st.sidebar.selectbox("Model", api.models, index=0)
    else:
        model = st.sidebar.text_input("Model", value="phi-4-mini-instruct")

    with st.sidebar.expander("Generation", expanded=True):
        temperature = st.slider("Temperature", 0.0, 1.5, 0.2, 0.05)
        max_tokens = st.number_input(
            "Max tokens", min_value=1, max_value=8192, value=512, step=1
        )
        stream = st.checkbox("Stream", value=True)

    with st.sidebar.expander("Auth & Advanced", expanded=False):
        api_key = st.text_input("API key (optional)", type="password")
        timeout_s = st.number_input(
            "HTTP timeout (seconds)", min_value=5, max_value=600, value=120, step=5
        )

        merged_defaults: dict[str, Any] = dict(api.extra_payload_defaults or {})
        # Good defaults for OpenAI-compatible servers
        merged_defaults.setdefault("temperature", float(temperature))
        merged_defaults.setdefault("max_tokens", int(max_tokens))

        extra_json = st.text_area(
            "Extra JSON payload (merged)",
            value=json.dumps(merged_defaults, indent=2),
            height=180,
        )

        try:
            extra_payload = json.loads(extra_json) if extra_json.strip() else {}
            if not isinstance(extra_payload, dict):
                raise ValueError("Extra payload must be a JSON object")
        except Exception as e:  # noqa: BLE001
            st.error(f"Invalid extra JSON: {e}")
            st.stop()

    if st.sidebar.button("New chat", type="secondary"):
        st.session_state.messages = [
            {"role": "system", "content": "You are a helpful assistant."}
        ]
        st.rerun()

    return {
        "api": api,
        "model": model,
        "api_key": api_key,
        "timeout_s": float(timeout_s),
        "stream": bool(stream),
        "extra_payload": extra_payload,
        "catalog_path": catalog_path,
    }


def main() -> None:
    _init_state()

    cfg = _sidebar_config()
    api = cfg["api"]

    st.title("Streamlit Chatbot (KAITO / OpenAI-compatible)")

    # Render existing chat
    for m in st.session_state.messages:
        if m["role"] == "system":
            continue
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    prompt = st.chat_input("Ask anything…")
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_text = ""
        try:
            resp = chat_completions(
                url=api.chat_completions_url,
                model=cfg["model"],
                messages=st.session_state.messages,
                api_key=cfg["api_key"],
                timeout_s=cfg["timeout_s"],
                stream=cfg["stream"],
                extra_payload=cfg["extra_payload"],
            )
            raise_for_status_with_body(resp)

            if cfg["stream"]:
                for chunk in iter_sse_chat_delta_text(resp):
                    full_text += chunk
                    placeholder.markdown(full_text)
            else:
                resp_json = resp.json()
                full_text = parse_chat_completion_text(resp_json)
                placeholder.markdown(full_text)

        except ChatCompletionError as e:
            st.error(str(e))
            return
        except Exception as e:  # noqa: BLE001
            st.error(f"Unexpected error: {e}")
            return

    st.session_state.messages.append({"role": "assistant", "content": full_text})


if __name__ == "__main__":
    main()
