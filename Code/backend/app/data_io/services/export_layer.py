"""已导入图层导出：geojson/csv/shp-zip/geotiff/netcdf（支持多编码）。"""

from __future__ import annotations

import csv
import io
import json
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
) -> tuple[bytes, str, str]:
    """返回 (content, media_type, filename)."""
    fmt = fmt.lower().strip()
    dest = IMPORTS_DIR / layer_id
    if not dest.exists():
        raise FileNotFoundError(f"图层不存在: {layer_id}")

    meta_path = dest / "meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    kind = meta.get("kind")
    if (dest / "bounds.json").exists() and kind != "vector":
        return _export_raster(dest, layer_id, fmt, meta)

    if (dest / "data.geojson").exists() or kind == "vector":
        return _export_vector(layer_id, fmt, meta, encoding=encoding)

    if (dest / "preview.png").exists():
        return _export_raster(dest, layer_id, fmt, meta)

    raise ValueError(f"无法识别图层类型: {layer_id}")


def _export_vector(
    layer_id: str,
    fmt: str,
    meta: dict[str, Any],
    *,
    encoding: str | None,
) -> tuple[bytes, str, str]:
    geojson = load_vector_geojson(layer_id, preview=False)
    base = str(meta.get("source_name") or layer_id).rsplit(".", 1)[0]
    safe_base = _safe_filename_base(base)

    if fmt in {"geojson", "json"}:
        data = json.dumps(geojson, ensure_ascii=False).encode("utf-8")
        return data, "application/geo+json", f"{safe_base}.geojson"

    resolved = resolve_export_encoding(encoding, meta=meta, fmt=fmt)

    if fmt == "csv":
        return _export_csv(geojson, safe_base, resolved)

    if fmt in {"shp", "shp-zip", "shapefile"}:
        return _export_shp_zip(geojson, safe_base, resolved)

    raise ValueError(f"矢量不支持导出格式: {fmt}")


def _safe_filename_base(name: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in "-_." else "_" for ch in (name or "export")
    )
    cleaned = cleaned.strip("._") or "export"
    return cleaned[:80]


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


def _export_shp_zip(
    geojson: dict[str, Any], base: str, encoding: str
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
        zf.writestr(f"{base}.prj", _wgs84_prj())
        zf.writestr(f"{base}.cpg", cpg_text.encode("ascii", errors="ignore"))
    return mem.getvalue(), "application/zip", f"{base}.shp.zip"


def _wgs84_prj() -> str:
    return (
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
    )


def _export_raster(
    dest: Path, layer_id: str, fmt: str, meta: dict[str, Any]
) -> tuple[bytes, str, str]:
    base = _safe_filename_base(
        str(meta.get("source_filename") or meta.get("source_name") or layer_id).rsplit(
            ".", 1
        )[0]
    )
    tifs = list(dest.glob("*.tif")) + list(dest.glob("*.tiff"))
    source = None
    for cand in tifs:
        if cand.name.lower() not in {"preview.tif"}:
            source = cand
            break
    if source is None and tifs:
        source = tifs[0]

    if fmt in {"geotiff", "tif", "tiff"}:
        if source is None:
            raise ValueError("无可用 GeoTIFF 源文件")
        return source.read_bytes(), "image/tiff", f"{base}.tif"

    if fmt in {"netcdf", "nc"}:
        ncs = list(dest.glob("*.nc"))
        if ncs:
            return ncs[0].read_bytes(), "application/netcdf", f"{base}.nc"
        if source is None:
            raise ValueError("无法导出 NetCDF：无源 nc 且无 geotiff 可转换")
        try:
            import numpy as np
            import rasterio
            from netCDF4 import Dataset  # type: ignore
        except ImportError as exc:
            raise RuntimeError("缺少 netCDF4/rasterio，无法从 GeoTIFF 导出 NC") from exc

        with rasterio.open(source) as ds:
            arr = ds.read(1)
        buf_path = dest / "_export_tmp.nc"
        with Dataset(str(buf_path), "w", format="NETCDF4") as nc:
            nc.createDimension("y", arr.shape[0])
            nc.createDimension("x", arr.shape[1])
            var = nc.createVariable("band", "f4", ("y", "x"), zlib=True)
            var[:] = np.asarray(arr, dtype=np.float32)
        data = buf_path.read_bytes()
        buf_path.unlink(missing_ok=True)
        return data, "application/netcdf", f"{base}.nc"

    if fmt == "png":
        png = dest / "preview.png"
        if not png.exists():
            raise ValueError("无预览 PNG")
        return png.read_bytes(), "image/png", f"{base}.png"

    raise ValueError(f"栅格不支持导出格式: {fmt}")


def export_layers_batch_zip(
    layer_ids: list[str],
    *,
    format: str = "geojson",
    encoding: str | None = None,
) -> dict[str, Any]:
    """多图层打包为 zip；返回落盘路径供 job download。"""
    import time
    import uuid

    if not layer_ids:
        raise ValueError("layer_ids 不能为空")

    exports_dir = IMPORTS_DIR / "_exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"batch-{uuid.uuid4().hex[:12]}.zip"
    zip_path = exports_dir / zip_name

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for layer_id in layer_ids:
            try:
                content, _media, filename = export_layer(
                    layer_id, format, encoding=encoding
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
        "created_at": time.time(),
    }
