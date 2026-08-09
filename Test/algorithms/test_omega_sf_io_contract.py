"""行为契约测试：_load_ancillary 与 _preload_chunk 重构保真。

验证 omega_sf.py 复杂度拆分（C52/C57 → ≤10）后 I/O 行为不变：
- _load_ancillary: 合成 ancillary .mat 文件 → 断言 anc dict 的 key 集合 + 关键值
- _preload_chunk: 合成 SMAP/FY3D/NDVI 文件 → 断言输出 dict 结构 + 形状 + 关键值

合成数据用 scipy.io.savemat 生成（v7 格式，load_mat_file 可读）。
若重构改变了 I/O 行为（key 顺序、填充逻辑、回退分支），本测试会失败。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from algorithms.omega_sf import (
    OmegaSfConfig,
    _load_ancillary,
    _preload_chunk,
)


# ─── 合成数据 helpers ───────────────────────────────────────────────────────

_NPIX = 12  # 3x4 grid，足够小但能覆盖 lin_pix 越界


def _make_ancillary_tree(tmp: Path) -> Path:
    """合成 ancillary 目录（IGBP/Albedo/B/SF/BD/H/CF/VI_v_qa + NDVI_clim/）。"""
    anc = tmp / "anc"
    anc.mkdir()
    grid = np.arange(_NPIX, dtype=np.float64).reshape(3, 4)
    savemat(
        str(anc / "IGBP_9km_12.mat"),
        {
            "IGBP_9km_12": grid,
            "lat_9km": np.linspace(30, 35, _NPIX).reshape(3, 4),
            "lon_9km": np.linspace(110, 115, _NPIX).reshape(3, 4),
        },
    )
    savemat(str(anc / "Albedo.mat"), {"ALBEDO": np.full(_NPIX, 0.15).reshape(3, 4)})
    savemat(str(anc / "B.mat"), {"B": np.full(_NPIX, -0.32).reshape(3, 4)})
    savemat(str(anc / "SF.mat"), {"SF_smap": np.full(_NPIX, 0.5).reshape(3, 4)})
    savemat(str(anc / "BD.mat"), {"BD": np.full(_NPIX, 1.3).reshape(3, 4)})
    savemat(str(anc / "H.mat"), {"H": np.full(_NPIX, 0.1).reshape(3, 4)})
    savemat(str(anc / "CF.mat"), {"CF": np.full(_NPIX, 0.3).reshape(3, 4)})
    savemat(
        str(anc / "VI_v_qa.mat"),
        {
            "NDVI_v_max": np.full(_NPIX, 0.8),
            "NDVI_v_min": np.full(_NPIX, 0.1),
        },
    )
    # NDVI_clim 文件夹（DOY 文件）
    clim = anc / "NDVI_clim"
    clim.mkdir()
    savemat(str(clim / "1.mat"), {"NDVI_clim": np.full(_NPIX, 0.4).reshape(3, 4)})
    return anc


def _make_smap_day(folder: Path, date_str: str, offset: float = 0.0) -> None:
    """合成单日 SMAP 文件。"""
    folder.mkdir(parents=True, exist_ok=True)
    savemat(
        str(folder / f"{date_str}.mat"),
        {
            "TBv": np.full(_NPIX, 255.0 + offset).reshape(3, 4),
            "TBh": np.full(_NPIX, 235.0 + offset).reshape(3, 4),
            "IA": np.full(_NPIX, 40.0).reshape(3, 4),
            "Ts": np.full(_NPIX, 290.0 + offset).reshape(3, 4),
            "sm_dca": np.full(_NPIX, 0.2).reshape(3, 4),
        },
    )


# ─── _load_ancillary 契约 ───────────────────────────────────────────────────


class TestLoadAncillary:
    def test_loads_all_fields(self, tmp_path: Path) -> None:
        anc = _load_ancillary(str(_make_ancillary_tree(tmp_path)))
        # 核心 key 集合
        expected_keys = {
            "landcover",
            "lat",
            "lon",
            "albedo",
            "b",
            "sf_static",
            "bd",
            "h",
            "clay",
            "ndvi_v_max",
            "ndvi_v_min",
            "ndvi_clim_max",
            "ndvi_clim_min",
            "porosity",
        }
        assert expected_keys <= set(
            anc.keys()
        ), f"缺失 key: {expected_keys - set(anc.keys())}"

    def test_landcover_values(self, tmp_path: Path) -> None:
        anc = _load_ancillary(str(_make_ancillary_tree(tmp_path)))
        np.testing.assert_array_equal(
            np.asarray(anc["landcover"]).ravel(),
            np.arange(_NPIX, dtype=np.float64),
        )

    def test_porosity_computed_from_bd(self, tmp_path: Path) -> None:
        anc = _load_ancillary(str(_make_ancillary_tree(tmp_path)))
        # BD=1.3 → porosity = 1 - 1.3/2.65 ≈ 0.5094
        np.testing.assert_allclose(
            np.asarray(anc["porosity"]).ravel(),
            np.full(_NPIX, 1.0 - 1.3 / 2.65),
            rtol=1e-9,
        )

    def test_ndvi_extrema_raveled(self, tmp_path: Path) -> None:
        anc = _load_ancillary(str(_make_ancillary_tree(tmp_path)))
        assert np.asarray(anc["ndvi_v_max"]).ndim == 1  # ravel 后 1D
        np.testing.assert_allclose(
            np.asarray(anc["ndvi_v_max"]),
            np.full(_NPIX, 0.8),
        )

    def test_missing_igbp_falls_back_to_defaults(self, tmp_path: Path) -> None:
        """无 IGBP 文件时 landcover 默认 zeros(1,1)。"""
        anc = _load_ancillary(str(tmp_path / "empty_anc"))
        assert "landcover" in anc
        assert np.asarray(anc["landcover"]).size == 1

    def test_ndvi_extrema_unreadable_falls_back_to_clim(self, tmp_path: Path) -> None:
        """VI_v_qa.mat 不存在时 ndvi_v_max 回退到 ndvi_clim_max。"""
        anc_root = _make_ancillary_tree(tmp_path)
        (anc_root / "VI_v_qa.mat").unlink()
        anc = _load_ancillary(str(anc_root))
        # ndvi_clim_max 来自 DOY=1 的 NDVI_clim=0.4
        np.testing.assert_allclose(
            np.asarray(anc["ndvi_v_max"]).ravel(),
            np.full(_NPIX, 0.4),
        )


# ─── _preload_chunk 契约 ─────────────────────────────────────────────────────


class TestPreloadChunk:
    @pytest.fixture
    def smap_setup(self, tmp_path: Path):
        """合成 SMAP 模式场景：3 天 SMAP 数据 + ancillary。"""
        anc_root = _make_ancillary_tree(tmp_path)
        smap_folder = tmp_path / "smap"
        tvec = [datetime(2025, 12, 1) + timedelta(days=i) for i in range(3)]
        for i, d in enumerate(tvec):
            _make_smap_day(smap_folder, d.strftime("%Y%m%d"), offset=i * 1.0)
        anc = _load_ancillary(str(anc_root))
        config = OmegaSfConfig.from_params(
            {
                "tb_source": "SMAP",
                "sf_mode": "STATIC",
                "ndvi_mode": "DOY_CLIM",
            }
        )
        return {
            "tvec": tvec,
            "anc": anc,
            "config": config,
            "smap_folder": str(smap_folder),
            "ndvi_clim_folder": str(anc_root / "NDVI_clim"),
            "ndvi_folder": "",
            "fy3d_folder": "",
            "fy3b_folder": "",
        }

    def test_returns_all_seven_keys(self, smap_setup) -> None:
        result = _preload_chunk(
            smap_setup["tvec"],
            3,
            4,
            smap_setup["config"],
            smap_setup["smap_folder"],
            smap_setup["fy3d_folder"],
            smap_setup["fy3b_folder"],
            smap_setup["ndvi_clim_folder"],
            smap_setup["ndvi_folder"],
            smap_setup["anc"],
            lin_pix=np.arange(_NPIX, dtype=np.int64),
        )
        assert set(result.keys()) == {"tbv", "tbh", "ia", "ts", "sm_ref", "ndvi", "sf"}

    def test_output_shapes(self, smap_setup) -> None:
        lin_pix = np.array([0, 2, 5, 7], dtype=np.int64)
        result = _preload_chunk(
            smap_setup["tvec"],
            3,
            4,
            smap_setup["config"],
            smap_setup["smap_folder"],
            smap_setup["fy3d_folder"],
            smap_setup["fy3b_folder"],
            smap_setup["ndvi_clim_folder"],
            smap_setup["ndvi_folder"],
            smap_setup["anc"],
            lin_pix=lin_pix,
        )
        nt = len(smap_setup["tvec"])
        chunk_pix = lin_pix.size
        for key in ("tbv", "tbh", "ia", "ts", "sm_ref", "ndvi", "sf"):
            assert result[key].shape == (
                nt,
                chunk_pix,
            ), f"{key}: {result[key].shape} != ({nt}, {chunk_pix})"

    def test_smap_tb_values_filled(self, smap_setup) -> None:
        """SMAP 模式 TBv 应从 SMAP 文件填充（255+offset）。"""
        result = _preload_chunk(
            smap_setup["tvec"],
            3,
            4,
            smap_setup["config"],
            smap_setup["smap_folder"],
            smap_setup["fy3d_folder"],
            smap_setup["fy3b_folder"],
            smap_setup["ndvi_clim_folder"],
            smap_setup["ndvi_folder"],
            smap_setup["anc"],
            lin_pix=np.arange(_NPIX, dtype=np.int64),
        )
        # 第 0 天 TBv=255，第 1 天=256，第 2 天=257
        np.testing.assert_allclose(result["tbv"][0, 0], 255.0)
        np.testing.assert_allclose(result["tbv"][1, 0], 256.0)
        np.testing.assert_allclose(result["tbv"][2, 0], 257.0)

    def test_sf_static_mode(self, smap_setup) -> None:
        """STATIC 模式 SF 应等于 anc['sf_static'][lin_pix]=0.5。"""
        result = _preload_chunk(
            smap_setup["tvec"],
            3,
            4,
            smap_setup["config"],
            smap_setup["smap_folder"],
            smap_setup["fy3d_folder"],
            smap_setup["fy3b_folder"],
            smap_setup["ndvi_clim_folder"],
            smap_setup["ndvi_folder"],
            smap_setup["anc"],
            lin_pix=np.arange(_NPIX, dtype=np.int64),
        )
        np.testing.assert_allclose(result["sf"], np.full((3, _NPIX), 0.5))

    def test_chunk_start_end_equivalent_to_lin_pix(self, smap_setup) -> None:
        """chunk_start/chunk_end 等价于 lin_pix=arange(start,end)。"""
        r1 = _preload_chunk(
            smap_setup["tvec"],
            3,
            4,
            smap_setup["config"],
            smap_setup["smap_folder"],
            smap_setup["fy3d_folder"],
            smap_setup["fy3b_folder"],
            smap_setup["ndvi_clim_folder"],
            smap_setup["ndvi_folder"],
            smap_setup["anc"],
            chunk_start=0,
            chunk_end=_NPIX,
        )
        r2 = _preload_chunk(
            smap_setup["tvec"],
            3,
            4,
            smap_setup["config"],
            smap_setup["smap_folder"],
            smap_setup["fy3d_folder"],
            smap_setup["fy3b_folder"],
            smap_setup["ndvi_clim_folder"],
            smap_setup["ndvi_folder"],
            smap_setup["anc"],
            lin_pix=np.arange(_NPIX, dtype=np.int64),
        )
        for key in ("tbv", "tbh", "ia", "ts", "sm_ref", "ndvi", "sf"):
            np.testing.assert_allclose(r1[key], r2[key], equal_nan=True)

    def test_missing_smap_file_yields_nan_row(self, smap_setup, tmp_path: Path):
        """SMAP 文件缺失时该行保持 NaN。"""
        # 删掉第 1 天的 SMAP 文件
        (Path(smap_setup["smap_folder"]) / "20251202.mat").unlink()
        result = _preload_chunk(
            smap_setup["tvec"],
            3,
            4,
            smap_setup["config"],
            smap_setup["smap_folder"],
            smap_setup["fy3d_folder"],
            smap_setup["fy3b_folder"],
            smap_setup["ndvi_clim_folder"],
            smap_setup["ndvi_folder"],
            smap_setup["anc"],
            lin_pix=np.arange(_NPIX, dtype=np.int64),
        )
        # 第 1 行（k=1）TBv 应全 NaN
        assert np.all(np.isnan(result["tbv"][1]))
        # 第 0 行仍有效
        assert not np.all(np.isnan(result["tbv"][0]))
