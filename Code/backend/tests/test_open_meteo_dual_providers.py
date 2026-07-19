"""Tests for open-meteo-online / open-meteo-local split and layer provider listing."""

from __future__ import annotations

import unittest

from app.weatherengine.field_mapping import SURFACE_LAYER_IDS
from app.weatherengine.fetch_gateway import list_providers_for_layer, resolve_provider_for_layer
from app.weatherengine.provider_ids import (
    OPEN_METEO_LOCAL_ID,
    OPEN_METEO_ONLINE_ID,
    normalize_provider_id,
    provider_grid_mode,
)
from app.weatherengine.provider_registry import get_registry, register_default_providers
from app.weatherengine.constants import WEATHER_LAYER_SPECS


class OpenMeteoDualProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        registry = get_registry()
        registry.clear()
        register_default_providers()

    def tearDown(self) -> None:
        get_registry().clear()

    def test_normalize_legacy_alias(self) -> None:
        self.assertEqual(normalize_provider_id("open-meteo"), OPEN_METEO_ONLINE_ID)
        self.assertEqual(normalize_provider_id(OPEN_METEO_LOCAL_ID), OPEN_METEO_LOCAL_ID)

    def test_resolve_local_best_match_to_ecmwf(self) -> None:
        from app.weatherengine.provider_ids import resolve_open_meteo_model

        self.assertEqual(
            resolve_open_meteo_model("best_match", provider_id=OPEN_METEO_LOCAL_ID),
            "ecmwf_ifs025",
        )
        self.assertEqual(
            resolve_open_meteo_model("best_match", provider_id=OPEN_METEO_ONLINE_ID),
            "best_match",
        )
        self.assertEqual(
            resolve_open_meteo_model("ecmwf_ifs025", provider_id=OPEN_METEO_LOCAL_ID),
            "ecmwf_ifs025",
        )

    def test_both_open_meteo_registered(self) -> None:
        registry = get_registry()
        self.assertIsNotNone(registry.get_provider(OPEN_METEO_ONLINE_ID))
        self.assertIsNotNone(registry.get_provider(OPEN_METEO_LOCAL_ID))
        self.assertIsNone(registry.get_provider("open-meteo"))

    def test_resolve_legacy_pin(self) -> None:
        provider = resolve_provider_for_layer("wind-field", provider_id="open-meteo")
        self.assertEqual(provider.provider_id, OPEN_METEO_ONLINE_ID)

    def test_wind_field_lists_both_om(self) -> None:
        rows = list_providers_for_layer("wind-field")
        ids = {r["provider_id"] for r in rows}
        self.assertIn(OPEN_METEO_ONLINE_ID, ids)
        self.assertIn(OPEN_METEO_LOCAL_ID, ids)
        for row in rows:
            if row["provider_id"].startswith("open-meteo"):
                self.assertEqual(row["grid_mode"], "dense")

    def test_pressure_level_only_om(self) -> None:
        rows = list_providers_for_layer("wind-field-850hPa", include_disabled=True)
        ids = {r["provider_id"] for r in rows}
        self.assertIn(OPEN_METEO_ONLINE_ID, ids)
        self.assertIn(OPEN_METEO_LOCAL_ID, ids)
        self.assertNotIn("weatherapi", ids)
        self.assertNotIn("openweather", ids)

    def test_commercial_surface_expanded(self) -> None:
        self.assertIn("pressure", SURFACE_LAYER_IDS)
        self.assertIn("visibility", SURFACE_LAYER_IDS)
        registry = get_registry()
        wapi = registry.get_provider("weatherapi")
        self.assertIsNotNone(wapi)
        assert wapi is not None
        self.assertTrue(wapi.supports_layer("pressure"))
        self.assertTrue(wapi.supports_layer("visibility"))
        self.assertFalse(wapi.supports_layer("wind-field-850hPa"))
        self.assertFalse(wapi.supports_layer("cloud-cover"))

    def test_new_layer_specs(self) -> None:
        self.assertIn("cloud-cover", WEATHER_LAYER_SPECS)
        self.assertIn("dewpoint", WEATHER_LAYER_SPECS)
        self.assertEqual(provider_grid_mode("weatherapi"), "sparse")


if __name__ == "__main__":
    unittest.main()
