"""统计 JSON NaN 安全化测试（数值专项 W1）。

全 NaN 栅格的统计量（mean/std/min/max）为 NaN，旧实现
``json.dumps`` 默认 ``allow_nan=True`` 产出含 ``NaN`` 字面量的非法
JSON，前端 ``JSON.parse`` 抛错。修复后 ``_json_safe`` 递归转 None +
``allow_nan=False`` 硬门。
"""

from __future__ import annotations

import json
import math

import numpy as np

import contracts.job  # noqa: F401  (先行导入打破 modules 循环导入，见 test_gldas_nc4_to_mat.py)
from modules.statistics import _json_safe as _json_safe_stats
from modules.stats_histogram import _json_safe as _json_safe_hist


def test_json_safe_scalar_nonfinite_to_none() -> None:
    for bad in (float("nan"), float("inf"), float("-inf"), np.float64("nan")):
        for sanitizer in (_json_safe_stats, _json_safe_hist):
            assert sanitizer(bad) is None


def test_json_safe_preserves_finite_and_ints() -> None:
    payload = {"mean": 3.5, "count": 10, "name": "ts", "ok": True}
    assert _json_safe_stats(payload) == payload
    assert _json_safe_hist(payload) == payload


def test_json_safe_recursive_containers() -> None:
    payload = {
        "series": [{"x": [1, 2], "y": [float("nan"), 2.0]}],
        "rows": [[float("nan"), 1.0], [float("inf"), None]],
        "nested": {"deep": {"v": float("-inf")}},
    }
    out = _json_safe_stats(payload)
    assert out["series"][0]["y"] == [None, 2.0]
    assert out["rows"] == [[None, 1.0], [None, None]]
    assert out["nested"]["deep"]["v"] is None


def test_all_nan_stats_payload_is_parseable_json() -> None:
    """全 NaN 栅格统计 payload → json.loads 可解析且含 null。"""
    stats_payload = {
        "schema_version": "1",
        "series": [{"name": "mean", "x": [0, 1], "y": [float("nan")] * 2}],
        "rows": [[0, float("nan"), float("nan")], [1, float("nan"), float("nan")]],
        "stats": {
            "count": 0.0,
            "mean": float("nan"),
            "std": float("nan"),
            "min": float("nan"),
            "max": float("nan"),
        },
    }
    for sanitizer in (_json_safe_stats, _json_safe_hist):
        text = json.dumps(sanitizer(stats_payload), allow_nan=False)
        assert "NaN" not in text and "Infinity" not in text
        parsed = json.loads(text)
        assert parsed["stats"]["mean"] is None
        assert parsed["series"][0]["y"] == [None, None]


def test_dumps_hard_gate_rejects_leaked_nan() -> None:
    """allow_nan=False 硬门：未经清洗的 NaN 必须显式报错而非静默写非法 JSON。"""
    with_math_nan = {"mean": math.nan}
    try:
        json.dumps(with_math_nan, allow_nan=False)
    except ValueError:
        pass
    else:
        raise AssertionError("allow_nan=False 应拒绝 NaN")
