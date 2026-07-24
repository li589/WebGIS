#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 /layers 接口返回新增的 10 个图层。"""

import sys
import urllib.request
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"

NEW_LAYERS = {
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

try:
    with urllib.request.urlopen(f"{BASE}/layers", timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
except Exception as e:
    print(f"[ERROR] /layers failed: {e}")
    sys.exit(1)

items = data.get("items", [])
print(f"/layers returns {len(items)} layers")
print()

layer_ids = set()
for item in items:
    lid = item.get("layer_id", "?")
    layer_ids.add(lid)

# Show new layers
print("New layers in /layers:")
for lid in sorted(NEW_LAYERS):
    item = next((i for i in items if i.get("layer_id") == lid), None)
    if item:
        print(
            f"  [OK] {lid:20s} name='{item.get('display_name', '?')}' "
            f"category='{item.get('category', '?')}' status='{item.get('status', '?')}'"
        )
    else:
        print(f"  [MISSING] {lid}")

missing = NEW_LAYERS - layer_ids
if missing:
    print(f"\n[FAIL] Missing: {sorted(missing)}")
    sys.exit(2)
else:
    print("\n[OK] All 10 new layers present in /layers")

# Also check /overlays
try:
    with urllib.request.urlopen(f"{BASE}/overlays", timeout=10) as resp:
        odata = json.loads(resp.read().decode("utf-8"))
    oids = set(odata.get("overlay_layer_ids", []))
    print(f"/overlays returns {len(oids)} layers")
    om = NEW_LAYERS - oids
    if om:
        print(f"[WARN] Missing from /overlays: {sorted(om)}")
    else:
        print("[OK] All 10 new layers in /overlays too")
except Exception as e:
    print(f"[ERROR] /overlays: {e}")
