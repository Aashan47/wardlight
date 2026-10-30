"""Line-outage scenario (brief 13, "Hours of critical service maintained during a line outage, and diesel litres
avoided"; also useful for brief 16).

A grid-down window of N days is placed inside each lane's normal band supply: the grid is forced off for those
hours (the OFFGRID path, no new physics) and is unchanged before and after. The window starts on a day drawn per
lane, uniformly over the simulated year after the 7-day burn-in, from its own random stream (seed + 1000 + N), so
the existing draws and results are untouched. Days 3, 7 and 14 are the defaults (a stated range; the brief may
name one).

Critical services: each priority-1 clinic load (delivery room, oxygen, interior lights) and the vaccine fridge.
"Service-hours maintained" = hours in the window in which the service was running while it was needed (a load is
needed in the hours its daily window covers; the fridge every hour). Reported per service and summed, as a median
with 5th to 95th percentiles over lanes. Fridge hours are technical (equipment working); the annual availability
scenario is not applied inside a single window.

Today: no solar. Scenario (b) domestic fridge is the headline, (a) PQS ice-lined alongside; clinic loads run only
on grid. Optional labelled scenario "generator": a generator covers every critical service through the window,
burning (priority-1 energy + the mains fridge's energy) x GEN_L_PER_KWH (UNVERIFIED range 0.303 to 0.454 L/kWh).
With the recommended system: the facility's cold-chain fix (an ice-lined fridge on the grid falls back on its
holdover during the outage; a solar direct-drive fridge is unaffected) and the clinic system.
Diesel avoided in the window = energy the systems deliver to critical services in the window x the L/kWh range,
i.e. the generator fuel they replace where a generator would otherwise run. Litres per year stay the existing
`diesel_l_avoided` column of the clinic line.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace

import numpy as np
import pandas as pd

from . import constants as C
from . import econ as E
from . import fridge as F
from . import loads as LD
from . import sim as SM

DEFAULT_DAYS: tuple[int, ...] = (3, 7, 14)


def window_mask(n_lanes: int, n_hours: int, days: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """(L, n_hours) bool, True inside each lane's outage window; and the start day per lane."""
    mask = np.zeros((n_lanes, n_hours), dtype=bool)
    n_days = n_hours // 24
    if days <= 0:
        return mask, np.zeros(n_lanes, dtype=int)
    days = min(days, n_days)
    rng = np.random.default_rng(seed + 1000 + days)
    start = rng.integers(0, n_days - days + 1, size=n_lanes)
    h = np.arange(n_hours)
    mask[:] = (h[None, :] >= (start * 24)[:, None]) & (h[None, :] < ((start + days) * 24)[:, None])
    return mask, start


def apply_outage(pp: SM.Prepared, mask: np.ndarray) -> SM.Prepared:
    """Grid off inside the window (mask has no burn-in columns); everything else unchanged."""
    g = pp.grid.copy()
    g[:, SM.BURN_IN_H:][mask] = False
    return replace(pp, grid=g)


@dataclass
class ServiceHours:
    key: str
    name: str
    needed_h: float
    today: SM.Interval
    with_system: SM.Interval


@dataclass
class OutageResult:
    days: int
    window_h: int
    services: list[ServiceHours]
    needed_h: float
    today: SM.Interval  # summed service-hours maintained, scenario (b) fridge, no generator
    today_pqs: SM.Interval  # same with scenario (a) PQS ice-lined fridge
    with_system: SM.Interval
    share_today: float
    share_with: float
    generator_litres: E.Range  # labelled scenario: a generator covers every critical service today
    diesel_l_avoided: E.Range  # fuel the systems replace inside the window
    energy_with_kwh: SM.Interval
    applied: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _in_window(ok: np.ndarray, need: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Hours per lane where the service ran while needed, inside the window. ok, need, mask (L, T)."""
    return (ok & need & mask).sum(axis=1).astype(float)


def simulate_outage(pp: SM.Prepared, days: int, crit_loads: Sequence[LD.Load], clinic: SM.ClinicSystem,
                    fix_kind: str, fix_code: str, cfg: SM.SimConfig = SM.SimConfig(),
                    apply: bool = True) -> OutageResult:
    """One facility, one window length. apply=False measures the same window on the normal grid (a baseline)."""
    B = SM.BURN_IN_H
    L = pp.n_lanes
    T = pp.grid.shape[1] - B
    mask, _ = window_mask(L, T, days, cfg.seed)
    po = apply_outage(pp, mask) if (apply and pp.known) else pp
    grid = po.grid[:, B:]
    window_h = int(mask[0].sum())
    hod = np.arange(T) % 24

    # fridge: today scenarios (b) and (a); with the fix
    _, ok_dom = SM.domestic_on_grid(po)
    _, ok_pqs = SM.ilr_on_grid(po, cfg.fridge_today, cfg.thermal)
    if fix_kind == "i" and po.known:
        _, ok_fix = SM.ilr_on_grid(po, fix_code, cfg.thermal)
    else:
        _, ok_fix, _ = SM.sdd_fridge(po, fix_code)
    all_h = np.ones((L, T), dtype=bool)
    zero = np.zeros((L, T), dtype=bool)
    fr_today = _in_window(ok_dom if ok_dom is not None else zero, all_h, mask)
    fr_pqs = _in_window(ok_pqs if ok_pqs is not None else zero, all_h, mask)
    fr_with = _in_window(ok_fix, all_h, mask)

    # clinic: priority-1 loads only, on grid today; on grid + PV + battery with the system
    crit = [ld for ld in crit_loads if ld.priority <= cfg.critical_priority]
    _, prof = LD.priority_profile(crit)
    res = SM.simulate_clinic(po.grid, po.pv_l, np.array([clinic.pv_kwp]), np.array([clinic.battery_kwh]), prof,
                             cfg.battery, burn_in_h=B, return_served=True)
    served = res["served_all"][0] >= 1  # (L, T) priority 1 served
    services: list[ServiceHours] = []
    tot_today = fr_today.copy()
    tot_pqs = fr_pqs.copy()
    tot_with = fr_with.copy()
    energy = np.zeros(L)
    for ld in crit:
        kw = ld.hourly_kw()
        need = np.broadcast_to(kw[hod] > 0, (L, T))
        t_h = _in_window(grid, need, mask)
        w_h = _in_window(served | grid, need, mask)
        n_h = float((need & mask)[0].sum())
        services.append(ServiceHours(ld.key, ld.name, n_h, SM.Interval.of(t_h), SM.Interval.of(w_h)))
        tot_today += t_h
        tot_pqs += t_h
        tot_with += w_h
        # energy the system (not the grid) delivers to this load in the window
        energy += ((served & ~grid & mask) * kw[hod][None, :]).sum(axis=1)
    services.append(ServiceHours("vaccine_fridge", "Vaccine fridge", float(window_h), SM.Interval.of(fr_today),
                                 SM.Interval.of(fr_with)))
    needed = float(sum(s.needed_h for s in services))
    mains_kw = (F.CATALOGUE[cfg.fridge_today].energy_kwh_24h or 0.0) / 24.0
    p1_energy_needed = sum(float((np.broadcast_to(ld.hourly_kw()[hod], (L, T)) * mask)[0].sum()) for ld in crit)
    gen_kwh = p1_energy_needed + mains_kw * window_h
    # an SDD fix also replaces the generator's mains-fridge energy in the window, where it holds
    if not (fix_kind == "i" and po.known):
        energy = energy + mains_kw * (ok_fix & mask).sum(axis=1)
    lpk = E.crange(C.GEN_L_PER_KWH)
    e_iv = SM.Interval.of(energy)
    share = (lambda x: float(np.median(x)) / needed if needed > 0 else float("nan"))
    return OutageResult(days, window_h, services, needed, SM.Interval.of(tot_today), SM.Interval.of(tot_pqs),
                        SM.Interval.of(tot_with), share(tot_today), share(tot_with), lpk * gen_kwh,
                        lpk * e_iv.point, e_iv, apply and pp.known)


# ---------------------------------------------------------------- batch columns, aggregation


def columns(out: OutageResult) -> dict:
    """Flat batch columns for one window length, prefixed out{N}_."""
    p = f"out{out.days}_"
    row = {f"{p}window_h": out.window_h, f"{p}needed_h": out.needed_h}
    for name, iv in (("hours_today", out.today), ("hours_today_pqs", out.today_pqs), ("hours_with", out.with_system),
                     ("energy_with_kwh", out.energy_with_kwh)):
        row[f"{p}{name}"], row[f"{p}{name}_lo"], row[f"{p}{name}_hi"] = iv.point, iv.lo, iv.hi
    row[f"{p}share_today"], row[f"{p}share_with"] = out.share_today, out.share_with
    for name, r in (("generator_litres", out.generator_litres), ("diesel_l_avoided", out.diesel_l_avoided)):
        row[f"{p}{name}"], row[f"{p}{name}_lo"], row[f"{p}{name}_hi"] = r.point, r.lo, r.hi
    row[f"{p}by_service"] = json.dumps({
        s.key: {"name": s.name, "needed_h": s.needed_h, "today_h": round(s.today.point, 1),
                "with_h": round(s.with_system.point, 1), "with_h_lo": round(s.with_system.lo, 1)}
        for s in out.services})
    return row


def aggregate(results: pd.DataFrame, facilities: pd.DataFrame, days: int = 7,
              by: Sequence[str] = ("state_standard", "lga_standard")) -> pd.DataFrame:
    """Sum the outage metrics by state and LGA (or any facility columns, e.g. settlement_name for a city)."""
    p = f"out{days}_"
    keep = ["unique_id", *[c for c in by if c in facilities]]
    df = results.merge(facilities[keep].drop_duplicates("unique_id"), on="unique_id", how="left")
    cols = {f"{p}needed_h": "service_hours_needed", f"{p}hours_today": "service_hours_today",
            f"{p}hours_with": "service_hours_with", f"{p}generator_litres": "generator_litres_today_scenario",
            f"{p}diesel_l_avoided": "diesel_l_avoided", f"{p}diesel_l_avoided_lo": "diesel_l_avoided_lo",
            f"{p}diesel_l_avoided_hi": "diesel_l_avoided_hi", "capex_ngn": "coldchain_fix_ngn",
            "clinic_capex_ngn": "clinic_system_ngn"}
    g = df.groupby(list(by), dropna=False).agg(facilities=("unique_id", "size"),
                                               **{v: (k, "sum") for k, v in cols.items() if k in df})
    g["share_today"] = g.service_hours_today / g.service_hours_needed
    g["share_with"] = g.service_hours_with / g.service_hours_needed
    g["outage_days"] = days
    return g.reset_index()
