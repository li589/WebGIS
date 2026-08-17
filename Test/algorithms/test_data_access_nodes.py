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

    def test_archive_extract_passthrough_restores_url_basename(self) -> None:
        """CMR 直下的裸 .h5：透传复制，并按 URL 恢复原始文件名（缓存名为 sha256）。"""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            cached = Path(tmp) / "deadbeefcafe0123456789ab.h5"
            cached.write_bytes(b"hdf5-bytes")

            out = self.registry.get_module("archive_extract").execute(
                {
                    "path": str(cached),
                    "url": (
                        "https://data.laadsdaac.earthdatacloud.nasa.gov/"
                        "laads/allData/VNP13C1.002/2025/161/"
                        "VNP13C1.A2025161.002.2025210032044.h5"
                    ),
                },
                {"output_dirname": "ndvi_extracted", "member_glob": "*.h5"},
                _ctx(workspace),
            )
            extract_dir = Path(str(out["extract_dir"]))
            restored = extract_dir / "VNP13C1.A2025161.002.2025210032044.h5"
            self.assertTrue(restored.exists())
            self.assertEqual(restored.read_bytes(), b"hdf5-bytes")

    def test_archive_extract_passthrough_without_url_keeps_cache_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            cached = Path(tmp) / "cafe0123456789ab.nc"
            cached.write_bytes(b"nc-bytes")

            out = self.registry.get_module("archive_extract").execute(
                {"path": str(cached)}, {}, _ctx(workspace)
            )
            extract_dir = Path(str(out["extract_dir"]))
            self.assertTrue((extract_dir / "cafe0123456789ab.nc").exists())

    def test_archive_extract_passthrough_glob_mismatch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            cached = Path(tmp) / "cafe0123456789ab.h5"
            cached.write_bytes(b"hdf5-bytes")

            with self.assertRaises(FileNotFoundError):
                self.registry.get_module("archive_extract").execute(
                    {"path": str(cached)},
                    {"member_glob": "*.hdf"},
                    _ctx(workspace),
                )

    def test_archive_extract_still_refuses_7z(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            archived = Path(tmp) / "a.7z"
            archived.write_bytes(b"fake-7z")

            with self.assertRaises(ValueError):
                self.registry.get_module("archive_extract").execute(
                    {"path": str(archived)}, {}, _ctx(workspace)
                )

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

    def test_output_map_layer_accepts_manifest_on_data_port(self) -> None:
        """Seeds wire module.manifest → map_layer.data (single LiteGraph slot)."""
        from workflow.schemas import ArtifactRef

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            upstream = ArtifactRef(
                artifact_id="run:n4:manifest",
                artifact_type="product_manifest",
                format="python_object",
                uri=None,
                producer_node_id="n4",
                schema_name="ProductManifest",
                metadata={"module_name": "omega_sf_fenkuai"},
            )
            out = self.registry.get_module("output_map_layer").execute(
                {"data": upstream},
                {"layer_id": "method-smap-omega-doy-dynamic", "display_name": "SF"},
                _ctx(workspace),
            )
            self.assertIs(out["manifest"], upstream)
            self.assertEqual(out["map_layer"]["source"], "upstream_manifest")
            self.assertEqual(
                out["map_layer"]["layer_id"], "method-smap-omega-doy-dynamic"
            )


class TestResolvePortalEntry(unittest.TestCase):
    """门户凭证统一解析：内联优先、禁用返回空、无回退标记不触达后端。"""

    def test_inline_credentials_win(self) -> None:
        from modules.download_nodes import _resolve_portal_entry

        entry = _resolve_portal_entry(
            {"portal_credentials": {"nsmc": {"token": "t1"}}}, "nsmc"
        )
        self.assertEqual(entry, {"token": "t1"})

    def test_disabled_entry_returns_empty(self) -> None:
        from modules.download_nodes import _resolve_portal_entry

        entry = _resolve_portal_entry(
            {"portal_credentials": {"nsmc": {"token": "t", "enabled": False}}},
            "nsmc",
        )
        self.assertEqual(entry, {})

    def test_missing_key_returns_empty(self) -> None:
        from modules.download_nodes import _resolve_portal_entry

        self.assertEqual(_resolve_portal_entry({}, "nsmc"), {})

    def test_no_resolve_flag_no_backend_import(self) -> None:
        import sys

        from modules.download_nodes import _resolve_portal_entry

        # 无 portal_credentials_resolve 标记时不 import app.services（算法包可独立运行）
        before = set(sys.modules)
        _resolve_portal_entry({"portal_credentials": {}}, "nsmc")
        new = set(sys.modules) - before
        self.assertFalse(
            [m for m in new if m.startswith("app.")],
            f"unexpected backend import: {sorted(m for m in new if m.startswith('app.'))}",
        )


if __name__ == "__main__":
    unittest.main()
