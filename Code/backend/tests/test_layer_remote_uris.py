"""Unit tests for remote URI catalog injection + download limits."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[2]
for _p in (_CODE_ROOT / "algorithms" / "providers" / "Python", _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


def test_get_max_remote_bytes_from_env(monkeypatch):
    from shared.remote_sources.limits import DEFAULT_MAX_REMOTE_BYTES, get_max_remote_bytes

    monkeypatch.delenv("BACKEND_REMOTE_MAX_BYTES", raising=False)
    assert get_max_remote_bytes() == DEFAULT_MAX_REMOTE_BYTES

    monkeypatch.setenv("BACKEND_REMOTE_MAX_BYTES", "8589934592")
    assert get_max_remote_bytes() == 8589934592

    monkeypatch.setenv("BACKEND_REMOTE_MAX_BYTES", "not-a-number")
    assert get_max_remote_bytes() == DEFAULT_MAX_REMOTE_BYTES

    monkeypatch.setenv("BACKEND_REMOTE_MAX_BYTES", "0")
    assert get_max_remote_bytes() == DEFAULT_MAX_REMOTE_BYTES


def test_merge_remote_data_access_candidates_prepends_and_dedupes():
    from app.services.layer_catalog import merge_remote_data_access_candidates

    local = {"SMAP_SPL3SMP_E": ["SMAP_L3", "smap"]}
    remote = {
        "SMAP_SPL3SMP_E": [
            "smb://nas/share/a.h5?cred=nas-lab",
            "SMAP_L3",  # already local — should not duplicate at end
        ]
    }
    merged = merge_remote_data_access_candidates(local, remote)
    assert merged["SMAP_SPL3SMP_E"] == [
        "smb://nas/share/a.h5?cred=nas-lab",
        "SMAP_L3",
        "smap",
    ]


def test_parse_remote_layer_data_uris_db_overrides_env(monkeypatch):
    from app.services import layer_catalog

    env_payload = {
        "smap-soil": {
            "SMAP_SPL3SMP_E": ["smb://env-nas/share/a.h5?cred=env"],
        }
    }
    db_payload = {
        "smap-soil": {
            "SMAP_SPL3SMP_E": ["smb://db-nas/share/b.h5?cred=db"],
        }
    }
    monkeypatch.setattr(
        "app.services.layer_catalog.settings",
        type("S", (), {"remote_layer_data_uris": json.dumps(env_payload)})(),
    )
    monkeypatch.setattr(layer_catalog, "_load_db_remote_layer_data_uris", lambda: db_payload)
    merged = layer_catalog._parse_remote_layer_data_uris()
    assert merged["smap-soil"]["SMAP_SPL3SMP_E"] == ["smb://db-nas/share/b.h5?cred=db"]


def test_apply_remote_layer_data_uris_injects_smap(monkeypatch):
    from app.services import layer_catalog

    payload = {
        "smap-soil": {
            "SMAP_SPL3SMP_E": ["smb://192.168.1.10/Geograph/SMAP/x.h5?cred=nas-lab"],
        }
    }
    monkeypatch.setattr(layer_catalog, "_parse_remote_layer_data_uris", lambda: payload)
    catalog = layer_catalog.get_layer_catalog()
    smap = next(i for i in catalog.items if i.layer_id == "smap-soil")
    candidates = smap.default_data_access_sources["SMAP_SPL3SMP_E"]
    assert candidates[0].startswith("smb://")
    assert "SMAP_L3" in candidates or "smap" in candidates
    assert any("远端数据源候选" in n for n in (smap.run_readiness_notes or []))
