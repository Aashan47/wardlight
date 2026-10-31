"""Brief 13 in the API: hours of critical service maintained during a line outage, and diesel litres avoided.

Reads the engine's batch columns `out{N}_*` (engine/outage.py `columns`) and the outage-ready fix columns
`orfix_*` (engine/outage.py `orfix_columns`): one fix per facility sized for `orfix_days`, whose service-hours kept
(`orfix_hours_kept`) and diesel avoided (`orfix_diesel_l_avoided`) fill that duration's block. Until a data build
carries them the blocks say so and the fields are null, never invented. The outage trace is an engine run (sim.prepare,
outage.window_mask and apply_outage, sim.simulate_clinic, the fridge scenarios).
"""

from __future__ import annotations

import json
import math
import re

import numpy as np
import pandas as pd

from engine import loads as LD
from engine import outage as OU
from engine import sim as SM

from .whatif import ROOM_LOAD_KEYS, ROOM_NAMES, SDD_CODE

METRIC_TEXT = "hours of critical service maintained during a line outage, and diesel litres avoided"
SCENARIOS = {"hours_today": "today: no solar, household or non-PQS fridge (the headline), clinic loads on grid only",
             "hours_today_pqs": "today, alongside: a PQS mains ice-lined fridge",
             "hours_with": "with the recommended fix (cold-chain fix plus the separate clinic system)",
             "hours_orfix": "with the outage-ready fix",
             "generator_litres": "labelled scenario: a generator covers every critical service through the window "
                                 "(clinic-set curve 0.40 to 0.73 L/kWh, DERIVED)",
             "diesel_l_avoided": "generator fuel the recommended systems replace inside the window"}
_ORFIX_DAY = [re.compile(r"^orfix_out(\d+)_(.+)$"), re.compile(r"^orfix(\d+)_(.+)$"), re.compile(r"^out(\d+)_orfix_(.+)$")]


def _num(x, nd=None):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, nd) if nd is not None else f


def durations(columns) -> list[int]:
    return sorted({int(m.group(1)) for c in columns if (m := re.match(r"^out(\d+)_window_h$", c))})


def orfix_columns(columns) -> tuple[dict[int, dict[str, str]], dict[str, str]]:
    """({days: {name: column}}, {name: column}) for the outage-ready fix columns present."""
    per: dict[int, dict[str, str]] = {}
    fix: dict[str, str] = {}
    for c in columns:
        if "orfix" not in c:
            continue
        for rx in _ORFIX_DAY:
            m = rx.match(c)
            if m:
                per.setdefault(int(m.group(1)), {})[m.group(2)] = c
                break
        else:
            if c.startswith("orfix_"):
                fix[c[len("orfix_"):]] = c
    return per, fix


def _jsonish(v):
    if isinstance(v, str) and v[:1] in "{[":
        try:
            return json.loads(v)
        except ValueError:
            return v
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    n = _num(v)
    return n if n is not None or v is None or (isinstance(v, float) and math.isnan(v)) else v


def _iv(row, name):
    p = _num(row.get(name))
    return None if p is None else {"p": p, "lo": _num(row.get(f"{name}_lo")), "hi": _num(row.get(f"{name}_hi"))}


def _rng(row, name):
    p = _num(row.get(name))
    return None if p is None else {"lo": _num(row.get(f"{name}_lo")), "mid": p, "hi": _num(row.get(f"{name}_hi"))}


def _orfix_values(row, cols: dict[str, str]) -> dict:
    out: dict = {}
    for name, col in cols.items():
        if name.endswith(("_lo", "_hi")) and name[:-3] in cols:
            continue
        v = row.get(col)
        if f"{name}_lo" in cols and f"{name}_hi" in cols:
            out[name] = {"p": _num(v), "lo": _num(row.get(cols[f"{name}_lo"])), "hi": _num(row.get(cols[f"{name}_hi"]))}
        else:
            out[name] = _jsonish(v)
    return out


def orfix_days(row) -> int | None:
    d = _num(row.get("orfix_days"))
    return None if d is None else int(d)


def block(row, days: int, orfix_cols: dict[str, str] | None = None) -> dict | None:
    p = f"out{days}_"
    if _num(row.get(f"{p}window_h")) is None:
        return None
    here = orfix_days(row) == days
    # the fix is sized for orfix_days; the engine also evaluates it at other lengths as orfix_at{N}_*
    pre = "orfix_" if here else f"orfix_at{days}_"
    hours_orfix = _iv(row, f"{pre}hours_kept")
    orf = {"hours_kept": hours_orfix, "diesel_l_avoided": _rng(row, f"{pre}diesel_l_avoided"),
           "share_kept": _num(row.get(f"{pre}share_kept"), 4), "capex_ngn": _rng(row, "orfix_capex_ngn"),
           "sized_for_days": orfix_days(row)} if hours_orfix else None
    by = row.get(f"{p}by_service")
    return {
        "days": days, "window_h": _num(row.get(f"{p}window_h")), "needed_h": _num(row.get(f"{p}needed_h")),
        "hours_today": _iv(row, f"{p}hours_today"), "hours_today_pqs": _iv(row, f"{p}hours_today_pqs"),
        "hours_with": _iv(row, f"{p}hours_with"), "hours_orfix": hours_orfix,
        "share_today": _num(row.get(f"{p}share_today"), 4), "share_with": _num(row.get(f"{p}share_with"), 4),
        "energy_with_kwh": _iv(row, f"{p}energy_with_kwh"),
        "generator_litres": _rng(row, f"{p}generator_litres"),
        "diesel_l_avoided": _rng(row, f"{p}diesel_l_avoided"),
        "by_service": json.loads(by) if isinstance(by, str) and by else None,
        "orfix": orf, "orfix_available": bool(orf),
        "orfix_note": None if orf else ("the outage-ready fix is sized for "
                                        f"{orfix_days(row)} days" if orfix_days(row) else
                                        "the outage-ready fix is not in this data build yet"),
    }


def outage_for(row, days_list: list[int], orfix_per: dict, orfix_fix: dict) -> dict:
    blocks = {str(d): block(row, d, orfix_per.get(d)) for d in days_list}
    return {
        "metric": METRIC_TEXT, "durations": days_list, "by_days": blocks, "scenarios": SCENARIOS,
        "outage_ready_fix": _orfix_values(row, orfix_fix) if orfix_fix else None,
        "outage_ready_fix_note": None if orfix_fix else "the outage-ready fix is not in this data build yet",
        "labels": {"hours": "service-hours: hours in the window each critical service (priority-1 clinic loads and "
                            "the vaccine fridge) ran while needed; median with 5th to 95th percentiles over lanes",
                   "supply": "the grid is forced off for the window inside the modelled NERC band supply"},
    }


def compact(row, days_list: list[int], orfix_per: dict) -> dict:
    """List rows: point values only."""
    out = {}
    for d in days_list:
        p = f"out{d}_"
        if _num(row.get(f"{p}window_h")) is None:
            out[str(d)] = None
            continue
        out[str(d)] = {"needed_h": _num(row.get(f"{p}needed_h"), 1), "today_h": _num(row.get(f"{p}hours_today"), 1),
                       "with_h": _num(row.get(f"{p}hours_with"), 1),
                       "orfix_h": _num(row.get("orfix_hours_kept"), 1) if orfix_days(row) == d else None,
                       "diesel_l_avoided": _num(row.get(f"{p}diesel_l_avoided"), 2)}
    return out


# ---------------------------------------------------------------- city


def city_totals(df: pd.DataFrame, days: int, orfix_cols: dict[str, str] | None) -> dict:
    p = f"out{days}_"

    def s(c):
        return _num(df[c].sum(skipna=True)) if c in df else None

    needed, today, with_ = s(f"{p}needed_h"), s(f"{p}hours_today"), s(f"{p}hours_with")
    here = "orfix_days" in df and len(df) and (df.orfix_days == days).all()
    orfix_h = s("orfix_hours_kept") if here else None
    return {
        "facilities": len(df), "outage_days": days, "service_hours_needed": needed,
        "service_hours_today": today, "service_hours_today_pqs": s(f"{p}hours_today_pqs"),
        "service_hours_with": with_, "service_hours_orfix": orfix_h,
        "share_today": None if not needed else today / needed, "share_with": None if not needed else with_ / needed,
        "share_orfix": None if not needed or orfix_h is None else orfix_h / needed,
        "diesel_l_avoided": {"lo": s(f"{p}diesel_l_avoided_lo"), "mid": s(f"{p}diesel_l_avoided"),
                             "hi": s(f"{p}diesel_l_avoided_hi")},
        "generator_litres_today_scenario": {"lo": s(f"{p}generator_litres_lo"), "mid": s(f"{p}generator_litres"),
                                            "hi": s(f"{p}generator_litres_hi")},
        "diesel_l_avoided_orfix": {"lo": s("orfix_diesel_l_avoided_lo"), "mid": s("orfix_diesel_l_avoided"),
                                   "hi": s("orfix_diesel_l_avoided_hi")} if here else None,
        "cost_ngn": {"coldchain_fix": s("capex_ngn"), "clinic_system": s("clinic_capex_ngn"),
                     "outage_ready_fix": s("orfix_capex_ngn") if here else None},
        "sum_note": "sums of per-facility medians; the lo and hi sums are the sums of per-facility 5th and 95th "
                    "percentiles, wider than a joint interval",
    }


# ---------------------------------------------------------------- outage trace


def trace(lat, lon, bands, days: int, pv_kwp: float, battery_kwh: float, fix_kind: str, fix_code: str,
          shortfall, n_draws: int = 32, pad_h: int = 12) -> dict:
    """Hourly trace across one lane's outage window (pad_h hours either side), for the 3D night.

    Lane: the draw whose service-hours kept with the recommended systems is closest to the median over draws."""
    cfg = SM.SimConfig(n_draws=n_draws, shortfall=shortfall)
    pp = SM.prepare(lat, lon, bands, cfg)
    B = SM.BURN_IN_H
    L, T = pp.n_lanes, pp.grid.shape[1] - B
    mask, start = OU.window_mask(L, T, days, cfg.seed)
    po = OU.apply_outage(pp, mask) if pp.known else pp
    crit = LD.critical()
    _, prof = LD.priority_profile(crit)
    hod = np.arange(T) % 24
    grid = po.grid[:, B:]
    _, ok_dom = SM.domestic_on_grid(po)
    if fix_kind == "i" and po.known:
        _, ok_fix = SM.ilr_on_grid(po, fix_code, cfg.thermal)
    else:
        _, ok_fix, _ = SM.sdd_fridge(po, fix_code or SDD_CODE)
    res = SM.simulate_clinic(po.grid, po.pv_l, np.array([pv_kwp]), np.array([battery_kwh]), prof, cfg.battery,
                             burn_in_h=B, return_served=True)
    served = res["served_all"][0] >= 1
    kept = (ok_fix & mask).sum(axis=1).astype(float)
    for ld in crit:
        need = ld.hourly_kw()[hod] > 0
        kept += ((served | grid) & need[None, :] & mask).sum(axis=1)
    med = float(np.median(kept))
    lane = int(np.argmin(np.abs(kept - med)))
    one = SM.simulate_clinic(po.grid[lane:lane + 1], po.pv_l[lane:lane + 1], np.array([pv_kwp]),
                             np.array([battery_kwh]), prof, cfg.battery, trace_lane=0, burn_in_h=B)
    soc, cap = one["soc_trace"][0], float(one["cap"][0])
    s0 = max(0, int(start[lane]) * 24 - pad_h)
    s1 = min(T, (int(start[lane]) + days) * 24 + pad_h)
    sl = slice(s0, s1)
    hrs = np.arange(s0, s1)
    room_need = {r: sum(LD.by_key()[k].hourly_kw() for k in ROOM_LOAD_KEYS[r]) > 0
                 for r in ("delivery", "oxygen", "ward")}
    rooms_with: dict[str, list] = {"fridge": [bool(x) for x in ok_fix[lane, sl]]}
    rooms_today: dict[str, list] = {"fridge": None if ok_dom is None else [bool(x) for x in ok_dom[lane, sl]]}
    for r, need in room_need.items():
        rooms_with[r] = [None if not need[h % 24] else bool(served[lane, h] or grid[lane, h]) for h in hrs]
        rooms_today[r] = [None if not need[h % 24] else bool(grid[lane, h]) for h in hrs]
    rooms_with["lab"] = rooms_today["lab"] = [None] * len(hrs)  # priority 2: not a critical service
    return {
        "days": days, "start_hour": int(s0 % 24), "hour_index": [int(h) for h in hrs],
        "hour": [int(h % 24) for h in hrs], "in_outage": [bool(x) for x in mask[lane, sl]],
        "grid_on": [bool(x) for x in grid[lane, sl]],
        "solar_kw": [round(float(x), 3) for x in (pv_kwp * po.pv_l[lane, B:][sl])],
        "load_kw": [round(float(prof.sum(axis=0)[h % 24]), 3) for h in hrs],
        "battery_soc": [round(float(x) / cap, 4) if cap > 0 else 0.0 for x in soc[sl]],
        "battery_kwh": battery_kwh, "pv_kwp": pv_kwp, "rooms": rooms_with, "rooms_today": rooms_today,
        "room_names": {k: ROOM_NAMES[k] for k in ("fridge", "delivery", "oxygen", "ward", "lab")},
        "scenario": "with the recommended fix: cold-chain fix " + (fix_code or "") + " and the separate clinic system "
                    f"({pv_kwp:g} kWp, {battery_kwh:g} kWh); rooms_today: no solar, household fridge, grid only",
        "draw": {"lane": lane, "n_lanes": int(L), "lane_service_hours_with": float(kept[lane]),
                 "median_service_hours_with": med, "window_start_day": int(start[lane]), "pad_h": pad_h,
                 "rule": "the draw whose service-hours kept with the recommended systems is closest to the median "
                         "over draws; window placed by engine.outage.window_mask (seed + 1000 + days)"},
        "note": "one simulated outage (modelled supply, NASA POWER weather), not a measurement",
    }
