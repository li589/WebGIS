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
import re
import sys
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
# 2026-08-24 P2 对齐后清零：forest-ratio/landscape 已统一到 descriptor
# 语义名（渲染经别名表解析为 greens/spectral）。新漂移出现即 CI 红。
KNOWN_PALETTE_MISMATCH: dict[str, tuple[str, str]] = {}

# 预存目录缺口已清零（2026-08-24 补 era5-dwaa/wdaa descriptor：
# ERA5 白天/夜间热浪事件，语义源自 Docs/03-规范协议/数据源与工作流对照说明）。
KNOWN_MISSING_DESCRIPTOR: set[str] = set()


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


class TestPaletteSingleSource:
    """P2-E 色带单源：palettes.json 为前后端唯一真源。"""

    def _palettes_json(self) -> dict:
        return json.loads((_CATALOG_SEEDS / "palettes.json").read_text(encoding="utf-8"))

    def test_palette_definitions_complete(self) -> None:
        data = self._palettes_json()
        palettes = data["palettes"]
        assert len(palettes) >= 24, f"色带条数异常: {len(palettes)}"
        assert "viridis" in palettes and "thermal-orange" in palettes
        exposed = [k for k, v in palettes.items() if v.get("exposed")]
        assert len(exposed) == 9, f"选择器可见条数变化（原 9）: {exposed}"
        for key, entry in palettes.items():
            colors = entry.get("colors") or []
            assert colors and all(
                isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in colors
            ), f"{key}: 色值非法"
            assert entry.get("label"), f"{key}: 缺 label"
            assert entry.get("type") in {"sequential", "diverging", "qualitative"}

    def test_backend_aliases_cover_semantic_ramps(self) -> None:
        """descriptor 语义 ramp 名必须可解析（别名表不能丢映射）。"""
        aliases = self._palettes_json()["backend_aliases"]
        required = [
            "elevation-terrain-ramp",
            "gebco-terrain-ramp",
            "spectral-ramp",
            "igbp",
            "igbp-landcover-ramp",
            "clcd-landcover-ramp",
            "hfp-ramp",
            "forest-ramp",
            "ndvi-ramp",
            "biomass-ramp",
            "soil-moisture-ramp",
            "station-ramp",
            "bright-temp-ramp",
        ]
        missing = [name for name in required if name not in aliases]
        assert not missing, f"backend_aliases 丢失语义 ramp 映射: {missing}"

    def test_frontend_generated_ts_in_sync(self) -> None:
        """前端生成物与真源同步（重跑 Tools/generate_palette_config.py 应零 diff）。"""
        import subprocess
        import tempfile

        result = subprocess.run(
            [
                sys.executable,
                str(_BACKEND.parent.parent / "Tools" / "generate_palette_config.py"),
            ],
            capture_output=True,
            text=True,
            cwd=_BACKEND.parent.parent,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        generated_path = (
            _BACKEND.parent / "frontend" / "src" / "data" / "weather-palettes-generated.ts"
        )
        # 脚本幂等：重跑后已跟踪的生成物无未暂存修改（`??` untracked 为首次
        # 提交前新文件的正常状态，不算失步）。
        git_status = subprocess.run(
            ["git", "status", "--porcelain", str(generated_path)],
            capture_output=True,
            text=True,
            cwd=_BACKEND.parent.parent,
        )
        modified = [
            line
            for line in git_status.stdout.splitlines()
            if line.strip() and not line.startswith("??")
        ]
        assert not modified, (
            f"生成物与 palettes.json 不同步（重跑脚本或禁止手改生成物）: {modified}"
        )


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
