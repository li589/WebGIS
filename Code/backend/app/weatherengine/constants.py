from __future__ import annotations

from dataclasses import dataclass


OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True, slots=True)
class WeatherLayerSpec:
    layer_id: str
    display_name: str
    palette: str
    paint_mode: str
    default_opacity: float
    primary_metric: str
    primary_label: str
    unit_label: str
    summary_template: str
    current_fields: tuple[str, ...]
    hourly_fields: tuple[str, ...]
    legend_ticks: tuple[float | int | str, ...]
    notes: tuple[str, ...]


WEATHER_LAYER_SPECS: dict[str, WeatherLayerSpec] = {
    "wind-field": WeatherLayerSpec(
        layer_id="wind-field",
        display_name="Wind Field",
        palette="wind-blue",
        paint_mode="point_symbol",
        default_opacity=0.82,
        primary_metric="wind_speed_10m",
        primary_label="Wind Speed",
        unit_label="m/s",
        summary_template="Current 10 m wind speed is {value} {unit}.",
        current_fields=("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"),
        hourly_fields=("wind_speed_10m", "temperature_2m", "precipitation"),
        legend_ticks=(0, 5, 10, 15, 20),
        notes=(
            "Use a cool blue ramp for point symbols and labels.",
            "Future raster layer should derive wind barb or particle flow styling from the same metric.",
        ),
    ),
    "temperature": WeatherLayerSpec(
        layer_id="temperature",
        display_name="Temperature",
        palette="thermal-orange",
        paint_mode="grid_fill",
        default_opacity=0.58,
        primary_metric="temperature_2m",
        primary_label="Temperature",
        unit_label="C",
        summary_template="Current 2 m temperature is {value} {unit}.",
        current_fields=("temperature_2m", "apparent_temperature", "cloud_cover"),
        hourly_fields=("temperature_2m", "wind_speed_10m", "precipitation"),
        legend_ticks=(-10, 0, 10, 20, 30, 40),
        notes=(
            "Use a warm sequential ramp and preserve strong contrast against the dark basemap.",
            "Raster styling can later reuse the same breakpoints for COG or tiles.",
        ),
    ),
    "precipitation": WeatherLayerSpec(
        layer_id="precipitation",
        display_name="Precipitation",
        palette="precip-cyan",
        paint_mode="grid_fill",
        default_opacity=0.74,
        primary_metric="precipitation",
        primary_label="Precipitation",
        unit_label="mm",
        summary_template="Current precipitation intensity is {value} {unit}.",
        current_fields=("precipitation", "rain", "weather_code", "cloud_cover"),
        hourly_fields=("precipitation", "temperature_2m", "wind_speed_10m"),
        legend_ticks=(0, 1, 5, 10, 25, 50),
        notes=(
            "Use cyan to blue classes and reserve higher opacity for strong rain rates.",
            "Raster output should prefer masked precipitation cells over full-frame haze.",
        ),
    ),
}


DEFAULT_LAYER_ID = "wind-field"
DEFAULT_POINT = {
    "latitude": 23.1291,
    "longitude": 113.2644,
    "place_name": "Guangzhou",
}
