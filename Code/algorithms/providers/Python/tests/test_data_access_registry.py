from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from data_access.contracts import DataRequestV2, build_prepared_input
from data_access.registry import build_default_source_registry


class DataAccessRegistryTests(unittest.TestCase):
    def test_default_registry_registers_expected_sources(self) -> None:
        registry = build_default_source_registry()

        self.assertEqual(
            registry.registered_names(),
            ("cache", "http", "local_fs", "minio", "remote"),
        )
        self.assertEqual(
            registry.registered_schemes(),
            (
                "cache",
                "file",
                "ftp",
                "ftps",
                "gcs",
                "gs",
                "http",
                "https",
                "local",
                "minio",
                "s3",
                "sftp",
                "smb",
            ),
        )

    def test_registry_locates_local_file_and_materializes_it(self) -> None:
        registry = build_default_source_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            local_file = Path(tmp_dir) / "input.mat"
            local_file.write_text("content", encoding="utf-8")

            resource = registry.locate(
                str(local_file), request=DataRequestV2(dataset_name="demo")
            )
            materialized = registry.materialize(resource)

            self.assertEqual(resource.source_kind, "local_file")
            self.assertEqual(resource.format, "mat")
            self.assertEqual(resource.logical_type, "array")
            self.assertEqual(materialized.local_path, str(local_file.resolve()))

    def test_registry_routes_http_minio_and_cache_uris(self) -> None:
        registry = build_default_source_registry()

        http_resource = registry.locate("https://example.com/data/test.json")
        minio_resource = registry.locate("minio://bucket-a/path/to/file.nc")
        cache_resource = registry.locate(
            "cache://prepared/demo.csv", metadata={"local_path": "C:/cache/demo.csv"}
        )

        self.assertEqual(http_resource.source_kind, "online")
        self.assertEqual(http_resource.storage_backend, "https")
        self.assertEqual(minio_resource.source_kind, "object_storage")
        self.assertEqual(minio_resource.bucket, "bucket-a")
        self.assertEqual(minio_resource.object_key, "path/to/file.nc")
        self.assertEqual(cache_resource.source_kind, "cache")
        self.assertEqual(cache_resource.metadata["cache_key"], "prepared/demo.csv")

    def test_prepared_input_keeps_structured_resources(self) -> None:
        registry = build_default_source_registry()
        resources = (
            registry.locate("https://example.com/data/test.json"),
            registry.locate("minio://bucket-a/path/to/file.nc"),
        )

        prepared = build_prepared_input(
            DataRequestV2(dataset_name="demo", variables=("tbv",)),
            resources=resources,
            materialized_resources=(),
            warnings=("deferred materialization",),
        )

        self.assertEqual(prepared.request.dataset_name, "demo")
        self.assertEqual(len(prepared.resources), 2)
        self.assertEqual(prepared.warnings, ("deferred materialization",))
        self.assertEqual(prepared.resources[0].storage_backend, "https")
        self.assertEqual(prepared.resources[1].bucket, "bucket-a")


if __name__ == "__main__":
    unittest.main()
