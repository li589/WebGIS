#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit overlay registry assets: source data vs exported PNG/bounds.

Reads ``Code/backend/app/services/overlay_registry.py`` registrations and checks
each configured source path and PNG/bounds path under ``I:\\Geograph_DataSet`` (and
any other absolute paths in the registry).

Writes ``Tools/reports/overlay_audit_report.md`` with exists/missing status.

When run with ``--regenerate-missing``, invokes ``Tools/export_overlay_assets.py``
export functions only for layers whose PNG is missing but source data exists.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _REPO_ROOT / "Code" / "backend"
_REPORT_PATH = _REPO_ROOT / "Tools" / "reports" / "overlay_audit_report.md"
_DATA_ROOT = Path(r"I:\Geograph_DataSet")

if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


@dataclass
class AssetCheck:
    layer_id: str
    category: str
    overlay_dir: Path
    kind: str  # static | time-series
    source_paths: list[tuple[str | None, Path | None, bool]] = field(
        default_factory=list
    )
    """(time_label, resolved_path, exists)"""
    png_paths: list[tuple[str | None, Path, bool]] = field(default_factory=list)
    bounds_paths: list[tuple[str | None, Path, bool]] = field(default_factory=list)

    @property
    def source_exists_count(self) -> int:
        return sum(1 for _, _, ok in self.source_paths if ok)

    @property
    def source_total(self) -> int:
        return len(self.source_paths)

    @property
    def png_exists_count(self) -> int:
        return sum(1 for _, _, ok in self.png_paths if ok)

    @property
    def png_total(self) -> int:
        return len(self.png_paths)

    @property
    def any_source(self) -> bool:
        return self.source_total == 0 or self.source_exists_count > 0

    @property
    def all_sources_exist(self) -> bool:
        return self.source_total == 0 or self.source_exists_count == self.source_total

    @property
    def any_png_missing(self) -> bool:
        return self.png_total > 0 and self.png_exists_count < self.png_total

    @property
    def can_regenerate(self) -> bool:
        return self.any_png_missing and self.any_source and self.layer_id in _EXPORT_MAP


def _status(ok: bool) -> str:
    return "exists" if ok else "missing"


def _rel_or_abs(path: Path | None) -> str:
    if path is None:
        return "(not configured)"
    try:
        return str(path.relative_to(_DATA_ROOT))
    except ValueError:
        return str(path)


def audit_overlay(spec) -> AssetCheck:
    check = AssetCheck(
        layer_id=spec.layer_id,
        category=spec.category,
        overlay_dir=spec.overlay_dir,
        kind=spec.category,
    )

    if spec.category == "time-series":
        times = spec.time_list or [None]
        for t in times:
            src = spec.resolve_source_path(t)
            src_ok = src is not None and src.exists()
            check.source_paths.append((t, src, src_ok))

            png = spec.resolve_png(t)
            check.png_paths.append((t, png, png.exists()))

            bounds = spec.resolve_bounds(t)
            check.bounds_paths.append((t, bounds, bounds.exists()))
    else:
        src = spec.source_path
        src_ok = src is not None and src.exists()
        check.source_paths.append((None, src, src_ok))

        png = spec.resolve_png(None)
        check.png_paths.append((None, png, png.exists()))

        bounds = spec.resolve_bounds(None)
        check.bounds_paths.append((None, bounds, bounds.exists()))

    return check


def _format_check_table(check: AssetCheck) -> list[str]:
    lines: list[str] = []
    lines.append(f"### `{check.layer_id}` ({check.category})")
    lines.append("")
    lines.append(f"- **overlay_dir:** `{check.overlay_dir}`")
    if check.source_total:
        lines.append(
            f"- **source:** {check.source_exists_count}/{check.source_total} {_status(check.all_sources_exist)}"
        )
    else:
        lines.append("- **source:** not configured")

    if check.png_total:
        lines.append(
            f"- **PNG:** {check.png_exists_count}/{check.png_total} "
            f"({'complete' if check.png_exists_count == check.png_total else 'incomplete'})"
        )
    else:
        lines.append("- **PNG:** not configured")

    lines.append("")
    lines.append("| kind | time | path | status |")
    lines.append("|------|------|------|--------|")

    for t, path, ok in check.source_paths:
        label = t or "—"
        display = _rel_or_abs(path)
        lines.append(f"| source | {label} | `{display}` | {_status(ok)} |")

    for t, path, ok in check.png_paths:
        label = t or "—"
        display = _rel_or_abs(path)
        lines.append(f"| png | {label} | `{display}` | {_status(ok)} |")

    for t, path, ok in check.bounds_paths:
        label = t or "—"
        display = _rel_or_abs(path)
        lines.append(f"| bounds | {label} | `{display}` | {_status(ok)} |")

    lines.append("")
    return lines


# layer_id -> export_overlay_assets function (lab-output has no exporter)
_EXPORT_MAP: dict[str, str] = {
    "dem-etopo": "export_dem_etopo",
    "landcover-cn": "export_thematic_layers",
    "hfp-cn": "export_thematic_layers",
    "aridity-cn": "export_thematic_layers",
    "omega-output": "export_omega_ts",
    "smap-sm-ts": "export_smap_ts",
    "gpcp-precip-ts": "export_gpcp_ts",
    "gebco-dem-cn": "export_gebco_dem",
    "cmfd-precip-cn": "export_cmfd_precip",
    "clcd-cn": "export_clcd",
    "biomass-cn": "export_biomass",
    "era5-dwaa-cn": "export_era5_dwaa",
    "era5-wdaa-cn": "export_era5_wdaa",
    "co2-cn": "export_co2",
    "soil-ddca": "export_soil_ddca_ts",
    "omega-fy-output": "export_omega_fy_ts",
    "landscape-metrics-9km": "export_landscape_metrics",
    "forest-ratio": "export_forest_ratio",
    "vod-dec2025": "export_vod_ts",
    "sm-dec2025": "export_sm_dec2025_ts",
    "omega-dec2025": "export_omega_2025_ts",
}


def write_report(checks: list[AssetCheck], regenerate_log: list[str] | None = None) -> None:
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    total = len(checks)
    src_ok = sum(1 for c in checks if c.all_sources_exist or c.source_total == 0)
    png_ok = sum(1 for c in checks if c.png_total and c.png_exists_count == c.png_total)
    png_partial = sum(
        1
        for c in checks
        if c.png_total and 0 < c.png_exists_count < c.png_total
    )
    png_missing = sum(1 for c in checks if c.png_total and c.png_exists_count == 0)

    lines: list[str] = [
        "# Overlay Asset Audit Report",
        "",
        f"Generated: {now}",
        "",
        f"Data root: `{_DATA_ROOT}`",
        "",
        "## Summary",
        "",
        f"| metric | count |",
        f"|--------|------:|",
        f"| registered overlays | {total} |",
        f"| sources fully present | {src_ok} |",
        f"| PNG complete | {png_ok} |",
        f"| PNG partial | {png_partial} |",
        f"| PNG all missing | {png_missing} |",
        "",
    ]

    if regenerate_log:
        lines.extend(["## Regeneration", ""])
        lines.extend(regenerate_log)
        lines.append("")

    lines.extend(["## Per-layer detail", ""])
    for check in checks:
        lines.extend(_format_check_table(check))

    _REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {_REPORT_PATH}")


def regenerate_missing(checks: list[AssetCheck]) -> list[str]:
    """Run export_overlay_assets functions for layers with missing PNG + existing source."""
    tools_dir = _REPO_ROOT / "Tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    import export_overlay_assets as exporter  # noqa: WPS433

    to_run: dict[str, AssetCheck] = {}
    for check in checks:
        if check.can_regenerate:
            fn_name = _EXPORT_MAP[check.layer_id]
            to_run.setdefault(fn_name, check)

    log: list[str] = []
    if not to_run:
        log.append("No layers eligible for regeneration (missing PNG + source exists + exporter available).")
        return log

    # De-duplicate by function name (thematic layers share one exporter)
    seen_fns: set[str] = set()
    for fn_name in sorted(to_run.keys()):
        if fn_name in seen_fns:
            continue
        seen_fns.add(fn_name)
        affected = [c.layer_id for c in checks if c.can_regenerate and _EXPORT_MAP[c.layer_id] == fn_name]
        log.append(f"- Running `{fn_name}()` for: {', '.join(affected)}")
        print(f"\n[REGEN] {fn_name}() -> {', '.join(affected)}")
        try:
            getattr(exporter, fn_name)()
            log.append(f"  - status: OK")
        except Exception as exc:
            log.append(f"  - status: FAIL ({exc})")
            print(f"  [FAIL] {fn_name}: {exc}")

    skipped = [
        c.layer_id
        for c in checks
        if c.any_png_missing and not c.can_regenerate
    ]
    if skipped:
        log.append("")
        log.append("Skipped (no exporter or no source):")
        for lid in skipped:
            c = next(x for x in checks if x.layer_id == lid)
            reason = []
            if not c.any_source:
                reason.append("source missing")
            if lid not in _EXPORT_MAP:
                reason.append("no export function")
            log.append(f"- `{lid}`: {', '.join(reason) or 'unknown'}")

    return log


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit overlay registry assets.")
    parser.add_argument(
        "--regenerate-missing",
        action="store_true",
        help="Regenerate PNGs via export_overlay_assets when source exists but PNG missing.",
    )
    args = parser.parse_args()

    from app.services import overlay_registry  # noqa: WPS433

    checks: list[AssetCheck] = []
    for layer_id in sorted(overlay_registry.list_overlay_ids()):
        spec = overlay_registry.get_overlay_spec(layer_id)
        if spec is None:
            continue
        checks.append(audit_overlay(spec))

    regenerate_log: list[str] | None = None
    if args.regenerate_missing:
        regenerate_log = regenerate_missing(checks)
        # Re-audit after regeneration
        checks = []
        for layer_id in sorted(overlay_registry.list_overlay_ids()):
            spec = overlay_registry.get_overlay_spec(layer_id)
            if spec is None:
                continue
            checks.append(audit_overlay(spec))

    write_report(checks, regenerate_log)

    # Console summary
    print("\n=== Audit Summary ===")
    for c in checks:
        src = f"{c.source_exists_count}/{c.source_total}" if c.source_total else "n/a"
        png = f"{c.png_exists_count}/{c.png_total}" if c.png_total else "n/a"
        print(f"  {c.layer_id:24s}  source={src:>7s}  png={png}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
