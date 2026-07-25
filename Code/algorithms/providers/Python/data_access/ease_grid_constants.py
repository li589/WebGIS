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
