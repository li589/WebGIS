"""已导入图层导出：geojson/csv/shp-zip/geotiff/netcdf/mat（支持多编码、裁剪、CRS、字段）。"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from app.data_io.services.dbf_encoding import (
    EXPORT_ENCODING_CHOICES,
    cpg_label_for_encoding,
    encode_export_text,
    resolve_export_encoding,
    truncate_to_encoded_bytes,
)
from app.data_io.services.paths import IMPORTS_DIR
from app.data_io.services.vector import load_vector_geojson

BBoxDict = dict[str, Any]


def list_export_encodings() -> list[dict[str, str]]:
    """前端下拉用的编码选项。"""
    labels = {
        "auto": "自动（跟导入源编码；CSV 默认 UTF-8 BOM）",
        "utf-8": "UTF-8（跨平台推荐）",
        "utf-8-sig": "UTF-8 BOM（Excel / Windows CSV）",
        "gbk": "GBK（国内 ArcGIS / 超图常见）",
        "gb18030": "GB18030（国标超集）",
        "big5": "Big5（繁体中文）",
        "cp1252": "Windows-1252（西欧）",
        "cp932": "Shift-JIS / CP932（日文）",
        "latin-1": "Latin-1 / ISO-8859-1",
    }
    return [{"id": k, "label": labels.get(k, k)} for k in EXPORT_ENCODING_CHOICES]


def export_layer(
    layer_id: str,
    fmt: str,
    *,
    encoding: str | None = None,
    time: str | None = None,
    times: list[str] | None = None,
    bbox: BBoxDict | None = None,
    output_crs: str | None = None,
    fields: list[str] | None = None,
) -> tuple[bytes, str, str]:
    """返回 (content, media_type, filename).

    ``time``：单时刻切片标签（如 ``20251227_20251231``），写入文件名。
    ``times``：多时刻列表；长度 >1（或显式多选）时打包为 zip。
    ``bbox``：``{west,south,east,north,crs?}`` 裁剪到地图/指定范围。
    ``output_crs``：如 ``EPSG:4326`` / ``EPSG:3857``；缺省保持源 CRS。
    ``fields``：矢量属性字段子集。
    """
    fmt = fmt.lower().strip()
    dest = IMPORTS_DIR / layer_id
    if not dest.exists():
        raise FileNotFoundError(f"图层不存在: {layer_id}")

    meta_path = dest / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    kind = meta.get("kind")
    is_raster = (dest / "bounds.json").exists() and kind != "vector"
    is_raster = is_raster or (
        kind != "vector"
        and (dest / "preview.png").exists()
        and not (dest / "data.geojson").exists()
    )

    opts = {
        "bbox": _normalize_bbox(bbox),
        "output_crs": (str(output_crs).strip() if output_crs else None) or None,
        "fields": _normalize_fields(fields),
    }

    if is_raster:
        resolved_times = _resolve_export_times(meta, time=time, times=times)
        if len(resolved_times) > 1:
            return _export_raster_times_zip(
                dest, layer_id, fmt, meta, times=resolved_times, **opts
            )
        single = resolved_times[0] if resolved_times else time
        return _export_raster(dest, layer_id, fmt, meta, time=single, **opts)

    if (dest / "data.geojson").exists() or kind == "vector":
        return _export_vector(layer_id, fmt, meta, encoding=encoding, **opts)

    raise ValueError(f"无法识别图层类型: {layer_id}")


def _normalize_bbox(bbox: BBoxDict | None) -> BBoxDict | None:
    if not bbox or not isinstance(bbox, dict):
        return None
    try:
        west = float(bbox["west"])
        south = float(bbox["south"])
        east = float(bbox["east"])
        north = float(bbox["north"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("bbox 需包含 west/south/east/north 数值") from exc
    if east <= west or north <= south:
        raise ValueError("bbox 范围无效（east>west 且 north>south）")
    crs = str(bbox.get("crs") or "EPSG:4326").strip() or "EPSG:4326"
    return {"west": west, "south": south, "east": east, "north": north, "crs": crs}


def _normalize_fields(fields: list[str] | None) -> list[str] | None:
    if fields is None:
        return None
    cleaned = [str(f).strip() for f in fields if str(f).strip()]
    return cleaned or None


def _resolve_export_times(
    meta: dict[str, Any],
    *,
    time: str | None,
    times: list[str] | None,
) -> list[str]:
    """规范化导出时刻列表；``*`` / ``all`` 表示 time_list 全部。"""
    time_list = [str(t) for t in (meta.get("time_list") or []) if str(t).strip()]
    if times is not None:
        cleaned = [str(t).strip() for t in times if str(t).strip()]
        if len(cleaned) == 1 and cleaned[0].lower() in {"*", "all"}:
            if not time_list:
                raise ValueError("图层无 time_list，无法导出全部时刻")
            return time_list
        if not cleaned:
            return []
        if time_list:
            unknown = [t for t in cleaned if t not in time_list]
            if unknown:
                raise ValueError(f"时间切片不存在: {unknown[0]}")
        return cleaned
    if time and str(time).strip():
        key = str(time).strip()
        if key.lower() in {"*", "all"}:
            if not time_list:
                raise ValueError("图层无 time_list，无法导出全部时刻")
            return time_list
        if time_list and key not in time_list:
            raise ValueError(f"时间切片不存在: {key}")
        return [key]
    return []


def _export_raster_times_zip(
    dest: Path,
    layer_id: str,
    fmt: str,
    meta: dict[str, Any],
    *,
    times: list[str],
    bbox: BBoxDict | None = None,
    output_crs: str | None = None,
    fields: list[str] | None = None,
) -> tuple[bytes, str, str]:
    """同一图层多个时刻打包为 zip（常见多时相下载方式）。"""
    del fields  # raster N/A
    base = _export_filename_stem(layer_id, meta)
    mem = io.BytesIO()
    errors: list[str] = []
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for t in times:
            try:
                content, _media, filename = _export_raster(
                    dest,
                    layer_id,
                    fmt,
                    meta,
                    time=t,
                    bbox=bbox,
                    output_crs=output_crs,
                )
            except Exception as exc:  # noqa: BLE001 — per-slice errors into zip
                errors.append(f"{t}: {exc}")
                zf.writestr(f"{t}.error.txt", str(exc))
                continue
            zf.writestr(filename, content)
        if errors and len(errors) == len(times):
            raise ValueError(f"多时刻导出全部失败: {errors[0]}")
    stem = (
        f"{base}_{len(times)}times"
        if len(times) > 3
        else f"{base}_{times[0]}_{times[-1]}"
    )
    return mem.getvalue(), "application/zip", f"{_safe_filename_base(stem)}.zip"


def _export_vector(
    layer_id: str,
    fmt: str,
    meta: dict[str, Any],
    *,
    encoding: str | None,
    bbox: BBoxDict | None = None,
    output_crs: str | None = None,
    fields: list[str] | None = None,
) -> tuple[bytes, str, str]:
    geojson = load_vector_geojson(layer_id, preview=False)
    geojson = _apply_vector_export_options(
        geojson, bbox=bbox, output_crs=output_crs, fields=fields
    )
    safe_base = _export_filename_stem(layer_id, meta)
    out_crs = (output_crs or "EPSG:4326").strip()

    if fmt in {"geojson", "json"}:
        data = json.dumps(geojson, ensure_ascii=False).encode("utf-8")
        return data, "application/geo+json", f"{safe_base}.geojson"

    resolved = resolve_export_encoding(encoding, meta=meta, fmt=fmt)

    if fmt == "csv":
        return _export_csv(geojson, safe_base, resolved)

    if fmt in {"shp", "shp-zip", "shapefile"}:
        return _export_shp_zip(geojson, safe_base, resolved, output_crs=out_crs)

    raise ValueError(f"矢量不支持导出格式: {fmt}")


def _apply_vector_export_options(
    geojson: dict[str, Any],
    *,
    bbox: BBoxDict | None,
    output_crs: str | None,
    fields: list[str] | None,
) -> dict[str, Any]:
    features = list(geojson.get("features") or [])
    if fields is not None:
        allow = set(fields)
        filtered: list[dict[str, Any]] = []
        for feat in features:
            props = feat.get("properties") or {}
            new_props = {k: v for k, v in props.items() if str(k) in allow}
            filtered.append({**feat, "properties": new_props})
        features = filtered

    if bbox is not None:
        features = _clip_features_by_bbox(features, bbox)

    target_crs = (output_crs or "EPSG:4326").strip()
    if target_crs.upper() not in {"EPSG:4326", "WGS84", "CRS84"}:
        features = _reproject_features(features, "EPSG:4326", target_crs)

    return {**geojson, "features": features}


def _clip_features_by_bbox(
    features: list[dict[str, Any]], bbox: BBoxDict
) -> list[dict[str, Any]]:
    from shapely.geometry import box, mapping, shape
    from shapely.ops import transform as shp_transform

    west, south, east, north = (
        bbox["west"],
        bbox["south"],
        bbox["east"],
        bbox["north"],
    )
    clip_crs = str(bbox.get("crs") or "EPSG:4326")
    clip_poly = box(west, south, east, north)
    if clip_crs.upper() not in {"EPSG:4326", "WGS84", "CRS84"}:
        try:
            from pyproj import Transformer

            tf = Transformer.from_crs(clip_crs, "EPSG:4326", always_xy=True)

            def _xf(x: float, y: float, z: float | None = None):
                lng, lat = tf.transform(x, y)
                return (lng, lat) if z is None else (lng, lat, z)

            clip_poly = shp_transform(_xf, clip_poly)
        except Exception as exc:
            raise ValueError(f"无法将 bbox CRS 转为 EPSG:4326: {exc}") from exc

    out: list[dict[str, Any]] = []
    for feat in features:
        geom = feat.get("geometry")
        if not geom:
            continue
        try:
            g = shape(geom)
            if g.is_empty or not g.intersects(clip_poly):
                continue
            clipped = g.intersection(clip_poly)
            if clipped.is_empty:
                continue
            out.append({**feat, "geometry": mapping(clipped)})
        except Exception:
            continue
    return out


def _reproject_features(
    features: list[dict[str, Any]], src_crs: str, dst_crs: str
) -> list[dict[str, Any]]:
    from pyproj import Transformer
    from shapely.geometry import mapping, shape
    from shapely.ops import transform as shp_transform

    tf = Transformer.from_crs(src_crs, dst_crs, always_xy=True)

    def _xf(x: float, y: float, z: float | None = None):
        xx, yy = tf.transform(x, y)
        return (xx, yy) if z is None else (xx, yy, z)

    out: list[dict[str, Any]] = []
    for feat in features:
        geom = feat.get("geometry")
        if not geom:
            out.append(feat)
            continue
        try:
            g = shp_transform(_xf, shape(geom))
            out.append({**feat, "geometry": mapping(g)})
        except Exception:
            continue
    return out


def _safe_filename_base(name: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in "-_." else "_" for ch in (name or "export")
    )
    cleaned = cleaned.strip("._") or "export"
    return cleaned[:80]


def _export_filename_stem(layer_id: str, meta: dict[str, Any]) -> str:
    """导出文件名基座：优先 layer_id（ref-/prod-/method-/obs-/imported-），不用中文显示名。"""
    dataset_key = meta.get("dataset_key")
    source = meta.get("source_filename") or meta.get("source_name")
    display = meta.get("display_name") or meta.get("label")
    raw = str(
        layer_id
        or (dataset_key if isinstance(dataset_key, str) and dataset_key.strip() else "")
        or (source if isinstance(source, str) and source.strip() else "")
        or (display if isinstance(display, str) and display.strip() else "")
        or "export"
    ).rsplit(".", 1)[0]
    return _safe_filename_base(raw)


def _export_csv(
    geojson: dict[str, Any], base: str, encoding: str
) -> tuple[bytes, str, str]:
    buf = io.StringIO()
    fields: list[str] = []
    for feat in geojson.get("features") or []:
        props = feat.get("properties") or {}
        for k in props:
            if k not in fields:
                fields.append(str(k))
    writer = csv.DictWriter(
        buf, fieldnames=["lng", "lat", *fields], extrasaction="ignore"
    )
    writer.writeheader()
    for feat in geojson.get("features") or []:
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates")
        lng = lat = ""
        if (
            geom.get("type") == "Point"
            and isinstance(coords, (list, tuple))
            and len(coords) >= 2
        ):
            lng, lat = coords[0], coords[1]
        row: dict[str, Any] = {"lng": lng, "lat": lat}
        props = feat.get("properties") or {}
        for f in fields:
            row[f] = encode_export_text(props.get(f, ""), encoding)
        writer.writerow(row)
    text = buf.getvalue()
    try:
        payload = text.encode(encoding)
    except LookupError as exc:
        raise ValueError(f"不支持的 CSV 编码: {encoding}") from exc
    return payload, f"text/csv; charset={encoding}", f"{base}.csv"


def _prj_wkt(crs_code: str) -> str:
    code = (crs_code or "EPSG:4326").strip()
    if code.upper() in {"EPSG:4326", "WGS84", "CRS84"}:
        return _wgs84_prj()
    try:
        from pyproj import CRS

        return CRS.from_user_input(code).to_wkt("WKT1_ESRI")
    except Exception:
        return _wgs84_prj()


def _export_shp_zip(
    geojson: dict[str, Any],
    base: str,
    encoding: str,
    *,
    output_crs: str = "EPSG:4326",
) -> tuple[bytes, str, str]:
    try:
        import shapefile  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 pyshp，无法导出 SHP") from exc

    mem = io.BytesIO()
    shp_buf = io.BytesIO()
    shx_buf = io.BytesIO()
    dbf_buf = io.BytesIO()
    writer = shapefile.Writer(shp=shp_buf, shx=shx_buf, dbf=dbf_buf, encoding=encoding)
    writer.field("id", "N")

    prop_fields: list[str] = []
    dbf_names: list[str] = []
    used: set[str] = set({"id"})
    for feat in geojson.get("features") or []:
        props = feat.get("properties") or {}
        for k in props:
            key = str(k)
            if key in prop_fields:
                continue
            dbf_name = truncate_to_encoded_bytes(key, encoding, 10)
            base_name = dbf_name
            n = 1
            while dbf_name.lower() in {u.lower() for u in used}:
                suffix = str(n)
                dbf_name = truncate_to_encoded_bytes(
                    base_name[: max(1, 10 - len(suffix))] + suffix, encoding, 10
                )
                n += 1
            used.add(dbf_name)
            prop_fields.append(key)
            dbf_names.append(dbf_name)
            if len(prop_fields) >= 48:
                break
        if len(prop_fields) >= 48:
            break

    for name in dbf_names:
        writer.field(name, "C", size=254)

    for i, feat in enumerate(geojson.get("features") or []):
        geom = feat.get("geometry")
        if not geom:
            continue
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        try:
            if gtype == "Point":
                writer.shapeType = shapefile.POINT
                writer.point(coords[0], coords[1])
            elif gtype == "LineString":
                writer.shapeType = shapefile.POLYLINE
                writer.line([coords])
            elif gtype == "Polygon":
                writer.shapeType = shapefile.POLYGON
                writer.poly(coords)
            elif gtype == "MultiPoint":
                writer.shapeType = shapefile.MULTIPOINT
                writer.multipoint(coords)
            else:
                continue
        except Exception:
            continue
        props = feat.get("properties") or {}
        record = [i] + [
            encode_export_text(props.get(k, ""), encoding, max_bytes=254)
            for k in prop_fields
        ]
        writer.record(*record)

    writer.close()
    cpg_text = cpg_label_for_encoding(encoding) + "\n"
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base}.shp", shp_buf.getvalue())
        zf.writestr(f"{base}.shx", shx_buf.getvalue())
        zf.writestr(f"{base}.dbf", dbf_buf.getvalue())
        zf.writestr(f"{base}.prj", _prj_wkt(output_crs))
        zf.writestr(f"{base}.cpg", cpg_text.encode("ascii", errors="ignore"))
    return mem.getvalue(), "application/zip", f"{base}.shp.zip"


def _wgs84_prj() -> str:
    return (
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
    )


def _export_raster(
    dest: Path,
    layer_id: str,
    fmt: str,
    meta: dict[str, Any],
    *,
    time: str | None = None,
    bbox: BBoxDict | None = None,
    output_crs: str | None = None,
    fields: list[str] | None = None,
) -> tuple[bytes, str, str]:
    base = _export_filename_stem(layer_id, meta)
    time_list = meta.get("time_list") if isinstance(meta.get("time_list"), list) else []
    time_key = str(time or meta.get("default_time") or "").strip()
    if time_key and time_list and time_key not in [str(t) for t in time_list]:
        raise ValueError(f"时间切片不存在: {time_key}")
    if time_key:
        base = f"{base}_{time_key}"

    source = None
    if time_key:
        timed = dest / f"source_{time_key}.tif"
        if timed.exists():
            source = timed
    if source is None:
        tifs = list(dest.glob("*.tif")) + list(dest.glob("*.tiff"))
        for cand in tifs:
            name = cand.name.lower()
            if name.startswith("preview") or name.startswith("source_"):
                # prefer non-preview; timed sources only when time set
                if time_key and name == f"source_{time_key.lower()}.tif":
                    source = cand
                    break
                continue
            source = cand
            break
        if source is None and tifs:
            source = tifs[0]

    need_xform = bool(bbox) or bool(output_crs)

    if fmt in {"geotiff", "tif", "tiff"}:
        if source is None:
            raise ValueError("无可用 GeoTIFF 源文件")
        if need_xform:
            return (
                _transform_geotiff(source, bbox=bbox, output_crs=output_crs),
                "image/tiff",
                f"{base}.tif",
            )
        return source.read_bytes(), "image/tiff", f"{base}.tif"

    if fmt in {"netcdf", "nc"}:
        ncs = list(dest.glob("*.nc"))
        if ncs and not need_xform:
            return ncs[0].read_bytes(), "application/netcdf", f"{base}.nc"
        if source is None:
            raise ValueError("无法导出 NetCDF：无源 nc 且无 geotiff 可转换")
        tif_bytes = (
            _transform_geotiff(source, bbox=bbox, output_crs=output_crs)
            if need_xform
            else source.read_bytes()
        )
        return (
            _geotiff_bytes_to_netcdf(tif_bytes, time_key=time_key),
            "application/netcdf",
            f"{base}.nc",
        )

    if fmt in {"mat", "matlab"}:
        # 始终从 GeoTIFF 生成，写入准确 lat/lon（或投影 x/y）与多波段变量
        if source is None:
            native_mats = sorted(dest.glob("*.mat"))
            if native_mats and not need_xform:
                return (
                    native_mats[0].read_bytes(),
                    "application/x-matlab-data",
                    f"{base}.mat",
                )
            raise ValueError("无法导出 MAT：无可用 GeoTIFF 源文件")
        tif_bytes = (
            _transform_geotiff(source, bbox=bbox, output_crs=output_crs)
            if need_xform
            else source.read_bytes()
        )
        content = _geotiff_bytes_to_mat(
            tif_bytes,
            meta=meta,
            layer_id=layer_id,
            time_key=time_key,
            fields=fields,
        )
        return content, "application/x-matlab-data", f"{base}.mat"

    if fmt == "png":
        # 预览 PNG：不做科学 CRS；有 bbox 时仍返回原预览（避免伪地理裁切）
        if time_key:
            timed_png = dest / f"preview_{time_key}.png"
            if timed_png.exists():
                return timed_png.read_bytes(), "image/png", f"{base}.png"
        png = dest / "preview.png"
        if not png.exists():
            raise ValueError("无预览 PNG")
        return png.read_bytes(), "image/png", f"{base}.png"

    raise ValueError(f"栅格不支持导出格式: {fmt}")


def _transform_geotiff(
    source: Path,
    *,
    bbox: BBoxDict | None,
    output_crs: str | None,
) -> bytes:
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.windows import from_bounds, Window
    from rasterio.warp import (
        Resampling,
        calculate_default_transform,
        reproject,
        transform_bounds,
    )

    with rasterio.open(source) as src:
        src_crs = src.crs
        if src_crs is None:
            # 无 CRS 时仅允许字节直出；有裁剪/重投影需求则报错
            if bbox or output_crs:
                raise ValueError("源 GeoTIFF 无 CRS，无法裁剪或重投影")
            return source.read_bytes()

        window: Window | None = None
        if bbox is not None:
            bbox_crs = str(bbox.get("crs") or "EPSG:4326")
            try:
                west, south, east, north = transform_bounds(
                    bbox_crs,
                    src_crs,
                    bbox["west"],
                    bbox["south"],
                    bbox["east"],
                    bbox["north"],
                    densify_pts=21,
                )
            except Exception as exc:
                raise ValueError(f"bbox 变换到栅格 CRS 失败: {exc}") from exc
            window = from_bounds(west, south, east, north, transform=src.transform)
            window = window.intersection(Window(0, 0, src.width, src.height))
            if window.width <= 0 or window.height <= 0:
                raise ValueError("裁剪范围与栅格不相交")

        dst_crs_code = (output_crs or "").strip() or None
        same_crs = True
        if dst_crs_code:
            try:
                from rasterio.crs import CRS

                same_crs = CRS.from_user_input(dst_crs_code) == CRS.from_user_input(
                    src_crs
                )
            except Exception:
                same_crs = False

        if window is not None and (not dst_crs_code or same_crs):
            data = src.read(window=window, boundless=False)
            transform = src.window_transform(window)
            profile = src.profile.copy()
            profile.update(
                {
                    "height": data.shape[1],
                    "width": data.shape[2],
                    "transform": transform,
                }
            )
            with MemoryFile() as mem:
                with mem.open(**profile) as dst:
                    dst.write(data)
                return mem.read()

        # reproject (optionally after windowed read into temporary in-memory)
        if window is not None:
            data = src.read(window=window, boundless=False)
            transform = src.window_transform(window)
            height, width = int(window.height), int(window.width)
            count = src.count
            dtype = src.dtypes[0]
            nodata = src.nodata
        else:
            data = src.read()
            transform = src.transform
            height, width = src.height, src.width
            count = src.count
            dtype = src.dtypes[0]
            nodata = src.nodata

        target = dst_crs_code or str(src_crs)
        dst_transform, dst_width, dst_height = calculate_default_transform(
            src_crs,
            target,
            width,
            height,
            *rasterio.transform.array_bounds(height, width, transform),
        )
        dst_profile = src.profile.copy()
        dst_profile.update(
            {
                "crs": target,
                "transform": dst_transform,
                "width": dst_width,
                "height": dst_height,
            }
        )
        destination = np.zeros((count, dst_height, dst_width), dtype=dtype)
        for i in range(count):
            reproject(
                source=data[i],
                destination=destination[i],
                src_transform=transform,
                src_crs=src_crs,
                dst_transform=dst_transform,
                dst_crs=target,
                resampling=Resampling.bilinear,
                src_nodata=nodata,
                dst_nodata=nodata,
            )
        with MemoryFile() as mem:
            with mem.open(**dst_profile) as dst:
                dst.write(destination)
            return mem.read()


def _matlab_varname(name: str, fallback: str = "data") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", str(name or "").strip())
    cleaned = cleaned.strip("_") or fallback
    if cleaned[0].isdigit():
        cleaned = f"v_{cleaned}"
    return cleaned[:63]


def _raster_variable_names(meta: dict[str, Any], count: int) -> list[str]:
    raw = meta.get("variable_ids") or meta.get("band_names") or meta.get("variables")
    names: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                key = item.get("id") or item.get("name") or item.get("variable_id")
            else:
                key = item
            if key is not None and str(key).strip():
                names.append(str(key).strip())
    if len(names) >= count:
        return [
            _matlab_varname(n, f"band_{i + 1}") for i, n in enumerate(names[:count])
        ]
    vid = meta.get("variable_id") or meta.get("label") or meta.get("dataset_key")
    if count == 1 and vid:
        return [_matlab_varname(str(vid), "data")]
    return [f"band_{i + 1}" for i in range(count)]


def _pixel_center_xy(transform: Any, height: int, width: int) -> tuple[Any, Any]:
    import numpy as np
    from rasterio.transform import xy as transform_xy

    rows = np.arange(height, dtype=np.float64)
    cols = np.arange(width, dtype=np.float64)
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    xs, ys = transform_xy(transform, rr, cc, offset="center")
    # rasterio 可能返回扁平序列；强制还原为 (height, width)
    xs = np.asarray(xs, dtype=np.float64).reshape(height, width)
    ys = np.asarray(ys, dtype=np.float64).reshape(height, width)
    return xs, ys


def _to_lonlat(xs: Any, ys: Any, src_crs: Any) -> tuple[Any, Any]:
    """将像素中心坐标变换为 WGS84 lon/lat（始终 always_xy）。"""
    import numpy as np
    from rasterio.crs import CRS

    src = CRS.from_user_input(src_crs) if src_crs is not None else CRS.from_epsg(4326)
    if src.to_epsg() == 4326 or src.is_geographic:
        # 地理 CRS：x=lon, y=lat
        return np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
    from pyproj import Transformer

    tf = Transformer.from_crs(src, "EPSG:4326", always_xy=True)
    lon, lat = tf.transform(xs, ys)
    return np.asarray(lon, dtype=np.float64), np.asarray(lat, dtype=np.float64)


def _geotiff_bytes_to_mat_payload(
    tif_bytes: bytes,
    *,
    meta: dict[str, Any],
    layer_id: str,
    time_key: str,
    fields: list[str] | None,
    var_prefix: str | None = None,
) -> dict[str, Any]:
    """从 GeoTIFF 字节构建 MAT 载荷（多波段变量 + 准确坐标）。"""
    import numpy as np
    from rasterio.io import MemoryFile

    with MemoryFile(tif_bytes) as mem:
        with mem.open() as ds:
            if ds.crs is None:
                raise ValueError("源 GeoTIFF 无 CRS，无法写出带坐标的 MAT")
            count = int(ds.count)
            names = _raster_variable_names(meta, count)
            if fields:
                allow = {str(f).strip() for f in fields if str(f).strip()}
                # 也允许 band_1 这类默认名
                selected = [
                    (i, n)
                    for i, n in enumerate(names)
                    if n in allow or f"band_{i + 1}" in allow
                ]
                if not selected:
                    raise ValueError("fields 与栅格波段名无交集，无法导出 MAT")
            else:
                selected = list(enumerate(names))

            xs, ys = _pixel_center_xy(ds.transform, ds.height, ds.width)
            lon, lat = _to_lonlat(xs, ys, ds.crs)
            crs_str = ds.crs.to_string() if ds.crs else "EPSG:4326"
            gt = ds.transform.to_gdal()

            payload: dict[str, Any] = {
                "lat": np.asarray(lat, dtype=np.float64),
                "lon": np.asarray(lon, dtype=np.float64),
                "crs": crs_str,
                "geotransform": np.asarray(gt, dtype=np.float64),
                "layer_id": str(layer_id),
            }
            if not ds.crs.is_geographic:
                payload["x"] = np.asarray(xs, dtype=np.float64)
                payload["y"] = np.asarray(ys, dtype=np.float64)
            if time_key:
                payload["time"] = str(time_key)

            var_names: list[str] = []
            used: set[str] = set(payload.keys())
            for i, name in selected:
                arr = np.asarray(ds.read(i + 1), dtype=np.float32)
                key = _matlab_varname(
                    f"{var_prefix}_{name}" if var_prefix else name,
                    f"band_{i + 1}",
                )
                base_key = key
                n = 1
                while key in used:
                    key = _matlab_varname(f"{base_key}_{n}", f"band_{i + 1}_{n}")
                    n += 1
                used.add(key)
                payload[key] = arr
                var_names.append(key)
                if ds.nodata is not None and np.isfinite(ds.nodata):
                    payload[f"{key}_nodata"] = float(ds.nodata)

            payload["variables"] = np.array(var_names, dtype=object)
            return payload


def _savemat_bytes(payload: dict[str, Any]) -> bytes:
    from scipy.io import savemat  # type: ignore

    buf = io.BytesIO()
    savemat(buf, payload, do_compression=True, oned_as="column")
    return buf.getvalue()


def _geotiff_bytes_to_mat(
    tif_bytes: bytes,
    *,
    meta: dict[str, Any],
    layer_id: str,
    time_key: str,
    fields: list[str] | None,
) -> bytes:
    payload = _geotiff_bytes_to_mat_payload(
        tif_bytes,
        meta=meta,
        layer_id=layer_id,
        time_key=time_key,
        fields=fields,
    )
    return _savemat_bytes(payload)


def _geotiff_bytes_to_netcdf(tif_bytes: bytes, *, time_key: str) -> bytes:
    import uuid

    import numpy as np
    from netCDF4 import Dataset  # type: ignore
    from rasterio.io import MemoryFile

    with MemoryFile(tif_bytes) as mem:
        with mem.open() as ds:
            arr = ds.read(1)
    # netCDF4 needs a real path; use temp under IMPORTS_DIR/_exports
    # 临时文件名须唯一：并发/同批多图层导出会同时落到同一目录，固定名会互相
    # 覆盖或误删（finally unlink 可能删掉其它请求仍在使用中的文件）。
    exports_dir = IMPORTS_DIR / "_exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    buf_path = exports_dir / f"_export_tmp_{uuid.uuid4().hex}.nc"
    try:
        with Dataset(str(buf_path), "w", format="NETCDF4") as nc:
            nc.createDimension("y", arr.shape[0])
            nc.createDimension("x", arr.shape[1])
            var = nc.createVariable("band", "f4", ("y", "x"), zlib=True)
            var[:] = np.asarray(arr, dtype=np.float32)
            if time_key:
                nc.product_time = time_key
        return buf_path.read_bytes()
    finally:
        buf_path.unlink(missing_ok=True)


# 批导出产物（zip / 合并 mat）在 _exports 下的保留时长；超过即惰性清理，防磁盘泄漏
_EXPORTS_MAX_AGE_SECONDS = 24 * 3600


def _cleanup_exports_dir(
    exports_dir: Path, max_age_seconds: int = _EXPORTS_MAX_AGE_SECONDS
) -> None:
    """惰性清理 _exports 目录中超过 max_age_seconds 的过期产物。

    导出链路每次写入新产物前调用；删除失败（文件正被占用等）时静默跳过。
    """
    import time as time_mod

    try:
        deadline = time_mod.time() - max_age_seconds
        for child in exports_dir.iterdir():
            try:
                if child.is_file() and child.stat().st_mtime < deadline:
                    child.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError:
        return


def _try_export_layers_batch_mat(
    layer_ids: list[str],
    *,
    time: str | None,
    times: list[str] | None,
    bbox: BBoxDict | None,
    output_crs: str | None,
    fields: list[str] | None,
    exports_dir: Path,
) -> dict[str, Any] | None:
    """多图层若网格一致则合并为单文件多变量 MAT；否则返回 None（改走 zip）。"""
    import time as time_mod
    import uuid

    import numpy as np

    # 多时刻仍走逐层 zip
    if times and len([t for t in times if str(t).strip()]) > 1:
        return None

    payloads: list[dict[str, Any]] = []
    errors: list[str] = []
    for layer_id in layer_ids:
        dest = IMPORTS_DIR / layer_id
        meta_path = dest / "meta.json"
        meta: dict[str, Any] = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        try:
            tif_bytes, _m, _f = export_layer(
                layer_id,
                "tif",
                time=time,
                times=times,
                bbox=bbox,
                output_crs=output_crs,
            )
            resolved = _resolve_export_times(meta, time=time, times=times)
            time_key = resolved[0] if resolved else (time or "")
            prefix = _matlab_varname(layer_id, "layer")
            payloads.append(
                _geotiff_bytes_to_mat_payload(
                    tif_bytes,
                    meta=meta,
                    layer_id=layer_id,
                    time_key=str(time_key or ""),
                    fields=fields,
                    var_prefix=prefix,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{layer_id}: {exc}")

    if len(payloads) < 2:
        return None

    ref_lat = payloads[0].get("lat")
    ref_lon = payloads[0].get("lon")
    for p in payloads[1:]:
        if (
            getattr(p.get("lat"), "shape", None) != getattr(ref_lat, "shape", None)
            or getattr(p.get("lon"), "shape", None) != getattr(ref_lon, "shape", None)
            or not np.allclose(p["lat"], ref_lat, equal_nan=True)
            or not np.allclose(p["lon"], ref_lon, equal_nan=True)
        ):
            return None

    merged: dict[str, Any] = {
        "lat": payloads[0]["lat"],
        "lon": payloads[0]["lon"],
        "crs": payloads[0].get("crs", "EPSG:4326"),
        "geotransform": payloads[0].get("geotransform"),
    }
    if "x" in payloads[0]:
        merged["x"] = payloads[0]["x"]
        merged["y"] = payloads[0]["y"]
    all_vars: list[str] = []
    used = set(merged.keys())
    for p in payloads:
        for name in list(p.get("variables") or []):
            key = str(name)
            if key not in p:
                continue
            out_key = key
            n = 1
            while out_key in used:
                out_key = _matlab_varname(f"{key}_{n}", f"var_{n}")
                n += 1
            used.add(out_key)
            merged[out_key] = p[key]
            all_vars.append(out_key)
            nodata_key = f"{key}_nodata"
            if nodata_key in p:
                merged[f"{out_key}_nodata"] = p[nodata_key]
    merged["variables"] = np.array(all_vars, dtype=object)
    if time:
        merged["time"] = str(time)

    mat_name = f"batch-mat-{uuid.uuid4().hex[:12]}.mat"
    mat_path = exports_dir / mat_name
    mat_path.write_bytes(_savemat_bytes(merged))
    return {
        "download_path": str(mat_path),
        "filename": mat_name,
        "layer_count": len(layer_ids),
        "encoding": "binary",
        "created_at": time_mod.time(),
        "format": "mat",
        "errors": errors,
    }


def export_layers_batch_zip(
    layer_ids: list[str],
    *,
    format: str = "geojson",
    encoding: str | None = None,
    time: str | None = None,
    times: list[str] | None = None,
    bbox: BBoxDict | None = None,
    output_crs: str | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """多图层打包为 zip；MAT 且网格一致时合并为单文件多变量 .mat。"""
    import time as time_mod
    import uuid

    if not layer_ids:
        raise ValueError("layer_ids 不能为空")

    exports_dir = IMPORTS_DIR / "_exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_exports_dir(exports_dir)

    fmt = (format or "").lower().strip()
    if fmt in {"mat", "matlab"} and len(layer_ids) >= 2:
        merged = _try_export_layers_batch_mat(
            layer_ids,
            time=time,
            times=times,
            bbox=bbox,
            output_crs=output_crs,
            fields=fields,
            exports_dir=exports_dir,
        )
        if merged is not None:
            return merged

    zip_name = f"batch-{uuid.uuid4().hex[:12]}.zip"
    zip_path = exports_dir / zip_name

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for layer_id in layer_ids:
            try:
                content, _media, filename = export_layer(
                    layer_id,
                    format,
                    encoding=encoding,
                    time=time,
                    times=times,
                    bbox=bbox,
                    output_crs=output_crs,
                    fields=fields,
                )
            except Exception as exc:
                zf.writestr(f"{layer_id}.error.txt", str(exc))
                continue
            arcname = f"{layer_id}/{filename}"
            zf.writestr(arcname, content)

    return {
        "download_path": str(zip_path),
        "filename": zip_name,
        "layer_count": len(layer_ids),
        "encoding": encoding or "auto",
        "created_at": time_mod.time(),
    }
