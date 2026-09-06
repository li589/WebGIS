# Stub v1 seeds + hardening smoke (2026-08-10)

## Scope

- 5 system seeds (`stub_v1` tags) under `Code/backend/workflow_seeds/system/`
- Offline compile + module topology smoke (no live Celery/API required)
- FailureCategory mapping for RasterOps*/IO/SoftTimeLimit
- `resource_profile` from `_meta` + heavy-module bump
- Windowed `stats_spatial_mean` reduce path

## Offline results

| check | result |
|-------|--------|
| `Test/backend/test_failure_classifier_stub_ops.py` | 7 passed |
| `Test/backend/test_stub_v1_seeds_compile.py` | compile + profile resolver |
| `Test/algorithms/test_stub_modules.py` (incl. stub_v1 pipelines) | pipelines + windowed reduce |

**2026-08-10 local:** `17 passed` for the combined command below.

Re-run:

```text
Env\Python312\python.exe -m pytest Test/algorithms/test_stub_modules.py Test/backend/test_stub_v1_seeds_compile.py Test/backend/test_failure_classifier_stub_ops.py -q
```

## Live stack (optional, not CI gate)

Batch G on workflow smoke matrix: run the five `*_basic` seeds after writing
`{DATA_ROOT}/_runtime/smoke_stub.tif`, `smoke_points.geojson`, `smoke_zones.geojson`.

## Follow-ups (out of scope)

Kriging / PCA·Bayesian / PDF·DOCX / D∞ / GEE nodes.
