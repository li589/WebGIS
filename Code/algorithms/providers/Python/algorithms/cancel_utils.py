"""Cooperative workflow cancellation helpers for long-running algorithms."""

from __future__ import annotations

from pathlib import Path


class WorkflowCancelled(Exception):
    """Raised when lifecycle has requested cancellation for the run."""


def check_cancel_requested(cancel_flag_path: str | Path | None) -> None:
    """Raise :class:`WorkflowCancelled` when the cancel flag file exists."""
    if not cancel_flag_path:
        return
    if Path(cancel_flag_path).exists():
        raise WorkflowCancelled("workflow cancelled by user (cancel.requested)")
