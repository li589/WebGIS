from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
import threading

from contracts.api_errors import build_api_error_response
from contracts.job import JobRequest, JobResult
from contracts.request_templates import (
    RequestTemplateSpec,
    build_workflow_request_template,
    get_module_request_template,
)
from contracts.serialization import coerce_job_request, get_job_request_json_schema
from contracts.validation import validate_job_request
from modules.registry import get_module as get_registered_module
from modules.registry import list_modules as list_registered_modules
from runner.dispatch import run_job
from service.async_jobs import AsyncJobRegistry, AsyncJobStore, FileAsyncJobRegistry
from service.job_queue import InMemoryJobQueue, JobQueueBackend
from service.result_dto import build_job_result_dto
from utils.local_adapters import (
    ConsoleLoggerAdapter,
    LocalDataSourceAdapter,
    LocalProductSink,
    LocalSchedulerAdapter,
)
from service.worker import JobQueueWorker
from workflow.panel_schema import (
    WorkflowInputPanelSchema,
    WorkflowPanelField,
    build_workflow_input_panel_schema,
)
from workflow.presets import build_named_workflow, list_named_workflows
from workflow.ui_metadata import (
    WorkflowInputPanelUiSchema,
    enhance_panel_schema_with_ui_metadata,
)
from workflow.serialization import get_workflow_definition_json_schema


RunJobFn = Callable[..., JobResult]
AdapterFactory = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class ServiceResponse:
    status_code: int
    body: dict[str, Any]


class JobService:
    def __init__(
        self,
        *,
        scheduler_adapter=None,
        datasource_adapter=None,
        logger_adapter=None,
        product_sink=None,
        scheduler_adapter_factory: AdapterFactory | None = None,
        datasource_adapter_factory: AdapterFactory | None = None,
        logger_adapter_factory: AdapterFactory | None = None,
        product_sink_factory: AdapterFactory | None = None,
        workspace: str | Path | None = None,
        run_job_fn: RunJobFn = run_job,
        async_job_registry: AsyncJobStore | None = None,
        job_queue: JobQueueBackend | None = None,
    ) -> None:
        self._scheduler_adapter_factory = (
            scheduler_adapter_factory or _constant_factory(scheduler_adapter)
        )
        self._datasource_adapter_factory = (
            datasource_adapter_factory or _constant_factory(datasource_adapter)
        )
        self._logger_adapter_factory = logger_adapter_factory or _constant_factory(
            logger_adapter
        )
        self._product_sink_factory = product_sink_factory or _constant_factory(
            product_sink
        )
        self._workspace = None if workspace is None else Path(workspace)
        self._run_job_fn = run_job_fn
        self._async_job_registry = async_job_registry
        self._job_queue = job_queue

    def get_health_response(self) -> ServiceResponse:
        return ServiceResponse(
            status_code=200,
            body={
                "status": "ok",
                "service": "mat2py-job-api",
                "workspace": None if self._workspace is None else str(self._workspace),
                "async_jobs": self._async_job_registry is not None,
                "async_job_store": (
                    None
                    if self._async_job_registry is None
                    else type(self._async_job_registry).__name__
                ),
                "job_queue": None
                if self._job_queue is None
                else type(self._job_queue).__name__,
            },
        )

    def get_job_request_schema_response(self) -> ServiceResponse:
        return ServiceResponse(
            status_code=200, body=_to_jsonable(get_job_request_json_schema())
        )

    def get_workflow_definition_schema_response(self) -> ServiceResponse:
        return ServiceResponse(
            status_code=200, body=_to_jsonable(get_workflow_definition_json_schema())
        )

    def validate_job_response(self, payload: object) -> ServiceResponse:
        """基于 provider manifest 模板校验 JobRequest。

        供 backend bridge 在 submit_job 之前调用，提前发现参数错误。
        """
        from contracts.provider_manifest import provider_manifest

        try:
            request = coerce_job_request(payload)
            result = provider_manifest.validate_request(request)
            body = {
                "is_valid": result.is_valid,
                "errors": result.errors,
                "template": (
                    {
                        "entry_kind": result.template.entry_kind,
                        "entry_name": result.template.entry_name,
                        "allowed_task_types": list(result.template.allowed_task_types),
                        "required_datasource_keys": list(
                            result.template.required_datasource_keys
                        ),
                        "required_algorithm_keys": list(
                            result.template.required_algorithm_keys
                        ),
                    }
                    if result.template is not None
                    else None
                ),
            }
            return ServiceResponse(status_code=200, body=body)
        except Exception as exc:
            return ServiceResponse(
                status_code=400,
                body={
                    "is_valid": False,
                    "errors": [f"Failed to validate: {exc}"],
                    "template": None,
                },
            )

    def get_provider_manifest_response(self) -> ServiceResponse:
        """导出完整 provider manifest（供 backend /workflows API 展示）。"""
        from contracts.provider_manifest import provider_manifest

        return ServiceResponse(
            status_code=200, body=_to_jsonable(provider_manifest.export_manifest())
        )

    def list_modules_response(self) -> ServiceResponse:
        module_names = list_registered_modules()
        return ServiceResponse(
            status_code=200,
            body={
                "modules": [_build_module_summary(name) for name in module_names],
                "count": len(module_names),
            },
        )

    def describe_module_response(self, module_name: str) -> ServiceResponse:
        try:
            body = _build_module_description(module_name)
        except KeyError:
            return _not_found_service_response(
                error_type="module_not_found",
                error_code="module_not_found",
                user_message="未找到对应模块。",
                developer_message=f"Unknown module_name: {module_name}",
            )
        return ServiceResponse(status_code=200, body=body)

    def list_workflows_response(self) -> ServiceResponse:
        workflow_names = list_named_workflows()
        return ServiceResponse(
            status_code=200,
            body={
                "workflows": [_build_workflow_summary(name) for name in workflow_names],
                "count": len(workflow_names),
            },
        )

    def describe_workflow_response(self, workflow_name: str) -> ServiceResponse:
        try:
            body = _build_workflow_description(workflow_name)
        except KeyError:
            return _not_found_service_response(
                error_type="workflow_not_found",
                error_code="workflow_not_found",
                user_message="未找到对应工作流。",
                developer_message=f"Unknown workflow_name: {workflow_name}",
            )
        return ServiceResponse(status_code=200, body=body)

    def get_workflow_panel_schema_response(self, workflow_name: str) -> ServiceResponse:
        try:
            body = _to_jsonable(_build_workflow_panel_schema(workflow_name))
        except KeyError:
            return _not_found_service_response(
                error_type="workflow_not_found",
                error_code="workflow_not_found",
                user_message="未找到对应工作流。",
                developer_message=f"Unknown workflow_name: {workflow_name}",
            )
        return ServiceResponse(
            status_code=200,
            body=body,
        )

    def get_workflow_ui_schema_response(self, workflow_name: str) -> ServiceResponse:
        try:
            body = _to_jsonable(_build_workflow_ui_schema(workflow_name))
        except KeyError:
            return _not_found_service_response(
                error_type="workflow_not_found",
                error_code="workflow_not_found",
                user_message="未找到对应工作流。",
                developer_message=f"Unknown workflow_name: {workflow_name}",
            )
        return ServiceResponse(
            status_code=200,
            body=body,
        )

    def validate_job(self, payload: object) -> ServiceResponse:
        request, error_response = self._coerce_and_validate_request(payload)
        if error_response is not None:
            return error_response
        return ServiceResponse(
            status_code=200,
            body={
                "valid": True,
                "normalized_request": _to_jsonable(request),
            },
        )

    def submit_job(self, payload: object) -> ServiceResponse:
        request, error_response = self._coerce_and_validate_request(payload)
        if error_response is not None:
            return error_response
        scheduler_adapter, datasource_adapter, logger_adapter, product_sink = (
            self._create_runtime_adapters()
        )
        return self._execute_request(
            request,
            scheduler_adapter=scheduler_adapter,
            datasource_adapter=datasource_adapter,
            logger_adapter=logger_adapter,
            product_sink=product_sink,
        )

    def submit_job_async(self, payload: object) -> ServiceResponse:
        if self._async_job_registry is None or self._job_queue is None:
            return ServiceResponse(
                status_code=501,
                body={
                    "error_type": "async_jobs_not_enabled",
                    "error_code": "async_jobs_not_enabled",
                    "http_status": 501,
                    "retryable": False,
                    "user_message": "当前服务未启用异步任务。",
                    "developer_message": "JobService was created without an async job store or queue.",
                },
            )
        request, error_response = self._coerce_and_validate_request(payload)
        if error_response is not None:
            return error_response
        record = self._async_job_registry.create_submission(request.job_id)
        self._job_queue.enqueue(record.submission_id, request)
        self._async_job_registry.mark_queued(record.submission_id)
        return ServiceResponse(
            status_code=202,
            body={
                "accepted": True,
                "submission_id": record.submission_id,
                "job_id": request.job_id,
                "status": "queued",
                "status_url": f"/jobs/{record.submission_id}",
            },
        )

    def get_job_status(self, submission_id: str) -> ServiceResponse:
        if self._async_job_registry is None:
            return ServiceResponse(
                status_code=501,
                body={
                    "error_type": "async_jobs_not_enabled",
                    "error_code": "async_jobs_not_enabled",
                    "http_status": 501,
                    "retryable": False,
                    "user_message": "当前服务未启用异步任务。",
                    "developer_message": "JobService was created without an async job store.",
                },
            )
        snapshot = self._async_job_registry.get_submission(submission_id)
        if snapshot is None:
            return ServiceResponse(
                status_code=404,
                body={
                    "error_type": "job_not_found",
                    "error_code": "job_not_found",
                    "http_status": 404,
                    "retryable": False,
                    "user_message": "未找到对应的异步作业。",
                    "developer_message": f"Unknown submission_id: {submission_id}",
                },
            )
        body = _to_jsonable(snapshot)
        if snapshot.job_result is not None:
            body["result_dto"] = _to_jsonable(build_job_result_dto(snapshot.job_result))
        return ServiceResponse(status_code=200, body=body)

    def _coerce_and_validate_request(
        self, payload: object
    ) -> tuple[JobRequest | None, ServiceResponse | None]:
        request = None
        try:
            request = coerce_job_request(payload)
            validate_job_request(request)
            return request, None
        except Exception as exc:
            return None, _build_error_response(exc, request=request)

    def _create_runtime_adapters(self) -> tuple[object, object, object, object | None]:
        return (
            self._scheduler_adapter_factory(),
            self._datasource_adapter_factory(),
            self._logger_adapter_factory(),
            self._product_sink_factory(),
        )

    def _execute_request(
        self,
        request: JobRequest,
        *,
        scheduler_adapter,
        datasource_adapter,
        logger_adapter,
        product_sink,
    ) -> ServiceResponse:
        result = self._run_job_fn(
            request,
            scheduler_adapter,
            datasource_adapter,
            logger_adapter,
            product_sink=product_sink,
            workspace=self._workspace,
        )
        if result.status == "success":
            return ServiceResponse(
                status_code=200,
                body={
                    "job_result": _to_jsonable(result),
                    "result_dto": _to_jsonable(build_job_result_dto(result)),
                },
            )
        return ServiceResponse(
            status_code=500,
            body={
                "error_type": "job_execution_failed",
                "error_code": "job_execution_failed",
                "http_status": 500,
                "retryable": False,
                "user_message": "任务执行失败，请检查错误摘要、日志和产物清单。",
                "developer_message": result.error_summary
                or "run_job returned a failed result",
                "job_result": _to_jsonable(result),
                "result_dto": _to_jsonable(build_job_result_dto(result)),
            },
        )


def build_local_job_service(
    *,
    workspace: str | Path | None = None,
    async_job_registry: AsyncJobStore | None = None,
    job_queue: JobQueueBackend | None = None,
    run_job_fn: RunJobFn = run_job,
    start_worker: bool = True,
) -> JobService:
    resolved_workspace = None if workspace is None else Path(workspace)
    async_registry = async_job_registry or AsyncJobRegistry()
    queue_backend = job_queue or InMemoryJobQueue()
    service = JobService(
        scheduler_adapter_factory=LocalSchedulerAdapter,
        datasource_adapter_factory=LocalDataSourceAdapter,
        logger_adapter_factory=ConsoleLoggerAdapter,
        product_sink_factory=(
            (lambda: None)
            if resolved_workspace is None
            else (
                lambda: LocalProductSink(resolved_workspace / "products" / "manifests")
            )
        ),
        workspace=resolved_workspace,
        run_job_fn=run_job_fn,
        async_job_registry=async_registry,
        job_queue=queue_backend,
    )
    if start_worker:
        start_local_async_worker(service)
    return service


def build_local_persistent_job_service(
    *,
    workspace: str | Path,
    job_queue: JobQueueBackend | None = None,
    run_job_fn: RunJobFn = run_job,
    start_worker: bool = True,
) -> JobService:
    resolved_workspace = Path(workspace)
    async_registry = FileAsyncJobRegistry(
        resolved_workspace / "service_state" / "submissions"
    )
    return build_local_job_service(
        workspace=resolved_workspace,
        async_job_registry=async_registry,
        job_queue=job_queue,
        run_job_fn=run_job_fn,
        start_worker=start_worker,
    )


def build_worker(job_service: JobService) -> JobQueueWorker:
    if job_service._async_job_registry is None or job_service._job_queue is None:  # noqa: SLF001
        raise ValueError(
            "JobService must be created with async registry and job queue."
        )
    return JobQueueWorker(
        job_queue=job_service._job_queue,  # noqa: SLF001
        async_job_registry=job_service._async_job_registry,  # noqa: SLF001
        scheduler_adapter_factory=job_service._scheduler_adapter_factory,  # noqa: SLF001
        datasource_adapter_factory=job_service._datasource_adapter_factory,  # noqa: SLF001
        logger_adapter_factory=job_service._logger_adapter_factory,  # noqa: SLF001
        product_sink_factory=job_service._product_sink_factory,  # noqa: SLF001
        workspace=job_service._workspace,  # noqa: SLF001
        run_job_fn=job_service._run_job_fn,  # noqa: SLF001
    )


def start_local_async_worker(job_service: JobService) -> threading.Thread:
    worker = build_worker(job_service)
    thread = threading.Thread(target=lambda: _run_worker_forever(worker), daemon=True)
    thread.start()
    return thread


def _build_error_response(
    error: Exception, *, request: JobRequest | None
) -> ServiceResponse:
    api_error = build_api_error_response(error, request=request)
    return ServiceResponse(
        status_code=api_error.http_status,
        body=_to_jsonable(api_error),
    )


def _build_module_summary(module_name: str) -> dict[str, Any]:
    module = get_registered_module(module_name)
    spec = module.get_spec()
    template = get_module_request_template(module_name)
    return {
        "name": spec.name,
        "description": spec.description,
        "input_ports": _to_jsonable(spec.input_ports),
        "output_ports": _to_jsonable(spec.output_ports),
        "default_params": _to_jsonable(spec.default_params),
        "request_template": None if template is None else _to_jsonable(template),
    }


def _build_module_description(module_name: str) -> dict[str, Any]:
    summary = _build_module_summary(module_name)
    summary["entry_kind"] = "module"
    return summary


def _build_workflow_summary(workflow_name: str) -> dict[str, Any]:
    preview_variants = _build_named_workflow_previews(workflow_name)
    workflow = preview_variants[0][1]
    preview_modes = tuple(
        mode for mode, _workflow in preview_variants if mode is not None
    )
    template = _build_workflow_request_template_preview(workflow_name, preview_variants)
    return {
        "name": workflow.name,
        "workflow_id": workflow.workflow_id,
        "description": workflow.description,
        "node_count": len(workflow.nodes),
        "output_count": len(workflow.outputs),
        "metadata": _to_jsonable(workflow.metadata),
        "request_template": None if template is None else _to_jsonable(template),
        "preview_modes": preview_modes,
    }


def _build_workflow_description(workflow_name: str) -> dict[str, Any]:
    preview_variants = _build_named_workflow_previews(workflow_name)
    workflow = preview_variants[0][1]
    preview_modes = tuple(
        mode for mode, _workflow in preview_variants if mode is not None
    )
    template = _build_workflow_request_template_preview(workflow_name, preview_variants)
    panel_schema = _build_workflow_panel_schema(
        workflow_name, preview_variants=preview_variants
    )
    ui_schema = _build_workflow_ui_schema(
        workflow_name, preview_variants=preview_variants
    )
    body = {
        "name": workflow.name,
        "workflow_id": workflow.workflow_id,
        "description": workflow.description,
        "definition": _to_jsonable(workflow),
        "request_template": None if template is None else _to_jsonable(template),
        "panel_schema": _to_jsonable(panel_schema),
        "ui_schema": _to_jsonable(ui_schema),
        "preview_modes": preview_modes,
    }
    if len(preview_variants) > 1:
        body["definition_variants"] = {
            "default": _to_jsonable(workflow),
            **{
                str(mode): _to_jsonable(variant_workflow)
                for mode, variant_workflow in preview_variants
                if mode is not None
            },
        }
    return body


def _build_named_workflow_preview(workflow_name: str):
    return build_named_workflow(
        workflow_name, _build_preview_request(workflow_name=workflow_name)
    )


def _build_named_workflow_previews(workflow_name: str):
    preview_requests = _build_preview_requests(workflow_name)
    return tuple(
        (
            None
            if request.algorithm_params.get("mode") is None
            else str(request.algorithm_params["mode"]).lower(),
            build_named_workflow(workflow_name, request),
        )
        for request in preview_requests
    )


def _build_workflow_request_template_preview(
    workflow_name: str,
    preview_variants: tuple[tuple[str | None, Any], ...],
) -> RequestTemplateSpec | None:
    templates = [
        build_workflow_request_template(workflow_name, request)
        for request in _build_preview_requests(workflow_name)
    ]
    resolved_templates = [template for template in templates if template is not None]
    if not resolved_templates:
        return None
    if len(resolved_templates) == 1:
        return resolved_templates[0]
    preview_modes = tuple(
        mode for mode, _workflow in preview_variants if mode is not None
    )
    return _merge_request_templates(resolved_templates, preview_modes=preview_modes)


def _build_workflow_panel_schema(
    workflow_name: str,
    *,
    preview_variants: tuple[tuple[str | None, Any], ...] | None = None,
) -> WorkflowInputPanelSchema:
    variants = preview_variants or _build_named_workflow_previews(workflow_name)
    schemas = [
        build_workflow_input_panel_schema(workflow) for _mode, workflow in variants
    ]
    preview_modes = tuple(mode for mode, _workflow in variants if mode is not None)
    if len(schemas) == 1:
        return schemas[0]
    return _merge_panel_schemas(schemas, preview_modes=preview_modes)


def _build_workflow_ui_schema(
    workflow_name: str,
    *,
    preview_variants: tuple[tuple[str | None, Any], ...] | None = None,
) -> WorkflowInputPanelUiSchema:
    panel_schema = _build_workflow_panel_schema(
        workflow_name, preview_variants=preview_variants
    )
    return enhance_panel_schema_with_ui_metadata(panel_schema)


def _build_preview_request(
    *,
    workflow_name: str | None = None,
    module_name: str | None = None,
    algorithm_params: dict[str, object] | None = None,
    datasource_selection: dict[str, object] | None = None,
) -> JobRequest:
    from contracts.product import OutputSpec
    from contracts.runtime import RegionSpec, TimeRange

    task_type = workflow_name or module_name or "workflow"
    return JobRequest(
        job_id="preview-job",
        pipeline_name="workflow",
        task_type=task_type,
        time_range=TimeRange(
            start=datetime(2025, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 2, tzinfo=UTC),
        ),
        region=RegionSpec(kind="global", value={}),
        datasource_selection=dict(datasource_selection) if datasource_selection else {},
        algorithm_params={"mode": "dh"}
        if algorithm_params is None
        else dict(algorithm_params),
        output_spec=OutputSpec(),
        module_name=module_name,
        workflow_name=workflow_name,
    )


def _build_preview_requests(workflow_name: str) -> tuple[JobRequest, ...]:
    preview_modes = _workflow_preview_modes(workflow_name)
    if not preview_modes:
        return (_build_preview_request(workflow_name=workflow_name),)
    # 为各模式提供必要的 datasource_selection 占位键，确保预览变体验证通过
    mode_datasource: dict[str, dict[str, str]] = {
        "ddca": {"dh_mat": "placeholder"},
    }
    return tuple(
        _build_preview_request(
            workflow_name=workflow_name,
            algorithm_params={"mode": mode},
            datasource_selection=mode_datasource.get(mode),
        )
        for mode in preview_modes
    )


def _workflow_preview_modes(workflow_name: str) -> tuple[str, ...]:
    if workflow_name == "retrieval_workflow":
        return ("dh", "ddca", "omega")
    return ()


def _merge_request_templates(
    templates: list[RequestTemplateSpec],
    *,
    preview_modes: tuple[str, ...],
) -> RequestTemplateSpec:
    required_datasource_sets = [
        set(template.required_datasource_keys) for template in templates
    ]
    shared_required_datasource = (
        set.intersection(*required_datasource_sets)
        if required_datasource_sets
        else set()
    )
    all_datasource = set().union(
        *(
            set(template.required_datasource_keys)
            | set(template.optional_datasource_keys)
            for template in templates
        )
    )
    required_algorithm_sets = [
        set(template.required_algorithm_keys) for template in templates
    ]
    shared_required_algorithm = (
        set.intersection(*required_algorithm_sets) if required_algorithm_sets else set()
    )
    all_algorithm = set().union(
        *(
            set(template.required_algorithm_keys)
            | set(template.optional_algorithm_keys)
            for template in templates
        )
    )
    allowed_task_types = set(templates[0].allowed_task_types)
    for template in templates[1:]:
        allowed_task_types &= set(template.allowed_task_types)
    accepted_data_access_datasets = sorted(
        {
            dataset_name
            for template in templates
            for dataset_name in template.accepted_data_access_datasets
        }
    )
    accepted_by_required_key: dict[str, tuple[str, ...]] = {}
    for template in templates:
        for (
            required_key,
            dataset_names,
        ) in template.accepted_data_access_by_required_key.items():
            merged_names = set(accepted_by_required_key.get(required_key, ()))
            merged_names.update(dataset_names)
            accepted_by_required_key[required_key] = tuple(sorted(merged_names))
    allowed_algorithm_values: dict[str, tuple[object, ...]] = {}
    for template in templates:
        for key, values in template.allowed_algorithm_values.items():
            merged_values = set(allowed_algorithm_values.get(key, ()))
            merged_values.update(values)
            allowed_algorithm_values[key] = tuple(sorted(merged_values, key=str))
    notes = [
        note for note in {template.notes for template in templates if template.notes}
    ]
    notes.append(
        "Preview merges workflow variants for modes: "
        + ", ".join(preview_modes)
        + ". Mode-specific inputs are listed as optional."
    )
    return RequestTemplateSpec(
        entry_kind=templates[0].entry_kind,
        entry_name=templates[0].entry_name,
        required_datasource_keys=tuple(sorted(shared_required_datasource)),
        accepted_data_access_datasets=tuple(accepted_data_access_datasets),
        accepted_data_access_by_required_key=accepted_by_required_key,
        optional_datasource_keys=tuple(
            sorted(all_datasource - shared_required_datasource)
        ),
        required_algorithm_keys=tuple(sorted(shared_required_algorithm)),
        optional_algorithm_keys=tuple(
            sorted(all_algorithm - shared_required_algorithm)
        ),
        allowed_task_types=tuple(sorted(allowed_task_types)),
        allowed_algorithm_values=allowed_algorithm_values,
        notes=" ".join(notes),
    )


def _merge_panel_schemas(
    schemas: list[WorkflowInputPanelSchema],
    *,
    preview_modes: tuple[str, ...],
) -> WorkflowInputPanelSchema:
    return WorkflowInputPanelSchema(
        workflow_id=schemas[0].workflow_id,
        workflow_name=schemas[0].workflow_name,
        datasource_fields=_merge_panel_field_group(
            [schema.datasource_fields for schema in schemas], len(schemas)
        ),
        algorithm_param_fields=_merge_panel_field_group(
            [schema.algorithm_param_fields for schema in schemas], len(schemas)
        ),
        request_fields=_merge_panel_field_group(
            [schema.request_fields for schema in schemas], len(schemas)
        ),
        notes=tuple(
            sorted(
                {
                    *[note for schema in schemas for note in schema.notes],
                    "Preview merges workflow variants for modes: "
                    + ", ".join(preview_modes)
                    + ".",
                    "Fields that only appear in some modes are shown as optional.",
                }
            )
        ),
    )


def _merge_panel_field_group(
    field_groups: list[tuple[WorkflowPanelField, ...]],
    variant_count: int,
) -> tuple[WorkflowPanelField, ...]:
    merged: dict[str, list[WorkflowPanelField]] = {}
    for group in field_groups:
        for field in group:
            merged.setdefault(field.key, []).append(field)
    result: list[WorkflowPanelField] = []
    for key, fields in sorted(merged.items()):
        first = fields[0]
        descriptions = tuple(
            dict.fromkeys(field.description for field in fields if field.description)
        )
        result.append(
            WorkflowPanelField(
                key=first.key,
                section=first.section,
                required=len(fields) == variant_count
                and all(field.required for field in fields),
                value_kind=first.value_kind,
                description=" ".join(descriptions) if descriptions else None,
                consumers=tuple(
                    sorted({item for field in fields for item in field.consumers})
                ),
                entry_names=tuple(
                    sorted({item for field in fields for item in field.entry_names})
                ),
                allowed_values=tuple(
                    sorted({item for field in fields for item in field.allowed_values})
                ),
                source_types=tuple(
                    sorted({item for field in fields for item in field.source_types})
                ),
                format_hints=tuple(
                    sorted({item for field in fields for item in field.format_hints})
                ),
            )
        )
    return tuple(result)


def _not_found_service_response(
    *,
    error_type: str,
    error_code: str,
    user_message: str,
    developer_message: str,
) -> ServiceResponse:
    return ServiceResponse(
        status_code=404,
        body={
            "error_type": error_type,
            "error_code": error_code,
            "http_status": 404,
            "retryable": False,
            "user_message": user_message,
            "developer_message": developer_message,
        },
    )


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return value


def _constant_factory(value: Any) -> AdapterFactory:
    return lambda: value


def _run_worker_forever(worker: JobQueueWorker) -> None:
    while True:
        worker.process_next(timeout=0.2)
