"""What-if through the engine: one facility, one user-chosen clinic system, the 24-hour ring trace.

Rooms (the web app's RoomKey) map onto the engine's SEforALL load rows; the room-to-row mapping is the API's
choice and is stated in docs/sources/api.md:
  delivery: suction apparatus, procedure light, fetal heart monitor (priority 1)
  oxygen:   oxygen concentrator (priority 1)
  ward:     interior lighting (priority 1)
  lab:      centrifuge, electric microscope (priority 2)
  fridge:   the vaccine fridge, never on the clinic system (PQS PV01.3). fridge_mode "shared" reports the
            fridge on the grid it has today (scenario b, a domestic fridge: the headline); "pqs_sdd" reports a
            dedicated PQS solar direct-drive fridge on its own array. The engine has no vaccine fridge on a
            shared battery, so none is simulated.
Every figure comes from engine calls (sim.prepare, sim.simulate_facility, sim.simulate_clinic,
sim.domestic_on_grid, sim.sdd_fridge, econ). The cabinet temperature series is ILLUSTRATIVE: the engine tracks
whether the cold reserve lasts, not a temperature, so held hours show the engine's setpoint constant (5 degC)
and failed hours its holdover end point constant (10 degC).
"""

from __future__ import annotations

import dataclasses
import time

import numpy as np

from engine import constants as C
from engine import econ as E
from engine import fridge as F
from engine import loads as LD
from engine import sim as SM

ROOMS = ("fridge", "delivery", "oxygen", "lab", "ward")
ROOM_NAMES = {"fridge": "Vaccine fridge", "delivery": "Delivery room", "oxygen": "Oxygen", "lab": "Laboratory",
              "ward": "Ward lights"}
ROOM_LOAD_KEYS = {
    "delivery": ("suction", "procedure_light", "fetal_monitor"),
    "oxygen": ("oxygen",),
    "ward": ("light_interior",),
    "lab": ("centrifuge", "microscope"),
}
_BY_KEY = LD.by_key()
SDD_CODE = SM.SimConfig().fridge_with  # E003-040e, the engine's default SDD for "with"
START_HOUR = 18  # the ring opens at dusk


def room_loads(room: str) -> list[LD.Load]:
    return [_BY_KEY[k] for k in ROOM_LOAD_KEYS.get(room, ())]


def room_priority(room: str) -> int | None:
    lds = room_loads(room)
    return max(ld.priority for ld in lds) if lds else None


def _hours_kind(lds: list[LD.Load]) -> str:
    prof = sum(ld.hourly_kw() for ld in lds)
    on = np.where(prof > 0)[0]
    if len(on) == 24:
        return "all"
    night = sum(1 for h in on if h >= 18 or h < 6)
    return "night" if night >= len(on) / 2 else "day"


def loads_table(fridge_code: str | None) -> list[dict]:
    """The web's Load[]: one entry per room, from the engine's load rows and the fridge catalogue."""
    out = []
    m = F.CATALOGUE.get(fridge_code or "") if fridge_code else None
    kw = (m.energy_kwh_24h or 0) / 24.0 if m and m.energy_kwh_24h else None
    out.append({"key": "fridge", "name": ROOM_NAMES["fridge"], "priority": 1, "kw": None if kw is None else round(kw, 4),
                "hours": "all", "own_system": True,
                "source": (m.source if m else "fridge model unknown") + "; on its own system (PQS PV01.3 p.4)"})
    for room in ("delivery", "oxygen", "lab", "ward"):
        lds = room_loads(room)
        out.append({"key": room, "name": ROOM_NAMES[room], "priority": room_priority(room),
                    "kw": round(sum(ld.units * ld.watts for ld in lds) / 1000.0, 4), "hours": _hours_kind(lds),
                    "rows": [ld.name for ld in lds], "source": "; ".join(sorted({ld.source for ld in lds})),
                    "time_of_day": "ASSUMPTION (engine/loads.py windows)"})
    return out


def _iv(x: SM.Interval | None) -> dict | None:
    return None if x is None else {"p": x.point, "lo": x.lo, "hi": x.hi}


def _one_lane(pp: SM.Prepared, lane: int = 0) -> SM.Prepared:
    s = slice(lane, lane + 1)
    return dataclasses.replace(pp, pv_l=pp.pv_l[s], leak_l=pp.leak_l[s], grid=pp.grid[s], k=pp.k[s], n_lanes=1,
                               h_dom=pp.h_dom[s], avail=pp.avail[s], soil=pp.soil[s])


def run(lat: float, lon: float, bands, rooms: list[str], pv_kwp: float, battery_kwh: float, fridge_mode: str,
        target: float, n_draws: int, shortfall, prefer_held: bool | None = None) -> dict:
    """prefer_held: the fridge state the ring's night must show. The facility record passes the headline's (held
    when the headline uptime is at least one half); None uses this run's own median."""
    t0 = time.perf_counter()
    cfg = SM.SimConfig(n_draws=n_draws, shortfall=shortfall)
    pp = SM.prepare(lat, lon, bands, cfg)
    clinic_rooms = [r for r in ROOMS if r in rooms and r != "fridge"]
    loads = [ld for r in clinic_rooms for ld in room_loads(r)]
    res = SM.simulate_facility(lat, lon, bands, loads or None, SM.ClinicSystem(pv_kwp, battery_kwh), cfg,
                               trace=False, prepared=pp)

    # fridge figure for the chosen mode
    if fridge_mode == "pqs_sdd":
        fridge_iv, fridge_tech = res.fridge_with, res.fridge_with_technical
        fridge_label = f"dedicated PQS solar direct-drive fridge ({F.CATALOGUE[SDD_CODE].name}) on its own array"
    else:
        fridge_iv, fridge_tech = res.fridge_today, res.fridge_today_technical
        fridge_label = ("today's fridge on the grid it has (scenario b, a domestic or non-PQS fridge); the clinic "
                        "battery never powers the vaccine fridge (PQS PV01.3)")

    survival = []
    if "fridge" in rooms and fridge_iv is not None:
        survival.append({"load": "fridge", "name": ROOM_NAMES["fridge"], **_iv(fridge_iv),
                         "target_met": bool(fridge_tech.lo >= target) if fridge_tech else None})
    for r in clinic_rooms:
        iv = res.per_priority_with.get(room_priority(r))
        if iv is not None:
            survival.append({"load": r, "name": ROOM_NAMES[r], **_iv(iv), "target_met": bool(iv.lo >= target)})

    trace = ring_trace(pp, cfg, rooms, clinic_rooms, loads, pv_kwp, battery_kwh, fridge_mode, prefer_held)

    clinic_cost = E.clinic_capex_usd(pv_kwp, battery_kwh)
    fridge_cost = E.fridge_capex_usd(SDD_CODE) if fridge_mode == "pqs_sdd" else None
    total = clinic_cost.point + (fridge_cost.point if fridge_cost else 0.0)
    return {
        "pv_kwp": pv_kwp, "battery_kwh": battery_kwh, "fridge_mode": fridge_mode, "target": target,
        "survival": survival, "fridge_days": _iv(fridge_iv), "fridge_days_technical": _iv(fridge_tech),
        "fridge_label": fridge_label, "critical_today": _iv(res.critical_today),
        "cost_usd": round(total, 2),
        "costs": {"clinic_system_usd": dataclasses.asdict(clinic_cost),
                  "fridge_usd": None if fridge_cost is None else dataclasses.asdict(fridge_cost),
                  "clinic_system_ngn": dataclasses.asdict(E.to_ngn(clinic_cost)),
                  "basis": "clinic system at SEforALL $/Wp (7.2 kWh per kWp bundle); PQS sheet price, EXW, for the "
                           "solar fridge; naira at the CBN central rate of " + C.FX_DATE},
        "trace": trace, "supply_known": bool(res.supply_known), "n_lanes": int(res.n_lanes),
        "weather_point": list(res.weather_point),
        "labels": {"supply": "MODELLED from the NERC band promise; promised, not measured",
                   "rooms": "share of days every load up to this room's priority is served all day",
                   **res.labels},
        "engine_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


SCENARIO_TEXT = {
    "shared": "domestic: a household or non-PQS fridge on today's grid (scenario b, the headline)",
    "pqs_sdd": "pqs_sdd: a dedicated PQS solar direct-drive fridge on its own array (fix ii)",
}
TRACE_RULE = ("lane: the supply-and-weather draw whose share of days held (with the availability scenario) is "
              "closest to the median over all draws, which is the figure shown; night: 18:00 to 17:00, among the "
              "nights of that draw whose fridge state matches the figure (held when it is at least one half), the "
              "one whose grid hours are closest to that draw's median night")


def ring_trace(pp: SM.Prepared, cfg: SM.SimConfig, rooms, clinic_rooms, loads, pv_kwp: float, battery_kwh: float,
               fridge_mode: str, prefer_held: bool | None = None) -> dict:
    """The 24-hour ring from the same draws, and the same fridge scenario, as the figure it sits next to."""
    B = SM.BURN_IN_H
    if fridge_mode == "pqs_sdd":
        _, ok_all, _arr = SM.sdd_fridge(pp, SDD_CODE)
    else:
        _, ok_all = SM.domestic_on_grid(pp)
    grid_all = pp.grid[:, B:]
    L, T = grid_all.shape
    n_win = T // 24 - 1
    starts = np.arange(n_win) * 24 + START_HOUR
    idx = starts[:, None] + np.arange(24)[None, :]  # (n_win, 24)
    win_grid = grid_all[:, idx].sum(axis=2)  # (L, n_win)
    draw: dict = {"scenario": SCENARIO_TEXT[fridge_mode], "n_lanes": int(L), "rule": TRACE_RULE}
    if ok_all is not None:
        share = F.days_held(ok_all).mean(axis=1) * pp.avail
        med = float(np.median(share))
        lane = int(np.argmin(np.abs(share - med)))
        held_win = ok_all[lane][idx].all(axis=1)
        want = prefer_held if prefer_held is not None else med >= 0.5
        cand = np.where(held_win == want)[0]
        matched = cand.size > 0
        if not matched:
            cand = np.arange(n_win)
        target_h = float(np.median(win_grid[lane]))
        w = int(cand[np.argmin(np.abs(win_grid[lane, cand] - target_h))])
        draw.update({"lane": lane, "lane_uptime": float(share[lane]), "run_median_uptime": med,
                     "wanted_fridge_held": bool(want), "window_fridge_held": bool(held_win[w]),
                     "state_matched": bool(matched),
                     "nights_held_in_lane": int(held_win.sum()), "nights_in_lane": int(n_win)})
    else:  # supply unknown: no fridge figure today; the median-grid lane, labelled
        m = win_grid.mean(axis=1)
        lane = int(np.argmin(np.abs(m - np.median(m))))
        target_h = float(np.median(win_grid[lane]))
        w = int(np.argmin(np.abs(win_grid[lane] - target_h)))
        draw.update({"lane": lane, "lane_uptime": None, "run_median_uptime": None,
                     "note": "supply unknown (refused match): no fridge figure today, so the fridge row is empty"})
    s = slice(int(starts[w]), int(starts[w]) + 24)
    draw.update({"night_index": w, "day_of_year": int(starts[w] // 24), "window_grid_hours": int(win_grid[lane, w]),
                 "lane_median_grid_hours": target_h})
    p1 = _one_lane(pp, lane)
    grid0 = p1.grid[0, B:]
    ok_f = None if ok_all is None else ok_all[lane]
    if loads:
        prio, prof = LD.priority_profile(loads)
        cl = SM.simulate_clinic(p1.grid, p1.pv_l, np.array([pv_kwp]), np.array([battery_kwh]), prof, cfg.battery,
                                trace_lane=0, burn_in_h=B)
        soc, served, cap = cl["soc_trace"][0], cl["served_trace"][0], float(cl["cap"][0])
    else:
        prio, prof = np.array([], dtype=int), np.zeros((0, 24))
        soc, served, cap = np.zeros(T), np.zeros(T, dtype=int), battery_kwh * C.BATTERY_USABLE_FRACTION.value
    hours = [(START_HOUR + i) % 24 for i in range(24)]
    pv_kw = (pv_kwp * p1.pv_l[0, B:][s]).astype(float)
    load_kw = prof.sum(axis=0)[hours] if len(prio) else np.zeros(24)
    rooms_out: dict[str, list] = {}
    for r in ROOMS:
        if r == "fridge":
            rooms_out[r] = [None] * 24 if (ok_f is None or "fridge" not in rooms) else [bool(x) for x in ok_f[s]]
            continue
        if r not in clinic_rooms:
            rooms_out[r] = [None] * 24
            continue
        demand = sum(ld.hourly_kw() for ld in room_loads(r)) > 0
        i = int(np.where(prio == room_priority(r))[0][0])
        g, sv = grid0[s], served[s]
        rooms_out[r] = [None if not demand[h] else bool(g[k] or sv[k] > i) for k, h in enumerate(hours)]
    fridge_c = ([] if ok_f is None else
                [C.CABINET_SETPOINT_C.value if x else C.HOLDOVER_LIMIT_C.value for x in ok_f[s]])
    return {
        "start_hour": START_HOUR, "hour": hours, "grid_on": [bool(x) for x in grid0[s]],
        "solar_kw": [round(float(x), 3) for x in pv_kw], "load_kw": [round(float(x), 3) for x in load_kw],
        "battery_soc": [round(float(x) / cap, 4) if cap > 0 else 0.0 for x in soc[s]],
        "fridge_c": fridge_c, "battery_kwh": battery_kwh, "pv_kwp": pv_kwp, "fridge_mode": fridge_mode,
        "fridge_curve": "illustrative", "rooms": rooms_out,
        "scenario": "pqs_sdd" if fridge_mode == "pqs_sdd" else "domestic", "draw": draw,
        "day_of_year": draw["day_of_year"], "lane": lane,
        "note": ("one real simulated night (modelled supply draw, NASA POWER weather), not a measurement; "
                 "fridge_c is illustrative: 5 degC while the cold reserve lasts, 10 degC (the PQS holdover end "
                 "point) once it runs out"),
    }
