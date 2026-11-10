"""按需补帧的单日帧要能进时间轴，且逐日产品不许被折成长合成块。

两个用户可见的症状，根因是同一处：

1. **时间轴选不到单日**（2026-11-09 用户反馈）
   某层 ``meta.time_list`` 只有 ``['20250701_20250731', '20251201_20260201']``
   两个长合成块，而目录里躺着 ``preview_20251215.png`` 等按需补出来的单日帧。
   ``nas_ondemand`` 按设计不写 ``meta.time_list``（怕改了默认落点），于是前端
   时间轴只有两个块可选，用户拖到 12-15 只能吸附到 63 天季均块。

2. **输入单日却变成「这么多日」**
   逐日产品（``native_step=1d``）点某一天、那天没有单日帧时，
   ``_assert_time_available`` 的「块区间容错」会**静默**返回覆盖那天的长合成块。
   统计据此回答「12 月 18 日 0.16」，实际是 12-01~02-01 的季均 —— 把「没有这天」
   说成「有数」。现在改成返回 None，让上层去 NAS 现补；补不到就如实说没有。

而 8 天 / 整月产品必须保持原样：一个观测本来就覆盖一整段，折回所在块才对。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.overlay_registry import (
    OverlayNotFoundError,
    OverlaySpec,
    _is_daily_step,
)


def _spec(
    tmp_path: Path,
    *,
    time_list: list[str],
    native_step: str = "1d",
    previews: tuple[str, ...] = (),
    default_time: str | None = None,
) -> OverlaySpec:
    """造一个最小可用的时序图层目录。"""
    for day in previews:
        (tmp_path / f"preview_{day}.png").write_bytes(b"x")
    return OverlaySpec(
        layer_id="imported-testondemand",
        overlay_dir=tmp_path,
        bounds_filename="bounds.json",
        category="time-series",
        time_list=list(time_list),
        default_time=default_time or (time_list[0] if time_list else None),
        native_step=native_step,
    )


class TestDailyStepHelper:
    @pytest.mark.parametrize("step", ["1d", "1D", "day", "daily", "1day"])
    def test_daily_forms(self, step: str):
        assert _is_daily_step(step) is True

    @pytest.mark.parametrize("step", ["8d", "1M", "month", "", None, "16d"])
    def test_non_daily_forms(self, step):
        assert _is_daily_step(step) is False


class TestMetaDictExposesOndemandDays:
    """时间轴拿到的清单必须含盘上真实存在的单日帧。"""

    def test_time_list_includes_ondemand_days(self, tmp_path: Path):
        spec = _spec(tmp_path, time_list=["20251201_20260201"], previews=("20251215", "20251216"))
        spec.ondemand_times = ["20251215", "20251216"]

        meta = spec.meta_dict()

        assert "20251215" in meta["time_list"]
        assert "20251216" in meta["time_list"]
        assert "20251201_20260201" in meta["time_list"]
        assert meta["ondemand_times"] == ["20251215", "20251216"]

    def test_default_time_untouched(self, tmp_path: Path):
        """一进页面的默认落点不许被单日帧顶掉（这是既有承诺）。"""
        spec = _spec(tmp_path, time_list=["20250701_20250731"], previews=("20251215",))
        spec.ondemand_times = ["20251215"]

        meta = spec.meta_dict()

        assert meta["default_time"] == "20250701_20250731"
        assert meta["current_time"] == "20250701_20250731"

    def test_spec_time_list_not_mutated(self, tmp_path: Path):
        """内部白名单不因对外暴露而改动——校验行为保持原样。"""
        spec = _spec(tmp_path, time_list=["20251201_20260201"], previews=("20251215",))
        spec.ondemand_times = ["20251215"]

        spec.meta_dict()

        assert spec.time_list == ["20251201_20260201"]

    def test_no_duplicates_when_day_already_listed(self, tmp_path: Path):
        spec = _spec(tmp_path, time_list=["20251215", "20251201_20260201"])
        spec.ondemand_times = ["20251215"]

        meta = spec.meta_dict()

        assert meta["time_list"].count("20251215") == 1


class TestDailyProductNeverFoldsIntoBlock:
    """逐日产品点某天：有帧给单日，没帧返回 None（交给上层补帧）。"""

    def test_day_with_frame_resolves_to_that_day(self, tmp_path: Path):
        spec = _spec(
            tmp_path,
            time_list=["20251201_20260201"],
            previews=("20251215",),
        )

        assert spec.resolve_time_key("2025-12-15", prefer_finest=True) == "20251215"

    def test_day_without_frame_does_not_fall_back(self, tmp_path: Path):
        spec = _spec(tmp_path, time_list=["20251201_20260201"])

        assert spec.resolve_time_key("2025-12-18", prefer_finest=True) is None

    def test_explicit_error_is_not_found(self, tmp_path: Path):
        spec = _spec(tmp_path, time_list=["20251201_20260201"])

        with pytest.raises(OverlayNotFoundError):
            spec._assert_time_available("20251218", prefer_finest=True)

    def test_ask_for_month_block_still_works(self, tmp_path: Path):
        """用户/模型明确要那一块时，仍然照给（不能把整月查询也拦掉）。"""
        spec = _spec(tmp_path, time_list=["20251201_20260201"])

        assert spec.resolve_time_key("20251201_20260201") == "20251201_20260201"


class TestBlockProductStillFolds:
    """8 天 / 整月产品：一个观测覆盖一整段，折回所在块是对的。"""

    def test_eight_day_product_folds(self, tmp_path: Path):
        spec = _spec(
            tmp_path,
            time_list=["20251211_20251218", "20251219_20251226"],
            native_step="8d",
        )

        assert spec.resolve_time_key("20251220") == "20251219_20251226"

    def test_month_product_folds(self, tmp_path: Path):
        spec = _spec(tmp_path, time_list=["20251201_20251231"], native_step="1M")

        assert spec.resolve_time_key("20251215") == "20251201_20251231"


class TestRealLayerScan:
    """真实图层目录的扫描结果（没有该层数据时跳过，不把缺数据当成失败）。"""

    LAYER = "imported-38993117b963"

    def _spec_or_skip(self):
        from app.services.overlay_registry import get_overlay_spec

        try:
            spec = get_overlay_spec(self.LAYER)
        except Exception:  # pragma: no cover - 无该层数据的环境
            pytest.skip(f"{self.LAYER} 不在本机数据目录")
        if spec is None or not getattr(spec, "ondemand_times", None):
            pytest.skip(f"{self.LAYER} 目录里没有按需单日帧")
        return spec

    def test_scan_collects_only_eight_digit_days(self):
        spec = self._spec_or_skip()
        for day in spec.ondemand_times:
            assert len(day) == 8 and day.isdigit(), day
        assert set(spec.ondemand_times).isdisjoint(set(spec.time_list))

    def test_scanned_day_is_servable(self):
        spec = self._spec_or_skip()
        day = spec.ondemand_times[-1]
        assert spec.resolve_time_key(day) == day
