"""Sizing: the cheapest system meeting a target, the cost curve, and the knee.

Two systems, sized separately (two-system rule):
- Fridge system: the cheapest usable PQS solar direct-drive model whose fridge is held at 2 to 8 degC on at
  least `target` of days at the pessimistic end (5th percentile). Models without a printed price are listed
  but never chosen as "cheapest".
- Clinic system: PV kWp with battery at SEforALL's 7.2 kWh per kWp (DERIVED, p.11), searched over a
  geometric grid around the load's energy need, so the curve is one-dimensional and every point is priced by
  the verified $/Wp. Target: the critical loads (priority <= `priority`) fully served on at least `target` of
  days at the pessimistic end. The knee is where extra spend stops buying reliability (Kneedle).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np

from . import constants as C
from . import econ as E
from . import fridge as F
from . import loads as LD
from . import sim as SM


@dataclass
class CurvePoint:
    pv_kwp: float
    battery_kwh: float
    capex_usd: E.Range
    uptime: SM.Interval


@dataclass
class ClinicSizing:
    target: float
    priority: int
    target_met: bool
    chosen: CurvePoint
    knee: CurvePoint
    curve: list[CurvePoint]
    daily_load_kwh: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FridgeOption:
    code: str
    name: str
    array_kwp: float
    uptime: SM.Interval
    capex_usd: E.Range | None
    meets_target: bool


@dataclass
class FridgeSizing:
    target: float
    target_met: bool
    chosen: FridgeOption
    options: list[FridgeOption]

    def to_dict(self) -> dict:
        return asdict(self)


def knee_index(cost: np.ndarray, reliability: np.ndarray) -> int:
    """Kneedle: the point of a rising, flattening curve furthest above the chord from first to last point."""
    x = np.asarray(cost, float)
    y = np.asarray(reliability, float)
    if x.size < 3 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return int(np.argmax(y >= y.max() - 1e-12))
    xn = (x - x.min()) / np.ptp(x)
    yn = (y - y.min()) / np.ptp(y)
    return int(np.argmax(yn - xn))


def default_kwp_grid(daily_kwh: float, annual_yield_kwh_kwp: float, n: int = 16) -> np.ndarray:
    base = daily_kwh / max(annual_yield_kwh_kwp / 365.0, 1e-6)
    g = np.round(base * np.geomspace(0.3, 4.0, n), 2)
    return np.unique(np.maximum(g, 0.05))


def size_clinic(lat: float, lon: float, bands, loads: Sequence[LD.Load], target: float = 0.99, priority: int = 1,
                kwp_grid: Sequence[float] | None = None, ratio: float = C.BATTERY_KWH_PER_KWP.value,
                cfg: SM.SimConfig = SM.SimConfig(), prepared: SM.Prepared | None = None) -> ClinicSizing:
    pp = prepared or SM.prepare(lat, lon, bands, cfg)
    loads = list(loads)
    prio, prof = LD.priority_profile(loads)
    idx = np.where(prio <= priority)[0]
    if idx.size == 0:
        raise ValueError("no loads at or above the requested priority")
    pi = int(idx[-1])
    daily = LD.daily_kwh([ld for ld in loads if ld.priority <= priority])
    y = float(pp.pv_l[:, SM.BURN_IN_H:].sum(axis=1).mean())
    kwp = np.asarray(kwp_grid if kwp_grid is not None else default_kwp_grid(daily, y), dtype=float)
    kwh = kwp * ratio
    res = SM.simulate_clinic(pp.grid, pp.pv_l, kwp, kwh, prof, cfg.battery, burn_in_h=SM.BURN_IN_H)
    share = res["days_ok"][:, :, pi] / res["n_days"]  # (S, L)
    curve = [CurvePoint(float(a), float(b), E.clinic_capex_usd(a, b), SM.Interval.of(share[i]))
             for i, (a, b) in enumerate(zip(kwp, kwh))]
    lo = np.array([c.uptime.lo for c in curve])
    ok = np.where(lo >= target)[0]
    met = ok.size > 0
    chosen = curve[int(ok[0])] if met else curve[int(np.argmax(lo))]
    k = knee_index(np.array([c.capex_usd.point for c in curve]), lo)
    return ClinicSizing(target, priority, met, chosen, curve[k], curve, daily)


def size_fridge(lat: float, lon: float, target: float = 0.99, cfg: SM.SimConfig = SM.SimConfig(),
                prepared: SM.Prepared | None = None) -> FridgeSizing:
    pp = prepared or SM.prepare(lat, lon, SM.SP.OFFGRID, cfg)
    B = SM.BURN_IN_H
    opts = []
    for m in F.CATALOGUE.values():
        if m.kind != "sdd" or not m.usable or m.energy_kwh_24h is None or m.holdover_h is None:
            continue
        arr = F.sdd_array_kwp(m, pp.pr)
        ok = F.simulate_sdd(arr * pp.pv_l, m.energy_kwh_24h, pp.leak_l, pp.k * m.holdover_h)[:, B:]
        up = SM.Interval.of(F.days_held(ok).mean(axis=1))
        opts.append(FridgeOption(m.code, m.name, float(arr), up, E.fridge_capex_usd(m), up.lo >= target))
    priced = sorted([o for o in opts if o.capex_usd is not None and o.meets_target], key=lambda o: o.capex_usd.point)
    if priced:
        return FridgeSizing(target, True, priced[0], opts)
    best = max(opts, key=lambda o: o.uptime.lo)
    return FridgeSizing(target, best.meets_target, best, opts)
