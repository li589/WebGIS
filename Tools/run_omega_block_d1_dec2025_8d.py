"""Run real D1 omega_block on the Dec-2025 8-day timeseries bundle.

Writes omega_block_*.mat + daily_omega/ under Inversion_Results/omega_block,
replacing the bootstrap placeholder. Progress is appended to a sibling log.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from scipy.io import loadmat, savemat

from algorithms.omega import (
    build_omega_config,
    build_omega_field_config,
    execute_omega_retrieval,
)
from ingest.mat_bundle import load_mat_file


def main() -> None:
    root = Path(r"I:\Geograph_DataSet")
    ts_path = (
        root
        / "_runtime"
        / "python_provider"
        / "products"
        / "timeseries_bundle_d1_dec2025_8d"
        / "timeseries_bundle_20251203_20251210.mat"
    )
    out_dir = root / "Inversion_Results" / "omega_block"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "d1_8d_run.log"
    state_path = out_dir / "d1_8d_run_state.json"

    def log(msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    log(f"load timeseries {ts_path}")
    payload = load_mat_file(ts_path)
    extrema = loadmat(
        str(root / "Soil_Moisture" / "SMAP_Auxiliary_Data" / "VI_v_qa.mat"),
        squeeze_me=True,
    )
    payload["NDVI_v_max"] = np.asarray(extrema["NDVI_v_max"], dtype=np.float64)
    payload["NDVI_v_min"] = np.asarray(extrema["NDVI_v_min"], dtype=np.float64)

    cf = np.asarray(payload["CF"], dtype=np.float64).ravel()
    n_cf = int(np.count_nonzero(np.isfinite(cf) & (cf >= 0.0) & (cf <= 1.0)))
    log(f"pixels={cf.size} finite_cf={n_cf}")

    config = build_omega_config(
        {
            "mode": "dh",
            "freq_ghz": 1.4,
            "temp_scheme": "ORIG_TS",
            "exp_mode": "Exp0",
            "block_days": 8,
            "n_workers": 8,
        }
    )
    field_config = build_omega_field_config({})
    state_path.write_text(
        json.dumps(
            {
                "status": "running",
                "ts_path": str(ts_path),
                "out_dir": str(out_dir),
                "n_workers": config.n_workers,
                "finite_cf": n_cf,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    t0 = time.perf_counter()
    log("execute_omega_retrieval start")
    result = execute_omega_retrieval(
        payload, config=config, field_config=field_config
    )
    elapsed = time.perf_counter() - t0
    date_keys = [str(v) for v in result["date_keys"]]
    start_key = date_keys[0] if date_keys else "unknown"
    end_key = date_keys[-1] if date_keys else "unknown"
    omega = np.asarray(result["OMEGA_mat"], dtype=np.float64)
    sm = np.asarray(result["SM_RET_mat"], dtype=np.float64)
    vod = np.asarray(result["VOD_RET_mat"], dtype=np.float64)
    log(
        "done retrieval "
        f"elapsed_s={elapsed:.1f} "
        f"omega_finite={int(np.isfinite(omega).sum())} "
        f"sm_finite={int(np.isfinite(sm).sum())} "
        f"vod_finite={int(np.isfinite(vod).sum())}"
    )

    block_path = out_dir / f"omega_block_{start_key}_{end_key}.mat"
    block_payload = {k: v for k, v in result.items() if v is not None}
    log(f"savemat {block_path}")
    savemat(block_path, block_payload, do_compression=True)

    daily_dir = out_dir / "daily_omega"
    daily_dir.mkdir(parents=True, exist_ok=True)
    for day_index, date_key in enumerate(date_keys):
        day_path = daily_dir / f"{date_key}.mat"
        savemat(
            day_path,
            {
                "OMEGA": result["OMEGA_mat"][day_index, :],
                "SM": result["SM_RET_mat"][day_index, :],
                "VOD": result["VOD_RET_mat"][day_index, :],
                "Tau_star": result["Tau_star_mat"][day_index, :],
            },
            do_compression=True,
        )
    log(f"wrote {len(date_keys)} daily_omega mats under {daily_dir}")

    state_path.write_text(
        json.dumps(
            {
                "status": "succeeded",
                "block_path": str(block_path),
                "daily_dir": str(daily_dir),
                "elapsed_s": elapsed,
                "omega_finite": int(np.isfinite(omega).sum()),
                "sm_finite": int(np.isfinite(sm).sum()),
                "vod_finite": int(np.isfinite(vod).sum()),
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    log("SUCCEEDED")


if __name__ == "__main__":
    main()
