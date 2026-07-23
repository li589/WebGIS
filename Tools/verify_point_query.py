#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 /overlay-value 点查询对若干新图层可用（Python 组件验证）。"""

import sys
import urllib.request
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"

# (layer_id, lng, lat, expected_unit)
TESTS = [
    ("gebco-dem-cn", 116.0, 40.0, "m"),  # 北京附近高程
    ("cmfd-precip-cn", 116.0, 40.0, "mm"),  # 北京降水
    ("clcd-cn", 116.0, 40.0, "class"),  # 北京土地覆盖
    ("biomass-cn", 110.0, 25.0, "Mg/ha"),  # 华南生物量
    ("era5-dwaa-cn", 116.0, 40.0, "events"),  # 北京热浪
    ("co2-cn", 116.0, 40.0, "ppm"),  # 北京 CO2
    ("soil-ddca", 116.0, 40.0, ""),  # 土壤
    ("omega-fy-output", 116.0, 40.0, "Omega"),
    ("forest-ratio", 116.0, 40.0, "ratio"),
]


def fetch(path: str, timeout: int = 60):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as resp:
            return resp.status, resp.read()
    except Exception as e:
        return None, str(e).encode("utf-8")


print("=" * 60)
print("Verify /overlay-value point query (Python import components)")
print("=" * 60)

ok = 0
for layer_id, lng, lat, expected_unit in TESTS:
    url = f"/overlay-value/{layer_id}?lng={lng}&lat={lat}"
    status, raw = fetch(url, timeout=120)
    if status != 200:
        print(f"  [FAIL] {layer_id:20s} status={status} err={raw[:200]}")
        continue
    try:
        data = json.loads(raw.decode("utf-8"))
        value = data.get("value")
        unit = data.get("unit", "")
        has_error = "error" in data
        if has_error:
            print(
                f"  [WARN] {layer_id:20s} value={value} unit='{unit}' error={data.get('error', '')[:80]}"
            )
        else:
            print(f"  [OK]   {layer_id:20s} value={value} unit='{unit}' @({lng},{lat})")
            ok += 1
    except Exception as e:
        print(f"  [FAIL] {layer_id:20s} JSON parse: {e}")

print()
print(f"Result: {ok}/{len(TESTS)} point queries returned without error")
