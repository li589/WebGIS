"""文档导入会话：csv/xlsx/xls/txt + 基础表操作 + commit 为点图层。"""

from __future__ import annotations

import csv
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.data_io.services.dbf_encoding import (
    codec_available,
    score_decoded_text,
)
from app.data_io.services.paths import (
    DOC_PREVIEW_ROW_LIMIT,
    DOC_SESSIONS_DIR,
    ensure_imports_root,
    safe_import_child,
)
from app.data_io.services.vector import import_vector_from_paths

# CSV 编码候选池（优先级从高到低）
_CSV_ENCODING_CANDIDATES: tuple[str, ...] = (
    "utf-8-sig",
    "utf-8",
    "gb18030",
    "gbk",
    "big5",
    "cp932",
    "shift_jis",
    "cp949",
    "euc_kr",
    "cp1252",
    "cp1250",
    "cp1251",
    "latin-1",
)


def _session_dir(session_id: str) -> Path:
    # 安审 2026-08-22（B-2）：session_id 纯目录名校验，防越界读/写 table.json
    return safe_import_child(session_id, root=DOC_SESSIONS_DIR)


def _load_table(session_id: str) -> dict[str, Any]:
    path = _session_dir(session_id) / "table.json"
    if not path.exists():
        raise FileNotFoundError(f"文档会话不存在: {session_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_table(session_id: str, table: dict[str, Any]) -> None:
    dest = _session_dir(session_id)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "table.json").write_text(
        json.dumps(table, ensure_ascii=False), encoding="utf-8"
    )


def _detect_csv_encoding(path: Path) -> tuple[str, str]:
    """探测 CSV 文件最佳编码（类似 DBF 的多编码探测策略）。

    Returns:
        (encoding, detection_note)
    """
    raw = path.read_bytes()
    if not raw:
        return "utf-8-sig", "空文件，默认 utf-8-sig"

    # 尝试 BOM 检测
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig", "BOM 检测：UTF-8 with BOM"
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16", "BOM 检测：UTF-16"

    # 采样前 8KB 用于编码评分
    sample = raw[:8192]
    best: tuple[float, str] | None = None
    for enc in _CSV_ENCODING_CANDIDATES:
        if not codec_available(enc):
            continue
        try:
            text = sample.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        # 取前几行做评分
        lines = text.splitlines()[:20]
        score = score_decoded_text(lines, encoding=enc)
        if best is None or score > best[0]:
            best = (score, enc)

    if best is not None:
        return best[1], f"评分检测：{best[1]}（score={best[0]:.2f}）"
    return "utf-8-sig", "全部编码失败，回退 utf-8-sig+replace"


def _read_csv_like(path: Path, *, delimiter: str | None = None) -> dict[str, Any]:
    """读取 CSV/TXT 文件，自动探测编码与分隔符。"""
    encoding, enc_note = _detect_csv_encoding(path)
    text = path.read_text(encoding=encoding, errors="replace")
    sample = text[:4096]
    if delimiter is None:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = "," if sample.count(",") >= sample.count("\t") else "\t"
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    columns = list(reader.fieldnames or [])
    rows: list[dict[str, Any]] = []
    for i, row in enumerate(reader):
        if i >= 200_000:
            break
        rows.append(
            {k: (row.get(k) if row.get(k) is not None else "") for k in columns}
        )
    return {
        "columns": columns,
        "rows": rows,
        "delimiter": delimiter,
        "encoding": encoding,
        "encoding_note": enc_note,
    }


def _read_excel(path: Path) -> dict[str, Any]:
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 pandas，无法读取 Excel") from exc

    engine = None
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        engine = "openpyxl"
    elif suffix == ".xls":
        engine = "xlrd"
    try:
        df = pd.read_excel(path, engine=engine)
    except Exception:
        # 回退让 pandas 自选
        df = pd.read_excel(path)
    columns = [str(c) for c in df.columns.tolist()]
    records = df.fillna("").astype(str).to_dict(orient="records")
    rows = [{c: r.get(c, "") for c in columns} for r in records[:200_000]]
    return {"columns": columns, "rows": rows, "delimiter": None}


def create_document_session(
    path: Path, *, source_name: str | None = None
) -> dict[str, Any]:
    ensure_imports_root()
    ext = path.suffix.lower()
    if ext in {".csv", ".txt"}:
        table = _read_csv_like(path)
    elif ext in {".xlsx", ".xls"}:
        table = _read_excel(path)
    else:
        raise ValueError(f"不支持的文档格式: {ext}")

    session_id = f"doc-{uuid.uuid4().hex[:12]}"
    dest = _session_dir(session_id)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest / path.name)
    payload = {
        "session_id": session_id,
        "source_name": source_name or path.name,
        "columns": table["columns"],
        "rows": table["rows"],
        "row_count": len(table["rows"]),
        "delimiter": table.get("delimiter"),
        "source_encoding": table.get("encoding"),
        "encoding_note": table.get("encoding_note"),
    }
    _save_table(session_id, payload)
    return preview_document_session(session_id)


def preview_document_session(session_id: str) -> dict[str, Any]:
    table = _load_table(session_id)
    rows = table.get("rows") or []
    preview_rows = rows[:DOC_PREVIEW_ROW_LIMIT]
    return {
        "session_id": session_id,
        "source_name": table.get("source_name"),
        "columns": table.get("columns") or [],
        "row_count": len(rows),
        "preview_row_count": len(preview_rows),
        "truncated": len(rows) > DOC_PREVIEW_ROW_LIMIT,
        "rows": preview_rows,
        "source_encoding": table.get("source_encoding"),
        "encoding_note": table.get("encoding_note"),
    }


def apply_document_ops(session_id: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
    table = _load_table(session_id)
    columns: list[str] = list(table.get("columns") or [])
    rows: list[dict[str, Any]] = list(table.get("rows") or [])

    for op in ops:
        kind = str(op.get("op") or "").lower()
        if kind == "rename":
            old = str(op.get("from") or "")
            new = str(op.get("to") or "")
            if old not in columns or not new:
                raise ValueError(f"重命名失败: {old} → {new}")
            columns = [new if c == old else c for c in columns]
            for row in rows:
                if old in row:
                    row[new] = row.pop(old)
        elif kind == "filter":
            field = str(op.get("field") or "")
            contains = str(op.get("contains") or "").lower()
            rows = [
                r
                for r in rows
                if field in r and contains in str(r.get(field, "")).lower()
            ]
        elif kind == "find_replace":
            field = str(op.get("field") or "")
            find = str(op.get("find") or "")
            replace = str(op.get("replace") or "")
            if field not in columns:
                raise ValueError(f"字段不存在: {field}")
            for row in rows:
                val = str(row.get(field, ""))
                row[field] = val.replace(find, replace)
        elif kind == "split":
            field = str(op.get("field") or "")
            separator = str(op.get("separator") or ",")
            into = op.get("into") or []
            if field not in columns or not isinstance(into, list) or len(into) < 2:
                raise ValueError("分列参数无效")
            new_cols = [str(c) for c in into]
            for col in new_cols:
                if col not in columns:
                    columns.append(col)
            for row in rows:
                parts = str(row.get(field, "")).split(separator)
                for i, col in enumerate(new_cols):
                    row[col] = parts[i].strip() if i < len(parts) else ""
        else:
            raise ValueError(f"不支持的操作: {kind}")

    table["columns"] = columns
    table["rows"] = rows
    table["row_count"] = len(rows)
    _save_table(session_id, table)
    return preview_document_session(session_id)


def commit_document_session(
    session_id: str,
    *,
    x_field: str,
    y_field: str,
    source_crs: str = "EPSG:4326",
    target_crs: str = "EPSG:4326",
    lng_offset: float = 0.0,
    lat_offset: float = 0.0,
    swap_xy: bool | None = None,
) -> dict[str, Any]:
    table = _load_table(session_id)
    columns = table.get("columns") or []
    if x_field not in columns or y_field not in columns:
        raise ValueError("XY 字段不存在")

    points: list[tuple[float, float]] = []
    props_list: list[dict[str, Any]] = []
    for row in table.get("rows") or []:
        try:
            x = float(row.get(x_field))
            y = float(row.get(y_field))
        except (TypeError, ValueError):
            continue
        points.append((x, y))
        props_list.append({k: v for k, v in row.items() if k not in {x_field, y_field}})

    if not points:
        raise ValueError("没有有效的坐标行")

    # swap_xy: True 强制交换；False 保持；None 对采样点 bounds 自动检测
    xy_swap_applied = False
    xy_swap_note = ""
    if swap_xy is True:
        points = [(y, x) for x, y in points]
        xy_swap_applied = True
        xy_swap_note = "强制交换 XY"
    elif swap_xy is False:
        xy_swap_note = "保持 XY（用户指定不交换）"
    else:
        sample = points[: min(500, len(points))]
        xs = [p[0] for p in sample]
        ys = [p[1] for p in sample]
        sample_bounds = (min(xs), min(ys), max(xs), max(ys))
        from app.services.crs import crs_detector

        is_swapped, xy_swap_note = crs_detector.detect_xy_swap(
            sample_bounds, source_crs=source_crs
        )
        if is_swapped:
            points = [(y, x) for x, y in points]
            xy_swap_applied = True

    if source_crs != target_crs or lng_offset or lat_offset:
        from app.services.crs import crs_transformer

        transformed = crs_transformer.transform_points_batch(
            points,
            source_crs,
            target_crs,
            lng_offset=lng_offset,
            lat_offset=lat_offset,
        )
        points = [(float(r.lng), float(r.lat)) for r in transformed]

    features = []
    for (lng, lat), props in zip(points, props_list, strict=False):
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": props,
            }
        )
    geojson = {"type": "FeatureCollection", "features": features}

    # 写入临时 geojson 再走矢量入库
    dest = _session_dir(session_id)
    tmp = dest / "commit.geojson"
    tmp.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    result = import_vector_from_paths(
        [tmp], source_name=str(table.get("source_name") or session_id)
    )
    result["session_id"] = session_id
    result["point_count"] = len(features)
    result["xy_swap_applied"] = xy_swap_applied
    result["xy_swap_note"] = xy_swap_note
    return result


_SAFE_NAME = re.compile(r"[^\w.\-]+", re.UNICODE)
