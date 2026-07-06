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
            patch("app.api.routes.result_storage_service.get_artifact", return_value=self._artifact),
            patch("app.api.routes.raster_preview_service.render_cog_preview", return_value=b"png-bytes") as render_mock,
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
        with patch("app.api.routes.result_storage_service.get_artifact", return_value=non_tiff_artifact):
            response = self._client.get("/artifacts/artifact-preview-2/preview.png")

        self.assertEqual(response.status_code, 400)
        self.assertIn("not a TIFF/COG", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
