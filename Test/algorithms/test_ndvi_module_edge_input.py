"""NdviDailyModule 边输入契约：archive/extract → data 端口直供目录。

NDVI 在线链（CMR 检索 → Earthdata 下载 → 解压 → ndvi_daily）中，
``archive_extract`` 经 workflow edge 输出解压目录字符串；模块须将其
作为输入目录，而不是仅依赖 request.datasource_selection。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
from modules.ndvi import NdviDailyModule
from workflow.artifact_store import InMemoryArtifactStore
from workflow.schemas import NodeExecutionContext


def _make_ctx(root: Path) -> NodeExecutionContext:
    request = JobRequest(
        job_id="job-ndvi-edge",
        pipeline_name="workflow",
        task_type="ndvi_daily",
        time_range=TimeRange(
            start=datetime(2025, 6, 1, tzinfo=timezone.utc),
            end=datetime(2025, 6, 17, tzinfo=timezone.utc),
        ),
        region=RegionSpec(kind="global", value={}),
        datasource_selection={},
        algorithm_params={},
        output_spec=OutputSpec(),
    )
    rt = RuntimeContext(
        job_id="job-ndvi-edge",
        run_id="run-ndvi-edge",
        workspace=root,
        tmp_dir=root / "tmp",
        cache_dir=root / "cache",
    )
    return NodeExecutionContext(
        workflow_id="wf-ndvi-edge",
        node_id="n4",
        request=request,
        runtime_context=rt,
        workspace=root,
        artifact_store=InMemoryArtifactStore(),
    )


class NdviModuleEdgeInputTests(unittest.TestCase):
    def test_data_port_declared(self) -> None:
        spec = NdviDailyModule().get_spec()
        names = [p.name for p in spec.input_ports]
        self.assertIn("data", names)

    def test_execute_uses_edge_data_dir_over_datasource_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edge_dir = root / "ndvi_extracted"
            edge_dir.mkdir()

            captured: dict[str, Path] = {}

            def fake_load(input_dir, *, start_time, end_time):
                captured["input_dir"] = Path(str(input_dir))
                return np.zeros((2, 2, 1)), [datetime(2025, 6, 1)]

            with (
                patch("modules.ndvi.load_ndvi_stack", side_effect=fake_load),
                patch(
                    "modules.ndvi.process_ndvi_stack_to_daily",
                    return_value=(np.zeros((2, 2, 1)), [datetime(2025, 6, 1)]),
                ),
            ):
                NdviDailyModule().execute(
                    inputs={
                        "data": str(edge_dir),
                        "datasource_selection": {},
                        "algorithm_params": {"emit_quality_products": False},
                        "output_spec_extra": {},
                    },
                    params={},
                    ctx=_make_ctx(root),
                )

            self.assertEqual(captured["input_dir"], edge_dir)


if __name__ == "__main__":
    unittest.main()
