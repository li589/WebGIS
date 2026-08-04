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

from data_access import DataRequestV2, build_default_coordinator


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


def _write_minimal_tiff_without_crs(path: Path) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=3,
        height=2,
        count=1,
        dtype="float32",
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


class DataAccessPipelineTests(unittest.TestCase):
    def _assert_highlight_present(
        self,
        highlights: list[dict[str, object]],
        *,
        key: str,
        value: object,
    ) -> None:
        self.assertTrue(
            any(
                item.get("key") == key and item.get("value") == value
                for item in highlights
            ),
            msg=f"Expected highlight {key}={value!r} in {highlights!r}",
        )

    def _assert_warning_present(
        self,
        warnings: list[dict[str, str]],
        *,
        code: str,
        severity: str,
    ) -> None:
        self.assertTrue(
            any(
                item.get("code") == code and item.get("severity") == severity
                for item in warnings
            ),
            msg=f"Expected warning {code}/{severity} in {warnings!r}",
        )

    def test_local_resource_prepares_without_cache_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            local_file = root / "input.mat"
            local_file.write_text("mat-content", encoding="utf-8")
            coordinator = build_default_coordinator(root / "cache")

            prepared = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_local",
                    accepted_formats=("mat",),
                    selector={"uris": [str(local_file)]},
                )
            )

            self.assertEqual(len(prepared.resources), 1)
            self.assertEqual(len(prepared.materialized_resources), 1)
            self.assertEqual(prepared.resources[0].source_kind, "local_file")
            self.assertEqual(
                prepared.materialized_resources[0].local_path, str(local_file.resolve())
            )
            self.assertEqual(prepared.cache_hits, ())

    def test_http_resource_fetches_into_cache_and_materializes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            remote_file = root / "remote.json"
            remote_file.write_text('{"value": 1}', encoding="utf-8")
            coordinator = build_default_coordinator(root / "cache")

            prepared = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_http",
                    accepted_formats=("json",),
                    selector={
                        "uris": [
                            {
                                "uri": "https://example.com/data/demo.json",
                                "metadata": {"mock_local_path": str(remote_file)},
                            }
                        ]
                    },
                )
            )

            self.assertEqual(prepared.resources[0].source_kind, "online")
            self.assertEqual(prepared.materialized_resources[0].source_kind, "cache")
            self.assertTrue(
                Path(prepared.materialized_resources[0].local_path).exists()
            )
            self.assertEqual(prepared.cache_hits, ())

    def test_minio_resource_uses_cache_on_second_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            remote_file = root / "remote.nc"
            remote_file.write_text("nc-content", encoding="utf-8")
            coordinator = build_default_coordinator(root / "cache")
            request = DataRequestV2(
                dataset_name="demo_minio",
                accepted_formats=("nc",),
                selector={
                    "uris": [
                        {
                            "uri": "minio://bucket-a/path/to/demo.nc",
                            "metadata": {"mock_local_path": str(remote_file)},
                        }
                    ]
                },
            )

            first = coordinator.prepare(request)
            second = coordinator.prepare(request)

            self.assertEqual(first.materialized_resources[0].source_kind, "cache")
            self.assertEqual(second.materialized_resources[0].source_kind, "cache")
            self.assertEqual(second.cache_hits, ("minio://bucket-a/path/to/demo.nc",))
            self.assertEqual(
                first.materialized_resources[0].local_path,
                second.materialized_resources[0].local_path,
            )

    def test_resolver_filters_out_unaccepted_formats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            remote_file = root / "remote.json"
            remote_file.write_text('{"value": 1}', encoding="utf-8")
            coordinator = build_default_coordinator(root / "cache")

            prepared = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_filter",
                    accepted_formats=("csv",),
                    selector={
                        "uris": [
                            {
                                "uri": "https://example.com/data/demo.json",
                                "metadata": {"mock_local_path": str(remote_file)},
                            }
                        ]
                    },
                )
            )

            self.assertEqual(prepared.resources, ())
            self.assertEqual(prepared.materialized_resources, ())
            self.assertEqual(
                prepared.warnings,
                ("No resources resolved for dataset 'demo_filter'",),
            )

    def test_prepare_builds_conversion_trace_for_supported_formats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            coordinator = build_default_coordinator(root / "cache")

            text_file = root / "notes.txt"
            text_file.write_text("line-1\nline-2\n", encoding="utf-8")
            prepared_text = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_text",
                    accepted_formats=("txt",),
                    selector={"uris": [str(text_file)]},
                )
            )
            self.assertEqual(len(prepared_text.conversion_trace), 1)
            self.assertEqual(prepared_text.conversion_trace[0]["adapter"], "text")
            self.assertEqual(
                prepared_text.conversion_trace[0]["loaded_summary"]["counts"][
                    "line_count"
                ],
                2,
            )
            self.assertEqual(
                prepared_text.conversion_trace[0]["loaded_summary"]["title"],
                "Text resource",
            )
            self._assert_highlight_present(
                prepared_text.conversion_trace[0]["loaded_summary"]["highlights"],
                key="line_count",
                value=2,
            )
            self.assertEqual(
                prepared_text.conversion_trace[0]["loaded_summary"]["warnings"], []
            )

            csv_file = root / "stations.csv"
            csv_file.write_text(
                "site_id,network_id\nA,NET1\nB,NET2\n", encoding="utf-8"
            )
            prepared_csv = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_csv",
                    accepted_formats=("csv",),
                    selector={"uris": [str(csv_file)]},
                )
            )
            self.assertEqual(len(prepared_csv.conversion_trace), 1)
            self.assertEqual(prepared_csv.conversion_trace[0]["adapter"], "csv")
            self.assertEqual(
                prepared_csv.conversion_trace[0]["loaded_summary"]["counts"][
                    "row_count"
                ],
                2,
            )
            self.assertEqual(
                prepared_csv.conversion_trace[0]["loaded_summary"]["schema"]["headers"],
                ("site_id", "network_id"),
            )
            self.assertEqual(
                prepared_csv.conversion_trace[0]["loaded_summary"]["title"],
                "Tabular resource",
            )
            self._assert_highlight_present(
                prepared_csv.conversion_trace[0]["loaded_summary"]["highlights"],
                key="row_count",
                value=2,
            )

            json_file = root / "payload.json"
            json_file.write_text('{"name": "demo", "values": [1, 2]}', encoding="utf-8")
            prepared_json = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_json",
                    accepted_formats=("json",),
                    selector={"uris": [str(json_file)]},
                )
            )
            self.assertEqual(len(prepared_json.conversion_trace), 1)
            self.assertEqual(prepared_json.conversion_trace[0]["adapter"], "json")
            self.assertEqual(
                prepared_json.conversion_trace[0]["loaded_summary"]["document"]["keys"],
                ("name", "values"),
            )

            excel_file = root / "stations.xlsx"
            _write_minimal_xlsx(excel_file)
            prepared_excel = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_excel",
                    accepted_formats=("excel",),
                    selector={"uris": [str(excel_file)]},
                )
            )
            self.assertEqual(len(prepared_excel.conversion_trace), 1)
            self.assertEqual(prepared_excel.conversion_trace[0]["adapter"], "excel")
            self.assertEqual(
                prepared_excel.conversion_trace[0]["loaded_summary"]["counts"][
                    "worksheet_count"
                ],
                1,
            )
            self.assertEqual(
                prepared_excel.conversion_trace[0]["loaded_summary"]["counts"][
                    "row_count"
                ],
                2,
            )
            self.assertEqual(
                prepared_excel.conversion_trace[0]["loaded_summary"]["title"],
                "Excel workbook",
            )
            self._assert_highlight_present(
                prepared_excel.conversion_trace[0]["loaded_summary"]["highlights"],
                key="sheet_name",
                value="Stations",
            )

            xml_file = root / "payload.xml"
            xml_file.write_text(
                "<root><station id='A'>demo</station></root>", encoding="utf-8"
            )
            prepared_xml = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_xml",
                    accepted_formats=("xml",),
                    selector={"uris": [str(xml_file)]},
                )
            )
            self.assertEqual(len(prepared_xml.conversion_trace), 1)
            self.assertEqual(prepared_xml.conversion_trace[0]["adapter"], "xml")
            self.assertEqual(
                prepared_xml.conversion_trace[0]["loaded_summary"]["document"][
                    "root_tag"
                ],
                "root",
            )
            self.assertEqual(
                prepared_xml.conversion_trace[0]["loaded_summary"]["document"]["keys"],
                ("root",),
            )
            self.assertEqual(
                prepared_xml.conversion_trace[0]["loaded_summary"]["title"],
                "XML document root",
            )
            self._assert_highlight_present(
                prepared_xml.conversion_trace[0]["loaded_summary"]["highlights"],
                key="root_tag",
                value="root",
            )

            mat_file = root / "payload.mat"
            savemat(mat_file, {"tb": np.arange(6, dtype=np.float32).reshape(2, 3)})
            prepared_mat = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_mat",
                    accepted_formats=("mat",),
                    selector={"uris": [str(mat_file)]},
                )
            )
            self.assertEqual(prepared_mat.conversion_trace[0]["adapter"], "mat")
            self.assertEqual(
                prepared_mat.conversion_trace[0]["loaded_summary"]["counts"][
                    "variable_count"
                ],
                1,
            )

            h5_file = root / "payload.h5"
            with h5py.File(h5_file, "w") as handle:
                handle.create_dataset(
                    "tb", data=np.arange(6, dtype=np.float32).reshape(2, 3)
                )
            prepared_h5 = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_h5",
                    accepted_formats=("h5",),
                    selector={"uris": [str(h5_file)]},
                )
            )
            self.assertEqual(prepared_h5.conversion_trace[0]["adapter"], "hdf5")
            self.assertEqual(
                prepared_h5.conversion_trace[0]["loaded_summary"]["counts"][
                    "dataset_count"
                ],
                1,
            )

            nc_file = root / "payload.nc"
            _write_minimal_netcdf(nc_file)
            prepared_nc = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_nc",
                    accepted_formats=("nc",),
                    selector={"uris": [str(nc_file)]},
                )
            )
            self.assertEqual(prepared_nc.conversion_trace[0]["adapter"], "netcdf")
            self.assertEqual(
                prepared_nc.conversion_trace[0]["loaded_summary"]["counts"][
                    "dimension_count"
                ],
                2,
            )
            self.assertEqual(
                prepared_nc.conversion_trace[0]["loaded_summary"]["counts"][
                    "variable_count"
                ],
                1,
            )
            self.assertEqual(
                prepared_nc.conversion_trace[0]["loaded_summary"]["title"],
                "NetCDF dataset",
            )

            tif_file = root / "payload.tif"
            _write_minimal_tiff(tif_file)
            prepared_tif = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_tif",
                    accepted_formats=("tif",),
                    selector={"uris": [str(tif_file)]},
                )
            )
            self.assertEqual(prepared_tif.conversion_trace[0]["adapter"], "tiff")
            self.assertEqual(
                prepared_tif.conversion_trace[0]["loaded_summary"]["counts"][
                    "band_count"
                ],
                1,
            )
            self.assertEqual(
                prepared_tif.conversion_trace[0]["loaded_summary"]["spatial"]["crs"],
                "EPSG:4326",
            )
            self.assertEqual(
                prepared_tif.conversion_trace[0]["loaded_summary"]["title"],
                "Raster resource",
            )
            self._assert_highlight_present(
                prepared_tif.conversion_trace[0]["loaded_summary"]["highlights"],
                key="crs",
                value="EPSG:4326",
            )
            self.assertEqual(
                prepared_tif.conversion_trace[0]["loaded_summary"]["warnings"], []
            )

            tif_without_crs_file = root / "payload_no_crs.tif"
            _write_minimal_tiff_without_crs(tif_without_crs_file)
            prepared_tif_without_crs = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_tif_no_crs",
                    accepted_formats=("tif",),
                    selector={"uris": [str(tif_without_crs_file)]},
                )
            )
            self.assertEqual(
                prepared_tif_without_crs.conversion_trace[0]["loaded_summary"]["title"],
                "Raster resource",
            )
            self._assert_warning_present(
                prepared_tif_without_crs.conversion_trace[0]["loaded_summary"][
                    "warnings"
                ],
                code="missing_crs",
                severity="warning",
            )

            shp_file = root / "payload.shp"
            _write_minimal_shapefile(shp_file)
            prepared_shp = coordinator.prepare(
                DataRequestV2(
                    dataset_name="demo_shp",
                    accepted_formats=("shp",),
                    selector={"uris": [str(shp_file)]},
                )
            )
            self.assertEqual(prepared_shp.conversion_trace[0]["adapter"], "shapefile")
            self.assertEqual(
                prepared_shp.conversion_trace[0]["loaded_summary"]["counts"][
                    "feature_count"
                ],
                2,
            )
            self.assertEqual(
                prepared_shp.conversion_trace[0]["loaded_summary"]["spatial"][
                    "geometry_type"
                ],
                "point",
            )
            self.assertEqual(
                prepared_shp.conversion_trace[0]["loaded_summary"]["title"],
                "Vector point",
            )
            self._assert_highlight_present(
                prepared_shp.conversion_trace[0]["loaded_summary"]["highlights"],
                key="geometry_type",
                value="point",
            )


if __name__ == "__main__":
    unittest.main()
