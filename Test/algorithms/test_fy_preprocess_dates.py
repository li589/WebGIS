"""fy_preprocess 日期输入宽容解析：YYYY-MM-DD / YYYY.MM.DD / YYYYMMDD。"""

from __future__ import annotations

import unittest
from datetime import datetime

import contracts.job  # noqa: F401  # break modules.registry ↔ workflow.panel_schema cycle


class TestParseFyDate(unittest.TestCase):
    def _parse(self, value: str) -> datetime:
        from ingest.fy_preprocess import parse_fy_date

        return parse_fy_date(value)

    def test_iso_format(self) -> None:
        self.assertEqual(self._parse("2025-12-03"), datetime(2025, 12, 3))

    def test_compact_format_matches_seed_placeholder_expansion(self) -> None:
        """种子 {YYYYMMDD} 占位符展开后为紧凑格式（smoke 工具注入 20251203）。"""
        self.assertEqual(self._parse("20251203"), datetime(2025, 12, 3))

    def test_dotted_format(self) -> None:
        self.assertEqual(self._parse("2025.12.03"), datetime(2025, 12, 3))

    def test_whitespace_tolerated(self) -> None:
        self.assertEqual(self._parse("  2025-12-03  "), datetime(2025, 12, 3))

    def test_invalid_format_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._parse("2025/12/03")

    def test_build_date_keys_uses_compact_keys(self) -> None:
        from ingest.fy_preprocess import build_date_keys, parse_fy_date

        keys = build_date_keys(
            parse_fy_date("20251203"), parse_fy_date("2025-12-04")
        )
        self.assertEqual(keys, ["20251203", "20251204"])


if __name__ == "__main__":
    unittest.main()
