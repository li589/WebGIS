"""Tests for HttpSource auth headers, cache keys, and ETag revalidation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class HttpSourceMaterializeTests(unittest.TestCase):
    def test_applies_http_headers_and_cache_hit(self) -> None:
        from data_access.sources.http import HttpSource, build_http_cache_key

        source = HttpSource()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            uri = "https://example.test/data.bin"
            headers = {"Authorization": "Bearer secret-token"}
            key = build_http_cache_key(uri, headers)
            self.assertIn("_", key)  # header digest suffix

            payload = b"hello-open-data"
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.getcode.return_value = 200
            mock_resp.headers = {
                "ETag": '"abc123"',
                "Last-Modified": "Wed, 01 Jan 2020 00:00:00 GMT",
            }
            mock_resp.read.side_effect = [payload, b""]
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)

            with patch(
                "data_access.sources.http.urlopen", return_value=mock_resp
            ) as urlopen_mock:
                resource = source.locate(uri, metadata={"http_headers": headers})
                out = source.materialize(resource, target_dir=target)
                self.assertTrue(Path(out.local_path).is_file())
                self.assertFalse(out.metadata.get("cache_hit"))
                called_req = urlopen_mock.call_args[0][0]
                self.assertEqual(
                    called_req.headers.get("Authorization"), "Bearer secret-token"
                )

            # Second call should hit cache (no revalidate without needing network if sidecar missing path)
            # With sidecar present, conditional GET may run — mock 304
            mock_304 = MagicMock()
            mock_304.status = 304
            mock_304.getcode.return_value = 304
            mock_304.headers = {}
            mock_304.read.return_value = b""
            mock_304.__enter__ = lambda s: s
            mock_304.__exit__ = MagicMock(return_value=False)

            with patch("data_access.sources.http.urlopen", return_value=mock_304):
                out2 = source.materialize(
                    source.locate(uri, metadata={"http_headers": headers}),
                    target_dir=target,
                )
                self.assertTrue(out2.metadata.get("cache_hit"))

    def test_force_refresh_redownloads(self) -> None:
        from data_access.sources.http import HttpSource

        source = HttpSource()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            uri = "https://example.test/force.bin"
            # seed existing file
            existing = target / "seed.bin"
            # Use materialize once then force
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.getcode.return_value = 200
            mock_resp.headers = {}
            mock_resp.read.side_effect = [b"v1", b"", b"v2", b""]
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)

            with patch("data_access.sources.http.urlopen", return_value=mock_resp):
                r1 = source.materialize(source.locate(uri), target_dir=target)
                self.assertEqual(Path(r1.local_path).read_bytes(), b"v1")
                r2 = source.materialize(
                    source.locate(uri, metadata={"force_refresh": True}),
                    target_dir=target,
                )
                self.assertEqual(Path(r2.local_path).read_bytes(), b"v2")
                self.assertFalse(r2.metadata.get("cache_hit"))


class HttpOpenDataModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import contracts.job  # noqa: F401
        from modules import registry as module_registry

        cls.registry = module_registry

    def test_injects_headers_from_portal_credentials(self) -> None:
        from types import SimpleNamespace
        from workflow.schemas import NodeExecutionContext

        class _Store:
            def put(self, artifact, payload=None):
                return artifact

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            request = SimpleNamespace(
                job_id="j1",
                datasource_selection={
                    "open_data_presets": {"noaa_nomads": "https://example.test/"},
                    "portal_credentials": {
                        "earthdata": {
                            "enabled": True,
                            "auth_type": "bearer",
                            "token": "tok-123",
                        }
                    },
                },
            )
            runtime = SimpleNamespace(run_id="r1", workspace=str(workspace))
            ctx = NodeExecutionContext(
                workflow_id="wf",
                node_id="n1",
                request=request,  # type: ignore[arg-type]
                runtime_context=runtime,  # type: ignore[arg-type]
                workspace=workspace,
                artifact_store=_Store(),  # type: ignore[arg-type]
            )

            captured = {}

            def fake_materialize(self, resource, *, target_dir=None):
                captured["headers"] = dict(
                    (resource.metadata or {}).get("http_headers") or {}
                )
                path = Path(target_dir or workspace) / "out.bin"
                path.write_bytes(b"x")
                from data_access.contracts import build_resource_ref

                return build_resource_ref(
                    uri=path.as_uri(),
                    source_kind="online",
                    storage_backend="local",
                    local_path=str(path),
                    metadata={"cache_hit": False, "local_path": str(path)},
                )

            with patch(
                "data_access.sources.http.HttpSource.materialize", fake_materialize
            ):
                out = self.registry.get_module("http_open_data").execute(
                    {},
                    {
                        "preset": "noaa_nomads",
                        "relative_path": "file.bin",
                        "cred_profile": "earthdata",
                    },
                    ctx,
                )
            self.assertIn("path", out)
            self.assertTrue(str(out.get("url", "")).endswith("file.bin"))
            self.assertEqual(captured["headers"].get("Authorization"), "Bearer tok-123")


class ArchiveExtractEnhancementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import contracts.job  # noqa: F401
        from modules import registry as module_registry

        cls.registry = module_registry

    def test_member_glob_and_safe_root(self) -> None:
        import zipfile
        from types import SimpleNamespace
        from workflow.schemas import NodeExecutionContext

        class _Store:
            def put(self, artifact, payload=None):
                return artifact

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            zip_path = Path(tmp) / "prod.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("skip.txt", "no")
                zf.writestr("scene.SAFE/manifest.safe", "ok")
                zf.writestr("scene.SAFE/data.h5", "h5")

            request = SimpleNamespace(job_id="j1", datasource_selection={})
            runtime = SimpleNamespace(run_id="r1", workspace=str(workspace))
            ctx = NodeExecutionContext(
                workflow_id="wf",
                node_id="arc",
                request=request,  # type: ignore[arg-type]
                runtime_context=runtime,  # type: ignore[arg-type]
                workspace=workspace,
                artifact_store=_Store(),  # type: ignore[arg-type]
            )
            out = self.registry.get_module("archive_extract").execute(
                {"path": str(zip_path)},
                {"member_glob": "*.SAFE/*", "recurse_once": False},
                ctx,
            )
            result_path = Path(str(out["path"]))
            self.assertTrue(
                result_path.name.endswith(".SAFE") or "SAFE" in result_path.name
            )

    def test_rejects_zip_slip_member(self) -> None:
        import zipfile
        from types import SimpleNamespace
        from workflow.schemas import NodeExecutionContext

        class _Store:
            def put(self, artifact, payload=None):
                return artifact

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            zip_path = Path(tmp) / "evil.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("../outside.txt", "pwned")

            request = SimpleNamespace(job_id="j1", datasource_selection={})
            runtime = SimpleNamespace(run_id="r1", workspace=str(workspace))
            ctx = NodeExecutionContext(
                workflow_id="wf",
                node_id="arc",
                request=request,  # type: ignore[arg-type]
                runtime_context=runtime,  # type: ignore[arg-type]
                workspace=workspace,
                artifact_store=_Store(),  # type: ignore[arg-type]
            )
            with self.assertRaises(ValueError) as raised:
                self.registry.get_module("archive_extract").execute(
                    {"path": str(zip_path)},
                    {"recurse_once": False},
                    ctx,
                )
            self.assertIn("unsafe archive member", str(raised.exception).lower())
            self.assertFalse((Path(tmp) / "outside.txt").exists())

    def test_lazy_portal_resolve_without_embedded_secrets(self) -> None:
        from types import SimpleNamespace
        from workflow.schemas import NodeExecutionContext

        class _Store:
            def put(self, artifact, payload=None):
                return artifact

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            request = SimpleNamespace(
                job_id="j1",
                datasource_selection={
                    "open_data_presets": {"noaa_nomads": "https://example.test/"},
                    "portal_credentials_resolve": True,
                },
            )
            runtime = SimpleNamespace(run_id="r1", workspace=str(workspace))
            ctx = NodeExecutionContext(
                workflow_id="wf",
                node_id="n1",
                request=request,  # type: ignore[arg-type]
                runtime_context=runtime,  # type: ignore[arg-type]
                workspace=workspace,
                artifact_store=_Store(),  # type: ignore[arg-type]
            )
            captured: dict[str, object] = {}

            def fake_materialize(self, resource, *, target_dir=None):
                captured["headers"] = dict(
                    (resource.metadata or {}).get("http_headers") or {}
                )
                path = Path(target_dir or workspace) / "out.bin"
                path.write_bytes(b"x")
                from data_access.contracts import build_resource_ref

                return build_resource_ref(
                    uri=path.as_uri(),
                    source_kind="online",
                    storage_backend="local",
                    local_path=str(path),
                    metadata={"cache_hit": False, "local_path": str(path)},
                )

            with (
                patch(
                    "data_access.sources.http.HttpSource.materialize",
                    fake_materialize,
                ),
                patch(
                    "app.services.config_service.get_portal_credentials_runtime",
                    return_value={
                        "earthdata": {
                            "enabled": True,
                            "auth_type": "bearer",
                            "token": "lazy-tok",
                        }
                    },
                ),
            ):
                self.registry.get_module("http_open_data").execute(
                    {},
                    {
                        "preset": "noaa_nomads",
                        "relative_path": "file.bin",
                        "cred_profile": "earthdata",
                    },
                    ctx,
                )
            self.assertEqual(
                captured["headers"].get("Authorization"), "Bearer lazy-tok"
            )


class OpenDataPresetsTests(unittest.TestCase):
    def test_default_presets_include_nsidc_and_esa_download(self) -> None:
        from app.services.data_cache_service import DEFAULT_OPEN_DATA_PRESETS

        for key in (
            "noaa_nomads",
            "nasa_earthdata",
            "nasa_cmr",
            "nsidc_data",
            "esa_copernicus",
            "esa_download",
        ):
            self.assertIn(key, DEFAULT_OPEN_DATA_PRESETS)


class PortalCredentialsTests(unittest.TestCase):
    def test_upsert_masks_secrets(self) -> None:
        from app.services.portal_credentials import (
            public_portal_credentials,
            upsert_portal_credential,
        )
        from app.services.research_data_settings_repository import (
            ResearchDataSettingsRepository,
        )

        with tempfile.TemporaryDirectory() as tmp:
            repo = ResearchDataSettingsRepository(Path(tmp) / "settings.sqlite3")
            try:
                public = upsert_portal_credential(
                    repo=repo,
                    encryption_key="",
                    portal_id="earthdata",
                    payload={
                        "enabled": True,
                        "auth_type": "bearer",
                        "token": "super-secret-token",
                    },
                )
                self.assertTrue(public["earthdata"]["has_token"])
                self.assertNotIn("token", public["earthdata"])
                masked = public_portal_credentials(repo=repo, encryption_key="")
                self.assertTrue(masked["earthdata"]["has_token"])
            finally:
                repo.close()


class WorkflowSeedSyncTests(unittest.TestCase):
    def test_seeds_copied_on_ensure(self) -> None:
        from app.services import workflow_definition_service as wds

        wds._ensure_dirs()
        ids = {item["workflow_id"] for item in wds.list_definitions()}
        for wid in (
            "open_data_noaa_grib_sample",
            "open_data_nsidc_smap_sample",
            "open_data_nasa_earthdata_sample",
            "open_data_esa_product_sample",
            "smap_soil_moisture_local",
        ):
            self.assertIn(wid, ids)


if __name__ == "__main__":
    unittest.main()
