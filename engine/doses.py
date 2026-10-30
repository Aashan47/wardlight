"""Doses per facility per year, an ESTIMATE from WorldPop catchment, the crude birth rate and the schedule.

Catchment rule (a modelling choice, stated on /method): every populated 100 m WorldPop 2026 cell (CC BY 4.0,
DOI 10.5258/SOTON/WP00839) is assigned to its nearest eligible GRID3 facility, if that facility is within
CATCHMENT_RADIUS_KM (default 5 km, ASSUMPTION range 3 to 10). Eligible: has coordinates and is not recorded as
"Closed" or "Not-Functional". Population beyond the radius of every facility stays unassigned and is reported.
Distances are great-circle chords on a unit sphere (exact nearest neighbour).

Doses: births = catchment population x 32.493 / 1,000 (World Bank 2024, CC BY 4.0); doses needed per year =
births x 20 doses per child in the first year (DERIVED from the NPHCDA FHIR implementation guide, an unofficial
CI build; 23 with malaria vaccine). Doses protected = doses x share of days the fridge is held at 2 to 8 degC,
assuming sessions are spread evenly over the year (stated). Survival to each dose and coverage are not modelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import constants as C
from . import paths

EARTH_RADIUS_KM = 6371.0088
EXCLUDE_FUNCTIONAL = ("Closed", "Not-Functional")


@dataclass(frozen=True)
class CatchmentRule:
    radius_km: float = C.CATCHMENT_RADIUS_KM.value
    exclude_functional: tuple[str, ...] = EXCLUDE_FUNCTIONAL


def _unit(lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    la, lo = np.radians(lat_deg), np.radians(lon_deg)
    c = np.cos(la)
    return np.column_stack([c * np.cos(lo), c * np.sin(lo), np.sin(la)])


def _chord(km: float) -> float:
    return 2.0 * np.sin(km / EARTH_RADIUS_KM / 2.0)


def eligible(facilities: pd.DataFrame, rule: CatchmentRule = CatchmentRule()) -> pd.DataFrame:
    f = facilities.dropna(subset=["latitude", "longitude"])
    if "functional" in f:
        f = f[~f.functional.isin(rule.exclude_functional)]
    return f.reset_index(drop=True)


def allocate_points(fac_lat: np.ndarray, fac_lon: np.ndarray, pt_lat: np.ndarray, pt_lon: np.ndarray,
                    pt_pop: np.ndarray, radius_km: float) -> tuple[np.ndarray, float]:
    """Sum point population onto the nearest facility within radius. Returns (pop per facility, unassigned)."""
    from scipy.spatial import cKDTree

    tree = cKDTree(_unit(fac_lat, fac_lon))
    _, idx = tree.query(_unit(pt_lat, pt_lon), k=1, distance_upper_bound=_chord(radius_km))
    n = len(fac_lat)
    hit = idx < n
    pop = np.bincount(idx[hit], weights=pt_pop[hit], minlength=n)
    return pop, float(pt_pop[~hit].sum())


def build_catchments(facilities: pd.DataFrame, raster: Path = paths.WORLDPOP_TIF,
                     rule: CatchmentRule = CatchmentRule(), rows_per_block: int = 1024) -> tuple[pd.DataFrame, dict]:
    """Stream the WorldPop raster in row blocks and allocate every populated cell. Minutes, run once."""
    import rasterio
    from rasterio.windows import Window
    from scipy.spatial import cKDTree

    fac = eligible(facilities, rule)
    tree = cKDTree(_unit(fac.latitude.to_numpy(), fac.longitude.to_numpy()))
    n = len(fac)
    pop = np.zeros(n)
    cells = np.zeros(n, dtype=np.int64)
    total = unassigned = 0.0
    chord = _chord(rule.radius_km)
    with rasterio.open(raster) as src:
        nod = src.nodata
        tr = src.transform
        for r0 in range(0, src.height, rows_per_block):
            h = min(rows_per_block, src.height - r0)
            a = src.read(1, window=Window(0, r0, src.width, h))
            m = (a > 0) if nod is None else ((a != nod) & (a > 0))
            if not m.any():
                continue
            rr, cc = np.nonzero(m)
            v = a[rr, cc].astype(float)
            lon = tr.c + (cc + 0.5) * tr.a
            lat = tr.f + (r0 + rr + 0.5) * tr.e
            _, idx = tree.query(_unit(lat, lon), k=1, distance_upper_bound=chord)
            hit = idx < n
            pop += np.bincount(idx[hit], weights=v[hit], minlength=n)
            cells += np.bincount(idx[hit], minlength=n)
            total += v.sum()
            unassigned += v[~hit].sum()
    out = pd.DataFrame({"unique_id": fac.unique_id.values, "catchment_pop": pop, "catchment_cells": cells})
    meta = {"radius_km": rule.radius_km, "eligible_facilities": n, "raster_total_pop": total,
            "assigned_pop": total - unassigned, "unassigned_pop": unassigned,
            "source": "WorldPop 2026 constrained 100 m R2025A v1, CC BY 4.0, DOI 10.5258/SOTON/WP00839",
            "label": "ESTIMATE: nearest-facility allocation within the radius"}
    return out, meta


def births_per_year(catchment_pop: np.ndarray | float, cbr_per_1000: float = C.CRUDE_BIRTH_RATE_PER_1000.value):
    return np.asarray(catchment_pop, dtype=float) * cbr_per_1000 / 1000.0


def doses_per_year(catchment_pop: np.ndarray | float, doses_per_child: float = C.DOSES_PER_CHILD_Y1.value,
                   cbr_per_1000: float = C.CRUDE_BIRTH_RATE_PER_1000.value):
    return births_per_year(catchment_pop, cbr_per_1000) * doses_per_child


def doses_protected(doses: np.ndarray | float, uptime_share: np.ndarray | float):
    return np.asarray(doses, dtype=float) * np.asarray(uptime_share, dtype=float)


def apply_cap(catchment_pop, cap: float = C.CATCHMENT_CAP_POP.value):
    """Cap each facility's catchment at a sourced population per facility (SEforALL: a Type 2 PHC serves 10,000 to
    20,000). Returns (capped population, population above the cap). Fixes dense urban cells piling onto one
    facility (one facility had 963,708 people, 626,275 doses a year, before the cap)."""
    p = np.asarray(catchment_pop, dtype=float)
    capped = np.minimum(p, cap)
    return capped, p - capped
