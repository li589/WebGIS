from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class StationRecord:
    year: int
    month: int
    day: int
    hour: int
    lat: float
    lon: float
    elev: float
    depth_upper: float
    depth_lower: float
    soil_moisture: float
    quality_flag: int = 1
    site_id: str = ""
    source: str = ""


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _split_tokens(line: str) -> list[str]:
    if "," in line:
        return [token.strip() for token in line.strip().split(",") if token.strip()]
    return line.strip().split()


def discover_ismn_stm_files(input_dir: str | Path) -> list[Path]:
    input_dir = Path(input_dir)
    files = sorted(input_dir.rglob("*sm_0.*.stm"))
    if not files:
        raise FileNotFoundError(f"No ISMN STM files found in {input_dir}")
    return files


def parse_ismn_stm_file(
    file_path: str | Path,
    default_latlon: tuple[float, float, float, float, float] | None = None,
) -> list[StationRecord]:
    """Parse an ISMN STM file into StationRecord list.

    Args:
        file_path: Path to the STM file.
        default_latlon: Fallback (lat, lon, elev, depth_upper, depth_lower) used when
            the file does not contain geographic columns. Pass this when the STM file
            only contains date / soil_moisture columns without coordinate metadata.
    """
    file_path = Path(file_path)
    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        return []

    first_tokens = _split_tokens(lines[0])

    if default_latlon is not None:
        lat, lon, elev, depth_upper, depth_lower = default_latlon
    else:
        lat = _safe_float(first_tokens[3]) if len(first_tokens) > 3 else None
        lon = _safe_float(first_tokens[4]) if len(first_tokens) > 4 else None
        elev = _safe_float(first_tokens[5]) if len(first_tokens) > 5 else None
        depth_upper = _safe_float(first_tokens[6]) if len(first_tokens) > 6 else None
        depth_lower = _safe_float(first_tokens[7]) if len(first_tokens) > 7 else None
        if None in {lat, lon, elev, depth_upper, depth_lower}:
            return []

    records: list[StationRecord] = []
    for line in lines:
        tokens = _split_tokens(line)
        if len(tokens) < 4:
            continue
        soil_moisture = _safe_float(tokens[2])
        if soil_moisture is None:
            continue
        try:
            timestamp = datetime.strptime(tokens[0], "%Y/%m/%d")
        except ValueError:
            continue
        hour = 0
        if len(tokens[1]) >= 2 and tokens[1][:2].isdigit():
            hour = int(tokens[1][:2])
        qflag = 1 if len(tokens) > 3 and tokens[3] == "G" else 0
        records.append(
            StationRecord(
                year=timestamp.year,
                month=timestamp.month,
                day=timestamp.day,
                hour=hour,
                lat=float(lat),
                lon=float(lon),
                elev=float(elev),
                depth_upper=float(depth_upper),
                depth_lower=float(depth_lower),
                soil_moisture=float(soil_moisture),
                quality_flag=qflag,
                site_id=file_path.stem,
                source="ISMN",
            )
        )
    return records


def discover_casmos_txt_files(input_dir: str | Path) -> list[Path]:
    input_dir = Path(input_dir)
    files = sorted(input_dir.glob("*.txt"))
    if not files:
        raise FileNotFoundError(f"No CASMOS txt files found in {input_dir}")
    return files


def load_casmos_site_info(csv_file: str | Path) -> dict[str, dict[str, Any]]:
    csv_file = Path(csv_file)
    with csv_file.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        result: dict[str, dict[str, Any]] = {}
        for row in reader:
            site_id = str(row["id"]).strip()
            result[site_id] = {
                "lat": _safe_float(str(row.get("lat", ""))) or 0.0,
                "lon": _safe_float(str(row.get("lon", ""))) or 0.0,
                "elv": _safe_float(str(row.get("elv", ""))) or 0.0,
            }
        return result


def parse_casmos_txt_file(
    file_path: str | Path,
    site_info: dict[str, dict[str, Any]] | None = None,
) -> list[StationRecord]:
    file_path = Path(file_path)
    site_id = file_path.stem
    info = (site_info or {}).get(site_id, {"lat": 0.0, "lon": 0.0, "elv": 0.0})
    records: list[StationRecord] = []

    with file_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        for raw_line in handle:
            tokens = _split_tokens(raw_line)
            if len(tokens) < 6:
                continue
            try:
                year = int(tokens[0])
                month = int(tokens[1])
                day = int(tokens[2])
                hour = int(tokens[3])
            except Exception:
                continue
            depth_cm = _safe_float(tokens[4])
            soil_moisture_raw = _safe_float(tokens[5])
            if depth_cm is None or soil_moisture_raw is None:
                continue
            soil_moisture = np_scale_percent_to_fraction(soil_moisture_raw)
            if soil_moisture_raw == 9999:
                soil_moisture = float("nan")
            records.append(
                StationRecord(
                    year=year,
                    month=month,
                    day=day,
                    hour=hour,
                    lat=float(info["lat"]),
                    lon=float(info["lon"]),
                    elev=float(info["elv"]),
                    depth_upper=float(depth_cm),
                    depth_lower=float(depth_cm),
                    soil_moisture=soil_moisture,
                    quality_flag=1,
                    site_id=site_id,
                    source="CASMOS",
                )
            )
    return records


def np_scale_percent_to_fraction(value: float) -> float:
    return value * 0.01
