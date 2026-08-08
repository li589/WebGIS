"""Time-series imports often lack root preview.png; lazy-load must still work."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import overlay_registry as reg


@pytest.fixture()
def ts_import_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    imports = tmp_path / "imports"
    layer = imports / "imported-ts-lazy"
    layer.mkdir(parents=True)
    (layer / "bounds.json").write_text(
        json.dumps(
            {
                "bounds": [100.0, 20.0, 110.0, 30.0],
                "meta": {
                    "category": "time-series",
                    "time_list": ["20251227_20251231"],
                    "default_time": "20251227_20251231",
                    "label": "OMEGA_BLOCK",
                    "palette": "cividis",
                },
            }
        ),
        encoding="utf-8",
    )
    (layer / "preview_20251227_20251231.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (layer / "source_20251227_20251231.tif").write_bytes(b"fake")
    (layer / "meta.json").write_text(
        json.dumps(
            {
                "layer_id": "imported-ts-lazy",
                "category": "time-series",
                "time_list": ["20251227_20251231"],
                "label": "OMEGA_BLOCK",
                "variable_id": "OMEGA",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.data_io.services.paths.IMPORTS_DIR",
        imports,
    )
    # Clear any prior registry entry
    reg.unregister_overlay("imported-ts-lazy")
    return layer


def test_lazy_load_timeseries_without_root_preview(ts_import_dir: Path) -> None:
    assert not (ts_import_dir / "preview.png").exists()
    spec = reg.get_overlay_spec("imported-ts-lazy")
    assert spec is not None
    assert spec.category == "time-series"
    assert spec.default_time == "20251227_20251231"
    assert spec.time_pattern == "preview_{time}.png"
    assert spec.source_pattern is not None
    assert "imported-ts-lazy" in reg.list_overlay_ids()
