"""矢量导入：shp(+sidecar)/zip/rar/geojson → GeoJSON 落盘。"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.data_io.services.archive_safe import safe_extract_archive
from app.data_io.services.dbf_encoding import (
    shapefile_to_geojson_with_fallback,
    truncate_to_encoded_bytes,
)
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

# GIS / SQL 保留字（不区分大小写比较，统一以大写形式存储）
RESERVED_FIELD_NAMES = frozenset(
    {
        "OBJECTID",
        "FID",
        "OID",
        "ID",
        "GEOMETRY",
        "SHAPE",
        "THE_GEOM",
        "GID",
        "UID",
        "PK",
        "FK",
    }
)

# DBF（dBase III）字段名最大字节数
_DBF_MAX_FIELD_NAME_BYTES = 10

# 匹配字段名首尾的空白和控制字符（含 Unicode 空白）
_FIELD_EDGE_RE = re.compile(r"^[\s\x00-\x1f\x7f]+|[\s\x00-\x1f\x7f]+$")


def _clean_field_name(name: str) -> str:
    """去除字段名首尾空白和控制字符。"""
    return _FIELD_EDGE_RE.sub("", name)


def _deduplicate_name(name: str, used: set[str], encoding: str) -> str:
    """为重复字段名追加唯一后缀，同时确保不超过 DBF 字节长度限制。

    当基础名称已被占用时，依次尝试 ``_2``、``_3`` … 后缀。
    为保证追加后缀后总长不超过 ``_DBF_MAX_FIELD_NAME_BYTES`` 字节，
    会先将基础名称截断至 ``max_bytes - len(suffix)`` 字节。
    """
    suffix = 2
    while True:
        suffix_str = f"_{suffix}"
        suffix_bytes = len(suffix_str.encode(encoding, errors="ignore"))
        if suffix_bytes >= _DBF_MAX_FIELD_NAME_BYTES:
            base = ""
        else:
            base = truncate_to_encoded_bytes(
                name, encoding, _DBF_MAX_FIELD_NAME_BYTES - suffix_bytes
            )
        candidate = base + suffix_str
        if candidate not in used:
            return candidate
        suffix += 1


def sanitize_field_names(
    fields: list[str], *, encoding: str = "utf-8"
) -> tuple[list[str], list[dict]]:
    """规范化字段名列表，确保符合 DBF / GIS 命名规范。

    按以下顺序处理每个字段名：

    1. **去除首尾空白和控制字符** —— 清理字段名边缘的空格、制表符、
       换行符及其他控制字符（``\\x00-\\x1f``、``\\x7f``）。
    2. **空字段名** —— 替换为 ``field_N``（N 从 1 递增）。
    3. **保留字** —— 若字段名（不区分大小写）命中
       :data:`RESERVED_FIELD_NAMES`，追加 ``_field`` 后缀
       （如 ``ID`` → ``ID_field``）。
    4. **DBF 字节长度截断** —— 按目标 ``encoding`` 编码后字段名超过
       ``_DBF_MAX_FIELD_NAME_BYTES``（10）字节时，使用
       :func:`truncate_to_encoded_bytes` 截断。
    5. **重复字段名** —— 若处理后名称与已确定名称重复，追加
       ``_2``、``_3`` … 后缀（同时确保不超字节限制）。

    Args:
        fields: 原始字段名列表。
        encoding: 用于字节长度计算的目标编码（如 ``"gbk"``、``"utf-8"``）。

    Returns:
        二元组 ``(sanitized, changes)``：

        - ``sanitized`` —— 规范化后的字段名列表，与输入等长且一一对应。
        - ``changes`` —— 变更记录列表，每条记录格式为
          ``{"original": str, "sanitized": str, "reason": str}``，
          仅包含发生变更的字段。当多个规则作用于同一字段时，
          ``reason`` 以分号连接各原因。
    """
    sanitized: list[str] = []
    changes: list[dict] = []
    used: set[str] = set()
    empty_counter = 0

    for original in fields:
        original_str = str(original) if original is not None else ""
        current = original_str
        reasons: list[str] = []

        # 1. 去除首尾空白和控制字符
        cleaned = _clean_field_name(current)
        if cleaned != current:
            reasons.append("去除空白和控制字符")
            current = cleaned

        # 2. 空字段名 → field_N
        if not current:
            empty_counter += 1
            current = f"field_{empty_counter}"
            reasons.append("空字段名")

        # 3. 保留字 → 追加 _field
        if current.upper() in RESERVED_FIELD_NAMES:
            current = current + "_field"
            reasons.append("保留字")

        # 4. DBF 字节长度截断
        truncated = truncate_to_encoded_bytes(
            current, encoding, _DBF_MAX_FIELD_NAME_BYTES
        )
        if truncated != current:
            current = truncated
            reasons.append("字段名超长截断")

        # 5. 重复字段名 → 追加后缀
        if current in used:
            current = _deduplicate_name(current, used, encoding)
            reasons.append("重复字段名")

        used.add(current)
        sanitized.append(current)

        if current != original_str:
            changes.append(
                {
                    "original": original_str,
                    "sanitized": current,
                    "reason": "；".join(reasons) if reasons else "规范化",
                }
            )

    return sanitized, changes


def apply_field_sanitization(
    geojson: dict, *, encoding: str = "utf-8"
) -> tuple[dict, list[dict]]:
    """对 GeoJSON FeatureCollection 的属性字段名进行规范化。

    遍历所有要素的 ``properties``，收集全量字段名后调用
    :func:`sanitize_field_names` 进行规范化，再将规范化后的名称
    映射回每个要素的 ``properties``。

    Args:
        geojson: GeoJSON FeatureCollection 字典。
        encoding: 传递给 :func:`sanitize_field_names` 的目标编码。

    Returns:
        二元组 ``(geojson, changes)``：

        - ``geojson`` —— 更新后的 GeoJSON（原地修改并返回同一对象）。
        - ``changes`` —— 字段名变更记录列表（同 :func:`sanitize_field_names`）。
    """
    features = list(geojson.get("features") or [])

    # 收集所有字段名（保持首次出现顺序）
    field_names: list[str] = []
    seen: set[str] = set()
    for feat in features:
        props = feat.get("properties") or {}
        if not isinstance(props, dict):
            continue
        for k in props:
            sk = str(k)
            if sk not in seen:
                seen.add(sk)
                field_names.append(sk)

    # 规范化字段名
    sanitized_names, changes = sanitize_field_names(field_names, encoding=encoding)

    # 无变更则直接返回
    if not changes:
        return geojson, changes

    # 构建映射并应用到所有要素
    name_map = dict(zip(field_names, sanitized_names))
    for feat in features:
        props = feat.get("properties")
        if not isinstance(props, dict):
            continue
        new_props: dict[str, Any] = {}
        for k, v in props.items():
            new_key = name_map.get(str(k), str(k))
            new_props[new_key] = v
        feat["properties"] = new_props

    return geojson, changes


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

    # 收集原始字段名（用于检测与规范化）
    field_names: list[str] = []
    for feat in features[:200]:
        props = feat.get("properties") or {}
        if isinstance(props, dict):
            for k in props:
                if k not in field_names:
                    field_names.append(str(k))

    # 确定字段名规范化所用编码：优先源编码，回退 utf-8
    preserved = _load_preserved_encoding_meta(dest)
    source_encoding = (
        (extra_meta or {}).get("source_encoding")
        or preserved.get("source_encoding")
        or "utf-8"
    )
    sanitize_encoding = str(source_encoding).split("+")[0].strip() or "utf-8"

    # 字段名规范化
    geojson, field_sanitization = apply_field_sanitization(
        geojson, encoding=sanitize_encoding
    )
    features = list(geojson.get("features") or [])

    # 收集规范化后的字段名
    field_names = []
    for feat in features[:200]:
        props = feat.get("properties") or {}
        if isinstance(props, dict):
            for k in props:
                if k not in field_names:
                    field_names.append(str(k))

    # 写入 data.geojson（使用规范化后的字段名）
    data_path = dest / "data.geojson"
    data_path.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")

    # 写入 preview.geojson（使用规范化后的字段名）
    preview_features = features[:PREVIEW_FEATURE_LIMIT]
    preview = {"type": "FeatureCollection", "features": preview_features}
    (dest / "preview.geojson").write_text(
        json.dumps(preview, ensure_ascii=False), encoding="utf-8"
    )

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
        "field_sanitization": field_sanitization,
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
