"""Resolve block-cache reuse paths when retrying workflow runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.workflow_repository import SQLiteWorkflowRepository

# Modules that support reuse_block_cache / reuse_output_dir on retry.
_OMEGA_BLOCK_MODULES = frozenset(
    {
        "omega_sf_fenkuai",
        "omega_sf",
        "omega_block",
        "block_inversion",
    }
)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _module_supports_block_reuse(module_name: str | None) -> bool:
    if not module_name:
        return False
    normalized = module_name.strip().lower()
    return normalized in _OMEGA_BLOCK_MODULES or normalized.startswith("omega_")


def _output_dir_from_products(products: list[Any]) -> str | None:
    for product in products:
        if not isinstance(product, dict):
            continue
        uri = product.get("uri") or product.get("path") or product.get("local_path")
        if not isinstance(uri, str) or not uri.strip():
            continue
        path = Path(uri)
        name_lower = path.name.lower()
        tags = product.get("tags") if isinstance(product.get("tags"), dict) else {}
        layer = str(tags.get("layer", "")).upper()
        product_type = str(product.get("type") or product.get("name") or "").lower()
        if "block_dir" in product_type or layer == "BLOCK" or "block" in name_lower:
            if path.is_dir():
                return str(path)
            parent = path.parent
            if parent.is_dir():
                return str(parent)
        if path.suffix.lower() in {".mat", ".tif", ".tiff"} and path.parent.is_dir():
            return str(path.parent)
    return None


def _output_dir_from_request(request_json: str | None) -> str | None:
    if not request_json:
        return None
    try:
        payload = json.loads(request_json)
    except json.JSONDecodeError:
        return None
    algo = payload.get("algorithm_request")
    if not isinstance(algo, dict):
        return None
    params = algo.get("algorithm_params")
    if not isinstance(params, dict):
        return None
    output_spec = algo.get("output_spec")
    extra = output_spec.get("extra") if isinstance(output_spec, dict) else None
    for source in (params, extra if isinstance(extra, dict) else {}):
        for key in ("reuse_output_dir", "output_dir"):
            raw = source.get(key)
            if isinstance(raw, str) and raw.strip():
                path = Path(raw.strip())
                if path.exists():
                    return str(path)
    module_name = algo.get("module_name")
    if _module_supports_block_reuse(str(module_name) if module_name else None):
        default = (
            Path(settings.python_provider_workspace) / "products" / str(module_name)
        )
        if default.is_dir():
            return str(default)
    return None


def resolve_reuse_output_dir(
    repository: SQLiteWorkflowRepository,
    run_id: str,
) -> tuple[str | None, str | None]:
    """Return ``(reuse_output_dir, module_name)`` for a prior workflow run.

    Priority:
    1. ``executor_metadata.reuse_output_dir``
    2. ``result_dto.products`` block/mat paths
    3. Original request ``algorithm_params.output_dir`` / ``output_spec.extra``
    4. Default ``products/{module_name}`` when module is omega-block capable
    """
    run = repository.get_run(run_id)
    if run is None:
        return None, None

    meta = _as_dict(run.executor_metadata)
    cached = meta.get("reuse_output_dir")
    if isinstance(cached, str) and cached.strip() and Path(cached).exists():
        module = meta.get("module_name")
        return cached.strip(), str(module) if module else None

    raw_payload = repository.get_run_payload(run_id)
    raw_result_dto = (
        raw_payload.get("result_dto") if isinstance(raw_payload, dict) else None
    )
    if isinstance(raw_result_dto, dict):
        products = raw_result_dto.get("products")
        if isinstance(products, list):
            from_products = _output_dir_from_products(products)
            if from_products:
                module = raw_result_dto.get("module_name") or meta.get("module_name")
                return from_products, str(module) if module else None

    result_dto = _as_dict(run.result_dto)
    products = result_dto.get("products")
    if isinstance(products, list):
        from_products = _output_dir_from_products(products)
        if from_products:
            module = result_dto.get("module_name") or meta.get("module_name")
            return from_products, str(module) if module else None

    request_json = repository.get_run_request_json(run_id)
    from_request = _output_dir_from_request(request_json)
    if from_request:
        module = None
        if request_json:
            try:
                algo = json.loads(request_json).get("algorithm_request") or {}
                if isinstance(algo, dict) and algo.get("module_name"):
                    module = str(algo["module_name"])
            except json.JSONDecodeError:
                pass
        return from_request, module

    return None, None


def inject_retry_reuse_params(
    payload_dict: dict[str, Any],
    *,
    reuse_output_dir: str | None,
) -> dict[str, Any]:
    """Merge reuse flags into ``algorithm_request.algorithm_params``."""
    if not reuse_output_dir:
        return payload_dict
    algo = payload_dict.get("algorithm_request")
    if not isinstance(algo, dict):
        return payload_dict
    params = dict(algo.get("algorithm_params") or {})
    if params.get("reuse_block_cache", True) is False:
        return payload_dict
    if "reuse_output_dir" not in params:
        params["reuse_block_cache"] = True
        params["reuse_output_dir"] = reuse_output_dir
        algo = {**algo, "algorithm_params": params}
        return {**payload_dict, "algorithm_request": algo}
    return payload_dict
