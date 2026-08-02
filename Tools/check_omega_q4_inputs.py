"""Quick inventory / variable check for omega_sf Q4 inputs."""

from __future__ import annotations

import json
from pathlib import Path

REQUIRED_SMAP = ("sm_dca", "vwc", "Ts")
REQUIRED_FY = ("TBv", "TBh", "IA")
SHAPE = (1624, 3856)


def _check_mat(path: Path, required: tuple[str, ...]) -> dict:
    from ingest.mat_bundle import load_mat_file

    data = load_mat_file(str(path))
    keys = set(data.keys())
    missing = [k for k in required if k not in keys and f"{k}_mat" not in keys]
    shape_ok = None
    for cand in required:
        for key in (cand, f"{cand}_mat"):
            if key in data:
                arr = __import__("numpy").asarray(data[key])
                shape_ok = arr.shape == SHAPE or arr.size == SHAPE[0] * SHAPE[1]
                break
        if shape_ok is not None:
            break
    return {
        "file": path.name,
        "missing": missing,
        "shape_ok": shape_ok,
        "keys": sorted(k for k in keys if not k.startswith("__")),
    }


def main() -> None:
    root = Path(r"I:\Geograph_DataSet\Soil_Moisture")
    report: dict = {"smap": [], "fy3d": [], "ancillary": {}}
    for folder, req, bucket in (
        (root / "SMAP_Origin_Data", REQUIRED_SMAP, "smap"),
        (root / "FY3D", REQUIRED_FY, "fy3d"),
    ):
        files = sorted(folder.glob("202512*.mat"))[:3] + sorted(folder.glob("202511*.mat"))[:2]
        for f in files:
            try:
                report[bucket].append(_check_mat(f, req))
            except Exception as exc:  # noqa: BLE001
                report[bucket].append({"file": f.name, "error": str(exc)})

    anc = root / "SMAP_Auxiliary_Data"
    report["ancillary"] = {
        "VI_v_qa": (anc / "VI_v_qa.mat").exists(),
        "IGBP_9km_12": (anc / "IGBP_9km_12.mat").exists(),
        "path_alias_targets": {
            "FY3D": (root / "FY3D").exists(),
            "FY3B": (root / "FY3B").exists(),
            "SMAP_Auxiliary_Data": anc.exists(),
        },
    }
    out = Path(__file__).with_name("omega_q4_data_check_report.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
