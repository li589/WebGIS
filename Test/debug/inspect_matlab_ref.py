# -*- coding: utf-8 -*-
"""Inspect MATLAB reference .mat structure for FY/SMAP omega results."""
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np

CUSTOM_RES = Path(r"I:\Geograph_DataSet\Soil_Moisture\Omega_Custom_Res")


def load_any_mat(path):
    """Load .mat with scipy first, fall back to h5py for v7.3."""
    try:
        from scipy.io import loadmat
        return ("scipy", loadmat(str(path)))
    except NotImplementedError:
        import h5py
        return ("h5py", h5py.File(str(path), "r"))


def describe(path, max_keys=20):
    print(f"\n{'='*66}")
    print(f"FILE: {path.name}  ({path.stat().st_size/1024**2:.2f} MB)")
    print("="*66)
    loader, data = load_any_mat(path)
    print(f"[loader={loader}]")
    if loader == "scipy":
        keys = [k for k in data.keys() if not k.startswith("__")]
        for k in keys[:max_keys]:
            v = data[k]
            arr = np.asarray(v)
            info = f"  {k}: shape={arr.shape}, dtype={arr.dtype}"
            if arr.size and np.issubdtype(arr.dtype, np.number):
                finite = arr[np.isfinite(arr)] if arr.dtype.kind == "f" else arr
                if finite.size:
                    info += f", min={np.nanmin(finite):.4g}, max={np.nanmax(finite):.4g}, mean={np.nanmean(finite):.4g}, nan%={100*np.mean(~np.isfinite(arr)):.1f}"
            print(info)
    else:  # h5py
        def walk(g, prefix=""):
            for k in g.keys():
                item = g[k]
                if hasattr(item, "shape"):
                    print(f"  {prefix}{k}: shape={item.shape}, dtype={item.dtype}")
                else:
                    print(f"  {prefix}{k}/ (group)")
                    walk(item, prefix + k + "/")
        walk(data)
        data.close()


# Inspect one FY omega and one SMAP omega file (weekly aggregated)
targets = [
    CUSTOM_RES / "fy_raw_ω" / "20251203_20251210_exp0_global_ismn_all_shard01of01_roundrobin.mat",
    CUSTOM_RES / "smap_raw_omega" / "20251203_20251210_exp0_global_ismn_all_shard01of01_roundrobin.mat",
    # Also a daily smvod file (Stage output)
    CUSTOM_RES / "smap_raw_smvod" / "20251203.mat",
    CUSTOM_RES / "fy_raw_smvod" / "20251203.mat",
]

for t in targets:
    if t.exists():
        try:
            describe(t)
        except Exception as e:
            print(f"\n[ERROR] {t.name}: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"\n[MISSING] {t}")
