"""Quick inspect of .mat file variables for new landscape-metrics layer."""

from pathlib import Path
from scipy.io import loadmat

files = [
    r"I:\Geograph_DataSet\InversionResults\Landscape_Metrics_LandOnly_9KM_2020.mat",
    r"I:\Geograph_DataSet\InversionResults\Forest_Ratio_9KM_2020.mat",
    r"I:\Geograph_DataSet\InversionResults\smap_avg\doy_017.mat",
    r"I:\Geograph_DataSet\InversionResults\fy_avg\doy_025.mat",
    r"I:\Geograph_DataSet\Soil_Ecological_Data\DDCA\DDCA_DH\H\20150401.mat",
]

for fp in files:
    p = Path(fp)
    if not p.exists():
        print(f"[MISS] {fp}")
        continue
    print(f"\n=== {p.name} ===")
    try:
        m = loadmat(str(p))
        for k, v in m.items():
            if k.startswith("__"):
                continue
            shape = getattr(v, "shape", None)
            dtype = getattr(v, "dtype", None)
            print(f"  {k}: shape={shape}, dtype={dtype}")
    except Exception as e:
        print(f"  [ERR] {e}")
