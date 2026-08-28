"""Unit tests for overlay asset bake failure messaging."""

from __future__ import annotations

from app.services.overlay_asset_workflow_service import (
    _format_bake_failure_message,
    _summarize_bake_tool_output,
)


def test_summarize_skip_file_not_found() -> None:
    stdout = (
        "============================================================\n"
        "Overlay Assets Export Tool\n"
        "=== CMFD Precipitation (China 1km) === [SKIP] File not found\n"
        "Summary: [OK] CMFD Precip: OK\n"
    )
    reason, notes = _summarize_bake_tool_output(stdout, "")
    assert reason is not None
    assert "源数据文件缺失" in reason
    assert any("未找到" in n or "跳过" in n for n in notes)


def test_format_bake_failure_prefers_missing_source_over_stale_generic() -> None:
    message, diagnostics = _format_bake_failure_message(
        asset_state={
            "asset_state": "missing",
            "bake_version": None,
            "current_bake_version": 3,
        },
        returncode=0,
        stdout="=== CMFD Precipitation === [SKIP] File not found\n",
        stderr="",
        remaining_stale=[],
    )
    assert "陈旧" not in message or "源数据" in message
    assert "源数据文件缺失" in message
    assert "资产状态：缺失" not in message  # 中文在 diagnostics 本地化侧
    assert any(d.startswith("asset_state=missing") for d in diagnostics)
    assert any(d.startswith("bake_log=") for d in diagnostics)
    assert not any(d == "returncode=0" for d in diagnostics)
    assert not any(d.startswith("remaining_stale=[]") for d in diagnostics)


def test_format_bake_failure_nonzero_returncode() -> None:
    message, diagnostics = _format_bake_failure_message(
        asset_state={"asset_state": "stale", "bake_version": 1, "current_bake_version": 3},
        returncode=2,
        stdout="",
        stderr="boom",
        remaining_stale=["cmfd_precip"],
    )
    assert "退出码 2" in message or "失败" in message
    assert any("returncode=2" in d for d in diagnostics)
    assert any("remaining_stale=" in d for d in diagnostics)
