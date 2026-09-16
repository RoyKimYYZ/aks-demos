from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any

PROMPT_LIBRARY_FILE = "prompt_library.csv"
FIELDNAMES = ["name", "prompt", "updated_at"]
MAX_PROMPT_SHORT_NAME = 15


def _prompt_library_path() -> Path:
    return Path(__file__).resolve().parent / PROMPT_LIBRARY_FILE


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def ensure_prompt_library_file() -> Path:
    path = _prompt_library_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
    return path


def load_prompts() -> list[dict[str, str]]:
    path = ensure_prompt_library_file()
    prompts: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = str((row or {}).get("name", "")).strip()
            prompt = str((row or {}).get("prompt", "")).strip()
            updated_at = str((row or {}).get("updated_at", "")).strip()
            if not name or not prompt:
                continue
            prompts.append({"name": name, "prompt": prompt, "updated_at": updated_at})

    prompts.sort(key=lambda item: item["name"].lower())
    return prompts


def save_prompts(prompts: list[dict[str, Any]]) -> None:
    path = ensure_prompt_library_file()
    cleaned: list[dict[str, str]] = []
    for item in prompts:
        name = str(item.get("name", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        if not name or not prompt:
            continue
        updated_at = str(item.get("updated_at", "")).strip() or _now_iso()
        cleaned.append({"name": name, "prompt": prompt, "updated_at": updated_at})

    cleaned.sort(key=lambda item: item["name"].lower())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(cleaned)


def upsert_prompt(*, name: str, prompt: str, original_name: str | None = None) -> None:
    target_name = name.strip()
    target_prompt = prompt.strip()
    if not target_name:
        raise ValueError("Prompt short name is required")
    if len(target_name) > MAX_PROMPT_SHORT_NAME:
        raise ValueError(f"Prompt short name must be {MAX_PROMPT_SHORT_NAME} characters or fewer")
    if not target_prompt:
        raise ValueError("Prompt text is required")

    prompts = load_prompts()
    original = (original_name or target_name).strip()

    existing_by_name = {item["name"]: item for item in prompts}
    if target_name != original and target_name in existing_by_name:
        raise ValueError(f"Prompt name '{target_name}' already exists")

    updated: list[dict[str, str]] = []
    matched_original = False
    for item in prompts:
        if item["name"] == original and not matched_original:
            matched_original = True
            updated.append({"name": target_name, "prompt": target_prompt, "updated_at": _now_iso()})
        else:
            updated.append(item)

    if not matched_original:
        updated.append({"name": target_name, "prompt": target_prompt, "updated_at": _now_iso()})

    save_prompts(updated)


def delete_prompt(name: str) -> bool:
    target = name.strip()
    if not target:
        return False

    prompts = load_prompts()
    remaining = [item for item in prompts if item["name"] != target]
    deleted = len(remaining) != len(prompts)
    if deleted:
        save_prompts(remaining)
    return deleted
