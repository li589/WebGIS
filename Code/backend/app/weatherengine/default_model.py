"""Effective global weather default model (DB > env)."""

from __future__ import annotations


def weather_default_model() -> str:
    from app.services.weather_engine_settings import get_effective_weather_default_model

    return get_effective_weather_default_model()
