from __future__ import annotations

import unittest
from pathlib import Path

from contracts.runtime import RuntimeContext
from runner.call_guard import MAX_CALL_DEPTH, push_runtime_call


class CallGuardTests(unittest.TestCase):
    def _build_runtime_context(self) -> RuntimeContext:
        workspace = Path(".")
        return RuntimeContext(
            job_id="job-call-guard",
            run_id="run-call-guard",
            workspace=workspace,
            tmp_dir=workspace / "tmp",
            cache_dir=workspace / "cache",
        )

    def test_push_runtime_call_rejects_recursive_entry(self) -> None:
        runtime_context = self._build_runtime_context()

        with push_runtime_call(runtime_context, "workflow:wf-a"):
            with self.assertRaisesRegex(
                RuntimeError, "Recursive runtime call detected"
            ):
                with push_runtime_call(runtime_context, "workflow:wf-a"):
                    self.fail("recursive entry should not be allowed")

    def test_push_runtime_call_rejects_depth_overflow(self) -> None:
        runtime_context = self._build_runtime_context()
        runtime_context.call_chain = [
            f"entry:{index}" for index in range(MAX_CALL_DEPTH)
        ]

        with self.assertRaisesRegex(
            RuntimeError, f"Runtime call depth exceeds limit {MAX_CALL_DEPTH}"
        ):
            with push_runtime_call(runtime_context, "workflow:wf-overflow"):
                self.fail("depth overflow should not be allowed")

    def test_push_runtime_call_pops_entry_after_exit(self) -> None:
        runtime_context = self._build_runtime_context()

        with push_runtime_call(runtime_context, "workflow:wf-a"):
            self.assertEqual(runtime_context.call_chain, ["workflow:wf-a"])

        self.assertEqual(runtime_context.call_chain, [])


if __name__ == "__main__":
    unittest.main()
