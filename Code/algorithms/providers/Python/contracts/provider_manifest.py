"""Provider 标准契约模板单一入口。

集中暴露 module / pipeline / workflow preset 的查询、校验、导出能力，
为 backend bridge 层提供统一 API。

用法（bridge 端）：
    from contracts.provider_manifest import provider_manifest

    # 查询所有 module 模板
    templates = provider_manifest.list_module_templates()

    # 校验 JobRequest
    is_valid, errors = provider_manifest.validate_request(request, entry_name="omega_block")

    # 导出 manifest（供 /workflows API 展示）
    manifest = provider_manifest.export_manifest()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from contracts.job import JobRequest
from contracts.request_templates import RequestTemplateSpec
from contracts.template_deriver import (
    derive_template_from_module,
    get_module_request_template,
    list_module_templates,
    validate_request_against_template,
)


@dataclass
class ValidationResult:
    """模板校验结果。"""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    template: RequestTemplateSpec | None = None


class ProviderManifest:
    """Provider 标准契约清单。

    单一入口聚合 module / pipeline / workflow preset 的查询与校验。
    """

    def list_module_templates(self) -> dict[str, RequestTemplateSpec]:
        """列出所有 module 的 RequestTemplateSpec（手工 + 自动推导）。"""
        return list_module_templates()

    def get_module_template(self, name: str) -> RequestTemplateSpec | None:
        """获取单个 module 的 RequestTemplateSpec。"""
        return get_module_request_template(name)

    def list_workflows(self) -> list[str]:
        """列出所有命名 workflow preset。"""
        try:
            from workflow.presets import list_named_workflows

            return sorted(list_named_workflows())
        except ImportError:
            return []

    def list_pipelines(self) -> list[str]:
        """列出所有 legacy pipeline（兼容用）。"""
        try:
            from runner.registry import PIPELINE_REGISTRY

            return sorted(PIPELINE_REGISTRY)
        except ImportError:
            return []

    def list_modules(self) -> list[str]:
        """列出所有已注册 module。"""
        try:
            from modules.registry import list_modules

            return list_modules()
        except ImportError:
            return []

    def validate_request(
        self,
        request: JobRequest,
        *,
        entry_name: str | None = None,
    ) -> ValidationResult:
        """基于模板校验 JobRequest。

        Args:
            request: JobRequest 实例
            entry_name: 指定 module/workflow 名称；若为 None 则自动从 request 推导

        Returns:
            ValidationResult
        """
        # 自动推导 entry_name
        if entry_name is None:
            entry_name = (
                request.workflow_entry_name
                or request.module_name
                or request.workflow_name
                or request.pipeline_name
            )

        if entry_name is None:
            return ValidationResult(
                is_valid=False,
                errors=["Cannot determine entry_name from request (module_name/workflow_name/pipeline_name all empty)"],
            )

        # 查找 template：先查 module，再查 workflow preset
        template = self.get_module_template(entry_name)
        if template is None:
            # 尝试 workflow preset template
            template = self._build_workflow_template(entry_name, request)

        if template is None:
            # 未注册的 entry_name：不阻断（允许自定义 workflow_definition）
            return ValidationResult(is_valid=True, errors=[], template=None)

        is_valid, errors = validate_request_against_template(request, template)
        return ValidationResult(is_valid=is_valid, errors=errors, template=template)

    def _build_workflow_template(
        self,
        name: str,
        request: JobRequest,
    ) -> RequestTemplateSpec | None:
        """构建 workflow preset 的 template。"""
        try:
            from contracts.request_templates import build_workflow_request_template

            return build_workflow_request_template(name, request)
        except ImportError:
            return None

    def export_manifest(self) -> dict[str, Any]:
        """导出完整 manifest（供 /workflows API 展示）。

        Returns:
            dict 包含 modules / workflows / pipelines 三部分
        """
        module_templates = self.list_module_templates()
        modules_info: list[dict[str, Any]] = []
        for name, template in sorted(module_templates.items()):
            modules_info.append(
                {
                    "name": name,
                    "entry_kind": template.entry_kind,
                    "required_datasource_keys": list(template.required_datasource_keys),
                    "optional_datasource_keys": list(template.optional_datasource_keys),
                    "required_algorithm_keys": list(template.required_algorithm_keys),
                    "optional_algorithm_keys": list(template.optional_algorithm_keys),
                    "allowed_task_types": list(template.allowed_task_types),
                    "allowed_algorithm_values": {
                        k: list(v) for k, v in template.allowed_algorithm_values.items()
                    },
                    "accepted_data_access_datasets": list(template.accepted_data_access_datasets),
                    "notes": template.notes,
                }
            )

        return {
            "modules": modules_info,
            "workflows": self.list_workflows(),
            "pipelines": self.list_pipelines(),
            "summary": {
                "module_count": len(modules_info),
                "workflow_count": len(self.list_workflows()),
                "pipeline_count": len(self.list_pipelines()),
            },
        }


# 单例
provider_manifest = ProviderManifest()
