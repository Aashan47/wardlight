"""Hourly PV output from NASA POWER, and the PVGIS cross-check (T4).

Model (documented in docs/sources/engine.md):
- Irradiance: NASA POWER hourly ALLSKY_SFC_SW_DWN (Wh/m2 in the hour, so mean W/m2) and T2M, nearest
  whole-degree grid point in `data-local/nasa-power/`, years 2021 to 2023, shifted from UTC to West Africa
  Time (UTC+1).
- Plane: horizontal (tilt 0). At Nigerian latitudes (4 to 14 N) the tilt gain is small; horizontal is
  the conservative choice and is what the T4 cross-check compares like for like.
- Cell temperature: NOCT model, Tc = Ta + (NOCT - 20) / 800 * G.
- Power: P/Pnom = G / 1000 * (1 + gamma * (Tc - 25)) * (1 - system_loss), floored at 0.
All three parameters are labelled ASSUMPTION ranges in `engine.constants`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import constants as C
from . import paths

YEARS: tuple[int, ...] = (2021, 2022, 2023)
HOURS_PER_YEAR = 8760
LAT_RANGE = (4, 14)
LON_RANGE = (3, 15)
UTC_OFFSET_H = 1  # West Africa Time


@dataclass(frozen=True)
class PVParams:
    system_loss: float = C.PV_SYSTEM_LOSS.value
    temp_coeff_per_c: float = C.PV_TEMP_COEFF_PER_C.value
    noct_c: float = C.PV_NOCT_C.value


@dataclass(frozen=True)
class Weather:
    """Hourly local-time weather, shape (n_years, 8760)."""

    point: tuple[int, int]  # (lat, lon) of the NASA POWER grid point used
    years: tuple[int, ...]
    ghi_w_m2: np.ndarray
    t2m_c: np.ndarray

    @property
    def n_years(self) -> int:
        return self.ghi_w_m2.shape[0]


def nearest_point(lat: float, lon: float) -> tuple[int, int]:
    """Nearest whole-degree NASA POWER point held locally (clamped to the downloaded grid)."""
    if not (np.isfinite(lat) and np.isfinite(lon)):
        raise ValueError("lat/lon must be finite")
    la = int(min(max(round(lat), LAT_RANGE[0]), LAT_RANGE[1]))
    lo = int(min(max(round(lon), LON_RANGE[0]), LON_RANGE[1]))
    return la, lo


def _read_year(lat: int, lon: int, year: int, root: Path) -> tuple[np.ndarray, np.ndarray]:
    path = root / f"lat{lat}_lon{lon}_{year}.json"
    with open(path) as f:
        d = json.load(f)
    p = d["properties"]["parameter"]
    fill = d["header"].get("fill_value", -999.0)
    keys = sorted(p["ALLSKY_SFC_SW_DWN"].keys())
    ghi = np.array([p["ALLSKY_SFC_SW_DWN"][k] for k in keys], dtype=float)
    t2m = np.array([p["T2M"][k] for k in keys], dtype=float)
    if ghi.size != HOURS_PER_YEAR or t2m.size != HOURS_PER_YEAR:
        raise ValueError(f"{path.name}: expected 8760 hours, got {ghi.size}")
    if np.any(ghi == fill) or np.any(t2m == fill):
        raise ValueError(f"{path.name}: fill values present")
    # UTC -> local (WAT): local hour h is UTC hour h-1, so roll forward by one.
    return np.roll(ghi, UTC_OFFSET_H), np.roll(t2m, UTC_OFFSET_H)


@lru_cache(maxsize=256)
def _load_point(lat: int, lon: int, years: tuple[int, ...], root: str) -> Weather:
    ghi, t2m = zip(*(_read_year(lat, lon, y, Path(root)) for y in years))
    g = np.clip(np.vstack(ghi), 0.0, None)
    t = np.vstack(t2m)
    g.setflags(write=False)
    t.setflags(write=False)
    return Weather((lat, lon), years, g, t)


def load_weather(lat: float, lon: float, years: tuple[int, ...] = YEARS, root: Path | None = None) -> Weather:
    la, lo = nearest_point(lat, lon)
    return _load_point(la, lo, tuple(years), str(root or paths.NASA_POWER))


def pv_kwh_per_kwp(ghi_w_m2: np.ndarray, t2m_c: np.ndarray, params: PVParams = PVParams()) -> np.ndarray:
    """AC energy per kWp in each hour (kWh/kWp), same shape as the inputs."""
    g = np.clip(np.asarray(ghi_w_m2, dtype=float), 0.0, None)
    tc = np.asarray(t2m_c, dtype=float) + (params.noct_c - 20.0) / 800.0 * g
    out = g / 1000.0 * (1.0 + params.temp_coeff_per_c * (tc - 25.0)) * (1.0 - params.system_loss)
    return np.clip(out, 0.0, None)


def weather_pv(weather: Weather, params: PVParams = PVParams()) -> np.ndarray:
    return pv_kwh_per_kwp(weather.ghi_w_m2, weather.t2m_c, params)


def annual_yield_kwh_per_kwp(lat: float, lon: float, params: PVParams = PVParams(),
                             years: tuple[int, ...] = YEARS) -> float:
    """Mean annual specific yield (kWh/kWp/yr) over the weather years."""
    w = load_weather(lat, lon, years)
    return float(weather_pv(w, params).sum(axis=1).mean())


# ---------------------------------------------------------------- PVGIS cross-check (T4)

PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_3/seriescalc"


def pvgis_annual_yield(lat: float, lon: float, years: tuple[int, int] = (2021, 2023), loss_pct: float = 14.0,
                       cache_dir: Path | None = None, client=None) -> dict:
    """PVGIS seriescalc, 1 kWp, horizontal, no horizon, same loss as our model. Cached on disk.

    Returns {'kwh_per_kwp_yr', 'years_returned', 'radiation_db', 'meteo_db'}.
    """
    cache_dir = cache_dir or paths.PVGIS_CACHE
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = f"series_{lat:.4f}_{lon:.4f}_{years[0]}_{years[1]}_loss{loss_pct:g}_h0.json"
    cpath = cache_dir / key
    if cpath.exists():
        data = json.loads(cpath.read_text())
    else:
        import httpx

        params = {
            "lat": f"{lat:.4f}", "lon": f"{lon:.4f}", "startyear": years[0], "endyear": years[1],
            "pvcalculation": 1, "peakpower": 1, "loss": loss_pct, "angle": 0, "aspect": 0,
            "usehorizon": 0, "outputformat": "json",
        }
        own = client is None
        client = client or httpx.Client(timeout=120)
        try:
            for attempt in range(4):
                r = client.get(PVGIS_URL, params=params)
                if r.status_code == 429:
                    time.sleep(1.0 + attempt)
                    continue
                r.raise_for_status()
                break
            data = r.json()
        finally:
            if own:
                client.close()
        cpath.write_text(json.dumps(data))
    hourly = data["outputs"]["hourly"]
    p_w = np.array([h["P"] for h in hourly], dtype=float)
    yrs = sorted({h["time"][:4] for h in hourly})
    meta = data.get("inputs", {}).get("meteo_data", {})
    return {
        "kwh_per_kwp_yr": float(p_w.sum() / 1000.0 / len(yrs)),
        "years_returned": yrs,
        "radiation_db": meta.get("radiation_db"),
        "meteo_db": meta.get("meteo_db"),
    }


def t4_sample_sites(facilities: pd.DataFrame, n: int = 20, seed: int = 20261030) -> pd.DataFrame:
    """PREREG T4: n sites drawn at random from facility locations with valid coordinates."""
    ok = facilities.dropna(subset=["latitude", "longitude"])
    ok = ok[(ok.latitude.between(4, 14.5)) & (ok.longitude.between(2.5, 15))]
    return ok.sample(n=n, random_state=seed)[["unique_id", "facility_name", "state_standard", "latitude", "longitude"]]


def t4_crosscheck(sites: pd.DataFrame, params: PVParams = PVParams(), tol: float = 0.10,
                  cache_dir: Path | None = None) -> tuple[pd.DataFrame, dict]:
    """Compare NASA POWER yield (nearest grid point) with PVGIS at the facility coordinates."""
    rows = []
    for s in sites.itertuples():
        ours = annual_yield_kwh_per_kwp(s.latitude, s.longitude, params)
        pv = pvgis_annual_yield(s.latitude, s.longitude, loss_pct=params.system_loss * 100, cache_dir=cache_dir)
        rows.append({
            "unique_id": s.unique_id, "facility_name": s.facility_name, "state": s.state_standard,
            "lat": s.latitude, "lon": s.longitude, "nasa_point": nearest_point(s.latitude, s.longitude),
            "nasa_kwh_kwp": ours, "pvgis_kwh_kwp": pv["kwh_per_kwp_yr"], "pvgis_years": ",".join(pv["years_returned"]),
            "pvgis_db": f'{pv["radiation_db"]}/{pv["meteo_db"]}',
        })
    df = pd.DataFrame(rows)
    df["rel_diff"] = df.nasa_kwh_kwp / df.pvgis_kwh_kwp - 1.0
    df["within_tol"] = df.rel_diff.abs() <= tol
    summary = {
        "n": len(df), "within": int(df.within_tol.sum()), "tol": tol,
        "median_rel_diff": float(df.rel_diff.median()), "max_abs_rel_diff": float(df.rel_diff.abs().max()),
        "pass_all_within": bool(df.within_tol.all()),
    }
    return df, summary
