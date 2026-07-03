from __future__ import annotations

from modules.registry import get_module
from workflow.registry import register_node_executor
from workflow.schemas import NodeExecutionContext, PortSpec


class ModuleNodeExecutor:
    node_type = "module"

    def get_input_ports(self) -> list[PortSpec]:
        return []

    def get_output_ports(self) -> list[PortSpec]:
        return []

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        module_name = str(params["module_name"])
        module = get_module(module_name)
        resolved_params = module.resolve_params(params)
        return module.execute(inputs, resolved_params, ctx)


register_node_executor(ModuleNodeExecutor.node_type, ModuleNodeExecutor)
