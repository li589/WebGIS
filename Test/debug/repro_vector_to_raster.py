import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "Code" / "algorithms" / "providers" / "Python"))

from runner.dispatch import run_job
from contracts.job import JobRequest, OutputSpec, TimeRange, RegionSpec

req = JobRequest(
    job_id="repro-v2r",
    pipeline_name="workflow",
    task_type="analysis",
    module_name="gis_vector_to_raster",
    workflow_name=None,
    time_range=TimeRange(start="2025-01-01T00:00:00", end="2025-01-02T00:00:00"),
    region=RegionSpec(kind="global", value={}),
    datasource_selection={
        "input_path": "I:/Geograph_DataSet/_runtime/smoke_vector.geojson"
    },
    algorithm_params={"attribute_field": "", "resolution": 0.01, "fill_value": 0},
    output_spec=OutputSpec(include_manifest=True, extra={}),
    tags={},
)

from utils.local_adapters import (
    LocalSchedulerAdapter,
    LocalDataSourceAdapter,
    ConsoleLoggerAdapter,
)

result = run_job(
    req, LocalSchedulerAdapter(), LocalDataSourceAdapter(), ConsoleLoggerAdapter()
)
print("status:", result.status)
if result.error:
    print("error:", result.error)
print("outputs keys:", list(result.outputs.keys()) if isinstance(result.outputs, dict) else result.outputs)
