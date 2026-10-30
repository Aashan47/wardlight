"""Hourly simulation: today (grid only) versus with the two systems, over weather years and supply draws.

Two-system rule (PQS E003/PV01.3 p.4, SOURCES-VERIFIED.md 1a): the vaccine fridge is always on its own
dedicated PQS solar direct-drive system; the clinic system (PV plus battery) carries lights, oxygen and the
delivery room and never the vaccine fridge.

Lanes: n_draws supply draws x n_years weather years; each lane is one simulated year (8760 h). To avoid
a full-reserve start flattering the first days, each lane first runs a 7-day burn-in (the last week of its
own year), which is discarded. Outputs are shares of days, with an interval: point = median over lanes,
lo = 5th percentile, hi = 95th percentile. "Pessimistic end" means lo.

Load shedding (clinic system): priority 1 may use the whole usable battery; lower priorities may only draw
the battery above SHED_RESERVE of usable capacity (an ASSUMPTION, editable), so fans and pumps cannot drain
the battery that the delivery room needs at night.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from functools import lru_cache

import numpy as np

from . import constants as C
from . import fridge as F
from . import loads as LD
from . import solar as S
from . import supply as SP


@dataclass(frozen=True)
class BatteryParams:
    usable_fraction: float = C.BATTERY_USABLE_FRACTION.value
    round_trip_eff: float = C.BATTERY_ROUND_TRIP_EFF.value
    grid_charge_c_rate: float = C.BATTERY_GRID_CHARGE_C_RATE.value
    grid_charging: bool = True
    shed_reserve: float = C.SHED_RESERVE.value  # lower priorities keep this share of usable battery for priority 1


@dataclass(frozen=True)
class ClinicSystem:
    pv_kwp: float
    battery_kwh: float


@dataclass(frozen=True)
class SimConfig:
    n_draws: int = 48
    seed: int = 20261030
    years: tuple[int, ...] = S.YEARS
    pv: S.PVParams = field(default_factory=S.PVParams)
    thermal: F.ThermalParams = field(default_factory=F.ThermalParams)
    battery: BatteryParams = field(default_factory=BatteryParams)
    shortfall: SP.ShortfallParams = field(default_factory=lambda: SP.PRIOR)
    timing: SP.OutageTiming = field(default_factory=SP.OutageTiming)
    fridge_today: str = F.DEFAULT_TODAY
    fridge_with: str = "E003-040e"
    critical_priority: int = LD.CRITICAL_PRIORITY


@dataclass(frozen=True)
class Interval:
    point: float  # median over lanes
    lo: float  # 5th percentile
    hi: float  # 95th percentile

    @staticmethod
    def of(x: np.ndarray, q: tuple[float, float] = (0.05, 0.95)) -> Interval:
        x = np.asarray(x, dtype=float)
        return Interval(float(np.median(x)), float(np.quantile(x, q[0])), float(np.quantile(x, q[1])))


@dataclass
class SimResult:
    fridge_today: Interval | None
    fridge_with: Interval
    critical_today: Interval | None
    critical_with: Interval | None
    per_priority_with: dict[int, Interval]
    clinic_offgrid_kwh_yr: Interval | None
    fridge_offgrid_kwh_yr: Interval | None
    sdd_array_kwp: float
    supply_calibrated: bool
    supply_known: bool
    weather_point: tuple[int, int]
    n_lanes: int
    trace: dict | None
    runtime_s: float
    fridge_today_pqs: Interval | None = None
    fridge_with_technical: Interval | None = None
    fridge_today_technical: Interval | None = None
    labels: dict = field(default_factory=lambda: {
        "supply": "modelled from the NERC band promise; promised, not measured",
        "fridge": "PQS holdover treated as an upper bound (measured to +10 degC)",
        "fridge_today": "scenario (b): a domestic or non-PQS fridge (4 h, range 1.5 to 6 h, NIST lab test); "
                        "fridge_today_pqs is scenario (a), a PQS ice-lined fridge; scenario (c), no fridge, "
                        "is not modelled",
        "availability": "every fridge figure is multiplied by an availability scenario value (0.90 to 0.99, "
                        "not sourced); technical figures assume no breakdowns",
    })

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- inputs


@lru_cache(maxsize=256)
def _pv_and_leak(point: tuple[int, int], years: tuple[int, ...], pv: S.PVParams, th: F.ThermalParams):
    w = S.load_weather(point[0], point[1], years)
    pv_kwh = S.weather_pv(w, pv).astype(np.float32)
    leak = F.leak_rate(w.t2m_c, th).astype(np.float32)
    irr_kwh_m2 = w.ghi_w_m2.sum() / 1000.0
    pr = float(pv_kwh.sum() / irr_kwh_m2) if irr_kwh_m2 > 0 else 1.0 - pv.system_loss
    return pv_kwh, leak, pr


BURN_IN_H = 7 * 24


def _with_burn_in(a: np.ndarray) -> np.ndarray:
    """Prepend the last week of each lane (wrap-around) as burn-in; drop BURN_IN_H outputs afterwards."""
    return np.concatenate([a[:, -BURN_IN_H:], a], axis=1)


def lane_inputs(lat: float, lon: float, cfg: SimConfig):
    """Per-lane PV (kWh/kWp) and leak, both with burn-in prepended, shape (L, 168 + 8760)."""
    point = S.nearest_point(lat, lon)
    pv_kwh, leak, pr = _pv_and_leak(point, tuple(cfg.years), cfg.pv, cfg.thermal)
    ny = pv_kwh.shape[0]
    n_lanes = cfg.n_draws * ny
    year_idx = np.arange(n_lanes) % ny
    return point, _with_burn_in(pv_kwh[year_idx]), _with_burn_in(leak[year_idx]), pr, n_lanes


@dataclass(frozen=True)
class Prepared:
    point: tuple[int, int]
    pv_l: np.ndarray  # (L, B + T) kWh per kWp
    leak_l: np.ndarray  # (L, B + T)
    pr: float  # site PV performance ratio (AC kWh / irradiation kWh/m2 per kWp)
    n_lanes: int
    grid: np.ndarray  # (L, B + T) bool
    k: np.ndarray  # (L,) holdover-to-8 degC fraction
    known: bool
    h_dom: np.ndarray  # (L,) domestic-fridge hours at 2 to 8 degC without power (NIST range)
    avail: np.ndarray  # (L,) share of days the fridge is in working order (scenario)
    soil: np.ndarray  # (L,) SDD array soiling factor (scenario)


def prepare(lat: float, lon: float, bands, cfg: SimConfig) -> Prepared:
    """Draw everything random for one facility once, so today, with-system and sizing share the same draws."""
    rng = np.random.default_rng(cfg.seed)
    point, pv_l, leak_l, pr, n_lanes = lane_inputs(lat, lon, cfg)
    T = pv_l.shape[1] - BURN_IN_H
    known = bands is not None
    grid = _with_burn_in(SP.sample_supply(bands if known else SP.OFFGRID, n_lanes, T // 24, rng, cfg.shortfall,
                                          cfg.timing))
    k = F.sample_k(n_lanes, rng, cfg.thermal)
    # drawn after the draws above, so those stay identical to earlier runs with the same seed
    h_dom = rng.uniform(C.DOMESTIC_HOLDOVER_H.lo, C.DOMESTIC_HOLDOVER_H.hi, n_lanes)
    avail = rng.uniform(C.EQUIPMENT_AVAILABILITY.lo, C.EQUIPMENT_AVAILABILITY.hi, n_lanes)
    soil = rng.uniform(C.SDD_SOILING_FACTOR.lo, C.SDD_SOILING_FACTOR.hi, n_lanes)
    return Prepared(point, pv_l, leak_l, pr, n_lanes, grid, k, known, h_dom, avail, soil)


# ---------------------------------------------------------------- vaccine fridge scenarios


@dataclass(frozen=True)
class FridgeUptime:
    """Share of days at 2 to 8 degC. `technical`: the equipment never breaks down. `available`: technical x the
    per-lane availability factor (scenario value), which is what the product reports."""

    technical: Interval
    available: Interval


def _uptime(ok: np.ndarray, avail: np.ndarray) -> FridgeUptime:
    share = F.days_held(ok).mean(axis=1)
    return FridgeUptime(Interval.of(share), Interval.of(share * avail))


def ilr_on_grid(pp: Prepared, code: str, th: F.ThermalParams = F.ThermalParams()):
    """Scenario (a) today and fix (i): a PQS mains ice-lined fridge on the facility's grid. None if supply unknown."""
    if not pp.known:
        return None, None
    m = F.CATALOGUE[code]
    ok = F.simulate_ice_lined(pp.grid, pp.leak_l, pp.k * m.holdover_h, th)[:, BURN_IN_H:]
    return _uptime(ok, pp.avail), ok


def domestic_on_grid(pp: Prepared):
    """Scenario (b) today: a domestic or non-PQS fridge on the grid. Fixed holdover hours (NIST range, no ambient
    scaling), full reserve restored within DOMESTIC_RECOVERY_H powered hours. None if supply unknown."""
    if not pp.known:
        return None, None
    th = F.ThermalParams(recharge_h_per_h=C.DOMESTIC_HOLDOVER_H.hi / C.DOMESTIC_RECOVERY_H.value,
                         ambient_scaling=False)
    leak = np.ones(pp.grid.shape[1], dtype=np.float32)
    ok = F.simulate_ice_lined(pp.grid, leak, pp.h_dom, th)[:, BURN_IN_H:]
    return _uptime(ok, pp.avail), ok


def sdd_fridge(pp: Prepared, code: str):
    """Fix (ii): a PQS solar direct-drive fridge on its own PQS-minimum array, with the soiling scenario."""
    m = F.CATALOGUE[code]
    arr = F.sdd_array_kwp(m, pp.pr)
    pv = arr * pp.pv_l * pp.soil[:, None]
    ok = F.simulate_sdd(pv, m.energy_kwh_24h, pp.leak_l, pp.k * m.holdover_h)[:, BURN_IN_H:]  # type: ignore[arg-type]
    return _uptime(ok, pp.avail), ok, float(arr)


# ---------------------------------------------------------------- clinic system loop


def simulate_clinic(grid: np.ndarray, pv_per_kwp: np.ndarray, pv_kwp: np.ndarray, battery_kwh: np.ndarray,
                    prof: np.ndarray, bp: BatteryParams = BatteryParams(), trace_lane: int | None = None,
                    burn_in_h: int = 0, return_served: bool = False) -> dict:
    """Battery dispatch in priority order, vectorised over S system sizes and L lanes.

    grid (L, T) bool; pv_per_kwp (L, T) kWh/kWp; pv_kwp, battery_kwh (S,); prof (P, 24) kW per priority.
    Returns days_ok (S, L, P) counts of days on which every priority up to p was fully served,
    offgrid_kwh (S, L) energy served from PV and battery while the grid was off, n_days, and an optional
    trace (S, T) of state of charge for one lane.
    """
    L, T = grid.shape
    if burn_in_h % 24:
        raise ValueError("burn_in_h must be whole days")
    n_days = (T - burn_in_h) // 24
    pv_kwp = np.asarray(pv_kwp, dtype=np.float32)[:, None]
    cap = (np.asarray(battery_kwh, dtype=np.float32) * bp.usable_fraction)[:, None]  # (S,1)
    Sn = cap.shape[0]
    P = prof.shape[0]
    cum = np.cumsum(prof, axis=0).astype(np.float32)  # (P, 24) energy for serving priorities 1..p in an hour
    eta = float(np.sqrt(bp.round_trip_eff))
    grid_chg = (np.asarray(battery_kwh, dtype=np.float32) * bp.grid_charge_c_rate)[:, None] if bp.grid_charging \
        else np.zeros((Sn, 1), np.float32)
    soc = np.broadcast_to(cap, (Sn, L)).astype(np.float32).copy()
    day_ok = np.ones((Sn, L, P), dtype=bool)
    days_ok = np.zeros((Sn, L, P), dtype=np.int32)
    offgrid = np.zeros((Sn, L), dtype=np.float32)
    p_idx = np.arange(P)
    res_frac = np.where(p_idx == 0, 0.0, bp.shed_reserve).astype(np.float32)
    reserve = cap[:, :, None] * res_frac[None, None, :]  # (S, 1, P)
    soc_trace = np.empty((Sn, T - burn_in_h), np.float32) if trace_lane is not None else None
    served_all = np.empty((Sn, L, T - burn_in_h), np.int8) if return_served else None
    served_trace = np.empty((Sn, T - burn_in_h), np.int8) if trace_lane is not None else None
    for t in range(T):
        h = t % 24
        counting = t >= burn_in_h
        g = grid[:, t]  # (L,)
        pv = pv_kwp * pv_per_kwp[:, t]  # (S, L)
        c = cum[:, h]
        avail = pv[..., None] + np.maximum(soc[..., None] - reserve, 0.0) * eta  # (S, L, P)
        fits = np.logical_and.accumulate(c[None, None, :] <= avail + 1e-6, axis=2)
        n_served = fits.sum(axis=2)  # (S, L) prefix count
        used = np.where(n_served > 0, c[np.maximum(n_served - 1, 0)], 0.0)
        draw = np.maximum(used - pv, 0.0) / eta
        surplus = np.maximum(pv - used, 0.0) * eta
        soc_off = np.clip(soc - draw + surplus, 0.0, cap)
        soc_on = np.minimum(soc + pv * eta + grid_chg * eta, cap)
        soc = np.where(g, soc_on, soc_off)
        n_eff = np.where(g, P, n_served)
        if not counting:
            continue
        offgrid += np.where(g, 0.0, used)
        day_ok &= p_idx[None, None, :] < n_eff[..., None]  # see note below
        if soc_trace is not None:
            soc_trace[:, t - burn_in_h] = soc[:, trace_lane]
            served_trace[:, t - burn_in_h] = n_eff[:, trace_lane]
        if served_all is not None:
            served_all[:, :, t - burn_in_h] = n_eff
        if h == 23:
            days_ok += day_ok
            day_ok[:] = True
    return {"days_ok": days_ok, "n_days": n_days, "offgrid_kwh": offgrid, "soc_trace": soc_trace,
            "served_all": served_all,
            "served_trace": served_trace, "cap": cap[:, 0]}


# Note on the day test: priorities are served as a prefix (1, then 2, ...), so "served up to p this hour" is
# n_eff > p. A priority with no demand that hour adds nothing to the cumulative energy, so it can never be the
# one that fails; zero-demand hours therefore pass automatically.


def _critical_index(prio: np.ndarray, critical_priority: int) -> int | None:
    idx = np.where(prio <= critical_priority)[0]
    return int(idx[-1]) if idx.size else None


def critical_today(grid: np.ndarray, prof: np.ndarray, crit_idx: int | None) -> np.ndarray | None:
    """Grid only: a day is held if the grid is on in every hour with critical demand. (L, days) bool."""
    if crit_idx is None:
        return None
    need = (prof[: crit_idx + 1] > 0).any(axis=0)  # (24,)
    L, T = grid.shape
    g = grid[:, : (T // 24) * 24].reshape(L, T // 24, 24)
    return (g | ~need).all(axis=2)


# ---------------------------------------------------------------- facility simulation


def simulate_facility(lat: float, lon: float, bands: Mapping[str, float] | str | None,
                      loads: Sequence[LD.Load] | None = LD.SEFORALL_TYPE2_PHC,
                      clinic: ClinicSystem | None = None, cfg: SimConfig = SimConfig(),
                      trace: bool = False, prepared: Prepared | None = None) -> SimResult:
    """Run today and with-system for one facility.

    bands: {band: weight}, a band letter, 'OFFGRID', or None when supply is unknown (tier d refused): then
    the today figures are None and the clinic system is simulated as if off-grid (conservative, labelled).
    """
    t0 = time.perf_counter()
    pp = prepared or prepare(lat, lon, bands, cfg)
    point, pv_l, n_lanes, grid, known = pp.point, pp.pv_l, pp.n_lanes, pp.grid, pp.known
    B = BURN_IN_H

    # vaccine fridge, today: scenario (b) domestic or non-PQS fridge (headline) and scenario (a) PQS ice-lined,
    # both on grid alone. Scenario (c), no fridge (vaccines brought by an outreach carrier), is stated, not modelled.
    dom, ok_today = domestic_on_grid(pp)
    pqs, _ = ilr_on_grid(pp, cfg.fridge_today, cfg.thermal)
    fridge_today = dom.available if dom else None
    fridge_today_pqs = pqs.available if pqs else None
    ft = F.CATALOGUE[cfg.fridge_today]
    fridge_off_kwh = None
    if known:
        off_h = (~grid[:, B:]).sum(axis=1)
        fridge_off_kwh = Interval.of(off_h * (ft.energy_kwh_24h or 0) / 24.0)

    # vaccine fridge, with: dedicated PQS SDD on its own PQS-minimum array (no grid, no other loads)
    sdd, ok_with, arr = sdd_fridge(pp, cfg.fridge_with)
    fridge_with = sdd.available

    crit_t = crit_w = clinic_off = None
    per_p: dict[int, Interval] = {}
    trace_d = None
    if loads:
        prio, prof = LD.priority_profile(list(loads))
        ci = _critical_index(prio, cfg.critical_priority)
        if known and ci is not None:
            ct = critical_today(grid[:, B:], prof, ci)
            crit_t = Interval.of(ct.mean(axis=1))  # type: ignore[union-attr]
        if clinic is not None:
            res = simulate_clinic(grid, pv_l, np.array([clinic.pv_kwp]), np.array([clinic.battery_kwh]), prof,
                                  cfg.battery, trace_lane=0 if trace else None, burn_in_h=B)
            share = res["days_ok"][0] / res["n_days"]  # (L, P)
            per_p = {int(p): Interval.of(share[:, i]) for i, p in enumerate(prio)}
            if ci is not None:
                crit_w = per_p[int(prio[ci])]
            clinic_off = Interval.of(res["offgrid_kwh"][0])
            if trace:
                trace_d = _trace(grid[:, B:], pv_l[:, B:], arr, clinic, res, ok_today if known else None, ok_with,
                                 prof, prio)
    return SimResult(fridge_today, fridge_with, crit_t, crit_w, per_p, clinic_off, fridge_off_kwh, float(arr),
                     cfg.shortfall.calibrated, known, point, n_lanes, trace_d, time.perf_counter() - t0,
                     fridge_today_pqs=fridge_today_pqs, fridge_with_technical=sdd.technical,
                     fridge_today_technical=dom.technical if dom else None)


def _trace(grid, pv_l, arr, clinic, res, ok_today, ok_with, prof, prio, lane: int = 0) -> dict:
    """24-hour ring data for one real simulated day: the first day lane 0's fridge fails today, else day 0."""
    day = 0
    if ok_today is not None:
        bad = np.where(~F.days_held(ok_today[lane : lane + 1])[0])[0]
        if bad.size:
            day = int(bad[0])
    s = slice(day * 24, day * 24 + 24)
    return {
        "lane": lane, "day_of_year": day,
        "grid_on": grid[lane, s].astype(int).tolist(),
        "pv_kw_clinic": (clinic.pv_kwp * pv_l[lane, s]).round(3).tolist(),
        "pv_kw_fridge": (arr * pv_l[lane, s]).round(4).tolist(),
        "battery_soc_kwh": res["soc_trace"][0, s].round(2).tolist(),
        "battery_usable_kwh": float(res["cap"][0]),
        "priorities_served": res["served_trace"][0, s].astype(int).tolist(),
        "priorities": prio.tolist(),
        "load_kw_by_priority": prof.round(3).tolist(),
        "fridge_today_ok": None if ok_today is None else ok_today[lane, s].astype(int).tolist(),
        "fridge_with_ok": ok_with[lane, s].astype(int).tolist(),
        "note": "one real simulated day (modelled supply draw, NASA POWER weather), not a measurement",
    }


def what_if(lat: float, lon: float, bands, loads: Sequence[LD.Load] | None, pv_kwp: float, battery_kwh: float,
            cfg: SimConfig = SimConfig(n_draws=32)) -> SimResult:
    """The API's POST /simulate: one facility, one user-chosen clinic system, with the ring trace."""
    return simulate_facility(lat, lon, bands, loads, ClinicSystem(pv_kwp, battery_kwh), cfg, trace=True)
