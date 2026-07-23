"""Inspect EASE-Grid .mat files to understand actual data layout."""

import sys
import numpy as np
from pathlib import Path

# Add the tools dir to import the read function
sys.path.insert(0, str(Path(__file__).parent))
from export_overlay_assets import _read_mat_auto, _ease_grid_9k_transform

files = {
    "forest_ratio": r"I:\Geograph_DataSet\InversionResults\Forest_Ratio_9KM_2020.mat",
    "omega_fy": r"I:\Geograph_DataSet\InversionResults\fy_avg\doy_025.mat",
    "soil_ddca": r"I:\Geograph_DataSet\Soil_Ecological_Data\DDCA\DDCA_DH\H\20150401.mat",
}

for name, path in files.items():
    print(f"\n{'='*60}")
    print(f"=== {name}: {path}")
    print("=" * 60)
    p = Path(path)
    if not p.exists():
        print("  [SKIP] File not found")
        continue
    m = _read_mat_auto(p)
    print(f"  Keys: {list(m.keys())}")
    for k, v in m.items():
        if isinstance(v, np.ndarray):
            if v.dtype.kind in ("U", "S"):
                # String array (CRS)
                print(
                    f"    {k}: shape={v.shape}, dtype={v.dtype}, value={str(v.ravel()[0]) if v.size > 0 else 'empty'}"
                )
            elif v.size <= 16:
                # Small numeric array (Transform, Resolution)
                print(
                    f"    {k}: shape={v.shape}, dtype={v.dtype}, value={v.ravel().tolist()}"
                )
            else:
                print(
                    f"    {k}: shape={v.shape}, dtype={v.dtype}, range=[{np.nanmin(v):.4f}, {np.nanmax(v):.4f}]"
                )

# Also check the global EASE-Grid 9km dimensions
print(f"\n{'='*60}")
print("=== EASE-Grid 2.0 9km reference")
print("=" * 60)
transform = _ease_grid_9k_transform()
print(f"  Transform: {transform}")
print(f"  UL corner (0,0): {transform * (0, 0)}")
print("  Global grid: 1692 rows x 3600 cols")
print(f"  Global width: {3600 * 9000.879 / 1000:.1f} km")
print(f"  Global height: {1692 * 9000.879 / 1000:.1f} km")
print("  Data shape (1624, 3856):")
print(
    f"    width: {3856 * 9000.879 / 1000:.1f} km ({3856 * 9000.879 / 40075000 * 360:.1f} deg at equator)"
)
print(f"    height: {1624 * 9000.879 / 1000:.1f} km")
