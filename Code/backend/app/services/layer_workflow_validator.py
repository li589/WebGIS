"""图层-工作流交叉校验机制

检查图层描述符（catalog_seeds）与工作流 seed（workflow_seeds/system）之间的
双向链接一致性，在 CI 与开发阶段尽早发现链接漂移：

1. ``python_provider`` 图层有 ``workflow_name`` 时，对应 seed 必须存在（error）
2. seed 有 ``linked_layer_id`` 时，对应图层必须存在（error）
3. ``python_provider`` 图层无 ``workflow_name`` 时，记录 warning
4. ``overlay_registry`` 图层不应有 ``workflow_id``（warning）
5. 天气图层（``source_type=weather``）不应有 ``workflow_id``（warning）
6. seed 节点 ``properties.layer_id`` 若存在，对应图层必须存在（error）

本模块仅读取文件系统，不依赖 Redis / DB / 运行时 settings，可在 CI 与单测中
直接调用。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─── 路径常量 ────────────────────────────────────────────────────────────────
# app/services/layer_workflow_validator.py
#   → parents[0] = app/services
#   → parents[1] = app
#   → parents[2] = backend（Code/backend）
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_CATALOG_SEEDS_DIR = _BACKEND_ROOT / "app" / "catalog_seeds"
_WORKFLOW_SEEDS_DIR = _BACKEND_ROOT / "workflow_seeds" / "system"

# ─── 校验 issue code 常量 ────────────────────────────────────────────────────
CODE_MISSING_WORKFLOW_SEED = "missing_workflow_seed"
CODE_MISSING_LINKED_LAYER = "missing_linked_layer"
CODE_PYTHON_PROVIDER_NO_WORKFLOW_NAME = "python_provider_missing_workflow_name"
CODE_OVERLAY_REGISTRY_HAS_WORKFLOW_ID = "overlay_registry_has_workflow_id"
CODE_WEATHER_LAYER_HAS_WORKFLOW_ID = "weather_layer_has_workflow_id"
CODE_NODE_LAYER_ID_DANGLING = "node_layer_id_dangling"


@dataclass
class ValidationIssue:
    """图层-工作流链接校验结果项。

    Attributes:
        level: 严重级别，``"error"`` 或 ``"warning"``。
        code: 机器可读的 issue 类型码（见模块级 ``CODE_*`` 常量）。
        message: 人类可读的描述。
        layer_id: 相关图层 ID（可为 None）。
        workflow_id: 相关工作流 ID（可为 None）。
    """

    level: str  # "error" | "warning"
    code: str
    message: str
    layer_id: str | None = None
    workflow_id: str | None = None


# ─── 数据加载 ────────────────────────────────────────────────────────────────
def _load_workflow_seeds() -> list[dict[str, Any]]:
    """从 ``workflow_seeds/system/`` 目录加载所有 seed JSON 文件。

    Returns:
        seed 字典列表，每项为单个 workflow seed 的完整 JSON 内容。
    """
    seeds: list[dict[str, Any]] = []
    if not _WORKFLOW_SEEDS_DIR.is_dir():
        logger.warning("Workflow seeds directory not found: %s", _WORKFLOW_SEEDS_DIR)
        return seeds
    for path in sorted(_WORKFLOW_SEEDS_DIR.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                seeds.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load workflow seed %s: %s", path, exc)
    return seeds


def _load_catalog_layers() -> list[dict[str, Any]]:
    """从 ``catalog_seeds/`` 目录加载图层描述符。

    读取 ``layer_descriptors.json`` 与 ``weather_descriptors.json`` 两个文件，
    合并为统一列表返回。

    Returns:
        图层描述符字典列表。
    """
    layers: list[dict[str, Any]] = []
    for name in ("layer_descriptors.json", "weather_descriptors.json"):
        path = _CATALOG_SEEDS_DIR / name
        if not path.exists():
            logger.warning("Catalog seed file not found: %s", path)
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                layers.extend(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load catalog seed %s: %s", path, exc)
    return layers


# ─── 公开接口 ────────────────────────────────────────────────────────────────
def validate_layer_workflow_links() -> list[ValidationIssue]:
    """校验图层描述符与工作流 seed 之间的双向链接一致性。

    执行以下检查：

    - **error**: ``python_provider`` 图层有 ``workflow_name`` 但对应 seed 不存在。
    - **error**: seed 有 ``linked_layer_id`` 但对应图层不在 catalog 中。
    - **warning**: ``python_provider`` 图层缺少 ``workflow_name``。
    - **warning**: ``overlay_registry`` 图层设置了 ``workflow_id``。
    - **warning**: 天气图层（``source_type=weather``）设置了 ``workflow_id``。
    - **error**: seed 节点 ``properties.layer_id`` 引用的图层不在 catalog 中。

    Returns:
        ``ValidationIssue`` 列表，包含所有 error 与 warning 级别的校验结果。
    """
    issues: list[ValidationIssue] = []

    seeds = _load_workflow_seeds()
    layers = _load_catalog_layers()

    # ── 构建查找结构 ────────────────────────────────────────────────────────
    layer_ids: set[str] = {
        layer["layer_id"] for layer in layers if layer.get("layer_id")
    }
    # seed 的 workflow_id 集合（同时作为 workflow_name 查找键）
    seed_workflow_ids: set[str] = set()
    for seed in seeds:
        wf_id = seed.get("workflow_id")
        if wf_id:
            seed_workflow_ids.add(wf_id)

    # ── 逐图层检查（Rules 1, 3, 4, 5）──────────────────────────────────────
    for layer in layers:
        layer_id = layer.get("layer_id")
        engine = layer.get("engine")
        workflow_name = layer.get("workflow_name")
        workflow_id = layer.get("workflow_id")
        source_type = layer.get("source_type")

        # Rule 1: python_provider 图层有 workflow_name 时，对应 seed 必须存在
        if engine == "python_provider" and workflow_name:
            if workflow_name not in seed_workflow_ids:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code=CODE_MISSING_WORKFLOW_SEED,
                        message=(
                            f"python_provider 图层 '{layer_id}' 的 "
                            f"workflow_name '{workflow_name}' "
                            f"对应的 seed 不存在于 workflow_seeds/system/"
                        ),
                        layer_id=layer_id,
                        workflow_id=workflow_name,
                    )
                )

        # Rule 3: python_provider 图层无 workflow_name 时，记录 warning
        if engine == "python_provider" and not workflow_name:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code=CODE_PYTHON_PROVIDER_NO_WORKFLOW_NAME,
                    message=(
                        f"python_provider 图层 '{layer_id}' 未设置 "
                        f"workflow_name，无法关联到工作流 seed"
                    ),
                    layer_id=layer_id,
                )
            )

        # Rule 4: overlay_registry 图层不应有 workflow_id
        if engine == "overlay_registry" and workflow_id:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code=CODE_OVERLAY_REGISTRY_HAS_WORKFLOW_ID,
                    message=(
                        f"overlay_registry 图层 '{layer_id}' 不应设置 "
                        f"workflow_id（当前值: '{workflow_id}'），"
                        f"overlay 图层由 overlay_registry 直接提供瓦片"
                    ),
                    layer_id=layer_id,
                    workflow_id=workflow_id,
                )
            )

        # Rule 5: 天气图层（source_type=weather）不应有 workflow_id
        if source_type == "weather" and workflow_id:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code=CODE_WEATHER_LAYER_HAS_WORKFLOW_ID,
                    message=(
                        f"天气图层 '{layer_id}' 不应设置 workflow_id"
                        f"（当前值: '{workflow_id}'），"
                        f"天气图层主路径为 /weather/tiles"
                    ),
                    layer_id=layer_id,
                    workflow_id=workflow_id,
                )
            )

    # ── 逐 seed 检查（Rule 2）──────────────────────────────────────────────
    for seed in seeds:
        meta = seed.get("_meta")
        if not isinstance(meta, dict):
            continue
        linked_layer_id = meta.get("linked_layer_id")
        wf_id = seed.get("workflow_id")
        if linked_layer_id:
            if linked_layer_id not in layer_ids:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code=CODE_MISSING_LINKED_LAYER,
                        message=(
                            f"工作流 seed '{wf_id}' 的 linked_layer_id "
                            f"'{linked_layer_id}' 对应的图层不存在于 catalog"
                        ),
                        layer_id=linked_layer_id,
                        workflow_id=wf_id,
                    )
                )

        # Rule 6: 节点级 properties.layer_id 引用的图层必须存在
        nodes = seed.get("nodes")
        if isinstance(nodes, list):
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                properties = node.get("properties")
                if not isinstance(properties, dict):
                    continue
                node_layer_id = properties.get("layer_id")
                if node_layer_id and node_layer_id not in layer_ids:
                    issues.append(
                        ValidationIssue(
                            level="error",
                            code=CODE_NODE_LAYER_ID_DANGLING,
                            message=(
                                f"工作流 seed '{wf_id}' 节点 {node.get('id')} "
                                f"的 properties.layer_id '{node_layer_id}' "
                                f"对应的图层不存在于 catalog"
                            ),
                            layer_id=node_layer_id,
                            workflow_id=wf_id,
                        )
                    )

    return issues
