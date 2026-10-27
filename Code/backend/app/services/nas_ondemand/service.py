"""按需出图编排：确保「某产品 × 某变量 × 某一天」在本地有一张可显示的图。

流程（顺序即代码顺序）：
  1. 本地已有该帧 → 直接返回（**不连 NAS**）
  2. 本地没有 → 白名单校验 → NAS 取那一个 .mat
  3. 渲染成 PNG + bounds，写进 imports/imported-nas-<…>/
  4. 更新 meta.json 的 time_list / default_time
  5. 记录 last_used
  6. 检查总帧数，超 2000 就 LRU 淘汰到 1800

.mat 是中间产物（单文件 4.3 MB），渲染完立即删除，本地只留 PNG 与 JSON。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from app.services.nas_ondemand import cache, config, fetcher, renderer

logger = logging.getLogger(__name__)


class FrameError(RuntimeError):
    """按需出图失败（统一的对外错误类型）。"""


def _layer_dir(layer_id: str) -> Path:
    from app.data_io.services.paths import safe_import_child

    return safe_import_child(layer_id)


def _staging_dir() -> Path:
    from app.data_io.services.paths import imports_dir

    path = imports_dir() / "_staging" / "nas_ondemand"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_meta(layer_dir: Path) -> dict[str, Any]:
    import json

    path = layer_dir / "meta.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_meta(layer_dir: Path, meta: dict[str, Any]) -> None:
    import json

    path = layer_dir / "meta.json"
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _validate(
    product: str, variable: str
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if product not in config.PRODUCTS:
        raise FrameError(f"未知产品 {product!r}；可选：{sorted(config.PRODUCTS)}")
    var = variable.upper()
    if var not in config.VARIABLES:
        raise FrameError(f"未知变量 {variable!r}；可选：{sorted(config.VARIABLES)}")
    return var, config.PRODUCTS[product], config.VARIABLES[var]


def ensure_frame(
    product: str,
    variable: str,
    date_tag: str,
    *,
    force: bool = False,
    target_layer_id: str | None = None,
) -> dict[str, Any]:
    """确保该帧在本地可用。返回诊断字典。

    Args:
        product: fy_avg / fy_raw / smap_avg / smap_raw
        variable: SM / VOD / OMEGA
        date_tag: YYYYMMDD
        force: True 时忽略本地已有，强制重取重绘
        target_layer_id: 不给（默认）= 写进 ``imported-nas-*`` 独立图层，并维护
            该层 meta.json 的 time_list（既有行为，一个字节不改）。
            给了 = **补帧模式**：只往这个既有工作流图层目录里新增
            ``preview_<tag>.png`` + ``bounds_<tag>.json``，
            **绝不读写该层 meta.json**（time_list / default_time / native_step
            全部保持原样），从而保证「勾选/添加图层仍然是原来的长序列」。
            只接受 ``config.ONDEMAND_TARGETS`` 里登记过的图层。
    """
    started = time.time()
    tag = fetcher.assert_date_tag(date_tag)
    var, product_cfg, var_cfg = _validate(product, variable)

    target = str(target_layer_id or "").strip() or None
    if target is not None:
        spec = config.ondemand_target(target)
        if spec is None:
            raise FrameError(
                f"图层 {target!r} 未登记为按需补帧目标；"
                f"已登记：{sorted(config.ONDEMAND_TARGETS)}"
            )
        if spec["product"] != product or spec["variable"].upper() != var:
            raise FrameError(
                f"图层 {target!r} 的取数口径是 {spec['product']}/{spec['variable']}，"
                f"与请求 {product}/{var} 不一致（拒绝写错目录）"
            )

    layer_id = target or config.layer_id_for(product, var)
    layer_dir = _layer_dir(layer_id)
    if target is not None and not layer_dir.is_dir():
        raise FrameError(f"目标图层目录不存在：{layer_id}")
    png_path = layer_dir / f"preview_{tag}.png"
    bounds_path = layer_dir / f"bounds_{tag}.json"
    tif_path = layer_dir / f"source_{tag}.tif"
    # 该层如果本来就是「GeoTIFF 源 + 瓦片渲染」，单日帧也必须产出同规格的源文件。
    # 否则 /overlay-tiles/{z}/{x}/{y}.png?time=<单日> 找不到源 ⇒ 404 ⇒ 地图空白
    # （2026-10-27 现场实测：整月 200，单日 404）。
    needs_source_tif = any(layer_dir.glob("source_*.tif"))

    meta = _read_meta(layer_dir)
    time_list = [str(t) for t in (meta.get("time_list") or [])]
    # 该日期在 NAS 上对应的真实文件名（OMEGA 不是 YYYYMMDD.mat）
    filename = config.nas_filename_for(product, var, tag)

    # ── 1. 本地已有：直接返回，不连 NAS ──────────────────────────────────────
    if (
        not force
        and png_path.is_file()
        and bounds_path.is_file()
        and (not needs_source_tif or tif_path.is_file())
    ):
        cache.touch(layer_id, layer_dir, tag)
        return {
            "layer_id": layer_id,
            "time_key": tag,
            "cached": True,
            "source": "local",
            "nas_filename": filename,
            "elapsed_ms": int((time.time() - started) * 1000),
            "png": str(png_path),
            "bounds": str(bounds_path),
            "meta": {"time_list_size": len(time_list)},
        }

    # ── 2. NAS 取一个 .mat（白名单 + GET）───────────────────────────────────
    # 不预先列目录：该目录有 3800+ 个文件，列一次要 23 秒；直接取文件，
    # 404 就当作「这天没有数据」（1 秒）。OMEGA 的拉丁/希腊两种目录名按序试。
    candidates = config.nas_dir_candidates(product, var)
    staging = _staging_dir() / f"{layer_id}_{tag}{config.MAT_SUFFIX}"
    mat_bytes = 0
    render_info: dict[str, Any] = {}
    nas_dir = ""
    tried: list[str] = []
    try:
        for cand in candidates:
            nas_dir = cand.rstrip("/")
            tried.append(nas_dir)
            try:
                mat_bytes = fetcher.download_file(nas_dir, filename, staging)
                break
            except fetcher.NasFileMissing:
                continue
        else:
            # 用 NasFileMissing（→ HTTP 404）而不是 FrameError（→ 400）：
            # 「这天 NAS 上没有」是正常业务状态，不是请求写错了。前端据此提示
            # 「这天没有数据」并保持图层可用，绝不能记进负缓存把层冻掉。
            raise fetcher.NasFileMissing(
                f"NAS 上没有 {filename}（{'、'.join(tried)}）。"
                "该日期可能不在成果覆盖范围内（2015-04-01 ~ 2025-12-31），"
                "或该日无法解出反照率。"
            )
        # ── 3. 渲染 PNG + bounds ────────────────────────────────────────────
        # 补帧模式必须跟**该图层现有成品**用同一套配色/量程，否则同层里
        # 「整月合成」和「单日」颜色口径不一致，看着像换了产品。
        # 图层 meta 里的 palette/vmin/vmax 才是这一层真正在用的口径，
        # config.VARIABLES 只作为缺省兜底（不改任何数值口径）。
        palette = str(var_cfg["palette"])
        vmin = float(var_cfg["vmin"])
        vmax = float(var_cfg["vmax"])
        frame_kwargs: dict[str, Any] = {}
        if target is not None:
            if isinstance(meta.get("palette"), str) and meta["palette"].strip():
                palette = meta["palette"].strip()
            if isinstance(meta.get("vmin"), (int, float)):
                vmin = float(meta["vmin"])
            if isinstance(meta.get("vmax"), (int, float)):
                vmax = float(meta["vmax"])
            # 画幅跟着目标图层原有成品走：该层是全球 2048 方图，
            # 补帧也必须全球，否则拖动时画幅会从全球突变成中国区特写。
            frame_kwargs = {
                "clip_bounds": None,
                "target_resolution": config.GLOBAL_FRAME_RESOLUTION_DEG,
            }
            # 瓦片渲染要的是原始网格 GeoTIFF，不是上色后的 PNG
            if needs_source_tif:
                frame_kwargs["source_tif_path"] = tif_path
        render_info = renderer.render_frame(
            staging,
            variable=var,
            layer_id=layer_id,
            png_path=png_path,
            bounds_path=bounds_path,
            palette=palette,
            vmin=vmin,
            vmax=vmax,
            **frame_kwargs,
        )
    finally:
        # .mat 只是中间产物，绝不留在缓存目录（2000 帧会吃 8.6 GB）
        staging.unlink(missing_ok=True)

    # ── 4. 更新 meta.json ───────────────────────────────────────────────────
    # ⚠ 补帧模式（target）**整段跳过**：该层 meta.json 由工作流产物所有，
    #   time_list / default_time / native_step 一旦改动，「一进页面还是整月合成」
    #   这条承诺就破了（日键进 time_list 会让默认落点变成单日帧）。
    #   单日帧的可访问性靠 overlay_registry 的「目录里真有 preview_<tag>.png
    #   就放行」兜住，与 meta 无关，所以这里一个字节都不写。
    if target is None:
        if tag not in time_list:
            time_list.append(tag)
        time_list = sorted(set(time_list))
        meta.update(
            {
                "layer_id": layer_id,
                "kind": "raster",
                "category": "time-series",
                "native_step": "1d",
                "time_list": time_list,
                "default_time": time_list[-1],
                "variable_id": str(var_cfg["variable_id"]),
                "label": str(var_cfg["label"]),
                "title": f"{product_cfg['source_label']} {var_cfg['title']}（{product_cfg['constraint']}）",
                "palette": str(var_cfg["palette"]),
                "vmin": float(var_cfg["vmin"]),
                "vmax": float(var_cfg["vmax"]),
                "unit": str(var_cfg["unit"]),
                "source": "nas_ondemand",
                "nas_dir": nas_dir,
                "nas_filename": filename,
                "constraint": product_cfg["constraint"],
            }
        )
        # OMEGA 两种口径都不是「一天一个文件」：平均是年内日序气候态，
        # 动态是 8 天块。把真实口径写进 meta，看图层的人才知道这帧代表什么。
        if var == "OMEGA":
            if product.endswith("_avg"):
                meta["nas_granularity"] = (
                    "按年内日序（doy）的气候态，1 个文件对应全年同一天"
                )
            else:
                start, end = config.raw_block_span(tag)
                meta["nas_granularity"] = "8 天块，1 个文件代表一段区间"
                meta["span"] = [
                    start.strftime("%Y%m%d"),
                    end.strftime("%Y%m%d"),
                ]
        _write_meta(layer_dir, meta)

    # 根 bounds.json 是图层能否注册的硬前提（overlay_registry 要求它存在）
    root_bounds = layer_dir / "bounds.json"
    if not root_bounds.is_file():
        renderer.write_bounds(
            root_bounds,
            layer_id,
            tuple(render_info["bounds"]),  # type: ignore[arg-type]
        )

    cache.touch(layer_id, layer_dir, tag)

    # ── 5. 失效进程内注册缓存 ────────────────────────────────────────────────
    # 补帧模式下单日帧的可访问性由「文件存在」判定（见 overlay_registry），
    # 不依赖进程内缓存；这里照样失效一次，避免任何陈旧视图。
    try:
        from app.services.overlay_registry import unregister_overlay

        unregister_overlay(layer_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("失效 overlay 注册缓存失败 layer=%s: %s", layer_id, exc)

    # ── 6. 容量检查（超 2000 帧就淘汰到 1800）────────────────────────────────
    # ensure_capacity 只遍历 imported-nas-* 目录（cache._is_layer_dir 硬校验），
    # 补帧写进的是工作流图层目录 ⇒ 不会被当成缓存淘汰对象，一个都不会删。
    eviction = cache.ensure_capacity(keep_tags=[tag])

    return {
        "layer_id": layer_id,
        "time_key": tag,
        "cached": False,
        "source": "nas",
        "nas_dir": nas_dir,
        "nas_filename": filename,
        "mat_bytes": mat_bytes,
        "elapsed_ms": int((time.time() - started) * 1000),
        "png": str(png_path),
        "bounds": str(bounds_path),
        "render": render_info,
        "time_list_size": len(time_list),
        "eviction": {
            "total_before": eviction["total_before"],
            "total_after": eviction["total_after"],
            "deleted_count": len(eviction["deleted"]),
        },
    }


def ensure_layer_frame(
    layer_id: str,
    date_tag: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """「这个既有图层 × 这一天」有图可显示（前端按需补帧的唯一入口）。

    产品/变量由 ``config.ONDEMAND_TARGETS`` 反查，前端不必知道 NAS 目录语义。
    """
    spec = config.ondemand_target(layer_id)
    if spec is None:
        raise FrameError(
            f"图层 {layer_id!r} 未登记为按需补帧目标；"
            f"已登记：{sorted(config.ONDEMAND_TARGETS)}"
        )
    return ensure_frame(
        spec["product"],
        spec["variable"],
        date_tag,
        force=force,
        target_layer_id=layer_id,
    )


def cache_state() -> dict[str, Any]:
    """缓存现状（给验证接口用）。"""
    return cache.cache_state()
