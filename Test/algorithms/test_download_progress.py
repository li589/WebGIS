"""Download progress callback factories (download_nodes)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def logger():
    return MagicMock()


def test_multi_file_progress_cb_emits_detail(logger):
    from modules.download_nodes import _make_multi_file_progress_cb

    cb = _make_multi_file_progress_cb(logger, "nsidc_smap_download")
    cb(2, 5, 1_560_000, "file.h5")
    logger.emit_progress.assert_called_once()
    args = logger.emit_progress.call_args
    assert args[0][0] == "nsidc_smap_download"
    detail = args[0][3]
    assert detail["download_mode"] == "multi_file"
    assert detail["downloaded_items"] == 2
    assert detail["total_items"] == 5
    assert detail["phase"] == "downloading"


def test_skip_complete_emit(logger):
    from modules.download_nodes import _make_skip_complete_emit

    _make_skip_complete_emit(logger, "ssh_sync", total=10, skipped=10)
    logger.emit_progress.assert_called_once()
    detail = logger.emit_progress.call_args[0][3]
    assert detail["phase"] == "skipping"
    assert logger.emit_progress.call_args[0][1] == 1.0


def test_byte_stream_progress_cb(logger):
    from modules.download_nodes import _make_byte_stream_progress_cb

    cb = _make_byte_stream_progress_cb(logger, "gldas_download", item_name="a.nc4")
    cb(512_000, 1_024_000)
    detail = logger.emit_progress.call_args[0][3]
    assert detail["download_mode"] == "byte_stream"
    assert detail["current_item_name"] == "a.nc4"


def test_byte_stream_progress_cb_throttles(logger):
    from modules.download_nodes import _DOWNLOAD_EMIT_INTERVAL, _make_byte_stream_progress_cb

    cb = _make_byte_stream_progress_cb(logger, "fake_stage", item_name="x.bin")
    with patch("modules.download_nodes.time.monotonic", side_effect=[0.0, 0.5, 3.0]):
        cb(256_000, 1_024_000)
        cb(512_000, 1_024_000)
        cb(768_000, 1_024_000)
    assert logger.emit_progress.call_count == 2
    assert _DOWNLOAD_EMIT_INTERVAL == 2.0


def test_byte_stream_emits_on_complete(logger):
    from modules.download_nodes import _make_byte_stream_progress_cb

    cb = _make_byte_stream_progress_cb(logger, "fake_stage", item_name="done.bin")
    with patch("modules.download_nodes.time.monotonic", side_effect=[0.0, 0.1]):
        cb(256_000, 1_024_000)
        cb(1_024_000, 1_024_000)
    assert logger.emit_progress.call_count == 2
    complete_detail = logger.emit_progress.call_args_list[-1][0][3]
    assert complete_detail["phase"] == "complete"


def test_nomads_module_wires_progress_detail(logger):
    from ingest.nomads_download import NomadsDownloadResult, NomadsFile
    from modules.nomads_download import NomadsGribDownloadModule
    from workflow.schemas import NodeExecutionContext

    fake = NomadsDownloadResult(
        model="gfs",
        date="2026-01-02 06:00",
        use="legacy",
        target_dir="/tmp/nomads",
        downloaded=1,
        files=[NomadsFile(name="a.grib2", path="/tmp/nomads/a.grib2", size_bytes=100)],
        downloaded_bytes=100,
    )
    ctx = MagicMock(spec=NodeExecutionContext)
    ctx.workspace = MagicMock()
    ctx.logger_adapter = logger

    module = NomadsGribDownloadModule()
    with patch(
        "ingest.nomads_download.download_nomads_grib", return_value=fake
    ) as mock_dl:
        module.execute(
            {"datasource_selection": {}, "algorithm_params": {}},
            {"date": "2026-01-02 06:00", "use": "legacy", "legacy_url": "http://x"},
            ctx,
        )
        assert mock_dl.call_args.kwargs["progress_callback"] is not None
        assert mock_dl.call_args.kwargs["byte_stream_callback"] is not None


def test_cdse_module_wires_progress_detail(logger):
    from ingest.cdse_download import CdseDownloadResult
    from modules.cdse_download import CdseDownloadModule
    from workflow.schemas import NodeExecutionContext

    fake = CdseDownloadResult(
        use="cdse",
        target_dir="/tmp/cdse",
        downloaded=1,
        skipped=0,
        failed=0,
        downloaded_bytes=500,
    )
    ctx = MagicMock(spec=NodeExecutionContext)
    ctx.workspace = MagicMock()
    ctx.logger_adapter = logger

    module = CdseDownloadModule()
    with patch(
        "ingest.cdse_download.download_cdse_products", return_value=fake
    ) as mock_dl:
        module.execute(
            {"datasource_selection": {}, "algorithm_params": {}},
            {"product_ids": "pid-1", "use": "cdse", "username": "u", "password": "p"},
            ctx,
        )
        assert mock_dl.call_args.kwargs["progress_callback"] is not None
        assert mock_dl.call_args.kwargs["byte_stream_callback"] is not None


def test_cds_module_skip_complete_detail(logger):
    from ingest.cds_download import CdsDownloadResult
    from modules.cds_download import CdsDownloadModule
    from workflow.schemas import NodeExecutionContext

    fake = CdsDownloadResult(
        dataset="reanalysis-era5-single-levels",
        target="/tmp/cds/out.nc",
        skipped=True,
        use="cdsapi",
    )
    ctx = MagicMock(spec=NodeExecutionContext)
    ctx.workspace = MagicMock()
    ctx.logger_adapter = logger

    module = CdsDownloadModule()
    with patch("ingest.cds_download.download_cds_dataset", return_value=fake):
        module.execute(
            {"datasource_selection": {}, "algorithm_params": {}},
            {"dataset": "reanalysis-era5-single-levels", "request": "{}"},
            ctx,
        )
    skip_calls = [
        c for c in logger.emit_progress.call_args_list if c[0][3].get("phase") == "skipping"
    ]
    assert skip_calls
    assert skip_calls[0][0][3]["download_mode"] == "multi_file"
