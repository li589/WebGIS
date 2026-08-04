"""Workflow cancel flag paths shared by lifecycle and python provider bridge."""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings


def workflow_cancel_flag_path(run_id: str) -> Path:
    """Path written by lifecycle cancel and read by long-running algorithms."""
    return (
        Path(settings.python_provider_workspace) / "tmp" / run_id / "cancel.requested"
    )


def workflow_cancel_tmp_dir(run_id: str) -> Path:
    """Stable tmp dir for a workflow run (matches lifecycle cancel layout)."""
    return Path(settings.python_provider_workspace) / "tmp" / run_id
