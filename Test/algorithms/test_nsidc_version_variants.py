"""NSIDC granule 搜索 version 变体归一化测试。

CMR ``version_id`` 为 3 位零填充（SPL3SMP_E V6 = ``006``）；节点模板写 "6"
原样透传会 0 命中并被误判为"该日无数据"（2026-08-17 在线 run 失败根因）。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ingest.nsidc_download import Granule, _version_variants, search_granules


class TestVersionVariants(unittest.TestCase):
    def test_short_numeric_padded(self) -> None:
        self.assertEqual(_version_variants("6"), ["6", "006"])
        self.assertEqual(_version_variants("5"), ["5", "005"])

    def test_already_padded_kept_once(self) -> None:
        self.assertEqual(_version_variants("006"), ["006"])

    def test_non_numeric_unchanged(self) -> None:
        self.assertEqual(_version_variants("2.1"), ["2.1"])
        self.assertEqual(_version_variants("02"), ["02", "002"])

    def test_empty(self) -> None:
        self.assertEqual(_version_variants(""), [""])
        self.assertEqual(_version_variants("  "), [""])


class TestSearchGranuleFallback(unittest.TestCase):
    def test_retries_with_padded_version_on_empty(self) -> None:
        calls: list[str] = []

        def fake_search(start, end, short_name, version, user, pwd):  # noqa: ANN001
            calls.append(version)
            if version == "006":
                return [Granule(name="SMAP_L3_SM_P_E_20251227.h5", url="https://x/SMAP_L3_SM_P_E_20251227.h5")]
            return []

        with patch("ingest.nsidc_download._HAS_EARTHACCESS", True), patch(
            "ingest.nsidc_download._search_via_earthaccess", side_effect=fake_search
        ):
            granules = search_granules("2025-12-27", "2025-12-27", version="6")

        self.assertEqual(calls, ["6", "006"])
        self.assertEqual(len(granules), 1)
        self.assertIn("20251227", granules[0].name)

    def test_stops_at_first_non_empty_variant(self) -> None:
        calls: list[str] = []

        def fake_search(start, end, short_name, version, user, pwd):  # noqa: ANN001
            calls.append(version)
            return [Granule(name="a.h5", url="https://x/a.h5")] if version == "6" else []

        with patch("ingest.nsidc_download._HAS_EARTHACCESS", True), patch(
            "ingest.nsidc_download._search_via_earthaccess", side_effect=fake_search
        ):
            search_granules("2025-12-27", "2025-12-27", version="6")

        self.assertEqual(calls, ["6"])

    def test_cmr_fallback_uses_variants_too(self) -> None:
        calls: list[str] = []

        def fake_cmr(start, end, short_name, version):  # noqa: ANN001
            calls.append(version)
            return []

        with patch("ingest.nsidc_download._HAS_EARTHACCESS", False), patch(
            "ingest.nsidc_download._search_via_cmr", side_effect=fake_cmr
        ):
            result = search_granules("2025-12-27", "2025-12-27", version="6")

        self.assertEqual(calls, ["6", "006"])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
