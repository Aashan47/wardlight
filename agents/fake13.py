"""A rule-based scripted stand-in for the brief 13 planner model. NOT a language model and never presented as one.

It parses the question with fixed rules (city, budget, currency, outage days, sectors), calls the same brief 13
tools a model would (`agents/tools13.py`: rank_city_plan, then get_site on the first funded site, then
cost_compare), and writes the answer from a template filled only with values copied from those tool results. It
exists to test the harness and to record fixture sessions labelled "scripted". With `fabricate_first=True` its
first draft carries one invented number, so the grounding block and the retry can be shown and tested.

It returns no text alongside tool calls, so its sessions contain no `reasoning` events: there is no model
reasoning to show, and none is synthesised.
"""

from __future__ import annotations

import math
import re

from .fake import MONEY, SCALE, _tool_results
from .llm import ChatResponse, assistant, estimate_tokens, normalise_message, tool_call

CITY_RE = re.compile(r"\b(Maiduguri|Damaturu|Yola)\b", re.IGNORECASE)
MEDICAL = re.compile(r"\b(dose of|doses should|symptom|fever|diagnos|treat(ment)?|prescri|side effect|"
                     r"nine-month-old|month-old|my (child|baby)|the baby)\b", re.IGNORECASE)
OFF_TOPIC = re.compile(r"\b(campaign|speech|election|vote|poem|song|football|recipe|joke)\b", re.IGNORECASE)
ATTACK = re.compile(r"\b(which towers?\b.*\b(attack|hit|bomb|vandali[sz]e|target)|attack(ed)? next|next attack|"
                    r"predict\w*\b.*\b(attack|vandal|cut)|where will (insurgents|boko haram|vandals))", re.IGNORECASE)
MEASURED = re.compile(r"\b(lost power last|last week|yesterday|measured outage|outage log)\b", re.IGNORECASE)
WINDOWS = (7, 14, 40, 60)
WORD_N = {"one": 1, "a": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
SECTOR_RES = {
    "health": re.compile(r"\b(hospitals?|health|clinics?|maternal|patients?)\b", re.IGNORECASE),
    "water": re.compile(r"\b(water|boreholes?|pumping|pumps?)\b", re.IGNORECASE),
    "cold": re.compile(r"\b(cold[- ]chain|cold rooms?|markets?|ice|fish|freezers?)\b", re.IGNORECASE),
}
SECTOR_LABEL = {"health": "health facilities", "water": "water", "cold": "market cold rooms"}
SECTOR_SITES = {"health": "health facilities", "water": "water sites", "cold": "market cold rooms"}


def parse_question(q: str) -> dict:
    out: dict = {}
    m = MONEY.search(q)
    if m:
        out["budget"] = float(m.group("num").replace(",", "")) * SCALE.get((m.group("scale") or "").lower(), 1.0)
        out["currency"] = "USD" if m.group("cur").upper() in ("US$", "USD", "$") else "NGN"
    c = CITY_RE.search(q)
    if c:
        out["city"] = c.group(1).lower()
    days = None
    mm = re.search(r"\b(\d+|one|a|two|three|four|five|six|seven|eight)\s+(day|week|month)s?\b", q, re.IGNORECASE)
    if mm:
        n = int(mm.group(1)) if mm.group(1).isdigit() else WORD_N[mm.group(1).lower()]
        days = n * {"day": 1, "week": 7, "month": 30}[mm.group(2).lower()]
    out["days"] = min(WINDOWS, key=lambda w: (abs(w - days), -w)) if days else 60
    out["sectors"] = [k for k, r in SECTOR_RES.items() if r.search(q)] or ["health", "water", "cold"]
    return out


def pct(x) -> str:
    """The API's share rule (one decimal, half up, 99.9 cap) with more decimals where the cap would round."""
    if not isinstance(x, (int, float)) or not math.isfinite(x):
        return "unknown"
    if x >= 1:
        return "100%"
    v = math.floor(x * 1000 + 0.5 + 1e-9) / 10
    if v >= 100:
        return f"{x * 100:.2f}%"
    return f"{v:g}%"


def money(n) -> str:
    n = float(n)
    if abs(n) >= 1e9:
        return f"N{n / 1e9:.3f}".rstrip("0").rstrip(".") + " billion"
    if abs(n) >= 1e6:
        return f"N{n / 1e6:.1f}".rstrip("0").rstrip(".") + " million"
    return f"N{n:,.0f}"


def _sectors_phrase(secs: list[str]) -> str:
    names = [SECTOR_LABEL[s] for s in secs]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def compose_answer(plan: dict, site: dict | None, cost: dict | None, fabricate: bool = False) -> str:
    t, pc = plan["totals"], plan["cite"]
    money_in = (f"US${plan['budget']:,.0f} ({money(plan['budget_ngn'])} at N{plan['fx']['ngn_per_usd']:,.3f} per US$)"
                if plan["currency"] == "USD" else money(plan["budget_ngn"]))
    lines = [f"**{plan['city_name']}, a {plan['days']} day line outage: {money_in} for "
             f"{_sectors_phrase(plan['sectors'])}** [{pc}]", ""]
    lines.append(f"Funded in plan order: {t['funded_count']:,} of {t['candidates']:,} critical sites, spending "
                 f"{money(t['spent_ngn'])} and leaving {money(t['remaining_ngn'])} [{pc}].")
    lines.append(f"Critical service-hours kept through the outage: {pct(t['share_today'])} today with no backup, "
                 f"{pct(t['share_with_funded'])} with the funded sites, of {t['csh_needed']:,.0f} needed [{pc}]. "
                 f"Every site built would keep {pct(t['share_with_every_site'])} [{pc}].")
    lines.append(f"Diesel the funded systems avoid in the window: {t['diesel_l_avoided']:,.0f} litres, about "
                 f"{money(t['diesel_ngn_avoided'])} at N{t['diesel_ngn_per_l']:,.2f} per litre [{pc}].")
    if fabricate:
        lines.append("That serves about 987,654 more people every day.")
    w = plan.get("water") or {}
    if "water" in plan["sectors"] and w.get("m3_per_day_with_funded") and w["m3_per_day_with_funded"] > w["m3_per_day_today"]:
        lines.append(f"Water kept: {w['m3_per_day_with_funded']:,.0f} m3 a day with the funded sites against "
                     f"{w['m3_per_day_today']:,.0f} today, enough for up to {w['people_with_funded_upper']:,.0f} "
                     f"people at the Sphere minimum [{pc}].")
    lines += ["", f"By sector [{pc}]:"]
    for k, v in plan["by_sector"].items():
        if v["in_scope"]:
            lines.append(f"- {SECTOR_LABEL[k].capitalize()}: {v['funded']:,} of {v['sites']:,} funded, "
                         f"{pct(v['share_today'])} of their critical service-hours kept today, "
                         f"{pct(v['share_with_funded'])} with the funded sites")
    if plan["funded_top"]:
        lines += ["", f"Top of the list [{pc}]:"]
        for i, x in enumerate(plan["funded_top"][:3], 1):
            lines.append(f"{i}. {x['name']} ({x['lga']}, {x['sector']}): {x['pv_kwp']:g} kWp and "
                         f"{x['battery_kwh']:g} kWh of battery for {money(x['capex_ngn'])}; keeps "
                         f"{x['with_h']:,.0f} of {x['needed_h']:,.0f} critical service-hours ({x['today_h']:,.0f} "
                         f"today)")
    if site and not site.get("error"):
        st = site["siting"]
        fit = {"fits": "fits on its own roof", "partial": "fits partly on its own roof",
               "ground": "goes on the ground inside the compound wall",
               "unknown": "has no mapped roof, so the fit is unknown"}.get(st.get("roof_fit"), "has no roof check")
        line = f"Siting for the first pick [{site['cite']}]: it {fit}"
        if isinstance(st.get("roof_kwp"), dict) and st["roof_kwp"].get("point"):
            line += f" (about {st['roof_kwp']['point']:g} kWp of roof)"
        line += (f"; {st['km_to_330kv']:g} km from the {st['line_kv']} kV line; {st['new_line_km']} km of new line; "
                 f"{st['battery_room']}.") if st.get("km_to_330kv") is not None else "."
        lines += ["", line]
    if cost and not cost.get("error"):
        cp = cost["cost_per_kwh_ngn"]
        sol, dsl, gas = cp.get("solar") or {}, cp.get("diesel") or {}, cp.get("gas_support") or {}
        line = (f"Cost per kWh delivered [{cost['cite']}]: solar + storage N{sol['point']:,.0f} (N{sol['lo']:,.0f} to "
                f"N{sol['hi']:,.0f}), diesel N{dsl['point']:,.0f}.")
        # the gas plant (MEPP) serves Maiduguri; TCN sent Damaturu power over a 33 kV line from Potiskum (2024)
        if cost.get("city") == "maiduguri" and gas.get("point") is not None and gas["point"] < sol["point"]:
            mw = next(iter(cost.get("gas_support_at_mw") or {}), None)
            line += (f" When it runs, the gas plant costs less: about N{gas['point']:,.0f} of federal operating support "
                     f"per kWh" + (f" at {mw} MW delivered" if mw else "") + ". The plan works alongside the plant "
                     "and replaces the diesel critical sites burn when the line or the plant fails.")
        lines += ["", line]
    groups = [(k, v) for k, v in plan["by_sector"].items() if v["in_scope"] and v["not_funded"]]
    if groups:
        rest = "; ".join(f"{money(v['capex_to_fund_the_rest_ngn'])} for the {v['not_funded']:,} "
                         f"{SECTOR_SITES[k]} not funded" for k, v in groups)
        lines += ["", f"What the money does not reach [{pc}]: {t['not_funded_count']:,} sites in scope rank below "
                      f"the funded ones or did not fit what was left. Funding the rest would cost {rest}."]
    lines += ["", "Labels: grid supply is modelled from NERC's band promise, promised and not measured; critical "
                  "loads are archetypes, not measured per site; diesel is priced at the national average."]
    return "\n".join(lines)


class RuleBasedCityPlannerModel:
    """See the module docstring. kind = "scripted"."""

    kind = "scripted"
    model_name = "scripted-rule-based (no language model)"

    def __init__(self, fabricate_first: bool = False):
        self.fabricate_first = fabricate_first
        self.calls = 0

    def chat(self, messages: list[dict], tools=None, max_tokens: int = 900) -> ChatResponse:
        self.calls += 1
        msg = normalise_message(self._next(messages))
        return ChatResponse(msg, {"prompt_tokens": estimate_tokens(messages),
                                  "completion_tokens": estimate_tokens(msg)}, self.model_name)

    @staticmethod
    def _refuse(reason: str, explanation: str) -> dict:
        return assistant(calls=[tool_call("refuse", {"reason": reason, "explanation": explanation}, "call_refuse")])

    def _next(self, messages: list[dict]) -> dict:
        q = next(m["content"] for m in messages if m["role"] == "user")
        done = _tool_results(messages)
        k = len(done)
        if k == 0:
            if MEDICAL.search(q) or OFF_TOPIC.search(q):
                return self._refuse("out_of_scope", "Wardlight answers questions about power for critical sites, "
                                    "health, water pumping and the cold chain, in Maiduguri, Damaturu and Yola. This "
                                    "question is outside that, so it is not answered here.")
            if ATTACK.search(q):
                return self._refuse("data_cannot_support", "Wardlight maps the transmission line and its towers "
                                    "from OpenStreetMap, but it holds no incident records to forecast attacks from, "
                                    "and it does not name targets. It plans for the line being cut at any time, as "
                                    "the brief asks.")
            if MEASURED.search(q):
                return self._refuse("data_cannot_support", "Wardlight has no measured outage logs per site; its "
                                    "service-hours are modelled for an outage window. The SMS verifier can ask a "
                                    "site what happened and record the reply.")
            p = parse_question(q)
            if "city" not in p:
                return self._refuse("data_cannot_support", "Wardlight's city build covers Maiduguri, Damaturu "
                                    "and Yola. Name one of them and a budget to rank its critical sites.")
            if "budget" not in p:
                return self._refuse("data_cannot_support", "The question needs a budget to rank the city's "
                                    "critical sites against.")
            return assistant(calls=[tool_call("rank_city_plan", {
                "city": p["city"], "budget": p["budget"], "currency": p["currency"], "days": p["days"],
                "sectors": p["sectors"], "top": 5}, "call_plan")])
        name, plan = done[0]
        if name == "rank_city_plan" and plan.get("error"):
            return self._refuse("data_cannot_support", f"The plan tool could not run: {plan['error']}")
        if k == 1:
            if plan.get("funded_top"):
                return assistant(calls=[tool_call("get_site", {"site_id": plan["funded_top"][0]["id"],
                                                               "days": plan["days"]}, "call_site")])
            return assistant(calls=[tool_call("cost_compare", {"city": plan["city"]}, "call_cost")])
        if k == 2 and done[1][0] == "get_site":
            return assistant(calls=[tool_call("cost_compare", {"city": plan["city"]}, "call_cost")])
        by = {n: r for n, r in done}
        retried = any(m["role"] == "user" and str(m.get("content", "")).startswith("GROUNDING CHECK FAILED")
                      for m in messages)
        return assistant(compose_answer(plan, by.get("get_site"), by.get("cost_compare"),
                                        fabricate=self.fabricate_first and not retried))
