"""Submit SMAP Dec strip run (bbox + max_pixels) and poll until done."""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = r"I:/Geograph_DataSet/Soil_Moisture"
OUT = Path(__file__).resolve().parents[1] / "Code" / "backend" / ".data" / "omega_sf_q4_smoke"


def main() -> None:
    t0 = time.time()
    payload = {
        "command_type": "analysis",
        "command_label": "SF SMAP Dec strip timing+UI",
        "layer_id": "method-smap-omega-doy-dynamic",
        "priority": "high",
        "resource_profile": "heavy",
        "time_range": {
            "start_at": "2025-12-01T00:00:00Z",
            "end_at": "2025-12-31T00:00:00Z",
        },
        "algorithm_request": {
            "module_name": "omega_sf_fenkuai",
            "task_type": "omega_sf_fenkuai",
            "datasource_selection": {
                "smap_folder": ROOT + "/SMAP_Origin_Data",
                "anc_root": ROOT + "/SMAP_Auxiliary_Data",
                "ndvi_clim_folder": r"I:/Geograph_DataSet/Ecological_Vegetation/NDVI/climatology",
            },
            "algorithm_params": {
                "tb_source": "SMAP",
                "sm_source": "SMAP",
                "temp_scheme": "ORIG_TS",
                "sf_mode": "INVERTED_DAILY",
                "ndvi_mode": "DOY_CLIM",
                "omega_fixed_mode": "PIXEL",
                "start_date": "20251201",
                "end_date": "20251231",
                "bbox_west": 15.0,
                "bbox_south": -35.0,
                "bbox_east": 35.0,
                "bbox_north": -10.0,
                "max_pixels": 8000,
                "block_days": 8,
                "freq_ghz": 1.4,
            },
        },
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8000/workflow-runs",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        rid = json.load(resp)["run_id"]
    print(f"SMAP_STRIP {rid} submitted_at {time.time() - t0:.1f}s", flush=True)

    last = None
    for i in range(360):
        with urllib.request.urlopen(
            f"http://127.0.0.1:8000/workflow-runs/{rid}", timeout=30
        ) as resp:
            data = json.load(resp)
        with urllib.request.urlopen(
            f"http://127.0.0.1:8000/workflow-runs/{rid}/events", timeout=30
        ) as resp:
            items = json.load(resp).get("items") or []
        details = []
        for event in items:
            node = (event.get("payload") or {}).get("node_progress") or {}
            if node.get("detail"):
                details.append(node)
        status = data.get("status")
        msg = (data.get("message") or "")[:80]
        det = details[-1] if details else None
        line = f"{i} {status} {data.get('progress')} {msg} details={len(details)}"
        if det:
            line += f" | {det.get('message')} {det.get('detail')}"
        if line != last:
            print(line, flush=True)
            last = line
        if status in ("succeeded", "failed", "cancelled"):
            elapsed = time.time() - t0
            print(
                f"FINAL {status} wall_s={elapsed:.1f} refs={len(data.get('result_refs') or [])}",
                flush=True,
            )
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / "strip_run.json").write_text(
                json.dumps(
                    {
                        "run_id": rid,
                        "status": status,
                        "wall_s": elapsed,
                        "message": msg,
                        "detail_events": len(details),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise SystemExit(0 if status == "succeeded" else 1)
        time.sleep(5)
    raise SystemExit("timeout")


if __name__ == "__main__":
    main()
