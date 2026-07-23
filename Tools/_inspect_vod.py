#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Inspect VOD/SM and Smap_OriginData .mat file structures."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from scipy.io import loadmat


def inspect_v5(path: Path) -> None:
    print(f"=== {path.name} (scipy loadmat) ===")
    try:
        m = loadmat(str(path))
    except Exception as e:
        print(f"  loadmat failed: {e}")
        return
    for k, v in m.items():
        if k.startswith("__"):
            print(f"  {k}: {v}")
            continue
        shape = getattr(v, "shape", None)
        dtype = getattr(v, "dtype", None)
        if hasattr(v, "shape") and v.ndim >= 1:
            try:
                rng = f"[{np.nanmin(v):.4f}, {np.nanmax(v):.4f}]"
            except Exception:
                rng = "?"
            print(f"  {k}: shape={shape}, dtype={dtype}, range={rng}")
        else:
            print(f"  {k}: {type(v).__name__} = {v}")


def inspect_v73(path: Path) -> None:
    print(f"=== {path.name} (h5py v7.3) ===")
    import h5py

    with h5py.File(str(path), "r") as f:
        for k in list(f.keys()):
            arr = f[k]
            try:
                data = arr[:]
                if data.ndim == 2:
                    data = data.T
                rng = f"[{np.nanmin(data):.4f}, {np.nanmax(data):.4f}]"
            except Exception:
                rng = "?"
            print(f"  {k}: shape={arr.shape}, dtype={arr.dtype}, range={rng}")


if __name__ == "__main__":
    vod_path = Path(
        r"I:\Geograph_DataSet\Soil_Ecological_Data\SmapSoil_VOD_SM\20251201.mat"
    )
    inspect_v5(vod_path)

    print()
    origin_path = Path(
        r"I:\Geograph_DataSet\Soil_Ecological_Data\Smap_OriginData\20251201.mat"
    )
    try:
        inspect_v5(origin_path)
    except Exception as e:
        print(f"  v5 failed: {e}")
        inspect_v73(origin_path)

    print()
    nc_path = Path(
        r"I:\Geograph_DataSet\Soil_Ecological_Data\CustomNC_SM_CalData\Processed_SM_20251201.nc"
    )
    if nc_path.exists():
        print(f"=== {nc_path.name} (NetCDF) ===")
        from netCDF4 import Dataset

        with Dataset(nc_path) as ds:
            for name, var in ds.variables.items():
                print(
                    f"  {name}: dims={var.dimensions}, shape={var.shape}, dtype={var.dtype}"
                )
            attrs = {a: getattr(ds, a) for a in ds.ncattrs()}
            print(f"  Global attrs: {attrs}")
