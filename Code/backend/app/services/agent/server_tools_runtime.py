"""Server tool runtime for Agent (read tools immediate; run_workflow via confirmation)."""

from __future__ import annotations

import logging
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
        return _search_layers(args, cred=cred)
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
    return {
        "ok": True,
        "layer": {
            "layer_id": str(getattr(desc, "layer_id", "") or catalog_id),
            "display_name": str(getattr(desc, "display_name", "") or catalog_id),
            "description": str(getattr(desc, "description", "") or "")[:500],
            "category": str(getattr(desc, "category", "") or ""),
            "status": str(getattr(desc, "status", "") or ""),
            "workflow_id": str(getattr(desc, "workflow_id", "") or ""),
            "workflow_name": str(getattr(desc, "workflow_name", "") or ""),
            "engine": str(getattr(desc, "engine", "") or ""),
            "run_readiness": str(getattr(desc, "run_readiness", "") or ""),
            "run_readiness_summary": str(
                getattr(desc, "run_readiness_summary", "") or ""
            )[:300]
            or None,
            "run_readiness_notes": [str(n)[:160] for n in notes[:8]],
            "supports_time": bool(getattr(desc, "supports_time", False)),
            "is_realtime": bool(getattr(desc, "is_realtime", False)),
            "temporal_coverage": str(getattr(desc, "temporal_coverage", "") or "")
            or None,
            "extent": extent_out,
            "tags": [str(t)[:64] for t in tags[:20]],
        },
    }


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

    accessible = set(_filter_ids(targets, cred))
    samples: list[dict[str, Any]] = []
    for lid in targets:
        if lid not in accessible:
            samples.append({"catalog_id": lid, "ok": False, "error": "无权访问该图层"})
            continue
        samples.append(_sample_one_layer(lid, lng=lng, lat=lat, time=time_key))

    return {
        "ok": True,
        "lng": lng,
        "lat": lat,
        "time": time_key,
        "count": len(samples),
        "samples": samples,
    }


def _sample_one_layer(
    catalog_id: str,
    *,
    lng: float,
    lat: float,
    time: str | None,
) -> dict[str, Any]:
    from app.services.layer_catalog import get_layer_descriptor
    from app.services.overlay_registry import get_overlay_spec
    from app.weatherengine.constants import WEATHER_LAYER_SPECS

    display = catalog_id
    desc = get_layer_descriptor(catalog_id)
    if desc is not None:
        display = str(getattr(desc, "display_name", "") or catalog_id)

    spec = get_overlay_spec(catalog_id)
    if spec is not None:
        try:
            raw = spec.resolve_value(lng, lat, time)
            return {
                "ok": True,
                "kind": "overlay",
                "catalog_id": catalog_id,
                "display_name": display,
                "value": raw.get("value"),
                "unit": raw.get("unit"),
                "time": raw.get("time"),
                "error": raw.get("error"),
            }
        except Exception as exc:
            logger.exception("overlay sample failed for %s", catalog_id)
            return {
                "ok": False,
                "kind": "overlay",
                "catalog_id": catalog_id,
                "display_name": display,
                "error": f"overlay 采样失败: {exc}",
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
                "error": f"天气点查失败: {exc}",
            }

    return {
        "ok": False,
        "kind": "unsupported",
        "catalog_id": catalog_id,
        "display_name": display,
        "error": "该图层暂无 overlay/天气点采样能力",
    }


def _search_layers(args: dict[str, Any], *, cred: Any) -> dict[str, Any]:
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

    catalog = get_layer_catalog()
    items = list(catalog.items or [])
    env = (settings.environment or "").strip().lower()
    if env not in {"development", "dev", "test", "testing"}:
        items = [i for i in items if getattr(i, "status", None) != "placeholder"]

    layer_ids = [str(getattr(i, "layer_id", "") or "") for i in items]
    accessible = _filter_ids(layer_ids, cred)
    accessible_set = set(accessible)

    q = query.casefold()
    hits: list[dict[str, Any]] = []
    for item in items:
        lid = str(getattr(item, "layer_id", "") or "")
        if lid not in accessible_set:
            continue
        display = str(getattr(item, "display_name", "") or "")
        desc = str(getattr(item, "description", "") or "")
        tags = getattr(item, "tags", None) or []
        tag_s = " ".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)
        blob = f"{lid} {display} {desc} {tag_s}".casefold()
        if q in blob:
            hits.append(
                {
                    "layer_id": lid,
                    "display_name": display,
                    "category": str(getattr(item, "category", "") or ""),
                    "description": desc[:200],
                }
            )
        if len(hits) >= limit:
            break

    return {"ok": True, "query": query, "count": len(hits), "layers": hits}


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
        out.append(
            {
                "layer_id": lid,
                "display_name": str(getattr(item, "display_name", "") or lid),
            }
        )
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


def _get_layer_coverage(args: dict[str, Any], *, cred: Any) -> dict[str, Any]:
    catalog_id = str(args.get("catalog_id") or args.get("layer_id") or "").strip()
    if not catalog_id:
        return {"ok": False, "error": "catalog_id 不能为空"}
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
    local_dates: list[str] = []
    try:
        from app.services.overlay_asset_workflow_service import (
            overlay_asset_workflow_service,
        )

        state = overlay_asset_workflow_service.get_overlay_state(catalog_id)
        raw_dates = (state or {}).get("time_list") if isinstance(state, dict) else None
        if isinstance(raw_dates, list):
            local_dates = [str(d) for d in raw_dates[:366] if d is not None]
    except Exception:
        logger.debug("overlay time_list unavailable for %s", catalog_id, exc_info=True)
    return {
        "ok": True,
        "catalog_id": catalog_id,
        "channels": {
            "online": online,
            "local": {"dates": local_dates, "count": len(local_dates)},
        },
    }


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
