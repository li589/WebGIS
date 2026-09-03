# World administrative boundaries (built-in)

- **Source**: [Natural Earth](https://www.naturalearthdata.com/) 10m cultural vectors
  - Admin 0 – Countries (`ne_10m_admin_0_countries`)
  - Admin 1 – States, Provinces (`ne_10m_admin_1_states_provinces`)
- **License**: Public domain (see Natural Earth terms of use)
- **Rebuild**: `Env/Python312/python.exe Tools/build_world_admin_boundaries.py`
- **Source shapefiles**: `admin_0/` and `admin_1/` under this directory are build artifacts (gitignored). Download Natural Earth zips into `admin_0_src/` / `admin_1_src/` or follow `Tools/build_world_admin_boundaries.py` before rebuilding GeoJSON.
- **Usage**: Frontend basemap feature extract + admin boundary map overlay (lazy fetch)
- **Granularity**: Admin-1 = states/provinces (~4.6k features); Admin-0 = countries fallback
