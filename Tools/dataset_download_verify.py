#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""六源数据集在线下载最小验证（#58 端到端）。

逐源执行「凭据获取 → 最小检索 → 单文件下载 → 非空校验」，输出 JSON 报告。
每源独立 try/except 互不阻断；退出码：全过 0，有失败 1。

源清单（NSMC 预留占位，需人工预热会话后补验）：
  - nomads  无需凭据，最新 GFS 单变量小子集 GRIB
  - cmr     检索匿名，SPL3SMP_E 单日单 granule（复刻 data_access_nodes 查询）
  - gldas   Earthdata 凭据，单日 max_files=1
  - smap    Earthdata 凭据，单日 max_files=1
  - cds     BACKEND_CDS_API_KEY / 门户凭据，ERA5 单日极小区域
  - cdse    esa_copernicus 凭据，token 交换 + OData 检索 + 单产品下载

用法：
  Env\\Python312\\python.exe Tools/dataset_download_verify.py --all
  Env\\Python312\\python.exe Tools/dataset_download_verify.py --sources nomads,cmr
报告：Tools/reports/dataset_download_verify_<date>.json（gitignore 区）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "Tools" / "reports"
TMP_BASE = REPORTS_DIR / "dataset_verify_tmp"

# 导入路径（参考 Tools/nsmc_online_probe.py 模式）
sys.path.insert(0, str(REPO_ROOT / "Code" / "algorithms" / "providers" / "Python"))
sys.path.insert(0, str(REPO_ROOT / "Code" / "backend"))

# 本机网络存在自签证书链（data.rda.ucar.edu 等），与 nsmc_online_probe 的
# verify=False 同款处理：验证脚本全局禁用 TLS 证书校验（数据完整性靠
# 下载文件非空 + 后续算法校验兜底）。
import ssl  # noqa: E402

ssl._create_default_https_context = ssl._create_unverified_context
try:
    import requests  # noqa: E402
    import urllib3  # noqa: E402

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    _orig_session_request = requests.Session.request

    def _session_request_no_verify(self, *args, **kwargs):  # noqa: ANN001, ANN202
        kwargs.setdefault("verify", False)
        return _orig_session_request(self, *args, **kwargs)

    requests.Session.request = _session_request_no_verify
except ImportError:
    pass


def log(msg: str) -> None:
    print(f"[verify] {msg}", flush=True)


@dataclass
class SourceResult:
    source: str
    credential: str = "none"  # ok / missing / none(无需)
    search: str = "skip"  # ok / fail / skip
    download: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "credential": self.credential,
            "search": self.search,
            "download": self.download,
            "error": self.error,
        }


def _yesterday() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _classify_error(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if any(k in msg for k in ("credential", "password", "401", "403", "unauthorized", "forbidden", "账号", "凭据")):
        return "credential"
    if any(k in msg for k in ("search", "no granule", "not found", "404", "empty", "no product")):
        return "search"
    if any(k in name for k in ("timeout", "connection")) or any(
        k in msg for k in ("timed out", "connection", "ssl", "dns", "refused")
    ):
        return "network"
    return "unknown"


def _get_runtime_credentials() -> dict[str, Any]:
    """经后端 config_service 读解密门户凭据（密钥值不落日志）。"""
    os.chdir(str(REPO_ROOT / "Code" / "backend"))  # settings 依赖 cwd
    from app.services.config_service import get_portal_credentials_runtime

    return get_portal_credentials_runtime()


def _earthdata_creds(creds: dict[str, Any]) -> tuple[str, str] | None:
    entry = creds.get("earthdata") or {}
    # 门户凭据为扁平字段（username/password），部分账号型门户才是 accounts 数组
    user = str(entry.get("username") or "")
    pwd = str(entry.get("password") or "")
    if user and pwd:
        return user, pwd
    accounts = entry.get("accounts") or []
    if accounts:
        acc = accounts[0]
        return str(acc.get("username", "")), str(acc.get("password", ""))
    # 回退 env（与 nsidc_download.load_credentials 同款）
    user = os.getenv("BACKEND_EARTHDATA_USERNAME", "")
    pwd = os.getenv("BACKEND_EARTHDATA_PASSWORD", "")
    if user and pwd:
        return user, pwd
    return None


def _verify_download_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"downloaded file missing: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"downloaded file empty: {path}")
    return {"path": str(path), "bytes": size}


# ── 各源验证器 ────────────────────────────────────────────────────────────────


def verify_nomads(result: SourceResult) -> None:
    from ingest.nomads_download import download_nomads_grib

    target = TMP_BASE / "nomads"
    target.mkdir(parents=True, exist_ok=True)
    # AWS Open Data 源对最新 cycle 有数小时延迟（latest 会回退到 RDA 无 index
    # 源）；GFS 为 6 小时 cycle，对齐到 ≥18 小时前的整点 cycle 保证 AWS 可用
    now = datetime.now(timezone.utc)
    cycle = now.replace(hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0)
    while (now - cycle) < timedelta(hours=18):
        cycle -= timedelta(hours=6)
    date = cycle.strftime("%Y-%m-%d %H:%M")
    t0 = time.monotonic()
    res = download_nomads_grib(
        date,
        "gfs",
        product="pgrb2.0p25",
        fxx=0,
        search_string=":TMP:2 m above ground:",
        target_dir=str(target),
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    if res.failed or res.errors:
        raise RuntimeError(f"nomads failed={res.failed} errors={res.errors[:2]}")
    if not res.downloaded and not res.skipped:
        raise RuntimeError(f"nomads downloaded={res.downloaded} skipped={res.skipped}")
    files = [Path(f.path) if hasattr(f, "path") else Path(f) for f in (res.files or [])]
    real = [p for p in files if p.exists()] or sorted(target.glob("*.grb2")) or sorted(target.iterdir())
    if not real:
        raise RuntimeError("nomads: no files landed in target_dir")
    info = _verify_download_file(real[0])
    result.search = "ok"
    result.download = {**info, "duration_ms": duration_ms, "files": res.downloaded}


def verify_cmr(result: SourceResult) -> None:
    """CMR 检索级验证（匿名）：自昨日起回退最多 8 天找有 granule 的日期。"""
    import urllib.parse
    import urllib.request

    last_err: Exception | None = None
    for back in range(1, 9):
        day = (
            datetime.now(timezone.utc) - timedelta(days=back)
        ).strftime("%Y-%m-%d")
        temporal = f"{day}T00:00:00Z,{day}T23:59:59Z"
        params = urllib.parse.urlencode(
            {"short_name": "SPL3SMP_E", "page_size": 1, "temporal": temporal}
        )
        url = f"https://cmr.earthdata.nasa.gov/search/granules.json?{params}"
        t0 = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": "cgda-verify/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — 固定 https 端点
            body = json.loads(resp.read().decode("utf-8"))
        duration_ms = int((time.monotonic() - t0) * 1000)
        entries = body.get("feed", {}).get("entry", [])
        if entries:
            result.search = "ok"
            result.download = {
                "path": url,
                "bytes": 0,
                "duration_ms": duration_ms,
                "note": f"search-level verify: date={day}, {len(entries)} granule, id={entries[0].get('id', '')[:24]}",
            }
            return
        last_err = RuntimeError(f"cmr: no granules for {day} (SPL3SMP_E)")
    raise last_err or RuntimeError("cmr: no granules in last 8 days")


def _find_gldas_day(username: str, password: str, target: Path) -> tuple[str, Any]:
    """自昨日起回退最多 8 天找有 granule 的日期（数据发布滞后）。"""
    from ingest.gldas_download import download_gldas_range

    # GLDAS_NOAH025_3H 上游发布滞后可达数月（2026-08 实测最新为 2026-05-31），
    # 先经 CMR 查最新可用 granule 日期，再对该日期做最小下载
    latest_day = _cmr_latest_granule_day("GLDAS_NOAH025_3H")
    if latest_day is None:
        raise RuntimeError("gldas: CMR reports no granules at all for GLDAS_NOAH025_3H")
    res = download_gldas_range(
        start_date=latest_day,
        end_date=latest_day,
        local_dir=str(target),
        username=username,
        password=password,
        max_files=1,
    )
    if res.failed or res.errors:
        raise RuntimeError(f"gldas failed={res.failed} errors={res.errors[:2]}")
    if not res.downloaded and not res.skipped:
        raise RuntimeError(f"gldas: no granules for latest day {latest_day}")
    return latest_day, res


def _cmr_latest_granule_day(short_name: str) -> str | None:
    """经 CMR 查数据集最新 granule 的日期（YYYY-MM-DD）；无结果返回 None。"""
    import urllib.parse
    import urllib.request

    params = urllib.parse.urlencode(
        {"short_name": short_name, "page_size": 1, "sort_key": "-start_date"}
    )
    url = f"https://cmr.earthdata.nasa.gov/search/granules.json?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "cgda-verify/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — 固定 https 端点
        body = json.loads(resp.read().decode("utf-8"))
    entries = body.get("feed", {}).get("entry", [])
    if not entries:
        return None
    time_start = str(entries[0].get("time_start", ""))
    return time_start[:10] if len(time_start) >= 10 else None


def verify_gldas(result: SourceResult, creds: dict[str, Any]) -> None:
    pair = _earthdata_creds(creds)
    if pair is None:
        result.credential = "missing"
        raise RuntimeError("earthdata credentials missing (portal store + env)")
    result.credential = "ok"
    username, password = pair
    target = TMP_BASE / "gldas"
    target.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    day, res = _find_gldas_day(username, password, target)
    duration_ms = int((time.monotonic() - t0) * 1000)
    local = Path(res.local_dir or target)
    files = sorted(p for p in local.rglob("*") if p.is_file())
    if not files:
        raise RuntimeError("gldas: no files landed")
    info = _verify_download_file(files[-1])
    result.search = "ok"
    result.download = {**info, "duration_ms": duration_ms, "files": res.downloaded, "note": f"date={day}"}


def _find_smap_day(username: str, password: str, target: Path) -> tuple[str, Any]:
    """自昨日起回退最多 8 天找有 granule 的日期（SMAP L3 滞后数天）。"""
    from ingest.nsidc_download import download_smap_range

    last: Exception | None = None
    for back in range(1, 9):
        day = (datetime.now(timezone.utc) - timedelta(days=back)).strftime("%Y-%m-%d")
        res = download_smap_range(
            day,
            day,
            str(target),
            username=username,
            password=password,
            max_files=1,
        )
        if res.failed or res.errors:
            raise RuntimeError(f"smap failed={res.failed} errors={res.errors[:2]}")
        if res.downloaded or res.skipped:
            return day, res
        last = RuntimeError(f"smap: no granules for {day}")
    raise last or RuntimeError("smap: no granules in last 8 days")


def verify_smap(result: SourceResult, creds: dict[str, Any]) -> None:
    pair = _earthdata_creds(creds)
    if pair is None:
        result.credential = "missing"
        raise RuntimeError("earthdata credentials missing (portal store + env)")
    result.credential = "ok"
    username, password = pair
    target = TMP_BASE / "smap"
    target.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    day, res = _find_smap_day(username, password, target)
    duration_ms = int((time.monotonic() - t0) * 1000)
    local = Path(res.local_dir or target)
    files = sorted(p for p in local.rglob("*") if p.is_file())
    if not files:
        raise RuntimeError("smap: no files landed")
    info = _verify_download_file(files[-1])
    result.search = "ok"
    result.download = {**info, "duration_ms": duration_ms, "files": res.downloaded, "note": f"date={day}"}


def verify_cds(result: SourceResult, creds: dict[str, Any]) -> None:
    from ingest.cds_download import download_via_cdsapi

    api_key = os.getenv("BACKEND_CDS_API_KEY", "")
    if not api_key:
        entry = creds.get("ecmwf_cds") or creds.get("cds") or {}
        # 门户凭据为扁平 token 字段
        api_key = str(entry.get("token") or entry.get("password") or "")
        if not api_key:
            accounts = entry.get("accounts") or []
            if accounts:
                api_key = str(accounts[0].get("token") or accounts[0].get("password") or "")
    if not api_key:
        result.credential = "missing"
        raise RuntimeError("CDS api key missing (BACKEND_CDS_API_KEY env + portal store)")
    result.credential = "ok"
    target = TMP_BASE / "cds"
    target.mkdir(parents=True, exist_ok=True)
    # ERA5 发布滞后约 5-7 天：自 7 天前起逐日回退，首个可用日期成功即返回
    last_err: Exception | None = None
    for back in range(7, 21):
        day = (datetime.now(timezone.utc) - timedelta(days=back)).strftime("%Y-%m-%d")
        out = target / f"era5_{day.replace('-', '')}_tiny.nc"
        request = {
            "product_type": ["reanalysis"],
            "variable": ["2m_temperature"],
            "year": day[:4],
            "month": [day[5:7]],
            "day": [day[8:10]],
            "time": ["00:00"],
            "area": [23.5, 113.5, 22.5, 114.5],  # 极小区域（珠三角 1°×1°）
            "data_format": "netcdf",
            "download_format": "unarchived",
        }
        t0 = time.monotonic()
        try:
            n = download_via_cdsapi(
                "reanalysis-era5-single-levels",
                request,
                out,
                api_key=api_key,
            )
        except Exception as exc:  # noqa: BLE001 — 数据未发布（400）逐日回退
            last_err = exc
            log(f"[cds] {day} unavailable ({str(exc)[:80]}), retrying earlier date")
            continue
        duration_ms = int((time.monotonic() - t0) * 1000)
        info = _verify_download_file(out)
        result.search = "ok"
        result.download = {**info, "duration_ms": duration_ms, "note": f"cdsapi bytes={n}, date={day}"}
        return
    raise last_err or RuntimeError("cds: no available date in last 7-20 days")


def verify_cdse(result: SourceResult, creds: dict[str, Any]) -> None:
    from ingest.cdse_download import (
        download_product_value,
        exchange_cdse_token,
        search_by_odata_filter,
    )

    entry = creds.get("esa_copernicus") or creds.get("copernicus") or {}
    # 门户凭据为扁平字段；accounts 数组为兼容回退
    username = str(entry.get("username") or "")
    password = str(entry.get("password") or "")
    if not (username and password):
        accounts = entry.get("accounts") or []
        if accounts:
            acc = accounts[0]
            username = str(acc.get("username", ""))
            password = str(acc.get("password", ""))
    if not (username and password):
        result.credential = "missing"
        raise RuntimeError("esa_copernicus credentials missing in portal store")
    result.credential = "ok"

    token = exchange_cdse_token(username, password)
    result.search = "pending"
    # 最近 3 天的 S2MSI2A 小产品（cloudcover 限 20 以下，取最小 1 个）
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    odata_filter = (
        "Collection/Name eq 'SENTINEL-2' "
        "and ContentDate/Start gt " + recent + " "
        "and Attributes/OData.CSC.StringAttribute/any("
        "att:att/Name eq 'productType' and att/OData.CSC.StringAttributeValue/Value eq 'S2MSI2A') "
        "and Online eq true"
    )
    products = search_by_odata_filter(odata_filter, page_size=5)
    if not products:
        raise RuntimeError("cdse: no products matched filter")
    # 取最小的产品（最小下载量）
    products.sort(key=lambda p: (p.size_bytes or 10**12))
    product = products[0]
    result.search = "ok"
    target = TMP_BASE / "cdse"
    target.mkdir(parents=True, exist_ok=True)
    out = target / (product.name or f"{product.product_id}.zip")
    t0 = time.monotonic()
    n = download_product_value(product, out, bearer_token=token)
    duration_ms = int((time.monotonic() - t0) * 1000)
    info = _verify_download_file(out)
    result.download = {**info, "duration_ms": duration_ms, "note": f"product={product.name[:48]} bytes={n}"}


def verify_nsmc_placeholder(result: SourceResult) -> None:
    """NSMC 预留：会话未预热时报告 skipped（人工跑 nsmc_online_probe.py 后补验）。"""
    cache = Path(os.getenv("BACKEND_DATA_ROOT", "I:/Geograph_DataSet")) / "_runtime/cache/nsmc_session.json"
    if not cache.exists():
        result.error = {"type": "skipped", "message": "nsmc session not warm — run Tools/nsmc_online_probe.py first"}
        result.search = "skip"
        return
    # 会话存在时的轻量验证：仅确认会话文件可解析
    data = json.loads(cache.read_text(encoding="utf-8"))
    result.credential = "ok"
    result.search = "ok"
    result.download = {"path": str(cache), "bytes": len(data), "note": "session cache warm (download verify pending)"}


# ── 主流程 ────────────────────────────────────────────────────────────────────

VERIFIERS = {
    "nomads": lambda r, c: verify_nomads(r),
    "cmr": lambda r, c: verify_cmr(r),
    "gldas": verify_gldas,
    "smap": verify_smap,
    "cds": verify_cds,
    "cdse": verify_cdse,
    "nsmc": lambda r, c: verify_nsmc_placeholder(r),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="六源数据集在线下载最小验证")
    parser.add_argument("--sources", default="", help="逗号分隔：nomads,cmr,gldas,smap,cds,cdse,nsmc")
    parser.add_argument("--all", action="store_true", help="验证全部源（不含 nsmc 占位）")
    parser.add_argument("--report", default="", help="报告 JSON 输出路径")
    args = parser.parse_args()

    if args.all:
        sources = [s for s in VERIFIERS if s != "nsmc"]
    elif args.sources:
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        unknown = [s for s in sources if s not in VERIFIERS]
        if unknown:
            parser.error(f"unknown sources: {unknown}; available: {list(VERIFIERS)}")
    else:
        parser.print_help()
        return 2

    log(f"sources={sources}")
    creds: dict[str, Any] = {}
    try:
        creds = _get_runtime_credentials()
        log("portal credentials loaded")
    except Exception as exc:  # noqa: BLE001 — 凭据库不可用时逐源报告
        log(f"WARN portal credentials unavailable: {exc}")

    results: list[SourceResult] = []
    for name in sources:
        r = SourceResult(source=name)
        t0 = time.monotonic()
        try:
            VERIFIERS[name](r, creds)
            if not r.download:
                r.download = {"duration_ms": int((time.monotonic() - t0) * 1000)}
            status = "OK" if not r.error else f"SKIP({r.error.get('type', '')})"
            log(f"[{name}] {status} ({(time.monotonic() - t0):.1f}s)")
        except Exception as exc:  # noqa: BLE001 — 单源失败不阻断
            r.error = {
                "type": _classify_error(exc),
                "message": f"{type(exc).__name__}: {exc}"[:500],
                "traceback": traceback.format_exc()[-1500:],
            }
            log(f"[{name}] FAIL ({r.error['type']}): {exc}"[:200])
        results.append(r)

    # 报告
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report) if args.report else (
        REPORTS_DIR / f"dataset_download_verify_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    ok = [r for r in results if not r.error]
    fail = [r for r in results if r.error and r.error.get("type") != "skipped"]
    skipped = [r for r in results if r.error and r.error.get("type") == "skipped"]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(results),
            "ok": len(ok),
            "failed": len(fail),
            "skipped": len(skipped),
            "ok_sources": [r.source for r in ok],
            "failed_sources": [r.source for r in fail],
            "skipped_sources": [r.source for r in skipped],
        },
        "results": [r.to_dict() for r in results],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"report: {report_path}")
    log(f"summary: ok={len(ok)} failed={len(fail)} skipped={len(skipped)}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
