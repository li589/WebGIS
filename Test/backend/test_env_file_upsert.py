"""Regression tests for .env atomic upsert (CGDA review action #6 / F5).

Validates the atomic-replace behaviour added to ``app.services.env_file_upsert``:
- existing keys are updated in place, other keys/comments are preserved;
- a temp file (``.env.*.tmp``) is not left behind after a successful write.
"""

from __future__ import annotations

from pathlib import Path

from app.services.env_file_upsert import read_env_file_values, upsert_env_keys


def test_upsert_preserves_other_lines_and_updates_existing(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# header comment\nEXISTING=old\n\nKEEP=yes\n", encoding="utf-8")

    upsert_env_keys({"EXISTING": "new", "ADDED": "x"}, path=env)

    values = read_env_file_values(env)
    assert values["EXISTING"] == "new"
    assert values["KEEP"] == "yes"
    assert values["ADDED"] == "x"

    text = env.read_text(encoding="utf-8")
    assert "# header comment" in text
    assert "KEEP=yes" in text


def test_upsert_atomic_leaves_no_temp_file_on_success(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")

    upsert_env_keys({"A": "2", "B": "3"}, path=env)

    leftovers = list(tmp_path.glob(".env.*.tmp"))
    assert leftovers == [], f"temp file left behind after write: {leftovers}"
