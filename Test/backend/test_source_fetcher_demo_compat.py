from __future__ import annotations

import pytest
import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import settings as real_settings
from app.services.source_fetcher import DemoSourceFetcher


def _settings_with(**overrides: object):
    """settings 是 frozen dataclass，用 dataclasses.replace 生成开关变体。"""
    return dataclasses.replace(real_settings, **overrides)


def test_demo_fetcher_writes_legacy_demo_compat_artifact() -> None:
    """显式开启 demo 源（或 development 环境）时走兼容成功路径。"""
    fetcher = DemoSourceFetcher()

    with (
        patch(
            "app.core.config.settings",
            _settings_with(demo_sources_enabled=True),
        ),
        patch(
            "app.services.source_fetcher.object_store.put_bytes",
            return_value=SimpleNamespace(
                content_length=128, file_path=Path("demo-artifact.json")
            ),
        ) as put_bytes_mock,
    ):
        result = fetcher.fetch(
            ref_id="demo-ref",
            source_uri="demo://snapshots/wind-field",
            artifact_key_prefix="artifacts/test",
        )

    assert result.success, 'result.success is truthy'
    assert result.artifact_key == "artifacts/test/demo-ref", 'result.artifact_key == "artifacts/test/demo-ref"'
    payload = json.loads(put_bytes_mock.call_args.kwargs["data"].decode("utf-8"))
    metadata = put_bytes_mock.call_args.kwargs["metadata"]
    assert payload["compatibility_mode"] == "legacy-demo", 'payload["compatibility_mode"] == "legacy-demo"'
    assert "compatibility artifact" in payload["note"], '"compatibility artifact" in payload["note"]'
    assert metadata["compatibility_mode"] == "legacy-demo", 'metadata["compatibility_mode"] == "legacy-demo"'
    assert metadata["artifact_role"] == "compat-placeholder", 'metadata["artifact_role"] == "compat-placeholder"'


def test_demo_fetcher_fails_in_production_without_flag() -> None:
    """P0-10：production 且未显式开启时，demo:// 直接 fail（不再静默成功）。"""
    fetcher = DemoSourceFetcher()

    with patch(
        "app.core.config.settings",
        _settings_with(environment="production", demo_sources_enabled=False),
    ):
        with pytest.raises(ValueError) as ctx:
            fetcher.fetch(
                ref_id="demo-ref",
                source_uri="demo://snapshots/wind-field",
                artifact_key_prefix="artifacts/test",
            )

    assert "占位演示数据源" in str(ctx.value), '"占位演示数据源" in str(ctx.exception)'
    assert "BACKEND_DEMO_SOURCES_ENABLED" in str(ctx.value), '"BACKEND_DEMO_SOURCES_ENABLED" in str(ctx.exception)'
