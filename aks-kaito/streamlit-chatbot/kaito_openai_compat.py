from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import requests


class ChatCompletionError(RuntimeError):
    pass


def _coerce_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages:
        role = str(m.get("role", "user"))
        content = str(m.get("content", ""))
        out.append({"role": role, "content": content})
    return out


def chat_completions(
    *,
    url: str,
    model: str,
    messages: list[dict[str, str]],
    api_key: str | None = None,
    timeout_s: float = 120.0,
    stream: bool = False,
    extra_payload: dict[str, Any] | None = None,
) -> requests.Response:
    payload: dict[str, Any] = {
        "model": model,
        "messages": _coerce_messages(messages),
    }
    if extra_payload:
        payload.update(extra_payload)
    if stream:
        payload["stream"] = True

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout_s, stream=stream)
    return resp


def parse_chat_completion_text(resp_json: dict[str, Any]) -> str:
    def _as_non_empty_text(value: Any) -> str | None:
        if isinstance(value, str):
            text = value.strip()
            return text or None
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    candidate = item.get("text") or item.get("content")
                    if isinstance(candidate, str) and candidate.strip():
                        parts.append(candidate.strip())
                elif isinstance(item, str) and item.strip():
                    parts.append(item.strip())
            if parts:
                return "\n".join(parts)
        return None

    choices = resp_json.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else None
        if isinstance(message, dict):
            direct = _as_non_empty_text(message.get("content"))
            if direct:
                return direct
        direct_text = _as_non_empty_text(first.get("text")) if isinstance(first, dict) else None
        if direct_text:
            return direct_text

    for key in ("output_text", "response", "answer", "content", "text"):
        candidate = _as_non_empty_text(resp_json.get(key))
        if candidate:
            return candidate

    raise ChatCompletionError(
        "Response contained no assistant text content. Full JSON: "
        f"{resp_json}"
    )


def iter_sse_chat_delta_text(resp: requests.Response) -> Iterable[str]:
    """Parse OpenAI-compatible SSE stream.

    Expected lines:
      data: {"choices":[{"delta":{"content":"..."}}]}
      data: [DONE]

    Yields delta content chunks.
    """
    for raw_line in resp.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if data == "[DONE]":
            return
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        try:
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                yield str(content)
        except Exception:
            continue


def raise_for_status_with_body(resp: requests.Response) -> None:
    if 200 <= resp.status_code < 300:
        return

    body = None
    try:
        body = resp.json()
    except Exception:
        body = resp.text

    raise ChatCompletionError(f"HTTP {resp.status_code} from {resp.url}: {body}")
