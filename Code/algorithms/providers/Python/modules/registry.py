from __future__ import annotations

from modules.base import BaseModule


MODULE_REGISTRY: dict[str, BaseModule] = {}
MODULE_ALIASES: dict[str, str] = {}
_DEFAULT_MODULES_LOADED = False


def _ensure_default_modules_loaded() -> None:
    global _DEFAULT_MODULES_LOADED
    if _DEFAULT_MODULES_LOADED:
        return
    from modules import block_inversion  # noqa: F401
    from modules import bundles  # noqa: F401
    from modules import fy  # noqa: F401
    from modules import inversion  # noqa: F401
    from modules import ndvi  # noqa: F401
    from modules import omega  # noqa: F401
    from modules import smap  # noqa: F401
    from modules import station  # noqa: F401

    _DEFAULT_MODULES_LOADED = True


def register_module(module: BaseModule, aliases: list[str] | None = None) -> None:
    MODULE_REGISTRY[module.name] = module
    for alias in aliases or []:
        MODULE_ALIASES[alias] = module.name


def get_module(name: str) -> BaseModule:
    _ensure_default_modules_loaded()
    canonical_name = MODULE_ALIASES.get(name, name)
    if canonical_name not in MODULE_REGISTRY:
        raise KeyError(f"Module not registered: {name}")
    return MODULE_REGISTRY[canonical_name]


def list_modules() -> list[str]:
    _ensure_default_modules_loaded()
    return sorted(MODULE_REGISTRY)
