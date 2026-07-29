"""矢量导入：shp(+sidecar)/zip/rar/geojson → GeoJSON 落盘。"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.data_io.services.archive_safe import safe_extract_archive
from app.data_io.services.dbf_encoding import shapefile_to_geojson_with_fallback
from app.data_io.services.paths import (
    IMPORTS_DIR,
    PREVIEW_FEATURE_LIMIT,
    assert_quota_available,
    ensure_imports_root,
)


REQUIRED_SHP_SIDECARS = (".dbf", ".shx")
OPTIONAL_SHP_SIDECARS = (".prj", ".cpg", ".sbn", ".sbx", ".qix")

# 属性编辑写回时必须保留的编码诊断字段
_ENCODING_META_KEYS = (
    "source_encoding",
    "encoding_score",
    "encoding_sources",
    "encoding_platform",
    "encoding_locale",
    "encoding_strict",
    "export_encoding_default",
)


def _new_layer_dir(prefix: str = "imported-vec") -> tuple[str, Path]:
    ensure_imports_root()
    assert_quota_available()
    layer_id = f"{prefix}-{uuid.uuid4().hex[:12]}"
    dest = IMPORTS_DIR / layer_id
    dest.mkdir(parents=True, exist_ok=True)
    return layer_id, dest


def _load_preserved_encoding_meta(dest: Path) -> dict[str, Any]:
    """属性表编辑写回时保留导入阶段的编码元数据。"""
    meta_path = dest / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        old = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(old, dict):
        return {}
    return {k: old[k] for k in _ENCODING_META_KEYS if k in old}


def _write_layer(
    *,
    layer_id: str,
    dest: Path,
    geojson: dict[str, Any],
    source_name: str,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    features = list(geojson.get("features") or [])
    if not features:
        raise ValueError("文件中没有要素")
    data_path = dest / "data.geojson"
    data_path.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    preview_features = features[:PREVIEW_FEATURE_LIMIT]
    preview = {"type": "FeatureCollection", "features": preview_features}
    (dest / "preview.geojson").write_text(
        json.dumps(preview, ensure_ascii=False), encoding="utf-8"
    )

    field_names: list[str] = []
    for feat in features[:200]:
        props = feat.get("properties") or {}
        if isinstance(props, dict):
            for k in props:
                if k not in field_names:
                    field_names.append(str(k))

    preserved = _load_preserved_encoding_meta(dest)
    meta = {
        "layer_id": layer_id,
        "kind": "vector",
        "source_name": source_name,
        "feature_count": len(features),
        "fields": field_names,
        "geometry_types": sorted(
            {
                str((f.get("geometry") or {}).get("type") or "Unknown")
                for f in features
                if f.get("geometry")
            }
        ),
        **preserved,
        **(extra_meta or {}),
    }
    (dest / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "layer_id": layer_id,
        "feature_count": len(features),
        "fields": field_names,
        "geometry_types": meta["geometry_types"],
        "preview_feature_count": len(preview_features),
        "truncated": bool(len(features) > PREVIEW_FEATURE_LIMIT),
        "preview_geojson": preview,
        "source_name": source_name,
    }


def load_vector_meta(layer_id: str) -> dict[str, Any]:
    meta_path = IMPORTS_DIR / layer_id / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"矢量图层不存在: {layer_id}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def load_vector_geojson(layer_id: str, *, preview: bool = False) -> dict[str, Any]:
    dest = IMPORTS_DIR / layer_id
    path = dest / ("preview.geojson" if preview else "data.geojson")
    if not path.exists():
        raise FileNotFoundError(f"矢量数据不存在: {layer_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_vector_features(
    layer_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    field_filter: str | None = None,
    value_contains: str | None = None,
    sort: str | None = None,
    where: str | None = None,
) -> dict[str, Any]:
    geojson = load_vector_geojson(layer_id, preview=False)
    raw_features = list(geojson.get("features") or [])
    fields = _collect_fields(raw_features)
    # 保留原始绝对索引，供属性表编辑 / 高亮
    indexed: list[tuple[int, dict[str, Any]]] = list(enumerate(raw_features))

    if field_filter and value_contains is not None:
        needle = str(value_contains).lower()
        indexed = [
            (i, feat)
            for i, feat in indexed
            if needle
            in str((feat.get("properties") or {}).get(field_filter, "")).lower()
        ]

    if where:
        indexed = [(i, feat) for i, feat in indexed if _match_where(feat, where)]

    if sort:
        reverse = sort.startswith("-")
        key = sort[1:] if reverse else sort
        indexed = sorted(
            indexed,
            key=lambda pair: _sort_key((pair[1].get("properties") or {}).get(key)),
            reverse=reverse,
        )

    total = len(indexed)
    page = indexed[offset : offset + max(1, min(limit, 2000))]
    return {
        "layer_id": layer_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "features": [feat for _, feat in page],
        "indexes": [i for i, _ in page],
        "fields": fields,
    }


def _collect_fields(features: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for feat in features:
        props = feat.get("properties") or {}
        if not isinstance(props, dict):
            continue
        for k in props:
            sk = str(k)
            if sk not in seen:
                seen.add(sk)
                keys.append(sk)
    return keys


def _sort_key(value: Any) -> tuple[int, Any]:
    if value is None:
        return (2, "")
    if isinstance(value, (int, float)):
        return (0, value)
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value).lower())


def _match_where(feat: dict[str, Any], where: str) -> bool:
    """简单 where：``field=op=value`` 多条件用 ``;`` 或 `` AND `` 连接。

    op: ``=`` ``!=`` ``contains`` ``>`` ``>=`` ``<`` ``<=``
    """
    props = feat.get("properties") or {}
    clauses = [c.strip() for c in where.replace(" AND ", ";").split(";") if c.strip()]
    for clause in clauses:
        matched = False
        for op in ("!=", ">=", "<=", "contains", "=", ">", "<"):
            if op not in clause:
                continue
            left, right = clause.split(op, 1)
            field = left.strip()
            expect = right.strip().strip("'\"")
            actual = props.get(field)
            if op == "=":
                matched = str(actual) == expect
            elif op == "!=":
                matched = str(actual) != expect
            elif op == "contains":
                matched = expect.lower() in str(actual).lower()
            else:
                try:
                    a = float(actual)
                    b = float(expect)
                except (TypeError, ValueError):
                    matched = False
                else:
                    if op == ">":
                        matched = a > b
                    elif op == ">=":
                        matched = a >= b
                    elif op == "<":
                        matched = a < b
                    elif op == "<=":
                        matched = a <= b
            break
        if not matched:
            return False
    return True


def patch_feature_attribute(
    layer_id: str, feature_index: int, field: str, value: Any
) -> dict[str, Any]:
    geojson = load_vector_geojson(layer_id, preview=False)
    features = list(geojson.get("features") or [])
    if feature_index < 0 or feature_index >= len(features):
        raise ValueError(f"要素索引越界: {feature_index}")
    props = features[feature_index].setdefault("properties", {})
    if not isinstance(props, dict):
        raise ValueError("要素属性无效")
    props[field] = value
    dest = IMPORTS_DIR / layer_id
    _write_layer(
        layer_id=layer_id,
        dest=dest,
        geojson=geojson,
        source_name=load_vector_meta(layer_id).get("source_name", layer_id),
    )
    return {"layer_id": layer_id, "feature_index": feature_index}


def batch_set_feature_attribute(
    layer_id: str, indexes: list[int], field: str, value: Any
) -> dict[str, Any]:
    geojson = load_vector_geojson(layer_id, preview=False)
    features = list(geojson.get("features") or [])
    updated = 0
    for idx in indexes:
        if idx < 0 or idx >= len(features):
            continue
        props = features[idx].setdefault("properties", {})
        if not isinstance(props, dict):
            continue
        props[field] = value
        updated += 1
    dest = IMPORTS_DIR / layer_id
    _write_layer(
        layer_id=layer_id,
        dest=dest,
        geojson=geojson,
        source_name=load_vector_meta(layer_id).get("source_name", layer_id),
    )
    return {"layer_id": layer_id, "updated": updated}


def add_vector_field(layer_id: str, name: str, default: Any = "") -> dict[str, Any]:
    name = str(name).strip()
    if not name:
        raise ValueError("字段名不能为空")
    geojson = load_vector_geojson(layer_id, preview=False)
    for feat in geojson.get("features") or []:
        props = feat.setdefault("properties", {})
        if isinstance(props, dict) and name not in props:
            props[name] = default
    dest = IMPORTS_DIR / layer_id
    result = _write_layer(
        layer_id=layer_id,
        dest=dest,
        geojson=geojson,
        source_name=load_vector_meta(layer_id).get("source_name", layer_id),
    )
    return {"layer_id": layer_id, "fields": result.get("fields") or []}


def delete_vector_field(layer_id: str, name: str) -> dict[str, Any]:
    name = str(name).strip()
    if not name:
        raise ValueError("字段名不能为空")
    geojson = load_vector_geojson(layer_id, preview=False)
    for feat in geojson.get("features") or []:
        props = feat.get("properties")
        if isinstance(props, dict) and name in props:
            props.pop(name, None)
    dest = IMPORTS_DIR / layer_id
    result = _write_layer(
        layer_id=layer_id,
        dest=dest,
        geojson=geojson,
        source_name=load_vector_meta(layer_id).get("source_name", layer_id),
    )
    return {"layer_id": layer_id, "fields": result.get("fields") or []}


def rename_vector_field(layer_id: str, old_name: str, new_name: str) -> dict[str, Any]:
    if not new_name or new_name == old_name:
        raise ValueError("新字段名无效")
    geojson = load_vector_geojson(layer_id, preview=False)
    for feat in geojson.get("features") or []:
        props = feat.get("properties")
        if not isinstance(props, dict) or old_name not in props:
            continue
        props[new_name] = props.pop(old_name)
    dest = IMPORTS_DIR / layer_id
    result = _write_layer(
        layer_id=layer_id,
        dest=dest,
        geojson=geojson,
        source_name=load_vector_meta(layer_id).get("source_name", layer_id),
        extra_meta={"renamed_field": {"from": old_name, "to": new_name}},
    )
    return result


def _read_geojson_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        return data
    if isinstance(data, dict) and data.get("type") == "Feature":
        return {"type": "FeatureCollection", "features": [data]}
    if isinstance(data, dict) and "type" in data:
        return {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": data}],
        }
    raise ValueError("GeoJSON 格式无效")


def _shapefile_to_geojson(shp_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """委托 ``dbf_encoding``：跨平台多编码探测后转为 GeoJSON。

    返回 (geojson, encoding_meta)。
    """
    geojson, resolution = shapefile_to_geojson_with_fallback(shp_path)
    meta = {
        "source_encoding": resolution.encoding,
        "encoding_score": round(resolution.score, 3),
        "encoding_sources": list(resolution.sources),
        "encoding_platform": resolution.platform,
        "encoding_locale": resolution.locale,
        "encoding_strict": resolution.strict,
    }
    return geojson, meta


def _collect_shp_group(paths: list[Path]) -> Path:
    """从一组路径中定位 .shp，并校验 sidecar。

    注意：paths 可能来自不同 staging 目录；按文件名匹配附属文件，
    真正解析前调用方应先拷贝到同一目录。
    """
    shp_files = [p for p in paths if p.suffix.lower() == ".shp"]
    if not shp_files:
        raise ValueError("未找到 .shp 文件")
    shp = shp_files[0]
    present = {p.name.lower() for p in paths if p.is_file()}
    # 同目录 glob（单文件上传落在 staging 时通常只有 .shp）
    try:
        for sibling in shp.parent.glob(shp.stem + ".*"):
            if sibling.is_file():
                present.add(sibling.name.lower())
    except OSError:
        pass

    missing = [
        ext
        for ext in REQUIRED_SHP_SIDECARS
        if f"{shp.stem.lower()}{ext}" not in present
    ]
    if missing:
        received = ", ".join(sorted(present)) or "(无)"
        raise ValueError(
            "SHP 缺少必要附属文件: "
            f"{', '.join(missing)}。"
            "请在导入时一并选择同名的 .dbf / .shx"
            "（浏览器不会自动包含磁盘同目录未选中的文件；也可打成 zip 后导入）。"
            f" 当前收到: {received}"
        )
    return shp


def _extract_archive(archive: Path, dest: Path) -> list[Path]:
    """安全解压（路径穿越 / zip bomb / 符号链接防护）。"""
    return safe_extract_archive(archive, dest)


def import_vector_from_paths(
    paths: list[Path],
    *,
    source_name: str | None = None,
) -> dict[str, Any]:
    if not paths:
        raise ValueError("未提供文件")

    # 单文件 geojson / zip / rar / shp
    if len(paths) == 1:
        path = paths[0]
        ext = path.suffix.lower()
        layer_id, dest = _new_layer_dir()
        try:
            if ext in {".geojson", ".json"}:
                geojson = _read_geojson_file(path)
                return _write_layer(
                    layer_id=layer_id,
                    dest=dest,
                    geojson=geojson,
                    source_name=source_name or path.name,
                )
            if ext in {".zip", ".rar"}:
                extracted_dir = dest / "_extract"
                files = _extract_archive(path, extracted_dir)
                # prefer shp group, else geojson
                shp_candidates = [p for p in files if p.suffix.lower() == ".shp"]
                extra_meta: dict[str, Any] | None = None
                if shp_candidates:
                    shp = _collect_shp_group(files)
                    geojson, enc_meta = _shapefile_to_geojson(shp)
                    extra_meta = enc_meta
                else:
                    gj = [p for p in files if p.suffix.lower() in {".geojson", ".json"}]
                    if not gj:
                        raise ValueError("压缩包内未找到 SHP 或 GeoJSON")
                    geojson = _read_geojson_file(gj[0])
                return _write_layer(
                    layer_id=layer_id,
                    dest=dest,
                    geojson=geojson,
                    source_name=source_name or path.name,
                    extra_meta=extra_meta,
                )
            if ext == ".shp":
                shp = _collect_shp_group([path, *path.parent.glob(path.stem + ".*")])
                # copy sidecars into dest for provenance
                for sibling in path.parent.glob(path.stem + ".*"):
                    shutil.copy2(sibling, dest / sibling.name)
                geojson, enc_meta = _shapefile_to_geojson(dest / path.name)
                return _write_layer(
                    layer_id=layer_id,
                    dest=dest,
                    geojson=geojson,
                    source_name=source_name or path.name,
                    extra_meta=enc_meta,
                )
            raise ValueError(f"不支持的矢量格式: {ext}")
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
            raise

    # 多文件：视为 shp + sidecars
    layer_id, dest = _new_layer_dir()
    try:
        for p in paths:
            shutil.copy2(p, dest / p.name)
        copied = list(dest.glob("*"))
        shp = _collect_shp_group(copied)
        geojson, enc_meta = _shapefile_to_geojson(shp)
        return _write_layer(
            layer_id=layer_id,
            dest=dest,
            geojson=geojson,
            source_name=source_name or shp.name,
            extra_meta=enc_meta,
        )
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def import_vector_from_uploads(
    upload_paths: list[Path], *, source_name: str | None = None
) -> dict[str, Any]:
    return import_vector_from_paths(upload_paths, source_name=source_name)
