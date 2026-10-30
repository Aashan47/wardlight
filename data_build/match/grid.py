"""Distance from each facility to the nearest Gridfinder line, and the Gridfinder 'targets' flag.

Gridfinder v1.1.1 (Arderne et al., Zenodo 3628142, CC BY 4.0). Method in docs/sources/match.md:
- lines read from grid.gpkg with pyogrio's bbox filter, Nigeria plus a 1 degree margin, so lines across
  the border count as the nearest line where they are nearer;
- nearest line found with a shapely STRtree in an equirectangular plane, then the distance recomputed for
  every line within 1.1 times that distance in a plane scaled at the facility's own latitude, so the error
  from the projection is below 0.1 percent over a few tens of km;
- targets.tif (15 arc-second cells, 1 = predicted to be electrified) read once for the same window and
  indexed at the facility's cell.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio.raw
import shapely

from . import paths

NGA_BBOX = (2.6, 4.2, 14.7, 13.95)  # lon_min, lat_min, lon_max, lat_max of Nigeria, rounded outward
MARGIN_DEG = 1.0
KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON_EQ = 111.320
REF_LAT = 9.0


def _bbox(margin: float = MARGIN_DEG) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = NGA_BBOX
    return (x0 - margin, y0 - margin, x1 + margin, y1 + margin)


def read_lines(gpkg: Path = paths.GRIDFINDER_GPKG) -> np.ndarray:
    _meta, _fids, geom, _fields = pyogrio.raw.read(str(gpkg), bbox=_bbox(), columns=[])
    return shapely.from_wkb(geom)


def _scale(geoms, lat_deg: float):
    kx = KM_PER_DEG_LON_EQ * math.cos(math.radians(lat_deg))
    return shapely.transform(geoms, lambda c: c * np.array([kx, KM_PER_DEG_LAT]))


def nearest_km(lons: np.ndarray, lats: np.ndarray, lines: np.ndarray) -> np.ndarray:
    """Distance in km from each point to the nearest line. NaN where the point has no coordinates."""
    out = np.full(len(lons), np.nan)
    ok = np.isfinite(lons) & np.isfinite(lats)
    if not ok.any():
        return out
    plane = _scale(lines, REF_LAT)
    tree = shapely.STRtree(plane)
    kx0 = KM_PER_DEG_LON_EQ * math.cos(math.radians(REF_LAT))
    pts = shapely.points(lons[ok] * kx0, lats[ok] * KM_PER_DEG_LAT)
    idx, d0 = tree.query_nearest(pts, return_distance=True, all_matches=False)
    # idx is (2, n): row 0 point index, row 1 tree index
    approx = np.full(ok.sum(), np.nan)
    approx[idx[0]] = d0
    exact = np.empty(ok.sum())
    lon_ok, lat_ok = lons[ok], lats[ok]
    for i in range(len(exact)):
        r = approx[i] * 1.1 + 0.05
        cand = tree.query(shapely.buffer(pts[i], r))
        if len(cand) == 0:
            cand = idx[1][idx[0] == i]
        local = _scale(lines[cand], lat_ok[i])
        p = shapely.points(lon_ok[i] * KM_PER_DEG_LON_EQ * math.cos(math.radians(lat_ok[i])),
                           lat_ok[i] * KM_PER_DEG_LAT)
        exact[i] = float(shapely.distance(local, p).min())
    out[ok] = exact
    return out


def targets_flag(lons: np.ndarray, lats: np.ndarray, tif: Path = paths.GRIDFINDER_TARGETS) -> np.ndarray:
    """1 where targets.tif marks the facility's cell as electrified, 0 where not, -1 without coordinates
    or outside the raster."""
    import rasterio
    from rasterio.windows import from_bounds

    out = np.full(len(lons), -1, dtype=np.int8)
    ok = np.isfinite(lons) & np.isfinite(lats)
    with rasterio.open(tif) as src:
        win = from_bounds(*_bbox(0.2), transform=src.transform).round_offsets().round_lengths()
        arr = src.read(1, window=win)
        tr = src.window_transform(win)
    inv = ~tr
    cols, rows = inv * (lons[ok], lats[ok])
    cols = np.floor(cols).astype(int)
    rows = np.floor(rows).astype(int)
    inside = (rows >= 0) & (rows < arr.shape[0]) & (cols >= 0) & (cols < arr.shape[1])
    vals = np.full(ok.sum(), -1, dtype=np.int8)
    vals[inside] = (arr[rows[inside], cols[inside]] == 1).astype(np.int8)
    out[ok] = vals
    return out


def build(facilities: pd.DataFrame | None = None, out: Path = paths.FACILITY_GRID) -> pd.DataFrame:
    if facilities is None:
        facilities = pd.read_parquet(paths.FACILITIES)
    lons = facilities["longitude"].to_numpy(dtype=float)
    lats = facilities["latitude"].to_numpy(dtype=float)
    lines = read_lines()
    res = pd.DataFrame({
        "unique_id": facilities["unique_id"].to_numpy(),
        "grid_km": nearest_km(lons, lats, lines),
        "grid_target": targets_flag(lons, lats),
    })
    res.attrs["n_lines"] = len(lines)
    out.parent.mkdir(parents=True, exist_ok=True)
    res.to_parquet(out, index=False)
    return res


if __name__ == "__main__":
    r = build()
    print(f"lines read: {r.attrs['n_lines']}; facilities: {len(r)}")
    print(r["grid_km"].describe())
    print(r["grid_target"].value_counts())
