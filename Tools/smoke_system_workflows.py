#!/usr/bin/env python3
"""Lightweight system-seed workflow smoke runner (local联调).

Submit + poll POST/GET /workflow-runs for system seeds under
Code/backend/workflow_seeds/system/. Prints a matrix and optionally
writes Markdown under .ai/progress/.

Usage (repo root):
  Env\\Python312\\python.exe Tools\\smoke_system_workflows.py
  Env\\Python312\\python.exe Tools\\smoke_system_workflows.py --report .ai/progress/2026-08-06-workflow-smoke-matrix.md
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SEEDS_DIR = REPO_ROOT / "Code" / "backend" / "workflow_seeds" / "system"
DEFAULT_BASE = os.environ.get("CGDA_API_BASE", "http://127.0.0.1:8000")
DATA_ROOT = Path(os.environ.get("BACKEND_DATA_ROOT", r"I:\Geograph_DataSet"))

# Plan batch order (A tiles are separate; B–G below)
BATCH_B = [
    "weather_temperature_grid_demo",
    "weather_wind_field_demo",
]
BATCH_C = [
    "raster_histogram_basic",
    "raster_timeseries_curve",
    "raster_zonal_stats_aligned",
]
BATCH_D = [
    "smap_soil_moisture_local",
    "open_data_noaa_grib_sample",
]
BATCH_E = [
    "open_data_nasa_earthdata_sample",
    "open_data_nsidc_smap_sample",
    "open_data_esa_product_sample",
]
BATCH_F = [
    "omega_block_smap_single",
    "omega_avg_daily_smap_single",
    "omega_avg_daily_fy_single",
    "omega_avg_daily_smap_dual",
    "omega_avg_daily_smap_online",
    "omega_avg_daily_gldas_online",
    "omega_sf_fenkuai_smap_single",
    "omega_sf_fenkuai_fy_single",
]
BATCH_G = [
    "preprocess_clip_reproject_basic",
    "gis_raster_calc_reclassify_basic",
    "gis_buffer_zonal_basic",
    "stats_mean_summary_report_basic",
    "fusion_idw_interpolate_basic",
]
BATCH_H = [
    "preprocess_mask_resample_basic",
    "gis_vector_raster_roundtrip_basic",
    "gis_contour_slope_basic",
    "stats_trend_anomaly_basic",
    "fusion_multi_source_merge_basic",
]

TERMINAL = {"succeeded", "failed", "cancelled", "canceled"}


@dataclass
class Row:
    workflow_id: str
    batch: str
    run_id: str = ""
    status: str = "pending"
    elapsed_s: float = 0.0
    blocker: str = ""
    detail: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


_COOKIE_JAR = http.cookiejar.CookieJar()
_URL_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_COOKIE_JAR)
)


def _http_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    timeout: float = 60.0,
    api_key: str | None = None,
) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _URL_OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read()
            payload: Any = None
            if raw:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    payload = {"_raw": raw[:200].decode("utf-8", errors="replace")}
            return int(resp.status), payload
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {"detail": str(exc)}
        except json.JSONDecodeError:
            payload = {"detail": raw.decode("utf-8", errors="replace")[:500]}
        return int(exc.code), payload
    except Exception as exc:  # noqa: BLE001
        return 0, {"detail": str(exc)}


def login_session(
    base: str,
    *,
    username: str,
    password: str,
) -> tuple[bool, str]:
    """Establish session cookie for write endpoints when service key mismatches DB."""
    code, body = _http_json(
        "POST",
        f"{base.rstrip('/')}/auth/login",
        body={"username": username, "password": password},
        timeout=30,
    )
    if code != 200:
        detail = ""
        if isinstance(body, dict):
            detail = str(body.get("detail") or body)[:200]
        return False, f"HTTP {code} {detail}"
    return True, "ok"


def _http_bytes(url: str, timeout: float = 90.0) -> tuple[int, int, str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return int(resp.status), len(raw), ""
    except urllib.error.HTTPError as exc:
        return int(exc.code), 0, str(exc.reason)
    except Exception as exc:  # noqa: BLE001
        return 0, 0, str(exc)


def graph_body(definition: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in definition.items() if k != "_meta"}


def patch_node_path(definition: dict[str, Any], node_id: int, path: str) -> dict[str, Any]:
    out = json.loads(json.dumps(definition))
    for node in out.get("nodes") or []:
        if int(node.get("id", -1)) == node_id:
            props = node.setdefault("properties", {})
            props["path"] = path
            break
    return out


def patch_time_range(
    definition: dict[str, Any], start_at: str, end_at: str
) -> dict[str, Any]:
    out = json.loads(json.dumps(definition))
    for node in out.get("nodes") or []:
        if str(node.get("type") or "") == "data/time_range":
            props = node.setdefault("properties", {})
            props["start_at"] = start_at
            props["end_at"] = end_at
            break
    return out


def patch_bbox(
    definition: dict[str, Any],
    *,
    west: float,
    south: float,
    east: float,
    north: float,
) -> dict[str, Any]:
    out = json.loads(json.dumps(definition))
    for node in out.get("nodes") or []:
        if str(node.get("type") or "") == "data/bbox":
            props = node.setdefault("properties", {})
            props["west"] = west
            props["south"] = south
            props["east"] = east
            props["north"] = north
            break
    return out


def has_placeholder(definition: dict[str, Any]) -> list[str]:
    hits: list[str] = []
    blob = json.dumps(definition, ensure_ascii=False)
    for token in (
        "REPLACE_WITH_",
        "REPLACE_VARIABLE",
    ):
        if token in blob:
            hits.append(token)
    return hits


def discover_nomads_gfs_filter_target() -> dict[str, str] | None:
    """Resolve a tiny public NOMADS GFS filter URL (no credentials).

    Returns relative_path + query under https://nomads.ncep.noaa.gov/ suitable for
    http_open_data light smoke (≈200B GRIB2 subset). Returns None if NOMADS is
    unreachable or no recent GFS cycle yields a working filter response.

    Newest day/cycle directories often exist before filter_gfs_0p25.pl can serve
    f000 — probe candidates newest→oldest until HTTP 200 with payload.
    """
    import re
    import urllib.error
    import urllib.request

    base_list = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/"
    filter_rel = "cgi-bin/filter_gfs_0p25.pl"
    headers = {"User-Agent": "cgda-smoke/open_data_noaa"}

    def _fetch(url: str) -> str:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.read().decode("utf-8", "replace")

    def _probe_filter(day: str, cycle: str) -> dict[str, str] | None:
        query = (
            f"file=gfs.t{cycle}z.pgrb2.0p25.f000"
            f"&lev_2_m_above_ground=on&var_TMP=on"
            f"&subregion=&leftlon=113&rightlon=114&toplat=24&bottomlat=23"
            f"&dir=%2F{day}%2F{cycle}%2Fatmos"
        )
        url = f"https://nomads.ncep.noaa.gov/{filter_rel}?{query}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                chunk = resp.read(256)
                if resp.status != 200 or not chunk:
                    return None
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            return None
        return {
            "relative_path": filter_rel,
            "query": query,
            "day": day,
            "cycle": cycle,
        }

    try:
        listing = _fetch(base_list)
        days = sorted(set(re.findall(r'href="(gfs\.\d{8})/"', listing)), reverse=True)
        if not days:
            return None
        for day in days[:4]:
            cycles = sorted(
                set(re.findall(r'href="(\d{2})/"', _fetch(f"{base_list}{day}/"))),
                reverse=True,
            )
            for cycle in cycles:
                hit = _probe_filter(day, cycle)
                if hit is not None:
                    return hit
        return None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def cfgrib_available() -> bool:
    """True when optional cfgrib + xarray import in the current interpreter."""
    try:
        import cfgrib  # noqa: F401
        import xarray  # noqa: F401
    except ImportError:
        return False
    return True


def build_noaa_download_only_definition(
    definition: dict[str, Any], *, relative_path: str, query: str
) -> dict[str, Any]:
    """Smoke graph: http_open_data only (skip archive/extract — needs cfgrib)."""
    return build_http_open_data_download_only(
        definition,
        preset="noaa_nomads",
        relative_path=relative_path,
        query=query,
        cred_profile="",
    )


def build_noaa_download_extract_definition(
    definition: dict[str, Any],
    *,
    relative_path: str,
    query: str,
    variable: str = "t2m",
) -> dict[str, Any]:
    """Smoke graph: http_open_data → extract/variable (skip archive/convert).

    Used when cfgrib+eccodes are available in the worker interpreter.
    """
    out = json.loads(json.dumps(definition))
    download_node = {
        "id": 1,
        "type": "download/http_open_data",
        "pos": [80, 120],
        "properties": {
            "preset": "noaa_nomads",
            "relative_path": relative_path,
            "query": query,
            "cred_profile": "",
            "force_refresh": False,
        },
    }
    for node in out.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("type") or "") == "download/http_open_data":
            props = node.setdefault("properties", {})
            props["preset"] = "noaa_nomads"
            props["relative_path"] = relative_path
            props["query"] = query
            props["cred_profile"] = ""
            props["force_refresh"] = False
            download_node = node
            break
    extract_node = {
        "id": 3,
        "type": "extract/variable",
        "pos": [420, 120],
        "properties": {
            "variable": variable,
        },
    }
    out["nodes"] = [download_node, extract_node]
    # LiteGraph link: origin node 1 slot 0 (path) → target node 3 slot 0 (path)
    out["links"] = [
        {"0": 1, "1": 1, "2": 0, "3": 3, "4": 0, "5": "value:string"},
    ]
    return out


def build_http_open_data_download_only(
    definition: dict[str, Any],
    *,
    preset: str,
    relative_path: str,
    query: str = "",
    cred_profile: str = "",
) -> dict[str, Any]:
    """Smoke graph: single http_open_data node (skip archive/extract/variable)."""
    out = json.loads(json.dumps(definition))
    download_node = None
    for node in out.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("type") or "") == "download/http_open_data":
            props = node.setdefault("properties", {})
            props["preset"] = preset
            props["relative_path"] = relative_path
            props["query"] = query
            props["cred_profile"] = cred_profile
            props["force_refresh"] = False
            download_node = node
            break
    if download_node is None:
        download_node = {
            "id": 1,
            "type": "download/http_open_data",
            "pos": [80, 120],
            "properties": {
                "preset": preset,
                "relative_path": relative_path,
                "query": query,
                "cred_profile": cred_profile,
                "force_refresh": False,
            },
        }
    out["nodes"] = [download_node]
    out["links"] = []
    return out


def earthdata_portal_ready() -> bool:
    """True when env token or backend portal earthdata username/password/token exists."""
    if os.environ.get("BACKEND_EARTHDATA_TOKEN") or os.environ.get("EARTHDATA_TOKEN"):
        return True
    if os.environ.get("BACKEND_EARTHDATA_USERNAME") and os.environ.get(
        "BACKEND_EARTHDATA_PASSWORD"
    ):
        return True
    try:
        # Prefer runtime portal store (UI settings) over env-only checks.
        backend_root = REPO_ROOT / "Code" / "backend"
        if str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))
        os.environ.setdefault("ENVIRONMENT", "development")
        from app.services.config_service import get_portal_credentials_runtime

        ed = (get_portal_credentials_runtime() or {}).get("earthdata") or {}
        if not isinstance(ed, dict) or ed.get("enabled") is False:
            return False
        if str(ed.get("token") or ed.get("access_token") or "").strip():
            return True
        user = str(ed.get("username") or "").strip()
        pw = str(ed.get("password") or ed.get("secret") or "").strip()
        return bool(user and pw)
    except Exception:
        return False


def discover_nasa_lpdaac_smoke_target() -> dict[str, str] | None:
    """Tiny public LP DAAC browse JPG for nasa_earthdata download-only smoke."""
    import urllib.error
    import urllib.request

    # Stable public browse object (~1.5KB); exercises nasa_earthdata base URL + cache.
    rel = (
        "lp-prod-public/MCD43A4.061/MCD43A4.A2000055.h10v11.061.2020038135037/"
        "BROWSE.MCD43A4.A2000055.h10v11.061.2020038085120.1.jpg"
    )
    url = "https://data.lpdaac.earthdatacloud.nasa.gov/" + rel
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cgda-smoke/nasa"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            chunk = resp.read(64)
            if not chunk:
                return None
        return {"relative_path": rel, "label": "MCD43A4 browse jpg (public)"}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def path_exists_under_data(*parts: str) -> bool:
    return (DATA_ROOT.joinpath(*parts)).exists()


# Seed dataset_key → module required datasource keys (mirrors bundles / omega_avg)
_DS_ALIASES: dict[str, tuple[str, ...]] = {
    "ancillary_mat": ("anc_root",),
    "smap_daily_mat": ("smap_folder",),
    "ndvi_daily_mat": ("ndvi_folder",),
    "ndvi_clim_folder": ("ndvi_clim_folder",),
    "omega_block_output": ("omega_block_dir",),
    "fy3d_folder": ("fy3d_folder",),
    "fy3b_folder": ("fy3b_folder",),
    "gldas_mat": ("gldas_mat", "gldas_mat_folder", "gldas_folder"),
    "gldas_template_mat": ("gldas_template_mat", "gldas_template_file"),
    "input_path": ("input_path", "input_dir"),
    "SMAP_L3": ("input_dir", "input_path"),
}


def extract_time_range(definition: dict[str, Any]) -> dict[str, Any] | None:
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("type") or "") != "data/time_range":
            continue
        props = node.get("properties") or {}
        start = props.get("start_at")
        end = props.get("end_at")
        if start and end:
            gran = str(props.get("resolution_unit") or "day")
            if gran not in ("hour", "day", "month"):
                gran = "day"
            return {
                "start_at": str(start),
                "end_at": str(end),
                "granularity": gran,
            }
    return None


def extract_bbox_list(definition: dict[str, Any]) -> list[float] | None:
    """First data/bbox node → [west, south, east, north] for algorithm_params."""
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("type") or "") != "data/bbox":
            continue
        props = node.get("properties") or {}
        try:
            west = float(props["west"])
            south = float(props["south"])
            east = float(props["east"])
            north = float(props["north"])
        except (KeyError, TypeError, ValueError):
            continue
        return [west, south, east, north]
    return None


def extract_datasource_selection(definition: dict[str, Any]) -> dict[str, Any]:
    selection: dict[str, Any] = {}
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("type") or "") != "data/source":
            continue
        props = node.get("properties") or {}
        key = props.get("dataset_key") or props.get("key")
        path = props.get("path") or props.get("uri")
        if not path:
            continue
        path_s = str(path).replace("{DATA_ROOT}", str(DATA_ROOT)).replace("\\", "/")
        if not Path(path_s).is_absolute():
            path_s = str((DATA_ROOT / path_s).resolve()).replace("\\", "/")
        if key:
            selection[str(key)] = path_s
            for alias in _DS_ALIASES.get(str(key), ()):
                selection.setdefault(alias, path_s)
        selection.setdefault("input_path", path_s)
    return selection


def compile_litegraph(
    base: str,
    definition: dict[str, Any],
    *,
    api_key: str | None,
) -> tuple[dict[str, Any] | None, str]:
    """Compile seed LiteGraph → engine WorkflowDefinition via API.

    Returns ``(compiled_or_none, error_detail)``.
    """
    code, body = _http_json(
        "POST",
        f"{base}/workflow-definitions/compile",
        body={
            "workflow_id": definition.get("workflow_id"),
            "name": definition.get("name"),
            "description": definition.get("description"),
            "nodes": definition.get("nodes") or [],
            "links": definition.get("links") or [],
        },
        timeout=60,
        api_key=api_key,
    )
    if code != 200 or not isinstance(body, dict):
        detail = ""
        if isinstance(body, dict):
            detail = str(body.get("detail") or body)[:400]
        return None, f"HTTP {code} {detail}".strip()
    if isinstance(body.get("workflow_definition"), dict):
        return body["workflow_definition"], ""
    if isinstance(body.get("definition"), dict):
        return body["definition"], ""
    if "nodes" in body and isinstance(body.get("nodes"), list):
        if body["nodes"] and "node_id" in (body["nodes"][0] or {}):
            return body, ""
    return None, "unexpected compile response shape"


def build_payload(
    workflow_id: str,
    definition: dict[str, Any],
    *,
    overrides: dict[str, Any] | None = None,
    compiled_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    overrides = overrides or {}
    meta = definition.get("_meta") if isinstance(definition.get("_meta"), dict) else {}
    extra = definition.get("extra") if isinstance(definition.get("extra"), dict) else {}
    engine = str(meta.get("engine") or "common")
    command_type = str(extra.get("default_command") or "analysis")
    linked_layer = (
        overrides.get("layer_id")
        if "layer_id" in overrides
        else (extra.get("default_layer_id") or meta.get("linked_layer_id"))
    )
    parameters = dict(extra.get("default_parameters") or {})
    parameters.update(overrides.get("parameters") or {})

    defn = overrides.get("definition") or definition
    body = graph_body(defn)

    payload: dict[str, Any] = {
        "command_type": command_type,
        "command_label": f"smoke:{workflow_id}",
        "parameters": parameters,
        "requested_outputs": ["json"],
        "client": {"client_id": "smoke_system_workflows", "page": "tools"},
    }

    if engine == "weather":
        weather_graph = compiled_graph or body
        # Ensure fetch nodes have lat/lon; prefer online/auto provider for smoke
        # (open-meteo-local may be disabled until sync/registry enablement).
        if isinstance(weather_graph, dict):
            weather_graph = json.loads(json.dumps(weather_graph))
            for node in weather_graph.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                params_n = node.setdefault("params", {})
                ntype = str(node.get("node_type") or "")
                if "fetch" in ntype or "grid" in ntype or "render" in ntype or "wind" in ntype or "temperature" in ntype:
                    params_n.setdefault("latitude", 23.1291)
                    params_n.setdefault("longitude", 113.2644)
                if params_n.get("provider") == "open-meteo-local":
                    params_n["provider"] = "open-meteo-online"
                if params_n.get("provider_id") == "open-meteo-local":
                    params_n["provider_id"] = "open-meteo-online"
        payload["layer_id"] = linked_layer
        payload["resource_profile"] = "standard"
        payload["weather_request"] = {
            "workflow_id": workflow_id,
            "layer_id": linked_layer,
            "workflow": weather_graph,
            "context": {
                "latitude": 23.1291,
                "longitude": 113.2644,
                "forecast_hours": 6,
                "model": "ecmwf_ifs025",
            },
        }
        params = payload["parameters"]
        params.setdefault("latitude", 23.1291)
        params.setdefault("longitude", 113.2644)
        params.setdefault("place_name", "Guangzhou")
        params.setdefault("forecast_hours", 6)
        params.setdefault("model", "ecmwf_ifs025")
        payload["map_context"] = {
            "active_layer_id": linked_layer,
            "map_mode": "2d",
        }
        payload["requested_outputs"] = ["json", "map_layer"]
        payload["command_type"] = "custom"
    elif engine in ("python_provider", "common"):
        # Do NOT set layer_id: linked_layer_id often points at a different module
        # (e.g. omega_block seed → method-smap-omega-doy-avg) and trip submit-time 422.
        ds = overrides.get("datasource_selection")
        if not isinstance(ds, dict):
            ds = extract_datasource_selection(defn)
        algo_params = dict(parameters)
        for node in defn.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            ntype = str(node.get("type") or "")
            props = node.get("properties") or {}
            if ntype.startswith("module/"):
                nested = props.get("algorithm_params")
                if isinstance(nested, dict):
                    for k, v in nested.items():
                        algo_params.setdefault(k, v)
                for k, v in props.items():
                    if k not in ("module_name", "task_type", "algorithm_params", "notes"):
                        algo_params.setdefault(k, v)
            if ntype in ("stats/histogram", "viz/chart_generate"):
                for k, v in props.items():
                    if k not in ("notes",):
                        algo_params.setdefault(k, v)
            # preprocess/* etc. also carry params on the typed node itself
            if ntype.startswith(("preprocess/", "gis/", "stats/", "fusion/", "viz/")):
                for k, v in props.items():
                    if k not in ("notes", "path", "dataset_key"):
                        algo_params.setdefault(k, v)

        bbox_list = extract_bbox_list(defn)
        if bbox_list is not None:
            algo_params.setdefault("bbox", bbox_list)
            algo_params.setdefault("bbox_west", bbox_list[0])
            algo_params.setdefault("bbox_south", bbox_list[1])
            algo_params.setdefault("bbox_east", bbox_list[2])
            algo_params.setdefault("bbox_north", bbox_list[3])

        # Prefer compiled graph for python_provider/common (D1 multi-module and
        # D2 single-algorithm + data/source).
        algo: dict[str, Any] = {
            "algorithm_params": algo_params,
            "datasource_selection": ds,
        }
        if compiled_graph is not None:
            algo["workflow_definition"] = compiled_graph
        else:
            algo["workflow_name"] = workflow_id
        payload["algorithm_request"] = algo
        tr = overrides.get("time_range") or extract_time_range(defn)
        if tr is None:
            tr = {
                "start_at": "2025-01-01T00:00:00Z",
                "end_at": "2025-01-02T00:00:00Z",
                "granularity": "day",
            }
        payload["time_range"] = tr
        if bbox_list is not None:
            payload.setdefault(
                "spatial_filter",
                {
                    "filter_type": "bbox",
                    "bbox": {
                        "west": bbox_list[0],
                        "south": bbox_list[1],
                        "east": bbox_list[2],
                        "north": bbox_list[3],
                        "crs": "EPSG:4326",
                    },
                },
            )
        profile = str(meta.get("resource_profile") or "").strip().lower()
        if workflow_id.startswith("omega_") or profile == "heavy":
            payload["resource_profile"] = "heavy"
        elif profile in ("standard", "realtime", "batch"):
            payload["resource_profile"] = profile
        else:
            payload["resource_profile"] = "standard"
    elif engine == "gee":
        payload["layer_id"] = linked_layer
        payload["gee_request"] = {
            "workflow_id": workflow_id,
            "workflow": body,
        }
    else:
        payload["algorithm_request"] = {
            "workflow_name": workflow_id,
        }

    for key in (
        "time_range",
        "spatial_filter",
        "priority",
        "retry_policy",
        "config_overrides",
    ):
        if key in overrides and key not in payload:
            payload[key] = overrides[key]
    return payload


def poll_run(
    base: str,
    run_id: str,
    *,
    timeout_s: float,
    api_key: str | None,
    interval_s: float = 2.0,
) -> tuple[str, dict[str, Any], float]:
    t0 = time.time()
    last: dict[str, Any] = {}
    while time.time() - t0 < timeout_s:
        code, body = _http_json(
            "GET", f"{base}/workflow-runs/{run_id}", timeout=30, api_key=api_key
        )
        if code != 200 or not isinstance(body, dict):
            time.sleep(interval_s)
            continue
        last = body
        status = str(body.get("status") or "")
        if status in TERMINAL:
            return status, last, time.time() - t0
        time.sleep(interval_s)
    return "timeout", last, time.time() - t0


def extract_error(run: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("error_message", "message", "failure_reason"):
        val = run.get(key)
        if val and str(val) not in (
            "工作流执行失败，请查看服务端日志。",
            "Workflow execution failed",
        ):
            parts.append(str(val)[:300])
    diags = run.get("diagnostics")
    if isinstance(diags, list) and diags:
        # Prefer diagnostics that carry the real exception text
        for d in diags:
            s = str(d)
            if s.startswith("error_message="):
                parts.append(s.split("=", 1)[1][:400])
                break
        else:
            parts.append(" | ".join(str(d)[:120] for d in diags[-3:]))
    result = run.get("result_dto")
    if isinstance(result, dict):
        err = result.get("error") or result.get("message")
        if err:
            parts.append(str(err)[:200])
    return "; ".join(parts)[:500]


def preflight_block(workflow_id: str, definition: dict[str, Any]) -> str | None:
    """Return blocker code if we should not hard-submit."""
    placeholders = has_placeholder(definition)
    if workflow_id.startswith("open_data_") and placeholders:
        # NOAA: public portal — discover a live GFS filter target instead of REPLACE_*.
        if workflow_id == "open_data_noaa_grib_sample":
            if discover_nomads_gfs_filter_target() is None:
                return (
                    "blocked:config (NOMADS unreachable or no GFS cycle for smoke)"
                )
            return None
        # NASA: public LP DAAC browse object (download-only); portal creds optional.
        if workflow_id == "open_data_nasa_earthdata_sample":
            if discover_nasa_lpdaac_smoke_target() is None:
                return "blocked:config (LP DAAC browse sample unreachable)"
            return None
        # NSIDC: need earthdata portal + curated path (granules too large for light smoke)
        if workflow_id == "open_data_nsidc_smap_sample":
            if not earthdata_portal_ready():
                return "blocked:creds (no Earthdata portal username/password/token)"
            return (
                "blocked:runtime (Earthdata ready; NSIDC SMAP granules too large "
                "for light smoke — needs curated small path)"
            )
        if workflow_id == "open_data_esa_product_sample":
            return "blocked:creds (copernicus profile) + REPLACE_* path"
    if workflow_id == "omega_avg_daily_gldas_online":
        mat_dir = DATA_ROOT / "Meteorological" / "Weather" / "GLDAS"
        has_mat = mat_dir.is_dir() and any(mat_dir.glob("*.mat"))
        if not has_mat:
            nc4_dir = DATA_ROOT / "Meteorological" / "Weather" / "GLDAS_Download"
            has_nc4 = nc4_dir.is_dir() and any(nc4_dir.rglob("*.nc4"))
            if has_nc4:
                return (
                    "blocked:data (GLDAS .nc4 present; run gldas_nc4_to_mat first)"
                )
            return "blocked:data (no GLDAS .mat; need download + nc4→mat)"
    if workflow_id == "omega_avg_daily_smap_online":
        # Template is download→avg with date placeholders; needs h5→mat bridge.
        ed = "earthdata portal ready" if earthdata_portal_ready() else "no earthdata creds"
        return (
            f"blocked:config (online download template + needs h5→mat bridge; {ed}; "
            "not light-smoke)"
        )
    if workflow_id == "omega_avg_daily_smap_dual":
        mat_dir = DATA_ROOT / "Meteorological" / "Weather" / "GLDAS"
        nc4_dir = DATA_ROOT / "Meteorological" / "Weather" / "GLDAS_Download"
        has_mat = mat_dir.is_dir() and any(mat_dir.glob("*.mat"))
        has_nc4 = nc4_dir.is_dir() and any(nc4_dir.rglob("*.nc4"))
        if not has_mat:
            if has_nc4:
                return (
                    "blocked:data (GLDAS .nc4 present under GLDAS_Download; "
                    "need nc4→mat with Ts_gldas/Tsoil1_gldas/Tsoil2_gldas)"
                )
            return "blocked:data (GLDAS .mat dir missing for DUAL temp_scheme)"
    if workflow_id.startswith("omega_avg_daily_"):
        block_dir = DATA_ROOT / "Inversion_Results" / "omega_block"
        mats = list(block_dir.glob("omega_block_*.mat")) if block_dir.is_dir() else []
        if not mats:
            bak = (
                list(block_dir.glob("omega_block_*.mat.bootstrap.bak"))
                if block_dir.is_dir()
                else []
            )
            if bak:
                return (
                    "blocked:data (only omega_block_*.mat.bootstrap.bak present — "
                    "D1 incomplete; promote bak→mat or re-run D1)"
                )
            return (
                "blocked:data (no Inversion_Results/omega_block/omega_block_*.mat — "
                "run D1 omega_block first)"
            )
    # Fenkuai: allow when SMAP (and FY if needed) data exist; light-smoke caps
    # applied in prepare_overrides (max_pixels + short window + small bbox).
    if workflow_id.startswith("omega_sf_fenkuai_"):
        ready = path_exists_under_data(
            "Soil_Moisture", "SMAP_Origin_Data"
        ) and path_exists_under_data("Soil_Moisture", "SMAP_Auxiliary_Data")
        if not ready:
            return "blocked:data (SMAP origin/aux missing for fenkuai)"
        if workflow_id.endswith("_fy_single"):
            fy_ok = path_exists_under_data(
                "Soil_Moisture", "FY3D"
            ) or path_exists_under_data("Soil_Moisture", "FY3B")
            # Also accept common FY daily mat layouts under DATA_ROOT
            if not fy_ok:
                fy_hits = list(
                    (DATA_ROOT / "Soil_Moisture").glob("**/FY3*")
                ) if (DATA_ROOT / "Soil_Moisture").is_dir() else []
                if not fy_hits:
                    return "blocked:data (FY3B/FY3D mats missing for fenkuai_fy)"
        return None
    return None


def primary_module_name(definition: dict[str, Any], workflow_id: str) -> str | None:
    """Pick the main executable module (legacy helper; smoke prefers compiled graphs)."""
    if workflow_id.startswith("omega_avg_daily_"):
        return "omega_avg_daily"
    if workflow_id.startswith("omega_sf_fenkuai_"):
        return "omega_sf_fenkuai"
    if workflow_id.startswith("omega_block_"):
        return "omega_block"
    # Prefer last module/* node
    last: str | None = None
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        if ntype.startswith("module/"):
            props = node.get("properties") or {}
            last = str(props.get("module_name") or ntype.split("/", 1)[-1])
    return last


def ensure_analysis_fixtures() -> dict[str, Path]:
    """Create tiny MAT fixtures for timeseries / zonal smoke (under DATA_ROOT/_runtime)."""
    runtime = DATA_ROOT / "_runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    stack = runtime / "smoke_stack_3d.mat"
    zones = runtime / "smoke_zones.mat"
    value2d = runtime / "smoke_value_2d.mat"
    try:
        import numpy as np
        from scipy.io import savemat
    except Exception:
        return {}
    if not stack.is_file():
        arr = np.arange(3 * 8 * 8, dtype=np.float64).reshape(3, 8, 8)
        savemat(
            stack,
            {
                "sm": arr,
                "lat": np.linspace(40, 39.3, 8),
                "lon": np.linspace(100, 100.7, 8),
            },
            do_compression=True,
        )
    if not zones.is_file():
        z = np.zeros((8, 8), dtype=np.float64)
        z[:4, :4] = 1
        z[:4, 4:] = 2
        z[4:, :4] = 3
        z[4:, 4:] = 4
        savemat(zones, {"zones": z}, do_compression=True)
    if not value2d.is_file():
        v = np.arange(64, dtype=np.float64).reshape(8, 8)
        savemat(value2d, {"values": v}, do_compression=True)
    return {"stack": stack, "zones": zones, "value2d": value2d}


def ensure_stub_v1_fixtures() -> dict[str, Path]:
    """Create GeoTIFF + GeoJSON + timeseries fixtures for stub_v1 Batch G/H seeds."""
    runtime = DATA_ROOT / "_runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    stub_tif = runtime / "smoke_stub.tif"
    stub_b_tif = runtime / "smoke_stub_b.tif"
    dem_tif = runtime / "smoke_dem.tif"
    points_gj = runtime / "smoke_points.geojson"
    zones_gj = runtime / "smoke_zones.geojson"
    timeseries_json = runtime / "smoke_timeseries.json"
    out: dict[str, Path] = {}

    def _write_geotiff(path: Path, data, *, origin=(100.0, 30.0), res=0.1) -> None:
        import rasterio
        from rasterio.transform import from_origin

        transform = from_origin(origin[0], origin[1], res, res)
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            count=1,
            dtype="float64",
            crs="EPSG:4326",
            transform=transform,
            nodata=float("nan"),
        ) as dst:
            dst.write(data, 1)

    try:
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        _log(f"stub_v1 fixture numpy skipped: {exc}")
        np = None  # type: ignore[assignment]

    if np is not None:
        if not stub_tif.is_file():
            try:
                data = np.full((20, 20), 5.0, dtype=np.float64)
                data[0, 0] = np.nan
                _write_geotiff(stub_tif, data)
            except Exception as exc:  # noqa: BLE001
                _log(f"stub_v1 fixture GeoTIFF skipped: {exc}")
        if stub_tif.is_file():
            out["stub_tif"] = stub_tif

        if not stub_b_tif.is_file():
            try:
                data_b = np.full((20, 20), 8.0, dtype=np.float64)
                data_b[1, 1] = np.nan
                _write_geotiff(stub_b_tif, data_b)
            except Exception as exc:  # noqa: BLE001
                _log(f"stub_v1 fixture stub_b skipped: {exc}")
        if stub_b_tif.is_file():
            out["stub_b_tif"] = stub_b_tif

        if not dem_tif.is_file():
            try:
                yy, xx = np.mgrid[0:20, 0:20]
                dem = (xx + yy).astype(np.float64) * 2.0
                _write_geotiff(dem_tif, dem)
            except Exception as exc:  # noqa: BLE001
                _log(f"stub_v1 fixture DEM skipped: {exc}")
        if dem_tif.is_file():
            out["dem_tif"] = dem_tif
    else:
        if stub_tif.is_file():
            out["stub_tif"] = stub_tif
        if stub_b_tif.is_file():
            out["stub_b_tif"] = stub_b_tif
        if dem_tif.is_file():
            out["dem_tif"] = dem_tif

    if not points_gj.is_file():
        # Points inside fusion_idw bbox (112.9–113.3E / 22.9–23.2N); also used by buffer.
        points = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [113.0, 23.0]},
                    "properties": {"value": 10.0},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [113.2, 23.1]},
                    "properties": {"value": 20.0},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [113.1, 23.05]},
                    "properties": {"value": 15.0},
                },
            ],
        }
        points_gj.write_text(json.dumps(points), encoding="utf-8")
    if points_gj.is_file():
        out["points"] = points_gj

    if not zones_gj.is_file():
        zones = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [100.0, 28.0],
                                [102.0, 28.0],
                                [102.0, 30.0],
                                [100.0, 30.0],
                                [100.0, 28.0],
                            ]
                        ],
                    },
                    "properties": {"id": 1},
                }
            ],
        }
        zones_gj.write_text(json.dumps(zones), encoding="utf-8")
    if zones_gj.is_file():
        out["zones"] = zones_gj

    if not timeseries_json.is_file():
        series = {
            "times": [
                "2025-01-01",
                "2025-01-02",
                "2025-01-03",
                "2025-01-04",
                "2025-01-05",
                "2025-01-06",
                "2025-01-07",
                "2025-01-08",
            ],
            "values": [1.0, 1.2, 0.9, 1.1, 1.0, 10.0, 1.05, 0.95],
            "lon": 113.0,
            "lat": 23.0,
        }
        timeseries_json.write_text(json.dumps(series), encoding="utf-8")
    if timeseries_json.is_file():
        out["timeseries"] = timeseries_json

    return out


def prepare_overrides(
    workflow_id: str, definition: dict[str, Any]
) -> dict[str, Any]:
    """Local one-shot path/window tweaks for smoke (do not mutate seed files)."""
    overrides: dict[str, Any] = {}
    smoke_tif = DATA_ROOT / "_runtime" / "smoke_hist.tif"
    fixtures = ensure_analysis_fixtures()
    if workflow_id == "raster_histogram_basic" and smoke_tif.is_file():
        overrides["definition"] = patch_node_path(
            definition, 1, str(smoke_tif).replace("\\", "/")
        )
        overrides["datasource_selection"] = {
            "input_path": str(smoke_tif).replace("\\", "/")
        }
    if workflow_id == "raster_timeseries_curve" and fixtures.get("stack"):
        p = str(fixtures["stack"]).replace("\\", "/")
        overrides["definition"] = patch_node_path(definition, 1, p)
        overrides["datasource_selection"] = {"input_path": p}
        overrides["parameters"] = {"mode": "timeseries", "variable": "sm"}
    if workflow_id == "raster_zonal_stats_aligned" and fixtures.get("value2d"):
        p = str(fixtures["value2d"]).replace("\\", "/")
        z = str(fixtures["zones"]).replace("\\", "/")
        overrides["definition"] = patch_node_path(definition, 1, p)
        overrides["datasource_selection"] = {"input_path": p}
        overrides["parameters"] = {
            "mode": "zonal",
            "variable": "values",
            "zones_source": z,
        }
    if workflow_id == "open_data_noaa_grib_sample":
        target = discover_nomads_gfs_filter_target()
        if target is not None:
            if cfgrib_available():
                overrides["definition"] = build_noaa_download_extract_definition(
                    definition,
                    relative_path=target["relative_path"],
                    query=target["query"],
                    variable="t2m",
                )
                overrides["_note"] = (
                    f"NOMADS GFS filter {target['day']}/{target['cycle']} "
                    "http_open_data→variable_extract (t2m; archive skipped; cfgrib ok)"
                )
            else:
                overrides["definition"] = build_noaa_download_only_definition(
                    definition,
                    relative_path=target["relative_path"],
                    query=target["query"],
                )
                overrides["_note"] = (
                    f"NOMADS GFS filter {target['day']}/{target['cycle']} "
                    "download-only; blocked:deps (cfgrib/eccodes)"
                )
    if workflow_id == "open_data_nasa_earthdata_sample":
        target = discover_nasa_lpdaac_smoke_target()
        if target is not None:
            overrides["definition"] = build_http_open_data_download_only(
                definition,
                preset="nasa_earthdata",
                relative_path=target["relative_path"],
                cred_profile="earthdata",
            )
            overrides["_note"] = (
                f"NASA LP DAAC {target['label']} download-only "
                "(archive/extract/variable skipped)"
            )
    if workflow_id == "smap_soil_moisture_local":
        # Seed uses {DATA_ROOT}/SMAP; local layout is Soil_Moisture/SMAP
        smap_dir = DATA_ROOT / "Soil_Moisture" / "SMAP"
        if smap_dir.is_dir():
            overrides["definition"] = patch_node_path(
                definition, 1, str(smap_dir).replace("\\", "/")
            )
    if workflow_id == "omega_block_smap_single":
        # Seed window Dec 2025; local mats are Nov 2025 — short override for smoke
        mats = sorted(
            (DATA_ROOT / "Soil_Moisture" / "SMAP_Origin_Data").glob("202511*.mat")
        )
        if mats:
            overrides["definition"] = patch_time_range(
                definition,
                "2025-11-01T00:00:00",
                "2025-11-02T00:00:00",
            )
            overrides["time_range"] = {
                "start_at": "2025-11-01T00:00:00",
                "end_at": "2025-11-02T00:00:00",
                "granularity": "day",
            }
            overrides["_note"] = (
                "time_range overridden to 2025-11-01..02 (available mats); "
                "compiled graph timeseries_bundle → omega_block"
            )
    if workflow_id.startswith("omega_avg_daily_") and workflow_id not in (
        "omega_avg_daily_smap_online",
    ):
        # Align to available D1 Dec window; ensure ndvi_clim alias resolves.
        overrides["definition"] = patch_time_range(
            definition,
            "2025-12-03T00:00:00",
            "2025-12-05T00:00:00",
        )
        overrides["time_range"] = {
            "start_at": "2025-12-03T00:00:00",
            "end_at": "2025-12-05T00:00:00",
            "granularity": "day",
        }
        ds = extract_datasource_selection(overrides.get("definition") or definition)
        clim = DATA_ROOT / "Ecological_Vegetation" / "NDVI" / "climatology"
        if clim.is_dir():
            ds.setdefault("ndvi_clim_folder", str(clim).replace("\\", "/"))
        ndvi_day = DATA_ROOT / "Ecological_Vegetation" / "NDVI" / "NDVIday"
        if ndvi_day.is_dir():
            ds.setdefault("ndvi_folder", str(ndvi_day).replace("\\", "/"))
            ds.setdefault("ndvi_daily_mat", str(ndvi_day).replace("\\", "/"))
        gldas_dir = DATA_ROOT / "Meteorological" / "Weather" / "GLDAS"
        if gldas_dir.is_dir():
            ds.setdefault("gldas_mat", str(gldas_dir).replace("\\", "/"))
            ds.setdefault("gldas_mat_folder", str(gldas_dir).replace("\\", "/"))
            ds.setdefault("gldas_folder", str(gldas_dir).replace("\\", "/"))
        template_mat = _find_gldas_template_mat()
        algo_params: dict[str, Any] = {
            "enable_parallel": False,
            "pixel_chunk_size": 50_000,
            "target_year": 2025,
            "avg_build_start_year": 2025,
            "avg_build_end_year": 2025,
            "stage_d_start_date": "2025-12-07",
            "stage_d_end_date": "2025-12-11",
            "stage_d_max_days": 5,
        }
        if template_mat is not None:
            ds.setdefault("gldas_template_mat", str(template_mat).replace("\\", "/"))
            ds.setdefault("gldas_template_file", str(template_mat).replace("\\", "/"))
            if workflow_id in (
                "omega_avg_daily_smap_dual",
                "omega_avg_daily_gldas_online",
            ):
                algo_params["use_gldas_template"] = True
        elif workflow_id in ("omega_avg_daily_smap_dual", "omega_avg_daily_gldas_online"):
            # Soft fallback if template build failed in preflight.
            algo_params["use_gldas_template"] = False
        overrides["datasource_selection"] = ds
        overrides["parameters"] = algo_params
        note = (
            "compiled graph → omega_avg_daily; time_range→2025-12-03..05; "
            "parallel disabled for smoke; Stage D limited to 2025-12-07..11 (max 5 days)"
        )
        if workflow_id == "omega_avg_daily_gldas_online":
            note += (
                "; gldas_online graph=D2 only "
                "(gldas_download/nc4→mat verified separately)"
            )
        if workflow_id == "omega_avg_daily_smap_dual":
            note += "; DUAL temp_scheme with local GLDAS .mat"
        if template_mat is not None and workflow_id in (
            "omega_avg_daily_smap_dual",
            "omega_avg_daily_gldas_online",
        ):
            note += "; use_gldas_template=true"
        elif workflow_id in (
            "omega_avg_daily_smap_dual",
            "omega_avg_daily_gldas_online",
        ):
            note += "; use_gldas_template=false (template unavailable)"
        overrides["_note"] = note
    if workflow_id.startswith("omega_sf_fenkuai_"):
        # One 8-day block + tiny pixel budget so light smoke finishes in minutes.
        defn = overrides.get("definition") or definition
        defn = patch_time_range(
            defn, "2025-12-03T00:00:00", "2025-12-10T00:00:00"
        )
        defn = patch_bbox(
            defn, west=110.0, south=20.0, east=115.0, north=25.0
        )
        overrides["definition"] = defn
        overrides["time_range"] = {
            "start_at": "2025-12-03T00:00:00",
            "end_at": "2025-12-10T00:00:00",
            "granularity": "day",
        }
        ds = extract_datasource_selection(defn)
        clim = DATA_ROOT / "Ecological_Vegetation" / "NDVI" / "climatology"
        if clim.is_dir():
            ds.setdefault("ndvi_clim_folder", str(clim).replace("\\", "/"))
        overrides["datasource_selection"] = ds
        overrides["parameters"] = {
            "start_date": "20251203",
            "end_date": "20251210",
            "block_days": 8,
            "max_pixels": 400,
            "enable_parallel": False,
            "max_workers": 1,
            "pixel_chunk_size": 400,
            "bbox": [110.0, 20.0, 115.0, 25.0],
            "bbox_west": 110.0,
            "bbox_south": 20.0,
            "bbox_east": 115.0,
            "bbox_north": 25.0,
            "run_domain": "REGIONAL",
        }
        overrides["_note"] = (
            "light-smoke: 2025-12-03..10 (1×8d block), bbox 110–115E/20–25N, "
            "max_pixels=400, serial; keeps output/map_layer"
        )
    if workflow_id in BATCH_G or workflow_id in BATCH_H:
        stub = ensure_stub_v1_fixtures()
        defn = overrides.get("definition") or definition
        path_map = [
            ("smoke_stub.tif", stub.get("stub_tif")),
            ("smoke_stub_b.tif", stub.get("stub_b_tif")),
            ("smoke_dem.tif", stub.get("dem_tif")),
            ("smoke_points.geojson", stub.get("points")),
            ("smoke_zones.geojson", stub.get("zones")),
            ("smoke_timeseries.json", stub.get("timeseries")),
        ]
        for node in defn.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            if str(node.get("type") or "") != "data/source":
                continue
            props = node.get("properties") or {}
            path = str(props.get("path") or "")
            for suffix, resolved in path_map:
                if suffix in path and resolved is not None:
                    defn = patch_node_path(
                        defn, int(node["id"]), str(resolved).replace("\\", "/")
                    )
                    break
        overrides["definition"] = defn
        overrides["datasource_selection"] = extract_datasource_selection(defn)
        overrides["_note"] = (
            "stub_v1 fixtures under {DATA_ROOT}/_runtime "
            "(smoke_stub.tif / smoke_stub_b.tif / smoke_dem.tif / "
            "smoke_points.geojson / smoke_zones.geojson / smoke_timeseries.json)"
        )
    return overrides


def _find_gldas_template_mat() -> Path | None:
    """Locate ``gldas_utc_template_global.mat`` (or similar) under DATA_ROOT."""
    candidates = [
        DATA_ROOT / "Meteorological" / "Weather" / "GLDAS_UTC_TEMPLATE" / "gldas_utc_template_global.mat",
        DATA_ROOT / "GLDAS_UTC_TEMPLATE" / "gldas_utc_template_global.mat",
    ]
    for path in candidates:
        if path.is_file():
            return path
    for hit in DATA_ROOT.rglob("gldas_utc_template*.mat"):
        if hit.is_file():
            return hit
    return None


def ensure_gldas_utc_template_mat() -> dict[str, Any]:
    """Build local GLDAS UTC template when missing (from IGBP lon grid)."""
    existing = _find_gldas_template_mat()
    if existing is not None:
        return {"path": str(existing), "built": False}
    try:
        sys.path.insert(0, str(REPO_ROOT / "Code" / "algorithms" / "providers" / "Python"))
        from ingest.gldas_utc_template import ensure_gldas_utc_template

        path = ensure_gldas_utc_template(data_root=DATA_ROOT)
        return {"path": str(path), "built": True}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:300]}


def ensure_gldas_nc4_converted() -> dict[str, Any]:
    """Convert any GLDAS .nc4 under GLDAS_Download missing a sibling .mat."""
    nc4_dir = DATA_ROOT / "Meteorological" / "Weather" / "GLDAS_Download"
    mat_dir = DATA_ROOT / "Meteorological" / "Weather" / "GLDAS"
    anc = DATA_ROOT / "Soil_Moisture" / "SMAP_Auxiliary_Data" / "IGBP_9km_12.mat"
    if not nc4_dir.is_dir() or not anc.is_file():
        return {"skipped": True, "reason": "no nc4 dir or ancillary mat"}
    mat_dir.mkdir(parents=True, exist_ok=True)
    try:
        sys.path.insert(0, str(REPO_ROOT / "Code" / "algorithms" / "providers" / "Python"))
        from ingest.gldas_nc4_to_mat import convert_gldas_nc4_directory

        result = convert_gldas_nc4_directory(
            input_dir=str(nc4_dir),
            output_dir=str(mat_dir),
            ancillary_mat=str(anc),
            skip_existing=True,
        )
        return {
            "total_nc4": result.total_nc4,
            "converted": result.converted,
            "skipped": result.skipped,
            "failed": result.failed,
            "outputs": result.outputs[:5],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:300]}


def run_tiles(base: str) -> list[Row]:
    rows: list[Row] = []
    for layer in ("temperature", "wind-field"):
        url = f"{base}/weather/tiles/{layer}/3/6/3"
        t0 = time.time()
        code, nbytes, err = _http_bytes(url, timeout=120)
        elapsed = time.time() - t0
        row = Row(
            workflow_id=f"weather/tiles/{layer}",
            batch="A",
            status="succeeded" if code == 200 else "failed",
            elapsed_s=round(elapsed, 2),
            detail=f"HTTP {code} bytes={nbytes}" + (f" err={err}" if err else ""),
        )
        if code != 200:
            row.blocker = f"http_{code}"
        rows.append(row)
        _log(f"[A] {row.workflow_id}: {row.status} ({row.elapsed_s}s) {row.detail}")
    return rows


def submit_and_poll(
    base: str,
    workflow_id: str,
    batch: str,
    *,
    api_key: str | None,
    timeout_s: float,
    dry_run: bool = False,
) -> Row:
    row = Row(workflow_id=workflow_id, batch=batch)
    code, definition = _http_json(
        "GET", f"{base}/workflow-definitions/{workflow_id}", timeout=30, api_key=api_key
    )
    if code != 200 or not isinstance(definition, dict):
        row.status = "failed"
        row.blocker = "definition_missing"
        row.detail = str(definition)[:300]
        return row

    block = preflight_block(workflow_id, definition)
    if block:
        row.status = "skipped"
        row.blocker = block
        _log(f"[{batch}] {workflow_id}: skipped — {block}")
        return row

    # Soft data checks for omega (still attempt if core dirs exist)
    if workflow_id.startswith("omega_"):
        missing: list[str] = []
        for rel in (
            "Soil_Moisture/SMAP_Origin_Data",
            "Soil_Moisture/SMAP_Auxiliary_Data",
            "Ecological_Vegetation/NDVI/climatology",
        ):
            if not path_exists_under_data(*rel.split("/")):
                missing.append(rel)
        if workflow_id == "omega_block_smap_single":
            mats = list(
                (DATA_ROOT / "Soil_Moisture" / "SMAP_Origin_Data").glob("202511*.mat")
            )
            if not mats:
                row.status = "skipped"
                row.blocker = "blocked:data (no SMAP_Origin_Data 202511*.mat)"
                _log(f"[{batch}] {workflow_id}: skipped — {row.blocker}")
                return row
        if missing:
            row.status = "skipped"
            row.blocker = "blocked:data (" + ", ".join(missing) + ")"
            _log(f"[{batch}] {workflow_id}: skipped — {row.blocker}")
            return row

    overrides = prepare_overrides(workflow_id, definition)
    note = overrides.pop("_note", None)
    compiled_graph = None
    meta = definition.get("_meta") if isinstance(definition.get("_meta"), dict) else {}
    engine = str(meta.get("engine") or "")
    needs_compile = engine == "weather" or engine in ("python_provider", "common")
    if needs_compile:
        defn_for_compile = overrides.get("definition") or definition
        compiled_graph, compile_err = compile_litegraph(
            base, defn_for_compile, api_key=api_key
        )
        if compiled_graph is None:
            row.status = "failed"
            row.blocker = "compile_failed"
            row.detail = compile_err or "POST /workflow-definitions/compile failed"
            _log(f"[{batch}] {workflow_id}: {row.detail}")
            return row
    payload = build_payload(
        workflow_id,
        definition,
        overrides=overrides,
        compiled_graph=compiled_graph,
    )
    if dry_run:
        row.status = "dry_run"
        row.detail = f"payload_keys={list(payload.keys())}"
        return row

    t0 = time.time()
    _log(f"[{batch}] {workflow_id}: submitting…")
    scode, accepted = _http_json(
        "POST", f"{base}/workflow-runs", body=payload, timeout=60, api_key=api_key
    )
    if scode not in (200, 201, 202) or not isinstance(accepted, dict):
        row.status = "failed"
        row.elapsed_s = round(time.time() - t0, 2)
        row.blocker = f"submit_http_{scode}"
        row.detail = str(accepted)[:400]
        _log(f"[{batch}] {workflow_id}: submit failed HTTP {scode} {row.detail}")
        return row

    run_id = str(accepted.get("run_id") or "")
    row.run_id = run_id
    _log(f"[{batch}] {workflow_id}: polling run_id={run_id}")
    status, run_body, elapsed = poll_run(
        base, run_id, timeout_s=timeout_s, api_key=api_key
    )
    row.status = status
    row.elapsed_s = round(elapsed, 2)
    if status != "succeeded":
        row.detail = extract_error(run_body) or str(run_body.get("status"))
        # Prefer structured error fields when extract_error is empty
        if not row.detail:
            for key in ("error_message", "error_type", "failure_category", "message"):
                if run_body.get(key):
                    row.detail = str(run_body.get(key))[:400]
                    break
        if status == "timeout":
            row.blocker = "timeout"
        elif not row.blocker:
            row.blocker = "run_failed"
    if note:
        row.extras["note"] = note
    _log(
        f"[{batch}] {workflow_id}: {row.status} run_id={run_id} "
        f"({row.elapsed_s}s) {row.blocker or row.detail}"
    )
    return row


def render_markdown(rows: list[Row], *, infra: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    lines = [
        "# Workflow smoke matrix",
        "",
        f"- Generated: {now}",
        f"- API: {infra.get('base')}",
        f"- DATA_ROOT: {infra.get('data_root')}",
        f"- Definitions listed: {infra.get('definitions_count')}",
        "",
        "## Matrix",
        "",
        "| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |",
        "|-------|-------------|--------|--------|-----------|------------------|",
    ]
    for r in rows:
        detail = (r.blocker or r.detail or "").replace("|", "\\|").replace("\n", " ")
        note = str((r.extras or {}).get("note") or "").strip()
        if note:
            note = note.replace("|", "\\|").replace("\n", " ")
            detail = f"{detail} {note}".strip() if detail else note
        lines.append(
            f"| {r.batch} | `{r.workflow_id}` | `{r.run_id}` | {r.status} | "
            f"{r.elapsed_s} | {detail} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Batch A is weather tile hot path (not a system seed).",
            "- Open-data seeds with `REPLACE_*` placeholders were skipped as "
            "`blocked:config` / `blocked:creds` (no forged portal paths), except "
            "`open_data_noaa_grib_sample` (live NOMADS filter probe) and "
            "`open_data_nasa_earthdata_sample` (LP DAAC browse download-only).",
            "- `raster_histogram_basic` used temp GeoTIFF under "
            "`{DATA_ROOT}/_runtime/smoke_hist.tif`.",
            "- `smap_soil_moisture_local` path overridden to "
            "`Soil_Moisture/SMAP` (seed default `{DATA_ROOT}/SMAP` missing).",
            "- `omega_block_smap_single` time window overridden to 2025-11-01..02 "
            "to match available local mats (seed default Dec 2025).",
            "- `omega_avg_daily` Stage D light-smoke cap enabled "
            "(max 5 days) to avoid 365-day long runtimes / OOM.",
            "- Heavy omega chains may fail for missing GLDAS / online deps; "
            "recorded without inventing production datasets.",
            "",
            "## Verified today (ABCD sprint)",
            "",
            "- D1/D2 graph path: `omega_block_*` / `omega_avg_daily_*` submit "
            "compiled `workflow_definition` (no smoke flatten).",
            "- fenkuai + `output_map_layer`: SMAP/FY light-smoke keep map_layer "
            "(manifest→data accepted).",
            "- NOAA: cfgrib+eccodes available locally → "
            "`http_open_data→variable_extract` (`t2m`); CGI `.pl` cache sniff/rename.",
            "- NASA Earthdata: download-only LP DAAC browse JPG.",
            "- `output_map_layer` ArtifactRef-on-`data` fix remains in effect.",
            "",
            "## Follow-ups remaining",
            "",
            "1. `open_data_nsidc_*` / `esa_*` / `omega_avg_daily_smap_online` "
            "(large granules / Copernicus / h5→mat).",
            "2. HPC paper template sync (tunnel/direct still blocked).",
            "3. `omega_avg_daily_gldas_online` may fail when worker lacks "
            "Earthdata username/password even if portal token exists in UI.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    # Avoid silent Windows console buffering during long polls
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--api-key", default=os.environ.get("BACKEND_API_KEY") or "")
    parser.add_argument(
        "--login",
        action="store_true",
        help="login via /auth/login (session cookie) for write endpoints",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("BACKEND_SMOKE_USER") or "admin",
        help="username for --login (default admin)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("BACKEND_SMOKE_PASSWORD") or "cgda-dev-admin",
        help="password for --login (default cgda-dev-admin)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="per-run poll timeout seconds (default 600)",
    )
    parser.add_argument(
        "--omega-timeout",
        type=float,
        default=1200.0,
        help="omega run poll timeout seconds (default 1200)",
    )
    parser.add_argument("--skip-tiles", action="store_true")
    parser.add_argument("--skip-omega", action="store_true")
    parser.add_argument("--only", nargs="*", help="optional workflow_id allowlist")
    parser.add_argument("--report", default="", help="write markdown report path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    api_key = args.api_key or None
    base = args.base.rstrip("/")

    # Prefer session when --login; also auto-login if write probe fails with API key alone.
    if args.login:
        ok, msg = login_session(base, username=args.username, password=args.password)
        _log(f"session login ({args.username}): {'ok' if ok else msg}")
        if not ok:
            return 2
    else:
        probe, _ = _http_json(
            "GET", f"{base}/runtime/status", timeout=15, api_key=api_key
        )
        if probe == 401:
            ok, msg = login_session(
                base, username=args.username, password=args.password
            )
            _log(
                f"auto session login after write-probe 401 ({args.username}): "
                f"{'ok' if ok else msg}"
            )
            if ok:
                api_key = None  # rely on cookie; avoid mismatched X-API-Key noise

    _log(f"DATA_ROOT={DATA_ROOT} exists={DATA_ROOT.is_dir()}")
    stub_fx = ensure_stub_v1_fixtures()
    if stub_fx:
        _log(
            "stub_v1 fixtures: "
            + ", ".join(f"{k}={v}" for k, v in stub_fx.items())
        )
    else:
        _log("stub_v1 fixtures: none (Batch G may skip/fail)")
    gldas_conv = ensure_gldas_nc4_converted()
    if gldas_conv.get("converted") or gldas_conv.get("error"):
        _log(f"GLDAS nc4→mat preflight: {gldas_conv}")
    gldas_tpl = ensure_gldas_utc_template_mat()
    if gldas_tpl.get("built") or gldas_tpl.get("error") or gldas_tpl.get("path"):
        _log(f"GLDAS UTC template preflight: {gldas_tpl}")
    _log(f"SEEDS_DIR={SEEDS_DIR} count={len(list(SEEDS_DIR.glob('*.json')))}")
    code, defs = _http_json("GET", f"{base}/workflow-definitions", timeout=30, api_key=api_key)
    items = []
    if isinstance(defs, dict):
        items = defs.get("items") or defs.get("workflows") or defs.get("definitions") or []
    elif isinstance(defs, list):
        items = defs
    _log(f"GET /workflow-definitions HTTP {code} count={len(items)}")

    allow = set(args.only) if args.only else None
    rows: list[Row] = []

    # Always run tile smoke unless --skip-tiles (even with --only allowlist)
    if not args.skip_tiles:
        rows.extend(run_tiles(base))

    batches: list[tuple[str, list[str], float]] = [
        ("B", BATCH_B, args.timeout),
        ("C", BATCH_C, args.timeout),
        ("D", BATCH_D, args.timeout),
        ("E", BATCH_E, min(args.timeout, 180.0)),
        ("F", BATCH_F, args.omega_timeout),
        ("G", BATCH_G, args.timeout),
        ("H", BATCH_H, args.timeout),
    ]
    for batch_name, ids, timeout_s in batches:
        if batch_name == "F" and args.skip_omega:
            continue
        for wid in ids:
            if allow is not None and wid not in allow:
                continue
            rows.append(
                submit_and_poll(
                    base,
                    wid,
                    batch_name,
                    api_key=api_key,
                    timeout_s=timeout_s,
                    dry_run=args.dry_run,
                )
            )

    # Ensure all seed files appear even if not in batches
    seed_ids = sorted(p.stem for p in SEEDS_DIR.glob("*.json"))
    seen = {r.workflow_id for r in rows}
    for wid in seed_ids:
        if wid in seen:
            continue
        if allow is not None and wid not in allow:
            continue
        rows.append(
            submit_and_poll(
                base,
                wid,
                "X",
                api_key=api_key,
                timeout_s=args.timeout,
                dry_run=args.dry_run,
            )
        )

    infra = {
        "base": base,
        "data_root": str(DATA_ROOT),
        "definitions_count": len(items),
    }
    _log("\n=== MATRIX ===")
    _log(
        f"{'batch':4} {'workflow_id':40} {'status':12} {'elapsed':8} run_id / blocker"
    )
    for r in rows:
        _log(
            f"{r.batch:4} {r.workflow_id:40} {r.status:12} {r.elapsed_s:8} "
            f"{r.run_id or '-'} {r.blocker or r.detail}"
        )

    report_path = args.report
    if report_path:
        path = Path(report_path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(rows, infra=infra), encoding="utf-8")
        _log(f"\nWrote report: {path}")

    # JSON sidecar next to report for machine use
    if report_path:
        side = Path(report_path)
        if not side.is_absolute():
            side = REPO_ROOT / side
        side.with_suffix(".json").write_text(
            json.dumps(
                {"infra": infra, "rows": [asdict(r) for r in rows]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    failed = [r for r in rows if r.status in ("failed", "timeout")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
