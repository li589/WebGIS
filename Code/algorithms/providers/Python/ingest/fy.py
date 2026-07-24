from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


FY_DATE_PATTERN = re.compile(r"(\d{8})")


@dataclass(frozen=True, slots=True)
class FyOrbitFile:
    file_name: str
    file_path: Path
    date_key: str
    orbit_type: str
    satellite: str


@dataclass(frozen=True, slots=True)
class FyDailyGroup:
    date_key: str
    descending_files: tuple[FyOrbitFile, ...] = ()
    ascending_files: tuple[FyOrbitFile, ...] = ()


@dataclass(frozen=True, slots=True)
class FyDailyJobPlan:
    date_key: str
    orbit_type: str
    input_files: tuple[str, ...]
    output_dir: str
    work_dir: str
    output_prefix: str
    satellite: str
    metadata: dict[str, str] = field(default_factory=dict)


def extract_fy_date_key(file_name: str) -> str:
    match = FY_DATE_PATTERN.search(file_name)
    if match is None:
        raise ValueError(f"Cannot parse date from FY file name: {file_name}")
    return match.group(1)


def detect_fy_orbit_type(file_name: str) -> str:
    if "MWRID" in file_name:
        return "MWRID"
    if "MWRIA" in file_name:
        return "MWRIA"
    raise ValueError(f"Cannot detect FY orbit type from file name: {file_name}")


def detect_fy_satellite(file_name: str) -> str:
    upper_name = file_name.upper()
    if "FY3B" in upper_name:
        return "FY3B"
    if "FY3D" in upper_name:
        return "FY3D"
    return "FY3"


def build_date_keys(start_time: datetime, end_time: datetime) -> list[str]:
    keys: list[str] = []
    current = start_time
    while current <= end_time:
        keys.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return keys


def discover_fy_orbit_files(
    input_dir: str | Path, pattern: str = "*.HDF"
) -> list[FyOrbitFile]:
    input_dir = Path(input_dir)
    files: list[FyOrbitFile] = []
    for file_path in sorted(input_dir.glob(pattern)):
        file_name = file_path.name
        try:
            files.append(
                FyOrbitFile(
                    file_name=file_name,
                    file_path=file_path,
                    date_key=extract_fy_date_key(file_name),
                    orbit_type=detect_fy_orbit_type(file_name),
                    satellite=detect_fy_satellite(file_name),
                )
            )
        except ValueError:
            continue
    if not files:
        raise FileNotFoundError(f"No FY HDF files found in {input_dir}")
    return files


def group_fy_files_by_day(input_files: list[FyOrbitFile]) -> dict[str, FyDailyGroup]:
    grouped: dict[str, dict[str, list[FyOrbitFile]]] = {}
    for item in input_files:
        grouped.setdefault(item.date_key, {"MWRID": [], "MWRIA": []})
        grouped[item.date_key][item.orbit_type].append(item)

    result: dict[str, FyDailyGroup] = {}
    for date_key, orbit_map in grouped.items():
        result[date_key] = FyDailyGroup(
            date_key=date_key,
            descending_files=tuple(orbit_map["MWRID"]),
            ascending_files=tuple(orbit_map["MWRIA"]),
        )
    return result


def build_fy_daily_job_plans(
    input_dir: str | Path,
    output_root: str | Path,
    start_time: datetime,
    end_time: datetime,
    orbit_mode: str,
) -> list[FyDailyJobPlan]:
    input_files = discover_fy_orbit_files(input_dir)
    grouped = group_fy_files_by_day(input_files)
    date_keys = build_date_keys(start_time, end_time)
    output_root = Path(output_root)

    plans: list[FyDailyJobPlan] = []
    for date_key in date_keys:
        group = grouped.get(date_key)
        if group is None:
            continue

        orbit_items: list[tuple[str, tuple[FyOrbitFile, ...]]] = []
        if orbit_mode in {"MWRID", "Both"} and group.descending_files:
            orbit_items.append(("MWRID", group.descending_files))
        if orbit_mode in {"MWRIA", "Both"} and group.ascending_files:
            orbit_items.append(("MWRIA", group.ascending_files))

        for orbit_type, files in orbit_items:
            satellite = files[0].satellite
            target_output_dir = (
                output_root / orbit_type if orbit_mode == "Both" else output_root
            )
            work_dir = target_output_dir / "_work" / date_key
            output_prefix = f"{satellite}_GBAL_L1_10V10H_{date_key}_{orbit_type}"
            plans.append(
                FyDailyJobPlan(
                    date_key=date_key,
                    orbit_type=orbit_type,
                    input_files=tuple(str(item.file_path) for item in files),
                    output_dir=str(target_output_dir),
                    work_dir=str(work_dir),
                    output_prefix=output_prefix,
                    satellite=satellite,
                    metadata={
                        "input_dir": str(Path(input_dir)),
                        "file_count": str(len(files)),
                    },
                )
            )
    return plans


def write_fy_daily_plan_json(
    plans: list[FyDailyJobPlan], output_path: str | Path
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(plan) for plan in plans]
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output_path
