"""Module integration tests for OmegaAvgDailyModule (modules/omega_avg_daily.py).

Drives the full 4-stage pipeline (Stage A raw cache → Stage B DOY climatology →
Stage C h/alpha extract → Stage D per-day DDCA) against the synthetic dataset
produced by Tools/generate_synthetic_test_data.py::generate_omega_avg_daily_inputs.

The provider package has a circular import (contracts <-> workflow); importing
``contracts`` first breaks the cycle (same pattern as service/job_api.py and
test_omega_avg_algorithm.py).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

# ── Provider path setup (must precede algorithm imports) ─────────────────────
_PROVIDER_ROOT = (
    Path(__file__).resolve().parents[2] / "algorithms" / "providers" / "Python"
)
if str(_PROVIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROVIDER_ROOT))

import contracts  # noqa: E402, F401 — break circular import: contracts first
from contracts.job import JobRequest  # noqa: E402
from contracts.product import OutputSpec  # noqa: E402
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange  # noqa: E402
from modules.omega_avg_daily import OmegaAvgDailyModule  # noqa: E402
from workflow.schemas import NodeExecutionContext  # noqa: E402

# ── Synthetic data root ─────────────────────────────────────────────────────
# Tools/ lives at the repo root (parents[3] from Code/backend/tests/*.py),
# unlike algorithms/ which is under Code/ (parents[2]).
_SYNTH_ROOT = (
    Path(__file__).resolve().parents[3]
    / "Tools"
    / "test_data"
    / "omega_avg_daily_inputs"
)


# ── Minimal artifact store (dict-backed) ────────────────────────────────────


class _DictArtifactStore:
    """Minimal ArtifactStoreLike for tests: stores (artifact, payload) in a dict."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[object, object]] = {}

    def put(self, artifact: object, payload: object | None = None) -> object:
        artifact_id = getattr(artifact, "artifact_id", "")
        self._store[artifact_id] = (artifact, payload)
        return artifact

    def get(self, artifact_id: str) -> object:
        return self._store[artifact_id][0]

    def load(self, artifact_id: str) -> object:
        return self._store[artifact_id][1]

    def exists(self, artifact_id: str) -> bool:
        return artifact_id in self._store


# ── Context builder ─────────────────────────────────────────────────────────


def _build_ctx(workspace: Path) -> NodeExecutionContext:
    """Build a minimal NodeExecutionContext for module.execute()."""
    request = JobRequest(
        job_id="test-d2-module",
        pipeline_name="omega_avg_daily",
        task_type="omega_avg_daily",
        time_range=TimeRange(start=datetime(2023, 1, 1), end=datetime(2023, 1, 10)),
        region=RegionSpec(kind="bbox", value={}),
        datasource_selection={},
        algorithm_params={},
        output_spec=OutputSpec(),
    )
    runtime_context = RuntimeContext(
        job_id=request.job_id,
        run_id="test-run-d2",
        workspace=workspace,
        tmp_dir=workspace / "tmp",
        cache_dir=workspace / "cache",
    )
    (workspace / "tmp").mkdir(parents=True, exist_ok=True)
    (workspace / "cache").mkdir(parents=True, exist_ok=True)
    return NodeExecutionContext(
        workflow_id="test-workflow-d2",
        node_id="node-omega-avg-daily",
        request=request,
        runtime_context=runtime_context,
        workspace=workspace,
        artifact_store=_DictArtifactStore(),
        datasource_adapter=None,
        logger_adapter=None,
        product_sink=None,
    )


def _build_inputs(output_dir: Path) -> dict[str, object]:
    """Build module inputs pointing at the synthetic D2 dataset."""
    return {
        "datasource_selection": {
            "omega_block_dir": str(_SYNTH_ROOT / "omega_block"),
            "smap_folder": str(_SYNTH_ROOT / "smap_daily"),
            "ndvi_folder": str(_SYNTH_ROOT / "ndvi_daily"),
            "ndvi_clim_folder": str(_SYNTH_ROOT / "ndvi_clim"),
            "anc_root": str(_SYNTH_ROOT / "anc"),
            "ndvi_extrema_mat": str(_SYNTH_ROOT / "anc" / "NDVI_extrema.mat"),
        },
        "algorithm_params": {
            "target_year": 2023,
            "tb_source": "SMAP",
            "temp_scheme": "ORIG_TS",
            "ndvi_mode": "DAILY_FILE",
            "sf_mode": "STATIC",
            "sm_source": "SMAP",
            "enable_parallel": False,
            "avg_build_start_year": 2023,
            "avg_build_end_year": 2023,
            "grid_shape": [24, 48],
            "print_every_days": 5,
        },
        "output_spec_extra": {
            "output_dir": str(output_dir),
        },
    }


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not _SYNTH_ROOT.exists(),
    reason=(
        f"Synthetic D2 inputs not found at {_SYNTH_ROOT}. "
        "Run `python Tools/generate_synthetic_test_data.py` first."
    ),
)
def test_omega_avg_daily_module_executes_end_to_end(tmp_path: Path) -> None:
    """OmegaAvgDailyModule.execute() runs all 4 stages and produces daily SM/VOD/OMEGA."""
    output_dir = tmp_path / "d2_out"
    ctx = _build_ctx(tmp_path)
    inputs = _build_inputs(output_dir)

    module = OmegaAvgDailyModule()
    result = module.execute(inputs=inputs, params={}, ctx=ctx)

    # Module returns {"manifest": ArtifactRef}
    assert "manifest" in result
    artifact = result["manifest"]
    assert artifact is not None

    # The manifest payload should be stored in the artifact store
    manifest = ctx.artifact_store.load(artifact.artifact_id)
    assert manifest is not None
    main_layers = getattr(manifest, "main_layers", None)
    assert main_layers == ["SM", "VOD", "OMEGA"]
    # At least one product (the daily output dir)
    assert len(manifest.products) >= 1
    assert int(manifest.extra.get("days_processed", 0)) >= 1

    # Output directory should contain daily .mat files for the 10 synthetic days
    assert output_dir.exists()
    day_files = sorted(output_dir.glob("202301*.mat"))
    # Only DOY 1-10 have climatology → 10 days processed
    assert len(day_files) >= 1
    # The first day (20230101) must be present
    assert (output_dir / "20230101.mat").exists()

    # Verify each day file has SM/VOD/OMEGA 2D grids
    from scipy.io import loadmat

    data = loadmat(output_dir / "20230101.mat")
    assert "SM" in data
    assert "VOD" in data
    assert "OMEGA" in data
    assert data["SM"].shape == (24, 48)
    assert data["VOD"].shape == (24, 48)
    assert data["OMEGA"].shape == (24, 48)
    # SM should have at least some valid (finite) values in plausible range
    import numpy as np

    sm = data["SM"]
    valid = sm[np.isfinite(sm)]
    assert valid.size > 0, "Expected at least some finite SM values"
    assert np.all(valid >= 0.0)
    assert np.all(valid <= 0.60)


def test_omega_avg_daily_module_missing_datasource_raises(tmp_path: Path) -> None:
    """Missing omega_block_dir in datasource_selection raises ValueError."""
    ctx = _build_ctx(tmp_path)
    inputs = _build_inputs(tmp_path / "d2_out")
    # Remove a required key
    del inputs["datasource_selection"]["omega_block_dir"]  # type: ignore[union-attr]

    module = OmegaAvgDailyModule()
    with pytest.raises(ValueError, match="omega_block_dir"):
        module.execute(inputs=inputs, params={}, ctx=ctx)


def test_omega_avg_daily_module_missing_omega_block_mat_raises(
    tmp_path: Path,
) -> None:
    """omega_block_dir exists but has no omega_block_*.mat → FileNotFoundError."""
    ctx = _build_ctx(tmp_path)
    # Create an omega_block dir with daily_omega but no omega_block_*.mat
    fake_block_dir = tmp_path / "omega_block_empty"
    (fake_block_dir / "daily_omega").mkdir(parents=True, exist_ok=True)
    inputs = _build_inputs(tmp_path / "d2_out")
    inputs["datasource_selection"]["omega_block_dir"] = str(fake_block_dir)  # type: ignore[union-attr]

    module = OmegaAvgDailyModule()
    with pytest.raises(FileNotFoundError, match="omega_block_\\*.mat"):
        module.execute(inputs=inputs, params={}, ctx=ctx)
