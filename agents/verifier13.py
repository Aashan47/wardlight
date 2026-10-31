"""The brief 13 verifier: an SMS check that turns a site's modelled backup assumption into reported data.

SANDBOX ONLY, like `agents/verifier.py`: demonstrated on the Africa's Talking sandbox with replies typed into the
simulator, and every output says "sandbox, simulated replies". No real site is contacted by this code.

What the build cannot know about a site, and asks (each question fits one SMS):
  pump       water sites, to the borehole committee: how is the pump powered (1 solar, 2 generator, 3 grid,
             4 hand pump)? Checked against the iMMAP 2019 survey's archetype (motorized or solar borehole).
  generator  every site: is there a working generator (1 yes, 2 no)? The city scoreboard's "today with diesel"
             scenario ASSUMES every site has one, with fuel, for the whole window.
  gen_hours  asked only after a yes: how many hours did it run last week (0 to 168)?
  fridge     health sites, to the officer in charge: which fridge holds the vaccines (the vaccine fridge is one
             critical load inside a health site)?

How a reply changes the site's figures (all from the site's own engine results for the 7-day window, the
generator curves and the diesel price in the metrics file; nothing is re-simulated from one SMS):
- before: critical service-hours kept in a week of line cut, between `today_h` (no backup) and `needed_h` (the
  diesel scenario's every hour), because the backup is unknown;
- "no generator": the interval closes on `today_h`, and the diesel scenario is withdrawn for this site;
- a generator that ran H hours: for a single-load site with a stated pumping or cold-room schedule (water, cold),
  kept = min(needed, max(today, H)) clock-hours (REPORTED hours against the site's own schedule); litres =
  H x the site's critical kW x the sector's generator curve, and naira at the diesel price (DERIVED from a
  reported count). Health sites carry several loads, so their interval stays open and only the litres are
  reported;
- a pump type that contradicts the survey is recorded as a contradiction and the site is flagged for a survey,
  never re-run from one SMS.
An unreadable reply is asked again once; a second failure records the answer as unknown.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from . import city13 as C13
from . import events as EV
from . import grounding as G

LABEL = "sandbox, simulated replies"
WEEK = 7
MAX_SMS = 160
WHO = {"water": "the borehole committee", "health": "the officer in charge", "cold": "the market association"}
QUESTIONS = {
    "pump": "Wardlight (sandbox): how is the borehole pump powered? Reply 1 solar, 2 generator, 3 grid, 4 hand pump",
    "generator": "Wardlight (sandbox): does the site have a working generator? Reply 1 yes, 2 no",
    "gen_hours": "How many hours did the generator run last week? Reply one number from 0 to 168",
    "fridge": "Which fridge holds your vaccines? Reply 1 ice-lined, 2 solar, 3 household, 4 none",
}
REASK = {
    "pump": "Sorry, please reply with one number: 1 solar, 2 generator, 3 grid, 4 hand pump",
    "generator": "Sorry, please reply 1 yes or 2 no",
    "gen_hours": "Sorry, please reply with one number of hours from 0 to 168, for example 10",
    "fridge": "Sorry, please reply with one number: 1 ice-lined, 2 solar, 3 household, 4 none",
}
ORDER = {"water": ("pump", "generator", "gen_hours"), "health": ("generator", "gen_hours", "fridge"),
         "cold": ("generator", "gen_hours")}
PUMP = {1: "solar", 2: "generator", 3: "grid", 4: "hand pump"}
FRIDGE = {1: "PQS ice-lined (mains) fridge", 2: "solar direct-drive fridge", 3: "household or non-PQS fridge",
          4: "no fridge (vaccines from outreach)"}
SURVEY_PUMP = {"motorized_borehole": ("generator", "grid"), "solar_borehole": ("solar",)}
GEN_CURVE = {"health": "GEN_L_PER_KWH", "water": "GEN_L_PER_KWH_MID", "cold": "GEN_L_PER_KWH_MID"}


@dataclass
class Parsed:
    status: str  # ok | ambiguous | unparsed
    value: object = None


def _menu(text: str, n: int, words: dict[int, tuple[str, ...]]) -> Parsed:
    t = text.strip().lower()
    digits = re.findall(r"\b\d+\b", t)
    if len(digits) == 1 and 1 <= int(digits[0]) <= n:
        return Parsed("ok", int(digits[0]))
    if digits:
        return Parsed("ambiguous")
    hits = {k for k, pats in words.items() if any(re.search(p, t) for p in pats)}
    if len(hits) == 1:
        return Parsed("ok", hits.pop())
    return Parsed("ambiguous" if hits else "unparsed")


def parse_pump(text: str) -> Parsed:
    p = _menu(text, 4, {1: (r"\bsolar\b", r"\bpanel"), 2: (r"\bgenerator\b", r"\bgen\b", r"\bdiesel\b"),
                        3: (r"\bgrid\b", r"\bnepa\b", r"\bphcn\b", r"\bmains\b"), 4: (r"\bhand\b", r"\bmanual\b")})
    return Parsed(p.status, PUMP[p.value]) if p.status == "ok" else p


def parse_generator(text: str) -> Parsed:
    t = text.strip().lower()
    if re.fullmatch(r"\s*1\s*[.!]?\s*", t) or re.search(r"\b(yes|yeah|yep|we have|there is)\b", t):
        return Parsed("ok", True) if not re.search(r"\b(no|not|broken|spoilt|none)\b", t) else Parsed("ambiguous")
    if re.fullmatch(r"\s*2\s*[.!]?\s*", t) or re.search(r"\b(no|none|nothing|broken|spoilt)\b", t):
        return Parsed("ok", False)
    return Parsed("unparsed")


def parse_hours(text: str) -> Parsed:
    t = text.strip().lower()
    if re.search(r"\b(did not run|didn't run|not at all|none|zero|no fuel)\b", t):
        return Parsed("ok", 0.0)
    nums = G.numbers_in(t)
    if len(nums) == 1:
        return Parsed("ok", float(nums[0])) if 0 <= nums[0] <= WEEK * 24 else Parsed("ambiguous")
    return Parsed("ambiguous" if nums else "unparsed")


def parse_fridge(text: str) -> Parsed:
    p = _menu(text, 4, {1: (r"\bice[- ]?lined\b", r"\bilr\b"), 2: (r"\bsolar\b", r"\bsdd\b"),
                        3: (r"\bhouse(hold)?\b", r"\bdomestic\b", r"\bnormal fridge\b"), 4: (r"\bnone\b", r"\bno fridge\b")})
    return Parsed(p.status, FRIDGE[p.value]) if p.status == "ok" else p


RULES = {"pump": parse_pump, "generator": parse_generator, "gen_hours": parse_hours, "fridge": parse_fridge}


def _r(x: float, nd: int = 2) -> float:
    return round(float(x), nd)


@dataclass
class SiteVerifierSession:
    city: str
    site: dict
    card: dict
    data: C13.City13Data
    channel: str = "sms"
    log: EV.EventLog = field(default_factory=EV.EventLog)
    answers: dict = field(default_factory=dict)
    sms: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    before: dict | None = None
    current: dict | None = None
    finished: bool = False
    _i: int = 0
    _asked_twice: bool = False
    _n: int = 0
    _open: str | None = None

    # -------------------------------------------------- the site's figures

    @property
    def sector(self) -> str:
        return str(self.site.get("sector"))

    @property
    def order(self) -> tuple[str, ...]:
        o = ORDER.get(self.sector, ("generator", "gen_hours"))
        if self.sector == "water" and self.site.get("archetype") not in SURVEY_PUMP:
            o = tuple(x for x in o if x != "pump")  # the water works: no survey pump type to check
        return o

    @property
    def week(self) -> dict:
        r = (self.site.get("results") or {}).get(str(WEEK)) or {}
        return {"needed_h": float(r.get("needed_h") or 0.0), "today_h": float(r.get("today_h") or 0.0),
                "with_h": float(r.get("with_h") or 0.0), "diesel_l_avoided": float(r.get("diesel_l_avoided") or 0.0)}

    @property
    def schedule_h(self) -> float | None:
        """Clock-hours a week the single critical load runs (water and cold sites carry hours_per_day)."""
        h = self.site.get("hours_per_day")
        return float(h) * WEEK if self.sector in ("water", "cold") and h else None

    def _interval(self) -> dict:
        w = self.week
        gen = self.answers.get("generator")
        hours = self.answers.get("gen_hours")
        contradicted = any(x["key"] == "pump" and not x["agrees"] for x in self.facts)
        if contradicted:
            gen = None  # the site is not the archetype the figures were run for: keep the modelled interval
        if gen is False:
            v = w["today_h"]
            return {"lo": _r(v), "hi": _r(v), "point": _r(v), "width": 0.0, "of": _r(w["needed_h"]),
                    "basis": "REPORTED: no generator, so only what the site keeps with no backup"}
        if gen is True and isinstance(hours, float) and self.schedule_h:
            v = min(w["needed_h"], max(w["today_h"], hours))
            return {"lo": _r(v), "hi": _r(v), "point": _r(v), "width": 0.0, "of": _r(w["needed_h"]),
                    "basis": "REPORTED: the generator's hours last week against the site's own schedule"}
        return {"lo": _r(w["today_h"]), "hi": _r(w["needed_h"]), "point": None,
                "width": _r(w["needed_h"] - w["today_h"]), "of": _r(w["needed_h"]),
                "basis": ("MODELLED: backup unknown; from no backup (today) to the diesel scenario, which ASSUMES "
                          "a generator with fuel for every needed hour")}

    def _curve(self) -> dict:
        c = self.data.constant(self.city, GEN_CURVE.get(self.sector, "GEN_L_PER_KWH_MID")) or {}
        return {"l_per_kwh": c.get("value"), "lo": c.get("lo"), "hi": c.get("hi"), "status": c.get("status")}

    # -------------------------------------------------- events

    def _call(self, name: str, **args) -> tuple[dict, str]:
        self._n += 1
        cid = f"v{self._n}"
        return self.log.emit("tool_call", id=cid, name=name, args=args), cid

    def _ask(self, text: str) -> list[dict]:
        assert len(text) <= MAX_SMS, text
        ev, cid = self._call("ask_site", channel=self.channel, to=WHO.get(self.sector, "the site"), message=text)
        self._open = cid
        self.sms.append({"from": "wardlight", "text": text})
        return [ev]

    def _update(self, why: str) -> list[dict]:
        t = self.log.ms()
        ev, cid = self._call("update_site", site_id=self.site["id"], why=why)
        prev = self.current["interval"] if self.current else None
        iv = self._interval()
        self.current = {"interval": iv, "answers": dict(self.answers)}
        w0 = prev["width"] if prev else None
        summ = (f"critical service-hours kept in a {WEEK}-day cut: {iv['lo']:g} to {iv['hi']:g} of {iv['of']:g}"
                if iv["point"] is None else f"critical service-hours kept in a {WEEK}-day cut: {iv['point']:g} of "
                f"{iv['of']:g} (reported)")
        out = [ev, self.log.emit("tool_result", id=cid, summary=summ, rows=1, ms=self.log.ms() - t, interval=iv,
                                 width_before=w0, width_after=iv["width"],
                                 widened=bool(w0 is not None and iv["width"] > w0 + 1e-9))]
        self.steps.append({"why": why, "interval": iv, "width_before": w0})
        return out

    def start(self) -> list[dict]:
        titles = {"pump": "Ask how the pump is powered", "generator": "Ask if there is a working generator",
                  "gen_hours": "Ask the generator's hours last week", "fridge": "Ask which fridge holds the vaccines"}
        evs = [self.log.emit("plan", steps=[{"id": "baseline", "title": "Read the site's modelled figures"},
                                            *({"id": f"ask_{q}", "title": titles[q]} for q in self.order),
                                            {"id": "answer", "title": "Show what was modelled and what was reported"}])]
        evs.append(self.log.emit("step_start", id="baseline"))
        t = self.log.ms()
        ev, cid = self._call("read_site", site_id=self.site["id"], city=self.city, days=WEEK)
        evs.append(ev)
        w = self.week
        evs.append(self.log.emit("tool_result", id=cid, rows=1, ms=self.log.ms() - t,
                                 summary=f"{self.site.get('name')}: {self.site.get('archetype')}, "
                                         f"{w['needed_h']:g} critical service-hours needed a week",
                                 site={k: self.site.get(k) for k in ("id", "name", "sector", "archetype", "lga",
                                                                       "kw", "hours_per_day", "supply")},
                                 week=w))
        evs += self._update("baseline: backup unknown")
        self.before = self.current
        evs.append(self.log.emit("step_start", id=f"ask_{self.order[0]}"))
        evs += self._ask(QUESTIONS[self.order[0]])
        return evs

    @property
    def field(self) -> str | None:
        return self.order[self._i] if self._i < len(self.order) else None

    @property
    def outbox(self) -> str | None:
        return None if self.finished else self.sms[-1]["text"]

    def handle(self, reply: str) -> list[dict]:
        if self.finished or self.field is None:
            return []
        f = self.field
        self.sms.append({"from": "site", "text": reply})
        p = RULES[f](reply)
        evs = [self.log.emit("tool_result", id=self._open, summary=f"reply: {reply[:120]}", rows=1, ms=0,
                             reply=reply, parsed=p.value, parse_status=p.status, parsed_by="rule")]
        self._open = None
        if p.status != "ok":
            if not self._asked_twice:
                self._asked_twice = True
                return evs + self._ask(REASK[f])
            self.answers[f] = None
            self.notes.append(f"{f}: no clear answer after one re-ask; recorded as unknown")
        else:
            self.answers[f] = p.value
            evs += self._apply(f, p.value)
        self._asked_twice = False
        self._i += 1
        if f == "generator" and self.answers.get("generator") is not True and "gen_hours" in self.order:
            self._i = self.order.index("gen_hours") + 1  # no generator (or unknown): its hours are not asked
        nxt = self.field
        if nxt is None:
            return evs + self._finish()
        evs.append(self.log.emit("step_start", id=f"ask_{nxt}"))
        return evs + self._ask(QUESTIONS[nxt])

    def _apply(self, f: str, v) -> list[dict]:
        w = self.week
        if f == "pump":
            survey = self.site.get("archetype")
            ok = v in SURVEY_PUMP.get(str(survey), ())
            self.facts.append({"key": "pump", "modelled": f"{survey} (iMMAP 2019 survey)", "reported": v,
                               "agrees": ok})
            self.notes.append(f"pump powered by {v}: " + ("consistent with the 2019 survey" if ok else
                              "contradicts the 2019 survey; the site is flagged for a survey, not re-run from one SMS"))
            return []
        if f == "generator":
            self.facts.append({"key": "generator", "modelled": "ASSUMED in the diesel scenario (every site, fuel "
                                                               "for the whole window)", "reported": v})
            if v is False:
                self.notes.append("no working generator: the diesel scenario does not apply to this site; in a cut "
                                  f"it keeps {w['today_h']:g} of {w['needed_h']:g} critical service-hours a week")
            return self._update("generator reported: " + ("yes" if v else "no"))
        if f == "gen_hours":
            kw = float(self.site.get("kw") or 0.0)
            curve = self._curve()
            price = self.data.diesel_price(self.city)["ngn_per_l"]
            litres = v * kw * float(curve["l_per_kwh"] or 0.0)
            fact = {"key": "gen_hours", "reported": v, "kw": kw, "l_per_kwh": curve["l_per_kwh"],
                    "litres_week": _r(litres, 1), "ngn_week": _r(litres * price, 0), "diesel_ngn_per_l": price,
                    "plan_litres_week": _r(w["diesel_l_avoided"], 1)}
            if self.schedule_h:
                fact["schedule_h"] = _r(self.schedule_h, 1)
                fact["share_of_schedule"] = _r(min(1.0, v / self.schedule_h), 4)
            self.facts.append(fact)
            self.notes.append(f"generator ran {v:g} hours last week (reported): about {fact['litres_week']:g} litres at "
                              f"the site's {kw:g} kW critical load, N{fact['ngn_week']:,.0f} at N{price:,.2f} per litre")
            return self._update(f"generator hours reported: {v:g}")
        if f == "fridge":
            self.facts.append({"key": "fridge", "modelled": "a PQS vaccine fridge on its own system (archetype)",
                               "reported": v})
            self.notes.append(f"vaccine fridge reported: {v}")
        return []

    def _finish(self) -> list[dict]:
        self.finished = True
        evs = [self.log.emit("step_start", id="answer")]
        b, a = self.before["interval"], self.current["interval"]
        name = self.site.get("name")
        lines = [f"**{name}** ({LABEL}; asked {WHO.get(self.sector, 'the site')})", "",
                 f"Before asking: in a {WEEK} day line cut the site keeps between {b['lo']:g} and {b['hi']:g} of "
                 f"{b['of']:g} critical service-hours, because its backup is unknown (modelled)."]
        if a["point"] is not None:
            lines.append(f"After the replies: {a['point']:g} of {a['of']:g} (reported).")
        else:
            lines.append(f"After the replies: still between {a['lo']:g} and {a['hi']:g} of {a['of']:g}; "
                         "the replies did not close the interval.")
        if any(x["key"] == "pump" and not x["agrees"] for x in self.facts):
            lines.append("The pump reply contradicts the survey the figures were run for, so they are not updated "
                         "from this conversation.")
        g = next((x for x in self.facts if x["key"] == "gen_hours"), None)
        if g:
            lines.append(f"The planned solar + storage system would avoid about {g['plan_litres_week']:g} litres a "
                         "week in a cut (modelled).")
        lines += [f"- {n}" for n in self.notes]
        lines.append("Reported answers come from typed sandbox replies; no site was contacted.")
        md = "\n".join(lines)
        pool = [self.site, self.week, self.before, self.current, self.steps, self.facts, {"week": WEEK}]
        rep = G.check(md, pool, require_citation=False)
        evs.append(self.log.emit("check", kind="grounding", numbers_checked=rep.n_total,
                                 unmatched=[c.text for c in rep.unmatched] + rep.unknown_tokens,
                                 matches=[{"text": c.text, "value": c.value, "matched": c.matched}
                                          for c in rep.claims], ok=rep.ok))
        if not rep.ok:
            md = f"**{name}** ({LABEL}): the summary could not be grounded, so only the data is shown."
            evs.append(self.log.emit("error", message="verifier summary blocked by the grounding check"))
        totals = {"before": b, "after": a, "narrowed_by": _r(b["width"] - a["width"]), "answers": self.answers,
                  "facts": self.facts, "steps": self.steps, "label": LABEL, "site_id": self.site["id"],
                  "week_days": WEEK}
        evs.append(self.log.emit("answer", markdown=md, funded=[], not_reached=[], totals=totals, sms=self.sms,
                                 notes=self.notes))
        evs.append(self.log.emit("done", model="rules only (no language model)", tokens=0, cost_usd=0.0,
                                 recorded=False, duration_ms=self.log.ms(), label=LABEL))
        return evs

    def record(self) -> dict:
        return {"label": LABEL, "site": {k: self.site.get(k) for k in ("id", "name", "sector", "archetype", "lga")},
                "city": self.city, "answers": self.answers, "sms": self.sms, "facts": self.facts,
                "before": self.before, "after": self.current, "notes": self.notes, "events": self.log.events}


def session_for(data: C13.City13Data, site_id: str, **kw) -> SiteVerifierSession:
    city, site, card = data.find_site(site_id)
    if site.get("rank") is None:
        raise C13.CityDataError(f"{site_id} already runs on its own plant and is not in the plan")
    return SiteVerifierSession(city, site, card, data, **kw)


def run_events(data: C13.City13Data, site_id: str, replies: list[str], **kw) -> Iterator[dict]:
    s = session_for(data, site_id, **kw)
    yield from s.start()
    for r in replies:
        if s.finished:
            break
        yield from s.handle(r)
