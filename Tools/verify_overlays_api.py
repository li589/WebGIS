#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速验证 /api/overlays 与 /api/layers 接口返回新图层。"""

import sys
import urllib.request
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"


def fetch(path: str):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"_error": str(e)}


def main() -> int:
    print("=" * 60)
    print("1. /overlays")
    print("=" * 60)
    overlays = fetch("/overlays")
    if "_error" in overlays:
        print(f"[ERROR] {overlays['_error']}")
        return 1
    # /overlays returns {"overlay_layer_ids": [...]}
    overlay_ids_list = []
    if isinstance(overlays, dict):
        overlay_ids_list = overlays.get("overlay_layer_ids", [])
        print(f"Total overlays: {len(overlay_ids_list)}")
        for lid in overlay_ids_list:
            print(f"  - {lid}")
    elif isinstance(overlays, list):
        overlay_ids_list = [
            item.get("layer_id") if isinstance(item, dict) else item
            for item in overlays
        ]
        print(f"Total overlays: {len(overlay_ids_list)}")
        for lid in overlay_ids_list:
            print(f"  - {lid}")
    else:
        print(json.dumps(overlays, indent=2, ensure_ascii=False)[:1500])

    print()
    print("=" * 60)
    print("2. /layers (frontend catalog endpoint)")
    print("=" * 60)
    layers = fetch("/layers")
    if "_error" in layers:
        print(f"[ERROR] {layers['_error']}")
        return 1
    if isinstance(layers, list):
        print(f"Total layers: {len(layers)}")
        ids = []
        for item in layers:
            if isinstance(item, dict):
                ids.append(
                    item.get("id")
                    or item.get("layer_id")
                    or item.get("catalogId")
                    or "?"
                )
        print("Layer IDs:")
        for i in ids:
            print(f"  - {i}")
    else:
        print(json.dumps(layers, indent=2, ensure_ascii=False)[:1500])

    # 验证新增的 10 个 layer_id 是否都出现在 /overlays 中
    expected = {
        "gebco-dem-cn",
        "cmfd-precip-cn",
        "clcd-cn",
        "biomass-cn",
        "era5-dwaa-cn",
        "era5-wdaa-cn",
        "co2-cn",
        "soil-ddca",
        "omega-fy-output",
        "forest-ratio",
    }
    print()
    print("=" * 60)
    print("3. New layer registration check")
    print("=" * 60)
    overlay_ids = set(overlay_ids_list)

    missing = expected - overlay_ids
    if missing:
        print(f"[FAIL] Missing layer_ids: {sorted(missing)}")
        return 2
    else:
        print("[OK] All 10 new layer_ids registered in /overlays")
        # 也确认一下 bounds 可访问
        for layer_id in sorted(expected):
            b = fetch(f"/overlay-bounds/{layer_id}")
            if "_error" in b:
                print(f"  [FAIL] {layer_id}: bounds error -> {b['_error']}")
            else:
                bb = b.get("bounds", [])
                print(f"  [OK] {layer_id:20s} bounds={bb}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
