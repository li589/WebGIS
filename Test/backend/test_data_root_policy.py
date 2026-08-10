"""去硬编码批 1：data_root 策略与种子占位展开。"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services.effective_config import assert_data_root_policy
from app.services.workflow_definition_service import _expand_seed_placeholders


def test_assert_data_root_policy_allows_dev_without_root() -> None:
    with patch(
        "app.core.config.settings",
        replace(settings, environment="development", data_root=""),
    ):
        assert_data_root_policy()  # no raise


def test_assert_data_root_policy_rejects_production_without_root() -> None:
    with patch(
        "app.core.config.settings",
        replace(settings, environment="production", data_root=""),
    ):
        with pytest.raises(RuntimeError, match="BACKEND_DATA_ROOT"):
            assert_data_root_policy()


def test_expand_seed_placeholders_data_root() -> None:
    with patch(
        "app.core.config.settings",
        replace(settings, data_root=r"D:\OrgData"),
    ):
        out = _expand_seed_placeholders(
            '{"path":"{DATA_ROOT}/SMAP","win":"{DATA_ROOT_WIN}\\\\SMAP"}'
        )
    assert (
        '"path":"D:/OrgData/SMAP"' in out.replace("\\\\", "\\")
        or "D:/OrgData/SMAP" in out
    )
    assert "D:\\OrgData" in out or "D:/OrgData" in out
