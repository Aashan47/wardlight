"""The brief 13 line watcher: reads a line-cut signal, then re-plans which critical sites run first.

    python -m agents.watcher13 [--city maiduguri] [--budget 2e9]

Real signals only, as in the brief 1 watcher (which diffs NERC's published orders): the two signals below are
TCN's own statements about the 2024 cut of the Gombe to Damaturu to Maiduguri 330 kV line, quoted from the press
(raw HTML checked by the research stream, `research-raw/2026-10-31/BRIEF13-CITY.md`). A recorded run replays
them; nothing is staged. The plan the watcher re-plans is a scenario (a budget plan from `city13.plan`, by
default the planner's N2 billion), labelled as such.

Steps:
1. read the cut signal: the line, the time, the cities it names;
2. locate it on the corridor (the city build's mapped 330 kV line and towers);
3. re-plan the run order for the outage, before its length is known, at the brief's two months (60 days):
   sites the plan funded run on their own solar + storage; every other site goes dark unless fuelled, and the
   watcher orders those by critical service-hours gained per litre of diesel (the site's own engine results:
   hours its system would keep over today, and the litres a generator burns to deliver them), most first;
4. read the restoration signal and measure the outage (start to restoration);
5. close the event at the measured window: hours kept today and with the plan, litres the plan would have avoided;
6. report, grounded (every number in the text traced to the computed records).
No model is involved.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections.abc import Iterator

from . import city13 as C13
from . import events as EV
from . import grounding as G
from .fake13 import pct

SIGNALS = [
    {"id": "tcn-2024-09-21-cut", "kind": "cut", "at": "2024-09-21T01:44:00+01:00",
     "line": "Gombe to Damaturu to Maiduguri 330 kV line", "cities": ["maiduguri", "damaturu"],
     "quote": "the transmission line was brought down by vandals by cutting all four-tower footing and was noticed "
              "by the TCN around 01:44 am on the 21st of September 2024.",
     "quote_backup": "efforts are currently underway by its engineers to temporarily restore power to Damaturu "
                     "through a 33kV transmission line from Potiskum, while Maiduguri will receive power from the "
                     "Maiduguri Emergency Power Plant (MEPP).",
     "source": "Nairametrics, 23 Sep 2024, quoting TCN",
     "url": "https://nairametrics.com/2024/09/23/blackout-in-borno-yobe-as-vandals-destroy-gombe-maiduguri-"
            "transmission-three-months-after-repair", "status": "VERIFIED_SECONDARY"},
    {"id": "tcn-2024-10-31-restored", "kind": "restored", "at": "2024-10-31T14:01:00+01:00",
     "line": "Gombe to Damaturu to Maiduguri 330 kV line", "cities": ["maiduguri", "damaturu"],
     "quote": "power supply was fully restored on the Gombe-Damaturu line about 7:25p.m. on October 30, and on the "
              "Damaturu-Maiduguri (Molai) part of the line on October 31, 2024, around 2:01p.m.",
     "source": "Arise News, 2 Nov 2024, quoting TCN's GM Public Affairs Ndidi Mbah",
     "url": "https://www.arise.tv/tcn-restores-power-supply-through-gombe-damaturu-maiduguri-line/",
     "status": "VERIFIED_SECONDARY"},
]
PRIOR_DAYS = 60  # the brief: repairs took about two months; used until the restoration signal arrives
DEFAULT_BUDGET = 2e9
TOP = 10
LABEL = ("Recorded run. The signals are TCN's 2024 statements (press, quoted); the plan is a scenario (the "
         "planner's budget plan). Code only, no model.")


def run_order(p: dict, top: int = TOP) -> dict:
    """Funded sites run on their own systems; the rest in order of critical service-hours gained per litre."""
    dark = []
    for r in p["rows"]:
        if r["funded"]:
            continue
        litres, gain = float(r["diesel_l_avoided"] or 0.0), float(r["gained_h"] or 0.0)
        if gain <= 0:
            continue
        dark.append({**{k: r[k] for k in ("rank", "id", "name", "sector", "archetype", "lga", "needed_h",
                                          "today_h", "with_h", "gained_h")},
                     "litres": round(litres, 1), "hours_per_litre": round(gain / litres, 2) if litres else None})
    dark.sort(key=lambda x: (-(x["hours_per_litre"] or 0.0), x["id"]))
    for i, x in enumerate(dark, 1):
        x["fuel_order"] = i
    price = p["diesel_price"]["ngn_per_l"]
    litres_all = sum(x["litres"] for x in dark)
    head = dark[:top]
    return {"own_solar": [{k: f[k] for k in ("order", "id", "name", "sector")} for f in p["funded"][:top]],
            "own_solar_count": len(p["funded"]), "fuel_first": head, "dark_count": len(dark),
            "fuel_first_litres": round(sum(x["litres"] for x in head), 1),
            "fuel_first_gained_h": round(sum(x["gained_h"] for x in head), 1),
            "litres_to_fuel_every_dark_site": round(litres_all, 1),
            "ngn_to_fuel_every_dark_site": round(litres_all * price, 0), "diesel_ngn_per_l": price,
            "rule": "funded sites run on their own solar + storage; every other site in order of critical "
                    "service-hours gained per litre of diesel (its system's hours over today, and the litres a "
                    "generator burns to deliver them), most first"}


def _days_between(a: str, b: str) -> float:
    return (dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds() / 86400.0


def run_events(city: str = "maiduguri", budget_ngn: float = DEFAULT_BUDGET, data: C13.City13Data | None = None,
               signals: list[dict] | None = None, result: dict | None = None) -> Iterator[dict]:
    data = data or C13.City13Data()
    signals = signals or SIGNALS
    log = EV.EventLog()
    c = data.resolve_city(city)
    cut = next(s for s in signals if s["kind"] == "cut")
    back = next((s for s in signals if s["kind"] == "restored"), None)
    yield log.emit("plan", steps=[{"id": "signal", "title": "Read the line-cut signal"},
                                  {"id": "locate", "title": "Locate the cut on the 330 kV corridor"},
                                  {"id": "replan", "title": "Re-plan which sites run first"},
                                  {"id": "restored", "title": "Read the restoration signal"},
                                  {"id": "close", "title": "Close the event at its measured length"},
                                  {"id": "report", "title": "Write the run-order report"}])

    def call(cid, name, args):
        return log.emit("tool_call", id=cid, name=name, args=args), log.ms()

    yield log.emit("step_start", id="signal")
    ev, t = call("w1", "read_signal", {"signal": cut["id"], "source": cut["source"]})
    yield ev
    yield log.emit("tool_result", id="w1", rows=1, ms=log.ms() - t, signal=cut,
                   summary=f"TCN: {cut['line']} cut, noticed {cut['at'][:16].replace('T', ' ')} WAT")

    yield log.emit("step_start", id="locate")
    ev, t = call("w2", "locate_cut", {"line": cut["line"], "cities": cut["cities"]})
    yield ev
    m = data.any_metrics(c)
    cor = (m.get("innovation") or {}).get("corridor") or {}
    affected = [x for x in cut["cities"] if x in C13.CITIES]
    corridor = {"km_330": cor.get("km_330"), "towers": cor.get("towers"), "source": cor.get("source"),
                "box": cor.get("box"), "cities": affected}
    yield log.emit("tool_result", id="w2", rows=len(affected), ms=log.ms() - t, corridor=corridor,
                   summary=f"{cor.get('km_330')} km of mapped 330 kV line, {cor.get('towers')} towers; "
                           f"{len(affected)} cities on it")

    yield log.emit("step_start", id="replan")
    ev, t = call("w3", "replan_run_order", {"city": c, "budget_ngn": budget_ngn, "days": PRIOR_DAYS,
                                            "why": "outage length unknown: the brief's two months"})
    yield ev
    p60 = C13.plan(data, c, budget_ngn, PRIOR_DAYS)
    ro60 = run_order(p60)
    others = {}
    for o in affected:
        if o != c:
            po = C13.plan(data, o, 0.0, PRIOR_DAYS)
            others[o] = {"city_name": po["city_name"], "share_today": po["totals"]["share_today"],
                         "sites": po["totals"]["candidates"], "fuel_first": run_order(po, 3)["fuel_first"]}
    yield log.emit("tool_result", id="w3", rows=p60["totals"]["candidates"], ms=log.ms() - t,
                   summary=f"{ro60['own_solar_count']} sites run on their own solar; {ro60['dark_count']} go dark "
                           f"unless fuelled, ordered by hours per litre",
                   run_order=ro60, funded=[f["id"] for f in p60["funded"]])

    closed = None
    if back is not None:
        yield log.emit("step_start", id="restored")
        ev, t = call("w4", "read_signal", {"signal": back["id"], "source": back["source"]})
        yield ev
        dur = _days_between(cut["at"], back["at"])
        avail = data.days_available(c)
        window = min(avail, key=lambda w: (abs(w - dur), -w))
        yield log.emit("tool_result", id="w4", rows=1, ms=log.ms() - t, signal=back,
                       duration_days=round(dur, 2), window_days=window,
                       summary=f"restored {back['at'][:16].replace('T', ' ')} WAT: {dur:.1f} days out")
        yield log.emit("step_start", id="close")
        ev, t = call("w5", "close_event", {"city": c, "budget_ngn": budget_ngn, "days": window})
        yield ev
        pw = C13.plan(data, c, budget_ngn, window)
        closed = {"duration_days": round(dur, 2), "window_days": window, "totals": pw["totals"],
                  "run_order": run_order(pw)}
        yield log.emit("tool_result", id="w5", rows=pw["totals"]["candidates"], ms=log.ms() - t, closed=closed,
                       summary=f"{window}-day window: {pct(pw['totals']['share_today'])} kept today, "
                               f"{pct(pw['totals']['share_with_funded'])} with the plan")

    yield log.emit("step_start", id="report")
    t60 = p60["totals"]
    name = p60["city_name"]
    lines = [f"# Line cut: {cut['line']}", "",
             f"Signal: TCN noticed the cut at 01:44 on 21 September 2024 ({cut['source']}). It names "
             f"{' and '.join(C13.CITIES[x]['name'] for x in affected)}; the city build maps "
             f"{corridor['km_330']} km of 330 kV line and {corridor['towers']:,} towers on the corridor.",
             "", f"## Run order for {name}, before the outage length is known ({PRIOR_DAYS} days, the brief's two "
                 "months)",
             f"- {ro60['own_solar_count']} sites funded by the {C13.CITIES[c]['name']} plan run on their own solar + "
             f"storage: {pct(t60['share_with_funded'])} of critical service-hours kept against "
             f"{pct(t60['share_today'])} with nothing built.",
             f"- {ro60['dark_count']} sites go dark unless fuelled. Fuel these first, most hours per litre:"]
    for x in ro60["fuel_first"][:5]:
        lines.append(f"  {x['fuel_order']}. {x['name']} ({x['sector']}): {x['gained_h']:g} critical service-hours "
                     f"for {x['litres']:g} litres")
    lines.append(f"- The first {len(ro60['fuel_first'])} on that list need {ro60['fuel_first_litres']:g} litres; "
                 f"every dark site needs {ro60['litres_to_fuel_every_dark_site']:,.0f} litres, about "
                 f"N{ro60['ngn_to_fuel_every_dark_site']:,.0f} at N{ro60['diesel_ngn_per_l']:,.2f} per litre.")
    for o, v in others.items():
        lines.append(f"- {v['city_name']}, also on the line, has no plan built: {pct(v['share_today'])} of its "
                     "critical service-hours are kept with no backup.")
    if closed:
        tw = closed["totals"]
        lines += ["", "## Closed", "",
                  f"Restored at 14:01 on 31 October 2024 ({back['source']}): {closed['duration_days']:g} days out, "
                  f"closed on the {closed['window_days']} day window. Over it the plan keeps "
                  f"{pct(tw['share_with_funded'])} of {name}'s critical service-hours against {pct(tw['share_today'])} "
                  f"with nothing built, and its systems avoid {tw['diesel_l_avoided']:,.0f} litres of diesel."]
    lines += ["", "Signals are TCN statements quoted by the press. The plan is a scenario; supply and loads are "
                  "modelled, not measured."]
    md = "\n".join(lines)
    pool = [cut, back or {}, corridor, t60, ro60, others, closed or {}, {"prior_days": PRIOR_DAYS},
            {"times": ["01:44", "14:01", "21 September 2024", "31 October 2024"]}]
    rep = G.check(md, pool, require_citation=False)
    yield log.emit("check", kind="grounding", numbers_checked=rep.n_total,
                   unmatched=[x.text for x in rep.unmatched] + rep.unknown_tokens,
                   matches=[{"text": x.text, "value": x.value, "matched": x.matched} for x in rep.claims], ok=rep.ok)
    if not rep.ok:
        yield log.emit("error", message="report text failed the grounding check; records only")
        md = ""
    totals = {"city": c, "budget_ngn": budget_ngn, "own_solar": ro60["own_solar_count"], "dark": ro60["dark_count"],
              "share_today": t60["share_today"], "share_with_plan": t60["share_with_funded"],
              "duration_days": closed["duration_days"] if closed else None,
              "window_days": closed["window_days"] if closed else None,
              "diesel_l_avoided": closed["totals"]["diesel_l_avoided"] if closed else None}
    yield log.emit("answer", markdown=md, funded=[], not_reached=[], totals=totals, signals=[cut] + ([back] if back else []),
                   run_order=ro60, closed=closed, corridor=corridor, others=others)
    yield log.emit("done", model="none (code only)", tokens=0, cost_usd=0.0, recorded=False, duration_ms=log.ms())
    if result is not None:
        result.update({"events": log.events, "totals": totals, "markdown": md})


def run(city: str = "maiduguri", budget_ngn: float = DEFAULT_BUDGET, **kw) -> dict:
    rec: dict = {}
    for _ in run_events(city, budget_ngn, result=rec, **kw):
        pass
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="maiduguri")
    ap.add_argument("--budget", type=float, default=DEFAULT_BUDGET)
    a = ap.parse_args(argv)
    rec = run(a.city, a.budget)
    print(rec["markdown"])
    print(json.dumps(rec["totals"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
