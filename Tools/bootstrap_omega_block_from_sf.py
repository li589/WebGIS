"""Bootstrap D1-compatible omega_block dir from omega_sf_fenkuai block mats.

Maps each 8-day SF block (SM/VOD/OMEGA 2D) into daily_omega/{YYYYMMDD}.mat
plus a summary omega_block_{start}_{end}.mat with h_star_vec/alpha_star_vec
(from ancillary H.mat + constant alpha) so D2 omega_avg_daily Stage A–C can run.

This is a local-data bridge for UI acceptance when a full D1 omega_block run
has not yet been produced. It is not a science-equivalent substitute for D1.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

import h5py
import numpy as np
from scipy.io import loadmat, savemat

_BLOCK_NAME_RE = re.compile(r"^(?P<start>\d{8})_(?P<end>\d{8})\.mat$")


def _load_2d(path: Path, preferred: tuple[str, ...]) -> np.ndarray:
    try:
        payload = loadmat(str(path), squeeze_me=True, struct_as_record=False)
        for key in preferred:
            if key in payload:
                return np.asarray(payload[key], dtype=np.float64)
        raise KeyError(f"none of {preferred} in {path.name}")
    except NotImplementedError:
        with h5py.File(path, "r") as handle:
            for key in preferred:
                if key in handle:
                    return np.asarray(handle[key], dtype=np.float64)
            # nested datasets
            found: list[tuple[str, np.ndarray]] = []

            def _walk(name: str, obj: object) -> None:
                if isinstance(obj, h5py.Dataset) and Path(name).name in preferred:
                    found.append((Path(name).name, np.asarray(obj, dtype=np.float64)))

            handle.visititems(_walk)
            for key in preferred:
                for name, arr in found:
                    if name == key:
                        return arr
        raise KeyError(f"none of {preferred} in {path}")


def _align_to_grid(arr: np.ndarray, grid_shape: tuple[int, int]) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float64)
    if arr.shape == grid_shape:
        return arr
    if arr.shape == (grid_shape[1], grid_shape[0]):
        return arr.T
    raise ValueError(f"array shape {arr.shape} incompatible with grid {grid_shape}")


def _iter_dates(start: str, end: str) -> list[str]:
    cur = datetime.strptime(start, "%Y%m%d")
    last = datetime.strptime(end, "%Y%m%d")
    out: list[str] = []
    while cur <= last:
        out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


def bootstrap(
    *,
    sf_dir: Path,
    anc_root: Path,
    output_dir: Path,
    alpha_fill: float = 0.05,
) -> dict[str, object]:
    grid_shape = _load_2d(
        anc_root / "IGBP_9km_12.mat", ("IGBP_9km_12", "IGBP")
    ).shape
    h_map = _align_to_grid(_load_2d(anc_root / "H.mat", ("H", "h")), grid_shape)
    h_vec = h_map.reshape(-1)
    alpha_vec = np.full(h_vec.shape, float(alpha_fill), dtype=np.float64)

    blocks = sorted(
        p
        for p in sf_dir.glob("????????_????????.mat")
        if _BLOCK_NAME_RE.match(p.name)
    )
    if not blocks:
        raise FileNotFoundError(f"no SF block mats under {sf_dir}")

    daily_dir = output_dir / "daily_omega"
    daily_dir.mkdir(parents=True, exist_ok=True)

    date_keys: list[str] = []
    omega_days: list[np.ndarray] = []
    sm_days: list[np.ndarray] = []
    vod_days: list[np.ndarray] = []

    for block_path in blocks:
        match = _BLOCK_NAME_RE.match(block_path.name)
        assert match is not None
        start_key = match.group("start")
        end_key = match.group("end")
        omega = _align_to_grid(
            _load_2d(block_path, ("OMEGA", "omega")), grid_shape
        ).reshape(-1)
        sm = _align_to_grid(_load_2d(block_path, ("SM", "sm")), grid_shape).reshape(-1)
        vod = _align_to_grid(
            _load_2d(block_path, ("VOD", "vod")), grid_shape
        ).reshape(-1)
        for date_key in _iter_dates(start_key, end_key):
            day_path = daily_dir / f"{date_key}.mat"
            savemat(
                day_path,
                {
                    "OMEGA": omega,
                    "SM": sm,
                    "VOD": vod,
                    "Tau_star": np.full_like(omega, np.nan),
                },
                do_compression=True,
            )
            date_keys.append(date_key)
            omega_days.append(omega)
            sm_days.append(sm)
            vod_days.append(vod)

    start_all = date_keys[0]
    end_all = date_keys[-1]
    block_path = output_dir / f"omega_block_{start_all}_{end_all}.mat"
    savemat(
        block_path,
        {
            "date_keys": np.asarray(date_keys, dtype=object),
            "OMEGA_mat": np.vstack(omega_days),
            "SM_RET_mat": np.vstack(sm_days),
            "VOD_RET_mat": np.vstack(vod_days),
            "h_star_vec": h_vec,
            "alpha_star_vec": alpha_vec,
            "grid_shape": np.asarray(grid_shape, dtype=np.int32),
            "source": "bootstrap_omega_block_from_sf",
            "sf_dir": str(sf_dir),
        },
        do_compression=True,
    )
    return {
        "output_dir": str(output_dir),
        "omega_block_mat": str(block_path),
        "daily_count": len(date_keys),
        "grid_shape": grid_shape,
        "blocks": len(blocks),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sf-dir",
        type=Path,
        default=Path(
            r"I:\Geograph_DataSet\_runtime\python_provider\products"
            r"\omega_sf_fenkuai_smap_dec_parallel8k"
        ),
    )
    parser.add_argument(
        "--anc-root",
        type=Path,
        default=Path(r"I:\Geograph_DataSet\Soil_Moisture\SMAP_Auxiliary_Data"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(r"I:\Geograph_DataSet\Inversion_Results\omega_block"),
    )
    parser.add_argument("--alpha-fill", type=float, default=0.05)
    args = parser.parse_args()
    summary = bootstrap(
        sf_dir=args.sf_dir,
        anc_root=args.anc_root,
        output_dir=args.output_dir,
        alpha_fill=args.alpha_fill,
    )
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
