"""Shared utilities for the download service modules.

Extracted from the original ``download_service.py`` god class to break the
bidirectional coupling between orchestration, progress tracking and manifest
writing. These helpers are stateless and safe to share across the three
sibling modules:

- :mod:`download_orchestrator` (planning + source URI resolution)
- :mod:`download_progress_tracker` (follow-up fetch execution)
- :mod:`download_manifest_writer` (artifact result ref construction)

Keeping them here avoids both circular imports and duplicate implementations.
"""

from __future__ import annotations

import json
from typing import Any


def coerce_int(value: Any) -> int | None:
    """Coerce arbitrary input to ``int``; return ``None`` on failure.

    Accepts ``None`` passthrough, numeric strings, and floats. Returns
    ``None`` for non-numeric strings or unsupported types so callers can
    fall back to defaults via ``or`` without raising.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_str_list(value: Any) -> list[str]:
    """Coerce arbitrary input to a clean list of non-empty strings.

    Accepts ``None``, single strings, and lists of strings. Empty / whitespace
    items are dropped. Non-string items in lists are ignored.
    """
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized:
                    items.append(normalized)
        return items
    return []


def clone_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Deep-clone a JSON-serialisable dict via round-trip serialisation.

    Used when mutating ``inline_data`` payloads so the original
    ``WorkflowResultReference.inline_data`` is not aliased by reference.
    """
    return json.loads(json.dumps(payload, ensure_ascii=False))
