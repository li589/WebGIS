from __future__ import annotations

from contextlib import contextmanager

from contracts.runtime import RuntimeContext


MAX_CALL_DEPTH = 8


def forbid_shim_pipeline_reentry(pipeline_name: str) -> None:
    from runner.registry import PIPELINE_COMPATIBILITY

    info = PIPELINE_COMPATIBILITY.get(pipeline_name)
    if info is not None and info.status == "shim_compat":
        raise RuntimeError(
            f"Compatibility shim pipeline cannot be called from nested bridge/module execution: {pipeline_name}"
        )


@contextmanager
def push_runtime_call(runtime_context: RuntimeContext, entry: str):
    chain = runtime_context.call_chain
    if entry in chain:
        raise RuntimeError(
            f"Recursive runtime call detected: {' -> '.join([*chain, entry])}"
        )
    if len(chain) >= MAX_CALL_DEPTH:
        raise RuntimeError(
            f"Runtime call depth exceeds limit {MAX_CALL_DEPTH}: {' -> '.join(chain)}"
        )
    chain.append(entry)
    try:
        yield
    finally:
        chain.pop()
