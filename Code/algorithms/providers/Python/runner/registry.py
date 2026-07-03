from __future__ import annotations

from dataclasses import dataclass

from pipelines.block_inversion_products import BlockInversionPipeline
from pipelines.daily_bundle_products import DailyBundlePipeline
from pipelines.fy_products import FyDailyPipeline
from pipelines.inversion_products import InversionDailyPipeline
from pipelines.ndvi_products import NdviDailyPipeline
from pipelines.omega_block_products import OmegaBlockPipeline
from pipelines.base import BasePipeline
from pipelines.retrieval_workflow_products import RetrievalWorkflowPipeline
from pipelines.smap_products import SmapDailyPipeline
from pipelines.station_products import StationDailyPipeline
from pipelines.timeseries_bundle_products import TimeSeriesBundlePipeline


# Legacy registry retained for direct pipeline_name compatibility.
# Native execution should prefer module_name / workflow_name / workflow_definition.
PIPELINE_REGISTRY: dict[str, type[BasePipeline]] = {}


@dataclass(frozen=True, slots=True)
class PipelineCompatibilityInfo:
    preferred_entry: str
    status: str
    notes: str


PIPELINE_COMPATIBILITY: dict[str, PipelineCompatibilityInfo] = {
    "block_inversion_pipeline": PipelineCompatibilityInfo(
        preferred_entry="module_name=block_inversion",
        status="legacy_compat",
        notes="Native BlockInversionModule is the preferred entry; keep pipeline_name for old callers.",
    ),
    "daily_bundle_pipeline": PipelineCompatibilityInfo(
        preferred_entry="module_name=daily_bundle",
        status="legacy_compat",
        notes="Native DailyBundleModule is the preferred entry; keep pipeline_name for old callers.",
    ),
    "fy_daily_pipeline": PipelineCompatibilityInfo(
        preferred_entry="module_name=fy_daily",
        status="legacy_compat",
        notes="Native FyDailyModule is the preferred entry; keep pipeline_name for old callers.",
    ),
    "inversion_daily_pipeline": PipelineCompatibilityInfo(
        preferred_entry="module_name=inversion_daily",
        status="legacy_compat",
        notes="Native InversionDailyModule is the preferred entry; keep pipeline_name for old callers.",
    ),
    "ndvi_daily_pipeline": PipelineCompatibilityInfo(
        preferred_entry="module_name=ndvi_daily",
        status="legacy_compat",
        notes="Native NdviDailyModule is the preferred entry; keep pipeline_name for old callers.",
    ),
    "omega_block_pipeline": PipelineCompatibilityInfo(
        preferred_entry="module_name=omega_block",
        status="legacy_compat",
        notes="Native OmegaBlockModule is the preferred entry; keep pipeline_name for old callers.",
    ),
    "retrieval_workflow_pipeline": PipelineCompatibilityInfo(
        preferred_entry="workflow_name=retrieval_workflow",
        status="shim_compat",
        notes="Compatibility-only shim; run_job() auto-promotes this pipeline_name to the retrieval_workflow preset.",
    ),
    "smap_daily_pipeline": PipelineCompatibilityInfo(
        preferred_entry="module_name=smap_daily",
        status="legacy_compat",
        notes="Native SmapDailyModule is the preferred entry; keep pipeline_name for old callers.",
    ),
    "station_daily_pipeline": PipelineCompatibilityInfo(
        preferred_entry="module_name=station_daily",
        status="legacy_compat",
        notes="Native StationDailyModule is the preferred entry; keep pipeline_name for old callers.",
    ),
    "timeseries_bundle_pipeline": PipelineCompatibilityInfo(
        preferred_entry="module_name=timeseries_bundle",
        status="legacy_compat",
        notes="Native TimeSeriesBundleModule is the preferred entry; keep pipeline_name for old callers.",
    ),
}


def register_pipeline(name: str, pipeline_cls: type[BasePipeline]) -> None:
    PIPELINE_REGISTRY[name] = pipeline_cls


def get_pipeline(name: str) -> type[BasePipeline]:
    if name not in PIPELINE_REGISTRY:
        raise KeyError(f"Pipeline not registered: {name}")
    return PIPELINE_REGISTRY[name]


register_pipeline(BlockInversionPipeline.name, BlockInversionPipeline)
register_pipeline(DailyBundlePipeline.name, DailyBundlePipeline)
register_pipeline(OmegaBlockPipeline.name, OmegaBlockPipeline)
register_pipeline(RetrievalWorkflowPipeline.name, RetrievalWorkflowPipeline)
register_pipeline(TimeSeriesBundlePipeline.name, TimeSeriesBundlePipeline)
register_pipeline(SmapDailyPipeline.name, SmapDailyPipeline)
register_pipeline(NdviDailyPipeline.name, NdviDailyPipeline)
register_pipeline(FyDailyPipeline.name, FyDailyPipeline)
register_pipeline(StationDailyPipeline.name, StationDailyPipeline)
register_pipeline(InversionDailyPipeline.name, InversionDailyPipeline)
