"""天气源 Provider 实现集合。

每个 Provider 实现一个独立的天气数据源（Open-Meteo、NOAA、AccuWeather、本地 GRIB 等）。
所有 Provider 必须继承 ``app.weatherengine.provider_base.WeatherProvider``。
"""
