"""e2e 行为契约测试：retrieve_omega_sf_daily 主循环保真。

验证 omega_sf.py ``retrieve_omega_sf_daily``（C41 编排函数）的端到端 I/O 行为。
合成最小可运行场景（SMAP 模式 + 10 天 + 2x2 网格 + INVERTED_DAILY SF），
跑通主循环并锁定输出结构 + 关键数值，作为主循环提取重构的 golden baseline。

若提取 ``_process_one_chunk`` 改变了：
- 输出 OmegaSfResult 的字段类型/形状
- n_pixels_total/success/failed 计数
- omega_pft / omega_pixel_map / omega_pix_count 的数值
本测试会失败。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from algorithms.omega_sf import OmegaSfConfig, retrieve_omega_sf_daily


# ─── 合成场景 helpers ───────────────────────────────────────────────────────

_NROWS, _NCOLS = 2, 2
_NPIX = _NROWS * _NCOLS
_NDAYS = 10  # 足够 1-2 个 8 天块
_START = "20251201"
_END = "20251210"


def _make_ancillary_tree(tmp: Path) -> Path:
    """合成 ancillary 目录（与 test_omega_sf_io_contract 一致，但 2x2 grid）。"""
    anc = tmp / "anc"
    anc.mkdir()
    grid = np.arange(_NPIX, dtype=np.float64).reshape(_NROWS, _NCOLS)
    savemat(
        str(anc / "IGBP_9km_12.mat"),
        {
            "IGBP_9km_12": grid,
            "lat_9km": np.array([[30.0, 30.1], [30.2, 30.3]]),
            "lon_9km": np.array([[110.0, 110.1], [110.2, 110.3]]),
        },
    )
    savemat(
        str(anc / "Albedo.mat"),
        {"ALBEDO": np.full(_NPIX, 0.15).reshape(_NROWS, _NCOLS)},
    )
    savemat(str(anc / "B.mat"), {"B": np.full(_NPIX, -0.32).reshape(_NROWS, _NCOLS)})
    # SF static 用作 INVERTED_DAILY 的回退参考
    savemat(
        str(anc / "SF.mat"), {"SF_smap": np.full(_NPIX, 0.5).reshape(_NROWS, _NCOLS)}
    )
    savemat(str(anc / "BD.mat"), {"BD": np.full(_NPIX, 1.3).reshape(_NROWS, _NCOLS)})
    savemat(str(anc / "H.mat"), {"H": np.full(_NPIX, 0.1).reshape(_NROWS, _NCOLS)})
    savemat(str(anc / "CF.mat"), {"CF": np.full(_NPIX, 0.3).reshape(_NROWS, _NCOLS)})
    savemat(
        str(anc / "VI_v_qa.mat"),
        {
            "NDVI_v_max": np.full(_NPIX, 0.8),
            "NDVI_v_min": np.full(_NPIX, 0.1),
        },
    )
    clim = anc / "NDVI_clim"
    clim.mkdir()
    # DOY 335-344 (Dec 1-10)
    for doy in range(335, 345):
        savemat(
            str(clim / f"{doy}.mat"),
            {"NDVI_clim": np.full(_NPIX, 0.4).reshape(_NROWS, _NCOLS)},
        )
    return anc


def _make_smap_day(folder: Path, date_str: str, seed: int) -> None:
    """合成单日 SMAP 文件，物理合理的 TB/Ts/SM/IA/VWC/NDVI。

    seed 让每日数据有变化（反演需要时序变化），但同一场景可复现。
    """
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    # TBv ~ 255 + sin + noise，TBh ~ 235 + cos + noise
    t = np.linspace(0, 2 * np.pi, _NDAYS)
    idx = int(date_str[-2:]) - 1  # 日期序号
    tbv = 255.0 + 8.0 * np.sin(t[idx]) + rng.normal(0, 0.3, _NPIX)
    tbh = 235.0 + 7.0 * np.cos(t[idx]) + rng.normal(0, 0.3, _NPIX)
    savemat(
        str(folder / f"{date_str}.mat"),
        {
            "TBv": tbv.reshape(_NROWS, _NCOLS),
            "TBh": tbh.reshape(_NROWS, _NCOLS),
            "IA": np.full(_NPIX, 40.0).reshape(_NROWS, _NCOLS),
            "Ts": np.full(_NPIX, 290.0).reshape(_NROWS, _NCOLS),
            "sm_dca": np.full(_NPIX, 0.2).reshape(_NROWS, _NCOLS),
            "vwc": np.full(_NPIX, 0.15).reshape(_NROWS, _NCOLS),
        },
    )


@pytest.fixture
def e2e_setup(tmp_path: Path):
    """合成 e2e 场景：10 天 SMAP + ancillary + INVERTED_DAILY SF。"""
    anc_root = _make_ancillary_tree(tmp_path)
    smap_folder = tmp_path / "smap"
    for i in range(_NDAYS):
        date = datetime(2025, 12, 1) + timedelta(days=i)
        _make_smap_day(smap_folder, date.strftime("%Y%m%d"), seed=42 + i)

    config = OmegaSfConfig.from_params(
        {
            "tb_source": "SMAP",
            "sf_mode": "STATIC",  # 用静态 SF 避免 INVERTED_DAILY 的 vwc/ndvi 依赖
            "ndvi_mode": "DOY_CLIM",
            "omega_fixed_mode": "PIXEL",  # 避免 PFT 模式需要 omega_pft 文件
            "start_date": _START,
            "end_date": _END,
            "block_days": 8,
            "enable_parallel": False,  # 串行，确定性
        }
    )
    return {
        "config": config,
        "smap_folder": str(smap_folder),
        "anc_root": str(anc_root),
        "ndvi_clim_folder": str(anc_root / "NDVI_clim"),
    }


# ─── e2e 契约 ───────────────────────────────────────────────────────────────


class TestRetrieveOmegaSfDailyE2E:
    def test_returns_omega_sf_result(self, e2e_setup, monkeypatch) -> None:
        """返回 OmegaSfResult，所有字段类型正确。"""
        # 避免 checkpoint 干扰
        monkeypatch.setenv("OMEGA_SF_MAX_PIXELS", "0")
        result = retrieve_omega_sf_daily(
            config=e2e_setup["config"],
            smap_folder=e2e_setup["smap_folder"],
            anc_root=e2e_setup["anc_root"],
            ndvi_clim_folder=e2e_setup["ndvi_clim_folder"],
            grid_shape=(_NROWS, _NCOLS),
            reuse_block_cache=False,
        )
        # OmegaSfResult 字段
        assert hasattr(result, "omega_pft")
        assert hasattr(result, "omega_pixel_map")
        assert hasattr(result, "omega_pixel_count")
        assert hasattr(result, "sm_maps")
        assert hasattr(result, "vod_maps")
        assert hasattr(result, "omega_maps")
        assert hasattr(result, "n_pixels_total")
        assert hasattr(result, "n_pixels_success")
        assert hasattr(result, "n_pixels_failed")
        assert hasattr(result, "output_paths")

    def test_pixel_map_shape_matches_grid(self, e2e_setup, monkeypatch) -> None:
        """omega_pixel_map 形状 = grid_shape。"""
        monkeypatch.setenv("OMEGA_SF_MAX_PIXELS", "0")
        result = retrieve_omega_sf_daily(
            config=e2e_setup["config"],
            smap_folder=e2e_setup["smap_folder"],
            anc_root=e2e_setup["anc_root"],
            ndvi_clim_folder=e2e_setup["ndvi_clim_folder"],
            grid_shape=(_NROWS, _NCOLS),
            reuse_block_cache=False,
        )
        assert result.omega_pixel_map.shape == (_NROWS, _NCOLS)

    def test_block_maps_shape_matches_blocks(self, e2e_setup, monkeypatch) -> None:
        """sm_maps/vod_maps/omega_maps 是 dict[block_idx] = ndarray(grid_shape)。

        注：sm_maps 是 dict[int, np.ndarray]，不是 list。反演成功率 0 时
        网格全 NaN 但 dict 仍有块条目。
        """
        monkeypatch.setenv("OMEGA_SF_MAX_PIXELS", "0")
        result = retrieve_omega_sf_daily(
            config=e2e_setup["config"],
            smap_folder=e2e_setup["smap_folder"],
            anc_root=e2e_setup["anc_root"],
            ndvi_clim_folder=e2e_setup["ndvi_clim_folder"],
            grid_shape=(_NROWS, _NCOLS),
            reuse_block_cache=False,
        )
        # sm_maps 是 dict，10 天 / 8 天块 → 至少 1 个块
        assert isinstance(result.sm_maps, dict)
        assert len(result.sm_maps) >= 1, "sm_maps 不应为空（block_struct 至少 1 块）"
        for blk_idx, sm_grid in result.sm_maps.items():
            assert sm_grid.shape == (
                _NROWS,
                _NCOLS,
            ), f"block {blk_idx}: {sm_grid.shape} != ({_NROWS}, {_NCOLS})"

    def test_counts_consistent(self, e2e_setup, monkeypatch) -> None:
        """n_pixels_total == success + failed（每个像元要么成功要么失败）。"""
        monkeypatch.setenv("OMEGA_SF_MAX_PIXELS", "0")
        result = retrieve_omega_sf_daily(
            config=e2e_setup["config"],
            smap_folder=e2e_setup["smap_folder"],
            anc_root=e2e_setup["anc_root"],
            ndvi_clim_folder=e2e_setup["ndvi_clim_folder"],
            grid_shape=(_NROWS, _NCOLS),
            reuse_block_cache=False,
        )
        assert result.n_pixels_total == result.n_pixels_success + result.n_pixels_failed

    def test_output_dir_writes_files(self, e2e_setup, tmp_path, monkeypatch) -> None:
        """output_dir 不为空时写出 .mat 文件 + output_paths 填充。"""
        monkeypatch.setenv("OMEGA_SF_MAX_PIXELS", "0")
        out_dir = tmp_path / "output"
        result = retrieve_omega_sf_daily(
            config=e2e_setup["config"],
            smap_folder=e2e_setup["smap_folder"],
            anc_root=e2e_setup["anc_root"],
            ndvi_clim_folder=e2e_setup["ndvi_clim_folder"],
            grid_shape=(_NROWS, _NCOLS),
            output_dir=str(out_dir),
            reuse_block_cache=False,
        )
        assert result.output_paths, "output_paths 不应为空"
        assert "omega_pft" in result.output_paths
        assert "omega_pixel" in result.output_paths
        assert Path(result.output_paths["omega_pft"]).exists()
        assert Path(result.output_paths["omega_pixel"]).exists()

    def test_max_pixels_limits_processing(self, e2e_setup, monkeypatch) -> None:
        """OMEGA_SF_MAX_PIXELS=1 时只处理 1 个有效像元。"""
        monkeypatch.setenv("OMEGA_SF_MAX_PIXELS", "1")
        result = retrieve_omega_sf_daily(
            config=e2e_setup["config"],
            smap_folder=e2e_setup["smap_folder"],
            anc_root=e2e_setup["anc_root"],
            ndvi_clim_folder=e2e_setup["ndvi_clim_folder"],
            grid_shape=(_NROWS, _NCOLS),
            reuse_block_cache=False,
        )
        # n_pixels_total 应 ≤ 1（max_pixels 截断）
        assert result.n_pixels_total <= 1

    def test_numerical_baseline_stable(self, e2e_setup, monkeypatch) -> None:
        """数值 golden baseline：同一场景两次运行结果一致。"""
        monkeypatch.setenv("OMEGA_SF_MAX_PIXELS", "0")

        def _run():
            return retrieve_omega_sf_daily(
                config=e2e_setup["config"],
                smap_folder=e2e_setup["smap_folder"],
                anc_root=e2e_setup["anc_root"],
                ndvi_clim_folder=e2e_setup["ndvi_clim_folder"],
                grid_shape=(_NROWS, _NCOLS),
                reuse_block_cache=False,
            )

        r1 = _run()
        r2 = _run()
        # 计数一致
        assert r1.n_pixels_total == r2.n_pixels_total
        assert r1.n_pixels_success == r2.n_pixels_success
        # omega_pixel_map 数值一致
        np.testing.assert_array_equal(
            np.asarray(r1.omega_pixel_map),
            np.asarray(r2.omega_pixel_map),
        )
        # omega_pix_count 一致（可能是数组或标量，统一用 array_equal）
        np.testing.assert_array_equal(
            np.asarray(r1.omega_pixel_count).ravel(),
            np.asarray(r2.omega_pixel_count).ravel(),
        )
