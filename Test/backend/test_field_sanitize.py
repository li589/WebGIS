"""字段名规范化：空名 / 保留字 / DBF 10 字节 / 重复。"""

from __future__ import annotations

from app.data_io.services.vector import sanitize_field_names


def test_sanitize_empty_reserved_truncate_dup():
    fields = ["", "ID", "很长的中文字段名ABC", "name", "name", "  x\t"]
    sanitized, changes = sanitize_field_names(fields, encoding="utf-8")
    assert len(sanitized) == len(fields)
    assert sanitized[0].startswith("field_")
    assert sanitized[1] != "ID" or any(c["original"] == "ID" for c in changes)
    # 保留字 ID 应变更
    assert any(c["original"] == "ID" for c in changes)
    # DBF 10 字节截断（utf-8 中文多字节）
    assert all(len(s.encode("utf-8")) <= 10 for s in sanitized)
    # 重复 name
    assert sanitized[3] != sanitized[4] or any(
        c["original"] == "name" for c in changes
    )
    assert changes
