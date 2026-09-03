#!/usr/bin/env python3
"""Build world administrative boundary GeoJSON for frontend basemap extract.

Data source: Natural Earth 10m cultural vectors (public domain)
  - Admin 0 countries: https://www.naturalearthdata.com/downloads/10m-cultural-vectors/
  - Admin 1 states/provinces

Outputs (under Code/frontend/public/data/boundaries/):
  - world-admin-0.geojson
  - world-admin-1.geojson
  - ATTRIBUTION.md

Intermediate shapefile trees admin_0/ and admin_1/ are gitignored; only GeoJSON
and attribution ship in the repo. Rebuild downloads NE zips into *_src/ or temp.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

import geopandas as gpd

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "Code" / "frontend" / "public" / "data" / "boundaries"

DOWNLOADS = {
    "ne_10m_admin_0_countries.zip": (
        "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip",
        "ne_10m_admin_0_countries.shp",
    ),
    "ne_10m_admin_1_states_provinces.zip": (
        "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip",
        "ne_10m_admin_1_states_provinces.shp",
    ),
}

# ~1.1 km at equator; keeps coastlines usable while shrinking payload for browser fetch.
SIMPLIFY_TOLERANCE = 0.01


def _ensure_zip(name: str, url: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / name
    if not dest.exists():
        print(f"Downloading {name} ...")
        urlretrieve(url, dest)
    return dest


def _read_shp(zip_name: str, url: str, shp_name: str) -> gpd.GeoDataFrame:
    zip_path = _ensure_zip(zip_name, url)
    extract_dir = OUT_DIR / zip_name.replace(".zip", "_src")
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    shp_path = extract_dir / shp_name
    if not shp_path.exists():
        matches = list(extract_dir.rglob("*.shp"))
        if not matches:
            raise FileNotFoundError(f"No shapefile in {zip_path}")
        shp_path = matches[0]
    return gpd.read_file(shp_path)


def _pick_name(row: dict, *keys: str) -> str:
    for key in keys:
        val = row.get(key)
        if isinstance(val, str) and val.strip() and val.strip() != "-99":
            return val.strip()
    return "未命名行政区"


def _build_admin0() -> gpd.GeoDataFrame:
    zip_name = "ne_10m_admin_0_countries.zip"
    url, shp_name = DOWNLOADS[zip_name]
    gdf = _read_shp(zip_name, url, shp_name)
    gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
    rows = []
    for _, row in gdf.iterrows():
        props = row.to_dict()
        rows.append(
            {
                "name": _pick_name(props, "NAME_EN", "NAME_ZH", "NAME", "ADMIN"),
                "name_en": _pick_name(props, "NAME_EN", "NAME"),
                "admin_level": "country",
                "iso_a2": str(props.get("ISO_A2") or ""),
                "iso_a3": str(props.get("ADM0_A3") or props.get("ISO_A3") or ""),
                "adcode": str(props.get("ISO_A3") or props.get("ADM0_A3") or ""),
                "geometry": row.geometry,
            }
        )
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)
    return out


def _build_admin1() -> gpd.GeoDataFrame:
    zip_name = "ne_10m_admin_1_states_provinces.zip"
    url, shp_name = DOWNLOADS[zip_name]
    gdf = _read_shp(zip_name, url, shp_name)
    gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
    rows = []
    for _, row in gdf.iterrows():
        props = row.to_dict()
        iso2 = str(props.get("iso_a2") or "")
        iso3166_2 = str(props.get("iso_3166_2") or "")
        rows.append(
            {
                "name": _pick_name(props, "name_en", "name"),
                "name_en": _pick_name(props, "name_en", "name"),
                "admin_level": "state",
                "iso_a2": iso2,
                "iso_a3": str(props.get("adm0_a3") or ""),
                "adcode": iso3166_2 or iso2,
                "geometry": row.geometry,
            }
        )
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)
    return out


def _write_geojson(gdf: gpd.GeoDataFrame, filename: str) -> None:
    path = OUT_DIR / filename
    gdf.to_file(path, driver="GeoJSON")
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"Wrote {path} ({len(gdf)} features, {size_mb:.2f} MB)")


def _write_attribution() -> None:
    text = """# World administrative boundaries (built-in)

- **Source**: [Natural Earth](https://www.naturalearthdata.com/) 10m cultural vectors
  - Admin 0 – Countries (`ne_10m_admin_0_countries`)
  - Admin 1 – States, Provinces (`ne_10m_admin_1_states_provinces`)
- **License**: Public domain (see Natural Earth terms of use)
- **Rebuild**: `Env/Python312/python.exe Tools/build_world_admin_boundaries.py`
- **Usage**: Frontend basemap feature extract + admin boundary map overlay (lazy fetch)
"""
    (OUT_DIR / "ATTRIBUTION.md").write_text(text, encoding="utf-8")


def main() -> None:
    print("Building world admin-0 ...")
    admin0 = _build_admin0()
    _write_geojson(admin0, "world-admin-0.geojson")

    print("Building world admin-1 ...")
    admin1 = _build_admin1()
    _write_geojson(admin1, "world-admin-1.geojson")

    _write_attribution()

    # Drop extracted shapefile scratch dirs to keep tree small.
    for child in OUT_DIR.iterdir():
        if child.is_dir() and child.name.endswith("_src"):
            shutil.rmtree(child)

    print("Done.")


if __name__ == "__main__":
    main()
