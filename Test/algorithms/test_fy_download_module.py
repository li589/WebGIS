"""fy_download 模块：日期范围多日循环与逐日源回退。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import contracts.job  # noqa: F401  # break modules.registry ↔ workflow.panel_schema cycle


class _FakeArtifactStore:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}

    def put(self, artifact, payload=None) -> object:
        self.items[artifact.artifact_id] = payload
        return artifact


def _ctx(workspace: Path):
    from workflow.schemas import NodeExecutionContext

    request = SimpleNamespace(
        job_id="job-fy-1",
        datasource_selection={},
        region=None,
        time_range=None,
    )
    runtime = SimpleNamespace(run_id="run-fy-1", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n1",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_FakeArtifactStore(),  # type: ignore[arg-type]
    )


class TestIterDateRange(unittest.TestCase):
    def test_single_day_without_end(self) -> None:
        from modules.fy_download import _iter_date_range

        self.assertEqual(_iter_date_range("2025-12-01", ""), ["2025-12-01"])

    def test_multi_day_inclusive(self) -> None:
        from modules.fy_download import _iter_date_range

        days = _iter_date_range("2025-12-30", "2026-01-02")
        self.assertEqual(
            days, ["2025-12-30", "2025-12-31", "2026-01-01", "2026-01-02"]
        )

    def test_dot_format_accepted(self) -> None:
        from modules.fy_download import _iter_date_range

        self.assertEqual(_iter_date_range("2025.12.01", "2025.12.03")[0], "2025-12-01")
        self.assertEqual(len(_iter_date_range("2025.12.01", "2025.12.03")), 3)

    def test_end_before_start_raises(self) -> None:
        from modules.fy_download import _iter_date_range

        with self.assertRaises(ValueError):
            _iter_date_range("2026-01-02", "2026-01-01")

    def test_range_cap_enforced(self) -> None:
        from modules.fy_download import _iter_date_range

        with self.assertRaises(ValueError):
            _iter_date_range("2020-01-01", "2026-01-01")

    def test_empty_start_returns_empty(self) -> None:
        from modules.fy_download import _iter_date_range

        self.assertEqual(_iter_date_range("", ""), [])


class TestFYDownloadExecute(unittest.TestCase):
    def _run(self, tmp: str, *, params: dict, side_effects=None):
        from modules.fy_download import FYDownloadModule

        workspace = Path(tmp) / "ws"
        workspace.mkdir()
        ctx = _ctx(workspace)
        module = FYDownloadModule()
        with patch(
            "modules.fy_download._download_from_nsmc",
            side_effect=(side_effects or {}).get("nsmc"),
        ) as nsmc, patch(
            "modules.fy_download._fetch_from_nas",
            side_effect=(side_effects or {}).get("nas"),
        ) as nas:
            out = module.execute(inputs={}, params=params, ctx=ctx)
        manifest = next(iter(ctx.artifact_store.items.values()))
        return out, manifest.extra, nsmc, nas

    def test_multi_day_downloads_each_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out, extra, nsmc, _ = self._run(
                tmp,
                params={
                    "start_date": "2025-12-01",
                    "end_date": "2025-12-03",
                    "data_source": "nsmc",
                },
            )
            self.assertEqual(nsmc.call_count, 3)
            date_paths = [str(c.kwargs.get("date_path")) for c in nsmc.call_args_list]
            self.assertEqual(
                date_paths, ["2025.12.01", "2025.12.02", "2025.12.03"]
            )
            self.assertEqual(extra["day_count"], 3)
            self.assertEqual(
                extra["dates"],
                ["2025-12-01", "2025-12-02", "2025-12-03"],
            )
            self.assertTrue(Path(out["path"]).is_dir())

    def test_auto_falls_back_per_day(self) -> None:
        calls = {"nsmc": 0, "nas": 0}

        def _nsmc(ctx, **kwargs):
            calls["nsmc"] += 1
            if kwargs.get("date_path") == "2025.12.02":
                raise RuntimeError("nsmc down")
            return Path(kwargs["target_dir"])

        def _nas(ctx, **kwargs):
            calls["nas"] += 1
            return Path(kwargs["target_dir"])

        with tempfile.TemporaryDirectory() as tmp:
            _, extra, _, _ = self._run(
                tmp,
                params={
                    "start_date": "2025-12-01",
                    "end_date": "2025-12-03",
                    "data_source": "auto",
                },
                side_effects={"nsmc": _nsmc, "nas": _nas},
            )
            self.assertEqual(calls, {"nsmc": 3, "nas": 1})
            self.assertEqual(extra["data_source"], "nsmc+nas")

    def test_all_sources_failed_for_day_raises(self) -> None:
        def _boom(ctx, **kwargs):
            raise RuntimeError("network unreachable")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as cm:
                self._run(
                    tmp,
                    params={
                        "start_date": "2025-12-01",
                        "end_date": "2025-12-02",
                        "data_source": "auto",
                    },
                    side_effects={"nsmc": _boom, "nas": _boom},
                )
            msg = str(cm.exception)
            self.assertIn("2025-12-01", msg)
            self.assertIn("network unreachable", msg)

    def test_missing_start_date_raises(self) -> None:
        from modules.fy_download import FYDownloadModule

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            with self.assertRaises(ValueError):
                FYDownloadModule().execute(
                    inputs={}, params={}, ctx=_ctx(workspace)
                )


if __name__ == "__main__":
    unittest.main()
