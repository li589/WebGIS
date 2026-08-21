from __future__ import annotations

import threading
from contextlib import contextmanager

from contracts.runtime import RuntimeContext


MAX_CALL_DEPTH = 8

# 安审 2026-08-21 H-2：runtime_context 在同层并行节点（node_parallelism>1）
# 间共享，call_chain 的「检查 → append → finally pop」为无锁 check-then-act：
# 两线程 push 相同 entry 会假阳性报 Recursive；交错 pop 会弹掉对方条目。
# 以 entry 级锁串行化临界区（模块级全局锁即可——临界区极短，仅 list 操作）。
_CALL_CHAIN_LOCK = threading.Lock()


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
    with _CALL_CHAIN_LOCK:
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
        with _CALL_CHAIN_LOCK:
            # 防御：pop 可能被并发交错影响——只弹出自己 push 的 entry
            try:
                chain.remove(entry)
            except ValueError:
                pass  # 链已被外层异常路径清理
