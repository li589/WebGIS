"""EASE-Grid 2.0 Global（EPSG:6933）精确常量 — 算法侧与 backend grid_presets 对齐。

禁止使用两位小数近似（如 17367530.45）：会超出投影有效域，
6933→4326 时东缘经度从 +180 折到 -180。
"""

from __future__ import annotations

# NSIDC 官方角点（米）
EASE2_ULX = -17367530.445161516
EASE2_ULY = 7314540.830865865

# 对称全球域 (west, south, east, north)
EASE2_GLOBAL_BOUNDS = (EASE2_ULX, -EASE2_ULY, -EASE2_ULX, EASE2_ULY)

EASE2_RES_9KM = 9008.05521014913
EASE2_SHAPE_9KM = (1624, 3856)  # rows, cols


def ensure_ease2_9km_shape(array: object) -> object:
    """将 9 km EASE-Grid 2.0 场规范为 ``(1624, 3856)``（行, 列）。

    SMAP L3 SPL3SMP_E HDF5 原生即为该形状；历史上 ``ingest.smap`` 默认
    ``transpose=True`` 会把日 .mat 写成 ``(3856, 1624)``。与辅料
    （NDVI/LC 等，已是 ``(1624, 3856)``）共用 C-order ``ravel`` + ``lin_pix``
    时会发生空间错位，反演结果呈水平细条状。

    - 已是 ``(1624, 3856)``：原样返回
    - 仅行列颠倒 ``(3856, 1624)``：转置
    - 其它形状：原样返回（调用方自行处理）
    """
    import numpy as np

    arr = np.asarray(array)
    if arr.ndim != 2:
        return arr
    rows, cols = EASE2_SHAPE_9KM
    if arr.shape == (rows, cols):
        return arr
    if arr.shape == (cols, rows):
        return np.ascontiguousarray(arr.T)
    return arr
