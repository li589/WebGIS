from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from data_access.consumers import resolve_prepared_local_path


class DataAccessConsumerTests(unittest.TestCase):
    def test_resolve_prepared_local_path_prefers_matching_resource_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            smap_dir = workspace / "smap"
            ndvi_dir = workspace / "ndvi"
            smap_dir.mkdir()
            ndvi_dir.mkdir()
            datasource_selection = {
                "_prepared_inputs": {
                    "daily_mat_sources": {
                        "materialized_resources": [
                            {
                                "local_path": str(smap_dir),
                                "source_kind": "local_dir",
                                "metadata": {"role": "smap_folder"},
                            },
                            {
                                "local_path": str(ndvi_dir),
                                "source_kind": "local_dir",
                                "metadata": {"role": "ndvi_folder"},
                            },
                        ]
                    }
                }
            }

            resolved = resolve_prepared_local_path(
                datasource_selection,
                ("daily_mat_sources",),
                preferred_resource_keys=("ndvi_folder",),
            )

            self.assertEqual(resolved, ndvi_dir)

    def test_resolve_prepared_local_path_falls_back_to_first_resource_without_metadata_match(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            first_dir = workspace / "first"
            second_dir = workspace / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            datasource_selection = {
                "_prepared_inputs": {
                    "daily_mat_sources": {
                        "materialized_resources": [
                            {
                                "local_path": str(first_dir),
                                "source_kind": "local_dir",
                            },
                            {
                                "local_path": str(second_dir),
                                "source_kind": "local_dir",
                            },
                        ]
                    }
                }
            }

            resolved = resolve_prepared_local_path(
                datasource_selection,
                ("daily_mat_sources",),
                preferred_resource_keys=("missing_role",),
            )

            self.assertEqual(resolved, first_dir)


if __name__ == "__main__":
    unittest.main()
