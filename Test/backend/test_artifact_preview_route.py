from __future__ import annotations

import pytest
import types
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.result_storage import StoredArtifact


@pytest.fixture
def _artifact_preview_route_tests_env():
    ns = types.SimpleNamespace()
    ns._temp_file = tempfile.NamedTemporaryFile(suffix=".tiff", delete=False)
    ns._temp_file.write(b"fake-cog")
    ns._temp_file.flush()
    ns._temp_file.close()
    ns._artifact = StoredArtifact(
        artifact_id="artifact-preview-1",
        file_path=Path(ns._temp_file.name),
        mime_type="image/tiff",
        title="Temperature COG",
        content_length=8,
    )
    auth_patch = patch("app.api.routers.artifact_router._deny_if_unauthenticated")
    auth_patch.start()
    ns._client = TestClient(create_app())
    yield ns
    auth_patch.stop()
    Path(ns._temp_file.name).unlink(missing_ok=True)


def test_preview_route_returns_png_bytes(_artifact_preview_route_tests_env) -> None:
    self = _artifact_preview_route_tests_env
    with (
        patch(
            "app.api.routers.artifact_router.result_storage_service.get_artifact",
            return_value=self._artifact,
        ),
        patch(
            "app.api.routers.artifact_router.raster_preview_service.render_cog_preview",
            return_value=b"png-bytes",
        ) as render_mock,
    ):
        response = self._client.get(
            "/artifacts/artifact-preview-1/preview.png",
            params={
                "palette": "thermal-orange",
                "width": 512,
                "height": 256,
                "min_value": 5,
                "max_value": 40,
            },
        )

    assert response.status_code == 200, 'response.status_code == 200'
    assert response.headers["content-type"] == "image/png", 'response.headers["content-type"] == "image/png"'
    assert response.content == b"png-bytes", 'response.content == b"png-bytes"'
    render_mock.assert_called_once()
    call_kwargs = render_mock.call_args.kwargs
    assert call_kwargs["cog_path"] == self._artifact.file_path, 'call_kwargs["cog_path"] == self._artifact.file_path'
    assert call_kwargs["palette"] == "thermal-orange", 'call_kwargs["palette"] == "thermal-orange"'
    assert call_kwargs["width"] == 512, 'call_kwargs["width"] == 512'
    assert call_kwargs["height"] == 256, 'call_kwargs["height"] == 256'
    assert call_kwargs["min_value"] == 5, 'call_kwargs["min_value"] == 5'
    assert call_kwargs["max_value"] == 40, 'call_kwargs["max_value"] == 40'


def test_preview_route_rejects_non_tiff_artifacts(_artifact_preview_route_tests_env) -> None:
    self = _artifact_preview_route_tests_env
    non_tiff_artifact = StoredArtifact(
        artifact_id="artifact-preview-2",
        file_path=self._artifact.file_path,
        mime_type="application/geo+json",
        title="Temperature GeoJSON",
        content_length=8,
    )
    with patch(
        "app.api.routers.artifact_router.result_storage_service.get_artifact",
        return_value=non_tiff_artifact,
    ):
        response = self._client.get("/artifacts/artifact-preview-2/preview.png")

    assert response.status_code == 400, 'response.status_code == 400'
    assert "not a TIFF/COG" in response.json()["detail"], '"not a TIFF/COG" in response.json()["detail"]'


def test_preview_route_uses_unique_tempfile_for_remote_artifact(_artifact_preview_route_tests_env) -> None:
    self = _artifact_preview_route_tests_env
    remote_artifact = StoredArtifact(
        artifact_id="artifact-preview-remote",
        file_path=None,
        mime_type="image/tiff",
        title="Remote Temperature COG",
        content_length=8,
    )
    preview_paths: list[Path] = []

    def _render_preview(*, cog_path: Path, **kwargs) -> bytes:
        assert cog_path.exists(), 'cog_path.exists() is truthy'
        assert cog_path.read_bytes() == b"remote-cog", 'cog_path.read_bytes() == b"remote-cog"'
        preview_paths.append(cog_path)
        return b"png-bytes"

    with (
        patch(
            "app.api.routers.artifact_router.result_storage_service.get_artifact",
            return_value=remote_artifact,
        ),
        patch(
            "app.api.routers.artifact_router.result_storage_service.fetch_artifact_bytes",
            return_value=b"remote-cog",
        ),
        patch(
            "app.api.routers.artifact_router.raster_preview_service.render_cog_preview",
            side_effect=_render_preview,
        ),
    ):
        first = self._client.get("/artifacts/artifact-preview-remote/preview.png")
        second = self._client.get("/artifacts/artifact-preview-remote/preview.png")

    assert first.status_code == 200, 'first.status_code == 200'
    assert second.status_code == 200, 'second.status_code == 200'
    assert len(preview_paths) == 2, 'len(preview_paths) == 2'
    assert preview_paths[0] != preview_paths[1], 'preview_paths[0] != preview_paths[1]'
    for preview_path in preview_paths:
        assert not preview_path.exists(), f"temp preview file still exists: {preview_path}"
