"""Provider 注册表。

注意：``lab_output`` 是样板/兼容入口（sample），不是生产算法主叙事。
正式计算应走 ``algorithms/providers/Python`` 的 python_provider bridge。
"""
from __future__ import annotations

from algorithms.providers.base import AlgorithmProvider
from algorithms.providers.lab_output import lab_output_provider

# 样板仅用于兼容与联调；勿把 REGISTRY 当作「已接入全部课题组算法」的证据。
REGISTERED_PROVIDERS: tuple[AlgorithmProvider, ...] = (lab_output_provider,)
LAYER_PROVIDER_INDEX: dict[str, AlgorithmProvider] = {
    layer_id: provider
    for provider in REGISTERED_PROVIDERS
    for layer_id in provider.supported_layers
}


def get_provider_for_layer(layer_id: str) -> AlgorithmProvider | None:
    return LAYER_PROVIDER_INDEX.get(layer_id)


def list_registered_layers() -> list[str]:
    """返回所有已注册的 provider layer_id 列表。"""
    return sorted(LAYER_PROVIDER_INDEX.keys())
