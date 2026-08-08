from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import struct
import zipfile

import h5py
import numpy as np
import rasterio
from netCDF4 import Dataset
from rasterio.transform import from_origin
from scipy.io import savemat

from data_access import build_default_format_registry, build_resource_ref


def _write_minimal_xlsx(path: Path) -> None:
    workbook_xml = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheets>
    <sheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" name="Stations" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""
    worksheet_xml = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>site_id</t></is></c>
      <c r="B1" t="inlineStr"><is><t>network_id</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>A</t></is></c>
      <c r="B2" t="inlineStr"><is><t>NET1</t></is></c>
    </row>
    <row r="3">
      <c r="A3" t="inlineStr"><is><t>B</t></is></c>
      <c r="B3" t="inlineStr"><is><t>NET2</t></is></c>
    </row>
  </sheetData>
</worksheet>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)


def _write_minimal_netcdf(path: Path) -> None:
    with Dataset(path, "w") as dataset:
        dataset.createDimension("x", 2)
        dataset.createDimension("y", 3)
        variable = dataset.createVariable("tb", "f4", ("x", "y"))
        variable[:, :] = np.arange(6, dtype=np.float32).reshape(2, 3)


def _write_minimal_tiff(path: Path) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=3,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(10.0, 20.0, 1.0, 1.0),
    ) as dataset:
        dataset.write(np.arange(6, dtype=np.float32).reshape(1, 2, 3))


def _write_minimal_shapefile(path: Path) -> None:
    shp_header = bytearray(100)
    struct.pack_into(">i", shp_header, 0, 9994)
    struct.pack_into(">i", shp_header, 24, 50)
    struct.pack_into("<i", shp_header, 28, 1000)
    struct.pack_into("<i", shp_header, 32, 1)
    struct.pack_into("<4d", shp_header, 36, 10.0, 20.0, 10.0, 20.0)
    path.write_bytes(bytes(shp_header))
    dbf_header = bytearray(32)
    dbf_header[0] = 0x03
    struct.pack_into("<I", dbf_header, 4, 2)
    struct.pack_into("<H", dbf_header, 8, 33)
    struct.pack_into("<H", dbf_header, 10, 1)
    path.with_suffix(".dbf").write_bytes(bytes(dbf_header) + b"\r")


class DataAccessFormatAdapterTests(unittest.TestCase):
    def test_default_format_registry_registers_expected_adapters(self) -> None:
        registry = build_default_format_registry()

        self.assertEqual(
            registry.registered_names(),
            (
                "csv",
                "excel",
                "hdf5",
                "json",
                "mat",
                "netcdf",
                "shapefile",
                "text",
                "tiff",
                "xml",
            ),
        )
        self.assertEqual(
            registry.registered_formats(),
            (
                "csv",
                "excel",
                "h5",
                "hdf",
                "json",
                "mat",
                "nc",
                "shp",
                "tif",
                "tiff",
                "txt",
                "xml",
            ),
        )

    def test_text_adapter_probes_loads_and_materializes(self) -> None:
        registry = build_default_format_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_path = root / "notes.txt"
            source_path.write_text("line-1\nline-2\n", encoding="utf-8")
            resource = build_resource_ref(str(source_path))

            self.assertTrue(registry.probe(resource))
            loaded = registry.load(resource)
            materialized = registry.materialize(
                resource, target_dir=root / "materialized"
            )

            self.assertEqual(loaded["text"], "line-1\nline-2\n")
            self.assertEqual(loaded["lines"], ("line-1", "line-2"))
            self.assertTrue(Path(materialized.local_path).exists())
            self.assertEqual(Path(materialized.local_path).name, "notes.txt")

    def test_csv_adapter_loads_headers_and_rows(self) -> None:
        registry = build_default_format_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "stations.csv"
            source_path.write_text(
                "site_id,network_id\nA,NET1\nB,NET2\n", encoding="utf-8"
            )
            resource = build_resource_ref(str(source_path))

            loaded = registry.load(resource)

            self.assertEqual(loaded["headers"], ("site_id", "network_id"))
            self.assertEqual(
                loaded["rows"],
                (
                    {"site_id": "A", "network_id": "NET1"},
                    {"site_id": "B", "network_id": "NET2"},
                ),
            )

    def test_json_adapter_loads_document(self) -> None:
        registry = build_default_format_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "payload.json"
            source_path.write_text(
                '{"name": "demo", "values": [1, 2]}', encoding="utf-8"
            )
            resource = build_resource_ref(str(source_path))

            loaded = registry.load(resource)

            self.assertEqual(
                loaded["document"],
                {"name": "demo", "values": [1, 2]},
            )

    def test_excel_adapter_loads_sheet_headers_and_rows(self) -> None:
        registry = build_default_format_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "stations.xlsx"
            _write_minimal_xlsx(source_path)
            resource = build_resource_ref(str(source_path))

            self.assertTrue(registry.probe(resource))
            loaded = registry.load(resource)

            self.assertEqual(loaded["sheet_names"], ("Stations",))
            self.assertEqual(loaded["headers"], ("site_id", "network_id"))
            self.assertEqual(
                loaded["rows"],
                (
                    {"site_id": "A", "network_id": "NET1"},
                    {"site_id": "B", "network_id": "NET2"},
                ),
            )

    def test_xml_adapter_loads_root_tag_and_document(self) -> None:
        registry = build_default_format_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "payload.xml"
            source_path.write_text(
                "<root><station id='A'>demo</station></root>",
                encoding="utf-8",
            )
            resource = build_resource_ref(str(source_path))

            self.assertTrue(registry.probe(resource))
            loaded = registry.load(resource)

            self.assertEqual(loaded["root_tag"], "root")
            self.assertEqual(
                loaded["document"],
                {
                    "root": {
                        "children": [
                            {
                                "station": {
                                    "attributes": {"id": "A"},
                                    "text": "demo",
                                }
                            }
                        ]
                    }
                },
            )

    def test_mat_adapter_loads_variable_metadata(self) -> None:
        registry = build_default_format_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "payload.mat"
            savemat(source_path, {"tb": np.arange(6, dtype=np.float32).reshape(2, 3)})
            resource = build_resource_ref(str(source_path))

            self.assertTrue(registry.probe(resource))
            loaded = registry.load(resource)

            self.assertIn("tb", loaded["variable_names"])
            self.assertTrue(
                any(variable["name"] == "tb" for variable in loaded["variables"])
            )

    def test_hdf_adapter_loads_dataset_metadata(self) -> None:
        registry = build_default_format_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "payload.h5"
            with h5py.File(source_path, "w") as handle:
                handle.create_dataset(
                    "tb", data=np.arange(6, dtype=np.float32).reshape(2, 3)
                )
            resource = build_resource_ref(str(source_path))

            self.assertTrue(registry.probe(resource))
            loaded = registry.load(resource)

            self.assertEqual(loaded["dataset_names"], ("tb",))
            self.assertEqual(loaded["datasets"][0]["shape"], (2, 3))

    def test_netcdf_adapter_loads_dimension_and_variable_metadata(self) -> None:
        registry = build_default_format_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "payload.nc"
            _write_minimal_netcdf(source_path)
            resource = build_resource_ref(str(source_path))

            self.assertTrue(registry.probe(resource))
            loaded = registry.load(resource)

            self.assertEqual(loaded["dimension_names"], ("x", "y"))
            self.assertEqual(loaded["variable_names"], ("tb",))
            self.assertEqual(loaded["variables"][0]["shape"], (2, 3))

    def test_tiff_adapter_loads_raster_metadata(self) -> None:
        registry = build_default_format_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "payload.tif"
            _write_minimal_tiff(source_path)
            resource = build_resource_ref(str(source_path))

            self.assertTrue(registry.probe(resource))
            loaded = registry.load(resource)

            self.assertEqual(loaded["width"], 3)
            self.assertEqual(loaded["height"], 2)
            self.assertEqual(loaded["band_count"], 1)
            self.assertEqual(loaded["crs"], "EPSG:4326")

    def test_shapefile_adapter_loads_geometry_and_feature_metadata(self) -> None:
        registry = build_default_format_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "payload.shp"
            _write_minimal_shapefile(source_path)
            resource = build_resource_ref(str(source_path))

            self.assertTrue(registry.probe(resource))
            loaded = registry.load(resource)

            self.assertEqual(loaded["geometry_type"], "point")
            self.assertEqual(loaded["feature_count"], 2)
            self.assertEqual(
                loaded["bbox"],
                {"xmin": 10.0, "ymin": 20.0, "xmax": 10.0, "ymax": 20.0},
            )

    def test_registry_rejects_unregistered_format(self) -> None:
        registry = build_default_format_registry()
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "payload.bin"
            source_path.write_bytes(b"binary-content")
            resource = build_resource_ref(str(source_path))

            self.assertFalse(registry.probe(resource))
            with self.assertRaises(LookupError):
                registry.load(resource)


if __name__ == "__main__":
    unittest.main()
