from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any

CACHE_FILE = Path(".cache/canvas_cache.json")


def _load() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, default=str), encoding="utf-8")


def get(key: str) -> Any | None:
    data = _load()
    entry = data.get(key)
    if entry is None:
        return None
    if time.time() > entry["expires_at"]:
        return None
    return entry["value"]


def set(key: str, value: Any, ttl_seconds: int) -> None:
    data = _load()
    data[key] = {"value": value, "expires_at": time.time() + ttl_seconds}
    _save(data)


def invalidate(key: str) -> None:
    data = _load()
    data.pop(key, None)
    _save(data)


def clear_all() -> None:
    if CACHE_FILE.exists():
        CACHE_FILE.write_text("{}", encoding="utf-8")
