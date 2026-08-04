"""Smoke tests for data access workflow modules."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace


class _FakeArtifactStore:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}

    def put(self, artifact, payload=None) -> object:
        self.items[artifact.artifact_id] = payload
        return artifact


def _ctx(workspace: Path):
    from workflow.schemas import NodeExecutionContext

    request = SimpleNamespace(
        job_id="job-1",
        datasource_selection={},
        region=None,
        time_range=SimpleNamespace(start="2023-01-01", end="2023-01-02"),
    )
    runtime = SimpleNamespace(run_id="run-1", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n1",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_FakeArtifactStore(),  # type: ignore[arg-type]
    )


class DataAccessNodesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Break known circular import: contracts ↔ workflow via eager contracts.__init__
        import contracts.job  # noqa: F401
        from modules import registry as module_registry

        cls.registry = module_registry

    def test_modules_registered(self) -> None:
        names = set(self.registry.list_modules())
        for name in (
            "remote_fetch",
            "http_open_data",
            "archive_extract",
            "config_read",
            "variable_extract",
            "format_convert",
            "data_source",
            "output_map_layer",
        ):
            self.assertIn(name, names)
            mod = self.registry.get_module(name)
            self.assertTrue(mod.name)

        self.assertEqual(
            self.registry.get_module("preprocess_format_convert").name, "format_convert"
        )

    def test_config_read_and_archive_extract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            cfg = Path(tmp) / "cfg.json"
            cfg.write_text(json.dumps({"alpha": 1}), encoding="utf-8")
            zip_path = Path(tmp) / "a.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("inner.txt", "hello")
                zf.writestr("keep.nc", "netcdf")

            cfg_out = self.registry.get_module("config_read").execute(
                {}, {"path": str(cfg)}, _ctx(workspace)
            )
            self.assertEqual(cfg_out["config"]["alpha"], 1)
            self.assertIn("manifest", cfg_out)

            arc_out = self.registry.get_module("archive_extract").execute(
                {"path": str(zip_path)},
                {"member_glob": "*.nc"},
                _ctx(workspace),
            )
            extract_dir = Path(str(arc_out["extract_dir"]))
            self.assertTrue((extract_dir / "keep.nc").exists())
            self.assertFalse((extract_dir / "inner.txt").exists())

    def test_data_source_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            out = self.registry.get_module("data_source").execute(
                {},
                {"path": "D:/data/SMAP", "dataset_key": "SMAP_L3"},
                _ctx(workspace),
            )
            self.assertEqual(out["data"]["input_dir"], "D:/data/SMAP")
            self.assertEqual(out["path"], "D:/data/SMAP")


if __name__ == "__main__":
    unittest.main()
