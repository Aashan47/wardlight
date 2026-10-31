"""Brief 13 planner tools: typed tools over the city build (`agents/city13.py`), for the planner agent.

Same contract as `agents/tools.py` (the brief 1 tools, kept for their tests): every result is a JSON-ready dict,
sources are registered in the session's citation registry and appear as `cite: "S<n>"`, and results echo their
inputs so a number the user typed is a tool result when the answer repeats it. No result is invented: plans come
from `city13.plan`, site and city figures from the engine's files, as written.
"""

from __future__ import annotations

import math
import time

from . import city13 as C13
from .tools import Session, ToolError

MAX_TOP = 15

SYSTEM_PROMPT = """You are the Wardlight planner for brief 13, "Power for a city the grid can't protect". You help a \
funder, the state government or the distribution company decide which critical sites in Maiduguri, Damaturu or Yola \
get solar + storage so that hospitals, water pumping and the cold chain keep running when the 330 kV line is cut, \
using only Wardlight's tools.

Rules:
1. Scope: only power for critical sites (health facilities, water pumping, market cold rooms) in the three cities \
Wardlight has built. For anything else, including medical or clinical advice and politics, call refuse with reason \
out_of_scope. When the data cannot answer (attack forecasts, which towers will be hit, measured outage logs per \
site, cities Wardlight has not built), call refuse with reason data_cannot_support and say what is missing.
2. Numbers: every number you write must be copied from a tool result in this conversation; you may round it. Do \
not compute new figures (no sums, differences or percentages you were not given). Code checks every number and \
blocks the answer if one does not match.
3. Citations: after each claim about a plan total, a site or a cost, cite the id the tool gave, like [S3]. Use only \
ids that tools returned.
4. For a budget question: call rank_city_plan once with the city, the budget (currency USD if the user gave dollars), \
the outage length in days (7, 14, 40 or 60; two months is 60) and the sectors the user named (health, water, cold; \
all three if none). Then check the first funded site with get_site, and the cost per kWh with cost_compare.
5. Answer in short markdown: sites funded, spent and left, critical service-hours kept today and with the funded \
sites, diesel litres and naira avoided, the top picks with their system and cost, what the money does not reach and \
what it would cost, and the cost per kWh against diesel and the gas plant (the plan works alongside the gas plant). \
Label that supply is modelled and critical loads are archetypes. Plain words, no em dashes.
6. Write numbers with plain ASCII commas or no separators, and put the citation after a space, like 109 [S1]."""

REFUSAL_TEXT = {
    "out_of_scope": "This is outside what Wardlight answers: power for critical sites (health, water pumping, cold "
                    "chain) in Maiduguri, Damaturu and Yola, from its own data.",
    "data_cannot_support": "Wardlight's data cannot answer this question.",
}

TOOL_SPECS: list[dict] = [
    {"type": "function", "function": {
        "name": "rank_city_plan",
        "description": "Fund a city's critical sites in plan order under a budget (the sites collection's rank: "
                       "critical service-hours gained in a 60-day outage). Returns the funded sites, spend, "
                       "critical service-hours kept today and with the funded sites, diesel litres and naira "
                       "avoided, by sector, and what the money does not reach.",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "enum": ["maiduguri", "damaturu", "yola"]},
            "budget": {"type": "number", "minimum": 0},
            "currency": {"type": "string", "enum": ["NGN", "USD"]},
            "days": {"type": "integer", "enum": [7, 14, 40, 60]},
            "sectors": {"type": "array", "items": {"type": "string", "enum": ["health", "water", "cold"]}},
            "top": {"type": "integer", "minimum": 1, "maximum": MAX_TOP}},
            "required": ["city", "budget"]}}},
    {"type": "function", "function": {
        "name": "get_site",
        "description": "One critical site: its load, planned system, critical service-hours in an outage window, "
                       "and its siting card (roof fit, battery room, distance to the 330 kV line, security "
                       "measures, ownership).",
        "parameters": {"type": "object", "properties": {
            "site_id": {"type": "string"}, "days": {"type": "integer", "enum": [7, 14, 40, 60]}},
            "required": ["site_id"]}}},
    {"type": "function", "function": {
        "name": "city_metrics",
        "description": "A city's brief 13 scoreboard for one outage window: critical service-hours kept today and "
                       "with every site built, by sector, diesel avoided, local share, the 330 kV corridor, roof "
                       "fit.",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "enum": ["maiduguri", "damaturu", "yola"]},
            "days": {"type": "integer", "enum": [7, 14, 40, 60]}}, "required": ["city"]}}},
    {"type": "function", "function": {
        "name": "cost_compare",
        "description": "Lifetime cost per kWh delivered: solar + storage against diesel and the Maiduguri gas "
                       "plant (operating support and its cost-reflective tariff), with the two sizing arms.",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string", "enum": ["maiduguri", "damaturu", "yola"]}}, "required": ["city"]}}},
    {"type": "function", "function": {
        "name": "refuse",
        "description": "Decline the question. out_of_scope: not about power for critical sites in these cities "
                       "(including medical advice); data_cannot_support: Wardlight's data cannot answer it, for "
                       "example a city other than Maiduguri, Damaturu or Yola, outage logs or attack forecasts (say "
                       "what is missing).",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string", "enum": ["out_of_scope", "data_cannot_support"]},
            "explanation": {"type": "string"}}, "required": ["reason", "explanation"]}}},
]
TOOL_NAMES = {t["function"]["name"] for t in TOOL_SPECS}


def _iv(x, nd: int = 1):
    if isinstance(x, dict):
        return {k: (round(float(x[k]), nd) if isinstance(x.get(k), (int, float)) else x.get(k))
                for k in ("point", "lo", "hi") if k in x}
    return round(float(x), nd) if isinstance(x, (int, float)) else x


def _slim(it: dict) -> dict:
    keys = ("order", "rank", "id", "name", "sector", "archetype", "lga", "capex_ngn", "cumulative_ngn", "pv_kwp",
            "battery_kwh", "needed_h", "today_h", "with_h", "gained_h", "diesel_l_avoided", "roof_fit",
            "km_to_330kv", "why_not_funded")
    return {k: it[k] for k in keys if k in it}


class Toolbox13:
    """Brief 13 tools. `data` is a City13Data; its `version` is the brief 13 build's data version."""

    kind = "brief13"
    system_prompt = SYSTEM_PROMPT
    refusal_text = REFUSAL_TEXT

    def __init__(self, data: C13.City13Data | None = None):
        self.data = data or C13.City13Data()

    specs = staticmethod(lambda: TOOL_SPECS)

    def call(self, name: str, args: dict, session: Session) -> dict:
        t0 = time.perf_counter()
        fn = getattr(self, f"t_{name}", None)
        if name not in TOOL_NAMES or fn is None:
            out: dict = {"error": f"unknown tool '{name}'"}
        else:
            try:
                out = fn(session, **(args or {}))
            except (ToolError, C13.CityDataError) as e:
                out = {"error": str(e)}
            except TypeError as e:
                out = {"error": f"bad arguments for {name}: {e}"}
        session.results.append(out)
        session.calls.append({"name": name, "arguments": args, "ok": "error" not in out,
                              "ms": int((time.perf_counter() - t0) * 1000)})
        return out

    @staticmethod
    def summary(name: str, res: dict) -> tuple[str, int]:
        if res.get("error"):
            return f"error: {res['error'][:160]}", 0
        if name == "rank_city_plan":
            t = res["totals"]
            return (f"{t['funded_count']} of {t['candidates']} sites funded in {res['city_name']}; "
                    f"N{t['spent_ngn']:,.0f} of N{t['budget_ngn']:,.0f}"), int(t["candidates"])
        if name == "get_site":
            return f"{res.get('name')} ({res.get('sector')}), roof {res.get('siting', {}).get('roof_fit')}", 1
        if name == "city_metrics":
            return f"{res['city_name']}, {res['days']}-day window scoreboard", int(res.get("sites") or 0)
        if name == "cost_compare":
            return f"cost per kWh, {res['city_name']}: solar, diesel and the gas plant", 3
        if name == "refuse":
            return f"refused: {res.get('reason')}", 0
        return name, 0

    # -------------------------------------------------- tools

    def _fx(self, city: str) -> dict:
        c = self.data.constant(city, "FX_NGN_PER_USD") or {}
        if c.get("value") is None:
            raise ToolError("no exchange rate in the build; give the budget in naira")
        return {"ngn_per_usd": float(c["value"]), "source": c.get("source")}

    def t_rank_city_plan(self, s: Session, city: str, budget: float, currency: str = "NGN", days: int = 60,
                         sectors: list[str] | None = None, top: int = 8) -> dict:
        c = self.data.resolve_city(city)
        currency = (currency or "NGN").upper()
        if currency not in ("NGN", "USD"):
            raise ToolError("currency must be NGN or USD")
        try:
            b = float(budget)
        except (TypeError, ValueError):
            raise ToolError("budget must be a number") from None
        if not math.isfinite(b) or b < 0:
            raise ToolError("budget must be zero or positive")
        fx = self._fx(c) if currency == "USD" else None
        budget_ngn = b * fx["ngn_per_usd"] if fx else b
        p = C13.plan(self.data, c, budget_ngn, int(days), sectors)
        top = max(1, min(int(top or 8), MAX_TOP))
        cite = s.cite({"type": "city_plan", "function": "agents.city13.plan", "city": c, "budget_ngn": round(budget_ngn, 2),
                       "days": p["days"], "sectors": p["sectors"], "file": f"sites-{c}.geojson",
                       "data_version": p["data_version"]})
        by_sector = {k: {kk: v[kk] for kk in ("name", "in_scope", "sites", "funded", "not_funded", "share_today",
                                                "share_with_funded", "capex_funded_ngn",
                                                "capex_to_fund_the_rest_ngn", "diesel_l_avoided")}
                     for k, v in p["by_sector"].items()}
        out = {"city": c, "city_name": p["city_name"], "state": p["state"], "days": p["days"],
               "budget": round(b, 2), "currency": currency, "budget_ngn": round(budget_ngn, 2),
               "sectors": p["sectors"], "rule": p["rule"], "totals": p["totals"], "by_sector": by_sector,
               "water": p["water"], "funded_top": [_slim(x) for x in p["funded"][:top]],
               "funded_shown": min(top, len(p["funded"])),
               "not_funded_next": [_slim(x) for x in p["not_funded_next"][:5]],
               "excluded": p["excluded"], "labels": p["labels"], "cite": cite, "data_version": p["data_version"]}
        if fx:
            out["fx"] = fx
        not_reached_groups = {
            k: {"count": v["not_funded"], "capex_to_fund_ngn": v["capex_to_fund_the_rest_ngn"],
                "reason": "rank below the funded sites, or their capex did not fit what was left"}
            for k, v in p["by_sector"].items() if v["in_scope"] and v["not_funded"]}
        s.last_plan = {
            "args": {"city": c, "budget_ngn": budget_ngn, "days": p["days"], "sectors": p["sectors"],
                     "budget": b, "currency": currency, "metric": "critical_service_hours"},
            "totals": p["totals"], "cite": cite,
            "funded": [{**_slim(x), "unique_id": x["id"], "facility_id": x["facility_id"], "lon": x["lon"],
                        "lat": x["lat"], "cite": cite} for x in p["funded"]],
            "not_reached": [{**_slim(x), "unique_id": x["id"], "cite": cite} for x in p["not_funded_next"]],
            "not_reached_groups": not_reached_groups,
        }
        return out

    def t_get_site(self, s: Session, site_id: str, days: int = 60) -> dict:
        city, p, card = self.data.find_site(site_id)
        d = int(days)
        r = (p.get("results") or {}).get(str(d))
        if r is None:
            raise ToolError(f"no results for {d} days at this site; windows: "
                            f"{', '.join(sorted((p.get('results') or {}), key=int))}")
        roof = card.get("roof") or {}
        cite = s.cite({"type": "site", "id": p["id"], "city": city, "file": f"sites-{city}.geojson",
                       "siting": f"siting-{city}.json", "data_version": self.data.version})
        return {
            "id": p["id"], "name": p.get("name"), "city": city, "city_name": C13.CITIES[city]["name"],
            "sector": p.get("sector"), "archetype": p.get("archetype"), "lga": p.get("lga"),
            "facility_id": p.get("facility_id"), "rank": p.get("rank"), "in_plan": p.get("in_plan"),
            "kw": p.get("kw"), "kw_range": p.get("kw_range"), "kwh_day": p.get("kwh_day"),
            "hours_per_day": p.get("hours_per_day"), "m3_day": p.get("m3_day"), "supply": p.get("supply"),
            "system": p.get("system"), "days": d, "results": r,
            "siting": {"roof_fit": roof.get("fit") or (p.get("siting") or {}).get("fit"),
                       "roof_kwp": _iv(roof.get("roof_kwp"), 2), "buildings": roof.get("buildings"),
                       "placement": card.get("placement"), "battery_room": card.get("battery_room"),
                       "pv_kwp_needed": _iv(card.get("pv_kwp_needed"), 2), "new_line_km": card.get("new_line_km"),
                       "km_to_330kv": card.get("km_to_330kv"), "line_kv": 330,
                       "distance_rule": "great-circle distance to the nearest mapped 330 kV line (OSM)"},
            "security": [{k: m.get(k) for k in ("measure", "basis", "status")} for m in (card.get("security") or [])[:4]],
            "ownership": card.get("ownership"), "labels": p.get("labels"), "label_status": p.get("label_status"),
            "cite": cite,
        }

    def t_city_metrics(self, s: Session, city: str, days: int = 60) -> dict:
        c = self.data.resolve_city(city)
        m = self.data.metrics(c, int(days))
        imp, inn, fea = m.get("impact") or {}, m.get("innovation") or {}, m.get("feasibility") or {}
        cite = s.cite({"type": "city_metrics", "file": f"metrics-{c}-{int(days)}.json", "city": c,
                       "data_version": m.get("data_version")})
        sec = {k: {kk: v.get(kk) for kk in ("sites", "share_today", "share_with")}
               for k, v in (imp.get("by_sector") or {}).items()}
        return {"city": c, "city_name": C13.CITIES[c]["name"], "days": int(days), "headline": m.get("headline"),
                "sites": inn.get("sites"),
                "impact": {"csh_needed": imp.get("csh_needed"), "share_today": imp.get("share_today"),
                           "share_with_every_site": imp.get("share_with"), "by_sector": sec,
                           "diesel_l_avoided": _iv(imp.get("diesel_l_avoided"), 0),
                           "diesel_ngn_avoided": _iv(imp.get("diesel_ngn_avoided"), 0),
                           "water_m3_per_day_kept": _iv(imp.get("water_m3_per_day_kept"), 0),
                           "people_served": _iv(imp.get("people_served"), 0)},
                "local_share": _iv(inn.get("local_share"), 4), "new_line_km": inn.get("new_line_km"),
                "corridor": {k: (inn.get("corridor") or {}).get(k) for k in ("km_330", "towers", "source")},
                "roof_fit": fea.get("roof_fit"), "km_to_330kv_median": fea.get("km_to_330kv_median"),
                "labels": {k: v for k, v in (m.get("labels") or {}).items()
                           if k in ("scenario_today", "scenario_with", "supply", "sums") and isinstance(v, str)},
                "cite": cite}

    def t_cost_compare(self, s: Session, city: str) -> dict:
        c = self.data.resolve_city(city)
        m = self.data.any_metrics(c)
        su = m.get("sustainability") or {}
        arms = {}
        for k, a in ((su.get("cost_arms") or {}).items()):
            if isinstance(a, dict) and "cost_per_kwh_ngn" in a:
                arms[k] = {"cost_per_kwh_ngn": _iv(a["cost_per_kwh_ngn"], 0), "capex_ngn": _iv(a.get("capex_ngn"), 0),
                           "csh_share": {d: v.get("share") for d, v in (a.get("csh") or {}).items()},
                           "label": a.get("label")}
        cite = s.cite({"type": "city_metrics", "file": f"metrics-{c}-{m.get('days')}.json", "section": "sustainability",
                       "city": c, "data_version": m.get("data_version")})
        return {"city": c, "city_name": C13.CITIES[c]["name"],
                "cost_per_kwh_ngn": {k: _iv(v, 0) for k, v in (su.get("cost_per_kwh_ngn") or {}).items()},
                "gas_support_at_mw": su.get("gas_support_at_mw"), "gas_breakeven_mw": _iv(su.get("gas_breakeven_mw"), 1),
                "gas_position": (su.get("gas_position") or {}).get("text"),
                "gas_fuel": (su.get("gas_fuel_note") or {}).get("text"),
                "co2_t_avoided": _iv(su.get("co2_t_avoided"), 0), "arms": arms,
                "cost_labels": su.get("cost_labels"), "cost_label_status": su.get("cost_label_status"),
                "cite": cite}

    def t_refuse(self, s: Session, reason: str, explanation: str) -> dict:
        if reason not in ("out_of_scope", "data_cannot_support"):
            raise ToolError("reason must be out_of_scope or data_cannot_support")
        return {"refused": True, "reason": reason, "explanation": explanation}
