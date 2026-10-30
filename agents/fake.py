"""A rule-based scripted stand-in for the planner model. NOT a language model and never presented as one.

It parses the question with fixed rules (state, budget, currency, priority, LGA, level), calls the same tools a
model would, and writes the answer from a template filled only with values copied from the tool results. It
exists to test the harness (tool loop, budgets, refusal path, grounding, checkers, event stream) and to record
fixture sessions labelled "scripted". With `fabricate_first=True` its first draft carries one invented number,
so the grounding block and the retry can be shown and tested.

It returns no text alongside tool calls, so its sessions contain no `reasoning` events: there is no model
reasoning to show, and none is synthesised.
"""

from __future__ import annotations

import json
import re

from .llm import ChatResponse, assistant, estimate_tokens, normalise_message, tool_call

NIGERIAN_STATES = (
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno", "Cross River", "Delta",
    "Ebonyi", "Edo", "Ekiti", "Enugu", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi",
    "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto",
    "Taraba", "Yobe", "Zamfara",
)
MEDICAL = re.compile(r"\b(dose of|doses should|symptom|fever|diagnos|treat(ment)?|prescri|side effect|"
                     r"nine-month-old|month-old|my (child|baby)|the baby)\b", re.IGNORECASE)
OFF_TOPIC = re.compile(r"\b(campaign|speech|election|poem|song|football|recipe|joke)\b", re.IGNORECASE)
MEASURED = re.compile(r"\b(lost vaccines|last month|last week|yesterday|measured temperature|temperature log|"
                      r"stock record)\b", re.IGNORECASE)
FOREIGN = re.compile(r"\b(Ghana|Kenya|Cameroon|Niger Republic|Benin Republic|Togo|Chad)\b", re.IGNORECASE)
MONEY = re.compile(r"(?P<cur>US\$|USD|\$|₦|NGN|N)\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<scale>million|billion|"
                   r"thousand|m|bn|k)?\b", re.IGNORECASE)
SCALE = {"million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "thousand": 1e3, "k": 1e3}
PRIORITY_LH = re.compile(r"\b(maternal|delivery|oxygen|emergency|suction)\b", re.IGNORECASE)


def parse_question(q: str) -> dict:
    out: dict = {}
    m = MONEY.search(q)
    if m:
        v = float(m.group("num").replace(",", "")) * SCALE.get((m.group("scale") or "").lower(), 1.0)
        out["budget"] = v
        out["currency"] = "USD" if m.group("cur").upper() in ("US$", "USD", "$") else "NGN"
    if re.search(r"\bFCT\b|\bAbuja\b", q):
        out["state"] = "FCT"
    for st in sorted(NIGERIAN_STATES, key=len, reverse=True):
        if "state" in out:
            break
        if re.search(rf"\b{re.escape(st)}\b(?!\s+LGA)", q):
            out["state"] = st
    fm = FOREIGN.search(q)
    if fm and "state" not in out:
        region = re.search(r"(?:in|for) (?:clinics in )?(?:the )?([A-Z][\w ]+? of [A-Z]\w+|[A-Z]\w+)", q)
        out["state"] = region.group(1) if region else fm.group(0)
    lg = re.search(r"\b([A-Z][\w-]+(?: [A-Z][\w-]+)?) LGA\b", q)
    if lg:
        out["lga"] = lg.group(1)
    if re.search(r"primary health cent", q, re.IGNORECASE):
        out["facility_level"] = "Primary"
    out["priority"] = "load_hours" if PRIORITY_LH.search(q) else "doses"
    return out


def _tool_results(messages: list[dict]) -> list[tuple[str, dict]]:
    """(tool name, parsed result) for every tool message, in order."""
    names = {}
    for m in messages:
        for tc in m.get("tool_calls") or []:
            names[tc["id"]] = tc["function"]["name"]
    out = []
    for m in messages:
        if m.get("role") == "tool":
            try:
                body = json.loads(m.get("content") or "{}")
            except ValueError:
                body = {"error": "unparseable"}
            out.append((names.get(m.get("tool_call_id"), "?"), body))
    return out


def _pct(x) -> str:
    return f"{x:.0%}" if isinstance(x, (int, float)) else "unknown"


def compose_answer(plan: dict, fac: dict | None, fabricate: bool = False) -> str:
    t = plan["totals"]
    pc = plan["cite"]
    where = plan["state"] + (f", {plan['lga']} LGA" if plan.get("lga") else "")
    if plan.get("facility_level"):
        where += f", {plan['facility_level'].lower()} level only"
    label = "vaccine doses first" if plan["priority"] == "doses" else "maternal and emergency care first"
    if plan["currency"] == "USD":
        money = f"US${plan['budget']:,.0f} (N{plan['budget_ngn']:,.0f} at N{plan['fx']['ngn_per_usd']:,.2f} per US$)"
    else:
        money = f"N{plan['budget_ngn']:,.0f}"
    lines = [f"**{where}: {money}, {label}** [{pc}]", ""]
    lines.append(f"The ranking funds {t['funded_count']:,} facilities and spends N{t['spent_ngn']:,.0f}, leaving "
                 f"N{t['remaining_ngn']:,.0f} [{pc}]. Their combined gain is {t['benefit_total']:,.0f} "
                 f"{t['benefit_unit']} [{pc}].")
    if fabricate:
        lines.append("That reaches about 987,654 more children every year.")
    lines += ["", "Top of the list:"]
    for i, x in enumerate(plan["funded_top"][:3], 1):
        lines.append(f"{i}. {x['name']} ({x['lga']}, tier {x['tier']}): {x['fix_label']}, N{x['cost_ngn']:,.0f}; "
                     f"{x['reason']} [{x['cite']}]")
    if fac and not fac.get("error"):
        ev = fac.get("nerc_rows") or []
        if ev:
            r = ev[0]
            lines += ["", f"Evidence for the first pick: NERC row {r['sn']} on page {r['page']} of {r['order_file']}, "
                          f"Band {r['band']}, promising {r['min_hours']:g} hours a day [{r['cite']}]."]
        elif fac.get("match", {}).get("reason"):
            lines += ["", f"Evidence for the first pick: {fac['match']['reason']} [{fac['cite']}]."]
    nr = plan["not_reached"]
    lines += ["", f"What the money does not reach: {nr['ranked_not_funded']['count']:,} ranked facilities wait for "
                  f"the next budget; {nr['unknown_supply']['count']:,} are not ranked because today's grid supply "
                  f"is unknown (refused match); {nr['no_engine_result']['count']:,} have no engine result in this "
                  f"data version [{pc}].",
              "", "Doses are estimates. Grid supply is modelled from NERC's band promise: promised, not measured."]
    return "\n".join(lines)


class RuleBasedPlannerModel:
    """See the module docstring. kind = "scripted"."""

    kind = "scripted"
    model_name = "scripted-rule-based (no language model)"

    def __init__(self, fabricate_first: bool = False):
        self.fabricate_first = fabricate_first
        self.calls = 0

    def chat(self, messages: list[dict], tools=None, max_tokens: int = 900) -> ChatResponse:
        self.calls += 1
        msg = normalise_message(self._next(messages))
        return ChatResponse(msg, {"prompt_tokens": estimate_tokens(messages), "completion_tokens": estimate_tokens(msg)},
                            self.model_name)

    def _next(self, messages: list[dict]) -> dict:
        q = next(m["content"] for m in messages if m["role"] == "user")
        done = _tool_results(messages)
        k = len(done)
        if k == 0:
            if MEDICAL.search(q) or OFF_TOPIC.search(q):
                return assistant(calls=[tool_call("refuse", {
                    "reason": "out_of_scope",
                    "explanation": "Wardlight answers questions about power and the vaccine cold chain for Nigerian "
                                   "health facilities. This question is outside that, so it is not answered here."},
                    "call_refuse")])
            if MEASURED.search(q):
                return assistant(calls=[tool_call("refuse", {
                    "reason": "data_cannot_support",
                    "explanation": "Wardlight has no measured fridge temperatures, vaccine stock records or "
                                   "outage logs for any facility; its uptimes are modelled from NERC's promised "
                                   "supply. It cannot say which clinics lost vaccines."}, "call_refuse")])
            p = parse_question(q)
            if FOREIGN.search(q) and p.get("state") not in NIGERIAN_STATES + ("FCT",):
                return assistant(calls=[tool_call("refuse", {
                    "reason": "data_cannot_support",
                    "explanation": "Wardlight's data covers Nigerian health facilities (GRID3) and NERC's Nigerian "
                                   "feeder orders only, so it cannot plan for a place outside Nigeria."},
                    "call_refuse")])
            if "state" not in p or "budget" not in p:
                return assistant(calls=[tool_call("refuse", {
                    "reason": "data_cannot_support",
                    "explanation": "The question needs a Nigerian state and a budget to rank facilities."},
                    "call_refuse")])
            args = {"state": p["state"], "budget": p["budget"], "currency": p["currency"],
                    "priority": p["priority"], "top": 5}
            for key in ("lga", "facility_level"):
                if key in p:
                    args[key] = p[key]
            return assistant(calls=[tool_call("rank_budget", args, "call_rank")])
        name, plan = done[0]
        if name == "rank_budget" and plan.get("error"):
            return assistant(calls=[tool_call("refuse", {
                "reason": "data_cannot_support", "explanation": f"The ranking tool could not run: {plan['error']}"},
                "call_refuse")])
        if k == 1 and plan.get("funded_top"):
            return assistant(calls=[tool_call("get_facility", {"unique_id": plan["funded_top"][0]["unique_id"]},
                                              "call_fac")])
        fac = done[1][1] if k > 1 else None
        retried = any(m["role"] == "user" and str(m.get("content", "")).startswith("GROUNDING CHECK FAILED")
                      for m in messages)
        return assistant(compose_answer(plan, fac, fabricate=self.fabricate_first and not retried))
