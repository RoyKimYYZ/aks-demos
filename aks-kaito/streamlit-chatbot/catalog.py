from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


def _expand_env(s: str) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        default = match.group(2)
        val = os.environ.get(key)
        if val is None or val == "":
            return default or ""
        return val

    return _ENV_PATTERN.sub(repl, s)


def _expand_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return _expand_env(obj)
    if isinstance(obj, list):
        return [_expand_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _expand_obj(v) for k, v in obj.items()}
    return obj


@dataclass(frozen=True)
class KaitoApi:
    name: str
    base_url: str
    chat_completions_path: str = "/v1/chat/completions"
    models: list[str] = field(default_factory=list)
    extra_payload_defaults: dict[str, Any] = field(default_factory=dict)

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.chat_completions_path}"


@dataclass(frozen=True)
class KaitoCatalog:
    apis: list[KaitoApi]


def load_catalog(path: str) -> KaitoCatalog:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    data = _expand_obj(data)

    apis: list[KaitoApi] = []
    for raw in data.get("apis", []) or []:
        if not isinstance(raw, dict):
            continue
        apis.append(
            KaitoApi(
                name=str(raw.get("name", "Unnamed API")),
                base_url=str(raw.get("base_url", "")).strip(),
                chat_completions_path=str(raw.get("chat_completions_path", "/v1/chat/completions")),
                models=[str(m) for m in (raw.get("models", []) or [])],
                extra_payload_defaults=dict(raw.get("extra_payload_defaults", {}) or {}),
            )
        )

    if not apis:
        apis = [
            KaitoApi(
                name="Phi-4 (Port-forward localhost:8080)",
                base_url="http://localhost:8080",
                chat_completions_path="/v1/chat/completions",
                models=["phi-4-mini-instruct"],
            )
        ]

    return KaitoCatalog(apis=apis)


def resolve_catalog_path() -> str:
    # Prefer explicit env var; fall back to local catalog file.
    env_path = os.environ.get("KAITO_CATALOG_PATH")
    if env_path:
        return env_path
    return os.path.join(os.path.dirname(__file__), "kaito_catalog.yaml")


def get_api_by_name(catalog: KaitoCatalog, name: str) -> KaitoApi | None:
    for api in catalog.apis:
        if api.name == name:
            return api
    return None
