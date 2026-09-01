"""fy_daily：已有 YYYYMMDD.mat 时跳过 GDAL 命令链。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from scipy.io import savemat

_PROVIDER_ROOT = (
    Path(__file__).resolve().parents[2] / "Code" / "algorithms" / "providers" / "Python"
)
if str(_PROVIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROVIDER_ROOT))

import contracts  # noqa: F401 — break circular import


class _FakeArtifactStore:
    def put(self, artifact, payload=None):
        return artifact


def _ctx(workspace: Path):
    from workflow.schemas import NodeExecutionContext

    request = SimpleNamespace(
        job_id="job-fy-skip",
        datasource_selection={"input_dir": str(workspace / "in")},
        region=None,
        time_range=SimpleNamespace(
            start=__import__("datetime").datetime(2020, 1, 1),
            end=__import__("datetime").datetime(2020, 1, 1),
        ),
        algorithm_params={"orbit_mode": "MWRID", "execute_commands": True},
    )
    runtime = SimpleNamespace(run_id="run-fy-skip", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n-fy-daily",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_FakeArtifactStore(),  # type: ignore[arg-type]
    )


class _Plan:
    metadata: dict = {}

    def __init__(self, output_root: Path) -> None:
        self.date_key = "20200101"
        self.orbit_type = "MWRID"
        self.satellite = "FY3D"
        self.output_dir = str(output_root)
        self.work_dir = str(output_root / "_work" / self.date_key)
        self.output_prefix = f"{self.satellite}_GBAL_L1_10V10H_{self.date_key}_{self.orbit_type}"
        self.input_files = ()


class TestFyDailyMatSkip(unittest.TestCase):
    def test_execute_commands_skips_when_mat_exists(self) -> None:
        from modules.fy import FyDailyModule

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            input_dir = workspace / "in"
            input_dir.mkdir()
            output_dir = workspace / "fy_daily"
            output_dir.mkdir()
            savemat(
                output_dir / "20200101.mat",
                {"TBv": np.zeros((4, 4)), "TBh": np.zeros((4, 4))},
                do_compression=True,
            )
            plan = _Plan(output_dir)
            multiband = Path(plan.work_dir) / "multiband.tif"
            multiband.parent.mkdir(parents=True, exist_ok=True)
            multiband.write_bytes(b"tif")

            def _fake_write_plan_json(plans, output_path):
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("[]", encoding="utf-8")
                return output_path

            def _fake_write_command_json(steps, output_path):
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("[]", encoding="utf-8")
                return output_path

            module = FyDailyModule()
            with (
                patch("modules.fy.build_fy_daily_job_plans", return_value=[plan]),
                patch(
                    "modules.fy.write_fy_daily_plan_json",
                    side_effect=_fake_write_plan_json,
                ),
                patch("modules.fy.build_fy_daily_command_steps", return_value=[]),
                patch(
                    "modules.fy.write_fy_command_plan_json",
                    side_effect=_fake_write_command_json,
                ),
                patch(
                    "modules.fy.get_fy_daily_multiband_output_path",
                    return_value=multiband,
                ),
                patch("modules.fy.execute_fy_command_steps") as mock_exec,
            ):
                module.execute(
                    {
                        "datasource_selection": {"input_dir": str(input_dir)},
                        "algorithm_params": {
                            "orbit_mode": "MWRID",
                            "execute_commands": True,
                        },
                        "output_spec_extra": {"output_dir": str(output_dir)},
                    },
                    {},
                    _ctx(workspace),
                )

            mock_exec.assert_not_called()


if __name__ == "__main__":
    unittest.main()
