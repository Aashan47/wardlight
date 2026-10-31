"""Line-outage scenario (brief 13, "Hours of critical service maintained during a line outage, and diesel litres
avoided"; also useful for brief 16).

A grid-down window of N days is placed inside each lane's normal band supply: the grid is forced off for those
hours (the OFFGRID path, no new physics) and is unchanged before and after. The window starts on a day drawn per
lane, uniformly over the simulated year after the 7-day burn-in, from its own random stream (seed + 1000 + N), so
the existing draws and results are untouched. Days 3, 7, 14, 40 (the 2024 event) and 60 (brief 13's "two months")
are the defaults.

Critical services: each priority-1 clinic load (delivery room, oxygen, interior lights) and the vaccine fridge.
"Service-hours maintained" = hours in the window in which the service was running while it was needed (a load is
needed in the hours its daily window covers; the fridge every hour). Reported per service and summed, as a median
with 5th to 95th percentiles over lanes. Fridge hours are technical (equipment working); the annual availability
scenario is not applied inside a single window.

Today: no solar. Scenario (b) domestic fridge is the headline, (a) PQS ice-lined alongside; clinic loads run only
on grid. Optional labelled scenario "generator": a generator covers every critical service through the window,
burning (priority-1 energy + the mains fridge's energy) x GEN_L_PER_KWH (clinic-set curve, DERIVED from Cummins sheets:
0.40 to 0.73 L/kWh, point 0.55).
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

DEFAULT_DAYS: tuple[int, ...] = (3, 7, 14, 40, 60)
# 40 days: the Damaturu to Maiduguri 330kV line was down for about 40 days (TCN, quoted by Nairametrics and
# Arise News; research-raw BRIEF13-CITY.md, event A)
# 60 days: brief 13 starter question 1, "If the line goes down tomorrow for two months, what must keep running?"
ORFIX_SIZED_FOR: tuple[int, ...] = (7, 40)
ORFIX_EVAL_DAYS: tuple[int, ...] = (14, 40, 60)  # the 7-day outage-ready system, also run through these windows


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


# ---------------------------------------------------------------- outage-ready fix (brief 13)

OR_DAYS = 7
OR_TARGET = 0.95
ORFIX_LABEL = {
    "i+c": "PQS ice-lined fridge on the grid, plus a clinic system sized for the outage",
    "ii+c": "PQS solar direct-drive fridge, plus a clinic system sized for the outage",
    "none": "no listed size meets the outage target; the largest size is shown",
}


@dataclass
class OutageReadyFix:
    days: int
    target: float
    category: str
    label: str
    fridge_code: str
    fridge_kind: str
    fridge_share_lo: float
    pv_kwp: float
    battery_kwh: float
    crit_share: SM.Interval  # share of priority-1 load-hours kept in the window, over lanes
    target_met: bool
    capex_usd: E.Range
    capex_ngn: E.Range
    monthly_cost_ngn: E.Range
    result: OutageResult
    curve: list[tuple[float, float, float]]  # (pv_kwp, battery_kwh, crit share at the 5th percentile)

    def to_dict(self) -> dict:
        return asdict(self)


def _crit_share_by_size(po: SM.Prepared, mask: np.ndarray, crit: Sequence[LD.Load], kwp: np.ndarray,
                        kwh: np.ndarray, cfg: SM.SimConfig) -> np.ndarray:
    """(S, L) share of the critical loads' needed hours in the window that were kept, for each size."""
    B = SM.BURN_IN_H
    _, prof = LD.priority_profile(list(crit))
    res = SM.simulate_clinic(po.grid, po.pv_l, kwp, kwh, prof, cfg.battery, burn_in_h=B, return_served=True)
    grid = po.grid[:, B:]
    T = grid.shape[1]
    hod = np.arange(T) % 24
    served = res["served_all"] >= prof.shape[0]  # every priority in `crit` served that hour
    kept = np.zeros(served.shape[:2])
    needed = 0.0
    for ld in crit:
        need = (ld.hourly_kw()[hod] > 0)[None, :] & mask  # (L, T)
        kept += ((served | grid[None]) & need[None]).sum(axis=2)
        needed += float(need[0].sum())
    return kept / needed if needed > 0 else np.ones(served.shape[:2])


def size_outage_ready(pp: SM.Prepared, crit_loads: Sequence[LD.Load], offgrid: bool,
                      cfg: SM.SimConfig = SM.SimConfig(), days: int = OR_DAYS, target: float = OR_TARGET,
                      kwp_grid: Sequence[float] | None = None,
                      ratio: float = C.BATTERY_KWH_PER_KWP.value) -> OutageReadyFix:
    """Cheapest fridge and smallest clinic system keeping critical services through an N-day outage.

    Fridge: the cheapest priced PQS unit whose fridge is held for at least `target` of the window's hours at the
    5th percentile (an ice-lined unit on the grid only where supply is known and not off-grid). Clinic system: PV
    with battery at 7.2 kWh/kWp, the smallest size keeping at least `target` of the critical loads' needed hours
    at the 5th percentile. Two systems, never one battery for both (PQS PV01.3)."""
    from . import coldchain as CC

    B = SM.BURN_IN_H
    T = pp.grid.shape[1] - B
    mask, _ = window_mask(pp.n_lanes, T, days, cfg.seed)
    po = apply_outage(pp, mask) if pp.known else pp
    win = float(mask[0].sum())
    all_h = np.ones_like(mask)
    fr = []
    if pp.known and not offgrid:
        for code in CC.ILR_FIX_MODELS:
            _, ok = SM.ilr_on_grid(po, code, cfg.thermal)
            fr.append(("i", code, float(np.quantile(_in_window(ok, all_h, mask) / win, 0.05))))
    for code in CC.SDD_FIX_MODELS:
        _, ok, _ = SM.sdd_fridge(po, code)
        fr.append(("ii", code, float(np.quantile(_in_window(ok, all_h, mask) / win, 0.05))))
    price = {c: E.fridge_capex_usd(c).point for _, c, _ in fr}
    passing = sorted([f for f in fr if f[2] >= target], key=lambda f: price[f[1]])
    f_kind, f_code, f_lo = passing[0] if passing else max(fr, key=lambda f: (f[2], -price[f[1]]))

    crit = [ld for ld in crit_loads if ld.priority <= cfg.critical_priority] or list(crit_loads)
    daily = LD.daily_kwh(crit)
    y = float(pp.pv_l[:, B:].sum(axis=1).mean())
    base = daily / max(y / 365.0, 1e-6)
    kwp = np.unique(np.maximum(np.round(np.asarray(kwp_grid, float) if kwp_grid is not None
                                        else base * np.geomspace(0.3, 6.0, 18), 2), 0.05))
    kwh = kwp * ratio
    share = _crit_share_by_size(po, mask, crit, kwp, kwh, cfg)
    lo = np.quantile(share, 0.05, axis=1)
    ok = np.where(lo >= target)[0]
    if kwp_grid is None and ok.size and ok[0] > 0:
        # refine between the last failing and the first passing size (coarse steps are about 19%)
        fine = np.unique(np.round(np.linspace(kwp[ok[0] - 1], kwp[ok[0]], 8)[1:-1], 2))
        f_share = _crit_share_by_size(po, mask, crit, fine, fine * ratio, cfg)
        kwp = np.concatenate([kwp, fine])
        kwh = kwp * ratio
        share = np.concatenate([share, f_share])
        order = np.argsort(kwp, kind="mergesort")
        kwp, kwh, share = kwp[order], kwh[order], share[order]
        lo = np.quantile(share, 0.05, axis=1)
        ok = np.where(lo >= target)[0]
    i = int(ok[0]) if ok.size else int(np.argmax(lo))
    met = bool(ok.size) and f_lo >= target
    category = ("i+c" if f_kind == "i" else "ii+c") if met else "none"
    clinic = SM.ClinicSystem(float(kwp[i]), float(kwh[i]))
    res = simulate_outage(pp, days, crit, clinic, f_kind, f_code, cfg)
    cap = E.clinic_capex_usd(clinic.pv_kwp, clinic.battery_kwh) + E.fridge_capex_usd(f_code)
    monthly = E.monthly_cost_ngn(E.clinic_capex_usd(clinic.pv_kwp, clinic.battery_kwh)) + \
        CC.fix_monthly_cost_ngn(E.fridge_capex_usd(f_code))
    return OutageReadyFix(days, target, category, ORFIX_LABEL[category], f_code, f_kind, f_lo, clinic.pv_kwp,
                          clinic.battery_kwh, SM.Interval.of(share[i]), met, cap, E.to_ngn(cap), monthly, res,
                          [(float(a), float(b), float(c)) for a, b, c in zip(kwp, kwh, lo)])


def orfix_columns(o: OutageReadyFix, prefix: str = "orfix_") -> dict:
    r = o.result
    p = prefix
    row = {f"{p}days": o.days, f"{p}target": o.target, f"{p}category": o.category, f"{p}label": o.label,
           f"{p}fridge_code": o.fridge_code, f"{p}pv_kwp": o.pv_kwp, f"{p}battery_kwh": round(o.battery_kwh, 2),
           f"{p}target_met": o.target_met, f"{p}needed_h": r.needed_h, f"{p}share_kept": r.share_with,
           f"{p}crit_share_lo": o.crit_share.lo, f"{p}fridge_share_lo": o.fridge_share_lo}
    for name, v in (("capex_usd", o.capex_usd), ("capex_ngn", o.capex_ngn), ("monthly_cost_ngn", o.monthly_cost_ngn),
                    ("diesel_l_avoided", r.diesel_l_avoided)):
        row[f"{p}{name}"], row[f"{p}{name}_lo"], row[f"{p}{name}_hi"] = v.point, v.lo, v.hi
    row[f"{p}hours_kept"], row[f"{p}hours_kept_lo"], row[f"{p}hours_kept_hi"] = (
        r.with_system.point, r.with_system.lo, r.with_system.hi)
    return row


def orfix_eval_columns(r: OutageResult, prefix: str = "orfix_") -> dict:
    """The outage-ready system (sized for `prefix`'s days) run through a different window length."""
    p = f"{prefix}at{r.days}_"
    row = {f"{p}needed_h": r.needed_h, f"{p}share_kept": r.share_with}
    row[f"{p}hours_kept"], row[f"{p}hours_kept_lo"], row[f"{p}hours_kept_hi"] = (
        r.with_system.point, r.with_system.lo, r.with_system.hi)
    d = r.diesel_l_avoided
    row[f"{p}diesel_l_avoided"], row[f"{p}diesel_l_avoided_lo"], row[f"{p}diesel_l_avoided_hi"] = d.point, d.lo, d.hi
    return row


def orfix_prefix(sized_for: int) -> str:
    return "orfix_" if sized_for == OR_DAYS else f"orfix{sized_for}_"


MAIDUGURI = ("Borno", ("Maiduguri", "Jere"))


def aggregate_city(state: str = MAIDUGURI[0], lgas: Sequence[str] | None = MAIDUGURI[1],
                   results: pd.DataFrame | None = None, facilities: pd.DataFrame | None = None,
                   budget_ngn: float = float("inf"), days: int = OR_DAYS, sized_for: int | None = None) -> dict:
    """Per-city totals for the brief-13 view and the facilities ranked by critical service-hours kept per naira.

    Default city: Maiduguri (Maiduguri and Jere LGAs, Borno). `days` is the outage length; `sized_for` the
    outage the system was sized for (default: `days` when a system was sized for it, else the 7-day system run
    through the longer or shorter window). All LGAs of the state when `lgas` is None."""
    from . import paths
    from . import plan as PL

    results = results if results is not None else pd.read_parquet(paths.FACILITY_RESULTS)
    facilities = facilities if facilities is not None else pd.read_parquet(paths.FACILITIES)
    fac = facilities.drop_duplicates("unique_id")
    sel = fac[fac.state_standard.str.lower() == state.lower()]
    if lgas:
        sel = sel[sel.lga_standard.str.lower().isin([x.lower() for x in lgas])]
    keep = [c for c in ("unique_id", "facility_name", "facility_level", "lga_standard") if c in sel]
    df = results.merge(sel[keep], on="unique_id", how="inner")
    if df.empty:
        return {"state": state, "lgas": list(lgas or []), "facilities": 0, "by_level": {}, "ranked": df}
    if sized_for is None:
        sized_for = days if f"{orfix_prefix(days)}hours_kept" in df else OR_DAYS
    p = orfix_prefix(sized_for)
    w = p if sized_for == days else f"{p}at{days}_"
    df = df.assign(orfix_hours_kept=df[f"{w}hours_kept"], orfix_capex_ngn=df[f"{p}capex_ngn"])
    today = df[f"out{days}_hours_today"]
    needed = df[f"out{days}_needed_h"] if f"out{days}_needed_h" in df else df[f"{w}needed_h"]
    totals = {
        "state": state, "lgas": list(lgas or []), "outage_days": days, "system_sized_for_days": sized_for,
        "facilities": len(df),
        "by_level": df.facility_level.fillna("Unknown").replace("", "Unknown").value_counts().to_dict(),
        "service_hours_needed": float(needed.sum()), "service_hours_today": float(today.sum()),
        "service_hours_with_orfix": float(df.orfix_hours_kept.sum()),
        "diesel_l_avoided": {k: float(df[f"{w}diesel_l_avoided{s}"].sum()) for k, s in
                             (("point", ""), ("lo", "_lo"), ("hi", "_hi"))},
        "capex_ngn": {k: float(df[f"{p}capex_ngn{s}"].sum()) for k, s in (("point", ""), ("lo", "_lo"), ("hi", "_hi"))},
        "labels": {"supply": "modelled from the NERC band promise; outage window placed per simulated year",
                   "diesel": "clinic-set curve 0.40 to 0.73 L/kWh (point 0.55, DERIVED from Cummins C17/C22 D5 sheets); "
                             "fuel replaced where a generator would run",
                   "today": "no solar; domestic or non-PQS fridge scenario"},
    }
    totals["share_today"] = totals["service_hours_today"] / max(totals["service_hours_needed"], 1e-9)
    totals["share_with_orfix"] = totals["service_hours_with_orfix"] / max(totals["service_hours_needed"], 1e-9)
    totals["ranked"] = PL.rank(df, budget_ngn, metric="orfix_hours", outage_days=days)
    return totals


def t5_outage(sites: Sequence[tuple[float, float, object]] = ((9.0, 7.5, {"C": 1.0}), (9.0, 7.5, "OFFGRID"),
                                                             (6.0, 7.0, {"C": 1.0}), (12.0, 8.0, {"C": 1.0})),
              days: int = OR_DAYS, target: float = OR_TARGET, cfg: SM.SimConfig = SM.SimConfig()) -> list[dict]:
    """T5-style sanity for the outage-ready sizing: the full SEforALL Type 2 PHC load (every load treated as
    critical) and the priority-1 load alone, against SEforALL's 5 to 10 kWp and 36 to 72 kWh."""
    out = []
    full_cfg = replace(cfg, critical_priority=99)
    for lat, lon, bands in sites:
        pp = SM.prepare(lat, lon, bands, cfg)
        offgrid = bands == SP_OFFGRID
        full = size_outage_ready(pp, LD.SEFORALL_TYPE2_PHC, offgrid, full_cfg, days, target)
        crit = size_outage_ready(pp, LD.critical(), offgrid, cfg, days, target)
        out.append({"site": [lat, lon], "bands": bands, "days": days, "target": target,
                    "full_load_kwh_day": round(LD.daily_kwh(LD.SEFORALL_TYPE2_PHC), 3),
                    "full_kwp": full.pv_kwp, "full_kwh": round(full.battery_kwh, 1),
                    "full_inside_seforall": bool(5 <= full.pv_kwp <= 10), "full_target_met": full.target_met,
                    "critical_load_kwh_day": round(LD.daily_kwh(LD.critical()), 3),
                    "critical_kwp": crit.pv_kwp, "critical_kwh": round(crit.battery_kwh, 1)})
    return out


SP_OFFGRID = "OFFGRID"
