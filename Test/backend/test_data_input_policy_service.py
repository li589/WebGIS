"""data_input_policies：seed/runtime 合并、scope 优先级、allow_silent 判定。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import data_input_policy_service as svc


@pytest.fixture(autouse=True)
def _clear_policy_cache():
    svc.clear_policy_cache()
    yield
    svc.clear_policy_cache()


def test_load_seed_includes_omega_align_confirm():
    doc = svc.load_data_input_policies(force=True)
    assert doc["version"] >= 1
    assert any(
        p["input_key"] == svc.INPUT_KEY_TIME_WINDOW_ALIGN
        and p["mode"] == "allow_with_confirm"
        for p in doc["policies"]
    )


def test_runtime_override_merges_by_id(tmp_path: Path):
    runtime = tmp_path / "data_input_policies.json"
    runtime.write_text(
        json.dumps(
            {
                "version": 2,
                "policies": [
                    {
                        "id": "omega-sf-fenkuai-time-window-align",
                        "scope": "module",
                        "scope_id": "omega_sf_fenkuai",
                        "input_key": svc.INPUT_KEY_TIME_WINDOW_ALIGN,
                        "mode": "allow_silent",
                        "notes": "test override",
                    },
                    {
                        "id": "custom-deny-star",
                        "scope": "*",
                        "input_key": svc.INPUT_KEY_TIME_WINDOW_ALIGN,
                        "mode": "deny",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with patch.object(svc, "_runtime_override_path", return_value=runtime):
        svc.clear_policy_cache()
        doc = svc.load_data_input_policies(force=True)
    assert doc["version"] == 2
    assert doc["runtime_override_present"] is True
    overridden = next(
        p for p in doc["policies"] if p["id"] == "omega-sf-fenkuai-time-window-align"
    )
    assert overridden["mode"] == "allow_silent"
    assert any(p["id"] == "custom-deny-star" for p in doc["policies"])


def test_resolve_policy_mode_prefers_layer_over_module(tmp_path: Path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"version": 1, "policies": []}), encoding="utf-8")
    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "version": 1,
                "policies": [
                    {
                        "id": "mod",
                        "scope": "module",
                        "scope_id": "omega_sf_fenkuai",
                        "input_key": svc.INPUT_KEY_TIME_WINDOW_ALIGN,
                        "mode": "allow_silent",
                    },
                    {
                        "id": "layer",
                        "scope": "layer_id",
                        "scope_id": "method-fy-omega-doy-dynamic",
                        "input_key": svc.INPUT_KEY_TIME_WINDOW_ALIGN,
                        "mode": "deny",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    with (
        patch.object(svc, "_SEED_PATH", seed),
        patch.object(svc, "_runtime_override_path", return_value=runtime),
    ):
        svc.clear_policy_cache()
        mode = svc.resolve_policy_mode(
            svc.INPUT_KEY_TIME_WINDOW_ALIGN,
            module="omega_sf_fenkuai",
            layer_id="method-fy-omega-doy-dynamic",
        )
    assert mode == "deny"


def test_should_apply_align_from_relax_flags_or_silent(tmp_path: Path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"version": 1, "policies": []}), encoding="utf-8")
    empty = tmp_path / "empty_policies.json"
    empty.write_text(json.dumps({"version": 1, "policies": []}), encoding="utf-8")
    with (
        patch.object(svc, "_SEED_PATH", seed),
        patch.object(svc, "_runtime_override_path", return_value=empty),
    ):
        svc.clear_policy_cache()
        assert (
            svc.should_apply_time_window_align(
                relax_flags={svc.INPUT_KEY_TIME_WINDOW_ALIGN: True},
                module="omega_sf_fenkuai",
            )
            is True
        )
        assert (
            svc.should_apply_time_window_align(
                relax_flags={},
                module="omega_sf_fenkuai",
            )
            is False
        )

    silent = tmp_path / "silent_policies.json"
    silent.write_text(
        json.dumps(
            {
                "version": 1,
                "policies": [
                    {
                        "id": "silent",
                        "scope": "module",
                        "scope_id": "omega_sf_fenkuai",
                        "input_key": svc.INPUT_KEY_TIME_WINDOW_ALIGN,
                        "mode": "allow_silent",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with (
        patch.object(svc, "_SEED_PATH", seed),
        patch.object(svc, "_runtime_override_path", return_value=silent),
    ):
        svc.clear_policy_cache()
        assert (
            svc.should_apply_time_window_align(
                relax_flags={},
                module="omega_sf_fenkuai",
            )
            is True
        )


def test_load_seed_includes_source_route_silent():
    doc = svc.load_data_input_policies(force=True)
    assert any(
        p["input_key"] == svc.INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST
        and p["scope"] == "*"
        and p["mode"] == "allow_silent"
        for p in doc["policies"]
    )


def test_save_runtime_policies_atomic(tmp_path: Path):
    runtime = tmp_path / "data_input_policies.json"
    with patch.object(svc, "_runtime_override_path", return_value=runtime):
        svc.clear_policy_cache()
        doc = svc.save_runtime_data_input_policies(
            version=3,
            policies=[
                {
                    "id": "ndvi-route-confirm",
                    "scope": "layer_id",
                    "scope_id": "ndvi",
                    "input_key": svc.INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST,
                    "mode": "allow_with_confirm",
                    "notes": "ndvi confirm",
                }
            ],
        )
    assert runtime.is_file()
    assert doc["version"] == 3
    assert doc["runtime_override_present"] is True
    mode = None
    with patch.object(svc, "_runtime_override_path", return_value=runtime):
        svc.clear_policy_cache()
        mode = svc.resolve_policy_mode(
            svc.INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST,
            layer_id="ndvi",
        )
    assert mode == "allow_with_confirm"


def test_save_runtime_rejects_duplicate_ids(tmp_path: Path):
    runtime = tmp_path / "data_input_policies.json"
    with patch.object(svc, "_runtime_override_path", return_value=runtime):
        svc.clear_policy_cache()
        with pytest.raises(ValueError, match="duplicate"):
            svc.save_runtime_data_input_policies(
                version=1,
                policies=[
                    {
                        "id": "dup",
                        "scope": "*",
                        "input_key": svc.INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST,
                        "mode": "deny",
                    },
                    {
                        "id": "dup",
                        "scope": "layer_id",
                        "scope_id": "ndvi",
                        "input_key": svc.INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST,
                        "mode": "allow_silent",
                    },
                ],
            )


def test_get_data_input_policies_endpoint_shape():
    """路由依赖较重；直接校验契约模型可序列化策略投影。"""
    from shared.contracts.api_contracts import (
        DataInputPoliciesResponse,
        DataInputPoliciesUpdateRequest,
        DataInputPolicyItem,
    )

    doc = svc.load_data_input_policies(force=True)
    items = [
        DataInputPolicyItem(
            id=str(p["id"]),
            scope=str(p["scope"]),
            scope_id=p.get("scope_id"),
            input_key=str(p["input_key"]),
            mode=str(p["mode"]),
            notes=p.get("notes"),
        )
        for p in doc["policies"]
    ]
    body = DataInputPoliciesResponse(
        version=int(doc["version"]),
        policies=items,
        runtime_override_present=False,
    )
    dumped = body.model_dump()
    assert dumped["version"] >= 1
    assert isinstance(dumped["policies"], list)
    assert any(
        p["input_key"] == svc.INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST for p in dumped["policies"]
    )
    assert isinstance(dumped.get("seed_policies"), list)
    assert isinstance(dumped.get("runtime_policies"), list)
    update = DataInputPoliciesUpdateRequest(version=1, policies=items[:1])
    assert update.policies[0].id


def test_load_exposes_seed_and_runtime_separately(tmp_path: Path):
    seed = tmp_path / "seed.json"
    seed.write_text(
        json.dumps(
            {
                "version": 1,
                "policies": [
                    {
                        "id": "seed-only",
                        "scope": "*",
                        "input_key": svc.INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST,
                        "mode": "allow_silent",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "version": 2,
                "policies": [
                    {
                        "id": "runtime-only",
                        "scope": "layer_id",
                        "scope_id": "ndvi",
                        "input_key": svc.INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST,
                        "mode": "deny",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with (
        patch.object(svc, "_SEED_PATH", seed),
        patch.object(svc, "_runtime_override_path", return_value=runtime),
    ):
        svc.clear_policy_cache()
        doc = svc.load_data_input_policies(force=True)
    assert {p["id"] for p in doc["seed_policies"]} == {"seed-only"}
    assert {p["id"] for p in doc["runtime_policies"]} == {"runtime-only"}
    assert {p["id"] for p in doc["policies"]} == {"seed-only", "runtime-only"}
