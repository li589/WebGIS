"""ω 反演「一组三个」产物 tag 三方对齐回归（静态防线）。

守护 ActiveRunLayerGroup 占位成员 tag ↔ 算法 manifest main_layers ↔
python_provider_result_builder 产物 layer tag 三方一致，防止新增/改名 ω 种子或
产物类型后出现占位成员错位、终态清理误删真实图层。

对齐链（与 .trae/documents/2026-08-19-omega图层组在线反演续接执行计划.md §2.1 一致）：

1. 前端占位成员 tag ← 种子 ``extra.outputs``（workflow-expected-outputs.ts 读取）。
2. 算法 manifest ``main_layers`` 与 ``ProductRef.tags.layer`` ← 算法模块源码
   （modules/omega_sf_fenkuai.py、modules/omega_avg_daily.py）。
3. 产物 layer tag ← ``_MAPPABLE_PRODUCTS[type]["label"]`` 或产物自带 ``tags.layer``
   （python_provider_result_builder.py ``layer_tag = tags.get("layer") or label``）。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROVIDER_ROOT = _REPO_ROOT / "Code" / "algorithms" / "providers" / "Python"
_SEEDS_DIR = _REPO_ROOT / "Code" / "backend" / "workflow_seeds" / "system"

if str(_PROVIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROVIDER_ROOT))

import contracts  # noqa: E402, F401 — break circular import: contracts first

from app.services.python_provider_result_builder import (  # noqa: E402
    _MAPPABLE_PRODUCTS,
)

EXPECTED_TAGS = {"SM", "VOD", "OMEGA"}
BLOCK_DIR_TYPES = {
    "omega_sf_sm_block_dir": "SM",
    "omega_sf_vod_block_dir": "VOD",
    "omega_sf_omega_block_dir": "OMEGA",
}


def _iter_omega_seeds() -> list[tuple[str, dict]]:
    seeds: list[tuple[str, dict]] = []
    for path in sorted(_SEEDS_DIR.glob("omega_*.json")):
        seeds.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
    assert seeds, "no omega_*.json seeds found — seed directory drifted"
    return seeds


def _resolve_str_expr(expr: ast.expr, binding: dict[str, str]) -> str:
    """在字面量/绑定变量范围内求值为 str 的表达式（Constant/Name/f-string/.lower()）。"""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name):
        return binding.get(expr.id, "")
    if isinstance(expr, ast.JoinedStr):
        parts: list[str] = []
        for value in expr.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append(_resolve_str_expr(value.value, binding))
        return "".join(parts)
    if (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "lower"
    ):
        return _resolve_str_expr(expr.func.value, binding).lower()
    return ""


def _collect_productref_calls(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ProductRef"
        ):
            calls.append(node)
    return calls


def _extract_module_constants(module_path: Path) -> tuple[list[str], dict[str, str]]:
    """AST 解析算法模块：main_layers 列表 + ProductRef(type=…, tags={"layer": …}) 映射。

    支持两种构造：字面量 kwargs（fenkuai）与 for 循环字面量元组驱动（avg_daily 的
    ``for variable, layer in (("SM","SM"),…)`` + f-string type）。
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    main_layers: list[str] = []
    product_layer_tags: dict[str, str] = {}

    for kw_node in ast.walk(tree):
        if not isinstance(kw_node, ast.Call):
            continue
        for kw in kw_node.keywords:
            if kw.arg == "main_layers" and isinstance(kw.value, ast.List):
                main_layers = [
                    elt.value for elt in kw.value.elts if isinstance(elt, ast.Constant)
                ]

    def _record(call: ast.Call, binding: dict[str, str]) -> None:
        type_expr = layer_expr = None
        for kw in call.keywords:
            if kw.arg == "type":
                type_expr = kw.value
            if kw.arg == "tags" and isinstance(kw.value, ast.Dict):
                for key, value in zip(kw.value.keys, kw.value.values):
                    if isinstance(key, ast.Constant) and key.value == "layer":
                        layer_expr = value
        if type_expr is None or layer_expr is None:
            return
        product_type = _resolve_str_expr(type_expr, binding)
        layer_tag = _resolve_str_expr(layer_expr, binding)
        if product_type and layer_tag:
            product_layer_tags[product_type] = layer_tag

    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        pairs: list[tuple[str, ...]] = []
        if isinstance(node.iter, (ast.Tuple, ast.List)):
            for elt in node.iter.elts:
                if (
                    isinstance(elt, ast.Tuple)
                    and elt.elts
                    and all(isinstance(e, ast.Constant) for e in elt.elts)
                ):
                    pairs.append(tuple(str(e.value) for e in elt.elts))
        if not pairs or not (
            isinstance(node.target, ast.Tuple)
            and all(isinstance(t, ast.Name) for t in node.target.elts)
        ):
            continue
        var_names = [t.id for t in node.target.elts]
        for call in _collect_productref_calls(
            ast.Module(body=node.body, type_ignores=[])
        ):
            for pair in pairs:
                _record(call, dict(zip(var_names, pair)))

    for call in _collect_productref_calls(tree):
        _record(call, {})

    assert main_layers, f"main_layers literal not found in {module_path.name}"
    assert (
        product_layer_tags
    ), f"no ProductRef(type=…, tags.layer) found in {module_path.name}"
    return main_layers, product_layer_tags


def test_omega_seeds_extra_outputs_match_expected_tags() -> None:
    """种子 extra.outputs（前端占位成员 tag 来源）必须恰为 {SM, VOD, OMEGA}。"""
    for seed_name, seed in _iter_omega_seeds():
        outputs = (seed.get("extra") or {}).get("outputs")
        assert outputs is not None, f"{seed_name}: extra.outputs missing"
        assert (
            set(outputs) == EXPECTED_TAGS
        ), f"{seed_name}: extra.outputs={sorted(outputs)} != {sorted(EXPECTED_TAGS)}"


def test_omega_module_manifest_main_layers_match_expected_tags() -> None:
    """算法 manifest main_layers 必须与占位 tag 集合一致。"""
    for module_name in ("omega_sf_fenkuai", "omega_avg_daily"):
        module_path = _PROVIDER_ROOT / "modules" / f"{module_name}.py"
        assert module_path.exists(), f"missing module source: {module_path}"
        main_layers, _ = _extract_module_constants(module_path)
        assert (
            set(main_layers) == EXPECTED_TAGS
        ), f"{module_name}: main_layers={main_layers} != {sorted(EXPECTED_TAGS)}"


def test_omega_module_product_tags_cover_main_layers() -> None:
    """算法产物 tags.layer 必须覆盖 main_layers 全部成员（OMEGA_PFT 为额外产物，不在此约束内）。"""
    for module_name in ("omega_sf_fenkuai", "omega_avg_daily"):
        module_path = _PROVIDER_ROOT / "modules" / f"{module_name}.py"
        main_layers, product_layer_tags = _extract_module_constants(module_path)
        covered = set(product_layer_tags.values())
        assert set(main_layers) <= covered, (
            f"{module_name}: main_layers {sorted(main_layers)} not covered by "
            f"product tags {sorted(covered)}"
        )
        for product_type, layer_tag in product_layer_tags.items():
            if layer_tag in EXPECTED_TAGS:
                assert BLOCK_DIR_TYPES.get(product_type) == layer_tag, (
                    f"{module_name}: unexpected type→tag mapping "
                    f"{product_type}→{layer_tag}"
                )


def test_builder_mappable_products_cover_omega_block_dir_types() -> None:
    """builder 侧 _MAPPABLE_PRODUCTS 必须包含全部 ω block_dir 产物类型且 label 对齐。"""
    for product_type, expected_label in BLOCK_DIR_TYPES.items():
        config = _MAPPABLE_PRODUCTS.get(product_type)
        assert (
            config is not None
        ), f"_MAPPABLE_PRODUCTS missing omega product type: {product_type}"
        assert (
            config.get("label") == expected_label
        ), f"{product_type}: label={config.get('label')!r} != {expected_label!r}"


def test_omega_seed_placeholder_tags_align_end_to_end() -> None:
    """端到端静态对齐：种子 extra.outputs ↔ manifest main_layers ↔ builder label。"""
    seed_tags = {
        tag
        for _, seed in _iter_omega_seeds()
        for tag in (seed.get("extra") or {}).get("outputs", [])
    }
    assert seed_tags == EXPECTED_TAGS

    for module_name in ("omega_sf_fenkuai", "omega_avg_daily"):
        module_path = _PROVIDER_ROOT / "modules" / f"{module_name}.py"
        main_layers, _ = _extract_module_constants(module_path)
        assert (
            set(main_layers) == seed_tags
        ), f"{module_name}: main_layers {main_layers} != seed tags {sorted(seed_tags)}"

    builder_labels = {
        _MAPPABLE_PRODUCTS[product_type]["label"]
        for product_type in BLOCK_DIR_TYPES
        if product_type in _MAPPABLE_PRODUCTS
    }
    assert (
        builder_labels == seed_tags
    ), f"builder labels {sorted(builder_labels)} != seed tags {sorted(seed_tags)}"
