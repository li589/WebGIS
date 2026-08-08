"""Compare live FastAPI OpenAPI schema against committed frontend/openapi.json.

Exits non-zero when critical path definitions drift.

Usage:
    python scripts/check_openapi_drift.py [--update-hint]

Critical paths checked (prefix or exact):
    /weather          (covers /weather/tiles, /weather/point, /weather/coverage, ...)
    /unified-tiles
    /config
    /workflow-runs
    /workflow-definitions
    /import           (covers /import/raster, /import/upload/*, /import/crs-options/*, ...)
    /layers
    /export
    /overlay-tiles
    /runtime
    /gee
    /artifacts
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


# 发布就绪修复（P0-6）：从 4 个前缀扩展到覆盖全部对外 API 面，
# 防止 /import /layers /export /gee /runtime /artifacts 等前缀的契约漂移逃过 CI。
CRITICAL_PREFIXES: tuple[str, ...] = (
    "/weather",
    "/unified-tiles",
    "/config",
    "/workflow-runs",
    "/workflow-definitions",
    "/import",
    "/layers",
    "/export",
    "/overlay-tiles",
    "/runtime",
    "/gee",
    "/artifacts",
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
        if any(
            path == prefix
            or path.startswith(prefix + "/")
            or path.startswith(prefix + "{")
            for prefix in CRITICAL_PREFIXES
        ):
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
            if key.lower()
            in {"get", "post", "put", "patch", "delete", "head", "options"}
        )
        result[path] = methods
    return result


def _schema_ref_token(node: Any) -> str | None:
    """Extract a stable $ref / type token from requestBody or response content."""
    if not isinstance(node, dict):
        return None
    if "$ref" in node:
        return str(node["$ref"])
    content = node.get("content")
    if isinstance(content, dict):
        for media in content.values():
            if not isinstance(media, dict):
                continue
            schema = media.get("schema")
            if isinstance(schema, dict):
                if "$ref" in schema:
                    return str(schema["$ref"])
                if "type" in schema:
                    return f"type:{schema.get('type')}"
    schema = node.get("schema")
    if isinstance(schema, dict):
        if "$ref" in schema:
            return str(schema["$ref"])
        if "type" in schema:
            return f"type:{schema.get('type')}"
    return None


def _operation_fingerprint(op: dict[str, Any]) -> dict[str, Any]:
    """Shallow structural fingerprint (params + body/response refs), not full schema."""
    params = []
    for p in op.get("parameters") or []:
        if not isinstance(p, dict):
            continue
        # Resolve inline only; skip unresolved $ref parameter objects lightly
        if "$ref" in p:
            params.append({"$ref": p["$ref"]})
            continue
        params.append(
            {
                "name": p.get("name"),
                "in": p.get("in"),
                "required": bool(p.get("required", False)),
            }
        )
    params.sort(key=lambda x: (str(x.get("in")), str(x.get("name")), str(x.get("$ref"))))
    responses: dict[str, str | None] = {}
    for code, resp in (op.get("responses") or {}).items():
        if str(code) not in {"200", "201", "202", "204", "400", "401", "403", "422"}:
            continue
        responses[str(code)] = _schema_ref_token(resp)
    return {
        "operationId": op.get("operationId"),
        "parameters": params,
        "requestBody": _schema_ref_token(op.get("requestBody") or {}),
        "responses": dict(sorted(responses.items())),
        "security": op.get("security"),
    }


def _diff_paths(live: dict[str, Any], committed: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    live_methods = _path_methods(live)
    committed_methods = _path_methods(committed)
    live_keys = set(live_methods)
    committed_keys = set(committed_methods)

    missing_in_committed = sorted(live_keys - committed_keys)
    missing_in_live = sorted(committed_keys - live_keys)
    if missing_in_committed:
        issues.append(
            f"Paths in live app but missing from openapi.json: {missing_in_committed}"
        )
    if missing_in_live:
        issues.append(
            f"Paths in openapi.json but missing from live app: {missing_in_live}"
        )

    for path in sorted(live_keys & committed_keys):
        if live_methods[path] != committed_methods[path]:
            issues.append(
                f"{path}: method mismatch live={live_methods[path]} committed={committed_methods[path]}"
            )
            continue
        for method in live_methods[path]:
            live_fp = _operation_fingerprint(live[path].get(method) or {})
            committed_fp = _operation_fingerprint(committed[path].get(method) or {})
            if live_fp != committed_fp:
                issues.append(
                    f"{path} {method}: operation fingerprint mismatch "
                    f"(params/body/response/security/operationId)"
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
        print(
            "OK: critical OpenAPI paths + operation fingerprints match "
            "committed frontend/openapi.json"
        )
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
