"""一次性活体探针：确认 CDS / CDSE 公共检索端点契约（P1 实施前）。

用法（仓库根）::

    Env/Python312/python.exe Test/tools/probe_portal_search_endpoints.py

结论回填 portal_catalog.py 实现注释与计划文档；用后可删。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

UA = {"User-Agent": "CGDA-Backend/1.0"}


def fetch_json(url: str, timeout: float = 30.0) -> dict | list:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def probe_cdse_odata() -> None:
    base = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
    filt = "contains(Name,'S1A_IW_GRDH_1SDV')"
    query = urllib.parse.urlencode({"$filter": filt, "$top": 2})
    url = f"{base}?{query}"
    print("=== CDSE OData ===")
    print("URL:", url)
    d = fetch_json(url)
    items = d.get("value") if isinstance(d, dict) else None
    print("count:", len(items or []))
    if items:
        keys = [
            "Id",
            "Name",
            "ContentLength",
            "Online",
            "SensingStartDate",
            "SensingEndDate",
            "OriginDate",
        ]
        print(json.dumps({k: items[0].get(k) for k in keys}, indent=1, default=str))


def probe_cds_catalogue() -> None:
    candidates = [
        "https://cds.climate.copernicus.eu/api/catalogue/v1/collections?"
        "q=ERA5&limit=2",
        "https://cds.climate.copernicus.eu/api/catalogue/v1/collections"
        "/reanalysis-era5-single-levels",
    ]
    print("=== CDS catalogue ===")
    for url in candidates:
        print("URL:", url)
        try:
            d = fetch_json(url, timeout=30.0)
            text = json.dumps(d, ensure_ascii=False)[:800]
            print("OK:", text)
        except Exception as exc:  # noqa: BLE001 - 探针容错
            print("FAIL:", type(exc).__name__, exc)
        print("-" * 60)


if __name__ == "__main__":
    probe_cdse_odata()
    print()
    probe_cds_catalogue()
