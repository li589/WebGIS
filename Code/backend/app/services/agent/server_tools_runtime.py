"""Server tool runtime for Agent (read tools immediate; run_workflow via confirmation)."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Read tools execute immediately; write tools create confirmation tickets (Phase B/C).
_READ_TOOLS = frozenset(
    {
        "search_layers",
        "list_workflows",
        "get_layer_meta",
        "get_workflow_meta",
        "sample_layer_point",
        "web_search",
        "list_workflow_runs",
        "get_workflow_run",
        "get_layer_coverage",
        "get_layer_statistics",
        "list_workflow_timers",
    }
)
_WRITE_TOOLS = frozenset({"run_workflow"})
_ALLOWED_TOOLS = _READ_TOOLS | _WRITE_TOOLS
ALLOWED_SERVER_TOOLS = _ALLOWED_TOOLS


def execute_server_tool(
    name: str,
    args: dict[str, Any],
    *,
    cred: Any = None,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute an allowed server tool. Unknown tools return ok=False."""
    tool = (name or "").strip()
    if tool not in _ALLOWED_TOOLS:
        return {"ok": False, "error": f"未知或未授权的服务端工具: {tool}"}
    if tool == "search_layers":
        # client_context 必传：只有它知道「页面上现在挂着哪些图层」，
        # 运行产物（imported-*）不在 catalog 里，纯目录搜是搜不到的。
        return _search_layers(args, cred=cred, client_context=client_context)
    if tool == "list_workflows":
        return _list_workflows(args, cred=cred)
    if tool == "get_layer_meta":
        return _get_layer_meta(args, cred=cred)
    if tool == "get_workflow_meta":
        return _get_workflow_meta(args, cred=cred)
    if tool == "sample_layer_point":
        return _sample_layer_point(args, cred=cred, client_context=client_context)
    if tool == "web_search":
        return _web_search(args)
    if tool == "list_workflow_runs":
        return _list_workflow_runs(args, cred=cred)
    if tool == "get_workflow_run":
        return _get_workflow_run(args, cred=cred)
    if tool == "get_layer_coverage":
        return _get_layer_coverage(args, cred=cred)
    if tool == "get_layer_statistics":
        # client_context 必传：统计要默认用「页面当前日期 + 页面选中图层」，
        # 否则会静默退回 meta.default_time（曾导致页面停在 12-15 却统计 01-25~02-01）。
        return _get_layer_statistics(args, cred=cred, client_context=client_context)
    if tool == "list_workflow_timers":
        return _list_workflow_timers(args, cred=cred)
    if tool == "run_workflow":
        return _prepare_run_workflow(args, cred=cred)
    return {"ok": False, "error": f"未实现: {tool}"}


def _cred_meta(cred: Any) -> tuple[int | None, str | None]:
    if cred is None:
        return None, None
    uid = getattr(cred, "user_id", None)
    role = getattr(cred, "role", None)
    try:
        uid_i = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid_i = None
    return uid_i, str(role) if role else None


def _prepare_run_workflow(args: dict[str, Any], *, cred: Any) -> dict[str, Any]:
    """Build a confirmation ticket; never enqueue until /agent/confirm approve."""
    from app.services.credential_resolver import allows_write

    if cred is None or not allows_write(cred):
        return {
            "ok": False,
            "error": "当前身份无法提交工作流（需要 standard/admin 写权限）",
        }

    catalog_id = str(args.get("catalog_id") or "").strip()
    if not catalog_id:
        return {"ok": False, "error": "catalog_id 不能为空"}

    accessible = _filter_ids([catalog_id], cred)
    if catalog_id not in set(accessible):
        return {"ok": False, "error": f"无权访问图层: {catalog_id}"}

    from app.services.layer_catalog import get_layer_descriptor

    desc = get_layer_descriptor(catalog_id)
    display = catalog_id
    workflow_id = str(args.get("workflow_id") or "").strip()
    if desc is not None:
        display = str(getattr(desc, "display_name", "") or catalog_id)
        if not workflow_id:
            workflow_id = str(getattr(desc, "workflow_id", "") or "").strip()

    if not workflow_id:
        return {
            "ok": False,
            "error": f"图层 {catalog_id} 未绑定 workflow_id，请在参数中显式提供",
        }

    params = args.get("params") if isinstance(args.get("params"), dict) else {}
    # Keep params JSON-serializable and bounded
    safe_params: dict[str, Any] = {}
    for k, v in list(params.items())[:40]:
        key = str(k)[:64]
        if isinstance(v, (str, int, float, bool)) or v is None:
            safe_params[key] = v if not isinstance(v, str) else v[:500]
        elif isinstance(v, (list, dict)):
            safe_params[key] = v

    variant = (
        str(args.get("workflow_variant") or args.get("variant") or "").strip().lower()
    )
    if variant == "online":
        online_wf = ""
        if desc is not None:
            variants = getattr(desc, "workflow_variants", None) or {}
            if isinstance(variants, dict):
                online_def = variants.get("online")
                if online_def is not None:
                    online_wf = str(
                        getattr(online_def, "workflow_id", None)
                        or (
                            online_def.get("workflow_id")
                            if isinstance(online_def, dict)
                            else ""
                        )
                        or ""
                    ).strip()
        if not online_wf:
            return {
                "ok": False,
                "error": f"图层 {catalog_id} 无可用 online 工作流变体",
            }
        workflow_id = online_wf

    time_range_model = None
    raw_tr = args.get("time_range")
    if raw_tr is not None:
        if not isinstance(raw_tr, dict):
            return {"ok": False, "error": "time_range 须为对象 {start, end}"}
        start_raw = raw_tr.get("start_at") or raw_tr.get("start")
        end_raw = raw_tr.get("end_at") or raw_tr.get("end")
        if not start_raw or not end_raw:
            return {
                "ok": False,
                "error": "time_range 须同时提供 start/start_at 与 end/end_at",
            }
        from datetime import datetime

        from shared.contracts.api_contracts import TimeGranularity, TimeRange

        def _parse_dt(val: Any) -> datetime | None:
            s = str(val).strip()
            if not s:
                return None
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None

        start_at = _parse_dt(start_raw)
        end_at = _parse_dt(end_raw)
        if start_at is None or end_at is None:
            return {"ok": False, "error": "time_range 日期无法解析（需 ISO 8601）"}
        try:
            time_range_model = TimeRange(
                start_at=start_at,
                end_at=end_at,
                granularity=TimeGranularity.hour,
            )
        except ValueError as exc:
            return {"ok": False, "error": f"time_range 无效: {exc}"}

    from shared.contracts.api_contracts import (
        AlgorithmWorkflowRequest,
        WorkflowCommandType,
        WorkflowSubmitRequest,
    )

    submit = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label=f"agent:{catalog_id}",
        layer_id=catalog_id,
        parameters=dict(safe_params),
        time_range=time_range_model,
        algorithm_request=AlgorithmWorkflowRequest(
            workflow_name=workflow_id,
            algorithm_params=dict(safe_params),
            tags={
                "source": "agent",
                "catalog_id": catalog_id[:128],
                **({"workflow_variant": variant} if variant else {}),
            },
        ),
        requested_outputs=["json", "map_layer"],
    )
    submit_payload = submit.model_dump(mode="json")
    summary = {
        "catalog_id": catalog_id,
        "display_name": display,
        "workflow_id": workflow_id,
        "params": safe_params,
    }
    if variant:
        summary["workflow_variant"] = variant
    if time_range_model is not None:
        summary["time_range"] = {
            "start_at": time_range_model.start_at.isoformat(),
            "end_at": time_range_model.end_at.isoformat(),
        }
    uid, role = _cred_meta(cred)
    from app.services.agent.agent_confirm import create_confirmation

    ticket = create_confirmation(
        action="run_workflow",
        summary=summary,
        submit_payload=submit_payload,
        user_id=uid,
        role=role,
    )
    logger.info(
        "Agent run_workflow pending confirmation_id=%s catalog=%s workflow=%s user=%s",
        ticket.get("confirmation_id"),
        catalog_id,
        workflow_id,
        uid,
    )
    extra = ""
    if variant == "online":
        extra += "（在线变体）"
    if time_range_model is not None:
        extra += f"（时段 {summary['time_range']['start_at']} → {summary['time_range']['end_at']}）"
    return {
        "ok": True,
        "needs_confirmation": True,
        "confirmation_id": ticket["confirmation_id"],
        "expires_at": ticket["expires_at"],
        "summary": summary,
        "message": (
            f"已准备提交工作流「{workflow_id}」作用于图层「{display}」{extra}。"
            "请在对话中确认后才会真正排队执行。"
        ),
    }


def _list_workflows(args: dict[str, Any], *, cred: Any) -> dict[str, Any]:
    """List workflow definitions (read-only), optional keyword filter + ACL."""
    query = str(args.get("query") or "").strip().casefold()
    try:
        limit = int(args.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(50, limit))

    try:
        from app.services.workflow_definition_service import list_definitions
    except Exception as exc:
        logger.exception("list_workflows import failed")
        return {"ok": False, "error": f"无法加载工作流列表: {exc}"}

    candidates: list[dict[str, Any]] = []
    for item in list_definitions() or []:
        if not isinstance(item, dict):
            continue
        wid = str(item.get("workflow_id") or "").strip()
        if not wid:
            continue
        name = str(item.get("name") or wid)
        tags = item.get("tags") or []
        tag_s = " ".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)
        blob = f"{wid} {name} {tag_s} {item.get('engine') or ''}".casefold()
        if query and query not in blob:
            continue
        candidates.append(
            {
                "workflow_id": wid,
                "name": name,
                "engine": str(item.get("engine") or ""),
                "linked_layer_id": item.get("linked_layer_id"),
                "is_template": bool(item.get("is_template", False)),
                "kind": str(item.get("kind") or ""),
            }
        )

    accessible = set(
        _filter_resource_ids(
            [c["workflow_id"] for c in candidates],
            cred,
            resource_type="workflow",
        )
    )
    hits = [c for c in candidates if c["workflow_id"] in accessible][:limit]
    return {"ok": True, "count": len(hits), "workflows": hits}


def _format_block_key(raw: Any) -> str | None:
    """`20251201_20260201` / `20251215` → 可读时间说明（失败返回 None）。"""
    key = str(raw or "").strip()
    if not key:
        return None
    block = re.fullmatch(r"(\d{4})(\d{2})(\d{2})_(\d{4})(\d{2})(\d{2})", key)
    if block:
        y1, m1, d1, y2, m2, d2 = block.groups()
        return f"{y1}-{m1}-{d1} ~ {y2}-{m2}-{d2}"
    single = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", key)
    if single:
        y, m, d = single.groups()
        return f"{y}-{m}-{d}"
    return key


def _imported_raster_header(catalog_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    """只读栅格头（原生坐标系 + 宽高），用于补齐元数据。

    报告第二轮 P2：「元数据仍缺原生坐标系和宽高，而统计工具已返回 EPSG:6933
    与宽度；宜复用栅格头信息」。这里只 open 一下读 profile，不读像元；
    任何异常都返回空 dict（由调用方给 None），**绝不编造坐标系**。
    """
    try:
        from app.services.overlay_registry import get_overlay_spec

        spec = get_overlay_spec(catalog_id)
        if spec is None:
            return {}
        time_key = str(meta.get("default_time") or "").strip()
        if time_key:
            time_key = str(spec.resolve_time_key(time_key) or time_key)
        path = spec.resolve_source_path(time_key or None)
        if path is None:
            return {}
        import rasterio

        with rasterio.open(path) as ds:
            crs = ds.crs
            return {
                "crs": str(crs) if crs else None,
                "epsg": crs.to_epsg() if crs else None,
                "width": int(ds.width),
                "height": int(ds.height),
            }
    except Exception:
        logger.debug("raster header unavailable for %s", catalog_id, exc_info=True)
        return {}


def _imported_overlay_meta(catalog_id: str) -> dict[str, Any] | None:
    """imported-* 产物的元数据（从产物目录的 meta.json / bounds.json 读，只读）。

    与 get_layer_coverage / sample_layer_point 共用同一个来源判定
    （layer_identity），保证「来源 / 变量 / 单位 / 时间块」三处口径一致。
    不是 imported-* 或目录不存在时返回 None，由调用方继续走原来的错误分支。
    """
    if not catalog_id.startswith("imported-"):
        return None
    try:
        import json as _json

        from app.data_io.services.paths import safe_import_child

        dest = safe_import_child(catalog_id)
    except Exception:
        logger.debug("imported meta dir unavailable for %s", catalog_id, exc_info=True)
        return None
    if not dest.is_dir():
        return None

    meta: dict[str, Any] = {}
    meta_path = dest / "meta.json"
    if meta_path.is_file():
        try:
            loaded = _json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except Exception:
            logger.debug("bad meta.json for %s", catalog_id, exc_info=True)

    bounds_meta: dict[str, Any] = {}
    extent_out: dict[str, float] | None = None
    bounds_path = dest / "bounds.json"
    if bounds_path.is_file():
        try:
            blob = _json.loads(bounds_path.read_text(encoding="utf-8"))
            if isinstance(blob, dict):
                if isinstance(blob.get("meta"), dict):
                    bounds_meta = blob["meta"]
                bb = blob.get("bounds")
                if isinstance(bb, list) and len(bb) == 4:
                    extent_out = {
                        "west": float(bb[0]),
                        "south": float(bb[1]),
                        "east": float(bb[2]),
                        "north": float(bb[3]),
                    }
        except Exception:
            logger.debug("bad bounds.json for %s", catalog_id, exc_info=True)

    time_list = meta.get("time_list")
    if not isinstance(time_list, list):
        time_list = []
    blocks = [str(t) for t in time_list if t]
    first_block = blocks[0] if blocks else None
    last_block = blocks[-1] if blocks else None
    coverage_text: str | None = None
    if first_block and last_block:
        start = _format_block_key(first_block)
        end = _format_block_key(last_block)
        coverage_text = (
            start
            if start == end
            else f"{start} 起，共 {len(blocks)} 个时间块，末块 {end}"
        )

    identity = _layer_identity_fields(catalog_id)
    # 变量口径与覆盖/点查/统计对齐（外部测试报告 优先2 验收「返回一致的变量」）：
    # 身份证给的是变量代号 sm/vod/omega，而 meta.json 的 label 常写成大写的 SM/VOD。
    # 优先用身份证口径；身份证缺失时才回落到 label，并原样留一份备查。
    raw_label = str(meta.get("label") or bounds_meta.get("variable_id") or "").strip()
    variable = identity.get("variable") or raw_label
    unit_raw = str(meta.get("unit") or "").strip()

    # 时间事实走共用函数（与覆盖/统计三处同源，报告 优先2「共用解析逻辑」）
    facts = _temporal_facts(blocks)
    header = _imported_raster_header(catalog_id, meta)

    return {
        "ok": True,
        "answer_lead": (
            f"我按「{_qualified_layer_name(catalog_id, _layer_display_name(catalog_id))}」"
            f"（{catalog_id}）取数"
        ),
        "layer": {
            "layer_id": catalog_id,
            "display_name": _qualified_layer_name(
                catalog_id, _layer_display_name(catalog_id)
            ),
            "description": "运行期产物图层（本地已物化的科学栅格）。"
            + (
                f" 源文件 {meta['source_filename']}"
                if meta.get("source_filename")
                else ""
            ),
            "category": "imported",
            "status": "ready",
            "workflow_id": str(meta.get("workflow_id") or ""),
            "workflow_name": "",
            "engine": "local",
            "run_readiness": "ready",
            "run_readiness_summary": "本地产物已注册为 overlay",
            "run_readiness_notes": [],
            "supports_time": bool(blocks),
            "is_realtime": False,
            "temporal_coverage": coverage_text,
            # 与 catalog 图层的返回结构对齐：运行产物没有「描述符声明」，
            # 时间覆盖本来就来自真实 time_list，因此永远不冲突。
            "declared_temporal_coverage": None,
            "actual_temporal_coverage": coverage_text,
            "coverage_conflict": False,
            "coverage_note": None,
            # 报告第二轮 P2：元数据缺「原生坐标系 / 宽高」。
            # 复用同一条 overlay spec 只读栅格头（不读像元），失败给 None，绝不编造。
            "crs": header.get("crs"),
            "epsg": header.get("epsg"),
            "width": header.get("width"),
            "height": header.get("height"),
            "extent": extent_out,
            "tags": ["imported", "local"],
            # 与覆盖/取值两处对齐的来源与变量信息
            "source": identity.get("source"),
            "source_label": identity.get("source_label"),
            "variable": variable,
            "variable_label": identity.get("variable_label") or raw_label,
            "raw_label": raw_label or None,
            "unit": unit_raw or identity.get("unit"),
            "unit_label": identity.get("unit_label"),
            "time_blocks": facts["time_blocks"],
            "block_count": facts["block_count"],
            "period_start": facts["period_start"],
            "period_end": facts["period_end"],
            "native_step": str(meta.get("native_step") or "") or None,
            # native_step 是「原始步长声明」，不等于「真有几帧」。
            # 下面三项才是可以直接照着说的结论（外部测试报告 优先3）。
            "is_single_block": facts["is_single_block"],
            "time_span_days": facts["time_span_days"],
            "temporal_summary": facts["temporal_summary"],
            # 时序形态：运行产物里常见「单日帧 + 8 天块 + 季均块」混装，
            # 模型必须知道这一层到底是逐日动态还是跨段合成（报告第 1/2 条）。
            **_temporal_shape_fields(blocks, layer_id=catalog_id),
        },
    }


def _local_time_keys(catalog_id: str) -> list[str]:
    """图层的本地时间帧（覆盖 / 元数据 / 统计三处共用的唯一入口）。

    先问 overlay 注册表（会按需从 ``<imports>/<id>/meta.json`` 惰性加载）；
    ``imported-*`` 拿不到时再直接读盘上 meta.json。任何异常都返回空列表，
    **绝不编造日期**——空列表本身就是「这一层没有本地产物」这个事实。
    """
    keys: list[str] = []
    try:
        from app.services.overlay_registry import get_overlay_spec

        spec = get_overlay_spec(catalog_id)
        if spec is not None:
            keys = [str(d) for d in (spec.time_list or [])[:366] if d is not None]
    except Exception:
        logger.debug("overlay time_list unavailable for %s", catalog_id, exc_info=True)
    if not keys and catalog_id.startswith("imported-"):
        # 兜底：直接读盘上 meta.json 的 time_list
        try:
            from app.data_io.services.paths import safe_import_child
            import json as _json

            meta_path = safe_import_child(catalog_id) / "meta.json"
            if meta_path.is_file():
                loaded = _json.loads(meta_path.read_text(encoding="utf-8"))
                raw = loaded.get("time_list") if isinstance(loaded, dict) else None
                if isinstance(raw, list):
                    keys = [str(d) for d in raw[:366] if d is not None]
        except Exception:
            logger.debug("meta time_list unavailable for %s", catalog_id, exc_info=True)
    return keys


_OND_CACHE: dict[str, tuple[float, list[str]]] = {}


def _ondemand_frame_dates(catalog_id: Any) -> list[str]:
    """按需补帧（NAS 单日）在图层目录里留下的单日帧日期，升序去重。

    ``nas_ondemand.ensure_frame`` 的补帧模式**刻意不写 meta.json**（见
    ``nas_ondemand/service.py`` 的 ``target_layer_id`` 说明：为保住「勾选/添加
    图层仍是原来的长序列」），所以 ``time_list`` 里根本看不到这些单日帧，但
    磁盘上确实存在 ``preview_<YYYYMMDD>.png`` / ``source_<YYYYMMDD>.tif``。

    对外描述必须基于「磁盘上真有什么」，否则会出现「取的是单日帧、回答却说
    取的是块合成值」这种**反向**口径错误。2026-10-28 实测：某层 ``time_list``
    只有一个 63 天块，目录里却已有 6 个补出的单日帧，广州 79 像元 / 0.1257
    正是来自 20251215 那个单日帧，而回答写的是「整块合成值」。

    只认 8 位纯数字：块键（含 ``_``）和任何带路径分隔符的串都不会进入结果，
    从形态上堵死路径穿越。任何异常一律返回空列表——宁缺勿编。
    """
    lid = str(catalog_id or "").strip()
    if not lid.startswith("imported-"):
        return []
    try:
        from app.data_io.services.paths import safe_import_child

        layer_dir = safe_import_child(lid)
        if not layer_dir.is_dir():
            return []
        stamp = layer_dir.stat().st_mtime
    except Exception:
        return []
    hit = _OND_CACHE.get(lid)
    if hit is not None and hit[0] == stamp:
        return list(hit[1])
    found: set[str] = set()
    try:
        for entry in layer_dir.iterdir():
            name = entry.name
            if name.startswith("preview_") and name.endswith(".png"):
                tag = name[8:-4]
            elif name.startswith("source_") and name.endswith(".tif"):
                tag = name[7:-4]
            else:
                continue
            if len(tag) == 8 and tag.isdigit():
                found.add(tag)
    except OSError:  # 目录不可读时按「没有」处理，别把 500 抛给前端
        return []
    out = sorted(found)
    # 目录 mtime 在补帧写入新文件时会变，够用作失效键；补帧是低频操作。
    _OND_CACHE[lid] = (stamp, out)
    return list(out)


def _temporal_shape_fields(time_list: Any, layer_id: Any = None) -> dict[str, Any]:
    """图层的「时序形态」——模型区分「逐日动态」与「整段合成/平均」的唯一依据。

    外部报告第 1/2 条（复合指令串错产品、说"不是当天独立观测"）的物理根因：
    ``imported-136c60293bbf`` 这类目录里同时躺着单日帧、8 天窗块和跨季季均块，
    而 meta 里 ``variable_id`` / ``label`` / ``category`` / ``run_id`` 全相同的两个
    图层（逐日动态 vs 整季平均）在 search_layers 结果里**长得一模一样**，模型
    只能靠 id 猜。这里把 ``time_list`` 的形状显式说出来。

    ``mixed`` 表示这一层自己就混装了粒度不同的帧——此时"某一天的值"必须说清
    命中的是哪一片，不能当成当天观测。

    ``hybrid`` 表示 ``time_list`` 里只有多日块、但目录里已经按需补出了单日帧
    （NAS 补帧不写 meta）。此时「这一层非逐日」这句话是**错的**：能按天取数，
    只是时间清单里没登记。回答必须说「按需补出的单日帧」，不得说「块合成值」。
    """
    keys = [str(k) for k in (time_list or []) if k]
    daily = [k for k in keys if len(k) == 8 and k.isdigit()]
    blocks = [k for k in keys if "_" in k]
    ondemand = [t for t in _ondemand_frame_dates(layer_id) if t not in daily]
    try:
        from app.services.overlay_registry import _block_span_days

        longest = max((_block_span_days(k) for k in blocks), default=0)
    except Exception:  # pragma: no cover
        longest = 0
    if daily and blocks:
        shape = "mixed"
    elif daily:
        shape = "daily_series"
    elif ondemand:
        shape = "hybrid"
    elif len(blocks) <= 1 and blocks:
        shape = "single_block"
    elif blocks:
        shape = "block_series"
    else:
        shape = "unknown"
    out: dict[str, Any] = {
        "temporal_shape": shape,
        "daily_frame_count": len(daily),
        "block_count": len(blocks),
        "longest_block_days": longest,
        "ondemand_frame_count": len(ondemand),
        "daily_available": bool(daily or ondemand),
    }
    if ondemand:
        # 只给最近几天 + 总数，避免把几十个日期塞进上下文
        out["ondemand_dates"] = ondemand[-10:]
    if shape == "mixed":
        out["shape_warning"] = (
            "该图层的 time_list 同时含单日帧与多日块（最长 "
            f"{longest} 天），粒度不统一：引用「某一天」时必须说明实际命中的是哪一片，"
            "不得把跨多天的合成块当成当天的独立观测。"
        )
    elif shape == "hybrid":
        out["shape_warning"] = (
            f"该图层 time_list 只有 {len(blocks)} 个多日块（最长 {longest} 天），"
            f"但目录里已按需补出 {len(ondemand)} 个单日帧（最近："
            + "、".join(ondemand[-3:])
            + "）。因此「这一层只能取块合成值」是错的："
            "命中补帧单日时，必须说这是「按需补出的单日帧」，"
            "不得说成块合成值或整段平均。"
        )
    return out


def _value_basis(catalog_id: Any, actual_key: Any) -> dict[str, Any]:
    """这次的值到底出自哪种帧——回答表述的**唯一依据**。

    2026-10-28 实测的翻车：某层 ``time_list`` 只有一个 63 天块，目录里却已按需
    补出 6 个单日帧。统计确实命中了 ``20251215`` 的补帧（广州 79 像元 / 0.1257），
    但因为 ``temporal_summary`` 只说「1 片 63 天，非逐日」，回答就写成「取到的
    其实是整块合成值」——值与口径**反向**。这里把「值出自哪种帧」先定死，
    模型只能照着说，不能自己推理。
    """
    key = str(actual_key or "").strip()
    if not key:
        return {"kind": "none", "note": "没有命中任何时间片，不得给出数值。"}
    if "_" in key:
        return {
            "kind": "block",
            "note": (
                f"本次值出自多日合成块 {key}，不是某一天的独立观测；"
                "引用时必须说明这是跨天合成值，并给出块的起止日期。"
            ),
        }
    if key in _ondemand_frame_dates(catalog_id):
        return {
            "kind": "ondemand_frame",
            "note": (
                f"本次值出自按需补出的单日帧 {key}（NAS 单日反演，"
                "未登记在该层 time_list 里）。这就是当天的独立观测，"
                "不得说成块合成值或整段平均。"
            ),
        }
    return {
        "kind": "daily_frame",
        "note": f"本次值出自图层自带的单日帧 {key}，是当天的独立观测。",
    }


_MONTH_IN_TEXT_RE = re.compile(r"(\d{4})[-/年](\d{1,2})")


def _text_months(text: Any) -> set[tuple[int, int]]:
    """从描述文本里抠出所有「年-月」，例如 ``2025-12-01 to 2025-12-31``。

    只认 4 位年 + 分隔符 + 1~2 位月，``9km``/``L3``/``20251201`` 都不会误命中。
    """
    out: set[tuple[int, int]] = set()
    for year_s, month_s in _MONTH_IN_TEXT_RE.findall(str(text or "")):
        try:
            year, month = int(year_s), int(month_s)
        except ValueError:
            continue
        if 1970 <= year <= 2100 and 1 <= month <= 12:
            out.add((year, month))
    return out


def _key_months(keys: list[str]) -> set[tuple[int, int]]:
    """时间片键（``20251201`` 或 ``20251201_20260201``）→ 覆盖到的「年-月」。"""
    out: set[tuple[int, int]] = set()
    for key in keys or []:
        for part in str(key).split("_"):
            if len(part) != 8 or not part.isdigit():
                continue
            year, month = int(part[:4]), int(part[4:6])
            if 1970 <= year <= 2100 and 1 <= month <= 12:
                out.add((year, month))
    return out


def _coverage_consistency(declared: Any, keys: list[str]) -> dict[str, Any]:
    """「描述里声明的时间」与「盘上真实时间片」的一致性判定（只读、可解释）。

    这是外部测试报告第 1 条（同一图层宣称 2025-12、实物却是 2023-01）的
    结构性修复：旧 ``get_layer_meta`` 把描述符里的 ``temporal_coverage``
    原样返回，而 ``get_layer_coverage`` 读的是真实 ``time_list``，两个工具
    于是自相矛盾、模型随便挑一个念。现在元数据里同时给出两侧事实和冲突标记。
    """
    declared_months = _text_months(declared)
    actual_months = _key_months(keys)
    facts = _temporal_facts(keys)
    conflict = bool(declared_months and actual_months) and not bool(
        declared_months & actual_months
    )
    actual_text = None
    if actual_months:
        ordered = sorted(actual_months)
        first, last = ordered[0], ordered[-1]
        actual_text = f"{first[0]:04d}-{first[1]:02d} ~ {last[0]:04d}-{last[1]:02d}"
    note = None
    if conflict and actual_text:
        note = (
            f"描述里写的时间（{declared}）与图层实际产物（{actual_text}）不一致，"
            "必须以实际产物为准；不要念描述里的日期。"
        )
    elif not keys:
        note = "该图层暂无本地时间片，时间覆盖只能看在线通道（channels.online）。"
    return {
        "conflict": conflict,
        "declared": str(declared) if declared else None,
        "actual_text": actual_text,
        "actual_months": actual_months,
        "note": note,
        "facts": facts,
    }


def _get_layer_meta(args: dict[str, Any], *, cred: Any) -> dict[str, Any]:
    """Return safe metadata for one catalog layer (ACL filtered)."""
    catalog_id = str(args.get("catalog_id") or "").strip()
    if not catalog_id:
        return {"ok": False, "error": "catalog_id 不能为空"}

    accessible = _filter_ids([catalog_id], cred)
    if catalog_id not in set(accessible):
        return {"ok": False, "error": f"无权访问图层: {catalog_id}"}

    from app.services.layer_catalog import get_layer_descriptor

    desc = get_layer_descriptor(catalog_id)
    if desc is None:
        # imported-* 是运行期产物，不在 catalog_seeds 里（外部测试报告 优先2）：
        # 旧实现只查描述符 ⇒ 同一个 ID 覆盖查询成功、元数据却回「未找到图层」。
        imported = _imported_overlay_meta(catalog_id)
        if imported is not None:
            return imported
        return {"ok": False, "error": f"未找到图层: {catalog_id}"}

    tags = getattr(desc, "tags", None) or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    extent = getattr(desc, "extent", None)
    extent_out: dict[str, float] | None = None
    if extent is not None:
        try:
            extent_out = {
                "west": float(extent.west),
                "south": float(extent.south),
                "east": float(extent.east),
                "north": float(extent.north),
            }
        except (TypeError, ValueError, AttributeError):
            extent_out = None
    notes = getattr(desc, "run_readiness_notes", None) or []
    if not isinstance(notes, list):
        notes = [str(notes)]
    declared_coverage = str(getattr(desc, "temporal_coverage", "") or "") or None
    # 描述符里的时间覆盖只是「声明」，可能与盘上产物不一致（报告 第 1 条）。
    # 这里同时给出真实时间片与冲突标记，让模型没机会只念声明。
    actual_keys = _local_time_keys(catalog_id)
    consistency = _coverage_consistency(declared_coverage, actual_keys)
    facts = consistency["facts"]
    layer = {
        "layer_id": str(getattr(desc, "layer_id", "") or catalog_id),
        "display_name": str(getattr(desc, "display_name", "") or catalog_id),
        "description": str(getattr(desc, "description", "") or "")[:500],
        "category": str(getattr(desc, "category", "") or ""),
        "status": str(getattr(desc, "status", "") or ""),
        "workflow_id": str(getattr(desc, "workflow_id", "") or ""),
        "workflow_name": str(getattr(desc, "workflow_name", "") or ""),
        "engine": str(getattr(desc, "engine", "") or ""),
        "run_readiness": str(getattr(desc, "run_readiness", "") or ""),
        "run_readiness_summary": str(getattr(desc, "run_readiness_summary", "") or "")[
            :300
        ]
        or None,
        "run_readiness_notes": [str(n)[:160] for n in notes[:8]],
        "supports_time": bool(getattr(desc, "supports_time", False)),
        "is_realtime": bool(getattr(desc, "is_realtime", False)),
        # temporal_coverage 保留旧字段名（兼容老调用），但语义改为「声明值」；
        # 想回答"这层到底有哪些日期"必须看 actual_temporal_coverage。
        "temporal_coverage": declared_coverage,
        "declared_temporal_coverage": declared_coverage,
        "actual_temporal_coverage": consistency["actual_text"],
        "actual_block_count": facts["block_count"],
        "actual_time_blocks": list(facts["time_blocks"])[:8],
        "actual_period_start": facts["period_start"],
        "actual_period_end": facts["period_end"],
        "temporal_summary": facts["temporal_summary"],
        # 时序形态：回答「是逐日动态还是跨段合成」的唯一依据
        **_temporal_shape_fields(actual_keys, layer_id=catalog_id),
        "coverage_conflict": bool(consistency["conflict"]),
        "coverage_note": consistency["note"],
        "extent": extent_out,
        "tags": [str(t)[:64] for t in tags[:20]],
        # 身份与产品族：同名图层必须能区分「SMAP 动态 / SMAP 平均 × SM / VOD / ω」
        **_layer_identity_fields(
            catalog_id, display=str(getattr(desc, "display_name", "") or "")
        ),
    }
    # 产品族（method-*）：自身无栅格，必须引导到具体变量层，
    # 否则模型只会回一句「这是目录参考层、算不了」。
    if layer.get("is_product_group"):
        _members = layer.get("group_members") or []
        layer["layer_kind"] = "product_group"
        layer["group_hint"] = "这是一个产品族，本身不是可直接统计的栅格层。" + (
            f"本机已有 {len(_members)} 个变量产物，请指定其中一个再统计。"
            if _members
            else "本条产品族在本机还没有任何产物，需要先跑工作流。"
        )
    return {"ok": True, "layer": layer}


def _get_workflow_meta(args: dict[str, Any], *, cred: Any) -> dict[str, Any]:
    """Return safe workflow definition summary (ACL filtered)."""
    workflow_id = str(args.get("workflow_id") or "").strip()
    if not workflow_id:
        return {"ok": False, "error": "workflow_id 不能为空"}

    accessible = _filter_resource_ids([workflow_id], cred, resource_type="workflow")
    if workflow_id not in set(accessible):
        return {"ok": False, "error": f"无权访问工作流: {workflow_id}"}

    from app.services.workflow_definition_service import (
        get_definition,
        list_definitions,
    )

    listing = None
    for item in list_definitions() or []:
        if isinstance(item, dict) and str(item.get("workflow_id") or "") == workflow_id:
            listing = item
            break

    definition = get_definition(workflow_id)
    if definition is None and listing is None:
        return {"ok": False, "error": f"未找到工作流: {workflow_id}"}

    nodes_raw = (
        (definition or {}).get("nodes") if isinstance(definition, dict) else None
    )
    node_summaries: list[dict[str, str]] = []
    if isinstance(nodes_raw, list):
        for node in nodes_raw[:40]:
            if not isinstance(node, dict):
                continue
            props = (
                node.get("properties")
                if isinstance(node.get("properties"), dict)
                else {}
            )
            node_summaries.append(
                {
                    "id": str(node.get("id") or "")[:64],
                    "type": str(node.get("type") or props.get("type") or "")[:64],
                    "title": str(
                        props.get("title") or props.get("name") or node.get("id") or ""
                    )[:120],
                }
            )

    meta = (definition or {}).get("_meta") if isinstance(definition, dict) else None
    if not isinstance(meta, dict):
        meta = {}
    tags = (listing or {}).get("tags") if listing else meta.get("tags")
    if not isinstance(tags, list):
        tags = []

    return {
        "ok": True,
        "workflow": {
            "workflow_id": workflow_id,
            "name": str(
                (listing or {}).get("name")
                or (definition or {}).get("name")
                or workflow_id
            ),
            "description": str(
                (listing or {}).get("description")
                or (definition or {}).get("description")
                or ""
            )[:800],
            "engine": str((listing or {}).get("engine") or meta.get("engine") or ""),
            "kind": str((listing or {}).get("kind") or meta.get("kind") or ""),
            "category": str(
                (listing or {}).get("category") or meta.get("category") or ""
            ),
            "linked_layer_id": (listing or {}).get("linked_layer_id")
            or meta.get("linked_layer_id"),
            "is_template": bool(
                (listing or {}).get("is_template", meta.get("is_template", False))
            ),
            "tags": [str(t)[:64] for t in tags[:20]],
            "node_count": len(node_summaries)
            or int((listing or {}).get("node_count") or 0),
            "nodes": node_summaries,
        },
    }


def _web_search(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.agent.web_search import run_web_search

    try:
        limit = int(args.get("limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    return run_web_search(str(args.get("query") or ""), limit=limit)


def _parse_lng_lat(
    args: dict[str, Any],
    client_context: dict[str, Any] | None,
) -> tuple[float, float] | dict[str, Any]:
    """Resolve WGS84 point from args or client_context.map_point."""
    lng = args.get("lng", args.get("lon", args.get("longitude")))
    lat = args.get("lat", args.get("latitude"))
    if lng is None or lat is None:
        mp = None
        if isinstance(client_context, dict):
            mp = client_context.get("map_point")
        if isinstance(mp, dict):
            lng = mp.get("lng", mp.get("lon", mp.get("longitude")))
            lat = mp.get("lat", mp.get("latitude"))
    try:
        lng_f = float(lng)
        lat_f = float(lat)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": "需要有效的 lng/lat，或先在地图上选点（client_context.map_point）",
        }
    if not (-180.0 <= lng_f <= 180.0 and -90.0 <= lat_f <= 90.0):
        return {"ok": False, "error": "坐标超出 WGS84 范围"}
    return lng_f, lat_f


def _sample_layer_point(
    args: dict[str, Any],
    *,
    cred: Any,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sample overlay/weather value(s) at a map point."""
    parsed = _parse_lng_lat(args, client_context)
    if isinstance(parsed, dict):
        return parsed
    lng, lat = parsed
    time_key = str(args.get("time") or "").strip() or None

    catalog_id = str(args.get("catalog_id") or "").strip()
    targets: list[str] = []
    if catalog_id:
        targets = [catalog_id]
    elif isinstance(client_context, dict):
        raw_ids = client_context.get("active_catalog_ids")
        if isinstance(raw_ids, list):
            targets = [str(x).strip() for x in raw_ids if str(x).strip()]
        if not targets:
            raw_layers = client_context.get("active_layers")
            if isinstance(raw_layers, list):
                for layer in raw_layers:
                    if isinstance(layer, dict) and layer.get("catalog_id"):
                        cid = str(layer["catalog_id"]).strip()
                        if cid and cid not in targets:
                            targets.append(cid)
    targets = targets[:8]
    if not targets:
        return {
            "ok": False,
            "lng": lng,
            "lat": lat,
            "error": "未指定 catalog_id，且客户端无活动图层",
        }

    # 运行时栅格（imported-*/wf-run-*）：client_context 携带 overlay_layer_id，
    # catalog_id → overlay id 映射（overlay 采样以实际 overlay id 为准）
    overlay_id_by_catalog: dict[str, str] = {}
    display_by_catalog: dict[str, str] = {}
    if isinstance(client_context, dict):
        layers_ctx = client_context.get("active_layers")
        if isinstance(layers_ctx, list):
            for layer in layers_ctx:
                if not isinstance(layer, dict):
                    continue
                cid = str(layer.get("catalog_id") or "").strip()
                oid = str(layer.get("overlay_layer_id") or "").strip()
                name = str(layer.get("name") or "").strip()
                if cid and oid:
                    overlay_id_by_catalog[cid] = oid
                if cid and name:
                    display_by_catalog[cid] = name

    accessible = set(_filter_ids(targets, cred))
    samples: list[dict[str, Any]] = []
    for lid in targets:
        if lid not in accessible:
            samples.append({"catalog_id": lid, "ok": False, "error": "无权访问该图层"})
            continue
        samples.append(
            _sample_one_layer(
                lid,
                lng=lng,
                lat=lat,
                time=time_key,
                overlay_id=overlay_id_by_catalog.get(lid),
                display=display_by_catalog.get(lid),
            )
        )

    return {
        "ok": True,
        "lng": lng,
        "lat": lat,
        "time": time_key,
        "count": len(samples),
        "samples": samples,
    }


def _overlay_quality(spec: Any, raw: dict[str, Any]) -> tuple[str, str]:
    """给一次 overlay 采样打个质量标记 ``(code, 中文说明)``。

    只依据**本次采样真实拿到的信息**判断，不猜：
    - 有 error ⇒ error
    - value 为 None ⇒ nodata（该像元无有效值）
    - value 落在产品 palette 常规范围外 ⇒ out_of_range（可能是异常值/单位不符）
    - 其余 ⇒ good
    """
    if raw.get("error"):
        return "error", "取不到值"
    val = raw.get("value")
    if val is None:
        return "nodata", "缺测（该像元无有效值）"
    vmin = getattr(spec, "vmin", None)
    vmax = getattr(spec, "vmax", None)
    try:
        if isinstance(vmin, (int, float)) and float(val) < float(vmin):
            return "out_of_range", "低于该产品常规取值范围"
        if isinstance(vmax, (int, float)) and float(val) > float(vmax):
            return "out_of_range", "高于该产品常规取值范围"
    except (TypeError, ValueError):
        pass
    return "good", "有效"


def _layer_identity_fields(
    catalog_id: str, *, display: str | None = None
) -> dict[str, Any]:
    """R07：来源 / 变量 / 单位（失败降级为空 dict，绝不打断点查）。"""
    try:
        from app.services.agent.layer_identity import identity_fields

        return identity_fields(catalog_id, display_name=display)
    except Exception:  # pragma: no cover
        logger.debug("layer identity unavailable for %s", catalog_id, exc_info=True)
        return {}


# 产品族名里的通用尾词：去掉后得到「SMAP 动态」「风云卫星 平均」这种短名，
# 让用户嘴里的「SMAP 动态产品」也能匹配到页面上那一层。
_GROUP_LABEL_NOISE = ("散射约束产品", "散射约束", "卫星")


def _short_group_label(label: Any) -> str:
    text = str(label or "")
    for token in _GROUP_LABEL_NOISE:
        text = text.replace(token, "")
    return " ".join(text.split()).strip()


def _layer_names(layer_id: str, fallback: str | None = None) -> tuple[str, str]:
    """返回 ``(展示名, 搜索别名串)``。

    页面上常同时挂着 SMAP 动态 / SMAP 平均 / 风云动态 / 风云平均 四族各三变量
    （SM / VOD / ω）共 12 层，其中 4 层都叫「土壤水分」——前端只把侧栏变量名
    传上来（``agent-chat-helpers.ts`` 的 ``name: l.name``），产品和口径信息全丢。
    这里用产物的来源图层补出产品族名，得到可辨识的唯一名，例如
    ``SMAP 动态散射约束产品 · 土壤水分``。
    """
    base = str(fallback or "").strip()
    try:
        fields = _layer_identity_fields(layer_id, display=base or None)
    except Exception:  # pragma: no cover
        return (base or str(layer_id), base or str(layer_id))
    group = str(fields.get("product_group_label") or "").strip()
    var = str(fields.get("variable_label") or "").strip()
    if group and var and not group.endswith(var):
        qualified = f"{group} · {var}"
    else:
        qualified = group or base or var or str(layer_id)
    short = _short_group_label(group)
    alias_parts = [qualified, short, group, var, base]
    if short and var:
        alias_parts.append(f"{short} · {var}")
    # 用户打字常不带空格或用简称（「风云平均」「smap动态」「SMAP动态产品」），
    # 所以别名再补一份去空格的紧凑写法。
    for text in list(alias_parts):
        compact = str(text).replace(" ", "")
        if compact and compact != text:
            alias_parts.append(compact)
    aliases = " ".join(p for p in alias_parts if p)
    return (qualified, aliases)


def _qualified_layer_name(layer_id: str, fallback: str | None = None) -> str:
    """图层展示名（补全产品族，见 :func:`_layer_names`）。"""
    return _layer_names(layer_id, fallback)[0]


def _sample_one_layer(
    catalog_id: str,
    *,
    lng: float,
    lat: float,
    time: str | None,
    overlay_id: str | None = None,
    display: str | None = None,
) -> dict[str, Any]:
    from app.services.layer_catalog import get_layer_descriptor
    from app.services.overlay_registry import get_overlay_spec
    from app.weatherengine.constants import WEATHER_LAYER_SPECS

    display = display or catalog_id
    desc = get_layer_descriptor(catalog_id)
    if desc is not None:
        display = str(getattr(desc, "display_name", "") or display or catalog_id)

    # 运行时栅格图层：catalog_id 无 overlay spec，须用实际 overlay id 采样
    spec = get_overlay_spec(overlay_id or catalog_id)
    if spec is not None:
        # R07：来源 / 变量 / 物理单位由身份证统一给出（spec.unit 可能是变量标签）
        identity = _layer_identity_fields(catalog_id, display=display)
        try:
            raw = spec.resolve_value(lng, lat, time)
            quality, quality_label = _overlay_quality(spec, raw)
            payload = {
                "ok": True,
                "kind": "overlay",
                "catalog_id": catalog_id,
                "display_name": display,
                "value": raw.get("value"),
                "time": raw.get("time") or time,
                # 每条样值自带"请求日期 / 实际时间块"（外部测试报告 优先3）：
                # 六个图层各是一片不同区间时，模型不会再把上一层的区间套到下一层。
                "requested_time": raw.get("requested_time", time),
                "actual_time": raw.get("actual_time"),
                "period_start": raw.get("period_start"),
                "period_end": raw.get("period_end"),
                "is_single_block": raw.get("is_single_block"),
                "quality": quality,
                "quality_label": quality_label,
                "error": raw.get("error"),
                **identity,
                # 原始 unit 只留作排查线索，不再当成"单位"对外输出
                "unit_raw": raw.get("unit"),
            }
            return payload
        except Exception as exc:
            logger.exception("overlay sample failed for %s", catalog_id)
            return {
                "ok": False,
                "kind": "overlay",
                "catalog_id": catalog_id,
                "display_name": display,
                "quality": "error",
                "quality_label": "采样失败",
                "error": f"overlay 采样失败: {exc}",
                **identity,
            }

    if catalog_id in WEATHER_LAYER_SPECS:
        try:
            from app.weatherengine.service import weather_engine_service

            wx = weather_engine_service.get_point_weather(
                layer_id=catalog_id,
                latitude=lat,
                longitude=lng,
                forecast_hours=1,
            )
            payload = wx.model_dump(mode="json") if hasattr(wx, "model_dump") else {}
            current = payload.get("current") if isinstance(payload, dict) else None
            summary: dict[str, Any] = {
                "ok": True,
                "kind": "weather",
                "catalog_id": catalog_id,
                "display_name": display,
                "quality": "good",
                "quality_label": "实时数据",
                "provider": payload.get("provider")
                if isinstance(payload, dict)
                else None,
                "model": payload.get("model") if isinstance(payload, dict) else None,
            }
            if isinstance(current, dict):
                # Keep a small subset of numeric/string fields
                slim: dict[str, Any] = {}
                for key, val in list(current.items())[:24]:
                    if isinstance(val, (int, float, str, bool)) or val is None:
                        slim[str(key)[:64]] = val
                summary["current"] = slim
                # Prefer a primary scalar if present
                for key in (
                    "temperature_2m",
                    "precipitation",
                    "wind_speed_10m",
                    "relative_humidity_2m",
                    "visibility",
                ):
                    if key in slim:
                        summary["value"] = slim[key]
                        summary["metric"] = key
                        break
            return summary
        except Exception as exc:
            logger.warning("weather point sample failed for %s: %s", catalog_id, exc)
            return {
                "ok": False,
                "kind": "weather",
                "catalog_id": catalog_id,
                "display_name": display,
                "quality": "error",
                "quality_label": "实时数据获取失败",
                "error": f"天气点查失败: {exc}",
            }

    return {
        "ok": False,
        "kind": "unsupported",
        "catalog_id": catalog_id,
        "display_name": display,
        "quality": "unsupported",
        "quality_label": "该图层暂不支持按点取数",
        "error": "该图层暂无 overlay/天气点采样能力",
        **_layer_identity_fields(catalog_id, display=display),
    }


def _product_class(layer_id: str) -> str:
    """按编号族判断「参考层」还是「反演/自产层」，供模型决定要不要反问。

    报告 第 2 条（反演产品 vs L3 官方参考产品）需要一个**可判定**的信号：
    ``ref-*`` 是随目录发布的参考/官方层，``imported-`` / ``method-`` / ``prod-``
    是本机反演或物化的产物。两族同名时（例如都叫 SMAP 土壤水分）用户没说清，
    模型应当反问而不是自选一个。
    """
    lid = str(layer_id or "")
    if lid.startswith("imported-"):
        return "derived_product"
    if lid.startswith(("method-", "prod-")):
        return "derived_product"
    if lid.startswith("ref-"):
        return "reference_layer"
    return "catalog_other"


def _page_layer_index(
    client_context: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """``client_context.active_layers`` → ``{图层 id: {name, visible, selected}}``。

    一个图层可能同时有 catalog_id / instance_id / overlay_layer_id 三个别名，
    登记同一份信息，避免模型拿着其中一个 id 搜不到。

    **catalog_id 重复时不予登记**：产品族下一个 catalog_id 会挂 SM / VOD / ω
    三个产物（例如 `method-smap-omega-doy-dynamic` 对应三个 imported-*），
    拿它当别名只会指向「第一个变量」，查到的是错层——比查不到更容易答错。
    """
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(client_context, dict):
        return out
    layers = client_context.get("active_layers")
    if not isinstance(layers, list):
        return out
    cid_count: dict[str, int] = {}
    for item in layers:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("catalog_id") or "").strip()
        if cid:
            cid_count[cid] = cid_count.get(cid, 0) + 1
    for item in layers:
        if not isinstance(item, dict):
            continue
        info = {
            "name": str(item.get("name") or "").strip(),
            "visible": bool(item.get("visible")),
            "selected": bool(item.get("selected")),
        }
        for key in ("overlay_layer_id", "catalog_id", "instance_id"):
            lid = str(item.get(key) or "").strip()
            if not lid:
                continue
            if key == "catalog_id" and cid_count.get(lid, 0) > 1:
                continue
            out.setdefault(lid, info)
    return out


def _page_timeline_date(client_context: dict[str, Any] | None) -> str | None:
    """``client_context.timeline.date`` —— 页面时间轴当前停在哪一天。

    前端已按 ``formatLocalDateKey`` 写成 ``YYYY-MM-DD``；这里原样返回，
    由 ``_parse_date8`` 统一归一，避免两处各写一套日期格式转换。
    """
    if not isinstance(client_context, dict):
        return None
    timeline = client_context.get("timeline")
    if not isinstance(timeline, dict):
        return None
    raw = str(timeline.get("date") or "").strip()
    return raw or None


def _page_default_layer(client_context: dict[str, Any] | None) -> str | None:
    """页面上「该拿来统计」的那一层：selected 优先 → 可见 → 无。

    只认运行时产物（``imported-*`` / ``wf-run-*``）：目录参考层（``ref-*``）
    多半没有本地栅格，选它只会换来一句「不是本地栅格产物」。
    """
    if not isinstance(client_context, dict):
        return None
    layers = client_context.get("active_layers")
    if not isinstance(layers, list):
        return None
    candidates: list[tuple[int, str]] = []
    for item in layers:
        if not isinstance(item, dict):
            continue
        lid = ""
        for key in ("overlay_layer_id", "catalog_id", "instance_id"):
            val = str(item.get(key) or "").strip()
            if val:
                lid = val
                break
        if not lid:
            continue
        if not (lid.startswith("imported-") or lid.startswith("wf-run-")):
            continue
        score = (3 if item.get("selected") else 0) + (2 if item.get("visible") else 0)
        candidates.append((score, lid))
    if not candidates:
        return None
    # 稳定排序：同分时保留 active_layers 里的原始顺序
    candidates.sort(key=lambda pair: -pair[0])
    return candidates[0][1]


def _page_runtime_candidates(
    client_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """页面上所有**可统计**的运行时图层及其时序形态。

    外部报告第 1 条（「SMAP 动态产品」却回了平均产品的 0.1664）的直接成因：
    页面上同时挂着一个逐日动态层和一个整季平均层，两者 ``variable_label`` 都是
    「土壤水分」，模型看不见差别，`_page_default_layer` 又只能按 selected/visible
    挑一个。这里把候选连同 ``temporal_shape`` 一起交出去，模型才能发现
    「我用的这层是 single_block，而用户要的是动态」并换层重算。
    """
    out: list[dict[str, Any]] = []
    if not isinstance(client_context, dict):
        return out
    layers = client_context.get("active_layers")
    if not isinstance(layers, list):
        return out
    seen: set[str] = set()
    for item in layers:
        if not isinstance(item, dict):
            continue
        lid = ""
        for key in ("overlay_layer_id", "catalog_id", "instance_id"):
            val = str(item.get(key) or "").strip()
            if val:
                lid = val
                break
        if not lid or lid in seen:
            continue
        if not (lid.startswith("imported-") or lid.startswith("wf-run-")):
            continue
        seen.add(lid)
        _base = str(item.get("name") or "").strip() or _layer_display_name(lid)
        _identity = _layer_identity_fields(lid, display=_base)
        out.append(
            {
                "layer_id": lid,
                # 候选之间必须能区分：4 层都可能叫「土壤水分」，只报原名等于没报
                "display_name": _qualified_layer_name(lid, _base),
                "sidebar_name": _base,
                "visible": bool(item.get("visible")),
                "selected": bool(item.get("selected")),
                **_temporal_shape_fields(_local_time_keys(lid), layer_id=lid),
                "product_family": _identity.get("product_family"),
                "variable_label": _identity.get("variable_label"),
            }
        )
    return out


def _slim_layer_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """压掉检索结果里的空值与重复字段。

    实测（2026-10-29）：12 层页面 + 产品族成员的完整条目共 7960 字符、约 2400 token，
    而 20000 token 的单次上限里系统词已占 6000+。其中大半是 ``null``、
    与 ``display_name`` 重复的 ``sidebar_name``、以及 ``variable``/``variable_id``
    这类模型用不到的次级字段。只保留做判定真正要用的，内容一个不少：
    ``layer_id``、``display_name``、``on_page``、``layer_kind``、``product_class``、
    ``temporal_shape``、``product_family``、``variable_label``、``group_members``。
    """
    out: dict[str, Any] = {}
    # 这些字段模型从来不用：category/source 只是分类噪音，variable/unit 与
    # variable_label/unit_label 重复，product_group_label 与 display_name 同值。
    _DROP = {
        "sidebar_name",
        "category",
        "source",
        "variable",
        "unit",
        "origin_catalog_id",
        "variable_id",
    }
    for key, val in entry.items():
        if key in _DROP:
            continue
        # 检索结果里不重复解释：temporal_shape/计数已足够，mixed/hybrid 的表述规则
        # 在系统提示词里已写死（这两项合计 10 条结果要 480+ token）。
        if key in {"shape_warning", "ondemand_dates"}:
            continue
        if val is None or val == "" or val == [] or val == {}:
            continue
        # 三个布尔只在为真时才带，缺省即假，省 3×N 个字段
        if key in {"on_page", "visible", "selected"} and not val:
            continue
        if key == "product_group_label" and val == entry.get("display_name"):
            continue
        if key == "description":
            val = str(val)[:40]
        if key == "source_detail":
            val = str(val)[:16]
        if key == "group_hint":
            val = "产品族，本身不是栅格层；请从 group_members 选一个变量层再统计"
        if key == "group_members" and isinstance(val, list):
            members: list[dict[str, Any]] = []
            for m in val:
                if not isinstance(m, dict):
                    continue
                mid = m.get("overlay_layer_id") or m.get("layer_id")
                if not mid:
                    continue
                members.append(
                    {
                        "overlay_layer_id": mid,
                        "variable_label": m.get("variable_label") or m.get("variable"),
                    }
                )
            if not members:
                continue
            val = members
        out[key] = val
    return out


def _search_layers(
    args: dict[str, Any],
    *,
    cred: Any,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按关键词找图层：**页面上正在用的图层优先**，目录参考层排后面。

    外部测试报告第 2 条（「反演产品 vs L3 参考产品，Agent 选错了层」）的根因是
    旧实现只搜 catalog_seeds：运行产物 ``imported-*`` 根本不入库，于是用户说
    「SMAP」时只能搜到 ``ref-smap-*-l3`` 这类参考层，模型就顺手用了它，完全
    无视页面当前选中的那一层。现在把 ``client_context.active_layers`` 并进来，
    并给每条结果打 ``on_page`` 标记，供模型按「页面优先」裁决。
    """
    query = str(args.get("query") or "").strip()
    try:
        limit = int(args.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(50, limit))
    if not query:
        return {"ok": False, "error": "query 不能为空"}

    from app.core.config import settings
    from app.services.layer_catalog import get_layer_catalog

    q = query.casefold()
    page = _page_layer_index(client_context)

    # 用户嘴里常带「产品/图层/那一层」这类通用词（「SMAP动态产品」「风云平均产品」），
    # 而图层名里未必有。匹配时允许多种写法，命中任一即可。
    q_variants: set[str] = {q}
    for tail in ("这一层", "那个图层", "产品", "图层", "数据", "的"):
        if tail in q:
            trimmed = q.replace(tail, "").strip()
            if trimmed:
                q_variants.add(trimmed)
    q_variants = {v for v in q_variants if v}

    # 用户（和模型转述时）常把「来源 + 产品族 + 变量」连成一串，例如
    # 「SMAP 平均散射约束产品 土壤水分」。整串做子串匹配命中 0 条——
    # 实测（2026-10-29）：这种问法返回 count=0，模型只好退化到页面选中层，
    # 于是问「SMAP 平均」却答了风云的数据。这里再按分词做一次「全部命中」匹配。
    q_tokens = [
        tok
        for tok in re.split(r"[\s·・,，、/|的]+", q)
        if len(tok) >= 2 and not tok.isdigit()
    ]

    def _match_score(text: str) -> int:
        """命中强度：整串/去尾词命中 99，否则按分词命中个数打分（0=不命中）。"""
        low = str(text).casefold()
        if any(v in low for v in q_variants):
            return 99
        if len(q_tokens) < 2:
            return 0
        # 分词多数命中：允许「土壤水分」这种变量词只出现在 group_members 里而
        # 不在族名里（「SMAP 平均散射约束产品」这个名字本身不含「土壤水分」），
        # 否则整串问法又退回 0 条。
        hit = sum(1 for tok in q_tokens if tok in low)
        need = 2 if len(q_tokens) <= 3 else -(-len(q_tokens) * 3 // 5)
        return hit if hit >= need else 0

    def _hit(text: str) -> bool:
        return _match_score(text) > 0

    # ① 页面上的图层：先按名字/编号匹配，命中的排最前（selected > visible）
    # 注意：``page`` 里同一图层会按 overlay_layer_id / catalog_id / instance_id
    # 登记三次（为了模型用任一个 id 都搜得到），这里必须按图层去重，否则
    # 12 层会被报成 36 条，既误导模型也把上下文撑爆。
    page_hits: list[dict[str, Any]] = []
    reported: set[int] = set()
    for lid, info in page.items():
        if id(info) in reported:
            continue
        base_name = info["name"] or _layer_display_name(lid) or lid
        qualified, aliases = _layer_names(lid, base_name)
        # 名字匹配强度优先于 selected：用户点名「SMAP 平均」时，命中最强的那层
        # 必须排在前面，否则模型看到第一条是 selected 的风云层就顺手用了。
        score = _match_score(f"{lid} {qualified} {aliases}")
        if not score:
            continue
        reported.add(id(info))
        entry: dict[str, Any] = {
            "layer_id": lid,
            "display_name": qualified,
            # 侧栏原名（多为「土壤水分」），保留给模型解释「用户点的是哪个」
            "sidebar_name": base_name,
            "on_page": True,
            "visible": bool(info["visible"]),
            "selected": bool(info["selected"]),
            "_match": score,
            "layer_kind": "runtime_product"
            if lid.startswith("imported-")
            else "page_layer",
            "product_class": _product_class(lid),
            # 逐日动态 / 8 天块 / 跨季平均：模型据此区分同名不同产品
            **_temporal_shape_fields(_local_time_keys(lid), layer_id=lid),
            **_layer_identity_fields(lid, display=base_name),
        }
        page_hits.append(entry)
    page_hits.sort(
        key=lambda e: (
            -int(e.get("_match") or 0),
            0 if e.get("selected") else 1,
            0 if e.get("visible") else 1,
            0 if str(e.get("layer_id") or "").startswith("imported-") else 1,
            str(e.get("layer_id") or ""),
        )
    )
    for e in page_hits:
        e.pop("_match", None)
    # 页面上出现过的图层（任一别名）都不再作为「目录层」重复列出，
    # 否则同一产品会以 imported-* 和 method-* 两个身份各说一遍。
    seen = set(page.keys())

    # ② 目录里的图层（catalog_seeds）：去掉已经在页面上的重复项
    catalog = get_layer_catalog()
    items = list(catalog.items or [])
    env = (settings.environment or "").strip().lower()
    if env not in {"development", "dev", "test", "testing"}:
        items = [i for i in items if getattr(i, "status", None) != "placeholder"]

    layer_ids = [str(getattr(i, "layer_id", "") or "") for i in items]
    accessible = _filter_ids(layer_ids, cred)
    accessible_set = set(accessible)

    catalog_hits: list[dict[str, Any]] = []
    for item in items:
        lid = str(getattr(item, "layer_id", "") or "")
        if not lid or lid not in accessible_set or lid in seen:
            continue
        display = str(getattr(item, "display_name", "") or "")
        desc = str(getattr(item, "description", "") or "")
        tags = getattr(item, "tags", None) or []
        tag_s = " ".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)
        qualified, aliases = _layer_names(lid, display)
        blob = f"{lid} {display} {desc} {tag_s} {aliases}".casefold()
        if not _hit(blob):
            continue
        info = page.get(lid)
        _shape_keys = _local_time_keys(lid)
        _identity = _layer_identity_fields(lid, display=display)
        entry: dict[str, Any] = {
            "layer_id": lid,
            "display_name": qualified,
            "sidebar_name": display,
            "category": str(getattr(item, "category", "") or ""),
            "description": desc[:200],
            "on_page": info is not None,
            "visible": bool(info["visible"]) if info else False,
            "selected": bool(info["selected"]) if info else False,
            "layer_kind": "catalog_reference",
            "product_class": _product_class(lid),
            # 仅在真有本地时间片时给出形态，避免参考层一堆 unknown 噪音
            **(
                _temporal_shape_fields(_shape_keys, layer_id=lid) if _shape_keys else {}
            ),
            **_identity,
        }
        # 产品族（method-*）：本身不承载栅格，必须告诉模型「去挑哪一个变量」，
        # 否则模型只能回一句「是目录参考层、算不了」。
        if _identity.get("is_product_group"):
            _members = _identity.get("group_members") or []
            entry["layer_kind"] = "product_group"
            entry["group_hint"] = "这是一个产品族，本身不是可直接统计的栅格层。" + (
                f"本机已有 {len(_members)} 个变量产物，请指定其中一个再统计。"
                if _members
                else "本条产品族在本机还没有任何产物，需要先跑工作流。"
            )
        catalog_hits.append(entry)
    # 目录层里 imported-* 也优先于 ref-* 之类的参考层
    catalog_hits.sort(
        key=lambda e: (
            0 if e.get("on_page") else 1,
            0 if str(e.get("layer_id") or "").startswith("imported-") else 1,
            str(e.get("layer_id") or ""),
        )
    )

    hits = (page_hits + catalog_hits)[:limit]
    payload: dict[str, Any] = {
        "ok": True,
        "query": query,
        "count": len(hits),
        "layers": [_slim_layer_entry(h) for h in hits],
        "page_active_count": len(page_hits),
    }
    if page_hits:
        payload["selection_hint"] = (
            "on_page=true 的图层是用户页面上正在加载/选中的，排在前面；"
            "用户说的卫星名（SMAP/风云）只是来源，不等于目录里的参考图层。"
            "页面上的运行产物（layer_kind=runtime_product）优先于 catalog_reference。"
        )
    return payload


def _filter_ids(layer_ids: list[str], cred: Any) -> list[str]:
    return _filter_resource_ids(layer_ids, cred, resource_type="layer")


def _filter_resource_ids(
    resource_ids: list[str],
    cred: Any,
    *,
    resource_type: str,
) -> list[str]:
    if cred is None:
        return list(resource_ids)
    role = getattr(cred, "role", None)
    if role == "admin":
        return list(resource_ids)
    user_id = getattr(cred, "user_id", None)
    source = getattr(cred, "source", None)
    if user_id is None:
        if source in {"service_key", "dev_bypass"}:
            return list(resource_ids)
        return []
    try:
        from app.services.permission_repository import get_permission_repository

        return get_permission_repository().batch_filter_accessible(
            int(user_id), resource_type, resource_ids
        )
    except Exception:
        logger.exception("ACL filter failed for %s", resource_type)
        return []


def catalog_summary(*, cred: Any = None, limit: int = 40) -> list[dict[str, str]]:
    """Lightweight id/name list for system prompt injection."""
    from app.core.config import settings
    from app.services.layer_catalog import get_layer_catalog

    catalog = get_layer_catalog()
    items = list(catalog.items or [])
    env = (settings.environment or "").strip().lower()
    if env not in {"development", "dev", "test", "testing"}:
        items = [i for i in items if getattr(i, "status", None) != "placeholder"]
    ids = [str(getattr(item, "layer_id", "") or "") for item in items]
    accessible = set(_filter_ids(ids, cred))
    out: list[dict[str, str]] = []
    for item in items:
        lid = str(getattr(item, "layer_id", "") or "")
        if lid not in accessible:
            continue
        display = str(getattr(item, "display_name", "") or lid)
        row: dict[str, str] = {"layer_id": lid, "display_name": display}
        # R07：目录清单里也带来源，模型不必从名字猜卫星
        identity = _layer_identity_fields(lid, display=display)
        source = identity.get("source")
        if source and source != "unknown":
            row["source"] = str(source)
            row["source_label"] = str(identity.get("source_label") or "")
        variable = identity.get("variable")
        if variable and variable != "unknown":
            row["variable"] = str(variable)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _list_workflow_runs(args: dict[str, Any], *, cred: Any) -> dict[str, Any]:
    """List recent workflow runs with owner scoping (mirrors GET /workflow-runs)."""
    from shared.contracts.api_contracts import ExecutionStatus

    active_only = bool(args.get("active_only", False))
    status_filter = str(args.get("status") or "").strip() or None
    try:
        limit = int(args.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(50, limit))

    from app.services.workflow_repository import SQLiteWorkflowRepository

    repo = SQLiteWorkflowRepository()
    all_runs = list(repo.list_runs() or [])
    uid, role = _cred_meta(cred)
    if role != "admin":
        if uid is not None:
            owners = repo.list_run_user_ids()
            all_runs = [r for r in all_runs if owners.get(r.run_id) == uid]
        else:
            all_runs = []
    if status_filter:
        all_runs = [r for r in all_runs if r.status.value == status_filter]
    if active_only:
        active = {
            ExecutionStatus.accepted,
            ExecutionStatus.queued,
            ExecutionStatus.running,
            ExecutionStatus.retry_pending,
        }
        all_runs = [r for r in all_runs if r.status in active]
    all_runs = sorted(all_runs, key=lambda r: r.created_at, reverse=True)[:limit]
    items = []
    for r in all_runs:
        items.append(
            {
                "run_id": r.run_id,
                "status": r.status.value,
                "layer_id": getattr(r, "layer_id", None),
                "command_label": getattr(r, "command_label", None),
                "created_at": r.created_at.isoformat()
                if getattr(r, "created_at", None)
                else None,
                "progress": getattr(r, "progress", None),
            }
        )
    return {"ok": True, "count": len(items), "runs": items}


def _get_workflow_run(args: dict[str, Any], *, cred: Any) -> dict[str, Any]:
    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        return {"ok": False, "error": "run_id 不能为空"}
    from app.services.workflow.service_container import submission_service
    from app.services.workflow_repository import SQLiteWorkflowRepository

    run_status = submission_service.get_workflow_run(run_id)
    if run_status is None:
        return {"ok": False, "error": f"未找到 run: {run_id}"}
    uid, role = _cred_meta(cred)
    if role != "admin":
        if uid is None:
            return {"ok": False, "error": f"未找到 run: {run_id}"}
        owner = SQLiteWorkflowRepository().get_run_user_id(run_id)
        if owner is None or owner != uid:
            return {"ok": False, "error": f"未找到 run: {run_id}"}
    return {
        "ok": True,
        "run": {
            "run_id": run_status.run_id,
            "status": run_status.status.value,
            "layer_id": getattr(run_status, "layer_id", None),
            "command_label": getattr(run_status, "command_label", None),
            "progress": getattr(run_status, "progress", None),
            "message": getattr(run_status, "message", None),
            "created_at": run_status.created_at.isoformat()
            if getattr(run_status, "created_at", None)
            else None,
            "updated_at": run_status.updated_at.isoformat()
            if getattr(run_status, "updated_at", None)
            else None,
        },
    }


def _parse_date8(value: Any) -> str | None:
    """把 '2025-12-15' / '20251215' / '2025/12/15' / '2017-01' 统一成 'YYYYMMDD'。

    **块键 ``YYYYMMDD_YYYYMMDD`` 原样返回**：它是图层 ``time_list`` 里的真实时间片键。
    截成起始日会让「明确要这一整段」变成「只取第一天」——2026-10-29 实测：
    点名 ``20251201_20260201`` 合成块，被补帧单日 ``20251201`` 抢先命中，
    统计结果从 643,731 个像元变成当日单帧。
    """
    if value is None:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{8}_\d{8}", text):
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    if len(digits) == 6:  # 'YYYY-MM' → 当月第一天
        return digits + "01"
    if len(digits) == 4:  # 'YYYY' → 当年第一天
        return digits + "0101"
    return None


def _resolve_coverage(
    *,
    requested: str | None,
    local_dates: list[str],
    online: dict[str, Any],
) -> dict[str, Any]:
    """把"在线通道 / 本地通道"两套互不相干的结果合并成一句"这天到底有没有数据"。

    报告 R09/R10 的口径：不能只看 ``local.count=0`` 就说没数据，
    也不能因为两个日期取值相同就判断"日期切换坏了" —— 后者通常是
    两个日期命中了同一个时间块（如 ``20251203_20251231``）。
    """
    if not requested:
        return {
            "status": "unknown",
            "channel": None,
            "actual_time": None,
            "reason": "未指定日期；下面只列出两通道的覆盖明细，请按实际日期再问一次",
        }

    # 1) 逐日帧精确命中
    if requested in local_dates:
        return {
            "status": "available",
            "channel": "local",
            "actual_time": requested,
            "reason": f"本地时序里有 {requested} 这一逐日帧",
        }

    # 2) 命中某个时间块（区间帧 / 月块）
    for item in local_dates:
        if "_" not in item:
            continue
        start, _, end = item.partition("_")
        start8, end8 = _parse_date8(start), _parse_date8(end)
        if start8 and end8 and start8 <= requested <= end8:
            exact_day = start8 == end8
            return {
                "status": "available",
                "channel": "local",
                "actual_time": item,
                "reason": (
                    f"本地没有 {requested} 的独立逐日帧，该日期落在时间块 "
                    f"{item} 内，取的是这一块的值"
                    + (
                        ""
                        if exact_day
                        else "（所以相邻日期取值相同是正常的，不是日期切换失效）"
                    )
                ),
            }

    # 3) 本地没有，但在线通道声明可获取
    if online.get("available"):
        start8 = _parse_date8(online.get("coverage_start"))
        end8 = _parse_date8(online.get("coverage_end"))
        in_range = (
            start8
            and end8
            and (start8 <= requested <= end8)
            or (start8 and end8 is None and requested >= start8)
            or (end8 and start8 is None and requested <= end8)
        )
        if in_range:
            return {
                "status": "available",
                "channel": "online",
                "actual_time": None,
                "reason": (
                    f"本地暂无 {requested}，但在该图层的在线获取范围内"
                    "（需要触发现场获取后才有结果，不是已经算好的成品）"
                ),
            }
        return {
            "status": "unavailable",
            "channel": None,
            "actual_time": None,
            "reason": (
                f"{requested} 不在该图层的覆盖范围内"
                f"（在线可获取范围 {online.get('coverage_start')} ~ "
                f"{online.get('coverage_end')}）"
            ),
        }

    if local_dates:
        return {
            "status": "unavailable",
            "channel": None,
            "actual_time": None,
            "reason": (
                f"本地有 {len(local_dates)} 个时间点，但没有覆盖 {requested} 的帧，"
                "且该图层未开放在线获取"
            ),
        }
    return {
        "status": "unavailable",
        "channel": None,
        "actual_time": None,
        "reason": "本地没有任何已物化的时间帧，且该图层未开放在线获取",
    }


def _get_layer_coverage(args: dict[str, Any], *, cred: Any) -> dict[str, Any]:
    catalog_id = str(args.get("catalog_id") or args.get("layer_id") or "").strip()
    if not catalog_id:
        return {"ok": False, "error": "catalog_id 不能为空"}
    requested = _parse_date8(args.get("time") or args.get("date"))
    accessible = _filter_ids([catalog_id], cred)
    if catalog_id not in set(accessible):
        return {"ok": False, "error": f"无权访问图层: {catalog_id}"}
    from app.services.layer_catalog import get_layer_descriptor

    descriptor = get_layer_descriptor(catalog_id)
    cap = descriptor.online_temporal if descriptor else None
    if cap is None or not getattr(cap, "enabled", False):
        online: dict[str, Any] = {
            "available": False,
            "coverage_start": None,
            "coverage_end": None,
            "native_step": None,
        }
    else:
        online = {
            "available": True,
            "coverage_start": getattr(cap, "coverage_start", None),
            "coverage_end": getattr(cap, "coverage_end", None),
            "native_step": getattr(cap, "native_step", None),
        }
    # 本地时间帧：唯一入口（与 get_layer_meta / get_layer_statistics 同源）。
    # 注：旧实现直接调 overlay_asset_workflow_service.get_overlay_state()，
    # 但该方法并不存在 ⇒ 异常被吞 ⇒ local 永远为空（报告 R09/R10 的根因）。
    local_dates: list[str] = _local_time_keys(catalog_id)
    resolved = _resolve_coverage(
        requested=requested, local_dates=local_dates, online=online
    )
    # ★ 2026-10-28：真实命中必须与 get_layer_statistics 同源。
    # NAS 按需补出来的单日帧**不在** time_list 里，但 overlay spec 认它
    # （_has_ondemand_frame 放行）。旧实现只看 local_dates，会把「2025-12-15 补帧」
    # 说成「落在块 20251211~20251218 内」，模型据此回答「不是当天独立观测」，
    # 与统计返回的 is_daily_frame=true 直接打架（外部报告第 2 条）。
    hit_key: str | None = None
    hit_source = "none"
    if requested:
        try:
            from app.services.overlay_registry import get_overlay_spec

            _spec = get_overlay_spec(catalog_id)
            if _spec is not None:
                hit_key = _spec.resolve_time_key(requested, prefer_finest=True)
        except Exception:
            logger.debug(
                "coverage resolve_time_key failed for %s", catalog_id, exc_info=True
            )
        if hit_key:
            hit_source = "block" if str(hit_key) in local_dates else "ondemand_frame"
    if not hit_key:
        hit_key = resolved.get("actual_time")
        hit_source = "block" if hit_key else "none"
    # 时间事实与元数据/统计同源（报告 优先2「共用解析逻辑」）：
    # period_* 描述「这次实际命中的那一片」，is_single_block/span 描述「整层只有几片」。
    facts = _temporal_facts(local_dates)
    hit_start, hit_end = _block_period(hit_key)
    _cov_display = _qualified_layer_name(catalog_id, _layer_display_name(catalog_id))
    return {
        "ok": True,
        "catalog_id": catalog_id,
        "display_name": _cov_display,
        # 与统计同款固定句式：回答第一句原样照抄，必须带 catalog_id
        "answer_lead": f"我按「{_cov_display}」（{catalog_id}）取数",
        "requested_time": requested,
        # R09/R10：一句话回答"这天到底有没有"，channels 明细保留兼容旧调用
        "resolved": resolved,
        # 顶层 actual_time 是**权威命中**（含按需补帧的单日帧），与统计口径一致
        "actual_time": hit_key,
        "hit_source": hit_source,
        "is_daily_frame": bool(hit_key) and "_" not in str(hit_key),
        "period_start": hit_start,
        "period_end": hit_end,
        "block_count": facts["block_count"],
        "time_blocks": facts["time_blocks"],
        "is_single_block": facts["is_single_block"],
        "time_span_days": facts["time_span_days"],
        "temporal_summary": facts["temporal_summary"],
        # 报告 第 3 条：不许自己编「改查 12 月 15 日」。
        # 这里给的就是该层真实有的日期，模型要提替代日期只能从这里挑。
        "available_dates": _nearby_dates(local_dates, requested),
        # 时序形态：与 meta / statistics 三处同源，避免「覆盖说混装、统计说单块」
        **_temporal_shape_fields(local_dates, layer_id=catalog_id),
        # 这个值出自补帧单日 / 自带单日 / 多日块——回答只能照此表述
        "value_basis": _value_basis(catalog_id, hit_key),
        "channels": {
            "online": online,
            # local.dates 与上面的 time_blocks 是同一份 73 个键，重复三遍把单次
            # 返回撑到 3.6k 字符（多轮累计直接顶爆 20000 token 上限，2026-10-29
            # 实测「时间清单有几片」被中止）。这里只留条数，明细看 time_blocks。
            "local": {"count": len(local_dates)},
        },
        **_layer_identity_fields(catalog_id),
    }


def _nearby_dates(keys: list[str], requested: str | None) -> dict[str, Any]:
    """该图层真实可用的相邻日期（前 3 / 后 3），供「没有这一天」时如实引用。"""
    ordered = [str(k) for k in (keys or []) if k]
    if not ordered:
        return {
            "first": None,
            "last": None,
            "count": 0,
            "before": [],
            "after": [],
        }
    before: list[str] = []
    after: list[str] = []
    req = str(requested or "").strip()
    if req:
        before = [k for k in ordered if k < req][-3:]
        after = [k for k in ordered if k >= req][:3]
    else:
        after = ordered[:3]
    return {
        "first": ordered[0],
        "last": ordered[-1],
        "count": len(ordered),
        "before": before,
        "after": after,
    }


def _layer_display_name(catalog_id: str) -> str | None:
    """图层中文名；产物图层用身份证里的变量名，绝不回落成 id。"""
    try:
        from app.services.layer_catalog import get_layer_descriptor

        desc = get_layer_descriptor(catalog_id)
        if desc is not None:
            name = str(getattr(desc, "display_name", "") or "").strip()
            if name:
                return name
    except Exception:  # pragma: no cover
        pass
    try:
        from app.services.agent.layer_identity import resolve_layer_identity
        from app.services.agent.naming import UNKNOWN_LAYER_NAME

        label = resolve_layer_identity(catalog_id).get("variable_label")
        return str(label) if label else UNKNOWN_LAYER_NAME
    except Exception:  # pragma: no cover
        return None


def _block_period(key: str | None) -> tuple[str | None, str | None]:
    """`20251201_20260201` → ('20251201', '20260201')；单日键两个值相同。"""
    raw = str(key or "").strip()
    block = re.fullmatch(r"(\d{8})_(\d{8})", raw)
    if block:
        return block.group(1), block.group(2)
    single = re.fullmatch(r"(\d{8})", raw)
    if single:
        return single.group(1), single.group(1)
    return None, None


def _temporal_facts(blocks: Any) -> dict[str, Any]:
    """时间片键列表 → 「可以直接照着说」的时间事实（外部测试报告 优先3）。

    ★ 唯一真源：覆盖（get_layer_coverage）、元数据（get_layer_meta）、
    统计（get_layer_statistics）三处都调本函数，保证同一图层在任何工具里
    给出的片数 / 跨度 / 措辞逐字一致（报告 优先2 要求"共用解析逻辑"）。

    为什么需要它：``native_step`` 只是**原始步长声明**，不代表真有几帧。
    实测 SMAP 产物 ``native_step="1d"``、风云是 ``"1M"``，但两者都只有
    **一片**、分别跨 63 / 31 天的整段合成 ⇒ 直接念 native_step 会得出
    "每日 1 帧 / 每月 1 帧"的错误结论。
    """
    keys = [str(b) for b in (blocks or []) if b]
    out: dict[str, Any] = {
        "time_blocks": keys[:366],
        "block_count": len(keys),
        "period_start": None,
        "period_end": None,
        "is_single_block": False,
        "time_span_days": None,
        "temporal_summary": None,
    }
    if not keys:
        return out
    first_start, first_end = _block_period(keys[0])
    last_start, last_end = _block_period(keys[-1])
    out["period_start"] = first_start
    out["period_end"] = last_end
    if first_start and last_end:
        try:
            from datetime import date as _date

            _d1 = _date(
                int(first_start[:4]), int(first_start[4:6]), int(first_start[6:8])
            )
            _d2 = _date(int(last_end[:4]), int(last_end[4:6]), int(last_end[6:8]))
            out["time_span_days"] = (_d2 - _d1).days + 1
        except Exception:
            out["time_span_days"] = None
    # 「单片且这一片跨多天」才算时间块；单片单日仍是逐日帧，不能算块。
    out["is_single_block"] = bool(
        first_start and first_start != first_end and len(keys) == 1
    )
    span = out["time_span_days"]
    if out["is_single_block"] and span:
        out["temporal_summary"] = (
            f"单幅时间块 {_format_block_key(keys[0])}（共 {span} 天，非逐日）："
            "该图层只有这一片栅格，任何日期取到的都是这一整块的值"
        )
    elif len(keys) == 1:
        out["temporal_summary"] = f"仅 1 个时间片：{_format_block_key(keys[0])}"
    else:
        out["temporal_summary"] = (
            f"共 {len(keys)} 个时间片，{_format_block_key(keys[0])} 至 "
            f"{_format_block_key(keys[-1])}"
        )
    return out


def _parse_bbox(raw: Any) -> tuple[float, float, float, float] | None:
    """``[西, 南, 东, 北]``（WGS84，度）→ 4 个 float；非法返回 None。"""
    if raw is None or raw == "":
        return None
    vals: list[float] = []
    try:
        if isinstance(raw, str):
            parts = [p for p in re.split(r"[,\s]+", raw.strip()) if p]
        elif isinstance(raw, (list, tuple)):
            parts = list(raw)
        else:
            return None
        if len(parts) != 4:
            return None
        vals = [float(p) for p in parts]
    except Exception:
        return None
    west, south, east, north = vals
    if not all(abs(v) <= 1e6 for v in vals):
        return None
    if not (-180.0 <= west < east <= 180.0):
        return None
    if not (-90.0 <= south < north <= 90.0):
        return None
    return west, south, east, north


def _wgs84_bbox_window(ds: Any, bbox: tuple[float, float, float, float]) -> Any:
    """WGS84 经纬度框 → 栅格自身投影/像素下的读取窗口（越界自动裁剪）。

    统计不能假设源栅格是经纬度网格：SMAP/FY 产物是 EASE-Grid（EPSG:6933），
    直接拿 110°E/35°N 去 ``from_bounds`` 会得到错误的行列。这里先做
    WGS84 → 栅格 CRS 的边界换算，再按像素窗口读取（只读该窗口，省内存）。
    与栅格范围无交集时返回 None。
    """
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds

    west, south, east, north = bbox
    if ds.crs is not None and str(ds.crs).upper() not in {"EPSG:4326"}:
        west, south, east, north = transform_bounds(
            "EPSG:4326", ds.crs, west, south, east, north, densify_pts=21
        )
    win = from_bounds(west, south, east, north, transform=ds.transform)
    win = win.round_offsets().round_lengths()
    col0 = max(0, int(win.col_off))
    row0 = max(0, int(win.row_off))
    col1 = min(int(ds.width), int(win.col_off + win.width))
    row1 = min(int(ds.height), int(win.row_off + win.height))
    if col1 <= col0 or row1 <= row0:
        return None
    return Window(col0, row0, col1 - col0, row1 - row0)


def _window_extent_wgs84(ds: Any, window: Any = None) -> dict[str, float] | None:
    """读取窗口（默认整幅）覆盖的空间范围，换算回 WGS84 经纬度。"""
    try:
        from rasterio.warp import transform_bounds

        box = ds.window_bounds(window) if window is not None else ds.bounds
        left, bottom, right, top = (float(v) for v in box)
        if ds.crs is not None and str(ds.crs).upper() not in {"EPSG:4326"}:
            left, bottom, right, top = transform_bounds(
                ds.crs, "EPSG:4326", left, bottom, right, top, densify_pts=21
            )
        return {
            "west": round(float(left), 6),
            "south": round(float(bottom), 6),
            "east": round(float(right), 6),
            "north": round(float(top), 6),
        }
    except Exception:
        logger.debug("extent transform failed", exc_info=True)
        return None


def _raster_full_stats(
    raster_path: Any, bbox: tuple[float, float, float, float] | None = None
) -> dict[str, Any]:
    """栅格只读统计（排除 NoData），可选只统计某个经纬度框。

    用 ``masked=True`` 读取——rasterio 会按源文件 nodata 自动掩膜，
    因此 NoData 不会进均值；不做任何写回、不生成新图层。
    源文件不是 GeoTIFF（如 .mat / .nc）或读取失败时，返回中文原因而不是抛异常
    ——工具异常会让整轮对话中断。
    """
    try:
        import rasterio

        with rasterio.open(raster_path) as ds:
            window = None
            if bbox is not None:
                window = _wgs84_bbox_window(ds, bbox)
                if window is None:
                    return {
                        "ok": False,
                        "error": "bbox 与栅格实际范围没有交集（请检查经纬度顺序与数值）",
                        "extent": _window_extent_wgs84(ds),
                    }
            data = ds.read(1, window=window, masked=True)
            total = int(data.shape[0] * data.shape[1])
            count = int(data.count())
            extent = _window_extent_wgs84(ds, window)
            if count == 0:
                return {
                    "ok": False,
                    "error": "该范围内没有有效像元（全部为 NoData）",
                    "valid_pixels": 0,
                    "total_pixels": total,
                    "valid_ratio": 0.0,
                    "extent": extent,
                }
            return {
                "ok": True,
                "mean": float(data.mean()),
                "min": float(data.min()),
                "max": float(data.max()),
                "std": float(data.std()) if count > 1 else None,
                "valid_pixels": count,
                "total_pixels": total,
                "valid_ratio": round(count / total, 6) if total else None,
                "crs": ds.crs.to_string() if ds.crs else None,
                "width": int(ds.width),
                "height": int(ds.height),
                "analyzed_width": int(data.shape[1]),
                "analyzed_height": int(data.shape[0]),
                # 报告 优先1 要求"返回实际范围"：这里给出本次统计真正覆盖的经纬度框
                "extent": extent,
            }
    except Exception as exc:
        logger.debug("raster stats failed: %s", raster_path, exc_info=True)
        return {"ok": False, "error": f"栅格读取失败（可能不是 GeoTIFF 源）：{exc}"}


def _get_layer_statistics(
    args: dict[str, Any],
    *,
    cred: Any,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """整层只读统计（mean/min/max/std/有效像元数）——不建图层、不跑工作流。

    只统计「该图层该时间片的全范围有效像元」，**不是**点样本均值，
    也**不会**默认缩到当前视口（外部测试报告 优先1）。

    ★ 2026-10-28 修（外部报告第 2 条「统计没用页面日期」）：
    旧实现既拿不到 ``client_context``（分派处没传），没给 ``time`` 时又直接
    退回 ``spec.default_time``，于是页面停在 2025-12-15、问「当前图层平均值」
    却统计了 ``20260125_20260201``。现在取值优先级固定为

        显式 time → client_context.timeline.date（页面当前日期）→ 图层 default_time

    并且**如实回报来源**（``time_source``），模型才不会把"图层默认块"当成"那天"。
    """
    # ① 图层：不点名就用页面那一层（只认运行时产物，参考层没有本地栅格）
    catalog_id = str(args.get("catalog_id") or args.get("layer_id") or "").strip()
    layer_source = "requested" if catalog_id else "page"
    if not catalog_id:
        catalog_id = _page_default_layer(client_context) or ""
        if not catalog_id:
            return {
                "ok": False,
                "error": "catalog_id 不能为空：没传参，页面上也没有可统计的运行时图层",
            }
    accessible = _filter_ids([catalog_id], cred)
    if catalog_id not in set(accessible):
        return {"ok": False, "error": f"无权访问图层: {catalog_id}"}

    # ② 时间：显式 → 页面日期 → 图层默认（后者必须标注，否则就是"日期对不上"的根因）
    explicit_time = _parse_date8(args.get("time") or args.get("date"))
    page_date = _parse_date8(_page_timeline_date(client_context))
    requested = explicit_time or page_date
    if explicit_time:
        time_source = "requested"
    elif page_date:
        time_source = "page"
    else:
        time_source = "layer_default"

    # 可选空间范围（报告 优先1「输入至少包括统计范围」）：缺省＝整幅，绝不默认缩到视口
    bbox_raw = args.get("bbox")
    bbox = _parse_bbox(bbox_raw)
    if bbox is None and bbox_raw not in (None, ""):
        return {
            "ok": False,
            "catalog_id": catalog_id,
            "error": "bbox 需要 4 个数字 [西, 南, 东, 北]（WGS84 经纬度，"
            "西<东、南<北，例如 [105, 30, 115, 40]）",
        }
    from app.services.overlay_registry import get_overlay_spec

    try:
        spec = get_overlay_spec(catalog_id)
    except Exception:
        logger.debug("overlay spec unavailable for %s", catalog_id, exc_info=True)
        spec = None
    if spec is None:
        return {
            "ok": False,
            "error": "该图层不是本地栅格产物，暂不支持整层统计"
            "（请给出已加载的 imported 图层 ID）",
            "catalog_id": catalog_id,
        }

    # 只支持 GeoTIFF 源：catalog 里部分老图层是 .mat/.nc，rasterio 直接读会抛异常
    reader = str(getattr(spec, "source_reader", "") or "").strip().lower()
    if reader and reader != "geotiff":
        return {
            "ok": False,
            "catalog_id": catalog_id,
            "display_name": _qualified_layer_name(
                catalog_id, _layer_display_name(catalog_id)
            ),
            "requested_time": requested,
            "error": f"该图层的源文件是 {reader} 格式（非 GeoTIFF），暂不支持整层统计；"
            "请改用已物化为栅格的 imported-* 图层。",
        }

    spec_time = requested or getattr(spec, "default_time", None)
    # prefer_finest=True：同一天若同时落在「8 天窗块」和「跨季季均块」里，
    # 取跨度最短的那一片。否则会拿到季均块的 0.166402，回答却说成"这一天"。
    actual_key = spec.resolve_time_key(spec_time, prefer_finest=True)
    if actual_key is None:
        try:
            blocks = [str(t) for t in (getattr(spec, "time_list", None) or [])][:366]
        except Exception:
            blocks = []
        return {
            "ok": False,
            "catalog_id": catalog_id,
            "display_name": _qualified_layer_name(
                catalog_id, _layer_display_name(catalog_id)
            ),
            "requested_time": requested,
            "time_source": time_source,
            "page_date": page_date,
            "error": "该日期没有对应的栅格时间片",
            "available_blocks": blocks,
            # 报告 第 3 条：替代日期只能从真实时间片里挑，不许自己编
            "available_dates": _nearby_dates(blocks, requested),
        }

    try:
        src_path = spec.resolve_source_path(actual_key)
    except Exception:
        logger.debug("statistics source path failed for %s", catalog_id, exc_info=True)
        src_path = None
    if src_path is None:
        return {
            "ok": False,
            "catalog_id": catalog_id,
            "requested_time": requested,
            "actual_time": actual_key,
            "error": "找不到该时间片对应的栅格文件（产物可能已被清理）",
        }

    stats = _raster_full_stats(src_path, bbox=bbox)
    facts = _temporal_facts(getattr(spec, "time_list", None) or [])
    # 命中块（这次真读的那一片）与整层跨度必须分开：
    # 旧实现把 facts["period_*"]（整层首尾 20251101~20260208）当成 period_*，
    # 模型据此说「不是当天独立观测」——而提示词要的是「实际命中的数据时间块」。
    hit_start, hit_end = _block_period(actual_key)
    _stats_display = _qualified_layer_name(catalog_id, _layer_display_name(catalog_id))
    payload: dict[str, Any] = {
        "ok": bool(stats.get("ok")),
        "catalog_id": catalog_id,
        "display_name": _stats_display,
        # 回答第一句的**固定句式**：强制造句带 catalog_id，用户才能当场核对
        # 「这个数到底取自哪一层」。2026-10-29 实测：只写层名不写 id 时，
        # 模型每轮换层（动态→平均）用户完全看不出来。
        "answer_lead": f"我按「{_stats_display}」（{catalog_id}）取数",
        "scope": "bbox" if bbox is not None else "full_extent",
        "requested_bbox": list(bbox) if bbox is not None else None,
        "statistic": "mean",
        "requested_time": requested,
        # 与请求日期区分开：这才是数据实际覆盖的时间块（优先3 的前置能力）
        "actual_time": actual_key,
        # period_* = 命中块，语义与 get_layer_coverage 的 period_* 一致
        "period_start": hit_start,
        "period_end": hit_end,
        # 整层首尾另立字段，避免和命中块混用
        "layer_span_start": facts["period_start"],
        "layer_span_end": facts["period_end"],
        # 这个数是「按谁给的日期」算的：requested=显式传参 / page=页面当前日期
        # / layer_default=图层默认块（此时**不是**页面那天的数据，必须如实说明）
        "time_source": time_source,
        "page_date": page_date,
        "layer_source": layer_source,
        # actual_key 不含下划线 ⇒ 真是某一天的独立观测，而不是跨多天的块
        "is_daily_frame": "_" not in str(actual_key or ""),
        # 「整层只有一片且跨多天」——不能用 native_step 推（优先3）
        "is_single_block": facts["is_single_block"],
        "time_span_days": facts["time_span_days"],
        "block_count": facts["block_count"],
        "temporal_summary": facts["temporal_summary"],
        # 时序形态（daily_series / block_series / single_block / mixed）：
        # 让回答能自证「这一层到底是逐日动态，还是跨段合成」
        **_temporal_shape_fields(getattr(spec, "time_list", None), layer_id=catalog_id),
        # 这个值出自补帧单日 / 自带单日 / 多日块——回答只能照此表述
        "value_basis": _value_basis(catalog_id, actual_key),
        **_layer_identity_fields(catalog_id, display=_layer_display_name(catalog_id)),
        **stats,
    }
    if time_source == "layer_default":
        payload["time_source_warning"] = (
            "没有拿到页面日期，本次统计用的是该图层的默认时间块 "
            f"{actual_key}；这不代表页面上那一天的数据，回答里必须说明。"
        )
    # 报告第 1 条：页面上挂着多个同名运行时图层时，把候选（带形态）交出去。
    # 只在「没点名、按页面选层」且候选 >1 时给，避免正常单层场景刷噪音。
    if layer_source == "page":
        _cands = _page_runtime_candidates(client_context)
        if len(_cands) > 1:
            payload["page_candidates"] = _cands
            _used_shape = _temporal_shape_fields(
                getattr(spec, "time_list", None), layer_id=catalog_id
            ).get("temporal_shape")
            payload["layer_source_warning"] = (
                f"本次统计用的是页面选中图层 {catalog_id}（temporal_shape={_used_shape}）。"
                "若用户点名的产品形态与它不符（例如用户说动态/逐日，这层却是 single_block），"
                "必须从 page_candidates 里挑 temporal_shape 匹配的那一层，"
                "显式传 catalog_id 重新统计，不得直接拿这次结果回答。"
            )
    if not stats.get("ok") and "error" not in stats:
        payload["error"] = "统计失败"
    return payload


def _list_workflow_timers(args: dict[str, Any], *, cred: Any) -> dict[str, Any]:
    uid, role = _cred_meta(cred)
    if role != "admin":
        return {
            "ok": False,
            "error": "仅管理员可查看工作流定时器",
        }
    workflow_id = str(args.get("workflow_id") or "").strip() or None
    try:
        limit = int(args.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(50, limit))
    try:
        from app.services import workflow_timer_service as wts
    except Exception as exc:
        return {"ok": False, "error": f"无法加载定时器服务: {exc}"}
    timers = wts.get_timer_store().list_timers(workflow_id=workflow_id) or []
    items = [wts.timer_to_dict(t) for t in timers[:limit]]
    return {"ok": True, "count": len(items), "timers": items}


def load_server_tools_openai() -> list[dict[str, Any]]:
    """OpenAI tool defs for allowed server tools only (mtime-cached)."""
    import json
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[4]
        / "agentKits"
        / "tools"
        / "server_tools.json"
    )
    try:
        mtime = path.stat().st_mtime if path.is_file() else None
    except OSError:
        mtime = None

    cache = getattr(load_server_tools_openai, "_cache", None)
    if (
        isinstance(cache, tuple)
        and len(cache) == 2
        and cache[0] == mtime
        and mtime is not None
    ):
        return [dict(t) for t in cache[1]]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        load_server_tools_openai._cache = (mtime, [])  # type: ignore[attr-defined]
        return []
    tools_raw = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools_raw, list):
        load_server_tools_openai._cache = (mtime, [])  # type: ignore[attr-defined]
        return []
    out: list[dict[str, Any]] = []
    for item in tools_raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name not in _ALLOWED_TOOLS:
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(item.get("description") or name),
                    "parameters": item.get("args")
                    or {"type": "object", "properties": {}},
                },
            }
        )
    load_server_tools_openai._cache = (mtime, out)  # type: ignore[attr-defined]
    return [dict(t) for t in out]


def load_server_tools_anthropic() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in load_server_tools_openai():
        fn = t.get("function") or {}
        out.append(
            {
                "name": fn.get("name"),
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return out
