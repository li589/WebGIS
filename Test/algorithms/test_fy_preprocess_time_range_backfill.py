"""fy_preprocess：缺节点日期时从 job_request.time_range 回填（对齐 fy_download）。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

PROVIDER_ROOT = (
    Path(__file__).resolve().parents[2] / "Code" / "algorithms" / "providers" / "Python"
)
sys.path.insert(0, str(PROVIDER_ROOT))

import contracts.job  # noqa: F401, E402

from modules.download_nodes import FyPreprocessModule  # noqa: E402


def _ctx(*, time_range: object | None, workspace: Path) -> SimpleNamespace:
    return SimpleNamespace(
        request=SimpleNamespace(time_range=time_range, job_id="job-test"),
        workspace=workspace,
        logger_adapter=None,
    )


def test_fy_preprocess_backfills_dates_from_time_range(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    mod = FyPreprocessModule()
    ctx = _ctx(
        time_range={
            "start_at": "2025-10-15T00:00:00",
            "end_at": "2025-10-15T23:59:59",
        },
        workspace=tmp_path,
    )
    captured: dict[str, str] = {}

    class _FakePreprocessor:
        def __init__(self, *_a, **_k) -> None:
            pass

        def process_date_range(self, **kwargs):  # type: ignore[no-untyped-def]
            captured["start_date"] = str(kwargs["start_date"])
            captured["end_date"] = str(kwargs["end_date"])
            return ["20251015"]

    with (
        patch("ingest.fy_preprocess.FyPreprocessor", _FakePreprocessor),
        patch(
            "ingest.fy_preprocess.FySatelliteConfig.for_fy3d",
            return_value=object(),
        ),
        patch(
            "modules.download_nodes._store_path_manifest",
            return_value={"path": str(tmp_path / "out")},
        ),
    ):
        out = mod.execute(
            inputs={"data": str(input_dir)},
            params={"satellite": "FY3D"},
            ctx=ctx,  # type: ignore[arg-type]
        )

    assert captured["start_date"] == "20251015"
    assert captured["end_date"] == "20251015"
    assert "path" in out


def test_fy_preprocess_still_errors_without_time_range(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    mod = FyPreprocessModule()
    ctx = _ctx(time_range=None, workspace=tmp_path)
    with pytest.raises(ValueError, match="requires start_date and end_date"):
        mod.execute(
            inputs={"data": str(input_dir)},
            params={},
            ctx=ctx,  # type: ignore[arg-type]
        )


def test_fy_preprocess_prefers_explicit_params(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    mod = FyPreprocessModule()
    ctx = _ctx(
        time_range=SimpleNamespace(
            start=datetime(2020, 1, 1),
            end=datetime(2020, 1, 2),
        ),
        workspace=tmp_path,
    )
    captured: dict[str, str] = {}

    class _FakePreprocessor:
        def __init__(self, *_a, **_k) -> None:
            pass

        def process_date_range(self, **kwargs):  # type: ignore[no-untyped-def]
            captured["start_date"] = str(kwargs["start_date"])
            captured["end_date"] = str(kwargs["end_date"])
            return ["20251201"]

    with (
        patch("ingest.fy_preprocess.FyPreprocessor", _FakePreprocessor),
        patch(
            "ingest.fy_preprocess.FySatelliteConfig.for_fy3d",
            return_value=object(),
        ),
        patch(
            "modules.download_nodes._store_path_manifest",
            return_value={"path": str(tmp_path / "out")},
        ),
    ):
        mod.execute(
            inputs={"data": str(input_dir)},
            params={"start_date": "20251201", "end_date": "20251201"},
            ctx=ctx,  # type: ignore[arg-type]
        )

    assert captured["start_date"] == "20251201"
    assert captured["end_date"] == "20251201"


def test_fy_preprocess_errors_when_no_days_processed(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    mod = FyPreprocessModule()
    ctx = _ctx(
        time_range={
            "start_at": "2025-10-15T00:00:00",
            "end_at": "2025-10-15T23:59:59",
        },
        workspace=tmp_path,
    )

    class _EmptyPreprocessor:
        def __init__(self, *_a, **_k) -> None:
            pass

        def process_date_range(self, **_kwargs):  # type: ignore[no-untyped-def]
            return []

    with (
        patch("ingest.fy_preprocess.FyPreprocessor", _EmptyPreprocessor),
        patch(
            "ingest.fy_preprocess.FySatelliteConfig.for_fy3d",
            return_value=object(),
        ),
    ):
        with pytest.raises(FileNotFoundError, match="produced no output"):
            mod.execute(
                inputs={"data": str(input_dir)},
                params={"satellite": "FY3D"},
                ctx=ctx,  # type: ignore[arg-type]
            )
