"""通用数值哨兵/非有限值清洗（不改变有效物理量的计算逻辑）。

将常见填充值与非有限数转为 NaN，供 ingest / MAT / 反演入口复用。
"""

from __future__ import annotations

from typing import Any

# 遥感/气象产品常见无效哨兵（精确相等匹配）
_COMMON_FILL_EXACT: tuple[float, ...] = (
    -9999.0,
    -9998.0,
    -999.0,
    -32768.0,
    -32767.0,
)

# 坐标/亮温等场景：绝对值过大的哨兵启发式（不碰正常物理量）
_LARGE_ABS_SENTINEL = 9000.0


def mask_common_fill_values(
    value: Any,
    *,
    also_non_finite: bool = True,
    also_large_abs_sentinel: bool = False,
) -> Any:
    """将常见填充值转为 NaN；可选同时清洗非有限与 |x|≥9000 哨兵。

    对有效范围内的物理量（TB、SM、NDVI 等）不做改动。
    """
    import numpy as np

    array = np.asarray(value, dtype=np.float64).copy()
    if also_non_finite:
        array[~np.isfinite(array)] = np.nan
    for fill in _COMMON_FILL_EXACT:
        array[array == fill] = np.nan
    if also_large_abs_sentinel:
        # 用于 lat/lon 等：-9999 已覆盖；再兜底极端哨兵
        array[np.abs(array) >= _LARGE_ABS_SENTINEL] = np.nan
    return array


def mask_value_range(
    value: Any,
    *,
    min_valid: float | None = None,
    max_valid: float | None = None,
) -> Any:
    """将超出物理有效范围的值置为 NaN（范围外本就不会进入有效反演）。"""
    import numpy as np

    array = np.asarray(value, dtype=np.float64).copy()
    if min_valid is not None:
        array[array < min_valid] = np.nan
    if max_valid is not None:
        array[array > max_valid] = np.nan
    return array


def sanitize_science_array(
    value: Any,
    *,
    min_valid: float | None = None,
    max_valid: float | None = None,
    also_large_abs_sentinel: bool = False,
) -> Any:
    """填值 → 非有限 → 物理范围，一步完成。"""
    cleaned = mask_common_fill_values(
        value,
        also_non_finite=True,
        also_large_abs_sentinel=also_large_abs_sentinel,
    )
    if min_valid is not None or max_valid is not None:
        cleaned = mask_value_range(cleaned, min_valid=min_valid, max_valid=max_valid)
    return cleaned
