from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

# ─── Savitzky-Golay 滤波默认参数（无量纲） ───────────────────────────────────
_SG_DEFAULT_POLYORDER = 6
_SG_DEFAULT_WINDOW_LENGTH = 9
_SG_DEFAULT_GAP_THRESHOLD_DAYS = 30
_SG_DEFAULT_STEP_DAYS = 8
_SG_MIN_VALID_POINTS = 4  # SG 滤波最少有效观测点数

# ─── NDVI 有效范围（无量纲） ──────────────────────────────────────────────────
_NDVI_VALID_MIN = 0.0
_NDVI_VALID_MAX = 1.0

# ─── 质量度量参数 ─────────────────────────────────────────────────────────────
_NDVI_RANGE_PERCENTILE_LOW = 5.0
_NDVI_RANGE_PERCENTILE_HIGH = 95.0
_NDVI_MIN_VALID_OBS = 3  # 质量度量最少有效观测数


def build_datetime_sequence(start: datetime, end: datetime, step_days: int) -> list[datetime]:
    """构建等间距日期序列。输入 start/end 为 datetime，step_days 单位天，返回 datetime 列表。"""
    if step_days <= 0:
        raise ValueError("step_days must be positive")
    dates: list[datetime] = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=step_days)
    return dates


def to_day_numbers(dates: Iterable[datetime]) -> Any:
    """将 datetime 序列转换为 ordinal 日数（浮点数组）。"""
    import numpy as np

    return np.array([value.toordinal() for value in dates], dtype=np.float64)


def _linear_interp_with_nan(
    source_x: Any,
    source_y: Any,
    target_x: Any,
) -> Any:
    """线性插值，超出源范围的点设为 NaN。"""
    import numpy as np

    if source_x.size == 0:
        return np.full(target_x.shape, np.nan, dtype=np.float64)
    left_mask = target_x < source_x.min()
    right_mask = target_x > source_x.max()
    values = np.interp(target_x, source_x, source_y)
    values[left_mask | right_mask] = np.nan
    return values


def _fill_nan_edges_1d(arr: Any) -> tuple[Any, Any]:
    """用最近有效值填充首尾 NaN 段（1D）。

    量纲: arr 无量纲（NDVI 或插值中间量）。返回 (filled, nan_mask)。
    假设 NaN 仅出现在首尾连续段（由 _linear_interp_with_nan 保证）。
    全 NaN 输入返回 (arr, nan_mask) 不修改（由调用方提前规避）。
    """
    import numpy as np

    nan_mask = np.isnan(arr)
    if not nan_mask.any():
        return arr, nan_mask
    valid_indices = np.where(~nan_mask)[0]
    if valid_indices.size == 0:
        return arr, nan_mask  # 全 NaN，无法填充
    filled = arr.copy()
    first_valid = valid_indices[0]
    last_valid = valid_indices[-1]
    if first_valid > 0:
        filled[:first_valid] = arr[first_valid]
    if last_valid < arr.size - 1:
        filled[last_valid + 1 :] = arr[last_valid]
    return filled, nan_mask


def _fill_nan_edges_2d(arr: Any) -> tuple[Any, Any]:
    """沿 axis=1 用最近有效值填充首尾 NaN 段（2D 向量化）。

    量纲: arr shape (n_rows, n_cols)，值无量纲。返回 (filled, nan_mask)。
    假设每行 NaN 仅出现在首尾连续段（由 _linear_interp_with_nan 保证）。
    使用 maximum.accumulate / minimum.accumulate 技巧实现向量化前向+后向填充。
    """
    import numpy as np

    nan_mask = np.isnan(arr)
    if not nan_mask.any():
        return arr, nan_mask
    not_nan = ~nan_mask
    n_cols = arr.shape[1]
    cols = np.arange(n_cols)

    # 前向填充：每个位置取其左侧（含自身）最近的有效值索引
    fwd_idx = np.where(not_nan, cols, -1)
    fwd_idx = np.maximum.accumulate(fwd_idx, axis=1)  # -1 表示此前无有效值（首部 NaN）
    fwd_filled = np.take_along_axis(arr, np.maximum(fwd_idx, 0), axis=1)
    # 首部 NaN 行（fwd_idx=-1）取到 arr[row, 0] 仍为 NaN，需后向填充修复

    nan_after_fwd = np.isnan(fwd_filled)
    if not nan_after_fwd.any():
        return fwd_filled, nan_mask
    # 后向填充：从右向左传播最近有效值索引，修复首部 NaN
    bwd_idx = np.where(~nan_after_fwd, cols, n_cols)
    bwd_idx = np.minimum.accumulate(bwd_idx[:, ::-1], axis=1)[:, ::-1]
    filled = np.take_along_axis(fwd_filled, np.minimum(bwd_idx, n_cols - 1), axis=1)
    return filled, nan_mask


def _apply_range_masking(
    daily_values: Any,
    observation_days: Any,
    valid_mask: Any,
    output_days: Any,
) -> Any:
    """将超出有效观测范围的 output_days 位置设为 NaN。

    量纲: daily_values/output_days 为 ordinal 日数，observation_days 为 ordinal 日数。
    valid_mask 为布尔 1D 数组，标识有效观测位置。
    """
    import numpy as np

    valid_obs_days = observation_days[valid_mask]
    if valid_obs_days.size == 0:
        return daily_values
    first_obs_day = valid_obs_days.min()
    last_obs_day = valid_obs_days.max()
    daily_values[(output_days < first_obs_day) | (output_days > last_obs_day)] = np.nan
    return daily_values


def vi_sg_interpolate(
    data: Any,
    observation_days: Any,
    sg_days: Any,
    output_days: Any,
    gap_threshold_days: int = _SG_DEFAULT_GAP_THRESHOLD_DAYS,
    sg_polyorder: int = _SG_DEFAULT_POLYORDER,
    sg_window_length: int = _SG_DEFAULT_WINDOW_LENGTH,
) -> Any:
    """Savitzky-Golay 滤波插值，将观测 NDVI 序列重建为连续日序列。

    量纲: data 无量纲（NDVI 0-1），observation_days/sg_days/output_days 为 ordinal 日数。
    有效观测点少于 _SG_MIN_VALID_POINTS 时返回全 NaN。观测间隔超过 gap_threshold_days 的区段设为 NaN。
    超出有效观测范围的 output_days 位置设为 NaN（范围掩膜）。
    """
    import numpy as np
    from scipy.signal import savgol_filter

    valid_mask = ~np.isnan(data)
    valid_count = int(valid_mask.sum())
    if valid_count <= _SG_MIN_VALID_POINTS:
        return np.full(output_days.shape, np.nan, dtype=np.float64)

    # savgol_filter 要求 window_length <= len(data)；sg_days 过短时降级为线性插值
    if sg_days.size < sg_window_length:
        if valid_count < 2:
            return np.full(output_days.shape, np.nan, dtype=np.float64)
        daily_values = _linear_interp_with_nan(
            observation_days[valid_mask],
            data[valid_mask],
            output_days,
        )
        daily_values = _apply_gap_masking(
            daily_values, observation_days, valid_mask, output_days, gap_threshold_days
        )
        return _apply_range_masking(daily_values, observation_days, valid_mask, output_days)

    interpolated_8day = _linear_interp_with_nan(
        observation_days[valid_mask],
        data[valid_mask],
        sg_days,
    )
    # 填充首尾 NaN 防止 savgol_filter 崩溃（savgol_filter 无法处理 NaN 输入）
    interpolated_filled, _ = _fill_nan_edges_1d(interpolated_8day)
    sg_filtered = savgol_filter(interpolated_filled, sg_window_length, sg_polyorder, mode="interp")
    daily_values = _linear_interp_with_nan(sg_days, sg_filtered, output_days)

    daily_values = _apply_gap_masking(
        daily_values,
        observation_days,
        valid_mask,
        output_days,
        gap_threshold_days,
    )
    # 显式范围掩膜：超出有效观测范围的 output_days 设为 NaN（替代原隐式 NaN 传播）
    return _apply_range_masking(daily_values, observation_days, valid_mask, output_days)


def _apply_gap_masking(
    daily_values: Any,
    observation_days: Any,
    valid_mask: Any,
    output_days: Any,
    gap_threshold_days: int,
) -> Any:
    """对插值后的日序列应用间隔掩膜：观测间隔超过阈值的区段设为 NaN。

    量纲: daily_values/output_days 为 ordinal 日数，observation_days 为 ordinal 日数。
    valid_mask 为布尔 1D 数组，标识有效观测位置。
    """
    import numpy as np

    valid_dates = observation_days[valid_mask]
    if valid_dates.size >= 2:
        gaps = np.diff(valid_dates)
        gap_indices = np.where(gaps > gap_threshold_days)[0]
        for gap_index in gap_indices:
            left_day = valid_dates[gap_index]
            right_day = valid_dates[gap_index + 1]
            daily_values[(output_days > left_day) & (output_days < right_day)] = np.nan
    return daily_values


def process_ndvi_stack_to_daily(
    ndvi_stack: Any,
    observation_dates: list[datetime],
    start_time: datetime,
    end_time: datetime,
    sg_step_days: int = _SG_DEFAULT_STEP_DAYS,
    daily_step_days: int = 1,
    gap_threshold_days: int = _SG_DEFAULT_GAP_THRESHOLD_DAYS,
    sg_polyorder: int = _SG_DEFAULT_POLYORDER,
    sg_window_length: int = _SG_DEFAULT_WINDOW_LENGTH,
) -> tuple[Any, list[datetime]]:
    """将多时相 NDVI 立方体重建为日序列。

    量纲: ndvi_stack shape (rows, cols, time)，值无量纲 (NDVI 0-1)。
    返回 (daily_stack, daily_dates)，daily_stack shape (rows, cols, days)，值无量纲 (0-1)。
    超出有效范围的值设为 NaN。

    性能优化：对有效观测充足且 sg_days 长度足够的像素，批量调用 savgol_filter（沿 axis=1）
    以利用底层 C 向量化；对降级路径仍逐像素调用 vi_sg_interpolate。
    """
    import numpy as np
    from scipy.signal import savgol_filter

    if ndvi_stack.ndim != 3:
        raise ValueError("NDVI stack must be a 3D array: rows x cols x time")
    if ndvi_stack.shape[2] != len(observation_dates):
        raise ValueError("Observation date count does not match NDVI stack time dimension")

    sg_dates = build_datetime_sequence(start_time, end_time, sg_step_days)
    daily_dates = build_datetime_sequence(start_time, end_time, daily_step_days)
    observation_days = to_day_numbers(observation_dates)
    sg_days = to_day_numbers(sg_dates)
    output_days = to_day_numbers(daily_dates)

    rows, cols, _ = ndvi_stack.shape
    flattened = ndvi_stack.reshape(rows * cols, -1)
    n_pixels = flattened.shape[0]
    daily_flattened = np.full((n_pixels, output_days.size), np.nan, dtype=np.float64)

    # 像素级有效观测数 (shape: (n_pixels,))
    valid_counts = (~np.isnan(flattened)).sum(axis=1)
    # savgol_filter 批量路径要求 sg_days 长度 >= window_length，且像素有效点 > _SG_MIN_VALID_POINTS
    sg_capable_mask = (valid_counts > _SG_MIN_VALID_POINTS) & (sg_days.size >= sg_window_length)

    # ── 批量路径：对 sg_capable 像素沿时间轴批量 savgol_filter ─────────────────
    if np.any(sg_capable_mask):
        capable_indices = np.where(sg_capable_mask)[0]
        # 步骤 A：每像素线性插值到 sg_days（不同像素 valid_mask 不同，需逐像素调用）
        interpolated_to_sg = np.empty(
            (capable_indices.size, sg_days.size), dtype=np.float64
        )
        for row_idx, pixel_idx in enumerate(capable_indices):
            pixel_data = flattened[pixel_idx]
            pixel_valid = ~np.isnan(pixel_data)
            interpolated_to_sg[row_idx] = _linear_interp_with_nan(
                observation_days[pixel_valid],
                pixel_data[pixel_valid],
                sg_days,
            )

        # 步骤 A.1：向量化填充首尾 NaN，防止批量 savgol_filter 崩溃
        interpolated_filled, _ = _fill_nan_edges_2d(interpolated_to_sg)

        # 步骤 B：沿 axis=1 批量 SG 滤波（核心向量化收益）
        filtered = savgol_filter(
            interpolated_filled, sg_window_length, sg_polyorder, axis=1, mode="interp"
        )

        # 步骤 C：每像素线性插值到 output_days + 间隔掩膜 + 范围掩膜
        for row_idx, pixel_idx in enumerate(capable_indices):
            pixel_data = flattened[pixel_idx]
            pixel_valid = ~np.isnan(pixel_data)
            daily_values = _linear_interp_with_nan(sg_days, filtered[row_idx], output_days)
            daily_values = _apply_gap_masking(
                daily_values,
                observation_days,
                pixel_valid,
                output_days,
                gap_threshold_days,
            )
            daily_values = _apply_range_masking(
                daily_values, observation_days, pixel_valid, output_days
            )
            daily_flattened[pixel_idx] = daily_values

    # ── 降级路径：对有效点不足或 sg_days 过短的像素逐像素处理 ───────────────────
    for pixel_idx in np.where(~sg_capable_mask)[0]:
        daily_flattened[pixel_idx] = vi_sg_interpolate(
            flattened[pixel_idx],
            observation_days,
            sg_days,
            output_days,
            gap_threshold_days=gap_threshold_days,
            sg_polyorder=sg_polyorder,
            sg_window_length=sg_window_length,
        )

    daily_stack = daily_flattened.reshape(rows, cols, output_days.size)
    daily_stack[(daily_stack < _NDVI_VALID_MIN) | (daily_stack > _NDVI_VALID_MAX)] = np.nan
    return daily_stack, daily_dates


def _safe_nanmean(values: Any, axis: int) -> Any:
    import warnings

    import numpy as np

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmean(values, axis=axis)


def _safe_nanmax(values: Any, axis: int) -> Any:
    import warnings

    import numpy as np

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmax(values, axis=axis)


def _safe_nanmin(values: Any, axis: int) -> Any:
    import warnings

    import numpy as np

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmin(values, axis=axis)


def _safe_nanpercentile(values: Any, q: float, axis: int) -> Any:
    import warnings

    import numpy as np

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanpercentile(values, q, axis=axis)


def _build_dtw_kernel():
    import numpy as np
    from numba import njit

    @njit(cache=True)
    def _dtw_distance_1d(left: Any, right: Any) -> float:
        n_left = left.shape[0]
        n_right = right.shape[0]
        dp = np.full((n_left + 1, n_right + 1), np.inf, dtype=np.float64)
        dp[0, 0] = 0.0
        for i in range(1, n_left + 1):
            left_value = left[i - 1]
            for j in range(1, n_right + 1):
                cost = abs(left_value - right[j - 1])
                dp[i, j] = cost + min(dp[i - 1, j], dp[i, j - 1], dp[i - 1, j - 1])
        return dp[n_left, n_right]

    @njit(cache=True)
    def _dtw_map(clim_flat: Any, dyn_flat: Any) -> Any:
        pixel_count = dyn_flat.shape[0]
        result = np.full(pixel_count, np.nan, dtype=np.float64)
        for pixel_index in range(pixel_count):
            clim_count = 0
            dyn_count = 0
            for time_index in range(clim_flat.shape[1]):
                if np.isfinite(clim_flat[pixel_index, time_index]):
                    clim_count += 1
                if np.isfinite(dyn_flat[pixel_index, time_index]):
                    dyn_count += 1
            if clim_count < 3 or dyn_count < 3:
                continue
            clim_series = np.empty(clim_count, dtype=np.float64)
            dyn_series = np.empty(dyn_count, dtype=np.float64)
            clim_fill = 0
            dyn_fill = 0
            for time_index in range(clim_flat.shape[1]):
                clim_value = clim_flat[pixel_index, time_index]
                if np.isfinite(clim_value):
                    clim_series[clim_fill] = clim_value
                    clim_fill += 1
                dyn_value = dyn_flat[pixel_index, time_index]
                if np.isfinite(dyn_value):
                    dyn_series[dyn_fill] = dyn_value
                    dyn_fill += 1
            result[pixel_index] = _dtw_distance_1d(clim_series, dyn_series)
        return result

    return _dtw_map


_COMPUTE_DTW_MAP = _build_dtw_kernel()


def build_ndvi_quality_metrics(
    dynamic_stack: Any,
    climatology_stack: Any | None = None,
) -> dict[str, Any]:
    """计算 NDVI 质量度量指标。

    量纲: dynamic_stack shape (rows, cols, time)，值无量纲 (NDVI 0-1)。
    返回字典含: NDVI_v_mean/max/min（均值/最大/最小）、NDVI_v_range（P95-P5 极差）、
    NDVI_v_vali（有效观测数，少于 _NDVI_MIN_VALID_OBS 设为 NaN）、
    NDVI_v_diff_mean/std（与气候态差异均值/标准差）、NDVI_v_od（DTW 距离）。
    """
    import numpy as np

    dynamic_stack = np.asarray(dynamic_stack, dtype=np.float64)
    if dynamic_stack.ndim != 3:
        raise ValueError("dynamic_stack must be a 3D array: rows x cols x time")

    pixel_valid_count = np.sum(np.isfinite(dynamic_stack), axis=2).astype(np.float64)
    summary: dict[str, Any] = {
        "NDVI_v_mean": _safe_nanmean(dynamic_stack, axis=2),
        "NDVI_v_max": _safe_nanmax(dynamic_stack, axis=2),
        "NDVI_v_min": _safe_nanmin(dynamic_stack, axis=2),
        "NDVI_v_range": _safe_nanpercentile(dynamic_stack, _NDVI_RANGE_PERCENTILE_HIGH, axis=2)
        - _safe_nanpercentile(dynamic_stack, _NDVI_RANGE_PERCENTILE_LOW, axis=2),
        "NDVI_v_vali": np.where(pixel_valid_count >= _NDVI_MIN_VALID_OBS, pixel_valid_count, np.nan),
    }

    if climatology_stack is None:
        nan_like = np.full(dynamic_stack.shape[:2], np.nan, dtype=np.float64)
        summary["NDVI_v_diff_mean"] = nan_like.copy()
        summary["NDVI_v_diff_std"] = nan_like.copy()
        summary["NDVI_v_od"] = nan_like.copy()
        return summary

    climatology_stack = np.asarray(climatology_stack, dtype=np.float64)
    if climatology_stack.shape != dynamic_stack.shape:
        raise ValueError("climatology_stack must match dynamic_stack shape")

    diff_stack = dynamic_stack - climatology_stack
    summary["NDVI_v_diff_mean"] = _safe_nanmean(diff_stack, axis=2)
    summary["NDVI_v_diff_std"] = np.sqrt(_safe_nanmean(diff_stack**2, axis=2))
    summary["NDVI_v_od"] = _COMPUTE_DTW_MAP(
        climatology_stack.reshape(-1, climatology_stack.shape[2]),
        dynamic_stack.reshape(-1, dynamic_stack.shape[2]),
    ).reshape(dynamic_stack.shape[:2])
    return summary


def merge_ndvi_quality_metrics(metric_list: list[dict[str, Any]]) -> dict[str, Any]:
    """合并多个 NDVI 质量度量字典（如多年度指标合并）。

    量纲: metric_list 中各指标值无量纲 (NDVI 0-1) 或有效观测数。
    返回合并后的字典，各指标按时间维度聚合（mean/max/min/sum）。
    """
    import numpy as np

    if not metric_list:
        raise ValueError("metric_list must not be empty")

    mean_stack = np.stack([np.asarray(item["NDVI_v_mean"], dtype=np.float64) for item in metric_list], axis=2)
    max_stack = np.stack([np.asarray(item["NDVI_v_max"], dtype=np.float64) for item in metric_list], axis=2)
    min_stack = np.stack([np.asarray(item["NDVI_v_min"], dtype=np.float64) for item in metric_list], axis=2)
    range_stack = np.stack([np.asarray(item["NDVI_v_range"], dtype=np.float64) for item in metric_list], axis=2)
    diff_mean_stack = np.stack([np.asarray(item["NDVI_v_diff_mean"], dtype=np.float64) for item in metric_list], axis=2)
    diff_std_stack = np.stack([np.asarray(item["NDVI_v_diff_std"], dtype=np.float64) for item in metric_list], axis=2)
    od_stack = np.stack([np.asarray(item["NDVI_v_od"], dtype=np.float64) for item in metric_list], axis=2)
    vali_stack = np.stack([np.asarray(item["NDVI_v_vali"], dtype=np.float64) for item in metric_list], axis=2)

    merged = {
        "NDVI_v_mean": _safe_nanmean(mean_stack, axis=2),
        "NDVI_v_max": _safe_nanmax(max_stack, axis=2),
        "NDVI_v_min": _safe_nanmin(min_stack, axis=2),
        "NDVI_v_range": _safe_nanmean(range_stack, axis=2),
        "NDVI_v_od": np.sqrt(_safe_nanmean(od_stack**2, axis=2) * od_stack.shape[2]),
        "NDVI_v_diff_mean": _safe_nanmean(diff_mean_stack, axis=2),
        "NDVI_v_diff_std": np.sqrt(_safe_nanmean(diff_std_stack**2, axis=2)),
        "NDVI_v_vali": np.nansum(vali_stack, axis=2),
    }
    merged["NDVI_v_od"][merged["NDVI_v_od"] == 0.0] = np.nan
    return merged
