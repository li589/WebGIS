"""Generic raster histogram (float64, nodata-aware, overflow-safe bins).

Dataset-agnostic: operates on any numeric ndarray. Large arrays can be
processed in chunks to bound peak memory.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Pixel count above which we accumulate histogram in chunks.
_CHUNK_PIXEL_THRESHOLD = 50_000_000
_DEFAULT_CHUNK_ELEMS = 4_000_000


def _finite_mask(data: np.ndarray, nodata: float | None) -> np.ndarray:
    mask = np.isfinite(data)
    if nodata is not None and np.isfinite(nodata):
        # Exact match for integer-like nodata; also reject near-equal floats
        mask &= data != nodata
    return mask


def compute_histogram(
    data: np.ndarray,
    *,
    bins: int = 50,
    value_range: tuple[float, float] | None = None,
    nodata: float | None = None,
    density: bool = False,
) -> dict[str, Any]:
    """Compute histogram + basic stats in float64.

    Returns dict with keys:
      edges, counts, centers, density (optional), stats{mean,std,min,max,count,valid_pct}
    """
    bins = int(bins)
    if bins < 2:
        raise ValueError("bins must be >= 2")

    arr = np.asarray(data, dtype=np.float64)
    flat = arr.ravel()
    total = int(flat.size)
    if total == 0:
        edges = np.linspace(0.0, 1.0, bins + 1, dtype=np.float64)
        zeros = np.zeros(bins, dtype=np.float64)
        return {
            "edges": edges.tolist(),
            "counts": zeros.tolist(),
            "centers": ((edges[:-1] + edges[1:]) * 0.5).tolist(),
            "density": zeros.tolist() if density else None,
            "stats": {
                "mean": float("nan"),
                "std": float("nan"),
                "min": float("nan"),
                "max": float("nan"),
                "count": 0.0,
                "valid_pct": 0.0,
            },
        }

    mask = _finite_mask(flat, nodata)
    valid = flat[mask]
    count = int(valid.size)
    if count == 0:
        edges = np.linspace(0.0, 1.0, bins + 1, dtype=np.float64)
        zeros = np.zeros(bins, dtype=np.float64)
        return {
            "edges": edges.tolist(),
            "counts": zeros.tolist(),
            "centers": ((edges[:-1] + edges[1:]) * 0.5).tolist(),
            "density": zeros.tolist() if density else None,
            "stats": {
                "mean": float("nan"),
                "std": float("nan"),
                "min": float("nan"),
                "max": float("nan"),
                "count": 0.0,
                "valid_pct": 0.0,
            },
        }

    if value_range is not None:
        vmin, vmax = float(value_range[0]), float(value_range[1])
    else:
        vmin = float(np.min(valid))
        vmax = float(np.max(valid))
    if not np.isfinite(vmin) or not np.isfinite(vmax):
        raise ValueError("histogram range is not finite")
    if vmax < vmin:
        raise ValueError("histogram range max < min")
    if vmax == vmin:
        # Degenerate: expand by nextafter so a single bin captures the value
        vmax = float(np.nextafter(vmin, np.inf)) if vmin != 0 else 1.0
        vmin = float(np.nextafter(vmin, -np.inf)) if vmin == vmax else vmin

    edges = np.linspace(vmin, vmax, bins + 1, dtype=np.float64)
    # Ensure max falls into last bin: widen right edge slightly
    edges[-1] = float(np.nextafter(edges[-1], np.inf))

    if total <= _CHUNK_PIXEL_THRESHOLD:
        counts, _ = np.histogram(valid, bins=edges)
        counts = counts.astype(np.float64)
    else:
        counts = np.zeros(bins, dtype=np.float64)
        for start in range(0, valid.size, _DEFAULT_CHUNK_ELEMS):
            chunk = valid[start : start + _DEFAULT_CHUNK_ELEMS]
            c, _ = np.histogram(chunk, bins=edges)
            counts += c.astype(np.float64)

    centers = ((edges[:-1] + edges[1:]) * 0.5).astype(np.float64)
    dens: list[float] | None = None
    if density:
        widths = np.diff(edges)
        widths = np.where(widths > 0, widths, 1.0)
        dens_arr = counts / (float(count) * widths)
        dens = dens_arr.tolist()

    stats = {
        "mean": float(np.mean(valid)),
        "std": float(np.std(valid, ddof=0)),
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "count": float(count),
        "valid_pct": (count / total * 100.0) if total > 0 else 0.0,
    }

    return {
        "edges": edges.tolist(),
        "counts": counts.tolist(),
        "centers": centers.tolist(),
        "density": dens,
        "stats": stats,
    }


def histogram_to_chart_spec(
    hist: dict[str, Any],
    *,
    title: str = "Histogram",
    series_name: str = "count",
    use_density: bool = False,
) -> dict[str, Any]:
    """Map histogram dict → ChartSpec-compatible JSON (US-ASCII title)."""
    y_vals = hist["density"] if use_density and hist.get("density") else hist["counts"]
    return {
        "schema_version": "1",
        "chart_type": "histogram",
        "title": title,
        "x_label": "value",
        "y_label": "density" if use_density else "count",
        "unit": "",
        "series": [
            {
                "name": series_name,
                "x": list(hist["centers"]),
                "y": list(y_vals),
            }
        ],
        "x": list(hist["centers"]),
        "y": list(y_vals),
        "series_name": series_name,
        "bins": list(hist["edges"]),
        "categories": None,
    }
