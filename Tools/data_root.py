#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tools 共享：解析项目 DATA_ROOT（去硬编码 B1）。

优先级：
    1. env ``CGDA_DATA_ROOT`` / ``BACKEND_DATA_ROOT``
    2. 候选探测：现行数据盘 ``I:/Geograph_DataSet``（见 deployment.config.json /
       .workbuddy memory 约定）
    3. 开发兜底：仓库内 ``Code/backend/.data``

纯 stdlib、无项目内依赖——Tools 脚本直接 ``from data_root import resolve_data_root``。
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

_CANDIDATE_ROOTS = (
    Path("I:/Geograph_DataSet"),
    _REPO_ROOT / "Code" / "backend" / ".data",
)


def resolve_data_root() -> Path:
    """返回数据根目录（env 优先 → 探测 → 开发兜底）。"""
    for key in ("CGDA_DATA_ROOT", "BACKEND_DATA_ROOT"):
        value = os.getenv(key, "").strip()
        if value:
            return Path(value)
    for candidate in _CANDIDATE_ROOTS:
        if candidate.is_dir():
            return candidate
    return _CANDIDATE_ROOTS[-1]
