"""空间统计分析模块 — 区域统计、分区统计"""

from __future__ import annotations

import os
import sys

# 支持独立运行: 将上级目录(Python providers 根目录)加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np


# MCD12Q1 IGBP 土地覆盖类型默认名称表 (1-17)
_IGBP_DEFAULT_NAMES: dict[int, str] = {
    1: "Evergreen Needleleaf Forests",
    2: "Evergreen Broadleaf Forests",
    3: "Deciduous Needleleaf Forests",
    4: "Deciduous Broadleaf Forests",
    5: "Mixed Forests",
    6: "Closed Shrublands",
    7: "Open Shrublands",
    8: "Woody Savannas",
    9: "Savannas",
    10: "Grasslands",
    11: "Permanent Wetlands",
    12: "Croplands",
    13: "Urban and Built-Up Lands",
    14: "Cropland/Natural Vegetation Mosaics",
    15: "Permanent Snow and Ice",
    16: "Barren",
    17: "Water Bodies",
}


class ZonalStats:
    """区域统计分析"""

    def _basic_stats(self, values: np.ndarray) -> dict[str, float]:
        """计算一维数组的统计指标 (自动忽略 NaN)"""
        values = np.asarray(values, dtype=np.float64)
        total = float(values.size)
        valid = values[np.isfinite(values)]
        count = valid.size
        if count == 0:
            return {
                "mean": float("nan"),
                "std": float("nan"),
                "min": float("nan"),
                "max": float("nan"),
                "median": float("nan"),
                "count": 0.0,
                "valid_pct": 0.0,
            }
        return {
            "mean": float(np.mean(valid)),
            "std": float(np.std(valid, ddof=0)),
            "min": float(np.min(valid)),
            "max": float(np.max(valid)),
            "median": float(np.median(valid)),
            "count": float(count),
            "valid_pct": count / total * 100.0 if total > 0 else 0.0,
        }

    def compute_stats(
        self,
        data: np.ndarray,
        mask: np.ndarray | None = None,
        zones: np.ndarray | None = None,
    ) -> dict[str, float | dict]:
        """计算统计指标

        - 全局统计: mean, std, min, max, median, count, valid_pct
        - 掩膜统计: 如果提供 mask，只统计 mask=True 的区域
        - 分区统计: 如果提供 zones (整数数组)，按 zone 值分组统计
        - 返回 {global: {...}, zones: {1: {...}, 2: {...}}}
        """
        data = np.asarray(data, dtype=np.float64)
        result: dict[str, float | dict] = {"global": self._basic_stats(data)}

        # 掩膜统计
        if mask is not None:
            mask_arr = np.asarray(mask, dtype=bool)
            if mask_arr.shape != data.shape:
                raise ValueError("mask 形状必须与 data 一致")
            result["mask"] = self._basic_stats(data[mask_arr])
        else:
            result["mask"] = None

        # 分区统计
        zone_stats: dict[int, dict[str, float]] = {}
        if zones is not None:
            zones_arr = np.asarray(zones)
            if zones_arr.shape != data.shape:
                raise ValueError("zones 形状必须与 data 一致")
            # 仅对有限值的 zone 进行分组
            valid_zone_mask = np.isfinite(zones_arr)
            unique_zones = np.unique(zones_arr[valid_zone_mask])
            for zone_value in unique_zones:
                zone_mask = zones_arr == zone_value
                zone_stats[int(zone_value)] = self._basic_stats(data[zone_mask])
        result["zones"] = zone_stats
        return result

    def compute_zonal_mean(
        self,
        data: np.ndarray,
        zones: np.ndarray,
        zone_values: list[int] | None = None,
    ) -> dict[int, float]:
        """计算各分区的均值"""
        data = np.asarray(data, dtype=np.float64)
        zones_arr = np.asarray(zones)
        if zones_arr.shape != data.shape:
            raise ValueError("zones 形状必须与 data 一致")

        # 确定待计算的分区值
        if zone_values is None:
            valid_zone_mask = np.isfinite(zones_arr)
            target_values = [int(v) for v in np.unique(zones_arr[valid_zone_mask])]
        else:
            target_values = list(zone_values)

        result: dict[int, float] = {}
        for zone_value in target_values:
            zone_mask = zones_arr == zone_value
            zone_data = data[zone_mask]
            valid = zone_data[np.isfinite(zone_data)]
            result[int(zone_value)] = float(np.mean(valid)) if valid.size > 0 else float("nan")
        return result

    def compute_landcover_stats(
        self,
        data: np.ndarray,
        landcover: np.ndarray,
        igbp_names: dict[int, str] | None = None,
    ) -> dict[int, dict[str, float]]:
        """按 IGBP 土地覆盖类型计算统计

        - 输入: 数据数组 + MCD12Q1 土地覆盖数组 (1-17)
        - 输出: {igbp_code: {name, mean, std, count, area_pct}}
        """
        data = np.asarray(data, dtype=np.float64)
        lc = np.asarray(landcover)
        if lc.shape != data.shape:
            raise ValueError("landcover 形状必须与 data 一致")

        # 合并 IGBP 名称表
        names = dict(_IGBP_DEFAULT_NAMES)
        if igbp_names is not None:
            names.update(igbp_names)

        # 仅统计有限值的土地覆盖像元
        valid_lc_mask = np.isfinite(lc)
        unique_lc = np.unique(lc[valid_lc_mask])
        total_valid_pixels = float(np.sum(valid_lc_mask))

        result: dict[int, dict[str, float]] = {}
        for lc_value in unique_lc:
            lc_int = int(lc_value)
            lc_mask = lc == lc_value
            lc_pixel_count = float(np.sum(lc_mask))
            area_pct = lc_pixel_count / total_valid_pixels * 100.0 if total_valid_pixels > 0 else 0.0
            zone_data = data[lc_mask]
            valid = zone_data[np.isfinite(zone_data)]
            count = float(valid.size)
            result[lc_int] = {
                "name": names.get(lc_int, f"Type_{lc_int}"),
                "mean": float(np.mean(valid)) if count > 0 else float("nan"),
                "std": float(np.std(valid, ddof=0)) if count > 0 else float("nan"),
                "count": count,
                "area_pct": area_pct,
            }
        return result
