"""Agent provider presets — loaded from agentKits JSON with mtime hot-reload."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

AgentProtocol = Literal["openai", "anthropic", "demo"]

_FALLBACK_PRESETS: list[dict[str, Any]] = [
    {
        "id": "demo",
        "name": "演示（无网）",
        "provider_kind": "demo",
        "protocol": "demo",
        "base_url": "",
        "model": "demo-rules",
        "context_window_input": 4000,
        "context_window_output": 2000,
        "needs_api_key": False,
    },
    {
        "id": "ollama",
        "name": "Ollama（本地）",
        "provider_kind": "ollama",
        "protocol": "openai",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5",
        "context_window_input": 8192,
        "context_window_output": 4096,
        "needs_api_key": False,
    },
]

_lock = threading.Lock()
_cached: list[dict[str, Any]] = []
_cached_mtime: float | None = None
_cached_path: Path | None = None


def _catalog_path() -> Path:
    # Code/backend/app/services/agent -> Code/agentKits
    return (
        Path(__file__).resolve().parents[4]
        / "agentKits"
        / "presets"
        / "provider_catalog.json"
    )


def _normalize_preset(raw: dict[str, Any]) -> dict[str, Any] | None:
    pid = str(raw.get("id") or "").strip()
    if not pid:
        return None
    protocol = str(raw.get("protocol") or "openai").strip()
    if protocol not in {"openai", "anthropic", "demo"}:
        protocol = "openai"
    return {
        "id": pid,
        "name": str(raw.get("name") or pid),
        "provider_kind": str(raw.get("provider_kind") or "custom"),
        "protocol": protocol,
        "base_url": str(raw.get("base_url") or ""),
        "model": str(raw.get("model") or ""),
        "context_window_input": int(raw.get("context_window_input") or 8192),
        "context_window_output": int(raw.get("context_window_output") or 4096),
        "needs_api_key": bool(raw.get("needs_api_key", True)),
    }


def _load_from_disk(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("presets") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("provider_catalog.json missing presets[]")
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        norm = _normalize_preset(item)
        if norm:
            out.append(norm)
    if not out:
        raise ValueError("provider_catalog.json has no valid presets")
    return out


def _ensure_cache() -> list[dict[str, Any]]:
    global _cached, _cached_mtime, _cached_path
    path = _catalog_path()
    with _lock:
        try:
            mtime = path.stat().st_mtime if path.is_file() else None
        except OSError:
            mtime = None
        if (
            _cached
            and _cached_path == path
            and mtime is not None
            and mtime == _cached_mtime
        ):
            return [dict(p) for p in _cached]
        if path.is_file():
            try:
                loaded = _load_from_disk(path)
                _cached = loaded
                _cached_mtime = mtime
                _cached_path = path
                return [dict(p) for p in _cached]
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("Failed to load provider_catalog.json: %s", exc)
        if not _cached:
            _cached = [dict(p) for p in _FALLBACK_PRESETS]
            _cached_mtime = None
            _cached_path = path
            logger.warning("Using built-in fallback agent presets (demo+ollama)")
        return [dict(p) for p in _cached]


def list_presets() -> list[dict[str, Any]]:
    return _ensure_cache()


def get_preset(preset_id: str) -> dict[str, Any] | None:
    for p in _ensure_cache():
        if p.get("id") == preset_id:
            return dict(p)
    return None


# Back-compat alias used by older imports / tests
def _reload_presets_for_tests() -> None:
    global _cached, _cached_mtime
    with _lock:
        _cached = []
        _cached_mtime = None
