from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.result_storage import StoredArtifact


class ArtifactPreviewRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_file = tempfile.NamedTemporaryFile(suffix=".tiff", delete=False)
        self._temp_file.write(b"fake-cog")
        self._temp_file.flush()
        self._temp_file.close()
        self._artifact = StoredArtifact(
            artifact_id="artifact-preview-1",
            file_path=Path(self._temp_file.name),
            mime_type="image/tiff",
            title="Temperature COG",
            content_length=8,
        )
        self._client = TestClient(create_app())

    def tearDown(self) -> None:
        Path(self._temp_file.name).unlink(missing_ok=True)

    def test_preview_route_returns_png_bytes(self) -> None:
        with (
            patch("app.api.routers.artifact_router.result_storage_service.get_artifact", return_value=self._artifact),
            patch("app.api.routers.artifact_router.raster_preview_service.render_cog_preview", return_value=b"png-bytes") as render_mock,
        ):
            response = self._client.get(
                "/artifacts/artifact-preview-1/preview.png",
                params={"palette": "thermal-orange", "width": 512, "height": 256, "min_value": 5, "max_value": 40},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.content, b"png-bytes")
        render_mock.assert_called_once()
        call_kwargs = render_mock.call_args.kwargs
        self.assertEqual(call_kwargs["cog_path"], self._artifact.file_path)
        self.assertEqual(call_kwargs["palette"], "thermal-orange")
        self.assertEqual(call_kwargs["width"], 512)
        self.assertEqual(call_kwargs["height"], 256)
        self.assertEqual(call_kwargs["min_value"], 5)
        self.assertEqual(call_kwargs["max_value"], 40)

    def test_preview_route_rejects_non_tiff_artifacts(self) -> None:
        non_tiff_artifact = StoredArtifact(
            artifact_id="artifact-preview-2",
            file_path=self._artifact.file_path,
            mime_type="application/geo+json",
            title="Temperature GeoJSON",
            content_length=8,
        )
        with patch("app.api.routers.artifact_router.result_storage_service.get_artifact", return_value=non_tiff_artifact):
            response = self._client.get("/artifacts/artifact-preview-2/preview.png")

        self.assertEqual(response.status_code, 400)
        self.assertIn("not a TIFF/COG", response.json()["detail"])

    def test_preview_route_uses_unique_tempfile_for_remote_artifact(self) -> None:
        remote_artifact = StoredArtifact(
            artifact_id="artifact-preview-remote",
            file_path=None,
            mime_type="image/tiff",
            title="Remote Temperature COG",
            content_length=8,
        )
        preview_paths: list[Path] = []

        def _render_preview(*, cog_path: Path, **kwargs) -> bytes:
            self.assertTrue(cog_path.exists())
            self.assertEqual(cog_path.read_bytes(), b"remote-cog")
            preview_paths.append(cog_path)
            return b"png-bytes"

        with (
            patch("app.api.routers.artifact_router.result_storage_service.get_artifact", return_value=remote_artifact),
            patch("app.api.routers.artifact_router.result_storage_service.fetch_artifact_bytes", return_value=b"remote-cog"),
            patch("app.api.routers.artifact_router.raster_preview_service.render_cog_preview", side_effect=_render_preview),
        ):
            first = self._client.get("/artifacts/artifact-preview-remote/preview.png")
            second = self._client.get("/artifacts/artifact-preview-remote/preview.png")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(preview_paths), 2)
        self.assertNotEqual(preview_paths[0], preview_paths[1])
        for preview_path in preview_paths:
            self.assertFalse(preview_path.exists(), f"temp preview file still exists: {preview_path}")


if __name__ == "__main__":
    unittest.main()
