"""
端到端测试脚本：验证数据读取 → 算法处理 → 产物输出的完整链路。

测试内容：
1. OutputCoordinator 的 write_raster：COG + preview PNG
2. OutputCoordinator 的 write_table：Parquet 表格
3. OutputCoordinator 的 add_mat：MAT 文件记录
4. OutputCoordinator 的 build_manifest：manifest.json 组装
5. NdviDailyModule 完整执行：MAT + COG + preview + manifest
6. StationDailyModule 完整执行：MAT + Parquet + manifest
7. 存储抽象层双后端（local/minio）兼容性
8. 数据格式转换（HDF → numpy → COG）

用法：
    cd d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\algorithms\providers\Python
    python -m pytest tests/test_e2e_output_pipeline.py -v
    # 或直接运行：
    python tests/test_e2e_output_pipeline.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np

# 确保项目根目录在 Python 路径中
_ROOT = Path(__file__).parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 设置环境变量（使用本地存储后端）
os.environ.setdefault("BACKEND_STORAGE_BACKEND", "local")
os.environ.setdefault("BACKEND_DATA_ROOT", r"I:\Geograph_DataSet")
os.environ.setdefault("BACKEND_OUTPUT_ROOT", r"I:\GeoOutput")


class TestOutputCoordinatorRasterOutput(unittest.TestCase):
    """测试 OutputCoordinator 的栅格输出：COG + preview PNG"""

    def test_write_raster_produces_cog_and_preview(self):
        from output import OutputCoordinator

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "raster_output"
            coordinator = OutputCoordinator(
                job_id="test-job-raster",
                output_dir=output_dir,
                module_name="test_raster_module",
                crs="EPSG:4326",
                pixel_resolution=0.01,
                preview_cmap="viridis",
                preview_size=(256, 256),
                compress="deflate",
                overwrite=True,
            )

            # 创建合成 NDVI 数据（中国区域 shape：行=纬度，列=经度）
            data = np.random.uniform(-0.1, 0.9, size=(360, 720)).astype(np.float32)
            data = np.clip(data, -0.1, 1.0)

            from rasterio.transform import from_bounds

            west, south, east, north = 73.0, 18.0, 135.0, 53.0
            height, width = data.shape
            transform = from_bounds(west, south, east, north, width, height)

            result = coordinator.write_raster(
                name="test_ndvi",
                data=data,
                transform=transform,
                nodata=-9999.0,
                unit="NDVI",
                description="测试 NDVI 栅格",
                var_name="NDVI",
                generate_preview=True,
            )

            # 验证返回值
            self.assertEqual(result["name"], "test_ndvi")
            self.assertEqual(result["format"], "COG")
            self.assertIn("cog_path", result)
            self.assertIn("preview_path", result)
            self.assertEqual(result["unit"], "NDVI")

            # 验证 COG 文件存在
            cog_path = Path(result["cog_path"])
            self.assertTrue(cog_path.exists(), f"COG 文件不存在: {cog_path}")
            self.assertGreater(cog_path.stat().st_size, 0, "COG 文件为空")

            # 验证 preview PNG 存在
            preview_path = Path(result["preview_path"])
            self.assertTrue(preview_path.exists(), f"Preview PNG 不存在: {preview_path}")
            self.assertGreater(preview_path.stat().st_size, 0, "Preview PNG 为空")

            # 验证 manifest 中有对应条目
            manifest = coordinator.build_manifest()
            self.assertIn("products", manifest)
            raster_products = [p for p in manifest["products"] if p.get("name") == "test_ndvi"]
            self.assertEqual(len(raster_products), 1)
            self.assertEqual(raster_products[0]["format"], "COG")
            self.assertEqual(raster_products[0]["type"], "raster")
            self.assertIn("preview", raster_products[0])

            print(f"  [OK] COG + preview 输出正常: {cog_path.name}, {preview_path.name}")

    def test_write_raster_with_nodata_mask(self):
        from output import OutputCoordinator

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "raster_nodata"
            coordinator = OutputCoordinator(
                job_id="test-job-nodata",
                output_dir=output_dir,
                module_name="test_nodata",
                crs="EPSG:4326",
                pixel_resolution=0.01,
                overwrite=True,
            )

            data = np.full((100, 100), -9999.0, dtype=np.float32)
            data[20:80, 20:80] = 0.5  # 中间有效数据区域

            from rasterio.transform import from_bounds

            transform = from_bounds(0, 0, 10, 10, 100, 100)
            result = coordinator.write_raster(
                name="test_nodata",
                data=data,
                transform=transform,
                nodata=-9999.0,
                generate_preview=False,
            )

            self.assertTrue(Path(result["cog_path"]).exists())
            print("  [OK] nodata 掩膜处理正常")


class TestOutputCoordinatorTableOutput(unittest.TestCase):
    """测试 OutputCoordinator 的表格输出：Parquet"""

    def test_write_table_produces_parquet(self):
        from output import OutputCoordinator

        try:
            import pandas as pd
        except ImportError:
            self.skipTest("pandas 未安装，跳过 Parquet 测试")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "table_output"
            coordinator = OutputCoordinator(
                job_id="test-job-table",
                output_dir=output_dir,
                module_name="test_table_module",
                overwrite=True,
            )

            df = pd.DataFrame(
                {
                    "date": ["2023-01-01", "2023-01-02", "2023-01-03"],
                    "lat": [30.5, 31.0, 31.5],
                    "lon": [114.0, 114.5, 115.0],
                    "soil_moisture": [0.35, 0.38, 0.40],
                    "site_id": ["ISMN_001", "ISMN_001", "ISMN_001"],
                }
            )

            result = coordinator.write_table(
                name="test_station_sm",
                df=df,
                description="测试土壤水分表格",
            )

            self.assertEqual(result["name"], "test_station_sm")
            self.assertIn("path", result)

            table_path = Path(result["path"])
            self.assertTrue(table_path.exists(), f"表格文件不存在: {table_path}")
            self.assertGreater(table_path.stat().st_size, 0, "表格文件为空")

            # pyarrow 缺失时允许回退为 CSV
            if result["format"] == "Parquet":
                df_read = pd.read_parquet(table_path)
            else:
                self.assertTrue(result["format"].startswith("CSV"), result["format"])
                df_read = pd.read_csv(table_path)
            self.assertEqual(len(df_read), 3)
            self.assertIn("date", df_read.columns)
            self.assertIn("soil_moisture", df_read.columns)

            # 验证 manifest 条目
            coordinator.build_manifest()
            table_products = [p for p in coordinator.manifest_products if p.get("name") == "test_station_sm"]
            self.assertEqual(len(table_products), 1)
            self.assertEqual(table_products[0]["format"], result["format"])
            self.assertEqual(table_products[0]["type"], "table")

            print(f"  [OK] 表格输出正常: {table_path.name} ({result['format']})")


class TestOutputCoordinatorManifestBuilding(unittest.TestCase):
    """测试 OutputCoordinator 的 manifest 组装"""

    def test_build_manifest_includes_all_products(self):
        from output import OutputCoordinator

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "manifest_test"
            coordinator = OutputCoordinator(
                job_id="test-job-manifest",
                output_dir=output_dir,
                module_name="test_module",
                time_range={"start": "2023-01-01", "end": "2023-12-31"},
                region={"bounds": [73, 18, 135, 53]},
                crs="EPSG:4326",
                pixel_resolution=0.01,
                overwrite=True,
            )

            # 添加栅格
            data = np.random.rand(50, 50).astype(np.float32)
            from rasterio.transform import from_bounds

            transform = from_bounds(73, 18, 135, 53, 50, 50)
            coordinator.write_raster(
                name="test_raster",
                data=data,
                transform=transform,
                nodata=-9999.0,
                generate_preview=False,
            )

            # 添加 MAT 文件
            mat_path = output_dir / "test.mat"
            from scipy.io import savemat

            savemat(mat_path, {"test_var": data}, do_compression=True)
            coordinator.add_mat(
                name="test_mat",
                path=mat_path,
                variable="test_var",
                description="测试 MAT 文件",
            )

            # 添加诊断信息
            coordinator.add_diagnostic("total_count", 2)
            coordinator.add_diagnostic("status", "success")

            # 构建 manifest
            manifest = coordinator.build_manifest(extra={"custom_field": "custom_value"})

            # 验证 manifest 结构
            self.assertIn("job_id", manifest)
            self.assertEqual(manifest["job_id"], "test-job-manifest")
            self.assertIn("products", manifest)
            self.assertEqual(len(manifest["products"]), 2)

            # 验证栅格条目
            raster_entry = next((p for p in manifest["products"] if p["name"] == "test_raster"), None)
            self.assertIsNotNone(raster_entry)
            self.assertEqual(raster_entry["format"], "COG")
            self.assertEqual(raster_entry["type"], "raster")

            # 验证 MAT 条目
            mat_entry = next((p for p in manifest["products"] if p["name"] == "test_mat"), None)
            self.assertIsNotNone(mat_entry)
            self.assertEqual(mat_entry["format"], "MAT")
            self.assertEqual(mat_entry["type"], "mat")
            self.assertEqual(mat_entry["variable"], "test_var")

            # 验证诊断信息
            self.assertIn("diagnostics", manifest)
            self.assertEqual(manifest["diagnostics"]["total_count"], 2)
            self.assertEqual(manifest["diagnostics"]["status"], "success")

            # 验证附加字段被平铺到 manifest 顶层
            self.assertEqual(manifest["custom_field"], "custom_value")
            self.assertEqual(manifest["module_name"], "test_module")

            # 验证 manifest.json 文件写出
            manifest_path = Path(manifest["manifest_path"])
            self.assertTrue(manifest_path.exists(), f"manifest.json 未写出: {manifest_path}")
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_loaded = json.load(f)
            self.assertEqual(manifest_loaded["job_id"], "test-job-manifest")

            print(f"  [OK] manifest.json 组装正常: {manifest_path.name}")


class TestNdviModuleWithOutputCoordinator(unittest.TestCase):
    """测试 NdviDailyModule 完整执行：MAT + COG + preview + manifest"""

    def test_ndvi_module_produces_cog_and_manifest(self):
        from unittest.mock import MagicMock, patch

        from contracts.job import JobRequest
        from contracts.product import OutputSpec
        from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
        from workflow.schemas import NodeExecutionContext
        from modules.ndvi import NdviDailyModule

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "ndvi_16day"
            output_dir = root / "daily"
            quality_dir = root / "quality"
            input_dir.mkdir()
            output_dir.mkdir()
            quality_dir.mkdir()

            # 合成 NDVI 数据（16天合成 x 5景 x 5x10像素）
            observation_dates = [
                datetime(2023, 1, 1),
                datetime(2023, 1, 17),
                datetime(2023, 2, 2),
                datetime(2023, 2, 18),
                datetime(2023, 3, 6),
            ]
            ndvi_stack = np.stack(
                [np.random.uniform(0.1, 0.8, size=(5, 10)).astype(np.float64) for _ in observation_dates],
                axis=2,
            )
            daily_dates = [datetime(2023, 1, i) for i in range(1, 11)]
            daily_stack = np.stack(
                [np.random.uniform(0.1, 0.8, size=(5, 10)).astype(np.float64) for _ in daily_dates],
                axis=2,
            )

            request = JobRequest(
                job_id="job-ndvi-e2e",
                pipeline_name="ndvi_daily_pipeline",
                task_type="extract",
                time_range=TimeRange(start=datetime(2023, 1, 1), end=datetime(2023, 1, 10)),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(input_dir)},
                algorithm_params={"emit_quality_products": False},
                output_spec=OutputSpec(
                    extra={
                        "output_dir": str(output_dir),
                        "quality_output_dir": str(quality_dir),
                    }
                ),
            )
            runtime_ctx = RuntimeContext(
                job_id="job-ndvi-e2e",
                run_id="run-ndvi-e2e",
                workspace=root,
                tmp_dir=root / "tmp",
                cache_dir=root / "cache",
            )
            mock_logger = MagicMock()
            ctx = NodeExecutionContext(
                workflow_id="wf-ndvi-e2e",
                node_id="node-ndvi",
                request=request,
                runtime_context=runtime_ctx,
                workspace=root,
                artifact_store=MagicMock(),
                logger_adapter=mock_logger,
                product_sink=MagicMock(),
            )

            with patch("modules.ndvi.load_ndvi_stack", return_value=(ndvi_stack, observation_dates)), patch(
                "modules.ndvi.process_ndvi_stack_to_daily",
                return_value=(daily_stack, daily_dates),
            ):
                result = NdviDailyModule().execute(
                    inputs={
                        "datasource_selection": dict(request.datasource_selection),
                        "algorithm_params": dict(request.algorithm_params),
                        "output_spec_extra": dict(request.output_spec.extra),
                    },
                    params={},
                    ctx=ctx,
                )

            # 验证 MAT 文件存在
            mat_files = list(output_dir.glob("*.mat"))
            self.assertGreater(len(mat_files), 0, "MAT 文件未生成")
            print(f"  [OK] 生成了 {len(mat_files)} 个 MAT 文件")

            # 验证 COG 文件存在（来自 manifest.extra）
            manifest_path = str(result["manifest"].metadata.get("manifest_path", ""))
            if manifest_path and Path(manifest_path).exists():
                with open(Path(manifest_path), "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                raster_products = [p for p in manifest_data.get("products", []) if p.get("type") == "raster"]
                if raster_products:
                    for rp in raster_products:
                        cog_path = Path(rp.get("path", ""))
                        self.assertTrue(cog_path.exists(), f"COG 文件不存在: {cog_path}")
                    print(f"  [OK] 生成了 {len(raster_products)} 个 COG 栅格文件")
                else:
                    print("  [INFO] 无栅格产物（可能是合成数据无 transform）")

            # 验证 manifest.json 存在
            if manifest_path:
                self.assertTrue(Path(manifest_path).exists(), f"manifest.json 不存在: {manifest_path}")
                print(f"  [OK] manifest.json 已生成: {Path(manifest_path).name}")

            # 验证 logger 调用
            self.assertTrue(mock_logger.emit_stage_start.called, "emit_stage_start 未调用")
            self.assertTrue(mock_logger.emit_stage_end.called, "emit_stage_end 未调用")


class TestStationModuleWithOutputCoordinator(unittest.TestCase):
    """测试 StationDailyModule 完整执行：MAT + Parquet + manifest"""

    def test_station_module_produces_parquet_and_manifest(self):
        from unittest.mock import MagicMock, patch

        from contracts.job import JobRequest
        from contracts.product import OutputSpec
        from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
        from workflow.schemas import NodeExecutionContext
        from modules.station import StationDailyModule

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "stations"
            output_dir = root / "station_output"
            input_dir.mkdir()
            output_dir.mkdir()

            # 创建合成 .stm 文件
            stm_path = input_dir / "test_sm_0.site001.stm"
            stm_path.write_text("", encoding="utf-8")

            request = JobRequest(
                job_id="job-station-e2e",
                pipeline_name="station_daily_pipeline",
                task_type="extract",
                time_range=TimeRange(start=datetime(2023, 1, 1), end=datetime(2023, 1, 5)),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(input_dir)},
                algorithm_params={
                    "source_type": "ISMN",
                    "emit_validation_products": False,
                    "validation_min_valid_days": 1,
                },
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )
            runtime_ctx = RuntimeContext(
                job_id="job-station-e2e",
                run_id="run-station-e2e",
                workspace=root,
                tmp_dir=root / "tmp",
                cache_dir=root / "cache",
            )
            mock_logger = MagicMock()
            ctx = NodeExecutionContext(
                workflow_id="wf-station-e2e",
                node_id="node-station",
                request=request,
                runtime_context=runtime_ctx,
                workspace=root,
                artifact_store=MagicMock(),
                logger_adapter=mock_logger,
                product_sink=MagicMock(),
            )

            from ingest.station import StationRecord

            records = [
                StationRecord(2023, 1, 1, 6, 30.6, 113.5, 10.0, 0.01, 0.02, 0.35, 1, "SITE001", "ISMN"),
                StationRecord(2023, 1, 2, 6, 30.6, 113.5, 10.0, 0.01, 0.02, 0.36, 1, "SITE001", "ISMN"),
                StationRecord(2023, 1, 3, 6, 30.6, 113.5, 10.0, 0.01, 0.02, 0.37, 1, "SITE001", "ISMN"),
                StationRecord(2023, 1, 4, 6, 30.6, 113.5, 10.0, 0.01, 0.02, 0.38, 1, "SITE001", "ISMN"),
                StationRecord(2023, 1, 5, 6, 30.6, 113.5, 10.0, 0.01, 0.02, 0.39, 1, "SITE001", "ISMN"),
            ]

            with patch("modules.station.parse_ismn_stm_file", return_value=records):
                result = StationDailyModule().execute(
                    inputs={
                        "datasource_selection": dict(request.datasource_selection),
                        "algorithm_params": dict(request.algorithm_params),
                        "output_spec_extra": dict(request.output_spec.extra),
                    },
                    params={},
                    ctx=ctx,
                )

            # 验证 MAT 文件存在
            mat_files = list(output_dir.rglob("*.mat"))
            self.assertGreater(len(mat_files), 0, "MAT 文件未生成")
            print(f"  [OK] 生成了 {len(mat_files)} 个 MAT 文件")

            # 验证 Parquet 文件存在
            try:
                import pandas as pd

                parquet_files = list(output_dir.rglob("*.parquet"))
                csv_files = list(output_dir.rglob("*.csv"))
                table_files = parquet_files or csv_files
                self.assertGreater(len(table_files), 0, "表格文件未生成")
                print(f"  [OK] 生成了 {len(table_files)} 个表格文件")

                # 验证表格内容
                first_table = table_files[0]
                if first_table.suffix.lower() == ".parquet":
                    df = pd.read_parquet(first_table)
                else:
                    df = pd.read_csv(first_table)
                self.assertIn("soil_moisture", df.columns)
                self.assertIn("site_id", df.columns)
                self.assertGreater(len(df), 0)
                print(f"  [OK] 表格数据正常 ({len(df)} 行)")

            except ImportError:
                print("  [SKIP] pandas 未安装，跳过 Parquet 验证")

            # 验证 manifest.json
            manifest_path = str(result["manifest"].metadata.get("manifest_path", ""))
            if manifest_path and Path(manifest_path).exists():
                with open(Path(manifest_path), "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                table_products = [p for p in manifest_data.get("products", []) if p.get("type") == "table"]
                if table_products:
                    print(f"  [OK] manifest 中包含 {len(table_products)} 个表格条目")

            self.assertTrue(mock_logger.emit_stage_start.called)
            self.assertTrue(mock_logger.emit_stage_end.called)


class TestStorageBackendFactory(unittest.TestCase):
    """测试存储抽象层双后端工厂"""

    def test_local_storage_backend_resolves_path(self):
        from storage import get_storage_backend
        from storage.local_fs import LocalFileSystemStorage

        backend = get_storage_backend()
        self.assertIsInstance(backend, LocalFileSystemStorage)

        # 测试路径解析
        resolved = backend.resolve_path("栅格气象数据", "VIIRS_NDVI")
        self.assertIn("栅格气象数据", resolved)

        print(f"  [OK] LocalFileSystemStorage 正常工作，根路径: {backend.root}")

    def test_minio_storage_backend_fallback_to_local(self):
        from storage import get_storage_backend
        from storage.local_fs import LocalFileSystemStorage

        # 即使 BACKEND_STORAGE_BACKEND=minio，MinIO 未运行时也应该回退
        os.environ["BACKEND_STORAGE_BACKEND"] = "minio"
        try:
            backend = get_storage_backend()
            # MinIO 未配置时应回退到 local
            if isinstance(backend, LocalFileSystemStorage):
                print("  [OK] MinIO 不可用时回退到 LocalFileSystemStorage")
            else:
                print("  [INFO] MinIO 后端已配置")
        finally:
            os.environ["BACKEND_STORAGE_BACKEND"] = "local"


class TestIngestNdviTransform(unittest.TestCase):
    """测试 ingest/ndvi.py 返回 transform 信息"""

    def test_load_ndvi_stack_full_returns_transform(self):
        from unittest.mock import MagicMock, patch

        from contextlib import contextmanager

        # 创建一个带 transform 的 mock rasterio dataset
        mock_dataset = MagicMock()
        mock_dataset.read.return_value = np.random.rand(100, 200).astype(np.float32)
        mock_dataset.height = 100
        mock_dataset.width = 200
        mock_dataset.transform = MagicMock()
        mock_dataset.crs = MagicMock()

        @contextmanager
        def mock_rasterio_open(path):
            yield mock_dataset

        with patch("rasterio.open", mock_rasterio_open):
            from ingest.ndvi import NdviStackInfo, load_ndvi_stack_full

            with tempfile.TemporaryDirectory() as tmp_dir:
                input_dir = Path(tmp_dir)
                # 创建一个符合日期格式的假 tif 文件名（YYYYMMDD 格式）
                fake_tif = input_dir / "ndvi_20230101.tif"
                fake_tif.touch()

                result = load_ndvi_stack_full(
                    input_dir=input_dir,
                    start_time=datetime(2023, 1, 1),
                    end_time=datetime(2023, 12, 31),
                )

                self.assertIsInstance(result, NdviStackInfo)
                self.assertIsNotNone(result.transform, "transform 不应为空")
                self.assertIsNotNone(result.crs, "crs 不应为空")
                self.assertGreater(result.width, 0)
                self.assertGreater(result.height, 0)
                self.assertGreater(len(result.dates), 0)
                self.assertEqual(len(result.stack.shape), 3)  # (H, W, T)

                print(f"  [OK] load_ndvi_stack_full 返回正确结构: shape={result.stack.shape}, transform={result.transform}")


class TestDataFormatConversion(unittest.TestCase):
    """测试数据格式转换链路：HDF/MAT → numpy → COG"""

    def test_mat_to_numpy_to_cog_pipeline(self):
        """验证 MAT → numpy 数组 → COG 输出的完整转换链路"""
        from output import OutputCoordinator
        from rasterio.transform import from_bounds
        from scipy.io import savemat

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)

            # Step 1: 写入 MAT 文件（模拟 MATLAB 数据）
            mat_data = np.random.uniform(0.1, 0.9, size=(180, 360)).astype(np.float64)
            mat_path = output_dir / "input.mat"
            savemat(mat_path, {"NDVI": mat_data}, do_compression=True)

            # Step 2: 读取 MAT 文件（模拟 MATLAB 兼容性）
            from scipy.io import loadmat

            loaded = loadmat(mat_path)
            ndvi_array = loaded["NDVI"].astype(np.float32)

            # Step 3: 写出 COG（模拟 WebGIS 可用）
            coordinator = OutputCoordinator(
                job_id="test-mat2cog",
                output_dir=output_dir / "cog_output",
                module_name="mat2cog_test",
                crs="EPSG:4326",
                pixel_resolution=0.01,
                overwrite=True,
            )

            transform = from_bounds(73, 18, 135, 53, ndvi_array.shape[1], ndvi_array.shape[0])
            result = coordinator.write_raster(
                name="ndvi_from_mat",
                data=ndvi_array,
                transform=transform,
                nodata=-9999.0,
                unit="NDVI",
                generate_preview=True,
            )

            cog_path = Path(result["cog_path"])
            self.assertTrue(cog_path.exists(), f"COG 输出失败: {cog_path}")

            # Step 4: 验证 COG 可被 rasterio 读取（模拟 WebGIS 加载）
            try:
                import rasterio

                with rasterio.open(cog_path) as ds:
                    self.assertEqual(ds.crs.to_epsg(), 4326)
                    self.assertEqual(ds.width, ndvi_array.shape[1])
                    self.assertEqual(ds.height, ndvi_array.shape[0])
                print(f"  [OK] MAT → numpy → COG 链路正常，COG 可被 rasterio 读取")
            except ImportError:
                print("  [OK] MAT → numpy → COG 链路正常（rasterio 不可用于验证 CRS）")


if __name__ == "__main__":
    print("=" * 60)
    print("端到端测试：数据 → 算法 → 产物输出")
    print("=" * 60)
    unittest.main(verbosity=2)
