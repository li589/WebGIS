"""CLI: sample-pixel OMEGA parity vs Matlab Omega_Custom_Res block mats."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _load_omega_grid(path: Path) -> np.ndarray:
    from ingest.mat_bundle import load_mat_file

    data = load_mat_file(str(path))
    for key in ("OMEGA_grid", "OMEGA", "omega_grid", "omega"):
        if key in data:
            return np.asarray(data[key], dtype=np.float64)
    raise KeyError(f"No OMEGA grid in {path}: keys={list(data)[:20]}")


def compare(ref: Path, pred: Path, sample: int = 200, seed: int = 0) -> dict:
    a = _load_omega_grid(ref)
    b = _load_omega_grid(pred)
    if a.shape != b.shape:
        # try transpose
        if a.T.shape == b.shape:
            a = a.T
        elif b.T.shape == a.shape:
            b = b.T
        else:
            return {"ok": False, "error": f"shape mismatch {a.shape} vs {b.shape}"}
    mask = np.isfinite(a) & np.isfinite(b)
    n = int(mask.sum())
    if n == 0:
        return {"ok": False, "error": "no overlapping finite pixels", "finite_ref": int(np.isfinite(a).sum()), "finite_pred": int(np.isfinite(b).sum())}
    idx = np.flatnonzero(mask.ravel())
    rng = np.random.default_rng(seed)
    take = idx if n <= sample else rng.choice(idx, size=sample, replace=False)
    ra = a.ravel()[take]
    rb = b.ravel()[take]
    abs_err = np.abs(ra - rb)
    return {
        "ok": True,
        "n_overlap": n,
        "sample": int(take.size),
        "mae": float(np.mean(abs_err)),
        "median_abs": float(np.median(abs_err)),
        "p95_abs": float(np.percentile(abs_err, 95)),
        "mask_iou": float(n / max(int(np.isfinite(a).sum() | np.isfinite(b).sum()), 1)),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ref", required=True)
    p.add_argument("--pred", required=True)
    p.add_argument("--sample", type=int, default=200)
    args = p.parse_args()
    report = compare(Path(args.ref), Path(args.pred), sample=args.sample)
    print(report)
    raise SystemExit(0 if report.get("ok") else 1)


if __name__ == "__main__":
    main()
