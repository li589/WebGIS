"""DuXinTimeSeriesSmeModule 集成测试：.mat 输入 → 反演产物 → manifest。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROVIDER_ROOT = (
    Path(__file__).resolve().parents[2] / "Code" / "algorithms" / "providers" / "Python"
)
if str(PROVIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(PROVIDER_ROOT))

from contracts.job import JobRequest  # noqa: E402
from contracts.product import OutputSpec  # noqa: E402
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange  # noqa: E402
from modules.duxin_sme import DuxinTimeSeriesSmeModule  # noqa: E402
from workflow.artifact_store import InMemoryArtifactStore  # noqa: E402
from workflow.schemas import NodeExecutionContext  # noqa: E402


def _make_ctx(root: Path, job_id: str = "job-duxin") -> NodeExecutionContext:
    request = JobRequest(
        job_id=job_id,
        pipeline_name="workflow",
        task_type="duxin_time_series_sme",
        time_range=TimeRange(
            start=datetime(2025, 6, 1, tzinfo=timezone.utc),
            end=datetime(2025, 6, 30, tzinfo=timezone.utc),
        ),
        region=RegionSpec(kind="global", value={}),
        datasource_selection={},
        algorithm_params={},
        output_spec=OutputSpec(),
    )
    rt = RuntimeContext(
        job_id=job_id,
        run_id=f"run-{job_id}",
        workspace=root,
        tmp_dir=root / "tmp",
        cache_dir=root / "cache",
    )
    return NodeExecutionContext(
        workflow_id=f"wf-{job_id}",
        node_id="n1",
        request=request,
        runtime_context=rt,
        workspace=root,
        artifact_store=InMemoryArtifactStore(),
    )


def _write_input_mat(path: Path, rows: int = 6, cols: int = 7, n: int = 6) -> None:
    """构造与 MATLAB 原版主程序同形态的模拟输入。"""
    from scipy.io import savemat

    rng = np.random.default_rng(2026)
    base = rng.uniform(0.05, 0.3, (rows, cols))
    trend = np.linspace(0.8, 1.5, n)
    obsv = np.clip(base[:, :, None] * trend[None, None, :], 0.01, None)
    ang = rng.uniform(0.35, 1.15, (rows, cols))
    savemat(path, {"obsv_data": obsv, "inc_ang": ang})


class DuxinModuleTests(unittest.TestCase):
    def test_spec_declares_ports(self) -> None:
        spec = DuxinTimeSeriesSmeModule().get_spec()
        inputs = [p.name for p in spec.input_ports]
        outputs = [p.name for p in spec.output_ports]
        self.assertIn("data", inputs)
        self.assertIn("datasource_selection", inputs)
        self.assertIn("algorithm_params", inputs)
        self.assertIn("manifest", outputs)

    def test_execute_produces_mat_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_file = root / "input_sme.mat"
            _write_input_mat(input_file, rows=6, cols=7, n=6)

            module = DuxinTimeSeriesSmeModule()
            result = module.execute(
                inputs={
                    "data": str(input_file),
                    "datasource_selection": {},
                    "algorithm_params": {"polarization": "hh"},
                    "output_spec_extra": {},
                },
                params={},
                ctx=_make_ctx(root),
            )

            # 返回 manifest artifact
            self.assertIn("manifest", result)
            artifact = result["manifest"]
            self.assertEqual(artifact.artifact_type, "product_manifest")

            # 产物目录：每期一个 .mat + GeoTIFF
            product_dir = root / "products" / "duxin_time_series_sme"
            mat_files = sorted(product_dir.glob("soil_moisture_*.mat"))
            self.assertEqual(len(mat_files), 6)
            tif_files = sorted(product_dir.glob("*.tif"))
            self.assertTrue(tif_files, "GeoTIFF outputs expected")

            # manifest.json 落盘
            manifest_path = product_dir / "manifest.json"
            self.assertTrue(manifest_path.exists())

            # MAT 内容校验：三期变量 + 物理范围
            from scipy.io import loadmat

            payload = loadmat(mat_files[0])
            for var in ("soil_moisture", "soil_epsilon", "soil_alpha"):
                self.assertIn(var, payload)
            moisture = np.asarray(payload["soil_moisture"])
            self.assertEqual(moisture.shape, (6, 7))
            valid = moisture > 0
            if valid.any():
                self.assertGreaterEqual(moisture[valid].min(), 0.0)
                self.assertLessEqual(moisture[valid].max(), 60.0)

    def test_execute_via_datasource_input_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_file = root / "input2.mat"
            _write_input_mat(input_file, rows=4, cols=4, n=5)

            module = DuxinTimeSeriesSmeModule()
            result = module.execute(
                inputs={
                    "datasource_selection": {"input_file": str(input_file)},
                    "algorithm_params": {"polarization": "vv", "num_step": 4},
                    "output_spec_extra": {},
                },
                params={},
                ctx=_make_ctx(root, job_id="job-duxin-2"),
            )
            self.assertIn("manifest", result)
            product_dir = root / "products" / "duxin_time_series_sme"
            self.assertEqual(len(list(product_dir.glob("soil_moisture_*.mat"))), 5)

    def test_execute_rejects_missing_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = DuxinTimeSeriesSmeModule()
            with self.assertRaises((KeyError, FileNotFoundError)):
                module.execute(
                    inputs={"datasource_selection": {}, "algorithm_params": {}},
                    params={},
                    ctx=_make_ctx(root, job_id="job-duxin-3"),
                )

    def test_execute_rejects_mat_missing_variables(self) -> None:
        from scipy.io import savemat

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad.mat"
            savemat(bad, {"unrelated": np.zeros((2, 2))})
            module = DuxinTimeSeriesSmeModule()
            with self.assertRaises(KeyError):
                module.execute(
                    inputs={"data": str(bad), "algorithm_params": {}},
                    params={},
                    ctx=_make_ctx(root, job_id="job-duxin-4"),
                )


if __name__ == "__main__":
    unittest.main()
