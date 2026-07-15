#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 10 个新图层的 bounds 与 preview 可访问性。"""
import sys
import urllib.request
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"

NEW_LAYERS = [
    "gebco-dem-cn", "cmfd-precip-cn", "clcd-cn", "biomass-cn",
    "era5-dwaa-cn", "era5-wdaa-cn", "co2-cn", "soil-ddca",
    "omega-fy-output", "forest-ratio",
]


def fetch(path: str, timeout: int = 15):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as resp:
            ct = resp.headers.get("Content-Type", "")
            raw = resp.read()
            return resp.status, ct, raw
    except Exception as e:
        return None, str(e), b""


print("=" * 60)
print("Verify bounds + preview for 10 new layers")
print("=" * 60)

ok_count = 0
for layer_id in NEW_LAYERS:
    # bounds
    status, ct, raw = fetch(f"/overlay-bounds/{layer_id}")
    if status != 200:
        print(f"  [FAIL] {layer_id:20s} bounds status={status} err={ct}")
        continue
    try:
        bdata = json.loads(raw.decode("utf-8"))
        bounds = bdata.get("bounds", [])
        meta = bdata.get("meta", {})
        palette = meta.get("palette", "?")
        unit = meta.get("unit", "")
        vmin = meta.get("vmin")
        vmax = meta.get("vmax")
    except Exception as e:
        print(f"  [FAIL] {layer_id:20s} bounds JSON parse: {e}")
        continue

    # preview
    pstatus, pct, praw = fetch(f"/overlay-preview/{layer_id}", timeout=30)
    if pstatus != 200 or not praw:
        print(f"  [FAIL] {layer_id:20s} preview status={pstatus} ct={pct} size={len(praw)}")
        continue
    png_size_kb = len(praw) / 1024

    print(f"  [OK]   {layer_id:20s} bounds={bounds} palette={palette} "
          f"vmin={vmin} vmax={vmax} unit='{unit}' png={png_size_kb:.1f}KB")
    ok_count += 1

print()
print("=" * 60)
print(f"Result: {ok_count}/{len(NEW_LAYERS)} layers fully accessible")
print("=" * 60)

# Also verify /overlays count
status, ct, raw = fetch("/overlays")
if status == 200:
    odata = json.loads(raw.decode("utf-8"))
    ids = odata.get("overlay_layer_ids", [])
    print(f"/overlays returns {len(ids)} layers")
else:
    print(f"[ERROR] /overlays status={status}")
