from __future__ import annotations

from dataclasses import dataclass


OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# 断路器参数：API 连续失败后打开断路器，RECOVERY_TIMEOUT 秒内直接返回 stale cache
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 10  # 连续失败次数阈值，达到后打开断路器（提高以减少误触发）
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 30   # OPEN 状态持续时间（秒），超时后转为 HALF_OPEN（缩短恢复时间）
CIRCUIT_BREAKER_HALF_OPEN_PROBES = 2    # HALF_OPEN 状态允许的探测请求数（增加探测机会）

# 每日 API 预算：Open-Meteo 免费版每日限额 ~10000 次，预留 2000 次缓冲
OPEN_METEO_DAILY_API_LIMIT = 8000
# 软限制（80%）：超过后开始警告，前端可显示"接近限额"提示
OPEN_METEO_DAILY_API_SOFT_LIMIT = 6400


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
    # 气压层变量需要的压力等级（hPa），空 tuple 表示不需要 pressure_levels 参数
    pressure_levels: tuple[int, ...] = ()


WEATHER_LAYER_SPECS: dict[str, WeatherLayerSpec] = {
    "wind-field": WeatherLayerSpec(
        layer_id="wind-field",
        display_name="Wind Field",
        palette="wind-blue",
        paint_mode="particle_flow",
        default_opacity=0.82,
        primary_metric="wind_speed_10m",
        primary_label="Wind Speed",
        unit_label="m/s",
        summary_template="Current 10 m wind speed is {value} {unit}.",
        current_fields=("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"),
        hourly_fields=("wind_speed_10m", "wind_direction_10m", "temperature_2m", "precipitation"),
        legend_ticks=(0, 5, 10, 15, 20, 25, 30),
        notes=(
            "Particle flow field: 1000 particles animated along wind vectors with trailing fade.",
            "Color scheme: blue->teal->green->yellow->red->purple (Windy-style).",
            "Falls back to point_symbol if canvas is unavailable.",
        ),
    ),
    "wind-field-80m": WeatherLayerSpec(
        layer_id="wind-field-80m",
        display_name="Wind Field 80m",
        palette="wind-blue",
        paint_mode="particle_flow",
        default_opacity=0.82,
        primary_metric="wind_speed_80m",
        primary_label="Wind Speed 80m",
        unit_label="m/s",
        summary_template="Current 80 m wind speed is {value} {unit}.",
        current_fields=("wind_speed_80m", "wind_direction_80m", "wind_gusts_10m"),
        hourly_fields=("wind_speed_80m", "wind_direction_80m", "temperature_80m", "precipitation"),
        legend_ticks=(0, 5, 10, 15, 20),
        notes=(
            "80 m AGL wind field — typical hub-height for modern wind turbines.",
            "Particle flow field reuses the 10m renderer with 80m vectors.",
        ),
    ),
    "wind-field-120m": WeatherLayerSpec(
        layer_id="wind-field-120m",
        display_name="Wind Field 120m",
        palette="wind-blue",
        paint_mode="particle_flow",
        default_opacity=0.82,
        primary_metric="wind_speed_120m",
        primary_label="Wind Speed 120m",
        unit_label="m/s",
        summary_template="Current 120 m wind speed is {value} {unit}.",
        current_fields=("wind_speed_120m", "wind_direction_120m", "wind_gusts_10m"),
        hourly_fields=("wind_speed_120m", "wind_direction_120m", "temperature_120m", "precipitation"),
        legend_ticks=(0, 5, 10, 15, 20, 25),
        notes=(
            "120 m AGL wind field — offshore / large turbine hub-height layer.",
            "Particle flow field reuses the 10m renderer with 120m vectors.",
        ),
    ),
    "wind-field-180m": WeatherLayerSpec(
        layer_id="wind-field-180m",
        display_name="Wind Field 180m",
        palette="wind-blue",
        paint_mode="particle_flow",
        default_opacity=0.82,
        primary_metric="wind_speed_180m",
        primary_label="Wind Speed 180m",
        unit_label="m/s",
        summary_template="Current 180 m wind speed is {value} {unit}.",
        current_fields=("wind_speed_180m", "wind_direction_180m", "wind_gusts_10m"),
        hourly_fields=("wind_speed_180m", "wind_direction_180m", "temperature_180m", "precipitation"),
        legend_ticks=(0, 7, 14, 21, 28, 35),
        notes=(
            "180 m AGL wind field — boundary-layer top reference wind.",
            "Particle flow field reuses the 10m renderer with 180m vectors.",
        ),
    ),
    "wind-field-850hPa": WeatherLayerSpec(
        layer_id="wind-field-850hPa",
        display_name="Wind Field 850hPa",
        palette="wind-blue",
        paint_mode="particle_flow",
        default_opacity=0.78,
        primary_metric="wind_speed_850hPa",
        primary_label="Wind Speed 850hPa",
        unit_label="m/s",
        summary_template="Current 850 hPa wind speed is {value} {unit}.",
        current_fields=("wind_speed_850hPa", "wind_direction_850hPa"),
        hourly_fields=("wind_speed_850hPa", "wind_direction_850hPa", "temperature_850hPa"),
        legend_ticks=(0, 10, 20, 30, 40, 50),
        notes=(
            "850 hPa wind field (~1.5 km AGL) — low-level jet and convective inflow reference.",
            "Particle flow field reuses the 10m renderer with 850hPa vectors.",
            "Open-Meteo pressure_levels parameter required.",
        ),
        pressure_levels=(850,),
    ),
    "wind-field-500hPa": WeatherLayerSpec(
        layer_id="wind-field-500hPa",
        display_name="Wind Field 500hPa",
        palette="wind-blue",
        paint_mode="particle_flow",
        default_opacity=0.74,
        primary_metric="wind_speed_500hPa",
        primary_label="Wind Speed 500hPa",
        unit_label="m/s",
        summary_template="Current 500 hPa wind speed is {value} {unit}.",
        current_fields=("wind_speed_500hPa", "wind_direction_500hPa"),
        hourly_fields=("wind_speed_500hPa", "wind_direction_500hPa", "temperature_500hPa"),
        legend_ticks=(0, 15, 30, 45, 60, 75),
        notes=(
            "500 hPa wind field (~5.5 km AGL) — mid-level synoptic flow reference.",
            "Particle flow field reuses the 10m renderer with 500hPa vectors.",
            "Open-Meteo pressure_levels parameter required.",
        ),
        pressure_levels=(500,),
    ),
    "wind-field-200hPa": WeatherLayerSpec(
        layer_id="wind-field-200hPa",
        display_name="Wind Field 200hPa",
        palette="wind-blue",
        paint_mode="particle_flow",
        default_opacity=0.7,
        primary_metric="wind_speed_200hPa",
        primary_label="Wind Speed 200hPa",
        unit_label="m/s",
        summary_template="Current 200 hPa wind speed is {value} {unit}.",
        current_fields=("wind_speed_200hPa", "wind_direction_200hPa"),
        hourly_fields=("wind_speed_200hPa", "wind_direction_200hPa", "temperature_200hPa"),
        legend_ticks=(0, 20, 40, 60, 80, 100),
        notes=(
            "200 hPa wind field (~12 km AGL) — upper-level jet stream reference.",
            "Particle flow field reuses the 10m renderer with 200hPa vectors.",
            "Open-Meteo pressure_levels parameter required.",
        ),
        pressure_levels=(200,),
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
    "temperature-80m": WeatherLayerSpec(
        layer_id="temperature-80m",
        display_name="Temperature 80m",
        palette="thermal-orange",
        paint_mode="grid_fill",
        default_opacity=0.58,
        primary_metric="temperature_80m",
        primary_label="Temperature 80m",
        unit_label="C",
        summary_template="Current 80 m temperature is {value} {unit}.",
        current_fields=("temperature_80m", "temperature_2m", "cloud_cover"),
        hourly_fields=("temperature_80m", "wind_speed_80m", "precipitation"),
        legend_ticks=(-10, 0, 10, 20, 30, 40),
        notes=(
            "80 m AGL temperature — useful for wind turbine icing and wake analysis.",
            "Reuses the 2m temperature renderer with 80m field.",
        ),
    ),
    "temperature-120m": WeatherLayerSpec(
        layer_id="temperature-120m",
        display_name="Temperature 120m",
        palette="thermal-orange",
        paint_mode="grid_fill",
        default_opacity=0.58,
        primary_metric="temperature_120m",
        primary_label="Temperature 120m",
        unit_label="C",
        summary_template="Current 120 m temperature is {value} {unit}.",
        current_fields=("temperature_120m", "temperature_2m", "cloud_cover"),
        hourly_fields=("temperature_120m", "wind_speed_120m", "precipitation"),
        legend_ticks=(-10, 0, 10, 20, 30, 40),
        notes=(
            "120 m AGL temperature — large turbine hub-height thermal reference.",
            "Reuses the 2m temperature renderer with 120m field.",
        ),
    ),
    "temperature-180m": WeatherLayerSpec(
        layer_id="temperature-180m",
        display_name="Temperature 180m",
        palette="thermal-orange",
        paint_mode="grid_fill",
        default_opacity=0.58,
        primary_metric="temperature_180m",
        primary_label="Temperature 180m",
        unit_label="C",
        summary_template="Current 180 m temperature is {value} {unit}.",
        current_fields=("temperature_180m", "temperature_2m", "cloud_cover"),
        hourly_fields=("temperature_180m", "wind_speed_180m", "precipitation"),
        legend_ticks=(-10, 0, 10, 20, 30, 40),
        notes=(
            "180 m AGL temperature — boundary-layer top thermal profile.",
            "Reuses the 2m temperature renderer with 180m field.",
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
    "pressure": WeatherLayerSpec(
        layer_id="pressure",
        display_name="Pressure",
        palette="pressure-purple",
        paint_mode="grid_fill",
        default_opacity=0.62,
        primary_metric="pressure_msl",
        primary_label="Sea Level Pressure",
        unit_label="hPa",
        summary_template="Current mean sea level pressure is {value} {unit}.",
        current_fields=("pressure_msl", "surface_pressure"),
        hourly_fields=("pressure_msl", "temperature_2m", "wind_speed_10m"),
        legend_ticks=(980, 1000, 1010, 1020, 1040),
        notes=(
            "Use a purple sequential ramp with isobars at 4 hPa intervals.",
            "Low pressure centers should pop against the dark basemap.",
        ),
    ),
    "humidity": WeatherLayerSpec(
        layer_id="humidity",
        display_name="Humidity",
        palette="humidity-green",
        paint_mode="grid_fill",
        default_opacity=0.66,
        primary_metric="relative_humidity_2m",
        primary_label="Relative Humidity",
        unit_label="%",
        summary_template="Current 2 m relative humidity is {value} {unit}.",
        current_fields=("relative_humidity_2m", "cloud_cover", "dew_point_2m"),
        hourly_fields=("relative_humidity_2m", "temperature_2m", "precipitation"),
        legend_ticks=(0, 20, 40, 60, 80, 100),
        notes=(
            "Use a green sequential ramp with brighter greens for higher humidity.",
            "Saturation plateaus above 90% to avoid washing out coastal areas.",
        ),
    ),
    "visibility": WeatherLayerSpec(
        layer_id="visibility",
        display_name="Visibility",
        palette="visibility-amber",
        paint_mode="grid_fill",
        default_opacity=0.7,
        primary_metric="visibility",
        primary_label="Visibility",
        unit_label="m",
        summary_template="Current visibility is {value} {unit}.",
        current_fields=("visibility", "cloud_cover", "weather_code"),
        hourly_fields=("visibility", "temperature_2m", "wind_speed_10m"),
        legend_ticks=(0, 1000, 5000, 10000, 20000, 30000),
        notes=(
            "Use an amber-to-gray ramp with hazardous zones (<1 km) highlighted in red.",
            "Visibility below 5 km should retain strong contrast for aviation alerts.",
        ),
    ),
}


DEFAULT_LAYER_ID = "wind-field"
DEFAULT_POINT = {
    "latitude": 23.1291,
    "longitude": 113.2644,
    "place_name": "Guangzhou",
}
