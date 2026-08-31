"""Verify that SURFACE/HEIGHT/PRESSURE_LAYER_IDS are correctly derived from
WEATHER_LAYER_SPECS.layer_kind (N2 double-registration elimination).

The sets used to be hardcoded in field_mapping.py, duplicating the layer
information already in constants.WEATHER_LAYER_SPECS. Now they are derived
from specs.layer_kind. This test guards against regressions by asserting:
  1. Every spec has a valid layer_kind ("surface" / "height" / "pressure").
  2. The derived sets partition all specs (no spec is in two sets, no spec
     is missing).
  3. The derived sets match the expected hardcoded values from the pre-refactor
     era, so existing consumers see no change.
"""

from __future__ import annotations

from app.weatherengine.constants import WEATHER_LAYER_SPECS
from app.weatherengine.field_mapping import (
    HEIGHT_LAYER_IDS,
    PRESSURE_LAYER_IDS,
    SURFACE_LAYER_IDS,
)

_EXPECTED_SURFACE = frozenset(
    {
        "wind-field",
        "temperature",
        "precipitation",
        "humidity",
        "pressure",
        "visibility",
        "cloud-cover",
        "dewpoint",
    }
)
_EXPECTED_HEIGHT = frozenset(
    {
        "wind-field-80m",
        "wind-field-120m",
        "wind-field-180m",
        "temperature-80m",
        "temperature-120m",
        "temperature-180m",
    }
)
_EXPECTED_PRESSURE = frozenset(
    {
        "wind-field-850hPa",
        "wind-field-500hPa",
        "wind-field-200hPa",
    }
)

_VALID_KINDS = {"surface", "height", "pressure"}


def test_every_spec_has_valid_layer_kind():
    for layer_id, spec in WEATHER_LAYER_SPECS.items():
        kind = getattr(spec, "layer_kind", None)
        assert kind in _VALID_KINDS, (
            f"spec '{layer_id}' has invalid layer_kind='{kind}' "
            f"(expected one of {_VALID_KINDS})"
        )


def test_derived_sets_partition_all_specs():
    all_ids = set(WEATHER_LAYER_SPECS.keys())
    derived = SURFACE_LAYER_IDS | HEIGHT_LAYER_IDS | PRESSURE_LAYER_IDS
    assert derived == all_ids, (
        f"Mismatch: specs have {len(all_ids)} layers but derived sets "
        f"have {len(derived)}. Missing: {all_ids - derived}, "
        f"Extra: {derived - all_ids}"
    )
    # No overlap
    assert not (SURFACE_LAYER_IDS & HEIGHT_LAYER_IDS)
    assert not (SURFACE_LAYER_IDS & PRESSURE_LAYER_IDS)
    assert not (HEIGHT_LAYER_IDS & PRESSURE_LAYER_IDS)


def test_surface_set_matches_expected():
    assert SURFACE_LAYER_IDS == _EXPECTED_SURFACE


def test_height_set_matches_expected():
    assert HEIGHT_LAYER_IDS == _EXPECTED_HEIGHT


def test_pressure_set_matches_expected():
    assert PRESSURE_LAYER_IDS == _EXPECTED_PRESSURE


def test_pressure_specs_have_pressure_levels():
    """Every pressure-kind spec must declare its pressure_levels tuple."""
    for layer_id, spec in WEATHER_LAYER_SPECS.items():
        if spec.layer_kind == "pressure":
            assert spec.pressure_levels, (
                f"pressure-kind spec '{layer_id}' has empty pressure_levels"
            )


def test_height_specs_have_no_pressure_levels():
    """Height-kind specs should not carry pressure_levels."""
    for layer_id, spec in WEATHER_LAYER_SPECS.items():
        if spec.layer_kind == "height":
            assert not spec.pressure_levels, (
                f"height-kind spec '{layer_id}' has non-empty pressure_levels "
                f"{spec.pressure_levels}"
            )
