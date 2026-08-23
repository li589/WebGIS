"""catalog 三方一致性校验门（P1，2026-08-24）。

真源关系：
- ``catalog_seeds/layer_descriptors.json`` —— 图层目录语义（id/显示名/类别/style.palette）
- ``catalog_seeds/overlay_assets.json`` —— 静态叠加层渲染配置（P1-B 数据化产物）
- ``workflow_seeds/system/*.json`` —— 工作流↔图层对应 + 中文命名配置

校验项（失败即 CI 红）：
1. overlay_assets 的 layer_id 必须有 descriptor（目录可见性）
2. 两处 palette 经 resolve_palette_id 后不得"静默回落 viridis"（未知名=配置错误）
3. descriptor 与 overlay_assets 的 palette 解析结果一致性（已知漂移走
   KNOWN_PALETTE_MISMATCH waiver，消项须显式删豁免并说明）
4. 工作流种子里 layer_id 节点属性引用的图层必须在 descriptor 中存在
5. 61 个系统种子 group_title 覆盖率（P1-C 后应全量中文配置）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.raster_preview_service import resolve_palette_id

_BACKEND = Path(__file__).resolve().parents[2] / "Code" / "backend"
_CATALOG_SEEDS = _BACKEND / "app" / "catalog_seeds"
_SEEDS_DIR = _BACKEND / "workflow_seeds" / "system"


def _load_descriptors() -> dict[str, dict]:
    raw = json.loads((_CATALOG_SEEDS / "layer_descriptors.json").read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("items") or list(raw.values())
    return {it["layer_id"]: it for it in items if isinstance(it, dict) and it.get("layer_id")}


def _load_overlay_assets() -> dict[str, dict]:
    raw = json.loads((_CATALOG_SEEDS / "overlay_assets.json").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _descriptor_palette(layer_id: str, desc: dict) -> str | None:
    style = desc.get("style") or {}
    p = style.get("palette")
    return str(p) if p else None


# 已知 palette 漂移（descriptor 语义名 vs assets 显式显示名）。
# AST 提取真值（2026-08-24）：biomass/cmfd 经别名解析后已一致，真实漂移
# 仅 2 处。消除漂移须先对齐两处配置，再删除豁免（审查报告 P1-A）。
KNOWN_PALETTE_MISMATCH: dict[str, tuple[str, str]] = {
    "forest-ratio": ("greens", "ylgn"),
    "landscape-metrics-9km": ("spectral", "cividis"),
}

# 预存目录缺口：overlay 注册了但无 descriptor（P1 之前即如此；补目录
# 条目涉及前端目录展示，列 TODO 待拍板，非本次数据化范围）。
KNOWN_MISSING_DESCRIPTOR: set[str] = {"era5-dwaa-cn", "era5-wdaa-cn"}


class TestOverlayAssetsConsistency:
    def test_assets_layer_ids_have_descriptors(self) -> None:
        desc = _load_descriptors()
        assets = _load_overlay_assets()
        missing = sorted((set(assets) - set(desc)) - KNOWN_MISSING_DESCRIPTOR)
        assert not missing, (
            f"overlay_assets 有 descriptor 无的层: {missing}"
            f"（预存缺口白名单: {sorted(KNOWN_MISSING_DESCRIPTOR)}）"
        )

    def test_assets_palettes_resolve_without_silent_fallback(self) -> None:
        for layer_id, entry in _load_overlay_assets().items():
            raw = entry.get("palette") or "viridis"
            resolved = resolve_palette_id(raw)
            assert resolved != "viridis" or raw.lower() == "viridis", (
                f"{layer_id}: palette {raw!r} 未知名静默回落 viridis"
            )

    def test_descriptor_palettes_resolve_without_silent_fallback(self) -> None:
        for layer_id, d in _load_descriptors().items():
            raw = _descriptor_palette(layer_id, d)
            if not raw:
                continue
            resolved = resolve_palette_id(raw)
            assert resolved != "viridis" or raw.lower() == "viridis", (
                f"{layer_id}: palette {raw!r} 未知名静默回落 viridis"
            )

    def test_descriptor_asset_palette_alignment(self) -> None:
        desc = _load_descriptors()
        assets = _load_overlay_assets()
        problems: list[str] = []
        for layer_id, entry in assets.items():
            d = desc.get(layer_id)
            if d is None:
                continue
            dp = _descriptor_palette(layer_id, d)
            ap = entry.get("palette")
            if dp is None or ap is None:
                continue
            rd, ra = resolve_palette_id(dp), resolve_palette_id(ap)
            if rd != ra:
                waiver = KNOWN_PALETTE_MISMATCH.get(layer_id)
                if waiver == (rd, ra):
                    continue
                problems.append(f"{layer_id}: descriptor({dp}→{rd}) != assets({ap}→{ra})")
        assert not problems, "palette 双写漂移（新漂移或 waiver 过期）:\n" + "\n".join(problems)

    def test_waivers_still_relevant(self) -> None:
        """waiver 里的漂移若已对齐则豁免过期（须删除）。"""
        desc = _load_descriptors()
        assets = _load_overlay_assets()
        stale: list[str] = []
        for layer_id, (rd, ra) in KNOWN_PALETTE_MISMATCH.items():
            dp = _descriptor_palette(layer_id, desc[layer_id])
            ap = assets.get(layer_id, {}).get("palette")
            if dp is None or ap is None:
                continue
            if (resolve_palette_id(dp), resolve_palette_id(ap)) != (rd, ra):
                stale.append(layer_id)
        assert not stale, f"waiver 已过期（漂移已修复或变化），请删除: {stale}"


class TestWorkflowSeedConsistency:
    def _seed_layer_ids(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for f in sorted(_SEEDS_DIR.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            ids: list[str] = []
            for node in data.get("nodes", []):
                lid = node.get("layer_id")
                if isinstance(lid, str) and lid and lid != "none":
                    ids.append(lid)
            if ids:
                out[f.name] = sorted(set(ids))
        return out

    def test_seed_layer_ids_exist_in_descriptors(self) -> None:
        desc = _load_descriptors()
        problems = []
        for fname, lids in self._seed_layer_ids().items():
            for lid in lids:
                if lid not in desc:
                    problems.append(f"{fname}: layer_id {lid!r} 无 descriptor")
        assert not problems, "种子引用了不存在的图层:\n" + "\n".join(problems)

    def test_all_system_seeds_have_chinese_group_title(self) -> None:
        seeds = sorted(_SEEDS_DIR.glob("*.json"))
        assert len(seeds) >= 60, f"系统种子数异常: {len(seeds)}"
        missing = []
        for f in seeds:
            data = json.loads(f.read_text(encoding="utf-8"))
            title = (data.get("extra") or {}).get("group_title")
            if not (isinstance(title, str) and title.strip()):
                missing.append(f.name)
        assert not missing, f"缺中文组名配置的种子: {missing}"
