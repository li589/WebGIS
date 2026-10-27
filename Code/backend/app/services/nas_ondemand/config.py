"""nas_ondemand 配置与红线常量。

本模块**不含任何副作用**（不连网、不建目录），只声明常量，方便被 CLI、
路由、测试同时引用。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# ── 仓库根定位 ────────────────────────────────────────────────────────────────
# 本文件: <repo>/Code/backend/app/services/nas_ondemand/config.py
# parents: 0=nas_ondemand 1=services 2=app 3=backend 4=Code 5=<repo>
_REPO_ROOT = Path(__file__).resolve().parents[5]
_CRED_PATH = _REPO_ROOT / "Tools" / "_nas_credentials.json"

# ── NAS 接入（凭据从项目内文件读，不在代码里硬编码）──────────────────────────
_NAS_KEY = "filebrowser.nasfile"


def _load_nas_config() -> tuple[str, str, str]:
    """返回 (base_url, username, password)。

    优先级：环境变量 > Tools/_nas_credentials.json。
    环境变量便于容器化部署时不挂凭据文件。
    """
    base = os.environ.get("NAS_FILEBROWSER_BASE_URL", "").strip()
    user = os.environ.get("NAS_FILEBROWSER_USERNAME", "").strip()
    pwd = os.environ.get("NAS_FILEBROWSER_PASSWORD", "").strip()
    if base and user and pwd:
        return base.rstrip("/"), user, pwd
    if not _CRED_PATH.is_file():
        raise RuntimeError(
            f"NAS 凭据文件不存在：{_CRED_PATH}。"
            "请放置 Tools/_nas_credentials.json 或设置 "
            "NAS_FILEBROWSER_BASE_URL/USERNAME/PASSWORD 环境变量。"
        )
    cfg = json.loads(_CRED_PATH.read_text(encoding="utf-8"))["filebrowser"]["nasfile"]
    return (
        str(cfg["base_url"]).rstrip("/"),
        str(cfg["username"]),
        str(cfg["password"]),
    )


# ── 红线 1：NAS 上唯一允许触碰的 8 个目录 ────────────────────────────────────
# 校验方式是 str.startswith()，所以每一项都必须以 "/" 结尾，避免
# "fy_avg_smvod_xxx" 这类同前缀目录被误判为命中。
_NAS_DATA_ROOT = "/Liuzheng/omega_final"

#
# ⚠ OMEGA 组的目录名存在两种写法：勘察记录里 fy_avg_ω / smap_avg_ω / fy_raw_ω
#   用的是希腊小写 ω（U+03C9），而 smap_raw_omega 用的是拉丁字母。为避免靠记忆
#   硬编码导致 404，ω 与 omega 两种拼法都列入白名单，运行期按顺序试第一个
#   能列出内容的（见 fetcher.resolve_nas_dir）。两者都在同一个父目录下，
#   不扩大读取范围。
ALLOWED_NAS_PREFIXES: tuple[str, ...] = (
    f"{_NAS_DATA_ROOT}/fy_avg_smvod/",
    f"{_NAS_DATA_ROOT}/fy_raw_smvod/",
    f"{_NAS_DATA_ROOT}/smap_avg_smvod/",
    f"{_NAS_DATA_ROOT}/smap_raw_smvod/",
    f"{_NAS_DATA_ROOT}/fy_avg_omega/",
    f"{_NAS_DATA_ROOT}/fy_raw_omega/",
    f"{_NAS_DATA_ROOT}/smap_avg_omega/",
    f"{_NAS_DATA_ROOT}/smap_raw_omega/",
    f"{_NAS_DATA_ROOT}/fy_avg_\u03c9/",
    f"{_NAS_DATA_ROOT}/fy_raw_\u03c9/",
    f"{_NAS_DATA_ROOT}/smap_avg_\u03c9/",
    f"{_NAS_DATA_ROOT}/smap_raw_\u03c9/",
)

# ── 红线 2：只认这两种文件名形态 ──────────────────────────────────────────────
# 文件名必须是 8 位数字 + .mat；后缀白名单写死，其它后缀一律不下载。
MAT_SUFFIX = ".mat"
MAT_NAME_LEN = len("YYYYMMDD") + len(MAT_SUFFIX)

# ── 产品表：4 个 NAS 目录 = 卫星 × 约束口径 ───────────────────────────────────
# constraint 用来在图层名/图例里区分「平均散射约束」与「动态散射约束」。
PRODUCTS: dict[str, dict[str, str]] = {
    "fy_avg": {
        "nas_dir": f"{_NAS_DATA_ROOT}/fy_avg_smvod/",
        "source": "FY",
        "source_label": "风云卫星",
        "constraint": "平均散射约束",
    },
    "fy_raw": {
        "nas_dir": f"{_NAS_DATA_ROOT}/fy_raw_smvod/",
        "source": "FY",
        "source_label": "风云卫星",
        "constraint": "动态散射约束",
    },
    "smap_avg": {
        "nas_dir": f"{_NAS_DATA_ROOT}/smap_avg_smvod/",
        "source": "SMAP",
        "source_label": "SMAP",
        "constraint": "平均散射约束",
    },
    "smap_raw": {
        "nas_dir": f"{_NAS_DATA_ROOT}/smap_raw_smvod/",
        "source": "SMAP",
        "source_label": "SMAP",
        "constraint": "动态散射约束",
    },
}

# ω 单独一组目录（smvod 目录里的 OMEGA 与 omega 目录可能是同一批，这里按目录分派）。
# 变量 → 用哪个目录：smvod 目录取 SM/VOD，omega 目录取 OMEGA。
# 值为 str 表示唯一候选；值为 tuple 表示多个候选（运行期按序探测）。
PRODUCT_NAS_DIR_BY_VAR: dict[str, dict[str, str | tuple[str, ...]]] = {
    "SM": {
        "fy_avg": f"{_NAS_DATA_ROOT}/fy_avg_smvod/",
        "fy_raw": f"{_NAS_DATA_ROOT}/fy_raw_smvod/",
        "smap_avg": f"{_NAS_DATA_ROOT}/smap_avg_smvod/",
        "smap_raw": f"{_NAS_DATA_ROOT}/smap_raw_smvod/",
    },
    "VOD": {
        "fy_avg": f"{_NAS_DATA_ROOT}/fy_avg_smvod/",
        "fy_raw": f"{_NAS_DATA_ROOT}/fy_raw_smvod/",
        "smap_avg": f"{_NAS_DATA_ROOT}/smap_avg_smvod/",
        "smap_raw": f"{_NAS_DATA_ROOT}/smap_raw_smvod/",
    },
    "OMEGA": {
        # 按顺序试：拉丁写法优先（smap_raw_omega 已确认为拉丁），希腊 ω 作兜底。
        # 具体用哪个由 fetcher.resolve_nas_dir 在运行期确定并缓存。
        "fy_avg": (
            f"{_NAS_DATA_ROOT}/fy_avg_omega/",
            f"{_NAS_DATA_ROOT}/fy_avg_\u03c9/",
        ),
        "fy_raw": (
            f"{_NAS_DATA_ROOT}/fy_raw_omega/",
            f"{_NAS_DATA_ROOT}/fy_raw_\u03c9/",
        ),
        "smap_avg": (
            f"{_NAS_DATA_ROOT}/smap_avg_omega/",
            f"{_NAS_DATA_ROOT}/smap_avg_\u03c9/",
        ),
        "smap_raw": (
            f"{_NAS_DATA_ROOT}/smap_raw_omega/",
            f"{_NAS_DATA_ROOT}/smap_raw_\u03c9/",
        ),
    },
}

# ── 变量表：配色与量程口径 ────────────────────────────────────────────────────
# ⚠ 口径来源：app/services/python_provider_result_builder.py 的 VARIABLE 预设，
#   与现有导入产物 meta.json 完全一致（SM ylgnbu 0–0.5 / VOD darkgreen-yellow
#   0–1.5 / OMEGA reds 0–0.5）。**不是本模块新定的，不许擅自改**：
#   VOD 的 vmax=1.5 是用户 2026-10-20 明确否决过 0.75 之后确定的现状。
VARIABLES: dict[str, dict[str, object]] = {
    "SM": {
        "variable_id": "SM",
        "label": "SM",
        "title": "土壤水分",
        "palette": "ylgnbu",
        "vmin": 0.0,
        "vmax": 0.5,
        "unit": "m³/m³",
    },
    "VOD": {
        "variable_id": "VOD",
        "label": "VOD",
        "title": "植被光学厚度",
        "palette": "darkgreen-yellow",
        "vmin": 0.0,
        "vmax": 1.5,
        "unit": "1",
    },
    "OMEGA": {
        "variable_id": "OMEGA",
        "label": "OMEGA",
        "title": "散射反照率",
        "palette": "reds",
        "vmin": 0.0,
        "vmax": 0.5,
        "unit": "1",
    },
}

# 同一逻辑变量在 NAS .mat 里的多种写法（按顺序取第一个存在的）。
# 实测：smvod→SM/VOD/OMEGA；*_avg_ω→OMEGA_AVG；*_raw_ω→OMEGA_grid
VARIABLE_ALIASES: dict[str, tuple[str, ...]] = {
    "SM": ("SM",),
    "VOD": ("VOD",),
    "OMEGA": ("OMEGA", "OMEGA_AVG", "OMEGA_grid", "OMEGA_daily"),
}

# ── 缓存策略（用户 2026-10-27 定稿）────────────────────────────────────────────
# 2000 帧上限；每图层保底 30 帧；超限删到 1800 停（留 10% 缓冲，避免每存
# 一帧就删一帧的抖动）。
CACHE_MAX_FRAMES = 2000
CACHE_TARGET_FRAMES = 1800
PER_LAYER_FLOOR = 30
# 最近 N 天打开过的帧不参与淘汰
PROTECT_RECENT_DAYS = 7

# 本地落盘根：imports 下只认这个前缀
LOCAL_LAYER_PREFIX = "imported-nas-"

# 单帧目标分辨率（度，赤道处）。与 Tools/export_overlay_assets.py 里
# _export_smap_soil_vod_sm_ts 的调用一致（0.1°），保证与已有产物同规格。
TARGET_RESOLUTION_DEG = 0.1

# 与已有产物一致的裁剪窗口（中国区域）
CLIP_BOUNDS = (73.0, 15.0, 137.0, 59.0)

# 补帧进「既有图层」时的画幅口径（2026-10-27 实测修正）
# ────────────────────────────────────────────────────────────────────────────
# 工作流产出的风云平均图层，画幅是**全球**的 2048×2047 墨卡托方图
# （bounds ≈ [-180, -85.04, 180, 85.04]）。补进去的单日帧必须同画幅，
# 否则拖动时间轴会从「全球」突变成「中国区特写」，看着像换了图层。
# 分辨率取 360/2048 度 ≈ 0.1758°，与 2048 宽一一对应；
# 若按 0.1° 渲染全球，会得到 3600×3600、单帧 PNG 5~10 MB，没必要。
GLOBAL_FRAME_RESOLUTION_DEG = 360.0 / 2048.0

# 单次下载超时（秒）。NAS 隧道较慢，2.04 MB/s 实测，4.3 MB 文件留足余量。
DOWNLOAD_TIMEOUT = 180
LIST_TIMEOUT = 60

# 下载遇到网络抖动（连接被重置 / IncompleteRead）时的总尝试次数。
DOWNLOAD_RETRIES = 3


def layer_id_for(product: str, variable: str) -> str:
    """产品 × 变量 → 本地图层 ID（如 ``imported-nas-fy-avg-sm``）。"""
    return f"{LOCAL_LAYER_PREFIX}{product.replace('_', '-')}-{variable.lower()}"


def ondemand_target(layer_id: str) -> dict[str, str] | None:
    """图层 ID → 该层的 NAS 取数口径（未登记返回 None）。"""
    return ONDEMAND_TARGETS.get(str(layer_id or "").strip())


# ── 按需补帧目标图层（2026-10-27）────────────────────────────────────────────
# 用户要求「勾选/添加图层保持长序列，只有手动拖时间轴才看单日」，所以单日帧
# **不新建图层**，而是补进工作流已经产出的那个图层目录里。
#
# 目录名 = ``imported-<sha1(catalogId|role|role)[:12]>``，同一工作流重跑会覆盖
# 同一个目录（编号稳定，不随重跑变化），因此这里可以把映射写死。
#
# 前端只报 layer_id，产品/变量由后端查表 —— 避免前端硬编码 NAS 目录语义。
#
# ⚠ 只登记「NAS 上确实有逐日文件」的图层：
#   · 风云·平均散射约束 SM / VOD → fy_avg_smvod/YYYYMMDD.mat（真·逐日）
#   · 风云·平均散射约束 OMEGA    → fy_avg_ω/doy_DDD.mat（年内日序气候态，
#     与「2025-12-17 这一天」语义不等价，待用户确认口径后再接）
ONDEMAND_TARGETS: dict[str, dict[str, str]] = {
    "imported-55359b8ecd3d": {"product": "fy_avg", "variable": "SM"},
    "imported-a94205dad5f9": {"product": "fy_avg", "variable": "VOD"},
}

# NAS 成果的实际覆盖范围（前端据此提前拦掉明显不可能的日期，省一次往返）
DATA_COVERAGE_START = "20150401"
DATA_COVERAGE_END = "20251231"


# ── NAS 文件名规则（2026-10-27 实地核对 /Liuzheng/omega_final）───────────────
# 三套完全不同的命名，不能统一按 YYYYMMDD.mat 取：
#   · smvod 目录（SM / VOD）    ：YYYYMMDD.mat                     —— 逐日
#   · *_avg_ω 目录（OMEGA）     ：doy_DDD.mat                      —— 年内日序的气候态
#   · *_raw_ω 目录（OMEGA）     ：YYYYMMDD_YYYYMMDD_exp0_...mat    —— 8 天块
# 例：fy_raw_ω 里首尾是 20150330_20150406 / 20251227_20251231，
#     即按「年内第 DOY 天」每 8 天切一段，块起点 = 1/1 + 8*((doy-1)//8)，
#     与算法 algorithms/omega.py::make_date_blocks 完全一致，年末尾块截断。
RAW_BLOCK_DAYS = 8
RAW_OMEGA_FILENAME_SUFFIX = "_exp0_global_ismn_all_shard01of01_roundrobin.mat"


def _parse_tag(date_tag: str) -> Any:
    import datetime as _dt

    tag = str(date_tag).strip()
    return _dt.date(int(tag[0:4]), int(tag[4:6]), int(tag[6:8]))


def raw_block_span(date_tag: str) -> tuple[Any, Any]:
    """请求日期 → 它所属的 8 天块 (起, 止)，两者都含端点。"""
    import calendar
    import datetime as _dt

    d = _parse_tag(date_tag)
    year_start = _dt.date(d.year, 1, 1)
    doy = (d - year_start).days + 1
    start_doy = 1 + RAW_BLOCK_DAYS * ((doy - 1) // RAW_BLOCK_DAYS)
    year_days = 366 if calendar.isleap(d.year) else 365
    end_doy = min(start_doy + RAW_BLOCK_DAYS - 1, year_days)
    return (
        year_start + _dt.timedelta(days=start_doy - 1),
        year_start + _dt.timedelta(days=end_doy - 1),
    )


def nas_filename_for(product: str, variable: str, date_tag: str) -> str:
    """产品 × 变量 × 日期 → NAS 上真实存在的那个文件名。"""
    var = variable.upper()
    if var == "OMEGA":
        if product.endswith("_avg"):
            doy = _parse_tag(date_tag).timetuple().tm_yday
            return f"doy_{doy:03d}{MAT_SUFFIX}"
        start, end = raw_block_span(date_tag)
        return (
            f"{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
            f"{RAW_OMEGA_FILENAME_SUFFIX}"
        )
    return f"{date_tag}{MAT_SUFFIX}"


def nas_dir_candidates(product: str, variable: str) -> tuple[str, ...]:
    """产品 × 变量 → NAS 目录候选列表（带尾斜杠，按优先级排序）。

    OMEGA 组返回 2 个候选（拉丁 omega / 希腊 ω），SM 与 VOD 返回 1 个。
    真正的目录由 ``fetcher.resolve_nas_dir`` 探测确定并缓存。
    """
    try:
        raw = PRODUCT_NAS_DIR_BY_VAR[variable.upper()][product]
    except KeyError as exc:
        raise ValueError(f"未知的产品/变量组合：{product}/{variable}") from exc
    if isinstance(raw, tuple):
        return raw
    return (raw,)
