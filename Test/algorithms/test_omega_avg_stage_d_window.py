from __future__ import annotations

import unittest

from algorithms.omega_avg import (
    OmegaAvgConfig,
    _apply_stage_d_window,
    _iter_date_keys_for_year,
)


class TestOmegaAvgStageDWindow(unittest.TestCase):
    def test_filters_by_date_range_and_max_days(self) -> None:
        keys = _iter_date_keys_for_year(2025)
        config = OmegaAvgConfig(
            stage_d_start_date="2025-12-01",
            stage_d_end_date="2025-12-31",
            stage_d_max_days=5,
        )
        out = _apply_stage_d_window(keys, config)
        self.assertEqual(len(out), 5)
        self.assertEqual(out[0], "20251201")
        self.assertEqual(out[-1], "20251205")

    def test_no_window_keeps_full_year(self) -> None:
        keys = _iter_date_keys_for_year(2024)  # leap year
        out = _apply_stage_d_window(keys, OmegaAvgConfig())
        self.assertEqual(len(out), 366)


if __name__ == "__main__":
    unittest.main()
