"""图层-工作流交叉校验测试。

验证图层描述符（catalog_seeds）与工作流 seed（workflow_seeds/system）之间的
双向链接一致性。这些测试同时充当数据完整性守卫：任何新增/删除图层或 seed 时，
若链接关系断裂，CI 会立即失败。

运行方式（仓库根执行）::

    Env/Python312/python.exe -m pytest Test/backend/test_layer_workflow_validation.py -q
"""

from __future__ import annotations

import os

# 确保测试环境变量（conftest.py 已设 ENVIRONMENT=test，此处补齐 REDIS_URL）
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/15")

from pathlib import Path  # noqa: E402

from app.services.layer_workflow_validator import (  # noqa: E402
    CODE_MISSING_LINKED_LAYER,
    CODE_MISSING_WORKFLOW_SEED,
    CODE_OVERLAY_REGISTRY_HAS_WORKFLOW_ID,
    CODE_PYTHON_PROVIDER_NO_WORKFLOW_NAME,
    CODE_WEATHER_LAYER_HAS_WORKFLOW_ID,
    _load_catalog_layers,
    _load_workflow_seeds,
    validate_layer_workflow_links,
)

# ─── catalog_seeds / workflow_seeds 路径（与 validator 模块保持一致）──────────
_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "Code" / "backend"
_CATALOG_SEEDS_DIR = _BACKEND_ROOT / "app" / "catalog_seeds"
_WORKFLOW_SEEDS_DIR = _BACKEND_ROOT / "workflow_seeds" / "system"


# ─── 辅助：按来源拆分 catalog 图层 ────────────────────────────────────────────
def _load_layer_descriptors() -> list[dict]:
    """仅加载 layer_descriptors.json（不含 weather_descriptors.json）。"""
    import json

    path = _CATALOG_SEEDS_DIR / "layer_descriptors.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_weather_descriptors() -> list[dict]:
    """仅加载 weather_descriptors.json。"""
    import json

    path = _CATALOG_SEEDS_DIR / "weather_descriptors.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── 测试用例 ────────────────────────────────────────────────────────────────


def test_all_python_provider_layers_have_workflow_seed():
    """遍历 layer_descriptors.json 中 engine=python_provider 的图层，
    验证 workflow_name 对应的 seed 文件存在于 workflow_seeds/system/。
    """
    layers = _load_layer_descriptors()
    python_provider_layers = [
        layer for layer in layers if layer.get("engine") == "python_provider"
    ]

    # 确保测试覆盖到 python_provider 图层（防止数据被清空后测试静默通过）
    assert len(python_provider_layers) >= 1, (
        "layer_descriptors.json 中应至少有 1 个 python_provider 图层"
    )

    missing: list[str] = []
    for layer in python_provider_layers:
        layer_id = layer.get("layer_id", "<unknown>")
        workflow_name = layer.get("workflow_name")

        # python_provider 图层应有 workflow_name（无则由 warning 覆盖，此处跳过）
        if not workflow_name:
            continue

        seed_file = _WORKFLOW_SEEDS_DIR / f"{workflow_name}.json"
        if not seed_file.exists():
            missing.append(
                f"图层 '{layer_id}' 的 workflow_name='{workflow_name}' "
                f"对应 seed 文件不存在: {seed_file}"
            )

    assert not missing, (
        "以下 python_provider 图层的 workflow_name 缺少对应 seed 文件:\n"
        + "\n".join(missing)
    )

    # 同时验证 validator 函数未报 error 级别的 missing_workflow_seed
    issues = validate_layer_workflow_links()
    seed_errors = [
        i for i in issues
        if i.code == CODE_MISSING_WORKFLOW_SEED and i.level == "error"
    ]
    assert not seed_errors, (
        "validate_layer_workflow_links() 报告了 missing_workflow_seed error:\n"
        + "\n".join(i.message for i in seed_errors)
    )


def test_all_seed_linked_layers_exist():
    """遍历所有 workflow seeds，验证 linked_layer_id（非 null）对应的图层
    存在于 catalog（layer_descriptors.json + weather_descriptors.json）。
    """
    seeds = _load_workflow_seeds()
    all_layers = _load_catalog_layers()
    layer_ids = {
        layer["layer_id"] for layer in all_layers if layer.get("layer_id")
    }

    # 确保测试覆盖到带 linked_layer_id 的 seed
    linked_seeds = [
        seed for seed in seeds
        if isinstance(seed.get("_meta"), dict)
        and seed["_meta"].get("linked_layer_id")
    ]
    assert len(linked_seeds) >= 1, (
        "workflow_seeds/system/ 中应至少有 1 个带 linked_layer_id 的 seed"
    )

    missing: list[str] = []
    for seed in linked_seeds:
        meta = seed["_meta"]
        linked_layer_id = meta["linked_layer_id"]
        wf_id = seed.get("workflow_id", "<unknown>")
        if linked_layer_id not in layer_ids:
            missing.append(
                f"seed '{wf_id}' 的 linked_layer_id='{linked_layer_id}' "
                f"在 catalog 中找不到对应图层"
            )

    assert not missing, (
        "以下 seed 的 linked_layer_id 在 catalog 中缺失:\n" + "\n".join(missing)
    )

    # 同时验证 validator 函数未报 error 级别的 missing_linked_layer
    issues = validate_layer_workflow_links()
    layer_errors = [
        i for i in issues
        if i.code == CODE_MISSING_LINKED_LAYER and i.level == "error"
    ]
    assert not layer_errors, (
        "validate_layer_workflow_links() 报告了 missing_linked_layer error:\n"
        + "\n".join(i.message for i in layer_errors)
    )


def test_weather_layers_no_workflow_id():
    """验证 weather_descriptors.json 中的图层无 workflow_id。

    天气图层的主路径为 /weather/tiles，不应绑定 workflow_id。
    """
    weather_layers = _load_weather_descriptors()

    assert len(weather_layers) >= 1, "weather_descriptors.json 不应为空"

    offenders: list[str] = []
    for layer in weather_layers:
        layer_id = layer.get("layer_id", "<unknown>")
        workflow_id = layer.get("workflow_id")
        if workflow_id:
            offenders.append(
                f"天气图层 '{layer_id}' 设置了 workflow_id='{workflow_id}'"
            )

    assert not offenders, (
        "以下天气图层错误地设置了 workflow_id:\n" + "\n".join(offenders)
    )

    # 同时验证 validator 函数未报 weather_layer_has_workflow_id warning
    issues = validate_layer_workflow_links()
    weather_warnings = [
        i for i in issues if i.code == CODE_WEATHER_LAYER_HAS_WORKFLOW_ID
    ]
    assert not weather_warnings, (
        "validate_layer_workflow_links() 报告了 weather_layer_has_workflow_id:\n"
        + "\n".join(i.message for i in weather_warnings)
    )


def test_overlay_registry_layers_no_workflow_id():
    """验证 engine=overlay_registry 的图层无 workflow_id。

    overlay_registry 图层由 overlay_registry 直接提供瓦片，不应绑定 workflow_id。
    """
    layers = _load_layer_descriptors()
    overlay_layers = [
        layer for layer in layers if layer.get("engine") == "overlay_registry"
    ]

    assert len(overlay_layers) >= 1, (
        "layer_descriptors.json 中应至少有 1 个 overlay_registry 图层"
    )

    offenders: list[str] = []
    for layer in overlay_layers:
        layer_id = layer.get("layer_id", "<unknown>")
        workflow_id = layer.get("workflow_id")
        if workflow_id:
            offenders.append(
                f"overlay_registry 图层 '{layer_id}' 设置了 "
                f"workflow_id='{workflow_id}'"
            )

    assert not offenders, (
        "以下 overlay_registry 图层错误地设置了 workflow_id:\n"
        + "\n".join(offenders)
    )

    # 同时验证 validator 函数未报 overlay_registry_has_workflow_id warning
    issues = validate_layer_workflow_links()
    overlay_warnings = [
        i for i in issues if i.code == CODE_OVERLAY_REGISTRY_HAS_WORKFLOW_ID
    ]
    assert not overlay_warnings, (
        "validate_layer_workflow_links() 报告了 "
        "overlay_registry_has_workflow_id:\n"
        + "\n".join(i.message for i in overlay_warnings)
    )
