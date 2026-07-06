from __future__ import annotations

from typing import Any, Callable

from modules.base import BaseModule


MODULE_REGISTRY: dict[str, BaseModule] = {}
MODULE_ALIASES: dict[str, str] = {}
# 模板覆盖项：module_name → 覆盖字段 dict
# 由 @register_module(template_overrides=...) 注册，供自动推导使用
_TEMPLATE_OVERRIDES: dict[str, dict[str, Any]] = {}
_DEFAULT_MODULES_LOADED = False


def _ensure_default_modules_loaded() -> None:
    global _DEFAULT_MODULES_LOADED
    if _DEFAULT_MODULES_LOADED:
        return
    import importlib
    import logging
    import pkgutil
    from pathlib import Path

    _logger = logging.getLogger(__name__)
    # 扫描 modules/ 目录下所有 .py 文件（排除特殊文件）
    modules_dir = Path(__file__).parent
    exclude = {"__init__", "base", "compat", "registry"}
    for _finder, name, _ispkg in pkgutil.iter_modules([str(modules_dir)]):
        if name in exclude:
            continue
        try:
            importlib.import_module(f"modules.{name}")
        except Exception as e:  # noqa: BLE001
            _logger.warning(f"Failed to load module {name}: {e}")
    # 兜底：注册未被原生实现覆盖的兼容 shim。懒导入避免循环依赖。
    from modules.compat import register_default_compat_modules

    register_default_compat_modules()
    _DEFAULT_MODULES_LOADED = True


def register_module(
    module: BaseModule,
    aliases: list[str] | None = None,
    template_overrides: dict[str, Any] | None = None,
    name_override: str | None = None,
) -> None:
    """注册 module 到全局注册表。

    Args:
        module: BaseModule 实例
        aliases: 别名列表（如 ["ndvi_daily_pipeline"]）
        template_overrides: RequestTemplateSpec 覆盖字段
            支持的 key: accepted_data_access_datasets / allowed_task_types /
            allowed_algorithm_values / notes / required_algorithm_keys 等
            未覆盖的字段由 ModuleSpec 自动推导
        name_override: 注册名覆盖。若提供，使用此名称作为注册表 key，
            而非 module.name。供 @register_module_decorator(name=...) 使用。
    """
    registry_key = name_override or module.name
    MODULE_REGISTRY[registry_key] = module
    for alias in aliases or []:
        MODULE_ALIASES[alias] = registry_key
    if template_overrides:
        _TEMPLATE_OVERRIDES[registry_key] = dict(template_overrides)


def register_module_decorator(
    *,
    name: str | None = None,
    aliases: list[str] | None = None,
    template_overrides: dict[str, Any] | None = None,
) -> Callable[[type[BaseModule]], type[BaseModule]]:
    """类装饰器：声明式注册 module。

    用法：
        @register_module_decorator(name="ndvi_daily", aliases=["ndvi_daily_pipeline"])
        class NdviDailyModule(BaseModule):
            ...

    等价于：
        class NdviDailyModule(BaseModule):
            ...
        register_module(NdviDailyModule(), aliases=["ndvi_daily_pipeline"], name_override="ndvi_daily")
    """

    def _decorator(cls: type[BaseModule]) -> type[BaseModule]:
        instance = cls()
        # 若未指定 name，使用类属性 name
        module_name = name or cls.name
        # 修复：传入 name_override 使注册表使用 decorator 指定的 name 作为 key，
        # 而非 instance.name。此前此参数失效，传入 name='ndvi_daily' 但类属性
        # name='ndvi' 时仍以 'ndvi' 注册。
        name_override = module_name if name and name != instance.name else None
        register_module(
            instance,
            aliases=aliases,
            template_overrides=template_overrides,
            name_override=name_override,
        )
        return cls

    return _decorator


# 暴露更短的别名
register_module_dec = register_module_decorator


def get_module(name: str) -> BaseModule:
    _ensure_default_modules_loaded()
    canonical_name = MODULE_ALIASES.get(name, name)
    if canonical_name not in MODULE_REGISTRY:
        raise KeyError(f"Module not registered: {name}")
    return MODULE_REGISTRY[canonical_name]


def list_modules() -> list[str]:
    _ensure_default_modules_loaded()
    return sorted(MODULE_REGISTRY)


def get_template_overrides(name: str) -> dict[str, Any]:
    """获取 module 的模板覆盖字段。"""
    _ensure_default_modules_loaded()
    canonical_name = MODULE_ALIASES.get(name, name)
    return _TEMPLATE_OVERRIDES.get(canonical_name, {})
