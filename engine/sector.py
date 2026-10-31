"""Brief 13: the outage logic for a critical site that is not a health facility (a borehole pump, the water works,
a market cold room), with the same supply draws, outage windows and battery dispatch as the clinic system.

A site has one critical load: `kw` while it runs, `hours` a day from `start` (local time). Needed hours are the
hours in the outage window that load runs. Served:
- today, mode "grid": the grid alone (forced off inside the window, as for health);
- today, mode "solar_direct" (the survey's solar boreholes): the existing array alone, daylight only, no grid. A
  variable-speed solar pump runs in proportion to the array's output, so each needed hour counts as the share
  min(1, array output / pump kW) of a pump-hour (array = SOLAR_BH_ARRAY_KWP_PER_KW x pump kW, an ASSUMPTION);
- with the plan: a new PV + battery system (SEforALL 7.2 kWh per kWp) or what served it today. The existing array
  is not credited in the price (conservative).
Sizing: the smallest PV (battery at 7.2 kWh/kWp) keeping at least 95% of needed hours at the 5th percentile over lanes
in a 7-day outage, as for the health outage-ready fix (`outage.size_outage_ready`).

Every quantity is linear in the load (PV, battery, charge rate and demand scale together in `sim.simulate_clinic`),
so a profile is simulated once at 1 kW and scaled by each site's kW: sizes, energies and litres are per kW; hours
are unchanged. The sizing grid is not rounded, so scaling is exact.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from . import constants as C
from . import econ as E
from . import loads as LD
from . import outage as OU
from . import sim as SM

SIZE_DAYS = OU.OR_DAYS
TARGET = OU.OR_TARGET
EVAL_DAYS: tuple[int, ...] = (7, 14, 40, 60)
MODES = ("grid", "solar_direct")


def pump_kw(yield_l_s: float, head_m: C.Const = C.BH_PUMP_HEAD_M, eff: C.Const = C.BH_PUMP_EFF) -> E.Range:
    """P = rho g H Q / eta in kW. lo pairs the low head with the high efficiency; hi the reverse."""
    k = C.WATER_DENSITY_KG_M3.value * C.STANDARD_GRAVITY_M_S2.value * (yield_l_s / 1000.0) / 1000.0
    return E.Range(k * head_m.value / eff.value, k * head_m.lo / eff.hi, k * head_m.hi / eff.lo)


def window_start(hours: float, centre: float = C.PUMP_WINDOW_CENTRE_H.value) -> int:
    """First hour of a daily window of `hours` centred on `centre` (24 h loads start at 0)."""
    if hours >= 24:
        return 0
    return int(round(centre - hours / 2.0)) % 24


def daily_yield_kwh_per_kwp(lat: float, lon: float, cfg: SM.SimConfig = SM.SimConfig()) -> tuple[float, float, float]:
    """Mean daily AC yield per kWp at the site's NASA POWER point: (all years, lowest year, highest year)."""
    from . import solar as S

    pv, _, _ = SM._pv_and_leak(S.nearest_point(lat, lon), tuple(cfg.years), cfg.pv, cfg.thermal)
    per_year = pv.sum(axis=1) / 365.0
    return float(per_year.mean()), float(per_year.min()), float(per_year.max())


def unit_load(hours: float, start: int) -> LD.Load:
    return LD.Load("site", "critical site load (1 kW)", 1, 1000.0, float(min(hours, 24.0)), 1, int(start),
                   source="brief-13 site archetype")


@dataclass(frozen=True)
class Window:
    days: int
    needed_h: float
    today_h: SM.Interval
    with_h: SM.Interval
    needed_kwh: float  # per kW
    base_kwh: SM.Interval  # per kW, served locally today (existing solar array)
    system_kwh: SM.Interval  # per kW, delivered by the new system while nothing else served

    def share(self, which: str) -> float:
        iv = self.today_h if which == "today" else self.with_h
        return iv.point / self.needed_h if self.needed_h > 0 else float("nan")


@dataclass(frozen=True)
class DailyArm:
    kwp_per_kw: float
    kwh_per_kw: float
    windows: dict[int, Window]
    annual_kwh_per_kw: SM.Interval


DAILY_ARM_LABEL = ("daily-cycle design (our design rule): PV for one average day's critical energy at the site's mean "
                   "hourly yield, battery for one night's critical energy (hours under 10% of the mean peak yield) at "
                   "the stated usable share and round-trip efficiency; no multi-day autonomy. A cost arm only; the "
                   "plan's sizing is the 7-day outage-ready design")


def daily_cycle_size(pp: SM.Prepared, load24: np.ndarray, cfg: SM.SimConfig) -> tuple[float, float]:
    """(kWp, battery kWh nameplate) of the daily-cycle design for a 24-hour load profile in kW."""
    B = SM.BURN_IN_H
    pv = pp.pv_l[:, B:]
    T = pv.shape[1] - pv.shape[1] % 24
    pv_h = pv[:, :T].reshape(pv.shape[0], -1, 24).mean(axis=(0, 1))  # mean kWh per kWp in each hour of day
    night = pv_h < 0.1 * pv_h.max()
    load24 = np.asarray(load24, float)
    e_night = float(load24[night].sum())
    e_day = float(load24[~night].sum())
    rte = cfg.battery.round_trip_eff
    kwp = (e_day + e_night / rte) / max(float(pv_h.sum()), 1e-9)
    kwh = e_night / np.sqrt(rte) / cfg.battery.usable_fraction
    return float(kwp), float(kwh)


@dataclass(frozen=True)
class ProfileRun:
    hours: float
    start: int
    mode: str
    kwp_per_kw: float
    kwh_per_kw: float
    target_met: bool
    crit_share_lo: float
    windows: dict[int, Window]
    annual_kwh_per_kw: SM.Interval  # solar-first operation, no grid: energy the system delivers in a year
    daily: DailyArm | None = None  # the daily-cycle design, a cost arm (never the headline sizing)


def _base(pp: SM.Prepared, mode: str, ratio: float) -> np.ndarray:
    """(L, T) share of the load served without the new system: the grid (0 or 1) or the existing array."""
    B = SM.BURN_IN_H
    if mode == "solar_direct":
        return np.clip(ratio * pp.pv_l[:, B:], 0.0, 1.0).astype(np.float32)
    return pp.grid[:, B:].astype(np.float32)


def _served(po: SM.Prepared, kwp: np.ndarray, prof: np.ndarray, cfg: SM.SimConfig,
            kwh: np.ndarray | None = None) -> np.ndarray:
    kwh = kwp * C.BATTERY_KWH_PER_KWP.value if kwh is None else kwh
    res = SM.simulate_clinic(po.grid, po.pv_l, kwp, kwh, prof, cfg.battery,
                             burn_in_h=SM.BURN_IN_H, return_served=True)
    return res["served_all"] >= 1  # (S, L, T)


def run_profile(pp: SM.Prepared, hours: float, start: int, mode: str, cfg: SM.SimConfig,
                eval_days: Sequence[int] = EVAL_DAYS, size_days: int = SIZE_DAYS, target: float = TARGET,
                array_ratio: float = C.SOLAR_BH_ARRAY_KWP_PER_KW.value) -> ProfileRun:
    """One load shape at 1 kW on one prepared supply: size the system, then run every outage window."""
    if mode not in MODES:
        raise ValueError(mode)
    B = SM.BURN_IN_H
    T = pp.grid.shape[1] - B
    load = unit_load(hours, start)
    _, prof = LD.priority_profile([load])
    hod = np.arange(T) % 24
    need1 = load.hourly_kw()[hod] > 0  # (T,)
    kw_h = load.hourly_kw()[hod]  # (T,) kW, per 1 kW of load

    def masked(days):
        mask, _ = OU.window_mask(pp.n_lanes, T, days, cfg.seed)
        po = OU.apply_outage(pp, mask) if pp.known else pp
        return mask, po

    # sizing in the size_days window
    mask, po = masked(size_days)
    base = _base(po, mode, array_ratio)
    need = need1[None, :] & mask
    needed = float(need[0].sum())
    y = float(pp.pv_l[:, B:].sum(axis=1).mean())
    daily = load.wh_per_day / 1000.0
    kwp = daily / max(y / 365.0, 1e-6) * np.geomspace(0.3, 8.0, 20)

    def share_lo(k):
        sv = _served(po, k, prof, cfg)
        kept = (np.maximum(sv, base[None]) * need[None]).sum(axis=2) / max(needed, 1e-9)
        return np.quantile(kept, 0.05, axis=1), kept

    lo, _ = share_lo(kwp)
    ok = np.where(lo >= target)[0]
    if ok.size and ok[0] > 0:
        fine = np.linspace(kwp[ok[0] - 1], kwp[ok[0]], 8)[1:-1]
        flo, _ = share_lo(fine)
        kwp = np.concatenate([kwp, fine])
        lo = np.concatenate([lo, flo])
        order = np.argsort(kwp, kind="mergesort")
        kwp, lo = kwp[order], lo[order]
        ok = np.where(lo >= target)[0]
    i = int(ok[0]) if ok.size else int(np.argmax(lo))
    k1 = float(kwp[i])

    def evaluate(kp: float, kh: float):
        windows: dict[int, Window] = {}
        for d in eval_days:
            mask, po = masked(d)
            base = _base(po, mode, array_ratio)
            need = need1[None, :] & mask
            sv = _served(po, np.array([kp]), prof, cfg, np.array([kh]))[0]
            today = (base * need).sum(axis=1).astype(float)
            with_ = (np.maximum(sv, base) * need).sum(axis=1).astype(float)
            base_e = (base * need * kw_h[None, :]).sum(axis=1)
            sys_e = (sv * (1.0 - base) * need * kw_h[None, :]).sum(axis=1)
            windows[d] = Window(d, float(need[0].sum()), SM.Interval.of(today), SM.Interval.of(with_),
                                float((need[0] * kw_h).sum()), SM.Interval.of(base_e), SM.Interval.of(sys_e))
        off = replace(pp, grid=np.zeros_like(pp.grid))
        res = SM.simulate_clinic(off.grid, off.pv_l, np.array([kp]), np.array([kh]), prof, cfg.battery, burn_in_h=B)
        return windows, SM.Interval.of(res["offgrid_kwh"][0])

    kh1 = k1 * C.BATTERY_KWH_PER_KWP.value
    windows, annual = evaluate(k1, kh1)
    dk, dh = daily_cycle_size(pp, prof.sum(axis=0), cfg)
    dwin, dann = evaluate(dk, dh)
    return ProfileRun(float(hours), int(start), mode, k1, kh1, bool(ok.size), float(lo[i]), windows, annual,
                      DailyArm(dk, dh, dwin, dann))


def annual_solar_first_kwh(pp: SM.Prepared, loads: Sequence[LD.Load], pv_kwp: float, battery_kwh: float,
                           cfg: SM.SimConfig) -> SM.Interval:
    """Energy a clinic system delivers to `loads` in a year when it runs them first (no grid), for cost per kWh."""
    _, prof = LD.priority_profile(list(loads))
    off = replace(pp, grid=np.zeros_like(pp.grid))
    res = SM.simulate_clinic(off.grid, off.pv_l, np.array([pv_kwp]), np.array([battery_kwh]), prof, cfg.battery,
                             burn_in_h=SM.BURN_IN_H)
    return SM.Interval.of(res["offgrid_kwh"][0])


def trace(lat: float, lon: float, bands, hours: float, start: int, mode: str, kw: float, pv_kwp: float,
          battery_kwh: float, days: int, cfg: SM.SimConfig, pad_h: int = 12,
          array_ratio: float = C.SOLAR_BH_ARRAY_KWP_PER_KW.value) -> dict:
    """Hourly trace across one lane's outage window for a water or cold site (the 3D night), with the plan's system.

    Lane: the draw whose hours kept with the plan are closest to the median over draws (as api.outage_api.trace)."""
    B = SM.BURN_IN_H
    pp = SM.prepare(lat, lon, bands, cfg)
    T = pp.grid.shape[1] - B
    mask, start_day = OU.window_mask(pp.n_lanes, T, days, cfg.seed)
    po = OU.apply_outage(pp, mask) if pp.known else pp
    load = LD.Load("site", "critical site load", 1, kw * 1000.0, float(min(hours, 24.0)), 1, int(start),
                   source="brief-13 site archetype")
    _, prof = LD.priority_profile([load])
    hod = np.arange(T) % 24
    need = (load.hourly_kw()[hod] > 0)[None, :]
    base = _base(po, mode, array_ratio)  # share of the load served without the new system (scale-free)
    res = SM.simulate_clinic(po.grid, po.pv_l, np.array([pv_kwp]), np.array([battery_kwh]), prof, cfg.battery,
                             burn_in_h=B, return_served=True)
    sv = res["served_all"][0] >= 1
    kept = (np.maximum(sv, base) * need * mask).sum(axis=1)
    med = float(np.median(kept))
    lane = int(np.argmin(np.abs(kept - med)))
    one = SM.simulate_clinic(po.grid[lane:lane + 1], po.pv_l[lane:lane + 1], np.array([pv_kwp]),
                             np.array([battery_kwh]), prof, cfg.battery, trace_lane=0, burn_in_h=B)
    soc, cap = one["soc_trace"][0], float(one["cap"][0])
    s0 = max(0, int(start_day[lane]) * 24 - pad_h)
    s1 = min(T, (int(start_day[lane]) + days) * 24 + pad_h)
    hrs = np.arange(s0, s1)
    grid = po.grid[lane, B:]
    pv1 = po.pv_l[lane, B:]
    out = {
        "days": days, "hour_index": [int(h) for h in hrs], "hour": [int(h % 24) for h in hrs],
        "in_outage": [bool(mask[lane, h]) for h in hrs], "grid_on": [bool(grid[h]) for h in hrs],
        "solar_kw": [round(float(pv_kwp * pv1[h]), 3) for h in hrs],
        "load_kw": [round(float(load.hourly_kw()[h % 24]), 3) for h in hrs],
        "battery_soc": [round(float(soc[h]) / cap, 4) if cap > 0 else 0.0 for h in hrs],
        "needed": [bool(need[0, h]) for h in hrs],
        "served_with": [None if not need[0, h] else round(float(max(sv[lane, h], base[lane, h])), 3) for h in hrs],
        "served_today": [None if not need[0, h] else round(float(base[lane, h]), 3) for h in hrs],
        "pv_kwp": pv_kwp, "battery_kwh": battery_kwh, "kw": kw, "mode": mode, "hours_kept_median": med,
        "system": {"pv_kwp": pv_kwp, "battery_kwh": battery_kwh,
                   "label": "the plan's system for this site (as in /api/city/{city}/sites)"},
        "draw": {"lane": lane, "n_lanes": int(pp.n_lanes), "lane_hours_kept": float(kept[lane]),
                 "median_hours_kept": med, "window_start_day": int(start_day[lane]), "pad_h": pad_h,
                 "rule": "the draw whose hours kept with the plan are closest to the median over draws; window placed "
                         "by engine.outage.window_mask (seed + 1000 + days)"},
        "served_rule": "served_with and served_today are the share of the load served that hour (1 = fully); a solar "
                       "borehole's existing array serves a share in daylight",
        "note": "one simulated outage (modelled supply, NASA POWER weather), not a measurement",
    }
    if mode == "solar_direct":
        out["existing_array_kw"] = [round(float(array_ratio * kw * pv1[h]), 3) for h in hrs]
    return out
