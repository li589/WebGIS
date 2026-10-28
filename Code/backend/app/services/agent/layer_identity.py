"""图层身份适配层（Agent 侧）：给任意图层算出规范化的来源 / 变量 / 物理单位。

背景（SGFS 报告 R07）：
    后端此前把"变量标签"当单位写进 overlay 注册表
    （``overlay_registry.py:772`` → ``meta.get("unit") or meta.get("label")``，
    而产物 meta 里 ``unit`` 为空、``label`` 是 ``SM`` / ``VOD`` / ``OMEGA``），
    于是点查返回 ``{"unit": "SM"}``，模型就会说成"单位是 SM"。
    同时没有任何规范化的"来源"字段，模型只能靠图层名去猜卫星。

本模块只做一件事：``resolve_layer_identity()`` —— 输入任意 catalog_id /
overlay_id，输出一份"身份证"：来源、变量、物理单位。查不到就明确
``unknown``，绝不猜、绝不回落成 id 字符串。

判定优先级（全部有盘上数据依据，不硬编码图层清单）：
    source   ① catalog 描述符的 layer_id / sources[].name / presentation.source_label
             ② 产物 meta.json 的 run_id → workflow_runs.layer_id → 回到 ①
    variable ① 产物 meta.json 的 variable_id（SM / VOD / OMEGA，最精确）
             ② display_name 关键词，③ layer_id token
    unit     由 variable 决定；未知变量一律给 None，不编造默认值。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 来源代码 ────────────────────────────────────────────────────────────────
SOURCE_SMAP = "smap"
SOURCE_FY = "fy"
SOURCE_STATION = "station"
SOURCE_FUSED = "fused"
SOURCE_UNKNOWN = "unknown"

SOURCE_LABELS: dict[str, str] = {
    SOURCE_SMAP: "SMAP",
    SOURCE_FY: "风云卫星",
    SOURCE_STATION: "地面站点",
    SOURCE_FUSED: "多源融合",
    SOURCE_UNKNOWN: "未标注来源",
}

# ── 变量与物理单位 ──────────────────────────────────────────────────────────
# unit：机器字段（无量纲固定 "1"）；unit_label：给模型说话用的中文
VARIABLE_SPECS: dict[str, dict[str, str]] = {
    "sm": {"label": "土壤水分", "unit": "m³/m³", "unit_label": "m³/m³"},
    "vod": {"label": "植被光学厚度", "unit": "1", "unit_label": "无量纲"},
    "omega": {"label": "等效散射 ω", "unit": "1", "unit_label": "无量纲"},
    "tb": {"label": "亮温", "unit": "K", "unit_label": "K"},
    "ndvi": {"label": "植被指数 NDVI", "unit": "1", "unit_label": "无量纲"},
}

# 产物 meta.json 的 variable_id → 变量代码
_META_VARIABLE_CODES: dict[str, str] = {
    "SM": "sm",
    "VOD": "vod",
    "OMEGA": "omega",
    "TB": "tb",
    "NDVI": "ndvi",
}

# display_name 关键词（先匹配，名字比 id 更贴近用户看到的字）
_VARIABLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sm", ("土壤水分", "土壤湿度", "soil moisture")),
    ("vod", ("植被光学厚度", "光学厚度", "vegetation optical")),
    # 注意：「散射」**不能**单独作为变量证据。产品族名里必然含这两个字
    # （「SMAP 动态散射约束产品」「风云卫星平均散射约束产品」），一旦把
    # 「散射」当 ω 的证据，整族都会被误判成 ω 图层——2026-10-28 实测：
    # 用户问「SMAP 动态散射约束产品」，模型据此答「这一层是等效散射 ω（无量纲）」。
    # 真正的变量层显示名是「等效散射 ω」，靠「等效散射」/「omega」/「ω」已足够。
    ("omega", ("等效散射", "omega", "ω")),
    ("tb", ("亮温", "brightness temperature")),
    ("ndvi", ("ndvi", "植被指数")),
)

# layer_id token（按 - _ 切分后整词比对，避免 "modify" 里误命中 fy）
_VARIABLE_TOKENS: dict[str, str] = {
    "sm": "sm",
    "vod": "vod",
    "omega": "omega",
    "tb": "tb",
    "ndvi": "ndvi",
}

_FY_RE = re.compile(r"(^|[^a-z0-9])fy([-_ ]?3)?([^a-z0-9]|$)")


def _normalize_source_from_text(text: str) -> str | None:
    """从任意文本里判来源；同时含 SMAP 与风云 ⇒ 融合产品。"""
    if not text:
        return None
    t = str(text).casefold()
    has_smap = "smap" in t
    has_fy = bool(_FY_RE.search(t)) or "风云" in t or "mwri" in t
    has_station = "station" in t or "站点" in t or "ismn" in t or "casmos" in t
    if has_smap and has_fy:
        return SOURCE_FUSED
    if has_smap:
        return SOURCE_SMAP
    if has_fy:
        return SOURCE_FY
    if has_station:
        return SOURCE_STATION
    return None


def _descriptor(catalog_id: str) -> Any | None:
    try:
        from app.services.layer_catalog import get_layer_descriptor

        return get_layer_descriptor(catalog_id)
    except Exception:  # pragma: no cover - 目录不可用时降级
        logger.debug("layer descriptor unavailable for %s", catalog_id, exc_info=True)
        return None


# ── 产物来源回溯（meta.json → workflow_runs）────────────────────────────────


def _read_meta(overlay_id: str) -> dict[str, Any]:
    try:
        from app.data_io.services.paths import safe_import_child

        dest_dir = safe_import_child(overlay_id)
        meta_path = dest_dir / "meta.json"
        if not meta_path.is_file():
            return {}
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.debug("import meta unavailable for %s", overlay_id, exc_info=True)
        return {}


def _lookup_run_layer_id(run_id: str) -> str | None:
    """run_id → 当初提交这条运行的 catalog layer_id（只读、短超时）。"""
    if not run_id:
        return None
    try:
        from app.core.config import settings

        db_path = Path(settings.workflow_state_dir) / "workflow_state.sqlite3"
        if not db_path.is_file():
            return None
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            row = connection.execute(
                "SELECT layer_id FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        finally:
            connection.close()
    except Exception:
        logger.debug("run lookup failed for %s", run_id, exc_info=True)
        return None
    if row is None or row[0] is None:
        return None
    return str(row[0])


_ORIGIN_CACHE: dict[str, str | None] = {}
_ORIGIN_CACHE_LIMIT = 512


def _imported_origin_layer_id(overlay_id: str) -> str | None:
    """产物目录 → 生成它的工作流图层 id（认不出就 None）。"""
    if overlay_id in _ORIGIN_CACHE:
        return _ORIGIN_CACHE[overlay_id]
    meta = _read_meta(overlay_id)
    run_id = str(meta.get("run_id") or "").strip()
    origin = _lookup_run_layer_id(run_id) if run_id else None
    if origin == overlay_id:
        origin = None
    if len(_ORIGIN_CACHE) >= _ORIGIN_CACHE_LIMIT:
        _ORIGIN_CACHE.clear()
    _ORIGIN_CACHE[overlay_id] = origin
    return origin


def _meta_variable_code(overlay_id: str) -> str | None:
    meta = _read_meta(overlay_id)
    raw = str(meta.get("variable_id") or "").strip().upper()
    return _META_VARIABLE_CODES.get(raw)


# ── 产品族（method-* 工作流方法层）────────────────────────────────────────────
# ``method-*`` 是「产品族」：它下面按变量分 SM / VOD / OMEGA 三个产物，
# 本身不承载栅格。此前对它照常做变量推断，组名里的「散射」会被判成 ω，
# 于是「SMAP 动态散射约束产品」被说成「等效散射 ω 图层」「本地无产物」。
_PRODUCT_GROUP_PREFIX = "method-"
_GROUP_VARIABLE_ROLES: tuple[tuple[str, str], ...] = (
    ("SM", "sm"),
    ("VOD", "vod"),
    ("OMEGA", "omega"),
)


def _has_local_raster(layer_id: str) -> bool:
    """该 id 自己是否挂着栅格产物（有 overlay spec 才算数据层）。"""
    try:
        from app.services.overlay_registry import get_overlay_spec

        return get_overlay_spec(layer_id) is not None
    except Exception:  # pragma: no cover
        return False


def _group_member_ids(cid: str) -> list[dict[str, str]]:
    """产品族 id → 本机**实际存在**的成员产物（盘上没有的不列，绝不编造）。

    目录命名是 ``imported-<sha1(catalogId|role|role)[:12]>``（见
    ``data_io/services/raster_timeseries.stable_imported_layer_id``），
    所以这里用同一函数反算，再检查 ``meta.json`` 是否真存在。
    """
    if not str(cid or "").startswith(_PRODUCT_GROUP_PREFIX):
        return []
    try:
        from app.data_io.services.paths import safe_import_child
        from app.data_io.services.raster_timeseries import stable_imported_layer_id
    except Exception:  # pragma: no cover
        return []
    members: list[dict[str, str]] = []
    for role, code in _GROUP_VARIABLE_ROLES:
        try:
            oid = stable_imported_layer_id(cid, role, role)
            if not (safe_import_child(oid) / "meta.json").is_file():
                continue
        except Exception:  # pragma: no cover
            continue
        spec = VARIABLE_SPECS.get(code) or {}
        members.append(
            {
                "overlay_layer_id": oid,
                "variable": code,
                "variable_label": str(spec.get("label") or ""),
                "variable_id": role,
            }
        )
    return members


_IMPORT_INDEX_CACHE: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}


def _daily_tag_count(dir_name: str) -> int:
    """目录里 8 位单日产物（preview_*/source_*）的个数；块键带下划线，不计入。"""
    try:
        from app.data_io.services.paths import safe_import_child

        layer_dir = safe_import_child(dir_name)
        if not layer_dir.is_dir():
            return 0
        tags: set[str] = set()
        for entry in layer_dir.iterdir():
            name = entry.name
            if name.startswith("preview_") and name.endswith(".png"):
                tag = name[8:-4]
            elif name.startswith("source_") and name.endswith(".tif"):
                tag = name[7:-4]
            else:
                continue
            if len(tag) == 8 and tag.isdigit():
                tags.add(tag)
        return len(tags)
    except Exception:  # pragma: no cover - 目录不可读时按 0 处理
        return 0


def _import_meta_index(cid: str) -> dict[str, dict[str, Any]]:
    """``imports/`` 下所有产物目录的关键字段（按父目录 mtime 缓存，只读一次盘）。

    只取判定「是否同一份数据的两个副本」所需的最小字段，不读栅格。
    """
    try:
        from app.data_io.services.paths import safe_import_child

        parent = safe_import_child(cid).parent
        stamp = parent.stat().st_mtime
    except Exception:  # pragma: no cover
        return {}
    key = str(parent)
    hit = _IMPORT_INDEX_CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    index: dict[str, dict[str, Any]] = {}
    try:
        names = sorted(
            p.name
            for p in parent.iterdir()
            if p.is_dir() and p.name.startswith("imported-")
        )
    except OSError:  # pragma: no cover
        return {}
    for name in names:
        meta = _read_meta(name)
        if not meta:
            continue
        index[name] = {
            "run_id": str(meta.get("run_id") or "").strip(),
            "variable_id": str(meta.get("variable_id") or "").strip().upper(),
            "time_list_count": len(meta.get("time_list") or []),
            "daily_frame_count": _daily_tag_count(name),
        }
    _IMPORT_INDEX_CACHE[key] = (stamp, index)
    return index


def _canonical_sibling(run_id: str, variable_id: str) -> str | None:
    """同一 run + 同一变量下，目录名与 ``sha1(catalogId|role|role)`` 对得上的那个。"""
    if not run_id or not variable_id:
        return None
    origin = _lookup_run_layer_id(run_id)
    if not origin:
        return None
    try:
        from app.data_io.services.raster_timeseries import stable_imported_layer_id

        return str(stable_imported_layer_id(origin, variable_id, variable_id))
    except Exception:  # pragma: no cover
        return None


def _sibling_copies(cid: str) -> tuple[list[dict[str, Any]], bool]:
    """同源副本：**同一个 run、同一个变量、却是两个不同目录**的产物。

    2026-10-29 实测：``imported-38993117b963``（旧）与 ``imported-136c60293bbf``（新）
    的 63 天块逐像元完全相同（0.16640186 / 643731 像元 / 1624×3856），差别只在
    ``time_list``——旧目录只有 1 片 63 天块 + 6 天补帧，新目录 73 片（逐日 + 8 天块
    + 63 天块）。两者 label / variable_id / run_id 全同，靠名字分不开，于是出现
    「同一层一会儿说 11 片、一会儿说补了 6 天」的自相矛盾。

    Returns ``(siblings, is_stale_copy)``：``siblings`` 不含自己；``is_stale_copy``
    表示「自己是那个目录名与 sha1 对不上的旧副本」。
    """
    if not cid.startswith("imported-"):
        return ([], False)
    index = _import_meta_index(cid)
    me = index.get(cid) or {}
    run_id = str(me.get("run_id") or "")
    variable_id = str(me.get("variable_id") or "")
    if not run_id or not variable_id:
        return ([], False)
    twins = [
        name
        for name, info in index.items()
        if name != cid
        and info.get("run_id") == run_id
        and info.get("variable_id") == variable_id
    ]
    if not twins:
        return ([], False)
    canonical = _canonical_sibling(run_id, variable_id)
    members = sorted([cid, *twins])
    siblings = [
        {
            "overlay_layer_id": name,
            "time_list_count": int(index[name]["time_list_count"]),
            "daily_frame_count": int(index[name]["daily_frame_count"]),
            "is_canonical": bool(canonical and name == canonical),
        }
        for name in members
        if name != cid
    ]
    is_stale = bool(canonical) and cid != canonical and canonical in index
    return (siblings, is_stale)


def _product_family(layer_id: str) -> str | None:
    """产品族口径：dynamic（逐日/8 天动态） / average（整段平均） / raw（原始）。"""
    text = str(layer_id or "").casefold()
    if not text:
        return None
    if "dynamic" in text:
        return "dynamic"
    if "avg" in text or "average" in text:
        return "average"
    if "raw" in text:
        return "raw"
    return None


# ── 变量判定 ────────────────────────────────────────────────────────────────


def _normalize_variable(*texts: str) -> str | None:
    for text in texts:
        if not text:
            continue
        folded = str(text).casefold()
        for code, keywords in _VARIABLE_KEYWORDS:
            if any(k.casefold() in folded for k in keywords):
                return code
    for text in texts:
        if not text:
            continue
        tokens = [t for t in re.split(r"[-_\s]+", str(text).casefold()) if t]
        for token in tokens:
            code = _VARIABLE_TOKENS.get(token)
            if code:
                return code
    return None


def resolve_layer_identity(
    catalog_id: str,
    *,
    display_name: str | None = None,
) -> dict[str, Any]:
    """返回图层的规范化身份；识别不出的字段一律 unknown/None，不猜。"""
    cid = str(catalog_id or "").strip()
    identity: dict[str, Any] = {
        "catalog_id": cid,
        "display_name": (str(display_name).strip() if display_name else "") or cid,
        "source": SOURCE_UNKNOWN,
        "source_label": SOURCE_LABELS[SOURCE_UNKNOWN],
        "source_detail": None,
        "variable": "unknown",
        "variable_label": None,
        "unit": None,
        "unit_label": None,
        "origin_layer_id": None,
        "product_group_label": None,
        "product_family": None,
        "is_product_group": False,
        "group_members": [],
        "sibling_copies": [],
        "is_stale_copy": False,
        "basis": [],
    }
    if not cid:
        return identity

    desc = _descriptor(cid)
    origin_id: str | None = None
    if desc is None and cid.startswith("imported-"):
        origin_id = _imported_origin_layer_id(cid)
        if origin_id:
            identity["origin_layer_id"] = origin_id
            desc = _descriptor(origin_id)

    desc_name = str(getattr(desc, "display_name", "") or "") if desc else ""
    if desc_name:
        identity["display_name"] = desc_name

    # ---- 来源 ----
    source_candidates: list[str] = [cid]
    if origin_id:
        source_candidates.append(origin_id)
    if desc is not None:
        source_candidates.append(str(getattr(desc, "layer_id", "") or ""))
        for item in getattr(desc, "sources", None) or []:
            source_candidates.append(str(getattr(item, "name", "") or ""))
        presentation = getattr(desc, "presentation", None)
        source_label_seed = str(getattr(presentation, "source_label", "") or "").strip()
        if source_label_seed:
            source_candidates.append(source_label_seed)
            identity["source_detail"] = source_label_seed
    if display_name:
        source_candidates.append(str(display_name))

    source: str | None = None
    for candidate in source_candidates:
        source = _normalize_source_from_text(candidate)
        if source is not None:
            identity["basis"].append("source:descriptor")
            break
    if source is None:
        # 认不出仪器就不硬套"其他来源"——保持 unknown，把原始文案留在 source_detail
        source = SOURCE_UNKNOWN
    identity["source"] = source
    identity["source_label"] = SOURCE_LABELS.get(source, SOURCE_LABELS[SOURCE_UNKNOWN])

    # ---- 产品族：method-* 且自身没有栅格 spec ⇒ 是一族，不是一层 ----
    is_group = False
    if cid.startswith(_PRODUCT_GROUP_PREFIX) and not _has_local_raster(cid):
        is_group = True
        identity["is_product_group"] = True
        identity["group_members"] = _group_member_ids(cid)
        identity["basis"].append("variable:product_group")
    identity["product_group_label"] = desc_name or None
    identity["product_family"] = _product_family(origin_id or cid)

    # ---- 同源副本：同一 run + 同一变量却有两个目录（新旧两套产物）----
    if cid.startswith("imported-") and not is_group:
        siblings, is_stale = _sibling_copies(cid)
        if siblings:
            identity["sibling_copies"] = siblings
            identity["is_stale_copy"] = is_stale
            identity["basis"].append("sibling_copy:same_run_same_variable")

    # ---- 变量 ----
    variable: str | None = None
    if is_group:
        # 产品族不落单一变量：组名里的「散射」是族名用词，不是 ω 的证据。
        # 保持 unknown，让调用方去问「这一族里的哪一个」。
        pass
    elif cid.startswith("imported-"):
        variable = _meta_variable_code(cid)
        if variable:
            identity["basis"].append("variable:meta")
    if variable is None and not is_group:
        variable = _normalize_variable(
            str(display_name or ""), desc_name, cid, origin_id or ""
        )
        if variable:
            identity["basis"].append("variable:name")
    if variable is None:
        variable = "unknown"
    identity["variable"] = variable

    spec = VARIABLE_SPECS.get(variable)
    if spec is not None:
        identity["variable_label"] = spec["label"]
        identity["unit"] = spec["unit"]
        identity["unit_label"] = spec["unit_label"]
    else:
        metric_unit = ""
        presentation = getattr(desc, "presentation", None) if desc else None
        if presentation is not None:
            metric_unit = str(getattr(presentation, "metric_unit", "") or "").strip()
        # 只在目录里明确写了单位时才填，避免又一次"拿标签当单位"
        if metric_unit and metric_unit not in {"class", "fraction"}:
            identity["unit"] = metric_unit
            identity["unit_label"] = metric_unit
    return identity


def describe_identity_line(catalog_id: str, *, display_name: str | None = None) -> str:
    """一行式身份描述，供日志/兜底文案使用（不用于拼最终回答）。"""
    ident = resolve_layer_identity(catalog_id, display_name=display_name)
    parts = [ident["display_name"]]
    if ident["source"] != SOURCE_UNKNOWN:
        parts.append(ident["source_label"])
    if ident["variable_label"]:
        parts.append(ident["variable_label"])
    if ident["unit_label"]:
        parts.append(ident["unit_label"])
    return " · ".join(parts)


def identity_fields(
    catalog_id: str, *, display_name: str | None = None
) -> dict[str, Any]:
    """点查/目录/搜索结果要拼进返回体的字段子集。

    ``product_group_label`` / ``product_family`` / ``origin_catalog_id`` 三项是为
    了让同名图层可区分：页面上常同时挂着「SMAP 动态」「SMAP 平均」「风云动态」
    「风云平均」四族各三个变量，共 12 层，其中 4 层都叫「土壤水分」。
    """
    ident = resolve_layer_identity(catalog_id, display_name=display_name)
    fields: dict[str, Any] = {
        "source": ident["source"],
        "source_label": ident["source_label"],
        "source_detail": ident["source_detail"],
        "variable": ident["variable"],
        "variable_label": ident["variable_label"],
        "unit": ident["unit"],
        "unit_label": ident["unit_label"],
        "origin_catalog_id": ident["origin_layer_id"],
        "product_group_label": ident["product_group_label"],
        "product_family": ident["product_family"],
        "is_product_group": ident["is_product_group"],
        "group_members": ident["group_members"],
    }
    # 只有真存在同源副本时才带这两项，避免 12 层搜索结果里塞满空数组
    if ident["sibling_copies"]:
        fields["sibling_copies"] = ident["sibling_copies"]
        fields["is_stale_copy"] = ident["is_stale_copy"]
    return fields
