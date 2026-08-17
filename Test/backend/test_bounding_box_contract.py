"""BoundingBox 契约：跨日界线视口（unwrap east/west >180）与顺序校验。

对齐 layer_router Query(ge=-180, le=360)：unwrap 后 east 可到 235.5 等值，
west 同步放宽；west<=east 不强制（170..-170 跨日界线合法）；仅强制 south<=north。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.contracts.api_contracts import BoundingBox


def test_standard_bbox_accepted() -> None:
    box = BoundingBox(west=-180.0, south=-90.0, east=180.0, north=90.0)
    assert box.crs == "EPSG:4326"


def test_unwrapped_east_above_180_accepted() -> None:
    """unwrap 视口（如 170..235.5）是 /workflow-runs 500 修复的目标场景。"""
    box = BoundingBox(west=170.0, south=10.0, east=235.5, north=40.0)
    assert box.east == 235.5


def test_unwrapped_west_above_180_accepted() -> None:
    BoundingBox(west=190.0, south=-45.0, east=300.0, north=-10.0)


def test_antimeridian_wrapped_bounds_accepted() -> None:
    """west=170, east=-170（未 unwrap 的跨日界线写法）不强制 west<=east。"""
    BoundingBox(west=170.0, south=-20.0, east=-170.0, north=20.0)


def test_south_above_north_rejected() -> None:
    with pytest.raises(ValidationError, match="south must be <= north"):
        BoundingBox(west=0.0, south=30.0, east=10.0, north=10.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("west", -180.5),
        ("west", 360.5),
        ("east", -180.5),
        ("east", 360.5),
        ("south", -90.5),
        ("south", 90.5),
        ("north", -90.5),
        ("north", 90.5),
    ],
)
def test_out_of_range_bounds_rejected(field: str, value: float) -> None:
    payload = {"west": 0.0, "south": 0.0, "east": 10.0, "north": 10.0}
    payload[field] = value
    with pytest.raises(ValidationError):
        BoundingBox(**payload)  # type: ignore[arg-type]
