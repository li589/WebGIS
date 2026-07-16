"""Compare live FastAPI OpenAPI schema against committed frontend/openapi.json.

Exits non-zero when critical path definitions drift.

Usage:
    python scripts/check_openapi_drift.py [--update-hint]

Critical paths checked (prefix or exact):
    /weather/tiles
    /unified-tiles
    /config
    /workflow-runs
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


CRITICAL_PREFIXES: tuple[str, ...] = (
    "/weather/tiles",
    "/unified-tiles",
    "/config",
    "/workflow-runs",
)


def _setup_import_paths() -> tuple[Path, Path]:
    backend_root = Path(__file__).resolve().parent.parent
    code_root = backend_root.parent
    gee_src = str(backend_root / "app" / "gee" / "core" / "src")
    for path in (str(backend_root), str(code_root), gee_src):
        if path not in sys.path:
            sys.path.insert(0, path)
    return backend_root, code_root


def _load_live_openapi() -> dict[str, Any]:
    from app.main import app

    return app.openapi()


def _load_committed_openapi(code_root: Path) -> dict[str, Any]:
    openapi_path = code_root / "frontend" / "openapi.json"
    if not openapi_path.is_file():
        raise FileNotFoundError(f"Committed OpenAPI not found: {openapi_path}")
    return json.loads(openapi_path.read_text(encoding="utf-8"))


def _critical_paths(paths: dict[str, Any]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for path, definition in paths.items():
        if any(path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "{") for prefix in CRITICAL_PREFIXES):
            selected[path] = definition
        elif any(path.startswith(prefix) for prefix in CRITICAL_PREFIXES):
            selected[path] = definition
    return dict(sorted(selected.items()))


def _path_methods(paths: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path, definition in paths.items():
        methods = sorted(
            key.lower()
            for key in definition
            if key.lower() in {"get", "post", "put", "patch", "delete", "head", "options"}
        )
        result[path] = methods
    return result


def _diff_paths(live: dict[str, Any], committed: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    live_methods = _path_methods(live)
    committed_methods = _path_methods(committed)
    live_keys = set(live_methods)
    committed_keys = set(committed_methods)

    missing_in_committed = sorted(live_keys - committed_keys)
    missing_in_live = sorted(committed_keys - live_keys)
    if missing_in_committed:
        issues.append(f"Paths in live app but missing from openapi.json: {missing_in_committed}")
    if missing_in_live:
        issues.append(f"Paths in openapi.json but missing from live app: {missing_in_live}")

    for path in sorted(live_keys & committed_keys):
        if live_methods[path] != committed_methods[path]:
            issues.append(
                f"{path}: method mismatch live={live_methods[path]} committed={committed_methods[path]}"
            )

    return issues


def check_openapi_drift() -> list[str]:
    backend_root, code_root = _setup_import_paths()

    live_schema = _load_live_openapi()
    committed_schema = _load_committed_openapi(code_root)

    live_critical = _critical_paths(live_schema.get("paths", {}))
    committed_critical = _critical_paths(committed_schema.get("paths", {}))

    return _diff_paths(live_critical, committed_critical)


def main() -> int:
    try:
        issues = check_openapi_drift()
    except Exception as exc:
        print(f"ERROR: failed to check OpenAPI drift: {exc}", file=sys.stderr)
        return 2

    if not issues:
        print("OK: critical OpenAPI paths match committed frontend/openapi.json")
        return 0

    print("OpenAPI drift detected on critical paths:", file=sys.stderr)
    for issue in issues:
        print(f"  - {issue}", file=sys.stderr)
    print(
        "\nTo refresh: python scripts/export_openapi.py && cd ../frontend && npm run gen:types",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
