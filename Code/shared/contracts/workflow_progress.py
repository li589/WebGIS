"""Workflow node progress detail shapes (download / inversion)."""

from __future__ import annotations

from typing import Literal, TypedDict


class DownloadProgressDetail(TypedDict, total=False):
    """Unified download progress payload for node_progress.detail (snake_case)."""

    download_mode: Literal["single_file", "multi_file", "byte_stream"]
    downloaded_items: int
    total_items: int
    downloaded_bytes: int
    total_bytes: int | None
    speed_bps: float | None
    current_item_name: str | None
    active_workers: int | None
    phase: Literal["scanning", "downloading", "skipping", "complete"]
    items_display: Literal["index", "filename"]
