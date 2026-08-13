"""Tests for open-meteo-online / open-meteo-local split and layer provider listing."""

from __future__ import annotations


import pytest
import types
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


@pytest.fixture
def _open_meteo_dual_provider_tests_env():
    ns = types.SimpleNamespace()
    registry = get_registry()
    registry.clear()
    register_default_providers()
    yield ns
    get_registry().clear()


def test_normalize_legacy_alias(_open_meteo_dual_provider_tests_env) -> None:
    self = _open_meteo_dual_provider_tests_env
    assert normalize_provider_id("open-meteo") == OPEN_METEO_ONLINE_ID, 'normalize_provider_id("open-meteo") == OPEN_METEO_ONLINE_ID'
    assert normalize_provider_id(OPEN_METEO_LOCAL_ID) == OPEN_METEO_LOCAL_ID, 'normalize_provider_id(OPEN_METEO_LOCAL_ID) == OPEN_METEO_LOCAL_ID'


def test_resolve_local_best_match_to_ecmwf(_open_meteo_dual_provider_tests_env) -> None:
    self = _open_meteo_dual_provider_tests_env
    from app.weatherengine.provider_ids import resolve_open_meteo_model

    assert resolve_open_meteo_model("best_match", provider_id=OPEN_METEO_LOCAL_ID) == "ecmwf_ifs025", 'resolve_open_meteo_model("best_match", provider_id=OPEN_METEO_LOCAL_ID) == "ecmwf_ifs025"'
    assert resolve_open_meteo_model("best_match", provider_id=OPEN_METEO_ONLINE_ID) == "best_match", 'resolve_open_meteo_model("best_match", provider_id=OPEN_METEO_ONLINE_ID) == "best_match"'
    assert resolve_open_meteo_model("ecmwf_ifs025", provider_id=OPEN_METEO_LOCAL_ID) == "ecmwf_ifs025", 'resolve_open_meteo_model("ecmwf_ifs025", provider_id=OPEN_METEO_LOCAL_ID) == "ecmwf_ifs025"'


def test_both_open_meteo_registered(_open_meteo_dual_provider_tests_env) -> None:
    self = _open_meteo_dual_provider_tests_env
    registry = get_registry()
    assert registry.get_provider(OPEN_METEO_ONLINE_ID) is not None, 'registry.get_provider(OPEN_METEO_ONLINE_ID) is not None'
    assert registry.get_provider(OPEN_METEO_LOCAL_ID) is not None, 'registry.get_provider(OPEN_METEO_LOCAL_ID) is not None'
    assert registry.get_provider("open-meteo") is None, 'registry.get_provider("open-meteo") is None'
    by_id = {p.provider_id: pri for p, pri, _en in registry.list_provider_entries()}
    assert by_id[OPEN_METEO_LOCAL_ID] == 0, 'by_id[OPEN_METEO_LOCAL_ID] == 0'
    assert by_id[OPEN_METEO_ONLINE_ID] == 1, 'by_id[OPEN_METEO_ONLINE_ID] == 1'


def test_auto_resolve_prefers_local(_open_meteo_dual_provider_tests_env) -> None:
    self = _open_meteo_dual_provider_tests_env
    provider = resolve_provider_for_layer("wind-field")
    assert provider.provider_id == OPEN_METEO_LOCAL_ID, 'provider.provider_id == OPEN_METEO_LOCAL_ID'


def test_resolve_legacy_pin(_open_meteo_dual_provider_tests_env) -> None:
    self = _open_meteo_dual_provider_tests_env
    provider = resolve_provider_for_layer("wind-field", provider_id="open-meteo")
    assert provider.provider_id == OPEN_METEO_ONLINE_ID, 'provider.provider_id == OPEN_METEO_ONLINE_ID'


def test_wind_field_lists_both_om(_open_meteo_dual_provider_tests_env) -> None:
    self = _open_meteo_dual_provider_tests_env
    rows = list_providers_for_layer("wind-field")
    ids = {r["provider_id"] for r in rows}
    assert OPEN_METEO_ONLINE_ID in ids, 'OPEN_METEO_ONLINE_ID in ids'
    assert OPEN_METEO_LOCAL_ID in ids, 'OPEN_METEO_LOCAL_ID in ids'
    for row in rows:
        if row["provider_id"].startswith("open-meteo"):
            assert row["grid_mode"] == "dense", 'row["grid_mode"] == "dense"'


def test_pressure_level_lists_commercial_sparse(_open_meteo_dual_provider_tests_env) -> None:
    self = _open_meteo_dual_provider_tests_env
    rows = list_providers_for_layer("wind-field-850hPa", include_disabled=True)
    by_id = {r["provider_id"]: r for r in rows}
    assert OPEN_METEO_ONLINE_ID in by_id, 'OPEN_METEO_ONLINE_ID in by_id'
    assert OPEN_METEO_LOCAL_ID in by_id, 'OPEN_METEO_LOCAL_ID in by_id'
    assert "weatherapi" in by_id, '"weatherapi" in by_id'
    assert "openweather" in by_id, '"openweather" in by_id'
    assert by_id["weatherapi"]["data_quality"] == "sparse", 'by_id["weatherapi"]["data_quality"] == "sparse"'
    assert "气压" in by_id["weatherapi"]["hint"], '"气压" in by_id["weatherapi"]["hint"]'


def test_commercial_covers_all_catalog_layers(_open_meteo_dual_provider_tests_env) -> None:
    self = _open_meteo_dual_provider_tests_env
    assert "pressure" in SURFACE_LAYER_IDS, '"pressure" in SURFACE_LAYER_IDS'
    assert "visibility" in SURFACE_LAYER_IDS, '"visibility" in SURFACE_LAYER_IDS'
    assert "cloud-cover" in SURFACE_LAYER_IDS, '"cloud-cover" in SURFACE_LAYER_IDS'
    assert "dewpoint" in SURFACE_LAYER_IDS, '"dewpoint" in SURFACE_LAYER_IDS'
    registry = get_registry()
    wapi = registry.get_provider("weatherapi")
    ow = registry.get_provider("openweather")
    assert wapi is not None, 'wapi is not None'
    assert ow is not None, 'ow is not None'
    assert wapi is not None and ow is not None
    for layer_id in WEATHER_LAYER_SPECS:
        assert wapi.supports_layer(layer_id), layer_id
        assert ow.supports_layer(layer_id), layer_id

    height_rows = list_providers_for_layer("wind-field-80m", include_disabled=True)
    height_wapi = next(r for r in height_rows if r["provider_id"] == "weatherapi")
    assert height_wapi["data_quality"] == "extrapolated", 'height_wapi["data_quality"] == "extrapolated"'

    surface_rows = list_providers_for_layer("cloud-cover", include_disabled=True)
    surface_wapi = next(r for r in surface_rows if r["provider_id"] == "weatherapi")
    assert surface_wapi["data_quality"] == "observed", 'surface_wapi["data_quality"] == "observed"'


def test_new_layer_specs(_open_meteo_dual_provider_tests_env) -> None:
    self = _open_meteo_dual_provider_tests_env
    assert "cloud-cover" in WEATHER_LAYER_SPECS, '"cloud-cover" in WEATHER_LAYER_SPECS'
    assert "dewpoint" in WEATHER_LAYER_SPECS, '"dewpoint" in WEATHER_LAYER_SPECS'
    assert provider_grid_mode("weatherapi") == "sparse", 'provider_grid_mode("weatherapi") == "sparse"'
    assert len(WEATHER_LAYER_SPECS) == 17, 'len(WEATHER_LAYER_SPECS) == 17'
