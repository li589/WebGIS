from __future__ import annotations

from importlib import import_module
import logging
from typing import Any, Callable

from algorithms.providers.base import ProviderExecutionPayload, ProviderExecutionResult

logger = logging.getLogger(__name__)

# Module name prefixes that resolve_algorithm_callable is permitted to load.
# P0-3: prevents arbitrary code execution via import_module.
_ALLOWED_MODULE_PREFIXES = ("algorithms.",)
_MAX_PARAMETER_KEYS = 64  # P0-5: prevent parameter dict DoS


def _validate_module_name(module_name: str) -> None:
    """Reject module names that could load arbitrary code."""
    if not any(module_name.startswith(prefix) for prefix in _ALLOWED_MODULE_PREFIXES):
        raise ValueError(
            f"Module {module_name!r} is not allowed. "
            f"Only modules with prefix {_ALLOWED_MODULE_PREFIXES!r} may be imported."
        )


def resolve_algorithm_callable(entrypoint: str) -> Callable[[ProviderExecutionPayload], Any]:
    if ":" not in entrypoint:
        raise ValueError("Algorithm entrypoint must use 'module.path:function_name' format.")

    module_name, function_name = entrypoint.split(":", 1)
    _validate_module_name(module_name)
    module = import_module(module_name)
    callable_obj = getattr(module, function_name, None)
    if callable_obj is None or not callable(callable_obj):
        raise ValueError(f"Algorithm callable not found: {entrypoint}")
    logger.info("Loaded algorithm entrypoint=%s", entrypoint)
    return callable_obj


def adapt_algorithm_output(
    raw_result: dict[str, Any],
    *,
    provider_key: str,
    layer_id: str,
    default_title: str,
    default_summary: str,
    default_metric_label: str,
    default_metric_unit: str,
) -> ProviderExecutionResult:
    hotspots = raw_result.get("hotspots", [])
    series = raw_result.get("series", [])
    diagnostics = list(raw_result.get("diagnostics", []))
    metadata = dict(raw_result.get("metadata", {}))

    return ProviderExecutionResult(
        provider_key=raw_result.get("provider_key", provider_key),
        layer_id=raw_result.get("layer_id", layer_id),
        title=raw_result.get("title", default_title),
        summary=raw_result.get("summary", default_summary),
        metric_label=raw_result.get("metric_label", default_metric_label),
        metric_unit=raw_result.get("metric_unit", default_metric_unit),
        metric_value=raw_result.get("metric_value"),
        status_label=raw_result.get("status_label", "Provider 已执行"),
        confidence_label=raw_result.get("confidence_label", "接口联调阶段"),
        hotspots=hotspots if isinstance(hotspots, list) else [],
        series=series if isinstance(series, list) else [],
        diagnostics=diagnostics,
        metadata=metadata,
    )
