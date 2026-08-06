"""Tests for configurable data-root paths and UI backend restart gating."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_upsert_env_keys_preserves_other_lines(tmp_path: Path):
    from app.services.env_file_upsert import read_env_file_values, upsert_env_keys

    env = tmp_path / ".env"
    env.write_text(
        "# keep me\nBACKEND_ENV=development\nBACKEND_API_KEY=secret\nOTHER=1\n",
        encoding="utf-8",
    )
    upsert_env_keys(
        {
            "BACKEND_DATA_ROOT": r"D:\data",
            "BACKEND_OUTPUT_ROOT": r"D:\data\out",
        },
        path=env,
    )
    text = env.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "BACKEND_ENV=development" in text
    assert "BACKEND_API_KEY=secret" in text
    assert "OTHER=1" in text
    vals = read_env_file_values(env)
    assert vals["BACKEND_DATA_ROOT"] == r"D:\data"
    assert vals["BACKEND_OUTPUT_ROOT"] == r"D:\data\out"

    # second upsert updates in place
    upsert_env_keys({"BACKEND_DATA_ROOT": r"E:\geo"}, path=env)
    vals2 = read_env_file_values(env)
    assert vals2["BACKEND_DATA_ROOT"] == r"E:\geo"
    assert vals2["BACKEND_API_KEY"] == "secret"


def test_update_data_source_paths_validates_and_writes(tmp_path: Path, monkeypatch):
    from app.services import config_service

    root = tmp_path / "Geograph_DataSet"
    root.mkdir()
    (root / "Soil_Moisture").mkdir()

    env = tmp_path / ".env"
    env.write_text("BACKEND_ENV=development\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.services.env_file_upsert.backend_env_path", lambda: env
    )

    result = config_service.update_data_source_paths(str(root), None)
    assert Path(result["data_root"]) == root.resolve()
    assert Path(result["output_root"]).name == "ProjectOutput"
    assert Path(result["output_root"]).is_dir()
    assert "BACKEND_DATA_ROOT=" in env.read_text(encoding="utf-8")
    assert result["pending_restart"] is True


def test_update_data_source_paths_rejects_relative(tmp_path: Path):
    from app.services import config_service

    with pytest.raises(ValueError, match="absolute"):
        config_service.update_data_source_paths("relative/path", None)


def test_schedule_ui_backend_restart_forbidden_when_disabled(monkeypatch):
    from app.services import config_service

    monkeypatch.setattr(
        "app.services.service_restart.ui_restart_allowed", lambda: False
    )
    with pytest.raises(PermissionError):
        config_service.schedule_ui_backend_restart(["fastapi"])


def test_schedule_ui_backend_restart_rejects_unknown_component(monkeypatch):
    from app.services import config_service

    monkeypatch.setattr(
        "app.services.service_restart.ui_restart_allowed", lambda: True
    )
    with pytest.raises(ValueError, match="unsupported"):
        config_service.schedule_ui_backend_restart(["docker"])


def test_schedule_ui_backend_restart_accepted(monkeypatch):
    from app.services import config_service

    calls: list[list[str] | None] = []

    def _fake(components=None, delay_seconds: float = 1.5):
        calls.append(components)
        return {
            "accepted": True,
            "components": ["worker", "beat", "fastapi"],
            "delay_seconds": delay_seconds,
            "message": "ok",
        }

    monkeypatch.setattr(
        "app.services.service_restart.ui_restart_allowed", lambda: True
    )
    monkeypatch.setattr(
        "app.services.service_restart.schedule_backend_restart", _fake
    )
    result = config_service.schedule_ui_backend_restart(None)
    assert result["accepted"] is True
    assert result["ui_restart_enabled"] is True
    assert calls == [None]
