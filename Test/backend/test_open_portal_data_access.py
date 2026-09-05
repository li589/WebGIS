"""Tests for HttpSource auth headers, cache keys, and ETag revalidation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import tempfile
from unittest.mock import MagicMock, patch

# 补齐算法包根目录到 sys.path，确保 data_access / modules / path_utils 等模块可导入。
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PROVIDER = _REPO_ROOT / "Code" / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _REPO_ROOT / "Code"):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


def test_applies_http_headers_and_cache_hit() -> None:
    from data_access.sources.http import HttpSource, build_http_cache_key

    source = HttpSource()
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        uri = "https://example.test/data.bin"
        headers = {"Authorization": "Bearer secret-token"}
        key = build_http_cache_key(uri, headers)
        assert "_" in key, '"_" in key'  # header digest suffix

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
            "urllib.request.OpenerDirector.open", return_value=mock_resp
        ) as urlopen_mock:
            resource = source.locate(uri, metadata={"http_headers": headers})
            out = source.materialize(resource, target_dir=target)
            assert Path(out.local_path).is_file(), 'Path(out.local_path).is_file() is truthy'
            assert not out.metadata.get("cache_hit"), 'out.metadata.get("cache_hit") is falsy'
            called_req = urlopen_mock.call_args[0][0]
            assert called_req.headers.get("Authorization") == "Bearer secret-token", 'called_req.headers.get("Authorization") == "Bearer secret-token"'

        # Second call should hit cache (no revalidate without needing network if sidecar missing path)
        # With sidecar present, conditional GET may run — mock 304
        mock_304 = MagicMock()
        mock_304.status = 304
        mock_304.getcode.return_value = 304
        mock_304.headers = {}
        mock_304.read.return_value = b""
        mock_304.__enter__ = lambda s: s
        mock_304.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.OpenerDirector.open", return_value=mock_304):
            out2 = source.materialize(
                source.locate(uri, metadata={"http_headers": headers}),
                target_dir=target,
            )
            assert out2.metadata.get("cache_hit"), 'out2.metadata.get("cache_hit") is truthy'


def test_force_refresh_redownloads() -> None:
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

        with patch("urllib.request.OpenerDirector.open", return_value=mock_resp):
            r1 = source.materialize(source.locate(uri), target_dir=target)
            assert Path(r1.local_path).read_bytes() == b"v1", 'Path(r1.local_path).read_bytes() == b"v1"'
            r2 = source.materialize(
                source.locate(uri, metadata={"force_refresh": True}),
                target_dir=target,
            )
            assert Path(r2.local_path).read_bytes() == b"v2", 'Path(r2.local_path).read_bytes() == b"v2"'
            assert not r2.metadata.get("cache_hit"), 'r2.metadata.get("cache_hit") is falsy'


def test_injects_headers_from_portal_credentials() -> None:
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

        def fake_materialize(_self, resource, *, target_dir=None):
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
            from modules.registry import get_module

            out = get_module("http_open_data").execute(
                {},
                {
                    "preset": "noaa_nomads",
                    "relative_path": "file.bin",
                    "cred_profile": "earthdata",
                },
                ctx,
            )
        assert "path" in out, '"path" in out'
        assert str(out.get("url", "")).endswith("file.bin"), 'str(out.get("url", "")).endswith("file.bin") is truthy'
        assert captured["headers"].get("Authorization") == "Bearer tok-123", 'captured["headers"].get("Authorization") == "Bearer tok-123"'


def test_member_glob_and_safe_root() -> None:
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
        from modules.registry import get_module

        out = get_module("archive_extract").execute(
            {"path": str(zip_path)},
            {"member_glob": "*.SAFE/*", "recurse_once": False},
            ctx,
        )
        result_path = Path(str(out["path"]))
        assert result_path.name.endswith(".SAFE") or "SAFE" in result_path.name, 'result_path.name.endswith(".SAFE") or "SAFE" in result_path.name is truthy'


def test_rejects_zip_slip_member() -> None:
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
        with pytest.raises(ValueError) as raised:
            from modules.registry import get_module

            get_module("archive_extract").execute(
                {"path": str(zip_path)},
                {"recurse_once": False},
                ctx,
            )
        assert "unsafe archive member" in str(raised.value).lower(), '"unsafe archive member" in str(raised.exception).lower()'
        assert not (Path(tmp) / "outside.txt").exists(), '(Path(tmp) / "outside.txt").exists() is falsy'


def test_lazy_portal_resolve_without_embedded_secrets() -> None:
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

        def fake_materialize(_self, resource, *, target_dir=None):
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
            from modules.registry import get_module

            get_module("http_open_data").execute(
                {},
                {
                    "preset": "noaa_nomads",
                    "relative_path": "file.bin",
                    "cred_profile": "earthdata",
                },
                ctx,
            )
        assert captured["headers"].get("Authorization") == "Bearer lazy-tok", 'captured["headers"].get("Authorization") == "Bearer lazy-tok"'


def test_default_presets_include_nsidc_and_esa_download() -> None:
    from app.services.data_cache_service import DEFAULT_OPEN_DATA_PRESETS

    for key in (
        "noaa_nomads",
        "nasa_earthdata",
        "nasa_cmr",
        "nsidc_data",
        "esa_copernicus",
        "esa_download",
    ):
        assert key in DEFAULT_OPEN_DATA_PRESETS, 'key in DEFAULT_OPEN_DATA_PRESETS'


def test_upsert_masks_secrets() -> None:
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
            assert public["earthdata"]["has_token"], 'public["earthdata"]["has_token"] is truthy'
            assert "token" not in public["earthdata"], '"token" not in public["earthdata"]'
            masked = public_portal_credentials(repo=repo, encryption_key="")
            assert masked["earthdata"]["has_token"], 'masked["earthdata"]["has_token"] is truthy'
        finally:
            repo.close()


def test_seeds_copied_on_ensure() -> None:
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
        assert wid in ids, 'wid in ids'


# ─── P2e：http_open_data earthaccess 默认化 ──────────────────────────────────


def _open_data_ctx(tmp: str, datasource_selection: dict):
    from types import SimpleNamespace
    from workflow.schemas import NodeExecutionContext

    class _Store:
        def put(self, artifact, payload=None):
            return artifact

    workspace = Path(tmp)
    request = SimpleNamespace(
        job_id="j-ea",
        datasource_selection=datasource_selection,
    )
    runtime = SimpleNamespace(run_id="r-ea", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n1",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_Store(),  # type: ignore[arg-type]
    )


def _fake_legacy_materialize(tmp: str):
    """HttpSource.materialize 桩：记录调用并落文件。"""
    captured = {"called": False}

    def fake_materialize(_self, resource, *, target_dir=None):
        captured["called"] = True
        path = Path(target_dir or tmp) / "out.bin"
        path.write_bytes(b"x")
        from data_access.contracts import build_resource_ref

        return build_resource_ref(
            uri=path.as_uri(),
            source_kind="online",
            storage_backend="local",
            local_path=str(path),
            metadata={"cache_hit": False, "local_path": str(path)},
        )

    return fake_materialize, captured


_EA_FAMILY_DS = {
    "open_data_presets": {
        "nasa_earthdata": "https://data.lpdaac.earthdatacloud.nasa.gov/"
    },
    "portal_credentials": {
        "earthdata": {
            "enabled": True,
            "auth_type": "basic",
            "username": "u",
            "password": "p",
        }
    },
}


def test_http_open_data_auto_earthaccess_when_family_and_creds() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with (
            patch(
                "modules.data_access_nodes._earthaccess_credentials_available",
                return_value=True,
            ),
            patch(
                "modules.data_access_nodes._materialize_via_earthaccess"
            ) as ea_mock,
        ):
            ea_mock.return_value = Path(tmp) / "ea.bin"
            from modules.registry import get_module

            out = get_module("http_open_data").execute(
                {},
                {
                    "preset": "nasa_earthdata",
                    "relative_path": "file.hdf",
                },
                _open_data_ctx(tmp, _EA_FAMILY_DS),
            )
        ea_mock.assert_called_once()
        assert "path" in out, '"path" in out'


def test_http_open_data_auto_legacy_without_credentials() -> None:
    fake, captured = _fake_legacy_materialize("legacynocreds")
    with tempfile.TemporaryDirectory() as tmp:
        with (
            patch(
                "modules.data_access_nodes._earthaccess_credentials_available",
                return_value=False,
            ),
            patch(
                "modules.data_access_nodes._materialize_via_earthaccess"
            ) as ea_mock,
            patch("data_access.sources.http.HttpSource.materialize", fake),
        ):
            from modules.registry import get_module

            get_module("http_open_data").execute(
                {},
                {"preset": "nasa_earthdata", "relative_path": "file.hdf"},
                _open_data_ctx(tmp, _EA_FAMILY_DS),
            )
        ea_mock.assert_not_called()
        assert captured["called"], 'captured["called"] is truthy'


def test_http_open_data_use_legacy_forced_overrides_default() -> None:
    fake, captured = _fake_legacy_materialize("legacyforced")
    with tempfile.TemporaryDirectory() as tmp:
        with (
            patch(
                "modules.data_access_nodes._earthaccess_credentials_available",
                return_value=True,
            ),
            patch(
                "modules.data_access_nodes._materialize_via_earthaccess"
            ) as ea_mock,
            patch("data_access.sources.http.HttpSource.materialize", fake),
        ):
            from modules.registry import get_module

            get_module("http_open_data").execute(
                {},
                {
                    "preset": "nasa_earthdata",
                    "relative_path": "file.hdf",
                    "use": "legacy",
                },
                _open_data_ctx(tmp, _EA_FAMILY_DS),
            )
        ea_mock.assert_not_called()
        assert captured["called"], 'captured["called"] is truthy'


def test_http_open_data_use_earthaccess_without_install_raises() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with patch(
            "modules.data_access_nodes._earthaccess_available",
            return_value=False,
        ):
            from modules.registry import get_module

            with pytest.raises(RuntimeError, match="earthaccess"):
                get_module("http_open_data").execute(
                    {},
                    {
                        "preset": "nasa_earthdata",
                        "relative_path": "file.hdf",
                        "use": "earthaccess",
                    },
                    _open_data_ctx(tmp, _EA_FAMILY_DS),
                )


def test_http_open_data_invalid_use_raises() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        from modules.registry import get_module

        with pytest.raises(ValueError, match="invalid use"):
            get_module("http_open_data").execute(
                {},
                {
                    "preset": "nasa_earthdata",
                    "relative_path": "file.hdf",
                    "use": "bogus",
                },
                _open_data_ctx(tmp, _EA_FAMILY_DS),
            )
