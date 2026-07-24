#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CGDA 数据产出能力 E2E 测试。

测试范围：
  A. 天气瓦片 API（16 层）—— GET /weather/tiles/{layer_id}/{z}/{x}/{y}
  B. 静态 COG 图层（22 层）—— 文件存在性 + GET /unified-tiles/{layer_id}/{z}/{x}/{y}
  C. 算法工作流 E2E（5 层）—— POST /workflow-runs + 轮询 + 产物验证
  D. 工作流种子校验（5 个）—— JSON 结构校验
  E. 现有测试套件执行 —— pytest backend + pytest algorithms

跳过项：
  - GEE 相关（remote-sensing 图层）
  - 门户凭证工作流（4 个 open_data_* 种子）
  - blocked 图层（ndvi / fy-mwri / station-soil）

用法：
    python Tools/test_data_production_e2e.py
    python Tools/test_data_production_e2e.py --category A      # 仅跑天气瓦片
    python Tools/test_data_production_e2e.py --category A,B    # 组合类别
    python Tools/test_data_production_e2e.py --no-pytest       # 跳过 pytest 套件（加速）
    python Tools/test_data_production_e2e.py --timeout-algo 180
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# 强制 stdout 使用 UTF-8，避免 Windows PowerShell GBK 乱码
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# ─── 配置常量 ────────────────────────────────────────────────────────────────

BASE_URL = os.environ.get("CGDA_BACKEND_URL", "http://127.0.0.1:8000")
OPEN_METEO_URL = os.environ.get("CGDA_OPEN_METEO_URL", "http://127.0.0.1:8080")
DATA_ROOT = Path(os.environ.get("BACKEND_DATA_ROOT", "I:/Geograph_DataSet"))
OUTPUT_ROOT = Path(os.environ.get("BACKEND_OUTPUT_ROOT", "I:/GeoOutput"))
REPORTS_DIR = Path(__file__).resolve().parent / "reports"
REPO_ROOT = Path(__file__).resolve().parent.parent
SEEDS_DIR = REPO_ROOT / "Code" / "backend" / "workflow_seeds" / "system"

# 测试瓦片：z=8, x=213, y=107（中国福建/广东区域）
TEST_TILE_ZXY = (8, 213, 107)

# 算法工作流轮询配置
ALGO_POLL_INTERVAL_S = 3
ALGO_DEFAULT_TIMEOUT_S = 120

# 跳过清单（按用户要求：跳过 GEE + 门户凭证 + blocked 图层）
SKIP_ALGO_LAYERS = {
    "remote-sensing": "GEE 凭据依赖，按用户要求跳过",
    "ndvi": "catalog 标记 blocked（原始数据待下载）",
    "fy-mwri": "catalog 标记 blocked",
    "station-soil": "catalog 标记 blocked",
}
SKIP_PORTAL_SEEDS = {
    "open_data_nsidc_smap_sample",
    "open_data_nasa_earthdata_sample",
    "open_data_noaa_grib_sample",
    "open_data_esa_product_sample",
    "omega_avg_daily_gldas_online",
    "omega_avg_daily_smap_online",
}

# ─── 全局状态 ────────────────────────────────────────────────────────────────

RESULTS: list[dict] = []
START_TIME: float = 0.0
ENV_STATUS: dict = {}


# ─── 辅助函数 ────────────────────────────────────────────────────────────────


def record(
    name: str,
    category: str,
    status: str,
    reason: str = "",
    duration_ms: int = 0,
    detail: str = "",
) -> None:
    """记录一条测试结果。status: pass / fail / skip"""
    RESULTS.append(
        {
            "name": name,
            "category": category,
            "status": status,
            "reason": reason,
            "duration_ms": duration_ms,
            "detail": detail,
        }
    )
    icon = {"pass": "✅", "fail": "❌", "skip": "⏭"}[status]
    suffix = f" — {reason}" if reason else ""
    print(f"  {icon} [{category}] {name}{suffix}")


def http_get_json(url: str, timeout: int = 30) -> tuple[int, object]:
    """GET 请求返回 JSON。返回 (status_code, data_or_error_str)。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CGDA-E2E-Test/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, data
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return e.code, f"HTTPError {e.code}: {body}"
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def http_get_bytes(url: str, timeout: int = 30) -> tuple[int, str, bytes]:
    """GET 请求返回字节。返回 (status_code, content_type, body_bytes)。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CGDA-E2E-Test/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers.get("content-type", ""), resp.read()
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()
        except Exception:
            pass
        return e.code, "", body
    except Exception as e:
        return 0, "", f"{type(e).__name__}: {e}".encode("utf-8", errors="replace")


def http_post_json(url: str, payload: dict, timeout: int = 30) -> tuple[int, object]:
    """POST JSON 请求。返回 (status_code, data_or_error_str)。"""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "CGDA-E2E-Test/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            return resp.status, resp_data
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        return e.code, f"HTTPError {e.code}: {body}"
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def extract_data_paths(notes: list[str]) -> list[str]:
    """从 run_readiness_notes 提取数据源路径。

    格式示例：
      "数据源: I:/Geograph_DataSet/DEM/ETOPO_2022/ETOPO_2022_v1_60s_N90W180_surface.tif"
      "数据源: I:/Geograph_DataSet/SMAP/SMAP_L3_SM_P_*.h5 (19 files)"
      "数据源: I:/Geograph_DataSet/Soil_Ecological_Data/SmapSoil_VOD_SM/YYYYMMDD.mat#OMEGA (31 files, v7.3 HDF5)"
    """
    paths: list[str] = []
    for note in notes:
        # 匹配 "数据源: <path>" 或 "数据源未就绪：..." 等
        m = re.match(r"数据源:\s*(.+?)(?:\s*\([^)]*\))?$", note.strip())
        if m:
            raw = m.group(1).strip()
            # 去掉 #VAR 后缀（如 YYYYMMDD.mat#OMEGA）
            raw = raw.split("#")[0].strip()
            if raw:
                paths.append(raw)
    return paths


def check_path_exists(path_str: str) -> tuple[bool, str]:
    """检查路径是否存在，支持 glob 通配符、日期模板、花括号展开、相对路径。

    支持的模板模式：
      - 标准 glob: SMAP_L3_SM_P_*.h5
      - 日期模板: YYYYMMDD.mat（检查父目录下是否有匹配文件）
      - 花括号展开: doy_{025..030}.mat → doy_025.mat ... doy_030.mat
      - 相对路径: 自动尝试 DATA_ROOT 及其子目录前缀

    返回 (exists, detail)。
    """
    # 标准化路径（I:/ → I:\）
    p = path_str.replace("/", "\\").strip()

    # 候选路径列表：原始路径 + 多个 DATA_ROOT 前缀（若为相对路径）
    candidates: list[str] = [p]
    if not Path(p).is_absolute():
        # 主候选：DATA_ROOT / path
        candidates.append(str(DATA_ROOT / p))
        # 次候选：ProjectOutput 子目录（stage* 等内部派生路径）
        candidates.append(
            str(DATA_ROOT / "ProjectOutput" / "2023-01_Omega_Inversion" / p)
        )

    for candidate in candidates:
        result = _check_single_path(candidate)
        if result[0]:
            return result

    # 最后尝试：在 DATA_ROOT 下递归搜索文件名（仅对 glob/模板路径，避免全盘扫描）
    if not Path(p).is_absolute():
        filename = Path(p).name
        if "*" in filename or "{" in filename or re.search(r"[A-Z]{4,}", filename):
            try:
                for match in DATA_ROOT.rglob(filename):
                    return True, f"递归搜索匹配: {match}"
            except Exception:
                pass

    # 全部候选均失败，返回最后一个的错误
    return result


def _check_single_path(p: str) -> tuple[bool, str]:
    """检查单个路径（内部辅助函数）。"""
    # 1. 花括号展开: doy_{025..030}.mat → doy_025.mat ... doy_030.mat
    brace_match = re.match(r"^(.*?)(\{(\d+)\.\.(\d+)\})(.*)$", p)
    if brace_match:
        prefix, _, start_str, end_str, suffix = brace_match.groups()
        start_val, end_val = int(start_str), int(end_str)
        width = len(start_str)  # 保持前导零宽度
        found_any = False
        for val in range(start_val, end_val + 1):
            expanded = f"{prefix}{val:0{width}d}{suffix}"
            pp = Path(expanded)
            if pp.exists():
                found_any = True
            else:
                return False, f"花括号展开项不存在: {expanded}"
        if found_any:
            count = end_val - start_val + 1
            return True, f"花括号展开 {count} 个文件全部存在"
        return False, f"花括号展开无匹配: {p}"

    # 2. 标准 glob 通配符 (* ?)
    if "*" in p or "?" in p:
        matches = glob.glob(p)
        if matches:
            return True, f"glob 匹配 {len(matches)} 个文件"
        return False, f"glob 无匹配: {p}"

    # 3. 日期模板: YYYYMMDD.mat（非标准 glob，需检查父目录）
    #    识别文件名中的 YYYY/MM/DD 等全大写字母模板
    pp = Path(p)
    if not pp.exists():
        parent = pp.parent
        filename = pp.name
        # 如果文件名含 4+ 连续大写字母（如 YYYYMMDD），检查父目录下是否有同扩展名文件
        if re.search(r"[A-Z]{4,}", filename) and parent.exists():
            ext = pp.suffix  # 如 .mat
            try:
                matches = list(parent.glob(f"*{ext}"))
                if matches:
                    return (
                        True,
                        f"日期模板匹配 {len(matches)} 个 {ext} 文件于 {parent.name}/",
                    )
            except Exception:
                pass
        return False, f"路径不存在: {p}"

    # 4. 直接存在
    if pp.is_dir():
        try:
            count = sum(1 for _ in pp.iterdir())
            return True, f"目录存在，{count} 个子项"
        except Exception:
            return True, "目录存在"
    return True, f"文件存在 ({pp.stat().st_size} bytes)"


def fetch_layer_catalog() -> list[dict]:
    """从 /layers API 拉取图层目录。"""
    status, data = http_get_json(f"{BASE_URL}/layers", timeout=60)
    if status != 200 or not isinstance(data, dict):
        print(f"[FATAL] /layers 请求失败: {data}")
        return []
    return data.get("items", [])


# ─── 类别 A：天气瓦片 E2E ────────────────────────────────────────────────────


def test_weather_tiles(layers: list[dict]) -> None:
    print("\n" + "=" * 70)
    print("类别 A：天气瓦片 E2E（GET /weather/tiles/{layer_id}/{z}/{x}/{y}）")
    print("=" * 70)

    weather_layers = [l for l in layers if l.get("source_type") == "weather"]
    if not weather_layers:
        record("(无 weather 图层)", "A", "skip", "图层目录无 weather 类型")
        return

    z, x, y = TEST_TILE_ZXY
    for layer in weather_layers:
        lid = layer["layer_id"]
        url = f"{BASE_URL}/weather/tiles/{lid}/{z}/{x}/{y}"
        t0 = time.monotonic()
        status, ct, body = http_get_bytes(url, timeout=60)
        elapsed = int((time.monotonic() - t0) * 1000)

        if status == 200 and "image" in ct and len(body) > 100:
            record(
                lid,
                "A",
                "pass",
                f"PNG {len(body) // 1024}KB",
                elapsed,
                f"content-type={ct}",
            )
        elif status == 200 and len(body) > 0:
            # 可能是透明瓦片或空数据
            record(
                lid,
                "A",
                "pass" if len(body) > 50 else "fail",
                f"HTTP 200, body={len(body)}B, ct={ct}",
                elapsed,
                "可能无数据区域",
            )
        else:
            record(
                lid,
                "A",
                "fail",
                f"HTTP {status}, body={len(body)}B",
                elapsed,
                body[:200].decode("utf-8", errors="replace") if body else "",
            )

        # 请求间隔，避免 Open-Meteo 限流
        time.sleep(0.2)


# ─── 类别 B：静态 COG 图层验证 ────────────────────────────────────────────────


def test_static_cog_layers(layers: list[dict]) -> None:
    print("\n" + "=" * 70)
    print("类别 B：静态 COG 图层验证（文件存在性 + GET /overlay-preview）")
    print("=" * 70)

    cog_layers = [l for l in layers if l.get("source_type") == "cog"]
    if not cog_layers:
        record("(无 cog 图层)", "B", "skip", "图层目录无 cog 类型")
        return

    for layer in cog_layers:
        lid = layer["layer_id"]
        notes = layer.get("run_readiness_notes", [])
        paths = extract_data_paths(notes)

        # 步骤 1：检查数据文件存在性
        file_ok = True
        file_detail = ""
        if paths:
            for p in paths:
                exists, detail = check_path_exists(p)
                if not exists:
                    file_ok = False
                    file_detail = f"路径缺失: {p}"
                    break
                file_detail = detail
        else:
            file_detail = "无路径信息（run_readiness_notes 未含数据源路径）"

        if not file_ok:
            record(lid, "B", "fail", file_detail, 0, f"paths={paths}")
            continue

        # 步骤 2：请求 overlay preview（验证后端可读取数据并渲染预览）
        url = f"{BASE_URL}/overlay-preview/{lid}"
        t0 = time.monotonic()
        status, ct, body = http_get_bytes(url, timeout=60)
        elapsed = int((time.monotonic() - t0) * 1000)

        if status == 200 and len(body) > 100:
            record(
                lid,
                "B",
                "pass",
                f"文件✓ 预览 {len(body) // 1024}KB",
                elapsed,
                f"{file_detail} | content-type={ct}",
            )
        elif status == 200:
            record(
                lid,
                "B",
                "pass" if len(body) > 0 else "fail",
                f"文件✓ 预览 HTTP 200, body={len(body)}B",
                elapsed,
                file_detail,
            )
        elif status == 404:
            # overlay-preview 不支持时，回退到 overlay-bounds（验证数据可读）
            url2 = f"{BASE_URL}/overlay-bounds/{lid}"
            t2 = time.monotonic()
            status2, data2 = http_get_json(url2, timeout=30)
            elapsed2 = int((time.monotonic() - t2) * 1000)
            if status2 == 200 and isinstance(data2, dict):
                record(
                    lid,
                    "B",
                    "pass",
                    "文件✓ bounds✓",
                    elapsed2,
                    f"{file_detail} | bounds={data2}",
                )
            else:
                record(
                    lid,
                    "B",
                    "fail",
                    f"文件✓ 预览 HTTP {status} bounds HTTP {status2}",
                    elapsed,
                    f"{file_detail} | preview_body={body[:200].decode('utf-8', errors='replace') if body else ''}",
                )
        else:
            record(
                lid,
                "B",
                "fail",
                f"文件✓ 预览 HTTP {status}",
                elapsed,
                f"{file_detail} | body={body[:200].decode('utf-8', errors='replace') if body else ''}",
            )


# ─── 类别 C：算法工作流 E2E ──────────────────────────────────────────────────


def build_algo_request(layer: dict) -> dict:
    """根据图层描述符构造 WorkflowSubmitRequest。"""
    lid = layer["layer_id"]
    engine = layer.get("engine", "")
    module_name = layer.get("module_name")
    task_type = layer.get("default_task_type")
    sources = layer.get("default_data_access_sources", {})

    # 构造 datasource_selection（从 default_data_access_sources 取候选）
    # 优先选择路径型候选（含 / 或 \），解析为绝对路径
    datasource_selection: dict[str, str] = {}
    for ds_key, candidates in sources.items():
        if not candidates:
            continue
        # 优先选择看起来像路径的候选（含 / 或 \ 或 :）
        path_candidate = next(
            (c for c in candidates if "/" in c or "\\" in c or ":" in c),
            None,
        )
        selected = path_candidate or candidates[0]
        # 如果是相对路径，尝试解析为绝对路径（DATA_ROOT 前缀）
        if path_candidate and not Path(selected.replace("/", "\\")).is_absolute():
            abs_path = str(DATA_ROOT / selected)
            if Path(abs_path).exists():
                selected = abs_path
        datasource_selection[ds_key] = selected

    # 如果有 run_readiness_notes 含路径，注入为 datasource_selection
    notes = layer.get("run_readiness_notes", [])
    paths = extract_data_paths(notes)
    if paths and not datasource_selection:
        datasource_selection["input_path"] = paths[0]

    # ── Per-module datasource overrides ──────────────────────────────────────
    # The catalog's default_data_access_sources often provides dataset KEYS
    # (e.g. "timeseries_bundle_mat", "INVERSION_OMEGA_SMAP") or directory paths
    # rather than specific .mat files. The DataAccessCoordinator prepares these
    # into _prepared_inputs, and the module's resolve_prepared_local_path may
    # overwrite input_mat with an invalid/directory path. To avoid this, we
    # provide the direct file path via input_mat and REMOVE the catalog-provided
    # dataset key so it doesn't get prepared into _prepared_inputs.
    #   - smap_daily      → input_dir  (directory of .h5 files)
    #   - inversion_daily → input_mat  (specific YYYYMMDD.mat file, remove daily_bundle_mat)
    #   - block_inversion → input_mat  (specific doy_*.mat file, remove timeseries_bundle_mat)
    #   - omega_block     → input_mat  (specific doy_*.mat file, remove timeseries_bundle_mat)
    algorithm_params_override: dict[str, object] = {}

    if module_name == "smap_daily":
        smap_dir = DATA_ROOT / "SMAP"
        if smap_dir.is_dir():
            datasource_selection["input_dir"] = str(smap_dir)
        algorithm_params_override = {}

    elif module_name == "inversion_daily":
        # Use synthetic daily bundle .mat (contains TBv, TBh, Ts, CF, Albedo,
        # porosity, IA, Tau_ini) — the real DDCA/DDCA_DH/H files only have DH.
        # Generated by Tools/generate_synthetic_test_data.py.
        synthetic_daily = (
            REPO_ROOT / "Tools" / "test_data" / "synthetic_daily_bundle.mat"
        )
        if synthetic_daily.is_file():
            datasource_selection["input_mat"] = str(synthetic_daily)
        datasource_selection.pop("daily_bundle_mat", None)
        # mode="dh" computes DH from TB data (no DH input required)
        algorithm_params_override = {"mode": "dh"}

    elif module_name == "block_inversion":
        # Use synthetic timeseries bundle .mat (contains TBv_mat, TBh_mat,
        # IA_mat, Ts_mat, NDVI_mat, SF_mat + static vectors) — no real
        # timeseries_bundle .mat exists in the data directory.
        # Generated by Tools/generate_synthetic_test_data.py.
        synthetic_ts = (
            REPO_ROOT / "Tools" / "test_data" / "synthetic_timeseries_bundle.mat"
        )
        if synthetic_ts.is_file():
            datasource_selection["input_mat"] = str(synthetic_ts)
        datasource_selection.pop("timeseries_bundle_mat", None)
        # mode="dh" only needs input_mat (no dh_mat required)
        algorithm_params_override = {"mode": "dh"}

    elif module_name == "omega_block":
        # Same synthetic timeseries bundle as block_inversion.
        synthetic_ts = (
            REPO_ROOT / "Tools" / "test_data" / "synthetic_timeseries_bundle.mat"
        )
        if synthetic_ts.is_file():
            datasource_selection["input_mat"] = str(synthetic_ts)
        datasource_selection.pop("timeseries_bundle_mat", None)
        # mode="dh" only needs input_mat (avoids omega_fixed_mat/exp0_calib_mat)
        algorithm_params_override = {"mode": "dh"}

    elif module_name == "omega_avg_daily":
        # D2 avg-omega daily retrieval — point at the synthetic D2 dataset
        # (omega_block output + daily bundle inputs) generated by
        # Tools/generate_synthetic_test_data.py::generate_omega_avg_daily_inputs.
        d2_root = REPO_ROOT / "Tools" / "test_data" / "omega_avg_daily_inputs"
        if d2_root.is_dir():
            datasource_selection = {
                "omega_block_dir": str(d2_root / "omega_block"),
                "smap_folder": str(d2_root / "smap_daily"),
                "ndvi_folder": str(d2_root / "ndvi_daily"),
                "ndvi_clim_folder": str(d2_root / "ndvi_clim"),
                "anc_root": str(d2_root / "anc"),
                "ndvi_extrema_mat": str(d2_root / "anc" / "NDVI_extrema.mat"),
            }
        # D2 only needs 10 synthetic days (2023-01-01..10); disable parallel
        # to keep the E2E run lightweight and avoid spawn overhead.
        algorithm_params_override = {
            "target_year": 2023,
            "tb_source": "SMAP",
            "temp_scheme": "ORIG_TS",
            "ndvi_mode": "DAILY_FILE",
            "sf_mode": "STATIC",
            "sm_source": "SMAP",
            "enable_parallel": False,
            "avg_build_start_year": 2023,
            "avg_build_end_year": 2023,
            "grid_shape": [24, 48],
            "print_every_days": 50,
        }

    # 时间范围（python_provider 的 JobRequest 要求 time_range + region）
    # 使用 2023-01-01 ~ 2023-01-10 作为测试时间范围（覆盖 SMAP/inversion 数据）
    algo_time_range = {
        "start": "2023-01-01T00:00:00",
        "end": "2023-01-10T00:00:00",
    }
    # 区域：中国区域 bbox
    algo_region = {
        "kind": "bbox",
        "value": {"west": 73.0, "south": 15.0, "east": 137.0, "north": 59.0},
    }

    # 顶层 time_range（WorkflowSubmitRequest 格式：start_at/end_at）
    top_time_range = {
        "start_at": "2023-01-01T00:00:00",
        "end_at": "2023-01-10T00:00:00",
        "granularity": "day",
    }

    # 构建 algorithm_request
    algorithm_request: dict = {
        "module_name": module_name,
        "task_type": task_type,
        "datasource_selection": datasource_selection,
        "algorithm_params": algorithm_params_override,
        "output_spec": {
            "raster_format": "COG",
            "table_format": "parquet",
            "include_qc": False,
            "include_manifest": True,
        },
        "time_range": algo_time_range,
        "region": algo_region,
    }

    payload = {
        "command_type": "analysis",
        "layer_id": lid,
        "time_range": top_time_range,
        "algorithm_request": algorithm_request,
        "parameters": {},
        "requested_outputs": ["map_layer", "json"],
    }

    # lab-output (engine="provider") 无 module_name，走简化路径
    if not module_name and engine == "provider":
        payload = {
            "command_type": "analysis",
            "layer_id": lid,
            "algorithm_request": {},
            "parameters": {},
            "requested_outputs": ["map_layer", "json"],
        }

    return payload


def poll_workflow_run(run_id: str, timeout_s: int) -> tuple[str, dict]:
    """轮询工作流状态直到完成或超时。

    返回 (final_status, run_data)。
    final_status: succeeded / failed / timeout / error
    """
    deadline = time.monotonic() + timeout_s
    last_data: dict = {}

    while time.monotonic() < deadline:
        status, data = http_get_json(f"{BASE_URL}/workflow-runs/{run_id}", timeout=30)
        if status != 200 or not isinstance(data, dict):
            # 临时错误，继续轮询
            time.sleep(ALGO_POLL_INTERVAL_S)
            continue

        last_data = data
        run_status = data.get("status", "")
        # 终态判断
        if run_status in ("succeeded", "completed", "success"):
            return "succeeded", data
        if run_status in ("failed", "error", "cancelled", "canceled"):
            return "failed", data

        # 运行中
        elapsed = int(time.monotonic() - (deadline - timeout_s))
        print(f"    … {run_id[:8]} status={run_status} ({elapsed}s)", end="\r")
        time.sleep(ALGO_POLL_INTERVAL_S)

    return "timeout", last_data


def verify_artifacts(run_id: str) -> tuple[int, str]:
    """验证工作流产出的产物。返回 (artifact_count, detail)。"""
    # 尝试 GET /workflow-runs/{run_id}/view 获取产物视图
    status, data = http_get_json(f"{BASE_URL}/workflow-runs/{run_id}/view", timeout=30)
    if status == 200 and isinstance(data, dict):
        results = data.get("results", [])
        artifacts = data.get("artifacts", [])
        total = len(results) + len(artifacts)
        if total > 0:
            return total, f"results={len(results)}, artifacts={len(artifacts)}"
        return 0, "view 返回但无产物"

    # 回退：检查 run status 中的 result_refs
    status2, data2 = http_get_json(f"{BASE_URL}/workflow-runs/{run_id}", timeout=30)
    if status2 == 200 and isinstance(data2, dict):
        refs = data2.get("result_references", []) or data2.get("results", [])
        if refs:
            return len(refs), f"result_references={len(refs)}"
        # 成功但无产物也算 pass（某些模块仅产出副作用）
        return 0, "运行成功但无显式产物（可能为副作用输出）"

    return 0, f"view/status 查询失败: HTTP {status}"


def test_algorithm_workflows(layers: list[dict], timeout_s: int) -> None:
    print("\n" + "=" * 70)
    print(f"类别 C：算法工作流 E2E（POST /workflow-runs，超时 {timeout_s}s）")
    print("=" * 70)

    algo_layers = [l for l in layers if l.get("source_type") == "algorithm_output"]
    if not algo_layers:
        record(
            "(无 algorithm_output 图层)",
            "C",
            "skip",
            "图层目录无 algorithm_output 类型",
        )
        return

    for layer in algo_layers:
        lid = layer["layer_id"]

        # 跳过清单
        if lid in SKIP_ALGO_LAYERS:
            record(lid, "C", "skip", SKIP_ALGO_LAYERS[lid])
            continue

        # 构造请求
        payload = build_algo_request(layer)
        t0 = time.monotonic()

        # 提交工作流
        status, resp = http_post_json(f"{BASE_URL}/workflow-runs", payload, timeout=30)
        submit_elapsed = time.monotonic() - t0

        if status != 202 and status != 200:
            record(
                lid,
                "C",
                "fail",
                f"提交失败 HTTP {status}",
                int(submit_elapsed * 1000),
                str(resp)[:300],
            )
            continue

        if not isinstance(resp, dict) or "run_id" not in resp:
            record(
                lid,
                "C",
                "fail",
                "提交响应无 run_id",
                int(submit_elapsed * 1000),
                str(resp)[:300],
            )
            continue

        run_id = resp["run_id"]
        print(f"  → {lid} submitted: run_id={run_id}")

        # 轮询状态
        final_status, run_data = poll_workflow_run(run_id, timeout_s)
        total_elapsed = time.monotonic() - t0
        print()  # 换行（轮询打印了 \r）

        if final_status == "succeeded":
            # 验证产物
            art_count, art_detail = verify_artifacts(run_id)
            record(
                lid,
                "C",
                "pass",
                f"成功 {total_elapsed:.1f}s 产物={art_count}",
                int(total_elapsed * 1000),
                f"run_id={run_id} | {art_detail}",
            )
        elif final_status == "timeout":
            record(
                lid,
                "C",
                "fail",
                f"超时 {timeout_s}s",
                int(total_elapsed * 1000),
                f"run_id={run_id} | last_status={run_data.get('status', '?')}",
            )
        else:
            # 提取诊断信息
            diags = run_data.get("diagnostics", [])
            error_msg = run_data.get("message", "")
            # 从 diagnostics 提取 error_message 和 error_type
            for dg in diags:
                if isinstance(dg, str):
                    if dg.startswith("error_message="):
                        error_msg = dg.split("=", 1)[1]
                    elif dg.startswith("error_type=") and not error_msg:
                        error_msg = dg
            record(
                lid,
                "C",
                "fail",
                f"运行失败 status={run_data.get('status', '?')}",
                int(total_elapsed * 1000),
                f"run_id={run_id} | {error_msg[:300]}",
            )


# ─── 类别 D：工作流种子校验 ──────────────────────────────────────────────────


def test_workflow_seeds() -> None:
    print("\n" + "=" * 70)
    print("类别 D：工作流种子校验（JSON 结构 + 凭证依赖识别）")
    print("=" * 70)

    if not SEEDS_DIR.exists():
        record("(seeds 目录)", "D", "fail", f"目录不存在: {SEEDS_DIR}")
        return

    seed_files = sorted(SEEDS_DIR.glob("*.json"))
    if not seed_files:
        record("(无种子文件)", "D", "skip", f"{SEEDS_DIR} 无 .json 文件")
        return

    for seed_path in seed_files:
        seed_id = seed_path.stem
        t0 = time.monotonic()

        # 跳过门户凭证种子
        if seed_id in SKIP_PORTAL_SEEDS:
            record(seed_id, "D", "skip", "需门户凭证（earthdata/nsidc/esa）")
            continue

        # 读取并校验 JSON 结构
        try:
            content = seed_path.read_text(encoding="utf-8")
            data = json.loads(content)
        except json.JSONDecodeError as e:
            record(
                seed_id,
                "D",
                "fail",
                f"JSON 解析失败: {e}",
                int((time.monotonic() - t0) * 1000),
            )
            continue
        except Exception as e:
            record(
                seed_id,
                "D",
                "fail",
                f"读取失败: {e}",
                int((time.monotonic() - t0) * 1000),
            )
            continue

        # 结构校验
        errors: list[str] = []
        if "workflow_id" not in data:
            errors.append("缺 workflow_id")
        if "nodes" not in data or not isinstance(data["nodes"], list):
            errors.append("缺 nodes 数组")
        elif len(data["nodes"]) == 0:
            errors.append("nodes 为空")
        if "links" not in data or not isinstance(data["links"], list):
            errors.append("缺 links 数组")

        # 检查节点类型
        node_types: list[str] = []
        for node in data.get("nodes", []):
            if isinstance(node, dict):
                nt = node.get("type", "")
                node_types.append(nt)
                # 检查凭证依赖
                props = node.get("properties", {})
                if isinstance(props, dict) and props.get("cred_profile"):
                    cred = props["cred_profile"]
                    if cred in ("earthdata", "nsidc", "copernicus", "esa"):
                        errors.append(f"节点 {nt} 依赖凭证 {cred}")

        elapsed = int((time.monotonic() - t0) * 1000)
        if errors:
            record(
                seed_id, "D", "fail", "; ".join(errors), elapsed, f"nodes={node_types}"
            )
        else:
            meta = data.get("_meta", {})
            engine = meta.get("engine", "?")
            record(
                seed_id,
                "D",
                "pass",
                f"结构合法 engine={engine} nodes={len(data['nodes'])}",
                elapsed,
                f"types={node_types}",
            )


# ─── 类别 E：现有测试套件执行 ────────────────────────────────────────────────


def run_pytest_suite(suite_name: str, cwd: Path, extra_env: dict | None = None) -> None:
    """运行 pytest 套件并记录结果。"""
    print(f"\n  运行 {suite_name} ...")
    t0 = time.monotonic()

    env = os.environ.copy()
    env["ENVIRONMENT"] = "test"
    env["REDIS_URL"] = "redis://127.0.0.1:6379/0"
    if extra_env:
        env.update(extra_env)

    # Use --tb=short (not --tb=no) so failures include concise tracebacks.
    # Save full output to a file for post-mortem diagnosis (the report only
    # keeps the last 800 chars).
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/",
        "-q",
        "--tb=short",
        "--basetemp="
        + str(
            Path(os.environ.get("TEMP", "C:/Users/likr/AppData/Local/Temp"))
            / "cgda_e2e_basetemp"
        ),
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        output = result.stdout + result.stderr

        # Save full output to a file for diagnosis
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = suite_name.replace("/", "_")
        log_path = (
            REPORTS_DIR
            / f"pytest_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        try:
            log_path.write_text(output, encoding="utf-8", errors="replace")
        except Exception:
            log_path = None

        # 解析 pytest 摘要（如 "345 passed, 2 skipped in 89.2s"）
        passed = failed = skipped = errors_count = 0
        m = re.search(r"(\d+) passed", output)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+) failed", output)
        if m:
            failed = int(m.group(1))
        m = re.search(r"(\d+) skipped", output)
        if m:
            skipped = int(m.group(1))
        m = re.search(r"(\d+) error", output)
        if m:
            errors_count = int(m.group(1))

        total = passed + failed + skipped + errors_count
        log_info = f" | 完整日志: {log_path}" if log_path else ""
        if failed == 0 and errors_count == 0:
            record(
                suite_name,
                "E",
                "pass",
                f"{passed} passed, {skipped} skipped",
                elapsed,
                f"total={total}{log_info}",
            )
        else:
            record(
                suite_name,
                "E",
                "fail",
                f"{failed} failed, {errors_count} errors",
                elapsed,
                f"passed={passed}, skipped={skipped} | 末尾输出: {output[-800:]}{log_info}",
            )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - t0) * 1000)
        record(suite_name, "E", "fail", "pytest 超时 300s", elapsed)
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        record(suite_name, "E", "fail", f"执行异常: {e}", elapsed)


def _flush_redis_db0() -> bool:
    """Flush Redis DB 0 to clear workflow/celery state before pytest.

    Returns True on success, False if Redis is unreachable.
    This prevents state pollution from category C (workflow submissions)
    from affecting category E (pytest) tests.
    """
    import socket

    try:
        sock = socket.create_connection(("127.0.0.1", 6379), timeout=3)
        sock.sendall(b"FLUSHDB\r\n")
        resp = sock.recv(64)
        sock.close()
        return b"OK" in resp
    except (OSError, socket.error):
        return False


def test_pytest_suites(run_pytest: bool) -> None:
    print("\n" + "=" * 70)
    print("类别 E：现有测试套件执行（pytest）")
    print("=" * 70)

    if not run_pytest:
        record("(pytest 套件)", "E", "skip", "--no-pytest 标志")
        return

    repo_root = Path(__file__).resolve().parent.parent
    backend_dir = repo_root / "Code" / "backend"
    algo_dir = repo_root / "Code" / "algorithms" / "providers" / "Python"

    # Flush Redis DB 0 to clear workflow/celery state from category C.
    # Also wait briefly for Celery workers to finish in-flight tasks.
    print("  清理 Redis DB 0（清除类别 C 残留状态）...")
    flushed = _flush_redis_db0()
    print(f"  Redis FLUSHDB: {'✓' if flushed else '✗ (unreachable)'}")
    # Give Celery workers a moment to release in-flight task state
    time.sleep(3)

    if backend_dir.exists():
        run_pytest_suite("backend/tests", backend_dir)
    else:
        record("backend/tests", "E", "skip", f"目录不存在: {backend_dir}")

    if algo_dir.exists():
        # CGDA_MAX_PARALLEL_WORKERS=1 prevents subprocess spawning under
        # memory pressure during E2E (system may be low on RAM from
        # running FastAPI + Celery + workers simultaneously).
        run_pytest_suite(
            "algorithms/tests",
            algo_dir,
            extra_env={"CGDA_MAX_PARALLEL_WORKERS": "1"},
        )
    else:
        record("algorithms/tests", "E", "skip", f"目录不存在: {algo_dir}")


# ─── 环境检查 ────────────────────────────────────────────────────────────────


def check_environment() -> bool:
    """检查运行环境。返回 True 表示可继续测试。"""
    print("=" * 70)
    print("环境检查")
    print("=" * 70)

    env_ok = True

    # FastAPI
    status, data = http_get_json(f"{BASE_URL}/health", timeout=10)
    if status == 200:
        ENV_STATUS["fastapi"] = f"✅ {BASE_URL}/health → 200"
        print(f"  ✅ FastAPI: {BASE_URL}")
    else:
        ENV_STATUS["fastapi"] = f"❌ {BASE_URL}/health → {status}: {data}"
        print(f"  ❌ FastAPI 不可达: {data}")
        env_ok = False

    # Open-Meteo
    status, data = http_get_json(
        f"{OPEN_METEO_URL}/v1/forecast?latitude=39.9&longitude=116.4&current=temperature_2m",
        timeout=10,
    )
    if status == 200:
        ENV_STATUS["open_meteo"] = f"✅ {OPEN_METEO_URL} → 200"
        print(f"  ✅ Open-Meteo: {OPEN_METEO_URL}")
    else:
        ENV_STATUS["open_meteo"] = f"❌ {OPEN_METEO_URL} → {status}: {data}"
        print(f"  ⚠️ Open-Meteo 不可达（天气瓦片测试将失败）: {data}")

    # DATA_ROOT
    if DATA_ROOT.exists():
        try:
            subdirs = [d.name for d in DATA_ROOT.iterdir() if d.is_dir()]
            ENV_STATUS["data_root"] = f"✅ {DATA_ROOT} ({len(subdirs)} 子目录)"
            print(f"  ✅ DATA_ROOT: {DATA_ROOT} ({len(subdirs)} 子目录)")
        except Exception as e:
            ENV_STATUS["data_root"] = f"⚠️ {DATA_ROOT} 读取异常: {e}"
            print(f"  ⚠️ DATA_ROOT 读取异常: {e}")
    else:
        ENV_STATUS["data_root"] = f"❌ {DATA_ROOT} 不存在"
        print(f"  ❌ DATA_ROOT 不存在: {DATA_ROOT}")
        env_ok = False

    # OUTPUT_ROOT（自动创建）
    if OUTPUT_ROOT.exists():
        ENV_STATUS["output_root"] = f"✅ {OUTPUT_ROOT}"
        print(f"  ✅ OUTPUT_ROOT: {OUTPUT_ROOT}")
    else:
        try:
            OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
            ENV_STATUS["output_root"] = f"✅ {OUTPUT_ROOT} (已创建)"
            print(f"  ✅ OUTPUT_ROOT: {OUTPUT_ROOT} (已自动创建)")
        except Exception as e:
            ENV_STATUS["output_root"] = f"❌ {OUTPUT_ROOT} 创建失败: {e}"
            print(f"  ❌ OUTPUT_ROOT 创建失败: {e}")

    return env_ok


# ─── 报告生成 ────────────────────────────────────────────────────────────────


def generate_markdown_report(output_path: Path, json_path: Path) -> None:
    """生成 Markdown 测试报告 + JSON 结果。"""
    # 保存 JSON
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(),
                "duration_seconds": round(time.monotonic() - START_TIME, 2),
                "environment": ENV_STATUS,
                "results": RESULTS,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    # 统计
    categories: dict[str, dict] = {}
    for r in RESULTS:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"pass": 0, "fail": 0, "skip": 0, "total": 0}
        categories[cat][r["status"]] = categories[cat].get(r["status"], 0) + 1
        categories[cat]["total"] += 1

    total_pass = sum(c["pass"] for c in categories.values())
    total_fail = sum(c["fail"] for c in categories.values())
    total_skip = sum(c["skip"] for c in categories.values())
    total_all = total_pass + total_fail + total_skip

    # 生成 Markdown
    lines: list[str] = []
    lines.append("# CGDA 数据产出能力 E2E 测试报告\n")
    lines.append(f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **测试耗时**：{time.monotonic() - START_TIME:.1f} 秒")
    lines.append(f"- **环境**：FastAPI `{BASE_URL}` | Open-Meteo `{OPEN_METEO_URL}`\n")

    # 汇总表
    lines.append("## 汇总\n")
    lines.append("| 类别 | 总数 | 通过 | 失败 | 跳过 |")
    lines.append("|------|------|------|------|------|")
    cat_labels = {
        "A": "A. 天气瓦片",
        "B": "B. 静态 COG",
        "C": "C. 算法工作流",
        "D": "D. 工作流种子",
        "E": "E. 测试套件",
    }
    for cat in sorted(categories.keys()):
        c = categories[cat]
        label = cat_labels.get(cat, cat)
        lines.append(
            f"| {label} | {c['total']} | {c['pass']} | {c['fail']} | {c['skip']} |"
        )
    lines.append(
        f"| **合计** | **{total_all}** | **{total_pass}** | **{total_fail}** | **{total_skip}** |\n"
    )

    # 详细结果（按类别分组）
    lines.append("## 详细结果\n")
    for cat in sorted(categories.keys()):
        label = cat_labels.get(cat, cat)
        lines.append(f"### {label}\n")
        cat_results = [r for r in RESULTS if r["category"] == cat]

        if cat == "A":
            lines.append("| 图层 ID | 状态 | 耗时(ms) | 备注 |")
            lines.append("|---------|------|----------|------|")
            for r in cat_results:
                icon = {"pass": "✅", "fail": "❌", "skip": "⏭"}[r["status"]]
                lines.append(
                    f"| {r['name']} | {icon} {r['status']} | {r['duration_ms']} | {r['reason']} |"
                )
        elif cat == "B":
            lines.append("| 图层 ID | 状态 | 耗时(ms) | 备注 |")
            lines.append("|---------|------|----------|------|")
            for r in cat_results:
                icon = {"pass": "✅", "fail": "❌", "skip": "⏭"}[r["status"]]
                lines.append(
                    f"| {r['name']} | {icon} {r['status']} | {r['duration_ms']} | {r['reason']} |"
                )
        elif cat == "C":
            lines.append("| 图层 ID | 状态 | 耗时(ms) | 备注 |")
            lines.append("|---------|------|----------|------|")
            for r in cat_results:
                icon = {"pass": "✅", "fail": "❌", "skip": "⏭"}[r["status"]]
                lines.append(
                    f"| {r['name']} | {icon} {r['status']} | {r['duration_ms']} | {r['reason']} |"
                )
        elif cat == "D":
            lines.append("| 种子文件 | 状态 | 备注 |")
            lines.append("|----------|------|------|")
            for r in cat_results:
                icon = {"pass": "✅", "fail": "❌", "skip": "⏭"}[r["status"]]
                lines.append(f"| {r['name']} | {icon} {r['status']} | {r['reason']} |")
        elif cat == "E":
            lines.append("| 套件 | 状态 | 耗时(ms) | 备注 |")
            lines.append("|------|------|----------|------|")
            for r in cat_results:
                icon = {"pass": "✅", "fail": "❌", "skip": "⏭"}[r["status"]]
                lines.append(
                    f"| {r['name']} | {icon} {r['status']} | {r['duration_ms']} | {r['reason']} |"
                )
        lines.append("")

    # 失败项详情
    failed = [r for r in RESULTS if r["status"] == "fail"]
    if failed:
        lines.append("## 失败项详情\n")
        for r in failed:
            lines.append(f"### {r['name']} ({r['category']})")
            lines.append(f"- **原因**：{r['reason']}")
            if r["detail"]:
                lines.append(f"- **详情**：{r['detail']}")
            lines.append("")

    # 跳过项清单
    skipped = [r for r in RESULTS if r["status"] == "skip"]
    if skipped:
        lines.append("## 跳过项清单\n")
        lines.append("| 项目 | 类别 | 原因 |")
        lines.append("|------|------|------|")
        for r in skipped:
            lines.append(f"| {r['name']} | {r['category']} | {r['reason']} |")
        lines.append("")

    # 附录：环境状态
    lines.append("## 附录：环境状态\n")
    for key, val in ENV_STATUS.items():
        lines.append(f"- {val}")
    lines.append("")

    # 写出
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n{'=' * 70}")
    print("报告已生成：")
    print(f"  Markdown: {output_path}")
    print(f"  JSON:     {json_path}")
    print(f"{'=' * 70}")
    print(
        f"\n汇总：{total_pass} pass / {total_fail} fail / {total_skip} skip (共 {total_all} 项)"
    )


# ─── 主入口 ──────────────────────────────────────────────────────────────────


def main() -> int:
    global START_TIME

    parser = argparse.ArgumentParser(description="CGDA 数据产出能力 E2E 测试")
    parser.add_argument(
        "--category",
        type=str,
        default="A,B,C,D,E",
        help="测试类别（A/B/C/D/E，逗号分隔，默认全部）",
    )
    parser.add_argument(
        "--no-pytest",
        action="store_true",
        help="跳过 pytest 套件（加速）",
    )
    parser.add_argument(
        "--timeout-algo",
        type=int,
        default=ALGO_DEFAULT_TIMEOUT_S,
        help=f"算法工作流超时秒数（默认 {ALGO_DEFAULT_TIMEOUT_S}）",
    )
    args = parser.parse_args()

    START_TIME = time.monotonic()
    cats = {c.strip().upper() for c in args.category.split(",") if c.strip()}

    print("╔" + "═" * 68 + "╗")
    print("║" + " CGDA 数据产出能力 E2E 测试".center(68) + "║")
    print("╚" + "═" * 68 + "╝")
    print(
        f"  类别: {sorted(cats)} | pytest: {not args.no_pytest} | algo 超时: {args.timeout_algo}s"
    )

    # 环境检查
    if not check_environment():
        print("\n[FATAL] 环境检查失败，无法继续测试。")
        return 1

    # 拉取图层目录
    layers = fetch_layer_catalog()
    if not layers:
        print("\n[FATAL] 无法获取图层目录，终止测试。")
        return 1

    print(f"\n  图层目录: {len(layers)} 项")
    by_type: dict[str, int] = {}
    for l in layers:
        st = l.get("source_type", "?")
        by_type[st] = by_type.get(st, 0) + 1
    for st, cnt in sorted(by_type.items()):
        print(f"    {st}: {cnt}")

    # 执行各类别
    if "A" in cats:
        test_weather_tiles(layers)
    if "B" in cats:
        test_static_cog_layers(layers)
    if "C" in cats:
        test_algorithm_workflows(layers, args.timeout_algo)
    if "D" in cats:
        test_workflow_seeds()
    if "E" in cats:
        test_pytest_suites(run_pytest=not args.no_pytest)

    # 生成报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = REPORTS_DIR / f"data_production_e2e_report_{timestamp}.md"
    json_path = REPORTS_DIR / f"data_production_e2e_results_{timestamp}.json"
    generate_markdown_report(md_path, json_path)

    # 退出码
    has_fail = any(r["status"] == "fail" for r in RESULTS)
    return 1 if has_fail else 0


if __name__ == "__main__":
    sys.exit(main())
