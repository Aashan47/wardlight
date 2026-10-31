"""Fixture mode (WARDLIGHT_FIXTURE=1): serves data/fixtures/web/ only. No data/work access, no engine calls, no
network, no model. Every response keeps the fixture's own "sample" flag so synthetic data stays labelled."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .config import Settings
from .errors import BadInput, NotFound
from .limits import Cache

SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class FixtureStore:
    fixture = True

    def __init__(self, s: Settings):
        self.s = s
        self.root = s.fixtures / "web"
        if not self.root.is_dir():
            raise RuntimeError(f"fixture directory {self.root} not found")
        self.cache = Cache(s.cache_entries)
        self.data_version = "fixture-" + str(self._load("health.json").get("data_version", "sample"))

    @lru_cache(maxsize=512)  # noqa: B019 - one store per app
    def _load_text(self, rel: str) -> str:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents or not p.is_file():
            raise NotFound(rel)
        return p.read_text(encoding="utf-8")

    def _load(self, rel: str):
        return json.loads(self._load_text(rel))

    def _id(self, fid: str) -> str:
        if not SAFE_ID.match(fid or ""):
            raise NotFound(f"no facility '{fid}'")
        m = re.fullmatch(r"(?:WL-?)?0*(\d{1,6})", fid, flags=re.IGNORECASE)
        return f"WL-{int(m.group(1)):04d}" if m else fid

    def health(self) -> dict:
        return {**self._load("health.json"), "fixture": True}

    def summary(self) -> dict:
        return self._load("summary.json")

    def facilities(self, state=None, lga=None, q=None, tier=None, limit=None) -> list[dict]:
        out = []
        ql = (q or "").strip().lower()
        for f in self._load("facilities.json"):
            if state and f.get("state") != state:
                continue
            if lga and f.get("lga") != lga:
                continue
            if tier and f.get("tier") != tier:
                continue
            if ql and not (ql in f["name"].lower() or ql in f["id"].lower() or ql in str(f.get("lga", "")).lower()):
                continue
            out.append(f)
        return out[: int(limit)] if limit else out

    def facility(self, fid: str) -> dict:
        try:
            return self._load(f"facility/{self._id(fid)}.json")
        except NotFound:
            raise NotFound(f"no facility '{fid}'") from None

    def simulate(self, fid: str, req: dict) -> dict:
        try:
            g = self._load(f"simulate/{self._id(fid)}.json")
        except NotFound:
            raise NotFound(f"no simulation grid for '{fid}'") from None

        def near(xs, x):
            return min(xs, key=lambda v: abs(v - x))

        pv, bat = near(g["pv_kwp"], req["pv_kwp"]), near(g["battery_kwh"], req["battery_kwh"])
        c = g["results"][f"{pv}|{bat}"]
        pqs = req["fridge_mode"] == "pqs_sdd"
        return {"pv_kwp": pv, "battery_kwh": bat, "cost_usd": c["cost_usd"],
                "survival": c["survival_pqs_sdd"] if pqs else c["survival"],
                "fridge_days": c.get("fridge_days_pqs_sdd") if pqs else c.get("fridge_days"),
                "trace": c["trace_pqs_sdd"] if pqs else c["trace"], "sample": True,
                "snapped": pv != req["pv_kwp"] or bat != req["battery_kwh"], "cached": False}

    def plan(self, state, budget_ngn, target, metric="doses", days=None) -> dict:
        p = dict(self._load("plan.json"))
        if state and state.lower() != str(p.get("state", "")).lower():
            raise NotFound(f"the fixture plan covers {p.get('state')} only")
        rows, cum = [], 0.0
        for i, r in enumerate(p.get("ranked", []), 1):
            cum += float(r.get("cost_ngn") or 0)
            rows.append({"rank": i, "cumulative_ngn": cum, "score": None, "reason": "sample row", **r})
        p["ranked"] = rows
        return p

    def brief(self, state, budget_ngn, metric="doses", days=None) -> dict:
        if metric not in ("doses", "load_hours", "outage_hours"):
            raise BadInput("metric must be 'doses' or 'load_hours'")
        p = self.plan(state, budget_ngn, None)
        budget = float(budget_ngn) if budget_ngn is not None else float(p.get("budget_ngn_max") or 0)
        funded = [{**r, "fix_label": None, "fix_model": None, "benefit": r.get("doses_protected_gain"),
                   "benefit_unit": "vaccine doses protected a year (sample)", "doses_gain": r.get("doses_protected_gain"),
                   "uptime_with_fix": r.get("uptime_with_system"),
                   "citation": {"kind": "sample", "text": "sample row, no evidence", "url": None}}
                  for r in p["ranked"] if r["cumulative_ngn"] <= budget]
        return {"sample": True, "kind": "investment_brief", "data_version": self.data_version, "state": p["state"],
                "metric": metric, "budget_ngn": budget, "funded": funded,
                "totals": {"funded": len(funded), "spent_ngn": funded[-1]["cumulative_ngn"] if funded else 0},
                "not_reached": [{"group": "ranked, over budget", "count": len(p["ranked"]) - len(funded),
                                 "why": "sample"}],
                "scenarios": [], "assumptions": [], "sources": self.health().get("sources", []),
                "currency_note": p.get("currency_note")}

    def city(self, state, lgas, days, limit=500) -> dict:
        raise NotFound("the city outage view needs the engine's outage columns; fixture mode has none")

    def outage_trace(self, fid, days) -> dict:
        raise NotFound("the outage trace needs the engine; fixture mode has none")

    def feeder(self, fid: str) -> dict:
        if not SAFE_ID.match(fid or ""):
            raise NotFound(fid)
        return self._load(f"feeder/{fid}.json")

    def results(self) -> dict:
        return self._load("results.json")

    def crop_path(self, name: str) -> Path | None:
        return None

    def lookup_short(self, code: str) -> dict | None:
        try:
            r = self.facility(code)
        except NotFound:
            return None
        b, f = r.get("brief_metric") or {}, r["facility"]
        rec, fix = r.get("recommended") or {}, r.get("fix") or {}
        roman = {"pqs_icelined": "i", "pqs_sdd": "ii", "solar_clinic": "iii"}.get(fix.get("category"))
        return {"id": f["id"], "code": int(re.sub(r"\D", "", f["id"]) or 0), "name": f["name"], "tier": f["tier"],
                "has_result": not r.get("refused") and bool(b), "fix_category": roman,
                "fix_label": fix.get("label") or (rec.get("fridge_system") or {}).get("design"),
                "capex_ngn": fix.get("cost_ngn") or (rec.get("capex_ngn") or {}).get("mid"),
                "uptime_today": (b.get("uptime_today") or {}).get("p"), "uptime_today_pqs": None,
                "uptime_with_system": (b.get("uptime_with_system") or {}).get("p"),
                "reason": (r.get("match") or {}).get("reason"), "sample": True}


__all__ = ["BadInput", "FixtureStore", "NotFound"]
