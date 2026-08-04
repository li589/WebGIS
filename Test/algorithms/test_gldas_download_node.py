"""GLDAS 在线下载节点：注册与 dry_run 执行。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class _FakeArtifactStore:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}

    def put(self, artifact, payload=None) -> object:
        self.items[artifact.artifact_id] = payload
        return artifact


def _ctx(workspace: Path):
    from workflow.schemas import NodeExecutionContext

    request = SimpleNamespace(
        job_id="job-gldas-1",
        datasource_selection={},
        region=None,
        time_range=None,
    )
    runtime = SimpleNamespace(run_id="run-gldas-1", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n1",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_FakeArtifactStore(),  # type: ignore[arg-type]
    )


class TestGldasDownloadNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import contracts.job  # noqa: F401
        from modules import registry as module_registry

        cls.registry = module_registry

    def test_module_registered(self) -> None:
        names = set(self.registry.list_modules())
        self.assertIn("gldas_download", names)
        module = self.registry.get_module("gldas_download")
        self.assertEqual(module.name, "gldas_download")
        self.assertTrue(any(p.name == "path" for p in module.output_ports))

    def test_dry_run_execute_writes_path_manifest(self) -> None:
        from ingest.nsidc_download import DownloadResult, Granule

        module = self.registry.get_module("gldas_download")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            local_dir = Path(tmp) / "gldas"
            local_dir.mkdir()
            fake = DownloadResult(
                total_granules=2,
                downloaded=0,
                skipped=0,
                failed=0,
                local_dir=str(local_dir),
                granules=[
                    Granule(name="a.nc4", url="https://example.test/a.nc4"),
                    Granule(name="b.nc4", url="https://example.test/b.nc4"),
                ],
            )
            with patch(
                "ingest.gldas_download.download_gldas_range", return_value=fake
            ) as mocked:
                out = module.execute(
                    inputs={},
                    params={
                        "start_date": "20251227",
                        "end_date": "20251228",
                        "local_dir": str(local_dir),
                        "dry_run": True,
                        "max_files": 2,
                    },
                    ctx=_ctx(workspace),
                )
            mocked.assert_called_once()
            self.assertEqual(out["path"], str(local_dir))
            self.assertIn("manifest", out)


if __name__ == "__main__":
    unittest.main()
