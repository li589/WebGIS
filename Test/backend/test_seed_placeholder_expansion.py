"""种子占位符展开：{DATA_ROOT} / {DATA_ROOT_WIN} 必须产出合法 JSON。

回归背景：去硬编码批 1 引入占位符后，Windows 路径的单反斜杠被直接注入 JSON
字符串字面量，产生非法转义（如 ``\\G``），导致整份种子解析失败并静默回退到
运行目录中的旧定义。
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from app.services import workflow_definition_service as svc

_SEED_TEMPLATE = (
    '{"workflow_id": "x", "nodes": [{"properties": '
    '{"local_dir": "{DATA_ROOT_WIN}\\\\Meteorological\\\\GLDAS", '
    '"path": "{DATA_ROOT}/SMAP"}}]}'
)


def _patch_data_root(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(
        "app.core.config.settings", SimpleNamespace(data_root=value), raising=False
    )


@pytest.mark.parametrize(
    "data_root",
    [
        pytest.param(
            r"I:\Geograph_DataSet",
            marks=pytest.mark.skipif(
                sys.platform != "win32",
                reason="Windows drive-letter backslash paths",
            ),
        ),
        "I:/Geograph_DataSet",
        "/srv/geodata",
        pytest.param(
            r"D:\data with space\root",
            marks=pytest.mark.skipif(
                sys.platform != "win32",
                reason="Windows drive-letter backslash paths",
            ),
        ),
    ],
)
def test_expanded_seed_is_valid_json(
    monkeypatch: pytest.MonkeyPatch, data_root: str
) -> None:
    _patch_data_root(monkeypatch, data_root)
    expanded = svc._expand_seed_placeholders(_SEED_TEMPLATE)
    parsed = json.loads(expanded)  # 关键断言：不得抛 JSONDecodeError
    props = parsed["nodes"][0]["properties"]
    if svc._IS_WINDOWS:
        assert props["local_dir"].endswith("\\Meteorological\\GLDAS")
    else:
        # 硬编码清理 A3：非 Windows 下 {DATA_ROOT_WIN} 退化为 posix 分隔符
        assert props["local_dir"].endswith("/Meteorological/GLDAS")
    assert props["path"].endswith("/SMAP")


def test_windows_placeholder_yields_backslash_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_data_root(monkeypatch, "I:/Geograph_DataSet")
    if not svc._IS_WINDOWS:
        pytest.skip("Windows 反斜杠展开仅在 win32 生效")
    parsed = json.loads(svc._expand_seed_placeholders(_SEED_TEMPLATE))
    assert (
        parsed["nodes"][0]["properties"]["local_dir"]
        == "I:\\Geograph_DataSet\\Meteorological\\GLDAS"
    )


def test_posix_platform_win_placeholder_uses_posix_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """硬编码清理 A3：Linux data_root + {DATA_ROOT_WIN} → 占位符退化为 posix root。

    原 ``root.replace("/", "\\\\")`` 在 Linux 下生成 ``\\srv\\geodata\\...``
    （POSIX 下反斜杠是文件名字符）→ 目录必不匹配。

    退化语义：占位符展开不再注入反斜杠（root 部分 posix 化）；模板中
    **字面**反斜杠不在占位符职责内（仓库种子已统一为 ``{DATA_ROOT}/``
    posix 模板，旧式 ``{DATA_ROOT_WIN}\\\\`` 模板已随 A3 清除）。
    """
    monkeypatch.setattr(svc, "_IS_WINDOWS", False)
    _patch_data_root(monkeypatch, "/srv/geodata")
    parsed = json.loads(svc._expand_seed_placeholders(_SEED_TEMPLATE))
    local_dir = parsed["nodes"][0]["properties"]["local_dir"]
    # 占位符 root 部分必须 posix（无反斜杠注入；模板字面 "\\" 紧随其后）
    assert local_dir.startswith("/srv/geodata")
    # 模板字面 ``\\\\``（JSON 转义反斜杠）保留原样，不由占位符退化负责
    assert "\\srv" not in local_dir and not local_dir.startswith("\\")


def test_posix_placeholder_normalizes_separators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_data_root(monkeypatch, r"I:\Geograph_DataSet")
    parsed = json.loads(svc._expand_seed_placeholders(_SEED_TEMPLATE))
    assert parsed["nodes"][0]["properties"]["path"] == "I:/Geograph_DataSet/SMAP"


def test_empty_data_root_still_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_data_root(monkeypatch, "")
    json.loads(svc._expand_seed_placeholders(_SEED_TEMPLATE))


def test_sync_skips_seed_that_expands_to_invalid_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    """展开后非法 JSON 时必须跳过写入，保留运行目录中的旧定义。"""
    seed_dir = tmp_path / "seeds"
    seed_dir.mkdir()
    (seed_dir / "broken.json").write_text('{"a": "{DATA_ROOT_WIN}"}', encoding="utf-8")
    dest_dir = tmp_path / "system"
    dest_dir.mkdir()
    dest = dest_dir / "broken.json"
    dest.write_text('{"a": "previous-good"}', encoding="utf-8")

    monkeypatch.setattr(svc, "_SEED_SYSTEM_DIR", seed_dir)
    monkeypatch.setattr(svc, "_SYSTEM_DIR", dest_dir)
    # 故意让展开结果非法：注入裸反斜杠构成非法转义 \G（\b 等是合法 JSON 转义）
    monkeypatch.setattr(svc, "_expand_seed_placeholders", lambda c: '{"a": "I:\\Geo"}')

    with caplog.at_level("ERROR"):
        svc._sync_system_seeds()

    assert dest.read_text(encoding="utf-8") == '{"a": "previous-good"}'
    assert "invalid JSON after placeholder expansion" in caplog.text
