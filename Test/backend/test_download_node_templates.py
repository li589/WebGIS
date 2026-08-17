"""数据源下载节点模板契约测试（M3/P2f）。

守卫三方契约漂移：
1. BE ``node_template_registry`` 模板 ↔ 算法模块 ``default_params``（模板不暴露
   模块无法消费的幽灵参数）。
2. 模板 ``node_class`` ↔ ``modules.registry`` 注册名（pkgutil 自动发现可达）。
3. ``use`` 枚举选项 ↔ 模块 ``_VALID_USE``（路径选择 auto/主路径/legacy）。

参照 ``test_system_seeds_compile.py::test_ssh_sync_template_contract`` 的守卫思路。
"""

from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/15")

from app.services.node_template_registry import get_node_template  # noqa: E402

# modules/__init__ → modules.base → workflow.schemas 会触发 workflow/__init__ 的
# executor/graph 链回导 modules.registry 形成环；先完整加载 workflow 包破环。
import workflow  # noqa: E402,F401

# node_type → (module_name, module_path)
_DOWNLOAD_CONTRACTS = {
    "download/cds_download": (
        "cds_download",
        "modules.cds_download",
    ),
    "download/nomads_grib_download": (
        "nomads_grib_download",
        "modules.nomads_download",
    ),
    "download/cdse_download": (
        "cdse_download",
        "modules.cdse_download",
    ),
}


def _load_module(module_path: str):
    import importlib

    return importlib.import_module(module_path)


def test_download_templates_exist_with_node_class() -> None:
    for node_type, (node_class, _module_path) in _DOWNLOAD_CONTRACTS.items():
        tpl = get_node_template(node_type)
        assert tpl is not None, node_type
        assert tpl["engine"] == "common", node_type
        assert tpl["category"] == "数据获取与解析", node_type
        assert tpl["node_class"] == node_class, node_type
        outputs = {p["name"]: p["type"] for p in tpl["outputs"]}
        assert outputs.get("path") == "value:string", node_type
        assert "manifest" in outputs, node_type


def test_download_node_class_registered_in_provider_registry() -> None:
    from modules.registry import get_module, list_modules

    registered = set(list_modules())
    for node_type, (node_class, _module_path) in _DOWNLOAD_CONTRACTS.items():
        assert node_class in registered, f"{node_type}: module not auto-discovered"
        module = get_module(node_class)
        assert module.name == node_class or type(module).__name__, node_type


def test_download_template_params_module_consumable() -> None:
    """模板参数必须是模块 default_params 的子集（幽灵参数回归守卫）。"""
    from modules.registry import get_module

    for node_type, (node_class, _module_path) in _DOWNLOAD_CONTRACTS.items():
        tpl = get_node_template(node_type)
        assert tpl is not None, node_type
        template_keys = {p["key"] for p in tpl["params"]}
        consumable = set(get_module(node_class).default_params)
        assert (
            template_keys <= consumable
        ), f"{node_type}: ghost params {sorted(template_keys - consumable)}"


def test_download_use_enum_matches_module_validation() -> None:
    """use 下拉选项必须与模块 _VALID_USE 一致，否则运行时直接 ValueError。"""
    for node_type, (_node_class, module_path) in _DOWNLOAD_CONTRACTS.items():
        tpl = get_node_template(node_type)
        assert tpl is not None, node_type
        use_param = next(p for p in tpl["params"] if p["key"] == "use")
        valid_use = sorted(getattr(_load_module(module_path), "_VALID_USE"))
        assert use_param.get("options") == valid_use, node_type
        assert use_param.get("default") == "auto", node_type
        assert use_param.get("allow_custom") is False, node_type


def test_download_templates_declare_datasource_selection_input() -> None:
    """datasource_selection config 输入端口：门户凭据注入通道（fy_download 同款）。"""
    for node_type in _DOWNLOAD_CONTRACTS:
        tpl = get_node_template(node_type)
        assert tpl is not None, node_type
        inputs = {p["name"]: p for p in tpl["inputs"]}
        port = inputs.get("datasource_selection")
        assert port is not None, node_type
        assert port["type"] == "config", node_type
        assert port["required"] is False, node_type
