"""FY-3F MWRI（ORBA 升轨）接入测试。

覆盖（对应 2026-08-19 P5 阶段）：
  - 文件发现：``FY3F_MWRI-_ORBA_L1_*.HDF`` 卫星/轨道识别（satellite=FY3F, orbit=ORBA）
  - profile：FY3F SDS 路径 / 源 nodata（TB=-32767, IA=-32768, 经纬度=-9999.9）/ scale
  - 3D TB 抽取：命令构建（EXTRACT_TB_CHANNEL + -b 1 临时 HDF5 URI）与 h5py 执行
  - 计划构建：orbit_mode=ORBA 生成 FY3F 日计划

参照课题组原始代码：``Matlab/fy拼接/B4_FY3F.m`` 与 ``FY3F_MWRI_mosaic.py``。

运行方式（仓库根执行）::

    Env/Python312/python.exe -m pytest Test/algorithms/test_fy3f_pipeline.py -q
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

# 先完整初始化 contracts/workflow 链：utils.local_adapters → contracts →
# workflow → runner.dispatch → utils.local_adapters 存在拓扑环，若 utils
# 先于 contracts 导入会触发 partial-init ImportError。
import contracts  # noqa: F401

from algorithms.fy import (
    FY3F_PROFILE,
    build_fy_daily_command_steps,
    get_fy_profile,
)
from ingest.fy import (
    build_fy_daily_job_plans,
    detect_fy_orbit_type,
    detect_fy_satellite,
)

_FY3F_FILE_NAME = "FY3F_MWRI-_ORBA_L1_20250101_011000_0.MWI.L1.HDF"


def _make_fy3f_hdf(path: Path) -> Path:
    """合成 FY-3F MWRI L1 HDF：3D TB + 2D 经纬度/天顶角（带空格组名）。"""
    import h5py
    import numpy as np

    rng = np.random.default_rng(20260819)
    tb = rng.integers(-1000, 1000, size=(24, 16, 10), dtype=np.int16)
    lat = rng.uniform(-90, 90, size=(24, 16)).astype(np.float32)
    lon = rng.uniform(-180, 180, size=(24, 16)).astype(np.float32)
    zen = rng.integers(0, 18000, size=(24, 16), dtype=np.int16)
    with h5py.File(path, "w") as h5:
        grp = h5.create_group("Window Channel")
        cal = grp.create_group("Calibration")
        cal.create_dataset("EARTH_OBSERVE_BT", data=tb)
        geo = grp.create_group("Geolocation")
        geo.create_dataset("Latitude", data=lat)
        geo.create_dataset("Longitude", data=lon)
        geo.create_dataset("Sensor_Zenith", data=zen)
    return path


class Fy3fDetectionTests(unittest.TestCase):
    """FY3F 文件名识别。"""

    def test_satellite_detection(self) -> None:
        self.assertEqual(detect_fy_satellite(_FY3F_FILE_NAME), "FY3F")

    def test_orba_orbit_detection(self) -> None:
        self.assertEqual(detect_fy_orbit_type(_FY3F_FILE_NAME), "ORBA")

    def test_fy3d_mwrid_still_detected(self) -> None:
        self.assertEqual(detect_fy_satellite("FY3D_GBAL_L1_10V_20230101_MWRID_0.tif"), "FY3D")
        self.assertEqual(detect_fy_orbit_type("FY3D_GBAL_L1_10V_20230101_MWRID_0.tif"), "MWRID")


class Fy3fProfileTests(unittest.TestCase):
    """FY3F profile 配置（以课题组原始代码实测属性为准）。"""

    def test_get_fy_profile_returns_fy3f(self) -> None:
        profile = get_fy_profile("FY3F")
        self.assertIs(profile, FY3F_PROFILE)

    def test_profile_values(self) -> None:
        self.assertEqual(profile_sds := FY3F_PROFILE.tb_sds_path, "//Window_Channel/Calibration/EARTH_OBSERVE_BT")
        self.assertEqual(FY3F_PROFILE.lat_sds_path, "//Window_Channel/Geolocation/Latitude")
        self.assertEqual(FY3F_PROFILE.zen_sds_path, "//Window_Channel/Geolocation/Sensor_Zenith")
        self.assertEqual(FY3F_PROFILE.tb_src_nodata, -32767.0)
        self.assertEqual(FY3F_PROFILE.zen_src_nodata, -32768.0)
        self.assertEqual(FY3F_PROFILE.lat_lon_src_nodata, -9999.9)
        self.assertEqual(FY3F_PROFILE.tb_scale, 0.01)
        self.assertEqual(FY3F_PROFILE.tb_offset, 327.68)
        self.assertTrue(FY3F_PROFILE.tb_3d_extract)
        self.assertEqual(FY3F_PROFILE.tb_h5_group_path, "Window Channel/Calibration/EARTH_OBSERVE_BT")
        self.assertEqual(FY3F_PROFILE.output_prefix, "FY3F_GBAL_L1")


class Fy3fJobPlanTests(unittest.TestCase):
    """FY3F 日计划构建（orbit_mode=ORBA）。"""

    def test_orba_plan_built_from_fy3f_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _make_fy3f_hdf(tmp_dir / _FY3F_FILE_NAME)
            plans = build_fy_daily_job_plans(
                input_dir=tmp_dir,
                output_root=tmp_dir,
                start_time=datetime(2025, 1, 1),
                end_time=datetime(2025, 1, 1),
                orbit_mode="ORBA",
            )
            self.assertEqual(len(plans), 1)
            plan = plans[0]
            self.assertEqual(plan.satellite, "FY3F")
            self.assertEqual(plan.orbit_type, "ORBA")
            self.assertEqual(plan.date_key, "20250101")
            self.assertEqual(len(plan.input_files), 1)

    def test_mwrid_mode_skips_fy3f_orba_files(self) -> None:
        """orbit_mode=MWRID（FY3D 主链）不受 FY3F ORBA 文件影响。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _make_fy3f_hdf(tmp_dir / _FY3F_FILE_NAME)
            plans = build_fy_daily_job_plans(
                input_dir=tmp_dir,
                output_root=tmp_dir,
                start_time=datetime(2025, 1, 1),
                end_time=datetime(2025, 1, 1),
                orbit_mode="MWRID",
            )
            self.assertEqual(plans, [])


class Fy3fCommandStepsTests(unittest.TestCase):
    """FY3F 命令构建：3D TB 先抽通道再 -b 1。"""

    def _plan(self, tmp_dir: Path, input_file: Path):
        from ingest.fy import FyDailyJobPlan

        return FyDailyJobPlan(
            date_key="20250101",
            orbit_type="ORBA",
            input_files=(str(input_file),),
            output_dir=str(tmp_dir),
            work_dir=str(tmp_dir),
            output_prefix="FY3F_GBAL_L1_10V10H_20250101_ORBA",
            satellite="FY3F",
            metadata={"input_dir": str(tmp_dir), "file_count": "1"},
        )

    def test_fy3f_steps_include_extract_and_band1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            input_file = _make_fy3f_hdf(tmp_dir / _FY3F_FILE_NAME)
            steps = build_fy_daily_command_steps(
                self._plan(tmp_dir, input_file), band_ids=(1, 2)
            )
            extract_steps = [s for s in steps if s.command.startswith("EXTRACT_TB_CHANNEL")]
            translate_steps = [s for s in steps if s.name.startswith("translate_tb_vrt")]
            self.assertEqual(len(extract_steps), 2, "10V/10H 各一个抽取步骤")
            self.assertEqual(len(translate_steps), 2)
            for band, step in zip(("10V", "10H"), translate_steps):
                self.assertIn("-b 1 ", step.command, f"{band} 应以 -b 1 读临时 2D HDF5")
                self.assertIn("tb_", step.command, f"{band} 应引用临时抽取文件")
            for step, channel in zip(extract_steps, (0, 1)):
                self.assertEqual(step.metadata["channel_index"], channel)
                self.assertEqual(
                    step.metadata["h5_group_path"],
                    "Window Channel/Calibration/EARTH_OBSERVE_BT",
                )

    def test_fy3d_steps_do_not_include_extract(self) -> None:
        """FY3D 主链保持既有行为（无抽取步骤，-b 直选波段）。"""
        from ingest.fy import FyDailyJobPlan

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            input_file = tmp_dir / "FY3D_MWRID_20230101.HDF"
            input_file.touch()
            plan = FyDailyJobPlan(
                date_key="20230101",
                orbit_type="MWRID",
                input_files=(str(input_file),),
                output_dir=str(tmp_dir),
                work_dir=str(tmp_dir),
                output_prefix="FY3D_GBAL_L1_10V10H_20230101_MWRID",
                satellite="FY3D",
                metadata={},
            )
            steps = build_fy_daily_command_steps(plan, band_ids=(1, 2))
            self.assertFalse(any(s.command.startswith("EXTRACT_TB_CHANNEL") for s in steps))
            translate = [s for s in steps if s.name.startswith("translate_tb_vrt")]
            self.assertEqual(len(translate), 2)
            self.assertIn("-b 1 ", translate[0].command)
            self.assertIn("-b 2 ", translate[1].command)

    def test_gdalwarp_daily_steps_use_overwrite_for_reruns(self) -> None:
        """重跑同日计划时 _work 下已有 GeoTIFF 须可覆盖（勿因残留半成品失败）。"""
        from ingest.fy import FyDailyJobPlan

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            input_file = tmp_dir / "FY3D_MWRID_20230101.HDF"
            input_file.touch()
            plan = FyDailyJobPlan(
                date_key="20230101",
                orbit_type="MWRID",
                input_files=(str(input_file),),
                output_dir=str(tmp_dir),
                work_dir=str(tmp_dir),
                output_prefix="FY3D_GBAL_L1_10V10H_20230101_MWRID",
                satellite="FY3D",
                metadata={},
            )
            steps = build_fy_daily_command_steps(plan, band_ids=(1, 2))
            warp_4326 = [s for s in steps if s.name.startswith("warp_daily_4326_")]
            warp_final = [s for s in steps if s.name.startswith("warp_daily_final_")]
            translate_mb = [s for s in steps if s.name == "translate_multiband_tif"]
            self.assertTrue(warp_4326, "应有 warp_daily_4326 步骤")
            for step in (*warp_4326, *warp_final):
                self.assertIn("-overwrite", step.command, step.name)
            self.assertIn("-overwrite", translate_mb[0].command)


class Fy3fExtractExecutorTests(unittest.TestCase):
    """EXTRACT_TB_CHANNEL 步骤执行（h5py 真实抽取）。"""

    def test_extract_channel_end_to_end(self) -> None:
        import h5py
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            source = _make_fy3f_hdf(tmp_dir / _FY3F_FILE_NAME)
            target = tmp_dir / "tb_extracted.h5"
            from utils.fy_executor import extract_tb_channel_to_h5

            result = extract_tb_channel_to_h5(
                source_hdf=source,
                h5_group_path="Window Channel/Calibration/EARTH_OBSERVE_BT",
                channel_index=0,
                target_h5=target,
            )
            self.assertTrue(result.exists())
            with (
                h5py.File(source, "r") as src,
                h5py.File(target, "r") as dst,
            ):
                expected = src["Window Channel/Calibration/EARTH_OBSERVE_BT"][:, :, 0]
                np.testing.assert_array_equal(dst["TB"][()], expected)
                self.assertEqual(dst["TB"].ndim, 2)

    def test_executor_handles_extract_step(self) -> None:
        import h5py

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            source = _make_fy3f_hdf(tmp_dir / _FY3F_FILE_NAME)
            target = tmp_dir / "tb_10V.h5"
            from algorithms.fy import FyCommandStep

            step = FyCommandStep(
                name="extract_tb_channel_10V",
                command=f"EXTRACT_TB_CHANNEL {source} channel=1 -> {target}",
                outputs=(str(target),),
                metadata={
                    "source_hdf": str(source),
                    "h5_group_path": "Window Channel/Calibration/EARTH_OBSERVE_BT",
                    "channel_index": 0,
                    "target_h5": str(target),
                },
            )
            from utils.fy_executor import execute_fy_command_steps

            results = execute_fy_command_steps([step])
            self.assertEqual(results[0]["returncode"], 0)
            self.assertTrue(target.exists())
            with h5py.File(target, "r") as h5:
                self.assertIn("TB", h5)


if __name__ == "__main__":
    unittest.main()
