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


# ── 生成物格式 ────────────────────────────────────────────────────────────────
# 生成物是 checked-in 的 prettier 产物，仓库 pre-commit 会对它跑 prettier。若生成器
# 的输出与 prettier 重排结果不一致，「重跑生成器应零 diff」的同步测试在任何缺少
# prettier 的环境（如 CI 后端 pytest job，无 Node）必失败。因此生成器**自身**复刻
# 所需格式化，不再 shell out 到 `npx prettier`（npx 版本不受 package-lock 约束，
# 且后端 CI job 无 Node——这是长跑红的根因）。
# 规则来源：Code/frontend/.prettierrc.json（printWidth=100 / singleQuote / trailingComma=all）。
# 若前端 prettier 配置变更导致格式漂移，pre-commit 的 prettier 钩子会立即报错，
# 到时同步更新此处即可（不静默）。
_PRINT_WIDTH = 100
_INDENT = "  "


# 除反斜杠/引号外必须转义的字符：C0 控制字符（含 \n \r \t）与 JS 行分隔符。
# 此前只转义反斜杠与引号，控制字符会以裸字符写进生成的 TS 字面量 → 语法错误
# （或换行被当成字符串终止）。当前色带名/色值均为中文与 #RRGGBB，尚无实际触发，
# 属潜伏缺陷；补齐后与 json.dumps 的转义面等价。
_JS_CONTROL_ESCAPES = {
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\v": "\\v",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}


def _js_escape(value: str, quote: str) -> str:
    """转义反斜杠、指定引号，以及所有 C0 控制字符 / JS 行分隔符。"""
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == quote:
            out.append("\\" + quote)
        else:
            esc = _JS_CONTROL_ESCAPES.get(ch)
            if esc is not None:
                out.append(esc)
            elif ord(ch) < 0x20:
                out.append("\\u%04x" % ord(ch))
            else:
                out.append(ch)
    return "".join(out)


def _js_string(value: str) -> str:
    """按 prettier singleQuote 语义输出字符串字面量。

    优先单引号；当内容含单引号且不含双引号时改用双引号（与 prettier 一致）。
    """
    if "'" in value and '"' not in value:
        return '"%s"' % _js_escape(value, '"')
    return "'%s'" % _js_escape(value, "'")


def _js_key(key: str) -> str:
    """对象键：合法标识符不加引号，否则用字符串字面量（prettier 行为）。"""
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", key):
        return key
    return _js_string(key)


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
        colors = ", ".join(_js_string(c) for c in p["colors"])
        lines.append(f"{_INDENT}{_js_key(key)}: {{")
        inline = f"{_INDENT * 2}colors: [{colors}],"
        if len(inline) <= _PRINT_WIDTH:
            lines.append(inline)
        else:
            # 单行超 printWidth：每个元素独占一行（prettier 对超宽数组的处理）
            lines.append(f"{_INDENT * 2}colors: [")
            for c in p["colors"]:
                lines.append(f"{_INDENT * 3}{_js_string(c)},")
            lines.append(f"{_INDENT * 2}],")
        lines.append(f"{_INDENT * 2}lineColor: {_js_string(p['lineColor'])},")
        lines.append(f"{_INDENT * 2}label: {_js_string(p['label'])},")
        lines.append(f"{_INDENT * 2}type: {_js_string(p['type'])},")
        lines.append(f"{_INDENT * 2}exposed: {'true' if p.get('exposed') else 'false'},")
        lines.append(f"{_INDENT}}},")
    lines.append("}")
    lines.append("")
    # 双端别名合并：后端别名（语义 ramp/matplotlib 经典名 → 实现键）为基底，
    # 前端目录历史别名优先覆盖——P3-D（2026-08-24）：此前 backend_aliases
    # 不下发前端，descriptor 语义名（hfp-ramp 等）在前端被误兜底
    # thermal-orange；合并后前端渲染与后端 resolve 结果一致。
    merged_aliases: dict[str, str] = {}
    merged_aliases.update(data.get("backend_aliases", {}))
    merged_aliases.update(data.get("frontend_aliases", {}))
    lines.append("export const GENERATED_PALETTE_ALIASES: Record<string, string> = {")
    for key in merged_aliases:
        lines.append(f"{_INDENT}{_js_key(key)}: {_js_string(merged_aliases[key])},")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-code", action="store_true", help="从两端代码重建 palettes.json（一次性迁移用）")
    args = parser.parse_args()

    if args.from_code:
        data = build_from_code()
        # 同上：显式 LF，避免 Windows 下 write_text 产生 CRLF 污染真源 JSON。
        JSON_PATH.write_bytes(
            (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        )
        print(f"palettes.json 重建完成: {len(data['palettes'])} 条色带")
    else:
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    GENERATED_TS.parent.mkdir(parents=True, exist_ok=True)
    # 输出已按 prettier 配置预先格式化（见 _js_string/_js_key/_PRINT_WIDTH），
    # 因此无需再调用 npx prettier —— 生成结果与运行环境无关，跨平台/CI 一致。
    # 必须写 LF 字节：Windows 上 write_text 会把 \n 转成 CRLF，与 .prettierrc
    # 的 endOfLine=lf、.gitattributes 的 eol=lf 冲突（此前由 prettier --write 兜底）。
    GENERATED_TS.write_bytes(generate_ts(data).encode("utf-8"))
    exposed = sum(1 for p in data["palettes"].values() if p.get("exposed"))
    print(f"weather-palettes-generated.ts 生成完成（exposed {exposed}/{len(data['palettes'])}）")


if __name__ == "__main__":
    main()
