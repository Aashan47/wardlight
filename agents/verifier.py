"""The verifier agent: asks a clinic by SMS or USSD what the model cannot know, and narrows the facility's interval.

SANDBOX ONLY. It is demonstrated on the Africa's Talking sandbox with replies typed into the simulator, and every
output says "sandbox, simulated replies". No real clinic is contacted by this code; the transport (the API, agent E)
decides where messages go.

Questions (each fits one SMS):
  fridge      which fridge holds the vaccines: 1 ice-lined, 2 solar, 3 household, 4 none
  grid_hours  hours of grid power yesterday, 0 to 24
  typical     optional: was yesterday a usual day for power (1 yes, 2 no, 0 skip)

Replies are parsed by rules (menu numbers, digits, a few keywords and number words). A free-text reply the rules
cannot read goes to the model, which must call `record_answer` with a verbatim quote from the reply; the value is
accepted only if the quote is in the reply and, for hours, the number is in the quote. An ambiguous reply is asked
again once; a second failure records the answer as unknown and moves on.

How the answers change the model (both MODELLED, both shown with before and after):
- fridge type picks the equipment scenario: before, today's uptime is the envelope over the scenarios (PQS
  ice-lined, domestic, solar direct-drive); after, the one scenario the clinic named ("none" is scenario c, not
  modelled: vaccines must come from outreach, so no interval is shown);
- yesterday's hours enter the supply model as an observation, never as a band: the band-promise supply is
  replaced by daily grid hours drawn around the reported value (normal, sd HOURS_SD = 2 h, an ASSUMPTION for one
  recalled day), with the engine's outage-timing pattern (`engine_adapter.coldchain_observed_hours`). The reply is
  also scored against the prior band mixture: the share of the mixture's modelled days within 2 h of it
  (`engine_adapter.prior_predictive`). Below CONTRADICTION_P (5%) the reply contradicts the prior and the event
  says so. If the clinic says yesterday was not a usual day, the observation is withdrawn and the band model
  returns (the event says the interval widened because evidence was withdrawn).

Every re-run reports the width before and after; an answer consistent with the prior should not widen the
interval, and any widening is stated in the event with its reason (`widened`, `contradicts_prior`, `note`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from . import engine_adapter as EA
from . import events as EV
from . import grounding as G
from .llm import ChatClient, LLMError

LABEL = "sandbox, simulated replies"
QUESTIONS = {
    "fridge": "Wardlight (sandbox): which fridge holds your vaccines? Reply 1 ice-lined, 2 solar, 3 household, "
              "4 none",
    "grid_hours": "How many hours of grid power did the clinic have yesterday? Reply one number from 0 to 24",
    "typical": "Optional: was yesterday a usual day for power? Reply 1 yes, 2 no, 0 skip",
}
REASK = {
    "fridge": "Sorry, please reply with one number: 1 ice-lined, 2 solar, 3 household, 4 none",
    "grid_hours": "Sorry, please reply with one number of hours from 0 to 24, for example 9",
    "typical": "Sorry, please reply 1 yes, 2 no or 0 skip",
}
ORDER = ("fridge", "grid_hours", "typical")
FRIDGE = {1: "ice_lined", 2: "solar", 3: "household", 4: "none"}
FRIDGE_LABEL = {"ice_lined": "PQS ice-lined (mains) fridge", "solar": "solar direct-drive fridge",
                "household": "household or non-PQS fridge", "none": "no fridge (vaccines from outreach)"}
SCENARIO_KEY = {"ice_lined": "today_pqs_ice_lined", "household": "today_domestic", "solar": "solar_direct_drive"}
FRIDGE_WORDS = {
    1: (r"\bice[- ]?lined\b", r"\bilr\b", r"\bice\b"),
    2: (r"\bsolar\b", r"\bsdd\b", r"\bpanel"),
    3: (r"\bhouse(hold)?\b", r"\bdomestic\b", r"\bhome\b", r"\bkitchen\b", r"\bnormal fridge\b"),
    4: (r"\bnone\b", r"\bno fridge\b", r"\bnothing\b"),
}
MAX_SMS = 160


@dataclass
class Parsed:
    status: str  # ok | ambiguous | unparsed
    value: object = None
    by: str = "rule"
    quote: str | None = None


# ---------------------------------------------------------------- rule parsers


def parse_fridge(text: str) -> Parsed:
    t = text.strip().lower()
    digits = re.findall(r"\b[1-4]\b", t)
    other_digits = re.findall(r"\d+", t)
    if digits and len(set(digits)) == 1 and len(other_digits) == 1:
        return Parsed("ok", FRIDGE[int(digits[0])])
    if len(set(digits)) > 1 or (other_digits and not digits):
        return Parsed("ambiguous")
    hits = {k for k, pats in FRIDGE_WORDS.items() if any(re.search(p, t) for p in pats)}
    if len(hits) == 1:
        return Parsed("ok", FRIDGE[hits.pop()])
    if len(hits) > 1:
        return Parsed("ambiguous")
    return Parsed("unparsed")


def parse_hours(text: str) -> Parsed:
    t = text.strip().lower()
    if re.search(r"\b(all day|24/7|full day|whole day|non[- ]?stop)\b", t):
        return Parsed("ok", 24.0)
    if re.search(r"\b(none|no light|no power|nothing|not at all|zero)\b", t):
        return Parsed("ok", 0.0)
    nums = G.numbers_in(t)
    if len(nums) == 1:
        v = nums[0]
        return Parsed("ok", float(v)) if 0 <= v <= 24 else Parsed("ambiguous")
    if len(nums) > 1:
        return Parsed("ambiguous")
    return Parsed("unparsed")


def parse_typical(text: str) -> Parsed:
    t = text.strip().lower()
    if re.fullmatch(r"\s*(1|yes|y|yeah|yep|usual|normal)\s*[.!]?", t):
        return Parsed("ok", "yes")
    if re.fullmatch(r"\s*(2|no|n|nope|not usual)\s*[.!]?", t):
        return Parsed("ok", "no")
    if re.fullmatch(r"\s*(0|skip|s)\s*[.!]?", t):
        return Parsed("ok", "skip")
    return Parsed("unparsed")


RULES: dict[str, Callable[[str], Parsed]] = {"fridge": parse_fridge, "grid_hours": parse_hours,
                                              "typical": parse_typical}


# ---------------------------------------------------------------- free text through the model (grounded)


RECORD_TOOL = {"type": "function", "function": {
    "name": "record_answer",
    "description": "Record the clinic's answer to the question, quoting the exact words of the reply it rests on. "
                   "Call with value null if the reply does not answer the question.",
    "parameters": {"type": "object", "properties": {
        "value": {"type": ["number", "null"]},
        "quote": {"type": "string"}}, "required": ["value", "quote"]}}}
EXTRACT_PROMPT = ("You read one SMS reply from a health clinic. Question asked: {q}\nMap the reply to the answer: "
                  "for the fridge question a number 1 to 4; for hours a number 0 to 24; for the usual-day question "
                  "1 yes, 2 no, 0 skip. Quote the exact words of the reply that give the answer. Never guess.")


class ModelExtractor:
    """Free-text replies through the model, accepted only when grounded in the reply's own words."""

    def __init__(self, client: ChatClient):
        self.client = client
        self.reasoning: list[str] = []

    def __call__(self, field_: str, reply: str) -> Parsed:
        msgs = [{"role": "system", "content": EXTRACT_PROMPT.format(q=QUESTIONS[field_])},
                {"role": "user", "content": reply}]
        try:
            r = self.client.chat(msgs, [RECORD_TOOL], 200)
        except LLMError:
            return Parsed("unparsed")
        m = r.message
        if m.get("content"):
            self.reasoning.append(m["content"])
        calls = [c for c in m.get("tool_calls") or [] if c["function"]["name"] == "record_answer"]
        if not calls:
            return Parsed("unparsed")
        try:
            a = json.loads(calls[0]["function"]["arguments"])
        except ValueError:
            return Parsed("unparsed")
        v, quote = a.get("value"), str(a.get("quote") or "")
        if v is None or not quote or quote.lower() not in reply.lower():
            return Parsed("ambiguous")
        try:
            v = float(v)
        except (TypeError, ValueError):
            return Parsed("ambiguous")
        if field_ == "grid_hours":
            grounded = any(abs(x - v) < 1e-9 for x in G.numbers_in(quote))
            if not grounded or not 0 <= v <= 24:
                return Parsed("ambiguous")
            return Parsed("ok", v, "model", quote)
        if field_ == "fridge" and int(v) in FRIDGE and v == int(v):
            return Parsed("ok", FRIDGE[int(v)], "model", quote)
        if field_ == "typical" and v in (0, 1, 2):
            return Parsed("ok", {1: "yes", 2: "no", 0: "skip"}[int(v)], "model", quote)
        return Parsed("ambiguous")


# ---------------------------------------------------------------- the supply observation

HOURS_SD = 2.0  # ASSUMPTION: spread of daily grid hours around one recalled day; no source
CONTRADICTION_P = 0.05  # a reply this unlikely under the prior band mixture is reported as contradicting it


# ---------------------------------------------------------------- the session


def pct(x: float) -> str:
    """A share as a percentage; one decimal below 10% so a small figure does not read as 0%."""
    return f"{x:.1%}" if 0 < x < 0.1 else f"{x:.0%}"


@dataclass
class Facility:
    unique_id: str
    name: str
    lat: float
    lon: float
    tier: str
    bands: dict | str | None  # mixture, "OFFGRID", or None (refused)


def facility_from_data(data, unique_id: str) -> Facility:
    r = data.row(unique_id)
    tier = str(r.get("match_tier") or r.get("tier"))
    return Facility(unique_id, str(r.get("facility_name")), float(r.latitude), float(r.longitude), tier,
                    EA.bands_for(tier, r.get("match_bands")))


def _interval_of(sim: dict, fridge: str | None) -> dict | None:
    if fridge is None:  # unknown equipment: envelope over the modelled scenarios
        ivs = [sim.get(k) for k in ("today_pqs_ice_lined", "today_domestic", "solar_direct_drive") if sim.get(k)]
        if not ivs:
            return None
        lo, hi = min(i["lo"] for i in ivs), max(i["hi"] for i in ivs)
        return {"point": None, "lo": lo, "hi": hi, "width": hi - lo, "scenario": "unknown equipment (envelope)"}
    if fridge == "none":
        return None
    iv = sim.get(SCENARIO_KEY[fridge])
    if not iv:
        return None
    return {**iv, "width": iv["hi"] - iv["lo"], "scenario": FRIDGE_LABEL[fridge]}


@dataclass
class VerifierSession:
    facility: Facility
    channel: str = "sms"  # sms | ussd
    extractor: Callable[[str, str], Parsed] | None = None
    simulate: Callable[..., dict] = EA.coldchain
    simulate_hours: Callable[..., dict] = EA.coldchain_observed_hours
    predictive: Callable[..., float | None] = EA.prior_predictive
    n_draws: int = 16
    log: EV.EventLog = field(default_factory=EV.EventLog)
    answers: dict = field(default_factory=dict)
    sms: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    model_name: str = "rules only"
    _i: int = 0
    _asked_twice: bool = False
    _call_n: int = 0
    _open_call: str | None = None
    before: dict | None = None
    current: dict | None = None
    observed_hours: float | None = None  # None: supply from the band mixture
    finished: bool = False

    # -------------------------------------------------- helpers

    @property
    def supply(self) -> str:
        if self.observed_hours is not None:
            return f"reported {self.observed_hours:g} h a day, sd {HOURS_SD:g} h (assumption)"
        return f"band mixture {EA.bands_key(self.facility.bands)}"

    def _sim(self) -> dict:
        f = self.facility
        if self.observed_hours is not None:
            return self.simulate_hours(f.lat, f.lon, self.observed_hours, HOURS_SD, self.n_draws)
        return self.simulate(f.lat, f.lon, f.bands, self.n_draws)

    def _state(self) -> dict:
        sim = self._sim()
        return {"supply": self.supply, "bands": EA.bands_key(self.facility.bands),
                "observed_hours": self.observed_hours,
                "interval": _interval_of(sim, self.answers.get("fridge")),
                "sim": {k: sim.get(k) for k in ("today_pqs_ice_lined", "today_domestic", "solar_direct_drive",
                                                "fix_label", "fix_category")}}

    def _call(self, name: str, **args) -> tuple[list[dict], str]:
        self._call_n += 1
        cid = f"v{self._call_n}"
        return [self.log.emit("tool_call", id=cid, name=name, args=args)], cid

    def _ask(self, text: str) -> list[dict]:
        assert len(text) <= MAX_SMS
        evs, cid = self._call("ask_clinic", channel=self.channel, message=text)
        self._open_call = cid
        self.sms.append({"from": "wardlight", "text": text})
        return evs

    def _rerun(self, why: str, contradicts: bool = False, prior_p: float | None = None,
               withdrawn: bool = False) -> list[dict]:
        t = self.log.ms()
        evs, cid = self._call("simulate", unique_id=self.facility.unique_id, supply=self.supply,
                              fridge=self.answers.get("fridge"), why=why)
        prev = self.current["interval"] if self.current else None
        self.current = self._state()
        iv = self.current["interval"]
        w0 = prev["width"] if prev else None
        w1 = iv["width"] if iv else None
        widened = bool(w0 is not None and w1 is not None and w1 > w0 + 1e-9)
        if widened and withdrawn:
            note = "the interval widened because the hours reply was withdrawn (not a usual day)"
        elif widened and contradicts:
            note = "the interval widened: the reply contradicts the prior supply model, which is now replaced by it"
        elif widened:
            note = "the interval widened although the reply is consistent with the prior"
        elif prev is None and self.before is None:
            note = "baseline"
        else:
            note = "the interval did not widen"
        summ = ("no interval: no fridge at the clinic (scenario c, not modelled)" if iv is None else
                f"today {pct(iv['lo'])} to {pct(iv['hi'])} of days held at 2 to 8 degC ({iv['scenario']})")
        evs.append(self.log.emit("tool_result", id=cid, summary=summ, rows=1, ms=self.log.ms() - t, interval=iv,
                                 supply=self.current["supply"], width_before=w0, width_after=w1, widened=widened,
                                 contradicts_prior=contradicts, prior_predictive=prior_p, note=note))
        self.steps.append({"why": why, "interval": iv, "width_before": w0, "widened": widened,
                           "contradicts_prior": contradicts, "prior_predictive": prior_p, "note": note})
        return evs

    # -------------------------------------------------- flow

    def start(self) -> list[dict]:
        evs = [self.log.emit("plan", steps=[
            {"id": "baseline", "title": "Model the facility before asking"},
            {"id": "ask_fridge", "title": "Ask which fridge holds the vaccines"},
            {"id": "ask_grid_hours", "title": "Ask yesterday's grid hours"},
            {"id": "ask_typical", "title": "Ask if yesterday was usual (optional)"},
            {"id": "answer", "title": "Show the interval before and after"}])]
        evs.append(self.log.emit("step_start", id="baseline"))
        evs += self._rerun("baseline: equipment unknown")
        self.before = self.current
        evs.append(self.log.emit("step_start", id="ask_fridge"))
        evs += self._ask(QUESTIONS["fridge"])
        return evs

    @property
    def field(self) -> str | None:
        return ORDER[self._i] if self._i < len(ORDER) else None

    @property
    def outbox(self) -> str | None:
        """The text waiting for the clinic's reply (None when finished)."""
        return None if self.finished else self.sms[-1]["text"]

    def handle(self, reply: str) -> list[dict]:
        if self.finished or self.field is None:
            return []
        f = self.field
        self.sms.append({"from": "clinic", "text": reply})
        p = RULES[f](reply)
        if p.status == "unparsed" and self.extractor is not None:
            p = self.extractor(f, reply)
        evs = []
        if p.by == "model" and getattr(self.extractor, "reasoning", None):
            evs.append(self.log.emit("reasoning", text=self.extractor.reasoning[-1], source="model"))
        evs.append(self.log.emit("tool_result", id=self._open_call, summary=f"reply: {reply[:120]}", rows=1, ms=0,
                                 reply=reply, parsed=p.value, parse_status=p.status, parsed_by=p.by, quote=p.quote))
        self._open_call = None
        if p.status != "ok":
            if not self._asked_twice:
                self._asked_twice = True
                evs += self._ask(REASK[f])
                return evs
            self.answers[f] = None
            self.notes.append(f"{f}: no clear answer after one re-ask; recorded as unknown")
        else:
            self.answers[f] = p.value
            evs += self._apply(f, p.value)
        self._asked_twice = False
        self._i += 1
        nxt = self.field
        if nxt is None:
            evs += self._finish()
        else:
            evs.append(self.log.emit("step_start", id=f"ask_{nxt}"))
            evs += self._ask(QUESTIONS[nxt])
        return evs

    def _apply(self, f: str, v) -> list[dict]:
        fac = self.facility
        if f == "fridge":
            return self._rerun(f"fridge reported: {FRIDGE_LABEL[v]}")
        if f == "grid_hours":
            if fac.bands is None:
                self.notes.append("grid supply is unknown for this facility (refused match); the reported hours are "
                                  "recorded, not modelled from one day")
                return []
            p = self.predictive(fac.bands, float(v), HOURS_SD)
            contradicts = p is not None and p < CONTRADICTION_P
            if contradicts:
                self.notes.append(f"the reported {v:g} hours are unlikely under the matched supply "
                                  f"({p:.0%} of modelled days within {HOURS_SD:g} h): the reply contradicts the "
                                  "prior and replaces it")
            else:
                self.notes.append(f"the reported {v:g} hours replace the band promise as the supply model")
            self.observed_hours = float(v)
            return self._rerun(f"grid hours reported: {v:g}", contradicts=contradicts, prior_p=p)
        if f == "typical" and v == "no" and self.observed_hours is not None:
            self.notes.append("yesterday was not a usual day, so the hours reply is withdrawn")
            self.observed_hours = None
            return self._rerun("hours reply withdrawn: not a usual day", withdrawn=True)
        return []

    def _finish(self) -> list[dict]:
        self.finished = True
        evs = [self.log.emit("step_start", id="answer")]
        b, a = self.before["interval"], self.current["interval"]
        lines = [f"**{self.facility.name}** ({LABEL})", ""]
        if b:
            lines.append(f"Before asking: today's fridge uptime between {pct(b['lo'])} and {pct(b['hi'])} of days "
                         f"({b['scenario']}).")
        if a:
            lines.append(f"After the replies: between {pct(a['lo'])} and {pct(a['hi'])} ({a['scenario']}; supply: "
                         f"{self.current['supply']}).")
        elif self.answers.get("fridge") == "none":
            lines.append("After the replies: the clinic has no vaccine fridge, so there is no uptime to model; "
                         f"the recommended fix stays: {self.current['sim']['fix_label']}.")
        lines += [f"Note: {n}" for n in self.notes]
        lines.append("Modelled: grid supply from the clinic's one reported day, with an assumed spread."
                     if self.observed_hours is not None else
                     "Modelled: grid supply from NERC's band promise, promised and not measured.")
        md = "\n".join(lines)
        # the text is checked against the computed states and answers, not against its own notes
        pool = [self.before, self.current, self.steps, self.answers, {"hours_sd": HOURS_SD}]
        rep = G.check(md, pool, require_citation=False)
        evs.append(self.log.emit("check", kind="grounding", numbers_checked=rep.n_total,
                                 unmatched=[c.text for c in rep.unmatched] + rep.unknown_tokens,
                                 matches=[{"text": c.text, "value": c.value, "matched": c.matched}
                                          for c in rep.claims], ok=rep.ok))
        if not rep.ok:
            md = f"**{self.facility.name}** ({LABEL}): the summary could not be grounded, so only the data is shown."
            evs.append(self.log.emit("error", message="verifier summary blocked by the grounding check"))
        narrowed = (b["width"] - a["width"]) if (a and b) else None
        totals = {"before": b, "after": a, "narrowed_by": narrowed, "answers": self.answers,
                  "supply_before": self.before["supply"], "supply_after": self.current["supply"],
                  "steps": self.steps, "label": LABEL}
        evs.append(self.log.emit("answer", markdown=md, funded=[], not_reached=[], totals=totals, sms=self.sms,
                                 notes=self.notes))
        evs.append(self.log.emit("done", model=self.model_name, tokens=0, cost_usd=0.0 if self.extractor is None
                                 else None, recorded=False, duration_ms=self.log.ms(), label=LABEL))
        return evs

    def record(self) -> dict:
        return {"label": LABEL, "facility": self.facility.__dict__, "answers": self.answers, "sms": self.sms,
                "before": self.before, "after": self.current, "notes": self.notes, "events": self.log.events}


def run_events(facility: Facility, replies: list[str], **kw) -> Iterator[dict]:
    """A whole conversation with given (sandbox, simulated) replies, as an event stream."""
    s = VerifierSession(facility, **kw)
    yield from s.start()
    for r in replies:
        if s.finished:
            break
        yield from s.handle(r)


def ussd(facility: Facility, text: str, **kw) -> str:
    """Africa's Talking USSD callback: `text` is every reply so far joined by '*'. Returns 'CON ...' or 'END ...'."""
    s = VerifierSession(facility, channel="ussd", **kw)
    s.start()
    for r in [x for x in text.split("*")] if text else []:
        s.handle(r)
    if s.finished:
        a = s.current["interval"]
        tail = (f"fridge days held {pct(a['lo'])} to {pct(a['hi'])}" if a else "no fridge to model")
        return f"END Thank you. Wardlight (sandbox): {tail}."
    return f"CON {s.outbox}"

