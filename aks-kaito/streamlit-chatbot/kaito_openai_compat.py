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

    resp = requests.post(
        url, headers=headers, json=payload, timeout=timeout_s, stream=stream
    )
    return resp


def parse_chat_completion_text(resp_json: dict[str, Any]) -> str:
    try:
        return str(resp_json["choices"][0]["message"]["content"])
    except Exception as e:  # noqa: BLE001
        raise ChatCompletionError(
            f"Unexpected response shape: {e}. Full JSON: {resp_json}"
        ) from e


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
