"""The only module in `agents/` that imports the engine. Thin wrappers that return plain, JSON-ready dicts.

When the engine's interfaces change, this file is the one to edit; tools, verifier and watcher call only these
functions. Every simulated figure here is MODELLED (supply from the NERC band promise; fridge holdover from PQS
sheets as an upper bound) and carries the engine's own labels.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from functools import lru_cache

import numpy as np
import pandas as pd

from engine import coldchain as CC
from engine import constants as C
from engine import econ as E
from engine import loads as LD
from engine import plan as PL
from engine import sim as SM
from engine import size as SZ
from engine import solar as S
from engine import supply as SP

OFFGRID = SP.OFFGRID
BANDS = tuple(C.BAND_MIN_HOURS)  # ("A", "B", "C", "D", "E")
BAND_MIN_HOURS = dict(C.BAND_MIN_HOURS)
TARGET = 0.99
METRICS = ("doses", "load_hours")
BENEFIT_UNIT = {"doses": "vaccine doses protected per year (estimate)",
                "load_hours": "critical load-hours restored per year"}
COST_BASIS = {"doses": "cold-chain fix capex (capex_ngn)",
              "load_hours": "separate clinic system capex (clinic_capex_ngn when present, else capex_ngn)"}


def iv(x) -> dict | None:
    if x is None:
        return None
    return {"point": float(x.point), "lo": float(x.lo), "hi": float(x.hi)}


def fx() -> dict:
    return {"ngn_per_usd": float(C.FX_NGN_PER_USD.value), "date": C.FX_DATE, "source": C.FX_NGN_PER_USD.source}


def usd_to_ngn(usd: float) -> float:
    return float(usd) * float(C.FX_NGN_PER_USD.value)


@lru_cache(maxsize=1)
def supply_params():
    """The product's supply parameters (calibrated on the NERC shortfalls, T3-widened); the prior if absent."""
    try:
        return SP.calibrated_from_work()[0]
    except Exception:  # noqa: BLE001 - a missing or unreadable work file falls back to the labelled prior
        return SP.PRIOR


def sim_config(n_draws: int = 16) -> SM.SimConfig:
    return SM.SimConfig(n_draws=n_draws, shortfall=supply_params())


def bands_for(tier: str | None, bands_json) -> dict | str | None:
    """Tier d: unknown (None). offgrid: no grid. Otherwise the band mixture (engine.batch's rule)."""
    try:
        from engine import batch as B

        return B.bands_for(str(tier), bands_json)
    except Exception:  # noqa: BLE001 - fall back to the same rule written out here
        if tier == "d_refused":
            return None
        if tier == "offgrid":
            return OFFGRID
        b = json.loads(bands_json) if isinstance(bands_json, str) else (bands_json or {})
        b = {str(k).upper(): float(v) for k, v in dict(b).items() if str(k).upper() in BANDS and float(v) > 0}
        return b or None


def weather_point(lat: float, lon: float) -> tuple[float, float]:
    """The NASA POWER grid point the engine uses for a site (results depend on the point, not the exact site)."""
    p = S.nearest_point(float(lat), float(lon))
    return (float(p[0]), float(p[1]))


def bands_key(bands) -> str:
    if bands is None:
        return "UNKNOWN"
    if isinstance(bands, str):
        return bands
    return json.dumps({k: round(float(v), 4) for k, v in sorted(bands.items())})


# ---------------------------------------------------------------- simulations


def _assess(pp, cfg, offgrid: bool, target: float, bands, supply_label: str) -> dict:
    cc = CC.assess(pp, offgrid, cfg, target)
    sdd_code = CC.SDD_FIX_MODELS[0]
    sdd, _, _arr = SM.sdd_fridge(pp, sdd_code)
    fix = cc.chosen
    return {
        "bands": None if bands is None else (bands if isinstance(bands, str) else dict(bands)),
        "supply_known": bool(pp.known),
        "today_domestic": iv(cc.today_b_domestic),
        "today_pqs_ice_lined": iv(cc.today_a_pqs),
        "solar_direct_drive": iv(sdd.available),
        "solar_direct_drive_model": sdd_code,
        "fix_category": cc.category,
        "fix_label": cc.label,
        "fix_model": {"code": fix.code, "name": fix.name},
        "fix_uptime": iv(fix.uptime),
        "fix_capex_ngn": iv(cc.capex_ngn),
        "fix_monthly_cost_ngn": iv(cc.monthly_cost_ngn),
        "target": target,
        "target_met": bool(cc.target_met),
        "n_lanes": int(pp.n_lanes),
        "supply_calibrated": bool(cfg.shortfall.calibrated),
        "labels": {
            "supply": supply_label,
            "fridge": "PQS holdover treated as an upper bound; uptimes include an availability scenario",
            "today_domestic": "scenario (b): a domestic or non-PQS fridge",
            "today_pqs_ice_lined": "scenario (a): a PQS mains ice-lined fridge",
            "metric": "share of days a year the vaccine fridge holds 2 to 8 degC",
        },
    }


@lru_cache(maxsize=512)
def _coldchain_cached(lat: float, lon: float, bkey: str, n_draws: int, target: float) -> dict:
    bands = None if bkey == "UNKNOWN" else (OFFGRID if bkey == OFFGRID else json.loads(bkey))
    cfg = sim_config(n_draws)
    pp = SM.prepare(lat, lon, bands, cfg)
    return _assess(pp, cfg, bands == OFFGRID, target, bands,
                   "MODELLED from the NERC band promise; promised, not measured")


@lru_cache(maxsize=256)
def _coldchain_hours_cached(lat: float, lon: float, hours: float, sd: float, n_draws: int, target: float) -> dict:
    cfg = sim_config(n_draws)
    pp = SM.prepare(lat, lon, OFFGRID, cfg)  # weather, thermal and equipment draws; the grid is replaced below
    rng = np.random.default_rng(cfg.seed + 7)
    n_lanes, n_hours = pp.grid.shape
    days = n_hours // 24
    d = np.clip(np.rint(rng.normal(hours, sd, size=(n_lanes, days))), 0, 24).astype(np.int16)
    grid = SP.daily_pattern(d, rng).reshape(n_lanes, days * 24)
    pp = replace(pp, grid=grid, known=True)
    out = _assess(pp, cfg, False, target, None,
                  f"MODELLED from the clinic's reported {hours:g} hours of grid power on one day: daily hours drawn "
                  f"around it (normal, sd {sd:g} h, an assumption), outage timing from the engine's pattern")
    out["supply_observed"] = {"hours": hours, "sd": sd}
    return out


def coldchain_observed_hours(lat: float, lon: float, hours: float, sd: float = 2.0, n_draws: int = 16,
                             target: float = TARGET) -> dict:
    """Cold-chain answer with the supply taken from a reported day of grid hours instead of a band promise: each
    simulated day's hours ~ Normal(hours, sd), rounded and clipped to 0 to 24. Never mapped to a band."""
    return dict(_coldchain_hours_cached(round(float(lat), 4), round(float(lon), 4), float(hours), float(sd),
                                        int(n_draws), float(target)))


def prior_predictive(bands, hours: float, sd: float = 2.0, n_draws: int = 64) -> float | None:
    """Share of the band mixture's modelled days whose grid hours lie within sd of the reported value (how
    consistent the reply is with the prior supply model). None when the supply is unknown."""
    if bands is None:
        return None
    if bands == OFFGRID:
        return 1.0 if hours <= sd else 0.0
    p = 0.0
    for b, w in dict(bands).items():
        s = daily_hours_samples(b, n_draws)
        p += float(w) * float((np.abs(s - hours) <= sd).mean())
    return p


def coldchain(lat: float, lon: float, bands, n_draws: int = 16, target: float = TARGET) -> dict:
    """Today's uptime under each equipment scenario and the cheapest fix meeting the target, for one site."""
    return dict(_coldchain_cached(round(float(lat), 4), round(float(lon), 4), bands_key(bands), int(n_draws),
                                  float(target)))


def what_if(lat: float, lon: float, bands, pv_kwp: float, battery_kwh: float, n_draws: int = 16) -> dict:
    """The engine's what_if: one clinic system (PV, battery) for the priority-1 loads, plus the vaccine fridge."""
    r = SM.what_if(lat, lon, bands, LD.critical(), float(pv_kwp), float(battery_kwh), cfg=sim_config(n_draws))
    cap = E.to_ngn(E.clinic_capex_usd(float(pv_kwp), float(battery_kwh)))
    return {
        "pv_kwp": float(pv_kwp), "battery_kwh": float(battery_kwh),
        "fridge_today_domestic": iv(r.fridge_today), "fridge_today_pqs_ice_lined": iv(r.fridge_today_pqs),
        "fridge_with_solar_direct_drive": iv(r.fridge_with),
        "critical_loads_today": iv(r.critical_today), "critical_loads_with_system": iv(r.critical_with),
        "clinic_capex_ngn": {"point": cap.point, "lo": cap.lo, "hi": cap.hi},
        "supply_known": bool(r.supply_known), "n_lanes": int(r.n_lanes),
        "labels": {"critical_loads": "share of days every priority-1 load (lights, oxygen, suction, procedure "
                                     "light, fetal monitor) is served all day",
                   "supply": "MODELLED from the NERC band promise; promised, not measured"},
    }


def size(lat: float, lon: float, bands, target: float = TARGET, n_draws: int = 16) -> dict:
    """The recommended cold-chain fix, and the separate optional clinic system sized to the target."""
    out = {"coldchain": coldchain(lat, lon, bands, n_draws, target)}
    cfg = sim_config(n_draws)
    cs = SZ.size_clinic(lat, lon, bands, LD.critical(), target, cfg=cfg)

    def pt(p):
        cap = E.to_ngn(p.capex_usd)
        return {"pv_kwp": float(p.pv_kwp), "battery_kwh": round(float(p.battery_kwh), 2),
                "capex_ngn": {"point": cap.point, "lo": cap.lo, "hi": cap.hi}, "uptime": iv(p.uptime)}

    out["clinic_system"] = {"target": target, "target_met": bool(cs.target_met), "chosen": pt(cs.chosen),
                            "knee": pt(cs.knee), "daily_load_kwh": float(cs.daily_load_kwh), "optional": True,
                            "note": "its own line; never in the cold-chain price (PQS: no other loads on a "
                                    "solar fridge system)"}
    return out


# ---------------------------------------------------------------- ranking


def rank(results: pd.DataFrame, budget_ngn: float, metric: str) -> tuple[pd.DataFrame, dict]:
    """engine.plan.rank and engine.plan.summary on an already-filtered results frame."""
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {METRICS}")
    r = PL.rank(results, float(budget_ngn), metric)
    return r, PL.summary(r, metric)


def daily_hours_samples(band: str, n_draws: int = 64, n_days: int = 365, seed: int = 20261101) -> np.ndarray:
    """Modelled daily grid hours for one band (for the verifier's update on a reported day)."""
    rng = np.random.default_rng(seed)
    hours, _ = SP.sample_daily_hours({band: 1.0}, n_draws, n_days, rng, supply_params())
    return hours.ravel()


def finite(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False
