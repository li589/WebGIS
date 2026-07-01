from __future__ import annotations

from algorithms.providers.base import AlgorithmProvider
from algorithms.providers.lab_output import lab_output_provider

REGISTERED_PROVIDERS: tuple[AlgorithmProvider, ...] = (lab_output_provider,)
LAYER_PROVIDER_INDEX: dict[str, AlgorithmProvider] = {
    layer_id: provider
    for provider in REGISTERED_PROVIDERS
    for layer_id in provider.supported_layers
}


def get_provider_for_layer(layer_id: str) -> AlgorithmProvider | None:
    return LAYER_PROVIDER_INDEX.get(layer_id)
