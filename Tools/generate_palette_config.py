#!/usr/bin/env python
"""色带单源生成器（P2-E，2026-08-24）。

背景：后端 ``_PALETTES``(24) 与前端 ``WEATHER_PALETTES``(9) 双维护、集合
不等、别名两套——「同层换源变色」类故障的结构性根因（实测前端 9 条与
后端同名条目色值 100% 一致，合并零视觉风险）。

用法：
  # 一次性：从两端代码现状提取生成 palettes.json（此后 JSON 为唯一真源）
  python Tools/generate_palette_config.py --from-code

  # 常规：从 palettes.json 重新生成前端 weather-palettes-generated.ts
  python Tools/generate_palette_config.py

真源流向：catalog_seeds/palettes.json → 前端 src/data/weather-palettes-generated.ts
（checked-in 生成物；改色带只改 JSON 再跑本脚本，禁止手改 generated.ts）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "Code" / "backend"
JSON_PATH = BACKEND / "app" / "catalog_seeds" / "palettes.json"
GENERATED_TS = ROOT / "Code" / "frontend" / "src" / "data" / "weather-palettes-generated.ts"

DEFAULT_LINE_COLOR = "rgba(255,255,255,0.08)"


def _extract_backend() -> tuple[dict[str, list[str]], dict[str, str]]:
    sys.path.insert(0, str(BACKEND))
    from app.services.raster_preview_service import _PALETTES, _PALETTE_ALIASES

    colors = {
        key: ["#%02x%02x%02x" % tuple(rgb) for rgb in stops]
        for key, stops in _PALETTES.items()
    }
    return colors, dict(_PALETTE_ALIASES)


def _extract_frontend() -> tuple[dict[str, dict], dict[str, str]]:
    src = (ROOT / "Code" / "frontend" / "src" / "components" / "map" / "weather-render.ts").read_text(
        encoding="utf-8"
    )
    palettes: dict[str, dict] = {}
    block_re = re.compile(
        r"'([a-z0-9_-]+)':\s*\{\s*colors:\s*\[([^\]]*)\]\s*,\s*"
        r"lineColor:\s*'([^']*)'\s*,\s*label:\s*'([^']*)'\s*,\s*"
        r"type:\s*'(sequential|diverging|qualitative)'",
        re.S,
    )
    for m in block_re.finditer(src):
        key = m.group(1)
        colors = re.findall(r"'(#[0-9a-fA-F]{6,8})'", m.group(2))
        palettes[key] = {
            "colors": colors,
            "lineColor": m.group(3),
            "label": m.group(4),
            "type": m.group(5),
        }
    alias_m = re.search(r"const PALETTE_ALIASES: Record<string, string> = \{(.*?)\n\}", src, re.S)
    aliases: dict[str, str] = {}
    if alias_m:
        for am in re.finditer(r"'([^']+)':\s*'([^']+)'", alias_m.group(1)):
            aliases[am.group(1)] = am.group(2)
    return palettes, aliases


def build_from_code() -> dict:
    be_colors, be_aliases = _extract_backend()
    fe_meta, fe_aliases = _extract_frontend()
    if not be_colors or len(fe_meta) < 9:
        raise SystemExit("提取失败：后端/前端色带解析异常")

    merged: dict[str, dict] = {}
    # 前端 9 条：元数据齐全，exposed（选择器可见）
    for key, meta in fe_meta.items():
        if key not in be_colors:
            raise SystemExit(f"前端色带 {key} 在后端缺失（色值集合应含前端超集）")
        merged[key] = {
            **meta,
            "colors": be_colors[key],  # 色值以后端渲染真源为准（实测一致）
            "exposed": True,
        }
    # 后端独有条目：无前端元数据，exposed=false（不进选择器，避免 UI 突变）
    for key, colors in be_colors.items():
        if key in merged:
            continue
        merged[key] = {
            "colors": colors,
            "lineColor": DEFAULT_LINE_COLOR,
            "label": key,
            "type": "sequential",
            "exposed": False,
        }

    return {
        "palettes": merged,
        "backend_aliases": be_aliases,
        "frontend_aliases": fe_aliases,
    }


def generate_ts(data: dict) -> str:
    lines = [
        "/** 色带单源生成物（Tools/generate_palette_config.py）——禁止手改。",
        " * 真源：Code/backend/app/catalog_seeds/palettes.json（P2-E 单源生成，2026-08-24）。",
        " * 后端 _PALETTES 同样从该 JSON 加载（raster_preview_service），",
        " * 前后端渲染色值/别名由同一份数据驱动，消除双维护漂移。",
        " */",
        "",
        "export interface GeneratedPaletteDefinition {",
        "  colors: string[]",
        "  lineColor: string",
        "  /** UI 显示名 */",
        "  label: string",
        "  /** 配色类型 */",
        "  type: 'sequential' | 'diverging' | 'qualitative'",
        "  /** 是否进色带选择器（后端独有条目为 false） */",
        "  exposed: boolean",
        "}",
        "",
        "export const GENERATED_WEATHER_PALETTES: Record<string, GeneratedPaletteDefinition> = {",
    ]
    # 保持 JSON 原序（前端条目在前）——色带选择器顺序不变
    for key in data["palettes"]:
        p = data["palettes"][key]
        colors = ", ".join(f"'{c}'" for c in p["colors"])
        lines.append(f"  '{key}': {{")
        lines.append(f"    colors: [{colors}],")
        lines.append(f"    lineColor: '{p['lineColor']}',")
        lines.append(f"    label: {json.dumps(p['label'], ensure_ascii=False)},")
        lines.append(f"    type: '{p['type']}',")
        lines.append(f"    exposed: {'true' if p.get('exposed') else 'false'},")
        lines.append("  },")
    lines.append("}")
    lines.append("")
    lines.append("export const GENERATED_PALETTE_ALIASES: Record<string, string> = {")
    for key in sorted(data["frontend_aliases"]):
        lines.append(f"  '{key}': '{data['frontend_aliases'][key]}',")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-code", action="store_true", help="从两端代码重建 palettes.json（一次性迁移用）")
    args = parser.parse_args()

    if args.from_code:
        data = build_from_code()
        JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"palettes.json 重建完成: {len(data['palettes'])} 条色带")
    else:
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    GENERATED_TS.parent.mkdir(parents=True, exist_ok=True)
    GENERATED_TS.write_text(generate_ts(data), encoding="utf-8")
    exposed = sum(1 for p in data["palettes"].values() if p.get("exposed"))
    print(f"weather-palettes-generated.ts 生成完成（exposed {exposed}/{len(data['palettes'])}）")


if __name__ == "__main__":
    main()
