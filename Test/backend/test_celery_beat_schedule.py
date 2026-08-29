"""Tests for Celery Beat schedule auto-repair (truncated shelve)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_beat_module():
    backend = Path(__file__).resolve().parents[2] / "Code" / "backend"
    code = backend.parent
    gee = backend / "app" / "gee" / "core" / "src"
    for p in (str(code), str(gee)):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(
        "_beat_sched_under_test", backend / "start_celery_beat.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ensure_beat_schedule_resets_truncated_shelve(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("ENVIRONMENT", "test")
    beat_mod = _load_beat_module()

    prefix = tmp_path / "celerybeat-schedule"
    (tmp_path / "celerybeat-schedule.dat").write_bytes(b"not-a-valid-pickle")
    (tmp_path / "celerybeat-schedule.dir").write_text("broken\n", encoding="utf-8")
    (tmp_path / "celerybeat-schedule.bak").write_bytes(b"\x00\x01")

    beat_mod.ensure_beat_schedule(prefix)

    left = list(tmp_path.glob("celerybeat-schedule*"))
    assert left == [], f"corrupt schedule files should be removed, left={left}"


def test_ensure_beat_schedule_keeps_healthy_shelve(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("ENVIRONMENT", "test")
    beat_mod = _load_beat_module()

    import shelve

    prefix = tmp_path / "celerybeat-schedule"
    with shelve.open(str(prefix)) as db:
        db["entries"] = {"tick": {"task": "x"}}
        db["__version__"] = "test"

    beat_mod.ensure_beat_schedule(prefix)
    assert list(tmp_path.glob("celerybeat-schedule*")), "healthy schedule must be kept"
    with shelve.open(str(prefix), flag="r") as db:
        assert "tick" in (db.get("entries") or {})
