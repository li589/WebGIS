from __future__ import annotations

import contextlib
import importlib
import json
import re
from pathlib import Path
from typing import Literal

NodataMode = Literal["transparent", "solid"]


# P2-E（2026-08-24）色带单源：定义与别名以 catalog_seeds/palettes.json 为
# 唯一真源（前端 src/data/weather-palettes.generated.ts 由
# Tools/generate_palette_config.py 从同一 JSON 生成），消除前后端双维护
# 漂移。改色带只改 JSON + 跑脚本，禁止在代码里加色带。
_PALETTES_PATH = (
    Path(__file__).resolve().parent.parent / "catalog_seeds" / "palettes.json"
)


def _load_palettes_from_config() -> (
    tuple[dict[str, list[tuple[int, int, int]]], dict[str, str]]
):
    def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
        value = hex_str.lstrip("#")
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))

    raw = json.loads(_PALETTES_PATH.read_text(encoding="utf-8"))
    palettes = {
        str(key): [_hex_to_rgb(c) for c in entry["colors"]]
        for key, entry in raw.get("palettes", {}).items()
    }
    aliases = {str(k): str(v) for k, v in raw.get("backend_aliases", {}).items()}
    if not palettes or "viridis" not in palettes:
        raise ValueError("palettes.json invalid: viridis baseline missing")
    return palettes, aliases


_PALETTES, _PALETTE_ALIASES = _load_palettes_from_config()


def resolve_palette_id(palette: str | None) -> str:
    raw = (palette or "").strip() or "viridis"
    aliased = _PALETTE_ALIASES.get(raw) or _PALETTE_ALIASES.get(raw.lower())
    if aliased:
        key = aliased
    else:
        key = raw.lower() if raw.lower() in _PALETTES else raw
    if key in _PALETTES:
        return key
    if raw in _PALETTES:
        return raw
    return "viridis"


def get_palette_rgb_stops(palette: str | None) -> list[tuple[int, int, int]]:
    return list(_PALETTES[resolve_palette_id(palette)])


def parse_nodata_color(raw: str | None) -> tuple[int, int, int]:
    """Parse ``#rgb`` / ``#rrggbb`` / ``r,g,b`` → RGB; default dark gray."""
    if not raw or not str(raw).strip():
        return (32, 36, 48)
    text = str(raw).strip()
    if text.startswith("#"):
        h = text[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) == 6 and re.fullmatch(r"[0-9a-fA-F]{6}", h):
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    parts = re.split(r"[,/\s]+", text)
    if len(parts) >= 3:
        try:
            r, g, b = (max(0, min(255, int(float(parts[i])))) for i in range(3))
            return (r, g, b)
        except (TypeError, ValueError):
            pass
    return (32, 36, 48)


def normalize_nodata_mode(raw: str | None) -> NodataMode:
    mode = (raw or "transparent").strip().lower()
    return "solid" if mode == "solid" else "transparent"


def _mask_invalid_raster(numpy, band, *, nodata: float | None = None):
    """Mask nodata + non-finite samples so voids become transparent.

    2026-08-24 CLCD 报障：整型源（uint8 分类数据）上 ``filled(nan)`` 会抛
    TypeError（NaN 无法转 int dtype）→ 注册 preview 渲染整链失败。先
    astype(float64)（MaskedArray 保 mask）再做 NaN 填充，任意 dtype 安全。
    """
    arr = numpy.ma.asarray(band)
    arrf = arr.astype("float64")
    invalid = ~numpy.isfinite(numpy.ma.filled(arrf, numpy.nan))
    if nodata is not None and numpy.isfinite(nodata):
        invalid = invalid | numpy.isclose(
            numpy.ma.filled(arrf, float(nodata)), float(nodata), equal_nan=False
        )
    invalid = invalid | numpy.ma.getmaskarray(arr)
    return numpy.ma.array(numpy.ma.filled(arrf, numpy.nan), mask=invalid)


def _colorize_masked_band(
    numpy,
    masked_array,
    palette_colors,
    *,
    min_value: float | None,
    max_value: float | None,
    nodata_mode: NodataMode = "transparent",
    nodata_rgb: tuple[int, int, int] = (32, 36, 48),
):
    count = int(masked_array.count()) if hasattr(masked_array, "count") else 0
    if min_value is None:
        # 2026-08-24 统一归一化基准：与瓦片路径（overlay_tile_service
        # ._source_value_range / _apply_palette）一致改用 p2/p98 百分位。
        # 此前用全量 min/max——与瓦片 p2/p98 两套基准，image↔瓦片模式切换
        # 时同数据色阶突变；且 min/max 受极值敏感（火点/异常值压扁整体色阶）。
        # filled(nan) 前先转 float：整型源（uint8 分类）会抛 TypeError
        # （2026-08-24 CLCD 注册失败根因之一）。
        if count >= 100:
            min_value = float(
                numpy.nanpercentile(
                    numpy.ma.filled(masked_array.astype("float64"), numpy.nan), 2
                )
            )
        else:
            min_value = float(masked_array.min()) if count else 0.0
    if max_value is None:
        if count >= 100:
            max_value = float(
                numpy.nanpercentile(
                    numpy.ma.filled(masked_array.astype("float64"), numpy.nan), 98
                )
            )
        else:
            max_value = (
                float(masked_array.max()) if count else max(float(min_value) + 1.0, 1.0)
            )
    if not numpy.isfinite(min_value):
        min_value = 0.0
    if not numpy.isfinite(max_value) or max_value <= min_value:
        max_value = float(min_value) + 1.0

    fill = float(min_value)
    data = masked_array.filled(fill).astype("float32")
    data = numpy.where(numpy.isfinite(data), data, fill)
    norm = numpy.clip(
        (data - float(min_value)) / (float(max_value) - float(min_value)), 0.0, 1.0
    )
    anchors = numpy.linspace(0.0, 1.0, len(palette_colors), dtype="float32")
    red = numpy.interp(norm, anchors, palette_colors[:, 0]).astype("uint8")
    green = numpy.interp(norm, anchors, palette_colors[:, 1]).astype("uint8")
    blue = numpy.interp(norm, anchors, palette_colors[:, 2]).astype("uint8")
    mask = numpy.ma.getmaskarray(masked_array)
    if nodata_mode == "solid":
        nr, ng, nb = nodata_rgb
        red = numpy.where(mask, nr, red).astype("uint8")
        green = numpy.where(mask, ng, green).astype("uint8")
        blue = numpy.where(mask, nb, blue).astype("uint8")
        alpha = numpy.full(mask.shape, 255, dtype="uint8")
    else:
        alpha = numpy.where(mask, 0, 255).astype("uint8")
    return red, green, blue, alpha


def colorize_array_to_rgba(
    data: object,
    *,
    palette: str | None = "viridis",
    min_value: float | None = None,
    max_value: float | None = None,
    nodata: float | None = None,
    nodata_mode: str | None = "transparent",
    nodata_color: str | None = None,
) -> object:
    """Colorize a 2D float array into HxWx4 uint8 RGBA (shared by tiles / overlay preview)."""
    numpy = importlib.import_module("numpy")
    arr = numpy.asarray(data, dtype="float32")
    if arr.ndim != 2:
        raise ValueError(f"colorize expects 2D array, got shape={arr.shape}")
    masked = _mask_invalid_raster(numpy, arr, nodata=nodata)
    stops = numpy.array(get_palette_rgb_stops(palette), dtype="float32")
    red, green, blue, alpha = _colorize_masked_band(
        numpy,
        masked,
        stops,
        min_value=min_value,
        max_value=max_value,
        nodata_mode=normalize_nodata_mode(nodata_mode),
        nodata_rgb=parse_nodata_color(nodata_color),
    )
    return numpy.stack([red, green, blue, alpha], axis=-1)


def encode_rgba_png(rgba: object) -> bytes:
    """Encode HxWx4 uint8 array as PNG bytes."""
    numpy = importlib.import_module("numpy")
    from PIL import Image

    arr = numpy.asarray(rgba, dtype="uint8")
    if arr.ndim != 3 or arr.shape[2] != 4:
        raise ValueError(f"encode_rgba_png expects HxWx4, got {arr.shape}")
    img = Image.fromarray(arr, mode="RGBA")
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _finite_data_window_bounds(numpy, src_band, src_transform, *, pad_pixels: int = 8):
    """Return cropped source-CRS bounds covering finite pixels, or None.

    Used when valid data is a tiny fraction of a global grid so the preview
    and map fitBounds land on the actual patch instead of a black globe.
    """
    masked = _mask_invalid_raster(numpy, src_band)
    valid = ~numpy.ma.getmaskarray(masked)
    if not valid.any():
        return None
    valid_frac = float(valid.mean())
    if valid_frac >= 0.05:
        return None
    rows = numpy.where(valid.any(axis=1))[0]
    cols = numpy.where(valid.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return None
    r0 = max(0, int(rows.min()) - pad_pixels)
    r1 = min(valid.shape[0] - 1, int(rows.max()) + pad_pixels)
    c0 = max(0, int(cols.min()) - pad_pixels)
    c1 = min(valid.shape[1] - 1, int(cols.max()) + pad_pixels)
    # pixel corners → source CRS
    xs = []
    ys = []
    for r, c in ((r0, c0), (r0, c1 + 1), (r1 + 1, c0), (r1 + 1, c1 + 1)):
        x, y = src_transform * (c, r)
        xs.append(float(x))
        ys.append(float(y))
    return min(xs), min(ys), max(xs), max(ys)


class RasterPreviewService:
    def render_cog_preview(
        self,
        *,
        cog_path: str | Path,
        palette: str,
        width: int,
        height: int,
        min_value: float | None = None,
        max_value: float | None = None,
        nodata_mode: str | None = "transparent",
        nodata_color: str | None = None,
    ) -> bytes:
        try:
            numpy = importlib.import_module("numpy")
            rasterio = importlib.import_module("rasterio")
            memory_file_cls = importlib.import_module("rasterio.io").MemoryFile
            resampling = importlib.import_module("rasterio.enums").Resampling
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise ValueError(
                f"Raster preview dependencies unavailable: {exc.__class__.__name__}"
            ) from exc

        palette_colors = numpy.array(get_palette_rgb_stops(palette), dtype="float32")
        width = max(64, min(2048, int(width)))
        height = max(64, min(2048, int(height)))

        with rasterio.open(Path(cog_path)) as dataset:
            band = dataset.read(
                1,
                out_shape=(height, width),
                resampling=resampling.bilinear,
                masked=True,
            )

        masked_array = _mask_invalid_raster(numpy, band)
        red, green, blue, alpha = _colorize_masked_band(
            numpy,
            masked_array,
            palette_colors,
            min_value=min_value,
            max_value=max_value,
            nodata_mode=normalize_nodata_mode(nodata_mode),
            nodata_rgb=parse_nodata_color(nodata_color),
        )

        with memory_file_cls() as memory_file:
            with memory_file.open(
                driver="PNG",
                width=width,
                height=height,
                count=4,
                dtype="uint8",
            ) as dataset:
                dataset.write(red, 1)
                dataset.write(green, 2)
                dataset.write(blue, 3)
                dataset.write(alpha, 4)
            return memory_file.read()

    def render_cog_preview_reprojected(
        self,
        *,
        cog_path: str | Path,
        palette: str,
        width: int,
        height: int,
        source_crs: str,
        target_crs: str = "EPSG:4326",
        min_value: float | None = None,
        max_value: float | None = None,
        crop_to_data: bool = True,
    ) -> tuple[bytes, tuple[float, float, float, float]]:
        """重投影栅格到 ``target_crs`` 后生成 PNG，返回 ``(png_bytes, target_bounds)``。

        内部用 ``rasterio.warp.calculate_default_transform`` + ``reproject``：
        1. 读源栅格 CRS/bounds
        2. ``calculate_default_transform(src_crs, dst_crs, ...)`` 得到目标 transform/尺寸
        3. ``reproject`` 把源 band 重采样到目标网格（bilinear）
        4. 按原 ``render_cog_preview`` 着色逻辑生成 PNG
        5. ``array_bounds(dst_height, dst_width, dst_transform)`` 得目标 bounds

        Args:
            cog_path: 源 GeoTIFF 路径
            palette: 配色方案（同 ``render_cog_preview``）
            width/height: 输出 PNG 尺寸上限（实际 dst 尺寸由 calculate_default_transform 决定）
            source_crs: 源 CRS code（如 'EPSG:32650'）
            target_crs: 目标 CRS code（默认 'EPSG:4326'）
            min_value/max_value: 着色值域，None 时自动从重投影后数据推断
            crop_to_data: 稀疏有效像元时是否裁到数据窗。时间序列全网格产品应关闭，
                否则各时刻裁剪范围不同 → 换时仅换 PNG 不换坐标时出现南北压缩/偏移。

        Returns:
            ``(png_bytes, (west, south, east, north))``，bounds 在 ``target_crs`` 下
        """
        try:
            numpy = importlib.import_module("numpy")
            rasterio = importlib.import_module("rasterio")
            memory_file_cls = importlib.import_module("rasterio.io").MemoryFile
            resampling = importlib.import_module("rasterio.enums").Resampling
            warp = importlib.import_module("rasterio.warp")
            array_bounds = importlib.import_module("rasterio.transform").array_bounds
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise ValueError(
                f"Raster preview dependencies unavailable: {exc.__class__.__name__}"
            ) from exc

        palette_colors = numpy.array(get_palette_rgb_stops(palette), dtype="float32")
        # width/height 仅作为 dst 计算的输入提示，最终由 calculate_default_transform 决定
        width = max(64, min(2048, int(width)))
        height = max(64, min(2048, int(height)))

        with rasterio.open(Path(cog_path)) as dataset:
            src_bounds = dataset.bounds  # (west, south, east, north) in source_crs
            src_transform = dataset.transform
            src_width = dataset.width
            src_height = dataset.height
            # 2026-08-24 CLCD 报障：巨型源（CLCD_v01 228579×131361 / 821MB、
            # stripped 无 overview）全分辨率 read(1) 要分配 ~30GB → 注册在
            # preview 渲染一步死掉（imports 目录只剩源文件、无 bounds.json/
            # preview.png = "工作流完成但图层不显示"）。超过 2048 边一律降
            # 采样读（nearest 保类别），transform 按比例缩放；warp 精度对
            # ≤2048 预览无损。
            if max(src_width, src_height) > 2048:
                from rasterio.enums import Resampling as _Resampling
                from rasterio.transform import Affine as _Affine

                _scale = 2048.0 / max(src_width, src_height)
                _oh = max(1, int(round(src_height * _scale)))
                _ow = max(1, int(round(src_width * _scale)))
                src_band = dataset.read(
                    1,
                    out_shape=(_oh, _ow),
                    resampling=_Resampling.nearest,
                    masked=True,
                )
                src_transform = src_transform * _Affine.scale(
                    src_width / _ow, src_height / _oh
                )
            else:
                src_band = dataset.read(1, masked=True)
            src_nodata = dataset.nodata
            if src_nodata is None:
                # Float science rasters often store voids as NaN without nodata tag.
                src_nodata = -9999.0

            # 投影域钳位：避免 EASE 等全球网格因浮点越界导致东缘经度折返
            try:
                from app.data_io.services.grid_presets import (
                    clamp_projected_bounds_to_crs_domain,
                    normalize_geographic_bounds,
                )

                sw, ss, se, sn = clamp_projected_bounds_to_crs_domain(
                    float(src_bounds.left),
                    float(src_bounds.bottom),
                    float(src_bounds.right),
                    float(src_bounds.top),
                    source_crs,
                )
                src_span_hint = abs(se - sw)
            except Exception:
                sw, ss, se, sn = (
                    float(src_bounds.left),
                    float(src_bounds.bottom),
                    float(src_bounds.right),
                    float(src_bounds.top),
                )
                normalize_geographic_bounds = None  # type: ignore[assignment]
                src_span_hint = abs(se - sw)

            # Sparse global products (e.g. max_pixels smoke runs): crop to the
            # finite-data window so the 1024px preview is not an empty globe.
            # Disable for multi-time full-grid science products (crop_to_data=False).
            if crop_to_data:
                crop = _finite_data_window_bounds(numpy, src_band, src_transform)
                if crop is not None:
                    sw, ss, se, sn = crop
                    src_span_hint = abs(se - sw)

            # 计算目标 CRS 下覆盖完整范围的 transform/尺寸（用于确定缩放比与像素尺寸）
            dst_transform_full, dst_width_full, dst_height_full = (
                warp.calculate_default_transform(
                    source_crs,
                    target_crs,
                    src_width,
                    src_height,
                    sw,
                    ss,
                    se,
                    sn,
                )
            )

            # P2-4：此前用 array_bounds(dst_transform_full) 提取 bounds，该 transform 是
            # calculate_default_transform 产出的整像素对齐 Affine——bounds 已被取整到整像素，
            # 再喂给 from_bounds(rounded_dims) 重建时累积 ~0.013° Mercator round-trip 漂移
            # （被测试容差掩盖）。改用 transform_bounds 直接得到目标 CRS 下的精确地理范围
            # （densify_pts=21 沿边缘采样，不取整到像素），再 from_bounds 用精确范围 + 缩放后
            # 的整像素尺寸重建 Affine——残余误差仅为亚像素，不再累积。
            full_west, full_south, full_east, full_north = warp.transform_bounds(
                source_crs,
                target_crs,
                sw,
                ss,
                se,
                sn,
                densify_pts=21,
            )

            # 限制预览像素尺寸，但必须用 from_bounds 重建 Affine，
            # 使缩略图仍覆盖完整地理范围（旧逻辑直接 min 尺寸却保留原 Affine，
            # 全球 EASE 会变成仅 NW 一角的错误 bounds）。
            # 宽高必须按同一 scale 缩放：若各自 clamp 到 1024 会变成正方形，
            # 贴到 ~2:1 的全球地理框时就会「过度拉伸」。
            from rasterio.transform import from_bounds as _from_bounds

            fw = max(1, int(dst_width_full))
            fh = max(1, int(dst_height_full))
            scale = min(float(width) / fw, float(height) / fh, 1.0)
            dst_width = max(1, int(round(fw * scale)))
            dst_height = max(1, int(round(fh * scale)))
            dst_transform = _from_bounds(
                full_west, full_south, full_east, full_north, dst_width, dst_height
            )

            # 重投影：用普通 ndarray 作 destination（不能用 MaskedArray + 标量 mask）。
            # Fill NaN voids with src_nodata before warp so GDAL treats them as nodata.
            dst_nodata = float(src_nodata) if src_nodata is not None else -9999.0
            src_for_warp = numpy.ma.filled(
                _mask_invalid_raster(numpy, src_band, nodata=src_nodata),
                dst_nodata,
            ).astype("float32")
            dst_band = numpy.full((dst_height, dst_width), dst_nodata, dtype="float32")
            warp.reproject(
                source=src_for_warp,
                destination=dst_band,
                src_transform=src_transform,
                src_crs=source_crs,
                dst_transform=dst_transform,
                dst_crs=target_crs,
                resampling=resampling.bilinear,
                src_nodata=dst_nodata,
                dst_nodata=dst_nodata,
                init_dest_nodata=True,
            )

        masked_array = _mask_invalid_raster(numpy, dst_band, nodata=dst_nodata)
        red, green, blue, alpha = _colorize_masked_band(
            numpy,
            masked_array,
            palette_colors,
            min_value=min_value,
            max_value=max_value,
        )

        with memory_file_cls() as memory_file:
            with memory_file.open(
                driver="PNG",
                width=dst_width,
                height=dst_height,
                count=4,
                dtype="uint8",
            ) as dataset:
                dataset.write(red, 1)
                dataset.write(green, 2)
                dataset.write(blue, 3)
                dataset.write(alpha, 4)
            png_bytes = memory_file.read()

        # 目标 bounds：与重建后的 Affine 一致；地理系再做日界线/塌缩规范化
        west, south, east, north = array_bounds(dst_height, dst_width, dst_transform)
        if west > east:
            west, east = east, west
        if south > north:
            south, north = north, south
        if (
            target_crs in ("EPSG:4326", "EPSG:4490", "EPSG:4258")
            and normalize_geographic_bounds
        ):
            with contextlib.suppress(ValueError):
                west, south, east, north = normalize_geographic_bounds(
                    float(west),
                    float(south),
                    float(east),
                    float(north),
                    source_span_hint=src_span_hint,
                )
        return png_bytes, (float(west), float(south), float(east), float(north))


raster_preview_service = RasterPreviewService()
