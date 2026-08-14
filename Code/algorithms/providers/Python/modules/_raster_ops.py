"""Shared raster/vector helpers for preprocess, GIS, stats, and fusion modules.

Design rules (stub-nodes plan):
- Compute in float64; store COG as float32 by default (optional float64).
- Nodata = non-finite values unless an explicit nodata is provided.
- Large rasters prefer windowed reads; small rasters may load fully.
- Raster calculator expressions use a whitelist AST (no eval/exec).
"""

from __future__ import annotations

import ast
import json
import math
import operator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from contracts.product import ProductManifest, ProductRef
from path_utils import local_path_to_uri
from workflow.schemas import ArtifactRef, NodeExecutionContext

# Memory budget: rasters larger than this (bytes of float64) prefer windowed ops.
_FULL_READ_BUDGET_BYTES = 256 * 1024 * 1024  # 256 MiB float64 ≈ 32M cells


class RasterOpsValidationError(ValueError):
    """Input/parameter validation failure (maps to FailureCategory.validation_error)."""


class RasterOpsDataError(FileNotFoundError):
    """Missing or unreadable upstream data."""


@dataclass(frozen=True, slots=True)
class RasterBundle:
    """In-memory single-band (or multi-band) raster with georeference."""

    data: np.ndarray  # float64, shape (H, W) or (C, H, W)
    transform: Any  # rasterio.Affine
    crs: str
    nodata: float | None = None
    path: Path | None = None

    @property
    def height(self) -> int:
        return int(self.data.shape[-2])

    @property
    def width(self) -> int:
        return int(self.data.shape[-1])

    def band(self, index: int = 0) -> np.ndarray:
        if self.data.ndim == 2:
            if index != 0:
                raise RasterOpsValidationError(
                    f"band index {index} out of range for 2D raster"
                )
            return self.data
        if index < 0 or index >= self.data.shape[0]:
            raise RasterOpsValidationError(
                f"band index {index} out of range (count={self.data.shape[0]})"
            )
        return self.data[index]


def _coerce_path(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, Path)):
        text = str(value).strip()
        return text or None
    if isinstance(value, dict):
        for key in ("path", "uri", "input_path", "local_path", "filepath"):
            if value.get(key):
                return str(value[key]).strip() or None
        return None
    # ArtifactRef-like
    uri = getattr(value, "uri", None)
    if uri:
        return str(uri).strip() or None
    return None


def _path_from_manifest_payload(payload: object) -> str | None:
    if isinstance(payload, ProductManifest) and payload.products:
        for prod in payload.products:
            if prod.uri and prod.type in {
                "raster",
                "cog",
                "geotiff",
                "overlay",
                "map_layer",
                "data",
            }:
                return str(prod.uri)
        return str(payload.products[0].uri) if payload.products[0].uri else None
    if isinstance(payload, dict):
        products = payload.get("products") or []
        if isinstance(products, list) and products:
            first = products[0]
            if isinstance(first, dict) and first.get("uri"):
                return str(first["uri"])
        if payload.get("path"):
            return str(payload["path"])
    return None


def resolve_raster_path(
    inputs: dict[str, object],
    ctx: NodeExecutionContext,
    *,
    keys: Sequence[str] = (
        "raster",
        "dem",
        "primary",
        "secondary",
        "mask",
        "a",
        "b",
        "data",
    ),
    params: dict[str, object] | None = None,
) -> Path:
    """Resolve a local raster path from ports / manifest / datasource / params."""
    params = params or {}
    candidates: list[str] = []

    for key in keys:
        coerced = _coerce_path(inputs.get(key))
        if coerced:
            candidates.append(coerced)

    ds = inputs.get("datasource_selection")
    if isinstance(ds, dict):
        for key in ("input_path", "path", "uri"):
            if ds.get(key):
                candidates.append(str(ds[key]))

    for key in ("path", "input_path", "raster"):
        if params.get(key):
            candidates.append(str(params[key]))

    # Upstream manifest artifact (port may be named dem/primary/… not only raster)
    artifact_keys = list(
        dict.fromkeys(
            [*keys, "manifest", "raster", "data", "dem", "primary", "secondary"]
        )
    )
    for mkey in artifact_keys:
        art = inputs.get(mkey)
        if art is None:
            continue
        artifact_id = getattr(art, "artifact_id", None)
        if artifact_id and hasattr(ctx.artifact_store, "load"):
            try:
                loaded = ctx.artifact_store.load(str(artifact_id))
                found = _path_from_manifest_payload(loaded)
                if found:
                    candidates.append(found)
            except Exception:
                pass
        found = _path_from_manifest_payload(art)
        if found:
            candidates.append(found)

    for raw in candidates:
        text = raw.strip().replace("file:///", "").replace("file://", "")
        if text.lower().startswith("file:"):
            text = text[5:]
        path = Path(text)
        if path.exists() and path.is_file():
            return path.resolve()

    if candidates:
        raise RasterOpsDataError(
            f"Raster path not found on disk (tried: {candidates[0]!r})"
        )
    raise RasterOpsValidationError(
        "Need a raster path via port, upstream manifest, or datasource_selection.input_path"
    )


def resolve_geojson(
    inputs: dict[str, object],
    ctx: NodeExecutionContext,
    *,
    keys: Sequence[str] = (
        "points",
        "zones",
        "vector",
        "pour_points",
        "buffer",
        "data",
    ),
    params: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Load GeoJSON FeatureCollection from port value, path, or manifest."""
    params = params or {}
    for key in keys:
        value = inputs.get(key)
        if value is None:
            continue
        if isinstance(value, dict) and value.get("type") in {
            "FeatureCollection",
            "Feature",
            "Point",
            "Polygon",
            "MultiPolygon",
            "LineString",
            "MultiLineString",
        }:
            if value.get("type") == "FeatureCollection":
                return value
            if value.get("type") == "Feature":
                return {"type": "FeatureCollection", "features": [value]}
            return {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "geometry": value, "properties": {}}],
            }
        path = _coerce_path(value)
        if path:
            p = Path(path.replace("file:///", "").replace("file://", ""))
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        artifact_id = getattr(value, "artifact_id", None)
        if artifact_id and hasattr(ctx.artifact_store, "load"):
            try:
                loaded = ctx.artifact_store.load(str(artifact_id))
                if isinstance(loaded, dict):
                    return (
                        loaded
                        if loaded.get("type")
                        else {"type": "FeatureCollection", "features": []}
                    )
                found = _path_from_manifest_payload(loaded)
                if found and Path(found).exists():
                    return json.loads(Path(found).read_text(encoding="utf-8"))
            except Exception:
                pass

    for key in ("geojson_path", "path", "vector"):
        if params.get(key):
            p = Path(str(params[key]))
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))

    raise RasterOpsValidationError("Need GeoJSON via port, path, or upstream artifact")


def parse_bbox(value: object | None) -> tuple[float, float, float, float] | None:
    """Parse bbox as (west, south, east, north)."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    if isinstance(value, dict):
        if all(k in value for k in ("west", "south", "east", "north")):
            return (
                float(value["west"]),
                float(value["south"]),
                float(value["east"]),
                float(value["north"]),
            )
        if all(k in value for k in ("minx", "miny", "maxx", "maxy")):
            return (
                float(value["minx"]),
                float(value["miny"]),
                float(value["maxx"]),
                float(value["maxy"]),
            )
        if "bbox" in value:
            return parse_bbox(value["bbox"])
    text = str(value).strip()
    if text:
        parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
        if len(parts) >= 4:
            return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
    return None


def open_raster(
    path: Path | str,
    *,
    band: int | None = None,
    as_float64: bool = True,
) -> RasterBundle:
    """Open a GeoTIFF (or GDAL-readable raster) into a RasterBundle."""
    import rasterio

    path = Path(path)
    if not path.exists():
        raise RasterOpsDataError(f"Raster not found: {path}")

    with rasterio.open(path) as ds:
        crs = ds.crs.to_string() if ds.crs else "EPSG:4326"
        transform = ds.transform
        nodata = ds.nodata
        if band is not None:
            arr = ds.read(band + 1)
            if as_float64:
                arr = np.asarray(arr, dtype=np.float64)
            if nodata is not None:
                arr = np.where(arr == nodata, np.nan, arr)
        else:
            arr = ds.read()
            if as_float64:
                arr = np.asarray(arr, dtype=np.float64)
            if nodata is not None:
                arr = np.where(arr == nodata, np.nan, arr)
            if arr.shape[0] == 1:
                arr = arr[0]

    return RasterBundle(
        data=arr,
        transform=transform,
        crs=crs,
        nodata=float(nodata) if nodata is not None else None,
        path=path,
    )


def finite_mask(arr: np.ndarray, nodata: float | None = None) -> np.ndarray:
    mask = np.isfinite(arr)
    if nodata is not None and np.isfinite(nodata):
        mask &= arr != nodata
    return mask


def write_cog(
    data: np.ndarray,
    output_dir: Path | str,
    output_name: str,
    *,
    transform: Any,
    crs: str,
    nodata: float | None = None,
    dtype: str = "float32",
    overwrite: bool = True,
) -> dict[str, Any]:
    """Write float data as COG via publish.COGWriter; compute stays float64 upstream."""
    from publish.raster_writer import COGWriter

    out = np.asarray(data)
    if out.ndim == 2:
        pass
    elif out.ndim == 3:
        pass
    else:
        raise RasterOpsValidationError(f"Unsupported array ndim={out.ndim}")

    writer = COGWriter(Path(output_dir), overwrite=overwrite)
    # Replace NaN with nodata for integer dtypes; keep NaN for float
    write_data = out
    write_nodata = nodata
    if np.issubdtype(np.dtype(dtype), np.floating):
        write_nodata = nodata if nodata is not None else float("nan")
    else:
        fill = -9999 if nodata is None else int(nodata)
        write_nodata = float(fill)
        write_data = np.where(np.isfinite(out), out, fill)

    meta = writer.write(
        write_data.astype(dtype, copy=False),
        output_name,
        crs=crs,
        transform=transform,
        nodata=write_nodata if np.isfinite(write_nodata) else None,
        dtype=dtype,
        compress="deflate",
    )
    return meta


def store_raster_manifest(
    ctx: NodeExecutionContext,
    *,
    module_name: str,
    uri: str,
    variable: str = "raster",
    extra: dict[str, object] | None = None,
    product_name: str | None = None,
    extra_products: list[ProductRef] | None = None,
) -> dict[str, object]:
    products = [
        ProductRef(
            name=product_name or Path(uri).name or module_name,
            type="raster",
            uri=uri,
            variable=variable,
            tags={"module": module_name, "kind": "raster"},
        )
    ]
    if extra_products:
        products.extend(extra_products)
    manifest = ProductManifest(
        job_id=ctx.request.job_id,
        run_id=ctx.runtime_context.run_id,
        products=products,
        main_layers=[variable],
        extra={"module_name": module_name, "path": uri, **(extra or {})},
    )
    artifact = ArtifactRef(
        artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
        artifact_type="product_manifest",
        format="python_object",
        uri=None,
        producer_node_id=ctx.node_id,
        schema_name="ProductManifest",
        metadata={"module_name": module_name},
    )
    ctx.artifact_store.put(artifact, payload=manifest)
    return {
        "manifest": artifact,
        "raster": uri,
        "path": uri,
        "uri": local_path_to_uri(uri, resolve=True)
        if not str(uri).startswith("file:")
        else uri,
    }


def store_geojson_manifest(
    ctx: NodeExecutionContext,
    *,
    module_name: str,
    geojson: dict[str, Any],
    output_path: Path,
    extra: dict[str, object] | None = None,
    port_name: str = "vector",
    extra_products: list[ProductRef] | None = None,
    table_uris: list[str] | None = None,
) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(geojson, ensure_ascii=True), encoding="utf-8")
    uri = str(output_path)
    products = [
        ProductRef(
            name=output_path.name,
            type="geojson",
            uri=uri,
            tags={"module": module_name, "kind": "vector"},
        )
    ]
    if extra_products:
        products.extend(extra_products)
    manifest = ProductManifest(
        job_id=ctx.request.job_id,
        run_id=ctx.runtime_context.run_id,
        products=products,
        tables=list(table_uris or []),
        extra={"module_name": module_name, "path": uri, **(extra or {})},
    )
    artifact = ArtifactRef(
        artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
        artifact_type="product_manifest",
        format="python_object",
        uri=None,
        producer_node_id=ctx.node_id,
        schema_name="ProductManifest",
        metadata={"module_name": module_name},
    )
    ctx.artifact_store.put(artifact, payload=manifest)
    return {"manifest": artifact, port_name: uri, "path": uri, "geojson": geojson}


def resampling_enum(name: str):
    from rasterio.enums import Resampling

    key = str(name or "nearest").lower()
    mapping = {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
        "average": Resampling.average,
        "mode": Resampling.mode,
    }
    if key not in mapping:
        raise RasterOpsValidationError(
            f"Unsupported resampling {name!r}; use one of {sorted(mapping)}"
        )
    return mapping[key]


def align_rasters(
    primary: RasterBundle,
    secondary: RasterBundle,
    *,
    resampling: str = "bilinear",
) -> RasterBundle:
    """Reproject secondary onto primary's grid (float64)."""
    from rasterio.warp import reproject

    src = secondary.band(0) if secondary.data.ndim == 3 else secondary.data
    dst = np.full((primary.height, primary.width), np.nan, dtype=np.float64)
    reproject(
        source=np.asarray(src, dtype=np.float64),
        destination=dst,
        src_transform=secondary.transform,
        src_crs=secondary.crs,
        dst_transform=primary.transform,
        dst_crs=primary.crs,
        resampling=resampling_enum(resampling),
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    return RasterBundle(
        data=dst,
        transform=primary.transform,
        crs=primary.crs,
        nodata=None,
        path=secondary.path,
    )


def estimate_full_read_ok(height: int, width: int, bands: int = 1) -> bool:
    return height * width * bands * 8 <= _FULL_READ_BUDGET_BYTES


def iter_block_windows(dataset: Any, *, band: int = 1):
    """Yield (window, data_f64) for each block of a rasterio dataset band."""
    from rasterio.windows import Window

    h, w = dataset.height, dataset.width
    block_h, block_w = 256, 256
    try:
        block_h, block_w = dataset.block_shapes[band - 1]
    except Exception:
        pass
    block_h = max(int(block_h), 64)
    block_w = max(int(block_w), 64)
    for row_off in range(0, h, block_h):
        for col_off in range(0, w, block_w):
            win = Window(
                col_off,
                row_off,
                min(block_w, w - col_off),
                min(block_h, h - row_off),
            )
            data = dataset.read(band, window=win)
            arr = np.asarray(data, dtype=np.float64)
            nodata = dataset.nodata
            if nodata is not None and np.isfinite(nodata):
                arr = np.where(arr == nodata, np.nan, arr)
            yield win, arr


def reduce_raster_blocks(
    path: Path | str,
    *,
    statistic: str,
    band: int = 0,
) -> tuple[float, int]:
    """Windowed spatial reduce for mean/min/max/sum/count/std (not median).

    Returns (value, finite_count).
    """
    import rasterio

    path = Path(path)
    stat = str(statistic).lower()
    if stat == "median":
        raise RasterOpsValidationError(
            "median on oversized rasters requires clip/resample first "
            "(windowed median is not supported)"
        )
    allowed = {"mean", "min", "max", "sum", "count", "std"}
    if stat not in allowed:
        raise RasterOpsValidationError(
            f"windowed statistic must be one of {sorted(allowed)}"
        )

    with rasterio.open(path) as ds:
        band_i = min(max(band, 0), ds.count - 1) + 1
        count = 0
        total = 0.0
        total_sq = 0.0
        vmin = np.inf
        vmax = -np.inf
        for _win, arr in iter_block_windows(ds, band=band_i):
            finite = arr[np.isfinite(arr)]
            if finite.size == 0:
                continue
            count += int(finite.size)
            total += float(np.sum(finite))
            if stat == "std":
                total_sq += float(np.sum(finite * finite))
            if stat in {"min", "max", "mean", "sum", "count", "std"}:
                vmin = min(vmin, float(np.min(finite)))
                vmax = max(vmax, float(np.max(finite)))

    if count == 0:
        raise RasterOpsValidationError("No finite pixels for spatial statistic")
    if stat == "count":
        return float(count), count
    if stat == "sum":
        return total, count
    if stat == "mean":
        return total / count, count
    if stat == "min":
        return vmin, count
    if stat == "max":
        return vmax, count
    # std
    mean = total / count
    var = max(total_sq / count - mean * mean, 0.0)
    return float(np.sqrt(var)), count


def chunked_map(
    items: Sequence[Any],
    fn: Callable[[Any], Any],
    *,
    max_workers: int | None = None,
) -> list[Any]:
    """Map over independent items with optional process pool (spawn-safe)."""
    if not items:
        return []
    if len(items) == 1 or (max_workers is not None and max_workers <= 1):
        return [fn(item) for item in items]

    try:
        from algorithms._parallel import auto_process_count

        workers = auto_process_count(chunk_count=len(items), max_workers=max_workers)
    except Exception:
        workers = min(2, len(items))

    if workers <= 1:
        return [fn(item) for item in items]

    # ProcessPool requires picklable top-level callables; callers should pass module-level fns.
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


# ---------------------------------------------------------------------------
# Safe raster expression (AST whitelist)
# ---------------------------------------------------------------------------

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_ALLOWED_FUNCS: dict[str, Callable[..., Any]] = {
    "abs": np.abs,
    "sqrt": np.sqrt,
    "log": np.log,
    "log10": np.log10,
    "exp": np.exp,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "minimum": np.minimum,
    "maximum": np.maximum,
    "where": np.where,
    "clip": np.clip,
    "nan_to_num": np.nan_to_num,
}


def safe_raster_expression(
    expression: str,
    variables: dict[str, np.ndarray],
) -> np.ndarray:
    """Evaluate a restricted arithmetic expression over named raster arrays."""
    expr = (expression or "").strip()
    if not expr:
        raise RasterOpsValidationError("expression must not be empty")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise RasterOpsValidationError(f"Invalid expression syntax: {exc}") from exc

    def _eval(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise RasterOpsValidationError(f"Disallowed constant: {node.value!r}")
        if isinstance(node, ast.Name):
            key = node.id
            # Allow A/B/C aliases case-insensitively
            for k, v in variables.items():
                if k.lower() == key.lower():
                    return np.asarray(v, dtype=np.float64)
            if key.lower() in {"pi", "e"}:
                return float(getattr(math, key.lower()))
            raise RasterOpsValidationError(f"Unknown variable {key!r}")
        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in _BIN_OPS:
                raise RasterOpsValidationError(
                    f"Disallowed operator: {op_type.__name__}"
                )
            return _BIN_OPS[op_type](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in _UNARY_OPS:
                raise RasterOpsValidationError(
                    f"Disallowed unary op: {op_type.__name__}"
                )
            return _UNARY_OPS[op_type](_eval(node.operand))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise RasterOpsValidationError("Only simple function calls allowed")
            fname = node.func.id
            if fname not in _ALLOWED_FUNCS:
                raise RasterOpsValidationError(
                    f"Disallowed function {fname!r}; allowed={sorted(_ALLOWED_FUNCS)}"
                )
            args = [_eval(a) for a in node.args]
            if node.keywords:
                raise RasterOpsValidationError("Keyword arguments are not allowed")
            return _ALLOWED_FUNCS[fname](*args)
        if isinstance(node, ast.Compare):
            # Support chained comparisons for thresholding: A > 0
            left = _eval(node.left)
            result = np.ones_like(np.asarray(left, dtype=np.float64), dtype=bool)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right = _eval(comparator)
                if isinstance(op, ast.Lt):
                    result = result & (left < right)
                elif isinstance(op, ast.LtE):
                    result = result & (left <= right)
                elif isinstance(op, ast.Gt):
                    result = result & (left > right)
                elif isinstance(op, ast.GtE):
                    result = result & (left >= right)
                elif isinstance(op, ast.Eq):
                    result = result & (left == right)
                elif isinstance(op, ast.NotEq):
                    result = result & (left != right)
                else:
                    raise RasterOpsValidationError(
                        f"Disallowed comparison {type(op).__name__}"
                    )
                left = right
            return result.astype(np.float64)
        raise RasterOpsValidationError(
            f"Disallowed expression node: {type(node).__name__}"
        )

    out = _eval(tree)
    arr = np.asarray(out, dtype=np.float64)
    if arr.ndim == 0:
        # Broadcast scalar to first variable shape
        ref = next(iter(variables.values()))
        arr = np.full(np.asarray(ref).shape, float(arr), dtype=np.float64)
    return arr


def parse_remap_table(table: str) -> list[tuple[float, float, float]]:
    """Parse remap like '0-30:1,30-60:2' into (lo, hi, value) half-open [lo, hi)."""
    text = (table or "").strip()
    if not text:
        raise RasterOpsValidationError("remap_table must not be empty")
    rules: list[tuple[float, float, float]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise RasterOpsValidationError(
                f"Invalid remap rule {part!r} (need lo-hi:value)"
            )
        rng, val_s = part.rsplit(":", 1)
        if "-" not in rng:
            raise RasterOpsValidationError(f"Invalid range {rng!r}")
        lo_s, hi_s = rng.split("-", 1)
        rules.append((float(lo_s), float(hi_s), float(val_s)))
    if not rules:
        raise RasterOpsValidationError("remap_table produced no rules")
    return rules


def apply_remap(
    data: np.ndarray,
    rules: Iterable[tuple[float, float, float]],
    *,
    nodata_value: float = -9999.0,
) -> np.ndarray:
    out = np.full(data.shape, nodata_value, dtype=np.float64)
    valid = finite_mask(data)
    for lo, hi, val in rules:
        sel = valid & (data >= lo) & (data < hi)
        out[sel] = val
    return out


def load_timeseries_payload(
    inputs: dict[str, object],
    ctx: NodeExecutionContext,
    *,
    keys: Sequence[str] = ("timeseries", "x", "y", "data"),
) -> dict[str, Any]:
    """Load a timeseries dict with keys times (ISO list) and values (list or 3D stack path)."""
    for key in keys:
        value = inputs.get(key)
        if value is None:
            continue
        if isinstance(value, dict) and ("values" in value or "y" in value):
            return value
        path = _coerce_path(value)
        if path and Path(path).exists():
            p = Path(path)
            if p.suffix.lower() == ".json":
                return json.loads(p.read_text(encoding="utf-8"))
            # Raster stack as timeseries surrogate: single value = spatial mean over time N/A
        artifact_id = getattr(value, "artifact_id", None)
        if artifact_id and hasattr(ctx.artifact_store, "load"):
            try:
                loaded = ctx.artifact_store.load(str(artifact_id))
                if isinstance(loaded, dict):
                    return loaded
                found = _path_from_manifest_payload(loaded)
                if found and Path(found).suffix.lower() == ".json":
                    return json.loads(Path(found).read_text(encoding="utf-8"))
            except Exception:
                pass
    raise RasterOpsValidationError(
        "Need timeseries payload {times, values} via port or JSON path"
    )


def emit_progress(
    ctx: NodeExecutionContext, stage: str, message: str, pct: float | None = None
) -> None:
    if ctx.logger_adapter is None:
        return
    extra = {"progress_pct": pct} if pct is not None else None
    try:
        if hasattr(ctx.logger_adapter, "emit_progress"):
            ctx.logger_adapter.emit_progress(stage, message, extra=extra or {})
        else:
            ctx.logger_adapter.emit_stage_start(stage, message)
    except Exception:
        pass
