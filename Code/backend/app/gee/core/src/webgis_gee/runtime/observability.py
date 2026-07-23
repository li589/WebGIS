from __future__ import annotations

from abc import ABC, abstractmethod
import json
import logging
from threading import Lock
from typing import Any


internal_logger = logging.getLogger(__name__)


class StructuredEventSink(ABC):
    """Pushes structured events to external logging or tracing systems."""

    @abstractmethod
    def emit(self, payload: dict[str, Any], *, level: int, logger_name: str) -> None:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
        }


class MetricsSink(ABC):
    """Pushes counters and durations to external metric backends."""

    @abstractmethod
    def record_counter(self, name: str, value: int = 1) -> None:
        raise NotImplementedError

    @abstractmethod
    def record_duration(self, name: str, duration_ms: float) -> None:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
        }


class CompositeStructuredEventSink(StructuredEventSink):
    def __init__(self, sinks: list[StructuredEventSink]) -> None:
        self._sinks = list(sinks)

    def emit(self, payload: dict[str, Any], *, level: int, logger_name: str) -> None:
        for sink in self._sinks:
            sink.emit(payload, level=level, logger_name=logger_name)

    def describe(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "sinks": [sink.describe() for sink in self._sinks],
        }


class CompositeMetricsSink(MetricsSink):
    def __init__(self, sinks: list[MetricsSink]) -> None:
        self._sinks = list(sinks)

    def record_counter(self, name: str, value: int = 1) -> None:
        for sink in self._sinks:
            sink.record_counter(name, value=value)

    def record_duration(self, name: str, duration_ms: float) -> None:
        for sink in self._sinks:
            sink.record_duration(name, duration_ms=duration_ms)

    def describe(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "sinks": [sink.describe() for sink in self._sinks],
        }


class InMemoryStructuredEventSink(StructuredEventSink):
    """Captures structured events for tests or upstream pull-style integration."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._events: list[dict[str, Any]] = []

    def emit(self, payload: dict[str, Any], *, level: int, logger_name: str) -> None:
        with self._lock:
            self._events.append(
                {
                    "logger_name": logger_name,
                    "level": level,
                    "payload": dict(payload),
                }
            )

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(event) for event in self._events]


class InMemoryMetricsSink(MetricsSink):
    """Captures exported metrics for tests or lightweight upstream scraping."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = {}
        self._durations: dict[str, list[float]] = {}

    def record_counter(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def record_duration(self, name: str, duration_ms: float) -> None:
        with self._lock:
            self._durations.setdefault(name, []).append(duration_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "durations": {
                    name: [round(value, 3) for value in values]
                    for name, values in self._durations.items()
                },
            }


def log_structured_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    sink: StructuredEventSink | None = None,
    **fields: Any,
) -> None:
    payload = {"event": event, **fields}
    logger.log(
        level, json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    )
    if sink is not None:
        try:
            sink.emit(payload, level=level, logger_name=logger.name)
        except Exception as exc:
            internal_logger.warning("structured event sink emit failed: %s", exc)


class InMemoryMetricsCollector:
    """Collects lightweight in-process counters and duration summaries."""

    def __init__(self, metrics_sink: MetricsSink | None = None) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = {}
        self._timers: dict[str, dict[str, float | int]] = {}
        self._metrics_sink = metrics_sink

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value
        if self._metrics_sink is not None:
            try:
                self._metrics_sink.record_counter(name, value=value)
            except Exception as exc:
                internal_logger.warning("metrics sink counter export failed: %s", exc)

    def observe_duration(self, name: str, duration_ms: float) -> None:
        with self._lock:
            summary = self._timers.setdefault(
                name,
                {"count": 0, "total_ms": 0.0, "max_ms": 0.0},
            )
            summary["count"] = int(summary["count"]) + 1
            summary["total_ms"] = float(summary["total_ms"]) + duration_ms
            summary["max_ms"] = max(float(summary["max_ms"]), duration_ms)
        if self._metrics_sink is not None:
            try:
                self._metrics_sink.record_duration(name, duration_ms=duration_ms)
            except Exception as exc:
                internal_logger.warning("metrics sink duration export failed: %s", exc)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            timers = {
                name: {
                    "count": int(summary["count"]),
                    "total_ms": round(float(summary["total_ms"]), 3),
                    "max_ms": round(float(summary["max_ms"]), 3),
                    "avg_ms": round(
                        float(summary["total_ms"]) / int(summary["count"]),
                        3,
                    )
                    if int(summary["count"]) > 0
                    else 0.0,
                }
                for name, summary in self._timers.items()
            }
        return {
            "status": "ok",
            "counters": counters,
            "timers": timers,
            "external_metrics_sink": self._metrics_sink.describe()
            if self._metrics_sink is not None
            else None,
        }
