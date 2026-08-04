"""Tests for open-meteo-online / open-meteo-local split and layer provider listing."""

from __future__ import annotations

import unittest

from app.weatherengine.field_mapping import SURFACE_LAYER_IDS
from app.weatherengine.fetch_gateway import (
    list_providers_for_layer,
    resolve_provider_for_layer,
)
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
        self.assertEqual(
            normalize_provider_id(OPEN_METEO_LOCAL_ID), OPEN_METEO_LOCAL_ID
        )

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
        by_id = {p.provider_id: pri for p, pri, _en in registry.list_provider_entries()}
        self.assertEqual(by_id[OPEN_METEO_LOCAL_ID], 0)
        self.assertEqual(by_id[OPEN_METEO_ONLINE_ID], 1)

    def test_auto_resolve_prefers_local(self) -> None:
        provider = resolve_provider_for_layer("wind-field")
        self.assertEqual(provider.provider_id, OPEN_METEO_LOCAL_ID)

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

    def test_pressure_level_lists_commercial_sparse(self) -> None:
        rows = list_providers_for_layer("wind-field-850hPa", include_disabled=True)
        by_id = {r["provider_id"]: r for r in rows}
        self.assertIn(OPEN_METEO_ONLINE_ID, by_id)
        self.assertIn(OPEN_METEO_LOCAL_ID, by_id)
        self.assertIn("weatherapi", by_id)
        self.assertIn("openweather", by_id)
        self.assertEqual(by_id["weatherapi"]["data_quality"], "sparse")
        self.assertIn("气压", by_id["weatherapi"]["hint"])

    def test_commercial_covers_all_catalog_layers(self) -> None:
        self.assertIn("pressure", SURFACE_LAYER_IDS)
        self.assertIn("visibility", SURFACE_LAYER_IDS)
        self.assertIn("cloud-cover", SURFACE_LAYER_IDS)
        self.assertIn("dewpoint", SURFACE_LAYER_IDS)
        registry = get_registry()
        wapi = registry.get_provider("weatherapi")
        ow = registry.get_provider("openweather")
        self.assertIsNotNone(wapi)
        self.assertIsNotNone(ow)
        assert wapi is not None and ow is not None
        for layer_id in WEATHER_LAYER_SPECS:
            self.assertTrue(wapi.supports_layer(layer_id), layer_id)
            self.assertTrue(ow.supports_layer(layer_id), layer_id)

        height_rows = list_providers_for_layer("wind-field-80m", include_disabled=True)
        height_wapi = next(r for r in height_rows if r["provider_id"] == "weatherapi")
        self.assertEqual(height_wapi["data_quality"], "extrapolated")

        surface_rows = list_providers_for_layer("cloud-cover", include_disabled=True)
        surface_wapi = next(r for r in surface_rows if r["provider_id"] == "weatherapi")
        self.assertEqual(surface_wapi["data_quality"], "observed")

    def test_new_layer_specs(self) -> None:
        self.assertIn("cloud-cover", WEATHER_LAYER_SPECS)
        self.assertIn("dewpoint", WEATHER_LAYER_SPECS)
        self.assertEqual(provider_grid_mode("weatherapi"), "sparse")
        self.assertEqual(len(WEATHER_LAYER_SPECS), 17)


if __name__ == "__main__":
    unittest.main()
