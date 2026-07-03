"""Runtime entrypoints and dispatch."""

from runner.call_guard import forbid_shim_pipeline_reentry, push_runtime_call
from runner.dispatch import run_job

__all__ = [
    "forbid_shim_pipeline_reentry",
    "push_runtime_call",
    "run_job",
]
