from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contracts.data import DataRequest
from data_access import (
    DataRequestV2,
    build_default_coordinator,
    build_prepared_input,
    build_resource_ref,
    resource_refs_to_legacy_bundle,
)
from contracts.job import JobRequest, JobResult
from interfaces.datasource import DataSourceAdapter
from interfaces.logger import LoggerAdapter
from interfaces.product_sink import ProductSink
from interfaces.scheduler import SchedulerAdapter
from runner.registry import get_pipeline
from runner.runtime import build_runtime_context
from utils.local_adapters import LocalProductSink

_PREPARED_BUNDLES_KEY = "_prepared_bundles"
_PREPARED_INPUTS_KEY = "_prepared_inputs"
_DATA_ACCESS_REQUESTS_KEY = "_data_access_requests"


def _normalize_acquire_mode(value: str | None) -> str:
    mode = str(value or "lazy").lower()
    if mode in {"lazy", "partial", "full"}:
        return mode
    return "lazy"


def _build_data_requests(
    request: JobRequest,
    required_datasets: list[str],
    required_variables: list[str],
    *,
    acquire_mode: str | None = None,
) -> list[DataRequest]:
    resolved_acquire_mode = _normalize_acquire_mode(acquire_mode)
    return [
        DataRequest(
            dataset_name=dataset_name,
            variables=list(required_variables),
            time_range=request.time_range,
            spatial_filter=request.region,
            acquire_mode=resolved_acquire_mode,
            cache_policy=request.cache_policy,
        )
        for dataset_name in required_datasets
    ]


def _build_data_request_v2(
    request: JobRequest, data_request: DataRequest
) -> DataRequestV2:
    raw_configs = request.datasource_selection.get(_DATA_ACCESS_REQUESTS_KEY, {})
    dataset_config: dict[str, Any] = {}
    if isinstance(raw_configs, dict):
        raw_dataset_config = raw_configs.get(data_request.dataset_name, {})
        if isinstance(raw_dataset_config, dict):
            dataset_config = dict(raw_dataset_config)

    selector = dict(dataset_config.get("selector", {}))
    if "uris" not in selector:
        if "uris" in dataset_config:
            selector["uris"] = list(dataset_config["uris"])
        elif "uri" in dataset_config:
            selector["uris"] = [dataset_config["uri"]]

    return DataRequestV2(
        dataset_name=data_request.dataset_name,
        variables=tuple(data_request.variables),
        selector=selector,
        accepted_formats=tuple(dataset_config.get("accepted_formats", ())),
        preferred_format=dataset_config.get("preferred_format"),
        materialization_mode=str(dataset_config.get("materialization_mode", "auto")),
        access_mode=_normalize_acquire_mode(
            dataset_config.get("access_mode") or data_request.acquire_mode
        ),
        allow_cache=bool(dataset_config.get("allow_cache", True)),
        allow_streaming=bool(dataset_config.get("allow_streaming", False)),
        logical_type=dataset_config.get("logical_type"),
        source_hints=tuple(dataset_config.get("source_hints", ())),
        converter_hints=dict(dataset_config.get("converter_hints", {})),
    )


def _build_request_v2_from_dataset_config(
    dataset_name: str, dataset_config: dict[str, Any], request: JobRequest
) -> DataRequestV2:
    selector = dict(dataset_config.get("selector", {}))
    if "uris" not in selector:
        if "uris" in dataset_config:
            selector["uris"] = list(dataset_config["uris"])
        elif "uri" in dataset_config:
            selector["uris"] = [dataset_config["uri"]]
    access_mode = _normalize_acquire_mode(dataset_config.get("access_mode"))
    return DataRequestV2(
        dataset_name=dataset_name,
        variables=tuple(dataset_config.get("variables", ())),
        selector=selector,
        accepted_formats=tuple(dataset_config.get("accepted_formats", ())),
        preferred_format=dataset_config.get("preferred_format"),
        materialization_mode=str(dataset_config.get("materialization_mode", "auto")),
        access_mode=access_mode,
        allow_cache=bool(dataset_config.get("allow_cache", True)),
        allow_streaming=bool(dataset_config.get("allow_streaming", False)),
        logical_type=dataset_config.get("logical_type"),
        source_hints=tuple(dataset_config.get("source_hints", ())),
        converter_hints=dict(dataset_config.get("converter_hints", {})),
    )


def _has_explicit_data_access_selector(request_v2: DataRequestV2) -> bool:
    raw_uris = request_v2.selector.get("uris", ())
    return bool(raw_uris)


def _resource_refs_from_assets(assets: list[object]) -> tuple[object, ...]:
    resources: list[object] = []
    for asset in assets:
        uri = getattr(asset, "uri", None)
        if not uri:
            continue
        metadata = dict(getattr(asset, "metadata", {}) or {})
        dataset_name = getattr(asset, "dataset_name", None)
        variables = getattr(asset, "variables", None)
        if dataset_name is not None:
            metadata.setdefault("dataset_name", dataset_name)
        if variables is not None:
            metadata.setdefault("variables", list(variables))
        resources.append(build_resource_ref(str(uri), metadata=metadata))
    return tuple(resources)


def _resource_refs_from_bundle(bundle) -> tuple[object, ...]:
    resources: list[object] = []
    for local_path in bundle.local_paths:
        resources.append(
            build_resource_ref(
                str(local_path), metadata={"dataset_name": bundle.dataset_name}
            )
        )
    for remote_ref in bundle.remote_refs:
        resources.append(
            build_resource_ref(
                str(remote_ref), metadata={"dataset_name": bundle.dataset_name}
            )
        )
    return tuple(resources)


def _build_prepared_input_from_legacy_result(
    data_request: DataRequest,
    data_request_v2: DataRequestV2,
    assets: list[object],
    bundle,
):
    resource_refs = _resource_refs_from_assets(assets) or _resource_refs_from_bundle(
        bundle
    )
    materialized_refs = _resource_refs_from_bundle(bundle)
    warnings: list[str] = []
    if not resource_refs:
        warnings.append(
            f"No resources discovered for dataset '{data_request.dataset_name}'"
        )
    cache_hits = (
        bundle.metadata.get("cache_hits", ())
        if isinstance(bundle.metadata, dict)
        else ()
    )
    return build_prepared_input(
        data_request_v2,
        resources=resource_refs,
        materialized_resources=materialized_refs,
        warnings=warnings,
        cache_hits=list(cache_hits),
    )


def _resource_refs_to_asset_payloads(resources) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for resource in resources:
        payloads.append(
            {
                "uri": resource.uri,
                "dataset_name": resource.metadata.get("dataset_name"),
                "variables": list(resource.metadata.get("variables", [])),
                "metadata": dict(resource.metadata),
            }
        )
    return payloads


def _extract_conversion_trace_entries(
    prepared_input_payload: object,
) -> tuple[dict[str, Any], ...]:
    raw_entries: object
    if isinstance(prepared_input_payload, dict):
        raw_entries = prepared_input_payload.get("conversion_trace", ())
    else:
        raw_entries = getattr(prepared_input_payload, "conversion_trace", ())
    if not isinstance(raw_entries, (list, tuple)):
        return ()
    return tuple(dict(entry) for entry in raw_entries if isinstance(entry, dict))


def _build_conversion_trace_resource_detail(entry: dict[str, Any]) -> dict[str, Any]:
    local_path = entry.get("local_path")
    loaded_summary = entry.get("loaded_summary")
    origin_uri = entry.get("origin_uri")
    return {
        "uri": entry.get("uri"),
        "origin_uri": origin_uri,
        "local_path": None if local_path is None else str(local_path),
        "adapter": None if entry.get("adapter") is None else str(entry["adapter"]),
        "format": None if entry.get("format") is None else str(entry["format"]),
        "logical_type": None
        if entry.get("logical_type") is None
        else str(entry["logical_type"]),
        "loaded_summary": dict(loaded_summary)
        if isinstance(loaded_summary, dict)
        else {},
    }


def _summarize_conversion_trace_dataset(
    dataset_name: str, prepared_input_payload: object
) -> dict[str, Any] | None:
    entries = _extract_conversion_trace_entries(prepared_input_payload)
    if not entries:
        return None
    adapters = sorted(
        {str(entry["adapter"]) for entry in entries if entry.get("adapter")}
    )
    formats = sorted({str(entry["format"]) for entry in entries if entry.get("format")})
    logical_types = sorted(
        {str(entry["logical_type"]) for entry in entries if entry.get("logical_type")}
    )
    resources = [_build_conversion_trace_resource_detail(entry) for entry in entries]
    return {
        "dataset_name": dataset_name,
        "entry_count": len(entries),
        "resource_count": len(resources),
        "adapters": adapters,
        "formats": formats,
        "logical_types": logical_types,
        "resources": resources,
    }


def _emit_conversion_trace_warning(
    logger_adapter: LoggerAdapter,
    dataset_name: str,
    prepared_input_payload: object,
) -> None:
    summary = _summarize_conversion_trace_dataset(dataset_name, prepared_input_payload)
    if summary is None:
        return
    logger_adapter.emit_warning(
        "data_prepare",
        f"Observed conversion trace for dataset {dataset_name}",
        extra={"conversion_trace": summary},
    )


def _build_conversion_trace_metrics(
    prepared_inputs: dict[str, dict[str, object]],
) -> dict[str, Any]:
    dataset_summaries: list[dict[str, Any]] = []
    total_entries = 0
    for dataset_name in sorted(prepared_inputs):
        summary = _summarize_conversion_trace_dataset(
            dataset_name, prepared_inputs[dataset_name]
        )
        if summary is None:
            continue
        dataset_summaries.append(summary)
        total_entries += int(summary["entry_count"])
    if not dataset_summaries:
        return {}
    return {
        "dataset_count": len(dataset_summaries),
        "entry_count": total_entries,
        "datasets": dataset_summaries,
    }


def _attach_conversion_trace_to_manifest(
    manifest: object, prepared_inputs: dict[str, dict[str, object]]
) -> dict[str, Any]:
    conversion_trace_metrics = _build_conversion_trace_metrics(prepared_inputs)
    if not conversion_trace_metrics:
        return {}
    manifest_extra = getattr(manifest, "extra", None)
    if isinstance(manifest_extra, dict):
        manifest_extra["conversion_trace"] = conversion_trace_metrics
    return conversion_trace_metrics


def _prepare_explicit_data_access_requests(
    request: JobRequest,
    logger_adapter: LoggerAdapter,
    *,
    cache_root: str | Path | None = None,
    excluded_datasets: set[str] | None = None,
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    raw_configs = request.datasource_selection.get(_DATA_ACCESS_REQUESTS_KEY, {})
    if not isinstance(raw_configs, dict) or not raw_configs:
        return {}, {}

    prepared: dict[str, dict[str, object]] = {}
    prepared_inputs: dict[str, dict[str, object]] = {}
    coordinator = build_default_coordinator(
        Path(cache_root or Path.cwd()) / "data_access"
    )
    skipped_datasets = excluded_datasets or set()
    for dataset_name, raw_config in raw_configs.items():
        if str(dataset_name) in skipped_datasets:
            continue
        if not isinstance(raw_config, dict):
            continue
        request_v2 = _build_request_v2_from_dataset_config(
            str(dataset_name), raw_config, request
        )
        if not _has_explicit_data_access_selector(request_v2):
            continue
        logger_adapter.emit_stage_start(
            "data_prepare", f"Prepare dataset {dataset_name}"
        )
        prepared_input = coordinator.prepare(
            request_v2,
            target_dir=Path(cache_root or Path.cwd())
            / "materialized"
            / str(dataset_name),
        )
        legacy_request = DataRequest(
            dataset_name=str(dataset_name),
            variables=list(request_v2.variables),
            time_range=request.time_range,
            spatial_filter=request.region,
            acquire_mode=request_v2.access_mode,
            cache_policy=request.cache_policy,
        )
        resources_for_bundle = (
            prepared_input.materialized_resources or prepared_input.resources
        )
        bundle = resource_refs_to_legacy_bundle(
            legacy_request,
            resources_for_bundle,
            bundle_id=f"{dataset_name}-bundle",
            storage_mode=request_v2.access_mode,
            metadata={
                "prepared_via": "data_access",
                "cache_hits": list(prepared_input.cache_hits),
                "warnings": list(prepared_input.warnings),
            },
        )
        prepared[str(dataset_name)] = {
            "request": asdict(legacy_request),
            "bundle": asdict(bundle),
            "assets": _resource_refs_to_asset_payloads(prepared_input.resources),
        }
        _emit_conversion_trace_warning(
            logger_adapter, str(dataset_name), prepared_input
        )
        prepared_inputs[str(dataset_name)] = asdict(prepared_input)
        logger_adapter.emit_stage_end(
            "data_prepare",
            (
                f"Prepared dataset {dataset_name} with "
                f"{len(bundle.local_paths)} local paths and "
                f"{len(prepared_input.materialized_resources)} prepared resources"
            ),
        )
    return prepared, prepared_inputs


def _merge_prepared_payloads(
    base: dict[str, dict[str, object]],
    extra: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    if not base:
        return dict(extra)
    if not extra:
        return dict(base)
    merged = dict(base)
    merged.update(extra)
    return merged


def _prepare_required_datasets(
    request: JobRequest,
    datasource_adapter: DataSourceAdapter,
    logger_adapter: LoggerAdapter,
    required_datasets: list[str],
    required_variables: list[str],
    *,
    acquire_mode: str | None = None,
    cache_root: str | Path | None = None,
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    prepared: dict[str, dict[str, object]] = {}
    prepared_inputs: dict[str, dict[str, object]] = {}
    coordinator = build_default_coordinator(
        Path(cache_root or Path.cwd()) / "data_access"
    )
    for data_request in _build_data_requests(
        request,
        required_datasets,
        required_variables,
        acquire_mode=acquire_mode,
    ):
        logger_adapter.emit_stage_start(
            "data_prepare", f"Prepare dataset {data_request.dataset_name}"
        )
        request_v2 = _build_data_request_v2(request, data_request)
        if _has_explicit_data_access_selector(request_v2):
            prepared_input = coordinator.prepare(
                request_v2,
                target_dir=Path(cache_root or Path.cwd())
                / "materialized"
                / data_request.dataset_name,
            )
            resources_for_bundle = (
                prepared_input.materialized_resources or prepared_input.resources
            )
            bundle = resource_refs_to_legacy_bundle(
                data_request,
                resources_for_bundle,
                bundle_id=f"{data_request.dataset_name}-bundle",
                storage_mode=data_request.acquire_mode,
                metadata={
                    "prepared_via": "data_access",
                    "cache_hits": list(prepared_input.cache_hits),
                    "warnings": list(prepared_input.warnings),
                },
            )
            assets_payload = _resource_refs_to_asset_payloads(prepared_input.resources)
        else:
            assets = datasource_adapter.discover(data_request)
            bundle = datasource_adapter.resolve(data_request)
            bundle = datasource_adapter.acquire(bundle)
            bundle = datasource_adapter.materialize(bundle)
            prepared_input = _build_prepared_input_from_legacy_result(
                data_request,
                request_v2,
                assets,
                bundle,
            )
            assets_payload = [asdict(asset) for asset in assets]
        prepared[data_request.dataset_name] = {
            "request": asdict(data_request),
            "bundle": asdict(bundle),
            "assets": assets_payload,
        }
        _emit_conversion_trace_warning(
            logger_adapter, data_request.dataset_name, prepared_input
        )
        prepared_inputs[data_request.dataset_name] = asdict(prepared_input)
        logger_adapter.emit_stage_end(
            "data_prepare",
            (
                f"Prepared dataset {data_request.dataset_name} with "
                f"{len(bundle.local_paths)} local paths and "
                f"{len(prepared_input.materialized_resources)} prepared resources"
            ),
        )
    return prepared, prepared_inputs


def _resolve_workflow_manifest_payload(output_value: object, workflow_runner) -> object:
    from contracts.product import ProductManifest
    from workflow.schemas import ArtifactRef

    if isinstance(output_value, ProductManifest):
        return output_value
    if isinstance(output_value, ArtifactRef):
        return workflow_runner.artifact_store.load(output_value.artifact_id)
    raise TypeError(f"Unsupported workflow output type: {type(output_value)!r}")


def _is_workflow_manifest_value(output_value: object) -> bool:
    from contracts.product import ProductManifest
    from workflow.schemas import ArtifactRef

    return isinstance(output_value, ProductManifest) or (
        isinstance(output_value, ArtifactRef)
        and output_value.artifact_type == "product_manifest"
    )


def _select_workflow_manifest_output(workflow_definition, workflow_result) -> object:
    preferred_names = ("final_manifest", "manifest")
    for output_name in preferred_names:
        if output_name in workflow_result.outputs:
            output_value = workflow_result.outputs[output_name]
            if _is_workflow_manifest_value(output_value):
                return output_value

    manifest_candidates: list[object] = []
    for output_spec in workflow_definition.outputs:
        output_value = workflow_result.outputs[output_spec.name]
        if _is_workflow_manifest_value(output_value):
            manifest_candidates.append(output_value)

    if len(manifest_candidates) == 1:
        return manifest_candidates[0]
    if not manifest_candidates:
        raise ValueError("workflow_definition must expose a final manifest output")
    raise ValueError(
        "workflow_definition exposes multiple manifest outputs; use final_manifest to disambiguate"
    )


def _build_single_module_workflow(request: JobRequest):
    from workflow.graph import WorkflowDefinition, WorkflowNodeSpec, WorkflowOutputSpec

    if not request.module_name:
        raise ValueError("module_name is required to build a single-module workflow")

    input_bindings = {
        "datasource_selection": "request:datasource_selection",
        "algorithm_params": "request:algorithm_params",
        "output_spec_extra": "request:output_spec_extra",
    }

    # Bind mode-required scalar inputs (e.g. input_mat, dh_mat) so the workflow
    # validator passes. The "input:{name}" binding resolves from
    # datasource_selection direct keys, or returns None when the key is absent
    # (the module then resolves it from _prepared_inputs at runtime).
    mode = request.algorithm_params.get("mode")
    if mode is not None:
        try:
            from modules.registry import get_module

            module_cls = get_module(request.module_name)
            mode_inputs = getattr(module_cls, "mode_required_inputs", {}).get(
                str(mode).lower(), ()
            )
            for input_name in mode_inputs:
                input_bindings[input_name] = f"input:{input_name}"
        except Exception:
            pass

    return WorkflowDefinition(
        workflow_id=request.workflow_name or f"module::{request.module_name}",
        name=request.workflow_name or request.module_name,
        description="Auto-generated single-module workflow",
        nodes=[
            WorkflowNodeSpec(
                node_id="module_node",
                node_type="module",
                input_bindings=input_bindings,
                params={
                    "module_name": request.module_name,
                    **(
                        {"mode": request.algorithm_params.get("mode")}
                        if request.algorithm_params.get("mode") is not None
                        else {}
                    ),
                },
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                name="final_manifest", source="node:module_node.manifest"
            )
        ],
        metadata={"generated_from": "run_job", "module_name": request.module_name},
    )


def _resolve_named_workflow(request: JobRequest):
    from workflow.presets import build_named_workflow

    if not request.workflow_name:
        raise ValueError("workflow_name is required to resolve a named workflow")
    return build_named_workflow(request.workflow_name, request)


def _promote_legacy_pipeline_to_workflow(request: JobRequest) -> None:
    if request.pipeline_name == "retrieval_workflow_pipeline":
        request.workflow_name = request.workflow_name or "retrieval_workflow"


def _copy_job_request(request: JobRequest) -> JobRequest:
    return replace(
        request,
        datasource_selection=dict(request.datasource_selection),
        algorithm_params=dict(request.algorithm_params),
        output_spec=replace(request.output_spec, extra=dict(request.output_spec.extra)),
        resume_policy=None
        if request.resume_policy is None
        else dict(request.resume_policy),
        tags=dict(request.tags),
    )


def run_job(
    request: JobRequest,
    scheduler_adapter: SchedulerAdapter,
    datasource_adapter: DataSourceAdapter,
    logger_adapter: LoggerAdapter,
    product_sink: ProductSink | None = None,
    workspace: str | Path | None = None,
) -> JobResult:
    from contracts.validation import validate_job_request

    working_request = _copy_job_request(request)
    started_at = datetime.now(UTC)
    base_workspace = Path(workspace or Path.cwd())
    resolved_product_sink = product_sink or LocalProductSink(
        base_workspace / "products" / "manifests"
    )
    scheduler_adapter.get_run_context(working_request)
    ctx = build_runtime_context(working_request, base_workspace)
    logger_adapter.bind_context(working_request.job_id, ctx.run_id)
    scheduler_adapter.update_status(working_request.job_id, ctx.run_id, "running")
    error_stage = "dispatch"

    try:
        validate_job_request(working_request)
        if (
            working_request.workflow_definition is None
            and working_request.workflow_name is None
            and working_request.module_name is None
        ):
            _promote_legacy_pipeline_to_workflow(working_request)

        if (
            working_request.workflow_definition is None
            and working_request.module_name is not None
        ):
            working_request.workflow_definition = _build_single_module_workflow(
                working_request
            )
            working_request.workflow_name = (
                working_request.workflow_name or working_request.module_name
            )
        elif (
            working_request.workflow_definition is None
            and working_request.workflow_name is not None
        ):
            working_request.workflow_definition = _resolve_named_workflow(
                working_request
            )

        if working_request.workflow_definition is not None:
            from workflow.executor import WorkflowRunner
            from workflow.serialization import coerce_workflow_definition
            from workflow.validation import validate_workflow_definition

            error_stage = "dispatch.workflow"
            workflow_definition = coerce_workflow_definition(
                working_request.workflow_definition
            )
            validate_workflow_definition(workflow_definition)
            working_request.workflow_definition = workflow_definition
            request_level_prepared_bundles, request_level_prepared_inputs = (
                _prepare_explicit_data_access_requests(
                    working_request,
                    logger_adapter,
                    cache_root=ctx.cache_dir,
                )
            )
            if request_level_prepared_bundles:
                working_request.datasource_selection[_PREPARED_BUNDLES_KEY] = (
                    request_level_prepared_bundles
                )
            if request_level_prepared_inputs:
                working_request.datasource_selection[_PREPARED_INPUTS_KEY] = (
                    request_level_prepared_inputs
                )
            workflow_name = (
                working_request.workflow_name or workflow_definition.workflow_id
            )
            scheduler_adapter.update_status(
                working_request.job_id,
                ctx.run_id,
                "planning",
                detail={
                    "workflow_id": workflow_definition.workflow_id,
                    "workflow_name": workflow_name,
                    "node_count": len(workflow_definition.nodes),
                    "output_count": len(workflow_definition.outputs),
                },
            )
            logger_adapter.emit_stage_start(
                "workflow_dispatch", f"Execute workflow {workflow_name}"
            )
            workflow_runner = WorkflowRunner(
                datasource_adapter=datasource_adapter,
                logger_adapter=logger_adapter,
                product_sink=resolved_product_sink,
            )
            workflow_result = workflow_runner.run(
                workflow_definition, working_request, ctx
            )
            if not workflow_definition.outputs:
                raise ValueError("workflow_definition.outputs must not be empty")
            manifest_value = _select_workflow_manifest_output(
                workflow_definition, workflow_result
            )
            manifest = _resolve_workflow_manifest_payload(
                manifest_value, workflow_runner
            )
            conversion_trace_metrics = _attach_conversion_trace_to_manifest(
                manifest, request_level_prepared_inputs
            )
            manifest_uri = resolved_product_sink.write_manifest(manifest)
            logger_adapter.emit_artifact(
                "dispatch.workflow", manifest_uri, "job_manifest"
            )
            logger_adapter.emit_stage_end("workflow_dispatch", "Workflow finished")
            workflow_metrics = {
                "workflow_id": workflow_definition.workflow_id,
                "node_count": len(workflow_result.execution_order),
            }
            if conversion_trace_metrics:
                workflow_metrics["conversion_trace"] = conversion_trace_metrics
            result = JobResult(
                job_id=working_request.job_id,
                run_id=ctx.run_id,
                status="success",
                started_at=started_at,
                finished_at=datetime.now(UTC),
                manifest_uri=manifest_uri,
                metrics=workflow_metrics,
            )
            scheduler_adapter.complete(result)
            return result

        error_stage = "dispatch.pipeline"
        pipeline_cls = get_pipeline(working_request.pipeline_name)
        pipeline = pipeline_cls(
            datasource_adapter=datasource_adapter,
            logger_adapter=logger_adapter,
            product_sink=resolved_product_sink,
        )
        plan = pipeline.plan(working_request, ctx)
        scheduler_adapter.update_status(
            working_request.job_id,
            ctx.run_id,
            "planning",
            detail={
                "required_datasets": list(plan.required_datasets),
                "required_variables": list(plan.required_variables),
                "estimated_outputs": list(plan.estimated_outputs),
                "cache_requirement": plan.cache_requirement,
            },
        )
        prepared_bundles, prepared_inputs = _prepare_required_datasets(
            working_request,
            datasource_adapter,
            logger_adapter,
            plan.required_datasets,
            plan.required_variables,
            acquire_mode=plan.cache_requirement,
            cache_root=ctx.cache_dir,
        )
        explicit_prepared_bundles, explicit_prepared_inputs = (
            _prepare_explicit_data_access_requests(
                working_request,
                logger_adapter,
                cache_root=ctx.cache_dir,
                excluded_datasets=set(plan.required_datasets),
            )
        )
        prepared_bundles = _merge_prepared_payloads(
            prepared_bundles, explicit_prepared_bundles
        )
        prepared_inputs = _merge_prepared_payloads(
            prepared_inputs, explicit_prepared_inputs
        )
        if prepared_bundles:
            working_request.datasource_selection[_PREPARED_BUNDLES_KEY] = (
                prepared_bundles
            )
        if prepared_inputs:
            working_request.datasource_selection[_PREPARED_INPUTS_KEY] = prepared_inputs
        logger_adapter.emit_stage_start(
            "pipeline_dispatch", f"Execute {working_request.pipeline_name}"
        )
        manifest = pipeline.execute(working_request, ctx)
        pipeline_conversion_trace_metrics = _attach_conversion_trace_to_manifest(
            manifest, prepared_inputs
        )
        manifest_uri = resolved_product_sink.write_manifest(manifest)
        logger_adapter.emit_artifact("dispatch.pipeline", manifest_uri, "job_manifest")
        logger_adapter.emit_stage_end("pipeline_dispatch", "Pipeline finished")
        result = JobResult(
            job_id=working_request.job_id,
            run_id=ctx.run_id,
            status="success",
            started_at=started_at,
            finished_at=datetime.now(UTC),
            manifest_uri=manifest_uri,
            metrics={"conversion_trace": pipeline_conversion_trace_metrics}
            if pipeline_conversion_trace_metrics
            else {},
        )
        scheduler_adapter.complete(result)
        return result
    except Exception as exc:
        # Sprint 3.5: 编程 bug（AttributeError/NameError/TypeError/ImportError/SyntaxError）
        # 必须向上传播，避免被掩盖为 job 失败；其余运行时异常（网络/数据/IO）降级为 JobResult(failed)。
        if isinstance(
            exc, (AttributeError, NameError, TypeError, ImportError, SyntaxError)
        ):
            raise
        logger_adapter.emit_error(
            error_stage,
            str(exc),
            extra={
                "exception_type": type(exc).__name__,
                "call_chain": list(ctx.call_chain),
            },
        )
        result = JobResult(
            job_id=working_request.job_id,
            run_id=ctx.run_id,
            status="failed",
            started_at=started_at,
            finished_at=datetime.now(UTC),
            error_summary=str(exc),
        )
        scheduler_adapter.complete(result)
        return result
