"""日期写法与「平均」形态词的口径锁（2026-11-08 外部复测两条失败）。

1. **非法日期不许静默沿用旧值**：用户问「20251301 那天多少」，13 月不是日期，
   旧实现解析失败 ⇒ 当「没给日期」⇒ 拿上一轮的 11-16 取数，正文还写
   「你请求的日期是 2025-11-16」，把系统补的日期说成用户请求的。
2. **「平均多少」是统计动词，不是「要平均版产品」**：页面开着动态版时，
   「这几天平均多少」被判成点了「平均版」⇒ 与页面层冲突 ⇒ 丢掉页面那层
   反问「本机有两个版本」，明明页面上就开着。

纯函数级，不连数据、不启动 app。
"""

from __future__ import annotations

import pytest

from app.services.agent.mock_orchestrator import (
    _contradicts_hints,
    _invalid_date_hint,
    _parse_date_arg,
)

DYN = {
    "catalog_id": "imported-a8940443fd6d",
    "name": "SMAP 动态散射约束产品 · 土壤水分",
    "variable": "sm",
}
AVG = {
    "catalog_id": "imported-136c60293bbf",
    "name": "SMAP 平均散射约束产品 · 土壤水分",
    "variable": "sm",
}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("20251301 那天广州市土壤水分多少", "20251301"),
        ("2025-13-01 呢", "2025-13-01"),
        ("20251131 广州市", "20251131"),
        ("2025年2月30日呢", "2025年2月30日"),
        ("2025-11-09 到 2025-11-16", None),
        ("11 月 9 日到 16 日", None),
        ("20251113 那天多少", None),
        ("广州市土壤水分多少", None),
        ("整幅有 350251559 个像元", None),
    ],
)
def test_invalid_date_hint(message, expected):
    assert _invalid_date_hint(message) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("20251113 那天多少", "2025-11-13"),
        ("2025-11-13", "2025-11-13"),
        ("2025年11月13日", "2025-11-13"),
        ("2025/11/13", "2025-11-13"),
        ("20251301 那天", None),
        ("20251131 那天", None),
        ("没有日期", None),
    ],
)
def test_parse_date_arg(message, expected):
    assert _parse_date_arg(message) == expected


@pytest.mark.parametrize(
    "message",
    ["这几天平均多少", "广州市这几天的平均值是多少", "帮我平均一下"],
)
def test_average_as_statistic_verb_is_not_product_form(message):
    """「平均」后面跟统计谓语 ⇒ 不是在点平均版那一层，不该与动态版冲突。"""
    assert _contradicts_hints(message, DYN) is False


@pytest.mark.parametrize("message", ["换成平均版", "平均产品的土壤水分"])
def test_average_as_product_form_still_detected(message):
    assert _contradicts_hints(message, DYN) is True


@pytest.mark.parametrize("message", ["换成动态版", "动态的土壤水分"])
def test_dynamic_form_still_detected(message):
    assert _contradicts_hints(message, AVG) is True
