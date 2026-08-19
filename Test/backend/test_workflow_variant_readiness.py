"""X2 工作流变体 readiness 二元语义测试。

覆盖阶段 2 契约（WorkflowVariantDef / LayerDescriptor.workflow_variants）投影与
``describe_layer_run_readiness`` 的变体分支：在线凭据就绪 OR 本地数据可解析 → ready；
皆缺 → blocked。无变体图层维持既有单变体语义。

运行方式（仓库根执行）::

    Env/Python312/python.exe -m pytest Test/backend/test_workflow_variant_readiness.py -q
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/15")

import json  # noqa: E402

from app.services import workflow_request_resolver as resolver  # noqa: E402

_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "Code" / "backend"
_CATALOG_SEEDS = _BACKEND_ROOT / "app" / "catalog_seeds" / "layer_descriptors.json"
_WORKFLOW_SEEDS_DIR = _BACKEND_ROOT / "workflow_seeds" / "system"

OMEGA_VARIANT_LAYERS = {
    "method-smap-omega-doy-dynamic": ("omega_sf_fenkuai_smap_online", "earthdata"),
    "method-fy-omega-doy-dynamic": ("omega_sf_fenkuai_fy_online", "nsmc"),
    "method-smap-omega-doy-avg": ("omega_avg_daily_smap_online", "earthdata"),
    "method-fy-omega-doy-avg": ("omega_avg_daily_fy_online", "nsmc"),
}


def _load_layer_descriptors() -> list[dict]:
    with open(_CATALOG_SEEDS, encoding="utf-8") as f:
        return json.load(f)


def test_omega_layers_declare_online_default_and_variants() -> None:
    """4 个 ω method 图层：workflow_id 默认 online + workflow_variants 双变体 + 凭据声明。"""
    layers = {item["layer_id"]: item for item in _load_layer_descriptors()}
    for layer_id, (online_seed, profile) in OMEGA_VARIANT_LAYERS.items():
        layer = layers.get(layer_id)
        assert layer is not None, f"{layer_id} missing from layer_descriptors.json"
        assert (
            layer["workflow_id"] == online_seed
        ), f"{layer_id}: workflow_id={layer['workflow_id']} 应默认指向 online 种子"
        variants = layer.get("workflow_variants") or {}
        assert set(variants) == {
            "online",
            "local",
        }, f"{layer_id}: workflow_variants 键应为 online/local，实际 {sorted(variants)}"
        assert variants["online"]["workflow_id"] == online_seed
        assert variants["online"]["credential_profile"] == profile
        assert variants["online"]["label"] == "在线反演"
        assert variants["local"]["label"] == "本地反演"
        assert variants["local"]["workflow_id"].endswith("_single")
        # 变体指向的两个种子文件都存在
        for variant in variants.values():
            seed_path = _WORKFLOW_SEEDS_DIR / f"{variant['workflow_id']}.json"
            assert seed_path.exists(), f"{layer_id}: 缺少变体种子 {seed_path.name}"


def _make_descriptor(
    *, variants: dict | None, layer_id: str = "layer-x"
) -> SimpleNamespace:
    return SimpleNamespace(
        layer_id=layer_id,
        is_merged_group=False,
        members=[],
        status="available",
        engine="python_provider",
        module_name="omega_sf_fenkuai",
        workflow_id="omega_sf_fenkuai_fy_online",
        workflow_name="omega_sf_fenkuai_fy_online",
        run_readiness_notes=[],
        run_readiness_summary=None,
        default_data_access_sources={},
        workflow_variants=variants,
    )


def _variant(credential_profile: str | None = None) -> dict:
    return {
        "workflow_id": "omega_sf_fenkuai_fy_online",
        "label": "在线反演",
        "credential_profile": credential_profile,
    }


def _describe(descriptor: SimpleNamespace, unresolved: list[dict]) -> dict | None:
    return resolver._describe_workflow_variant_readiness(descriptor, unresolved)


def test_variant_online_ready_local_missing_is_ready() -> None:
    """在线凭据就绪 + 本地数据缺失 → ready（默认走在线执行路径）。"""
    descriptor = _make_descriptor(
        variants={
            "online": _variant("nsmc"),
            "local": {"workflow_id": "omega_sf_fenkuai_fy_single", "label": "本地反演"},
        }
    )
    unresolved = [{"dataset_name": "fy3d_folder", "candidate_sources": ["I:/FY3D"]}]
    with patch.object(resolver, "_portal_credential_profile_ready", return_value=True):
        result = _describe(descriptor, unresolved)
    assert result is not None
    assert result["readiness"] == "ready"
    assert result["online_ready"] is True
    assert result["local_ready"] is False
    assert any("在线反演就绪" in note for note in result["notes"])
    assert any("本地反演未就绪" in note for note in result["notes"])


def test_variant_online_missing_local_ready_is_ready() -> None:
    """在线凭据缺失 + 本地数据就绪 → ready（可切换本地变体执行）。"""
    descriptor = _make_descriptor(
        variants={
            "online": _variant("nsmc"),
            "local": {"workflow_id": "omega_sf_fenkuai_fy_single", "label": "本地反演"},
        }
    )
    with patch.object(resolver, "_portal_credential_profile_ready", return_value=False):
        result = _describe(descriptor, [])
    assert result is not None
    assert result["readiness"] == "ready"
    assert result["online_ready"] is False
    assert result["local_ready"] is True


def test_variant_both_missing_is_blocked() -> None:
    """在线凭据与本地数据皆缺 → blocked，notes 指明缺失内容。"""
    descriptor = _make_descriptor(
        variants={
            "online": _variant("nsmc"),
            "local": {"workflow_id": "omega_sf_fenkuai_fy_single", "label": "本地反演"},
        }
    )
    unresolved = [{"dataset_name": "fy3d_folder", "candidate_sources": []}]
    with patch.object(resolver, "_portal_credential_profile_ready", return_value=False):
        result = _describe(descriptor, unresolved)
    assert result is not None
    assert result["readiness"] == "blocked"
    assert result["online_ready"] is False
    assert result["local_ready"] is False
    assert any("缺少门户凭据 nsmc" in note for note in result["notes"])


def test_variant_without_variants_returns_none() -> None:
    """无变体 descriptor → None（维持既有单变体语义）。"""
    assert _describe(_make_descriptor(variants=None), []) is None


def test_variant_online_only_local_resolvable_not_local_ready() -> None:
    """仅声明 online 变体时，本地数据可解析也不得误报「本地反演就绪/可用」。

    回归守护：``local_ready`` 必须以 ``local is not None`` 为前提。
    """
    descriptor = _make_descriptor(variants={"online": _variant("nsmc")})
    with patch.object(resolver, "_portal_credential_profile_ready", return_value=True):
        result = _describe(descriptor, [])
    assert result is not None
    assert result["readiness"] == "ready"
    assert result["online_ready"] is True
    assert result["local_ready"] is False
    assert "本地反演" not in (result["summary"] or "")
    assert not any("本地反演就绪" in note for note in result["notes"])


def test_describe_layer_run_readiness_online_ready_overrides_local_block() -> None:
    """主流程：online 凭据就绪时本地数据缺失不 block（readiness=ready + 变体 notes）。"""
    descriptor = _make_descriptor(
        variants={
            "online": _variant("nsmc"),
            "local": {"workflow_id": "omega_sf_fenkuai_fy_single", "label": "本地反演"},
        }
    )
    unresolved = [{"dataset_name": "fy3d_folder", "candidate_sources": []}]

    fake_populator = SimpleNamespace(
        describe_readiness=lambda d: {"unresolved_default_datasets": unresolved}
    )
    with (
        patch.object(resolver, "get_layer_descriptor", return_value=descriptor),
        patch.object(resolver, "get_engine_populator", return_value=fake_populator),
        patch.object(resolver, "_portal_credential_profile_ready", return_value=True),
    ):
        result = resolver.describe_layer_run_readiness("layer-x")
    assert result is not None
    assert result["run_readiness"] == "ready"
    assert "变体可用" in (result["run_readiness_summary"] or "")
    assert any("在线反演就绪" in note for note in result["run_readiness_notes"])


def test_describe_layer_run_readiness_blocked_without_online_creds() -> None:
    """主流程：online 凭据缺失且本地数据缺失 → blocked（变体不豁免）。"""
    descriptor = _make_descriptor(
        variants={
            "online": _variant("nsmc"),
            "local": {"workflow_id": "omega_sf_fenkuai_fy_single", "label": "本地反演"},
        }
    )
    unresolved = [{"dataset_name": "fy3d_folder", "candidate_sources": []}]

    fake_populator = SimpleNamespace(
        describe_readiness=lambda d: {"unresolved_default_datasets": unresolved}
    )
    with (
        patch.object(resolver, "get_layer_descriptor", return_value=descriptor),
        patch.object(resolver, "get_engine_populator", return_value=fake_populator),
        patch.object(resolver, "_portal_credential_profile_ready", return_value=False),
    ):
        result = resolver.describe_layer_run_readiness("layer-x")
    assert result is not None
    assert result["run_readiness"] == "blocked"
    assert "默认数据源未就绪" in (result["run_readiness_summary"] or "")
