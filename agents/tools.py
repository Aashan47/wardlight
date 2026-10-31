"""Typed tools over Wardlight's own data and engine, for the planner (and reused by the verifier and watcher).

Data: `data/work/facilities.parquet`, `matches.parquet`, `facility_results.parquet`, `nerc_rows.parquet`
(the runbook's contracts) and naija-grid's `band_history_wide.csv` / `feeders.csv` for band history. Engine
calls go through `agents.engine_adapter` only.

Every tool result is a JSON-ready dict. Sources are registered in the session's citation registry and appear
in results as `cite: "S<n>"`; the answer cites them as [S<n>]. Tool results echo their inputs (state, budget,
priority) so that a number the user typed is still a tool result when the answer repeats it.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import engine_adapter as EA

PROJECT = Path(__file__).resolve().parents[1]
WORK = PROJECT / "data" / "work"
DATA_LOCAL = PROJECT.parents[1] / "data-local"
NAIJA = DATA_LOCAL / "naija-grid"

STATE_ALIASES = {"FCT": "FCT, Abuja", "ABUJA": "FCT, Abuja", "FCT ABUJA": "FCT, Abuja",
                 "FEDERAL CAPITAL TERRITORY": "FCT, Abuja", "NASSARAWA": "Nasarawa"}
LEVELS = ("Primary", "Secondary", "Tertiary")
METRIC_DEFINITION = ("uptime = share of days in a year the vaccine fridge holds 2 to 8 degC; 'today' is the "
                     "domestic-fridge scenario (b), PQS ice-lined scenario (a) alongside; doses are estimates")
MAX_LIST = 25


class ToolError(Exception):
    """A tool refused the request (bad argument, unknown id); returned to the model as {error: ...}."""


def _num(x, nd: int | None = None):
    """JSON-safe, rounded number (None for NaN or inf)."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    if nd is not None:
        return round(f, nd)
    a = abs(f)
    if a >= 100:
        return int(round(f))
    if a >= 1:
        return round(f, 2)
    return round(f, 4)


def _rank(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return int(f) if math.isfinite(f) else None


def _json(x, default=None):
    if isinstance(x, (dict, list)):
        return x
    if not isinstance(x, str) or not x:
        return default
    try:
        return json.loads(x)
    except ValueError:
        return default


def _str(x) -> str | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip()
    return s or None


# ---------------------------------------------------------------- data


def _agent_names(row: dict) -> dict:
    """A full row from the API's on-disk store, renamed to this module's names: matches columns as match_*, and
    `tier` the tier the result was run on (the result's own, else the match's), as in WardlightData.table."""
    out = {("match_" + k[2:] if k.startswith("m_") else k): v for k, v in row.items()}
    out["tier"] = out.get("result_tier") or out.get("match_tier")
    out["state"] = out.get("state_standard")
    return out


class WardlightData:
    """Lazy access to the work tables. Frames may be injected (tests); otherwise read from `work_dir`.

    With `store` (the API's shared store: `core` frame, `nerc` frame, `data_version`, `full_rows(ids)`), nothing
    is read again: the tables are views of the store's slim in-memory columns, and the full row (evidence, system
    specs, labels) of a facility is read from the store's disk only when a tool returns it (`row`, `enrich`)."""

    def __init__(self, work_dir: Path | str | None = None, facilities: pd.DataFrame | None = None,
                 matches: pd.DataFrame | None = None, results: pd.DataFrame | None = None,
                 nerc_rows: pd.DataFrame | None = None, naija_dir: Path | str | None = None,
                 band_history: pd.DataFrame | None = None, store=None):
        self.work = Path(work_dir) if work_dir else WORK
        self.naija = Path(naija_dir) if naija_dir else NAIJA
        self._f, self._m, self._r, self._n, self._bh = facilities, matches, results, nerc_rows, band_history
        self._store = store
        if store is not None:
            core = store.core
            fac_cols = [c for c in ("unique_id", "facility_name", "facility_level", "facility_type",
                                    "state_standard", "lga_standard", "latitude", "longitude", "source_version")
                        if c in core]
            self._f = core[fac_cols]
            self._m = pd.DataFrame({"unique_id": core.unique_id, "tier": core.get("m_tier"),
                                    "bands": core.get("m_bands"), "feeder_ids": core.get("m_feeder_ids"),
                                    "evidence": core.get("ev_unit_json")})
            self._r = core[core.has_result]
            self._n = store.nerc

    def enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rows with every column (store mode: read from the store for these rows only); unchanged otherwise."""
        if self._store is None or df.empty:
            return df
        full = self._store.full_rows(df.unique_id)
        extra = pd.DataFrame([_agent_names(full.get(u, {})) for u in df.unique_id], index=df.index)
        return pd.concat([df, extra[[c for c in extra.columns if c not in df.columns]]], axis=1)

    def _read(self, name: str) -> pd.DataFrame:
        p = self.work / f"{name}.parquet"
        if not p.exists():
            raise ToolError(f"{p.name} is not built yet")
        return pd.read_parquet(p)

    @cached_property
    def facilities(self) -> pd.DataFrame:
        return self._f if self._f is not None else self._read("facilities")

    @cached_property
    def matches(self) -> pd.DataFrame:
        return self._m if self._m is not None else self._read("matches")

    @cached_property
    def results(self) -> pd.DataFrame:
        return self._r if self._r is not None else self._read("facility_results")

    @cached_property
    def nerc_rows(self) -> pd.DataFrame:
        n = self._n if self._n is not None else self._read("nerc_rows")
        n = n.copy()
        n["row_key"] = [f"{f}#p{int(p)}#sn{s}" for f, p, s in zip(n.order_file, n.page, n.sn)]
        return n

    @cached_property
    def band_history(self) -> pd.DataFrame:
        if self._bh is not None:
            return self._bh
        p = self.naija / "band_history_wide.csv"
        if not p.exists():
            raise ToolError("naija-grid band_history_wide.csv is not present")
        return pd.read_csv(p, dtype=str)

    @cached_property
    def version(self) -> str:
        """Short hash of the input tables (file sizes and mtimes, or frame shapes when injected)."""
        if self._store is not None:
            return self._store.data_version
        h = hashlib.sha256()
        for name in ("facilities", "matches", "facility_results", "nerc_rows"):
            p = self.work / f"{name}.parquet"
            injected = {"facilities": self._f, "matches": self._m, "facility_results": self._r,
                        "nerc_rows": self._n}[name]
            if injected is not None:
                h.update(f"{name}:injected:{injected.shape}:{list(injected.columns)}".encode())
            elif p.exists():
                st = p.stat()
                h.update(f"{name}:{st.st_size}:{int(st.st_mtime)}".encode())
        return h.hexdigest()[:12]

    @cached_property
    def table(self) -> pd.DataFrame:
        """facilities, left-joined to matches (match_*) and results; `tier` is the tier the result was run on."""
        if self._store is not None:
            t = self._store.core.rename(columns={c: "match_" + c[2:] for c in self._store.core.columns
                                                 if c.startswith("m_")})
            rt = t["result_tier"] if "result_tier" in t else pd.Series(np.nan, index=t.index)
            extra = pd.DataFrame({"tier": rt.where(rt.notna(), t.get("match_tier")), "state": t["state_standard"]},
                                 index=t.index)
            return pd.concat([t.drop(columns=["tier"], errors="ignore"), extra], axis=1)
        f = self.facilities.copy()
        m = self.matches.rename(columns={c: f"match_{c}" for c in self.matches.columns if c != "unique_id"})
        r = self.results.copy()
        if "tier" in r:
            r = r.rename(columns={"tier": "result_tier"})
        t = f.merge(m, on="unique_id", how="left").merge(r, on="unique_id", how="left")
        rt = t["result_tier"] if "result_tier" in t else pd.Series(np.nan, index=t.index)
        t["tier"] = rt.where(rt.notna(), t.get("match_tier"))
        t["has_result"] = t["unique_id"].isin(set(r.unique_id))
        t["state"] = t["state_standard"]
        return t

    @cached_property
    def states(self) -> list[str]:
        return sorted(s for s in self.facilities.state_standard.dropna().unique() if s)

    def resolve_state(self, state: str) -> str:
        s = (state or "").strip()
        if not s:
            raise ToolError("state is required")
        key = s.upper().replace(" STATE", "").strip()
        key = STATE_ALIASES.get(key, key)
        for st in self.states:
            if st.upper() == str(key).upper():
                return st
        raise ToolError(f"'{state}' is not a Nigerian state in the facility registry. Wardlight covers Nigeria "
                        f"only; valid states: {', '.join(self.states)}")

    def resolve_lga(self, state: str, lga: str) -> str:
        lgas = sorted(self.facilities.loc[self.facilities.state_standard == state, "lga_standard"].dropna().unique())
        for x in lgas:
            if x.upper() == lga.strip().upper():
                return x
        raise ToolError(f"LGA '{lga}' not found in {state}; valid LGAs: {', '.join(lgas)}")

    def row(self, unique_id: str) -> pd.Series:
        if self._store is not None:
            full = self._store.full_rows([unique_id]).get(unique_id)
            if full is None:
                raise ToolError(f"no facility with id '{unique_id}'")
            return pd.Series(_agent_names(full))
        t = self.table
        hit = t[t.unique_id == unique_id]
        if hit.empty:
            raise ToolError(f"no facility with id '{unique_id}'")
        return hit.iloc[0]


# ---------------------------------------------------------------- session: citations and call log


@dataclass
class Session:
    """Per-question state: citation registry, tool-call log, the last plan (for the structured output)."""

    citations: dict[str, dict] = field(default_factory=dict)
    _by_key: dict[str, str] = field(default_factory=dict)
    calls: list[dict] = field(default_factory=list)
    results: list[Any] = field(default_factory=list)  # every tool result as the model saw it
    last_plan: dict | None = None

    def cite(self, source: dict) -> str:
        key = json.dumps(source, sort_keys=True, default=str)
        if key in self._by_key:
            return self._by_key[key]
        cid = f"S{len(self.citations) + 1}"
        self.citations[cid] = {"id": cid, **source}
        self._by_key[key] = cid
        return cid


# ---------------------------------------------------------------- the toolbox


TOOL_SPECS: list[dict] = [
    {"type": "function", "function": {
        "name": "list_facilities",
        "description": "List health facilities in a Nigerian state (optionally one LGA, tier, level or name "
                       "search) with match tier, today's fridge uptime (scenarios), the recommended fix, its "
                       "cost and doses. Sorted by doses protected per naira of the fix.",
        "parameters": {"type": "object", "properties": {
            "state": {"type": "string"}, "lga": {"type": "string"},
            "tier": {"type": "string", "enum": ["a_named", "b_place", "c_lga_mixture", "c_unit_mixture",
                                                "d_refused", "offgrid"]},
            "facility_level": {"type": "string", "enum": list(LEVELS)},
            "name_contains": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIST}},
            "required": ["state"]}}},
    {"type": "function", "function": {
        "name": "get_facility",
        "description": "One facility with its evidence: registry row, feeder match (NERC file, page, row text) "
                       "or the reason it was refused, and the engine's results.",
        "parameters": {"type": "object", "properties": {"unique_id": {"type": "string"}},
                       "required": ["unique_id"]}}},
    {"type": "function", "function": {
        "name": "what_if",
        "description": "Re-run one facility under a changed grid band and/or a clinic system size (PV kWp, "
                       "battery kWh). Returns modelled fridge and critical-load uptimes and the clinic cost.",
        "parameters": {"type": "object", "properties": {
            "unique_id": {"type": "string"},
            "band": {"type": "string", "enum": ["A", "B", "C", "D", "E", "OFFGRID"]},
            "pv_kwp": {"type": "number", "minimum": 0, "maximum": 50},
            "battery_kwh": {"type": "number", "minimum": 0, "maximum": 400}},
            "required": ["unique_id"]}}},
    {"type": "function", "function": {
        "name": "size_system",
        "description": "The cheapest cold-chain fix meeting the target for one facility, and the separate "
                       "optional clinic system sized for the priority-1 loads.",
        "parameters": {"type": "object", "properties": {
            "unique_id": {"type": "string"},
            "target": {"type": "number", "minimum": 0.5, "maximum": 0.999}},
            "required": ["unique_id"]}}},
    {"type": "function", "function": {
        "name": "rank_budget",
        "description": "Rank a state's facilities under a budget with engine.plan.rank and return the funded "
                       "list, totals, what the money does not reach and why. priority 'doses' = vaccine doses "
                       "protected per naira of the cold-chain fix; 'load_hours' = maternal and emergency "
                       "care: critical load-hours restored per naira of the clinic system.",
        "parameters": {"type": "object", "properties": {
            "state": {"type": "string"}, "budget": {"type": "number", "exclusiveMinimum": 0},
            "currency": {"type": "string", "enum": ["NGN", "USD"]},
            "priority": {"type": "string", "enum": ["doses", "load_hours"]},
            "lga": {"type": "string"}, "facility_level": {"type": "string", "enum": list(LEVELS)},
            "top": {"type": "integer", "minimum": 1, "maximum": MAX_LIST}},
            "required": ["state", "budget", "priority"]}}},
    {"type": "function", "function": {
        "name": "get_nerc_rows",
        "description": "Rows of NERC's feeder appendices (band, feeder, location, streets, minimum hours, file, "
                       "page, serial number). Filter by DisCo, feeder name, a place named in the row, or band.",
        "parameters": {"type": "object", "properties": {
            "disco": {"type": "string"}, "feeder_name": {"type": "string"}, "place": {"type": "string"},
            "band": {"type": "string", "enum": ["A", "B", "C", "D", "E"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20}}}}},
    {"type": "function", "function": {
        "name": "band_history",
        "description": "A feeder's band in every NERC monthly cap order (naija-grid), and when it changed.",
        "parameters": {"type": "object", "properties": {
            "feeder_name": {"type": "string"}, "disco": {"type": "string"}},
            "required": ["feeder_name"]}}},
    {"type": "function", "function": {
        "name": "refuse",
        "description": "Decline the question. Use out_of_scope for anything that is not about energy and cold "
                       "chain for health facilities (including medical or clinical advice); use "
                       "data_cannot_support when Wardlight's data cannot answer it (say what is missing).",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string", "enum": ["out_of_scope", "data_cannot_support"]},
            "explanation": {"type": "string"}},
            "required": ["reason", "explanation"]}}},
]
TOOL_NAMES = {t["function"]["name"] for t in TOOL_SPECS}


class Toolbox:
    def __init__(self, data: WardlightData | None = None, n_draws: int = 16):
        self.data = data or WardlightData()
        self.n_draws = n_draws

    specs = staticmethod(lambda: TOOL_SPECS)

    # -------------------------------------------------- dispatch

    def call(self, name: str, args: dict, session: Session) -> dict:
        t0 = time.perf_counter()
        fn = getattr(self, f"t_{name}", None)
        if name not in TOOL_NAMES or fn is None:
            out: dict = {"error": f"unknown tool '{name}'"}
        else:
            try:
                out = fn(session, **(args or {}))
            except ToolError as e:
                out = {"error": str(e)}
            except TypeError as e:
                out = {"error": f"bad arguments for {name}: {e}"}
        session.results.append(out)
        session.calls.append({"name": name, "arguments": args, "ok": "error" not in out,
                              "ms": int((time.perf_counter() - t0) * 1000)})
        return out

    # -------------------------------------------------- shared pieces

    def _facility_cite(self, s: Session, r: pd.Series) -> str:
        ev = _json(r.get("match_evidence"), {}) or {}
        src: dict = {"type": "facility", "unique_id": r.unique_id,
                     "registry": f"GRID3 Nigeria health facilities ({_str(r.get('source_version')) or 'GRID3'})",
                     "match_tier": _str(r.get("match_tier")),
                     "results": f"facility_results.parquet (data version {self.data.version})"}
        if ev.get("order_file"):
            src["nerc"] = {"order_file": ev.get("order_file"), "page": ev.get("page"), "sn": ev.get("sn"),
                           "row_text": ev.get("row_text")}
        elif ev.get("source"):
            src["evidence_source"] = ev.get("source")
        return s.cite(src)

    def _fix(self, r: pd.Series) -> dict:
        sf = _json(r.get("system_fridge"), {}) or {}
        label = _str(r.get("fix_label")) or sf.get("kind")
        return {"label": label, "category": _str(r.get("fix_category")) or sf.get("category"),
                "model": sf.get("name"), "capex_ngn": _num(r.get("capex_ngn")),
                "capex_ngn_lo": _num(r.get("capex_ngn_lo")), "capex_ngn_hi": _num(r.get("capex_ngn_hi"))}

    def _brief(self, s: Session, r: pd.Series) -> dict:
        gain = r.get("doses_gain")
        if not EA.finite(gain) and EA.finite(r.get("doses_with_system")) and EA.finite(r.get("doses_protected_today")):
            gain = float(r.doses_with_system) - float(r.doses_protected_today)
        return {
            "unique_id": r.unique_id, "name": _str(r.get("facility_name")), "level": _str(r.get("facility_level")),
            "lga": _str(r.get("lga_standard")), "ward": _str(r.get("ward_standard")), "tier": _str(r.get("tier")),
            "has_result": bool(r.get("has_result")),
            "uptime_today": _num(r.get("uptime_today")), "uptime_today_lo": _num(r.get("uptime_today_lo")),
            "uptime_today_hi": _num(r.get("uptime_today_hi")),
            "uptime_today_pqs": _num(r.get("uptime_today_pqs")),
            "uptime_with_fix": _num(r.get("uptime_with_system")),
            "fix": self._fix(r),
            "doses_per_year": _num(r.get("doses_per_year")), "doses_gain": _num(gain),
            "cite": self._facility_cite(s, r),
        }

    def _bands_of(self, r: pd.Series):
        return EA.bands_for(_str(r.get("match_tier")) or _str(r.get("tier")), r.get("match_bands"))

    # -------------------------------------------------- tools

    def t_list_facilities(self, s: Session, state: str, lga: str | None = None, tier: str | None = None,
                          facility_level: str | None = None, name_contains: str | None = None,
                          limit: int = 10) -> dict:
        st = self.data.resolve_state(state)
        t = self.data.table
        sub = t[t.state_standard == st]
        if lga:
            lga = self.data.resolve_lga(st, lga)
            sub = sub[sub.lga_standard == lga]
        if facility_level:
            sub = sub[sub.facility_level == facility_level]
        by_tier = {str(k): int(v) for k, v in sub["tier"].fillna("no_match").value_counts().items()}
        if tier:
            sub = sub[sub["tier"] == tier]
        if name_contains:
            sub = sub[sub.facility_name.fillna("").str.contains(name_contains, case=False, regex=False)]
        score = sub["priority_score"] if "priority_score" in sub else pd.Series(np.nan, index=sub.index)
        sub = sub.assign(_score=score.fillna(-1)).sort_values(["_score", "facility_name"], ascending=[False, True])
        limit = max(1, min(int(limit or 10), MAX_LIST))
        return {"state": st, "lga": lga, "tier": tier, "facility_level": facility_level,
                "count": len(sub), "count_by_tier": by_tier,
                "count_with_result": int(sub.has_result.sum()), "returned": int(min(limit, len(sub))),
                "metric_definition": METRIC_DEFINITION,
                "facilities": [self._brief(s, r) for _, r in self.data.enrich(sub.head(limit)).iterrows()]}

    def t_get_facility(self, s: Session, unique_id: str) -> dict:
        r = self.data.row(unique_id)
        ev = _json(r.get("match_evidence"), {}) or {}
        rows = []
        n = self.data.nerc_rows
        for key in (_json(r.get("match_feeder_ids"), []) or [])[:5]:
            hit = n[n.row_key == key]
            if hit.empty:
                continue
            x = hit.iloc[0]
            rows.append({"order_file": x.order_file, "order_month": _str(x.get("order_month")), "page": int(x.page),
                         "sn": _rank(x.sn), "band": _str(x.band), "min_hours": _num(x.min_hours),
                         "feeder_name": _str(x.feeder_name), "location": _str(x.location),
                         "streets": _str(x.streets), "crop": _str(x.get("crop_path")),
                         "cite": s.cite({"type": "nerc_row", "order_file": x.order_file, "page": int(x.page),
                                         "sn": str(x.sn), "crop": _str(x.get("crop_path"))})})
        out = self._brief(s, r)
        out.update({
            "state": _str(r.get("state_standard")), "settlement": _str(r.get("settlement_name")),
            "facility_type": _str(r.get("facility_type")), "ownership": _str(r.get("facility_ownership")),
            "functional": _str(r.get("functional")), "registry_version": _str(r.get("source_version")),
            "lat": _num(r.get("latitude"), 5), "lon": _num(r.get("longitude"), 5),
            "match": {"tier": _str(r.get("match_tier")), "bands": _json(r.get("match_bands"), {}),
                      "reason": _str(r.get("match_reason")), "grid_km": _num(r.get("match_grid_km")),
                      "evidence": {k: v for k, v in ev.items() if k != "rows"}},
            "nerc_rows": rows,
            "results": None if not r.get("has_result") else {
                "uptime_today": _num(r.get("uptime_today")), "uptime_today_lo": _num(r.get("uptime_today_lo")),
                "uptime_today_hi": _num(r.get("uptime_today_hi")),
                "uptime_today_pqs": _num(r.get("uptime_today_pqs")),
                "uptime_with_fix": _num(r.get("uptime_with_system")),
                "doses_per_year": _num(r.get("doses_per_year")),
                "doses_protected_today": _num(r.get("doses_protected_today")),
                "doses_with_fix": _num(r.get("doses_with_system")),
                "fix_monthly_cost_ngn": _num(r.get("monthly_cost_ngn")),
                "crit_uptime_today": _num(r.get("crit_uptime_today")),
                "crit_uptime_with": _num(r.get("crit_uptime_with")),
                "clinic_system": _json(r.get("system_clinic"), None),
                "clinic_capex_ngn": _num(r.get("clinic_capex_ngn")),
                "labels": _json(r.get("labels"), None)},
            "result_tier_differs_from_match": bool(_str(r.get("result_tier")) and _str(r.get("match_tier"))
                                                   and r.get("result_tier") != r.get("match_tier")),
            "metric_definition": METRIC_DEFINITION,
        })
        return out

    def _site(self, unique_id: str):
        r = self.data.row(unique_id)
        if not (EA.finite(r.get("latitude")) and EA.finite(r.get("longitude"))):
            raise ToolError(f"{unique_id} has no coordinates in the registry, so it cannot be simulated")
        return r, float(r.latitude), float(r.longitude)

    def t_what_if(self, s: Session, unique_id: str, band: str | None = None, pv_kwp: float | None = None,
                  battery_kwh: float | None = None) -> dict:
        r, lat, lon = self._site(unique_id)
        if band:
            band = band.upper()
            if band not in (*EA.BANDS, EA.OFFGRID):
                raise ToolError("band must be A to E or OFFGRID")
            bands = EA.OFFGRID if band == EA.OFFGRID else {band: 1.0}
        else:
            bands = self._bands_of(r)
        sysc = _json(r.get("system_clinic"), {}) or {}
        pv = float(pv_kwp) if pv_kwp is not None else float(sysc.get("pv_kwp") or 1.0)
        kwh = float(battery_kwh) if battery_kwh is not None else float(sysc.get("battery_kwh") or pv * 7.2)
        out = EA.what_if(lat, lon, bands, pv, kwh, self.n_draws)
        cc = EA.coldchain(lat, lon, bands, self.n_draws)
        out.update({"unique_id": unique_id, "bands_used": EA.bands_key(bands), "band_override": band,
                    "coldchain": cc,
                    "cite": s.cite({"type": "engine_run", "function": "engine.sim.what_if + engine.coldchain.assess",
                                    "unique_id": unique_id, "bands": EA.bands_key(bands), "pv_kwp": pv,
                                    "battery_kwh": kwh, "n_draws": self.n_draws})})
        return out

    def t_size_system(self, s: Session, unique_id: str, target: float = EA.TARGET) -> dict:
        r, lat, lon = self._site(unique_id)
        bands = self._bands_of(r)
        out = EA.size(lat, lon, bands, float(target), self.n_draws)
        out.update({"unique_id": unique_id, "bands_used": EA.bands_key(bands),
                    "cite": s.cite({"type": "engine_run", "function": "engine.coldchain.assess + "
                                    "engine.size.size_clinic", "unique_id": unique_id,
                                    "bands": EA.bands_key(bands), "target": float(target),
                                    "n_draws": self.n_draws})})
        return out

    def plan_frame(self, state: str, lga: str | None = None, facility_level: str | None = None) -> pd.DataFrame:
        """The results rows the ranking runs on (public so the T9 checker uses exactly the same frame)."""
        t = self.data.table
        sub = t[(t.state_standard == state) & t.has_result]
        if lga:
            sub = sub[sub.lga_standard == lga]
        if facility_level:
            sub = sub[sub.facility_level == facility_level]
        return sub

    def t_rank_budget(self, s: Session, state: str, budget: float, priority: str, currency: str = "NGN",
                      lga: str | None = None, facility_level: str | None = None, top: int = 10) -> dict:
        st = self.data.resolve_state(state)
        if lga:
            lga = self.data.resolve_lga(st, lga)
        if priority not in EA.METRICS:
            raise ToolError("priority must be 'doses' or 'load_hours'")
        if facility_level and facility_level not in LEVELS:
            raise ToolError(f"facility_level must be one of {LEVELS}")
        currency = (currency or "NGN").upper()
        if currency not in ("NGN", "USD") or not EA.finite(budget) or float(budget) <= 0:
            raise ToolError("budget must be a positive number in NGN or USD")
        budget_ngn = EA.usd_to_ngn(budget) if currency == "USD" else float(budget)
        all_in = self.data.table
        scope = all_in[all_in.state_standard == st]
        if lga:
            scope = scope[scope.lga_standard == lga]
        if facility_level:
            scope = scope[scope.facility_level == facility_level]
        sub = self.plan_frame(st, lga, facility_level)
        if sub.empty:
            raise ToolError(f"no facility in {st}{' / ' + lga if lga else ''} has an engine result to rank")
        ranked, summ = EA.rank(sub, budget_ngn, priority)
        f = self.data.enrich(ranked[ranked.funded].sort_values("rank"))
        unf = self.data.enrich(ranked[(~ranked.funded) & ranked["rank"].notna()].sort_values("rank").head(MAX_LIST))
        n_unf = int(((~ranked.funded) & ranked["rank"].notna()).sum())
        unknown = ranked[ranked["rank"].isna()]
        top = max(1, min(int(top or 10), MAX_LIST))

        def item(x: pd.Series, funded: bool) -> dict:
            d = {"rank": _rank(x["rank"]), "unique_id": x.unique_id,
                 "name": _str(x.get("facility_name")), "lga": _str(x.get("lga_standard")),
                 "level": _str(x.get("facility_level")), "tier": _str(x.get("tier")),
                 "cost_ngn": _num(x.cost_ngn), "benefit": _num(x.benefit),
                 "benefit_per_million_ngn": _num(x.benefit_per_mngn),
                 "uptime_today": _num(x.get("uptime_today")), "uptime_with_fix": _num(x.get("uptime_with_system")),
                 "fix_label": self._fix(x)["label"], "reason": _str(x.get("reason"))}
            if not funded:
                d["why_not_funded"] = "the budget was spent on higher-ranked facilities before this one"
            d["cite"] = self._facility_cite(s, x)
            return d

        spent = float(summ["spent_ngn"])
        no_result = int((~scope.has_result).sum())
        plan_cite = s.cite({"type": "engine_run", "function": "engine.plan.rank", "state": st, "lga": lga,
                            "facility_level": facility_level, "budget_ngn": round(budget_ngn, 2),
                            "metric": priority, "data_version": self.data.version})
        totals = {"budget_ngn": _num(budget_ngn, 2), "spent_ngn": _num(spent, 2),
                  "remaining_ngn": _num(budget_ngn - spent, 2), "funded_count": int(summ["funded"]),
                  "benefit_total": _num(summ["benefit"]), "metric": priority,
                  "benefit_unit": EA.BENEFIT_UNIT[priority], "cost_basis": EA.COST_BASIS[priority],
                  "candidates_ranked": int(summ["candidates"]), "ranked_not_funded": n_unf,
                  "not_ranked_unknown_supply": int(summ["not_ranked_unknown_supply"]),
                  "no_engine_result": no_result, "facilities_in_scope": len(scope)}
        not_reached = {
            "ranked_not_funded": {"count": n_unf, "reason": "budget spent on higher-ranked facilities",
                                  "next_in_line": [item(x, False) for _, x in unf.head(5).iterrows()]},
            "unknown_supply": {"count": len(unknown),
                               "reason": "not ranked: today's grid supply is unknown (refused match), so the gain "
                                         "cannot be computed"},
            "no_engine_result": {"count": no_result,
                                 "reason": "no engine result row for these facilities in this data version"},
        }
        if lga is None and facility_level is None:
            refused = self.data.enrich(scope[scope["tier"] == "d_refused"].head(1))
            if len(refused):
                not_reached["unknown_supply"]["example_reason"] = _str(refused.iloc[0].get("match_reason"))
        out = {"state": st, "lga": lga, "facility_level": facility_level, "budget": _num(budget, 2),
               "currency": currency, "budget_ngn": _num(budget_ngn, 2), "priority": priority,
               "totals": totals, "funded_top": [item(x, True) for _, x in f.head(top).iterrows()],
               "funded_shown": int(min(top, len(f))), "not_reached": not_reached, "cite": plan_cite,
               "labels": {"doses": "ESTIMATE (WorldPop catchment, birth rate, unofficial schedule)",
                          "supply": "MODELLED from the NERC band promise; promised, not measured",
                          "metric_definition": METRIC_DEFINITION}}
        if currency == "USD":
            out["fx"] = EA.fx()
        s.last_plan = {"args": {"state": st, "lga": lga, "facility_level": facility_level, "budget_ngn": budget_ngn,
                                "metric": priority, "budget": float(budget), "currency": currency},
                       "totals": totals, "cite": plan_cite,
                       "funded": [self._plan_item(s, x) for _, x in f.iterrows()],
                       "not_reached": [self._plan_item(s, x, "budget spent on higher-ranked facilities")
                                       for _, x in unf.head(MAX_LIST).iterrows()],
                       "not_reached_groups": {k: {kk: vv for kk, vv in v.items() if kk != "next_in_line"}
                                              for k, v in not_reached.items()}}
        return out

    def _plan_item(self, s: Session, x: pd.Series, why: str | None = None) -> dict:
        d = {"rank": _rank(x["rank"]), "unique_id": x.unique_id, "name": _str(x.get("facility_name")),
             "lga": _str(x.get("lga_standard")), "tier": _str(x.get("tier")), "cost_ngn": _num(x.cost_ngn),
             "benefit": _num(x.benefit), "uptime_today": _num(x.get("uptime_today")),
             "uptime_with_fix": _num(x.get("uptime_with_system")), "fix_label": self._fix(x)["label"],
             "reason": _str(x.get("reason")), "cite": self._facility_cite(s, x)}
        if why:
            d["why_not_funded"] = why
        return d

    def t_get_nerc_rows(self, s: Session, disco: str | None = None, feeder_name: str | None = None,
                        place: str | None = None, band: str | None = None, limit: int = 10) -> dict:
        n = self.data.nerc_rows
        sub = n
        if disco:
            sub = sub[sub.disco.str.upper() == disco.strip().upper()]
        if feeder_name:
            sub = sub[sub.feeder_name.fillna("").str.contains(feeder_name.strip(), case=False, regex=False)]
        if place:
            hay = sub.location.fillna("") + " | " + sub.streets.fillna("")
            sub = sub[hay.str.contains(place.strip(), case=False, regex=False)]
        if band:
            sub = sub[sub.band == band.upper()]
        limit = max(1, min(int(limit or 10), 20))
        rows = []
        for _, x in sub.head(limit).iterrows():
            rows.append({"disco": x.disco, "order_file": x.order_file, "order_month": _str(x.get("order_month")),
                         "page": int(x.page), "sn": _rank(x.sn), "band": _str(x.band),
                         "feeder_name": _str(x.feeder_name), "location": _str(x.location),
                         "streets": _str(x.streets), "min_hours": _num(x.min_hours),
                         "ocr_confidence": _num(x.get("ocr_confidence")),
                         "cite": s.cite({"type": "nerc_row", "order_file": x.order_file, "page": int(x.page),
                                         "sn": str(x.sn), "crop": _str(x.get("crop_path"))})})
        return {"query": {"disco": disco, "feeder_name": feeder_name, "place": place, "band": band},
                "count": len(sub), "returned": len(rows), "rows": rows,
                "note": "minimum hours are NERC's promise per band, not measured supply"}

    def t_band_history(self, s: Session, feeder_name: str, disco: str | None = None) -> dict:
        bh = self.data.band_history
        sub = bh
        if disco:
            sub = sub[sub.disco.str.upper() == disco.strip().upper()]
        q = feeder_name.strip().upper()
        exact = sub[sub.feeder_raw.fillna("").str.upper() == q]
        sub = exact if len(exact) else sub[sub.feeder_raw.fillna("").str.upper().str.contains(q, regex=False)]
        months = [c for c in bh.columns if len(c) == 7 and c[4] == "-"]
        feeders = []
        for _, x in sub.head(3).iterrows():
            hist = [{"month": m, "band": x[m]} for m in months if isinstance(x[m], str) and x[m]]
            changes = [{"from_month": a["month"], "to_month": b["month"], "from": a["band"], "to": b["band"]}
                       for a, b in zip(hist, hist[1:]) if a["band"] != b["band"]]
            feeders.append({"feeder_id": x.feeder_id, "disco": x.disco, "state": _str(x.get("state")),
                            "feeder_name": x.feeder_raw, "history": hist, "changes": changes,
                            "cite": s.cite({"type": "naija_grid", "file": "band_history_wide.csv",
                                            "feeder_id": x.feeder_id,
                                            "repository": "github.com/Godzilla-lab/naija-grid (CC BY 4.0, "
                                                          "credit NERC)"})})
        return {"query": {"feeder_name": feeder_name, "disco": disco}, "count": len(sub),
                "feeders": feeders}

    def t_refuse(self, s: Session, reason: str, explanation: str) -> dict:
        if reason not in ("out_of_scope", "data_cannot_support"):
            raise ToolError("reason must be out_of_scope or data_cannot_support")
        return {"refused": True, "reason": reason, "explanation": explanation}
