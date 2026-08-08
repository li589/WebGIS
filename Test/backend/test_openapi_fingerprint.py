"""Unit tests for deepened OpenAPI operation fingerprints (no app boot)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "Code"
    / "backend"
    / "scripts"
    / "check_openapi_drift.py"
)
_spec = importlib.util.spec_from_file_location("check_openapi_drift", _SCRIPT)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["check_openapi_drift"] = _mod
_spec.loader.exec_module(_mod)

_operation_fingerprint = _mod._operation_fingerprint
_diff_paths = _mod._diff_paths


def test_operation_fingerprint_stable_for_params_and_body() -> None:
    op = {
        "operationId": "list_api_keys",
        "parameters": [
            {"name": "limit", "in": "query", "required": False},
            {"name": "x", "in": "header", "required": True},
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Foo"},
                }
            }
        },
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Bar"},
                    }
                }
            },
            "401": {"description": "nope"},
        },
        "security": [{"APIKeyHeader": []}],
    }
    fp = _operation_fingerprint(op)
    assert fp["operationId"] == "list_api_keys"
    assert fp["requestBody"] == "#/components/schemas/Foo"
    assert fp["responses"]["200"] == "#/components/schemas/Bar"
    assert fp["security"] == [{"APIKeyHeader": []}]


def test_diff_paths_detects_fingerprint_mismatch() -> None:
    live = {
        "/config/api-keys": {
            "get": {
                "operationId": "list_api_keys",
                "parameters": [],
                "responses": {"200": {"description": "ok"}},
                "security": [{"APIKeyHeader": []}],
            }
        }
    }
    committed = {
        "/config/api-keys": {
            "get": {
                "operationId": "list_api_keys",
                "parameters": [],
                "responses": {"200": {"description": "ok"}},
                "security": None,
            }
        }
    }
    issues = _diff_paths(live, committed)
    assert any("fingerprint mismatch" in i for i in issues)
