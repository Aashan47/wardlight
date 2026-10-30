"""Live data: precomputed at startup from data/work/*.parquet; what-if, supply model and T3 through the engine.

Every number served here is a value from facility_results / matches / facilities / nerc_rows / catchments, simple
arithmetic on those values (stated where it happens), an engine constant, or an engine call.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from engine import coldchain as CC
from engine import constants as C
from engine import fridge as F
from engine import plan as PL
from engine import supply as SP

from . import results as R
from . import whatif as W
from .config import Settings
from .errors import BadInput, NotFound
from .limits import Cache, input_hash
from .sources import QUOTES, SOURCES, nerc_urls

TIERS = ("a_named", "b_place", "c_lga_mixture", "c_unit_mixture", "d_refused", "offgrid")
WHO_PAYS = ["State Primary Health Care Board (state budget)",
            "Rural Electrification Agency health-facility programmes",
            "Donor or development partner (for example a Solar for Health programme); lease-to-own as an option"]
MAINTAINS = ("Not modelled: the payer's local installer or the state cold-chain officer would maintain it; no "
             "maintenance arrangement is sourced")
SCENARIO_HEADLINE = "household or non-PQS fridge"
UPTIME_SCENARIOS = {"uptime_today": SCENARIO_HEADLINE, "uptime_today_pqs": "PQS ice-lined fridge",
                    "uptime_with_system": "with the recommended cold-chain fix"}
FIX_CATEGORY = {"i": "pqs_icelined", "ii": "pqs_sdd", "iii": "solar_clinic"}  # engine fix -> types.ts FixCategory
DEFAULT_PLAN_STATE = "Edo"
PLAN_TARGET = 0.99  # facility_results.parquet was computed at this target (engine.batch.TARGET)


def num(x, nd: int | None = None):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, nd) if nd is not None else f


def jload(x, default=None):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return default
    if isinstance(x, (dict, list)):
        return x
    try:
        return json.loads(x)
    except (TypeError, ValueError):
        return default


def _norm(name) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def feeder_slug(row_key: str) -> str:
    """'PHED_..._097.pdf#p16#sn178' -> 'PHED_..._097-p16-sn178' (safe in a URL path)."""
    m = re.match(r"^(.*?)(?:\.pdf)?#p(\d+)#sn(.+)$", row_key)
    if not m:
        return re.sub(r"[^A-Za-z0-9_.-]", "-", row_key)
    return f"{m.group(1)}-p{m.group(2)}-sn{m.group(3)}"


def _iv(row, name: str) -> dict | None:
    p = num(row.get(name))
    if p is None:
        return None
    return {"p": p, "lo": num(row.get(f"{name}_lo")), "hi": num(row.get(f"{name}_hi"))}


def _rng(row, name: str) -> dict | None:
    p = num(row.get(name))
    if p is None:
        return None
    return {"lo": num(row.get(f"{name}_lo")), "mid": p, "hi": num(row.get(f"{name}_hi"))}


def catchment_fields(row) -> dict:
    """capped and doses_demand_uncapped from facility_results; catchment_pop and pop_above_cap from catchments."""
    cap = row.get("capped")
    return {"capped": None if cap is None or (isinstance(cap, float) and math.isnan(cap)) or cap is pd.NA
            else bool(cap),
            "catchment_pop": num(row.get("catchment_pop"), 0), "pop_above_cap": num(row.get("pop_above_cap"), 0),
            "doses_demand_uncapped": num(row.get("doses_demand_uncapped"), 0)}


class LiveStore:
    fixture = False

    def __init__(self, s: Settings):
        self.s = s
        work = s.work
        need = ["facilities", "matches", "facility_results", "nerc_rows"]
        missing = [n for n in need if not (work / f"{n}.parquet").exists()]
        if missing:
            raise RuntimeError(f"data/work is missing {missing}; run the data build or set WARDLIGHT_FIXTURE=1")
        fac = pd.read_parquet(work / "facilities.parquet")
        fac = fac.sort_values("latitude", na_position="last").drop_duplicates("unique_id")
        m = pd.read_parquet(work / "matches.parquet")
        r = pd.read_parquet(work / "facility_results.parquet").rename(columns={"tier": "result_tier"})
        # catchment figures come from catchments.parquet; the copies the batch carries are kept under result_*
        r = r.rename(columns={c: f"result_{c}" for c in ("catchment_pop", "catchment_pop_raw", "pop_above_cap")
                              if c in r})
        cat = (pd.read_parquet(work / "catchments.parquet")[["unique_id", "catchment_pop", "pop_above_cap"]]
               if (work / "catchments.parquet").exists() else None)
        t = fac.merge(m.rename(columns={c: f"m_{c}" for c in m.columns if c != "unique_id"}), on="unique_id",
                      how="left").merge(r, on="unique_id", how="left")
        if cat is not None:
            t = t.merge(cat, on="unique_id", how="left")
        else:
            t["catchment_pop"] = np.nan
            t["pop_above_cap"] = np.nan
        for col in ("capped", "doses_demand_uncapped"):
            if col not in t:
                t[col] = np.nan
        # the current match decides the tier; the result's own tier is kept, and a difference marks it stale
        t["tier"] = t["m_tier"].where(t["m_tier"].notna(), t["result_tier"]).fillna("d_refused")
        t["results_stale"] = t["result_tier"].notna() & (t["result_tier"] != t["tier"])
        t["has_result"] = t["uptime_with_system"].notna()
        t = t.sort_values("unique_id").reset_index(drop=True)
        t["code"] = np.arange(1, len(t) + 1)  # SMS / USSD code: position in the sorted id list
        self.t = t
        self.idx = {u: i for i, u in enumerate(t.unique_id)}
        self.data_version = self._version(work)
        mt, rt = (work / "matches.parquet").stat().st_mtime, (work / "facility_results.parquet").stat().st_mtime
        self.staleness = {"results_older_than_matches": bool(rt < mt),
                          "facilities_tier_changed_since_results": int(t.results_stale.sum()),
                          "note": "facility_results.parquet was computed on an earlier matches.parquet; precomputed "
                                  "figures for these facilities use the earlier tier until the engine batch is re-run "
                                  "(what-if runs always use the current match)" if rt < mt else None}

        n = pd.read_parquet(work / "nerc_rows.parquet")
        n["row_key"] = [f"{f}#p{int(p)}#sn{s_}" for f, p, s_ in zip(n.order_file, n.page, n.sn)]
        n["slug"] = n.row_key.map(feeder_slug)
        self.nerc = n
        self.nerc_by_key = {k: i for i, k in enumerate(n.row_key)}
        self.nerc_by_slug = {k: i for i, k in enumerate(n.slug)}
        self.urls = nerc_urls(s.data_local / "MANIFEST.md")
        self.checks = self._load_checks()

        # feeder -> facilities
        fx = t[["unique_id", "m_feeder_ids"]].copy()
        fx["fid"] = fx.m_feeder_ids.map(lambda x: jload(x, []))
        fx = fx.explode("fid").dropna(subset=["fid"])
        self.feeder_fac: dict[str, list[str]] = fx.groupby("fid").unique_id.apply(list).to_dict()

        self._naija = None
        self._naija_lock = threading.Lock()
        self.shortfall, self.supply_meta = SP.calibrated_from_work(work)
        self.cache = Cache(s.cache_entries)
        sf = work / "nerc_shortfalls.parquet"
        self.shortfalls = pd.read_parquet(sf) if sf.exists() else pd.DataFrame(
            columns=["disco", "order_file", "page", "feeder_name", "period", "measured_avg_hours", "action"])
        self.shortfalls["name_norm"] = self.shortfalls.feeder_name.map(_norm)
        self._list_json: bytes | None = None
        self._summary = self._build_summary()
        self._results = None

    # ------------------------------------------------------------ basics

    @staticmethod
    def _version(work: Path) -> str:
        """The data version the agents' recordings carry: agents.tools.WardlightData.version (file sizes and
        mtimes, no parquet read). The same definition is written out below for when agents/ is absent."""
        try:
            from agents.tools import WardlightData

            return WardlightData(work_dir=work).version
        except Exception:  # noqa: BLE001 - agents/ absent or broken: same definition, written out
            h = hashlib.sha256()
            for name in ("facilities", "matches", "facility_results", "nerc_rows"):
                p = work / f"{name}.parquet"
                if p.exists():
                    st = p.stat()
                    h.update(f"{name}:{st.st_size}:{int(st.st_mtime)}".encode())
            return h.hexdigest()[:12]

    def _load_checks(self) -> dict[str, dict]:
        """NERC rows checked by eye: docs/VERIFIED_ROWS.csv (order_file, page, sn, checked_by, how, result), read at
        startup. A listed row is verified unless its result reports a mismatch; the result is served either way."""
        out: dict[str, dict] = {}
        p = self.s.docs / "VERIFIED_ROWS.csv"
        if p.exists():
            d = pd.read_csv(p, dtype=str).fillna("")
            for x in d.itertuples():
                key = f"{x.order_file.strip()}#p{x.page.strip()}#sn{x.sn.strip()}"
                bad = re.search(r"mismatch|wrong|error|fail|incorrect", x.result, flags=re.IGNORECASE) is not None
                out[key] = {"verified": not bad, "checked_by": x.checked_by or None, "how": x.how or None,
                            "check_result": x.result or None}
        return out

    def check_of(self, row_key: str) -> dict:
        c = self.checks.get(row_key)
        if c:  # verified_by / verified_how / verified_method are the web types' names for the same facts
            return {**c, "verified_by": c["checked_by"], "verified_how": c["how"], "verified_method": "by eye",
                    "verified_note": "checked by eye: " + (c["how"] or "method not stated")}
        return {"verified": False, "checked_by": None, "how": None, "check_result": None, "verified_by": None,
                "verified_how": None, "verified_method": "OCR", "verified_note": "read by OCR, not checked by eye"}

    def health(self) -> dict:
        return {"ok": True, "fixture": False, "sample": False, "data_version": self.data_version,
                "sources": SOURCES, "facilities": len(self.t), "with_results": int(self.t.has_result.sum()),
                "supply_calibrated": bool(self.supply_meta.get("calibrated")), "staleness": self.staleness,
                "fx": {"ngn_per_usd": C.FX_NGN_PER_USD.value, "date": C.FX_DATE}}

    def resolve(self, fid: str) -> int:
        fid = (fid or "").strip()
        if fid in self.idx:
            return self.idx[fid]
        m = re.fullmatch(r"(?:WL-?)?0*(\d{1,6})", fid, flags=re.IGNORECASE)
        if m:
            code = int(m.group(1))
            if 1 <= code <= len(self.t):
                return code - 1
        raise NotFound(f"no facility '{fid}'")

    # ------------------------------------------------------------ list and summary

    def _list_frame(self) -> pd.DataFrame:
        t = self.t
        return pd.DataFrame({
            "id": t.unique_id, "name": t.facility_name, "type": t.facility_type,
            "lat": t.latitude.round(5), "lon": t.longitude.round(5), "state": t.state_standard,
            "lga": t.lga_standard, "tier": t.tier, "p_fridge_survives": t.uptime_today.round(4), "code": t.code,
            "scenario": SCENARIO_HEADLINE,
            "capped": t.capped.astype("boolean"), "catchment_pop": t.catchment_pop.round(0),
            "pop_above_cap": t.pop_above_cap.round(0), "doses_demand_uncapped": t.doses_demand_uncapped.round(0),
        })

    def facilities(self, state=None, lga=None, q=None, tier=None, limit=None) -> list[dict] | bytes:
        if not any([state, lga, q, tier, limit]):
            if self._list_json is None:
                self._list_json = self._list_frame().to_json(orient="records").encode()
            return self._list_json
        t = self.t
        mask = pd.Series(True, index=t.index)
        if state:
            mask &= t.state_standard.str.lower() == state.strip().lower()
        if lga:
            mask &= t.lga_standard.str.lower() == lga.strip().lower()
        if tier:
            if tier not in TIERS:
                raise BadInput(f"tier must be one of {TIERS}")
            mask &= t.tier == tier
        if q:
            ql = q.strip().lower()
            mask &= (t.facility_name.str.lower().str.contains(ql, regex=False)
                     | t.unique_id.str.lower().str.contains(ql, regex=False)
                     | t.lga_standard.str.lower().str.contains(ql, regex=False)
                     | (t.code.astype(str) == ql.lstrip("wl-").lstrip("0")))
        f = self._list_frame()[mask.to_numpy()]
        if limit:
            f = f.head(int(limit))
        return json.loads(f.to_json(orient="records"))

    def _build_summary(self) -> dict:
        t = self.t
        by_state = []
        for st, g in t.groupby("state_standard"):
            by_state.append({"state": st, "total": len(g),
                             "tiers": {k: int(v) for k, v in g.tier.value_counts().items()},
                             "with_results": int(g.has_result.sum())})
        ref = t[t.tier == "d_refused"]
        reasons = ref.m_reason.fillna("no match row").map(lambda s: s.split(";")[0].strip())
        refusals = [{"reason": k, "count": int(v)} for k, v in reasons.value_counts().items()]
        res = t[t.has_result]
        fixes = {k: int(v) for k, v in res.fix_category.value_counts().items()}

        def ssum(col):
            return num(res[col].sum(skipna=True))

        tiers = {k: int(v) for k, v in t.tier.value_counts().items()}
        return {
            "sample": False, "by_state": by_state, "tiers": tiers, "refusals": refusals,
            "headline": {"facilities": len(t),
                         "matched": int(t.tier.isin(["a_named", "b_place", "c_lga_mixture", "c_unit_mixture"]).sum()),
                         "refused": int((t.tier == "d_refused").sum()), "offgrid": int((t.tier == "offgrid").sum()),
                         "with_results": len(res),
                         "no_coordinates": int(t.latitude.isna().sum()),
                         "by_source_version": {k: int(v) for k, v in t.source_version.value_counts().items()}},
            "fixes": {"counts": fixes, "labels": dict(CC.FIX_LABEL)},
            "doses_year": {"protected_today_domestic": ssum("doses_protected_today"),
                           "protected_today_pqs_ice_lined": ssum("doses_protected_today_pqs"),
                           "protected_with_fix": ssum("doses_with_system"),
                           "note": "ESTIMATE: sums over facilities with results (WorldPop catchment capped at "
                                   "20,000 people, crude birth rate, unofficial schedule)"},
            "uptime_median": {"today_domestic": num(res.uptime_today.median()),
                              "today_pqs_ice_lined": num(res.uptime_today_pqs.median()),
                              "with_fix": num(res.uptime_with_system.median()),
                              "label": "share of days a year the vaccine fridge holds 2 to 8 degC"},
            "quotes": QUOTES,
            "coverage_note": "GRID3 v3.0 covers 24 of 37 states; the other 13 come from GRID3 v2.0, each facility "
                             "labelled with its source version",
        }

    def summary(self) -> dict:
        return self._summary

    # ------------------------------------------------------------ facility record

    def _nerc_row(self, row_key: str) -> dict | None:
        i = self.nerc_by_key.get(row_key)
        return None if i is None else self.nerc.iloc[i].to_dict()

    def _evidence(self, row) -> dict | None:
        ev = jload(row.get("m_evidence"), {}) or {}
        fids = jload(row.get("m_feeder_ids"), []) or []
        if ev.get("order_file"):
            key = fids[0] if fids else f"{ev['order_file']}#p{ev.get('page')}#sn{ev.get('sn')}"
            nr = self._nerc_row(key)
            crop = None
            if nr and isinstance(nr.get("crop_path"), str) and nr["crop_path"]:
                crop = "/api/evidence/crops/" + Path(nr["crop_path"]).name
            sn = ev.get("sn")
            return {"file": ev["order_file"], "url": self.urls.get(ev["order_file"]), "page": int(ev["page"]) if str(ev.get("page", "")).isdigit() else num(ev.get("page")),
                    "sn": int(sn) if str(sn).isdigit() else sn, "row_text": ev.get("row_text"), "crop": crop,
                    **self.check_of(key),
                    "matched_on": ev.get("matched_on"), "facility_value": ev.get("facility_value"),
                    "nerc_text": ev.get("nerc_text"), "score": num(ev.get("score")),
                    "ocr_confidence": num(nr.get("ocr_confidence")) if nr else None}
        if not ev:
            return None
        src = ev.get("source")
        return {"file": None, "url": src if isinstance(src, str) and src.startswith("http") else None, "page": None,
                "sn": None, "row_text": ev.get("quote") or ev.get("row_text"), "crop": None, "verified": False,
                "source": src, "detail": ev}

    def _match(self, row) -> dict:
        bands = jload(row.get("m_bands"), {}) or {}
        bands = {str(k).upper(): float(v) for k, v in bands.items()}
        fids = jload(row.get("m_feeder_ids"), []) or []
        nr = self._nerc_row(fids[0]) if fids else None
        single = next(iter(bands)) if len(bands) == 1 else None
        ev = jload(row.get("m_evidence"), {}) or {}
        min_h = num(ev.get("min_hours")) if ev.get("min_hours") is not None else (
            C.BAND_MIN_HOURS.get(single) if single else None)
        return {"tier": row["tier"], "feeder_id": feeder_slug(fids[0]) if fids else None,
                "feeder_ids": [feeder_slug(x) for x in fids],
                "feeder_name": nr["feeder_name"] if nr else None, "disco": nr["disco"] if nr else
                (ev.get("discos") or [None])[0] if isinstance(ev.get("discos"), list) else None,
                "band": single if single in C.BAND_MIN_HOURS else None, "bands": bands, "min_hours": min_h,
                "promised_not_measured": True, "evidence": self._evidence(row),
                "reason": row.get("m_reason") or "no match row for this facility",
                "grid_km": num(row.get("m_grid_km"), 3)}

    def _bands_obj(self, row):
        from engine import batch as B

        return B.bands_for(str(row["tier"]), row.get("m_bands") if isinstance(row.get("m_bands"), str) else "{}")

    def supply_model(self, bands) -> dict:
        key = "supply:" + input_hash([bands, self.data_version])
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        if bands is None:
            out = {"label": "modelled", "promised_hours": None, "median_hours": None, "p10_hours": None,
                   "p90_hours": None, "note": "Supply unknown (refused match): no grid figure is modelled."}
        else:
            rng = np.random.default_rng(20261030)
            hours, _ = SP.sample_daily_hours(bands, 64, 365, rng, self.shortfall)
            promised = (SP.BAND_HOURS[bands] if isinstance(bands, str) else
                        (SP.BAND_HOURS[next(iter(bands))] if len(bands) == 1 else None))
            mix = "" if isinstance(bands, str) or len(bands) == 1 else (
                " Band mixture " + ", ".join(f"{k} {v:.0%}" for k, v in sorted(bands.items())) + ".")
            out = {"label": "modelled", "promised_hours": promised,
                   "median_hours": float(np.median(hours)), "p10_hours": float(np.quantile(hours, 0.10)),
                   "p90_hours": float(np.quantile(hours, 0.90)),
                   "note": ("No grid line within reach (off-grid): no grid hours are modelled." if bands == SP.OFFGRID
                            else "Promised hours are the ceiling; daily hours are modelled below them from NERC's "
                                 "published shortfalls (calibrated, T3-widened). Promised, not measured." + mix)}
        self.cache.put(key, out)
        return out

    def facility(self, fid: str) -> dict:
        i = self.resolve(fid)
        row = self.t.iloc[i].to_dict()
        lat, lon = num(row.get("latitude")), num(row.get("longitude"))
        match = self._match(row)
        facility = {"id": row["unique_id"], "code": int(row["code"]), "name": row["facility_name"],
                    "type": row["facility_type"], "level": row["facility_level"], "ownership": row["facility_ownership"],
                    "state": row["state_standard"], "lga": row["lga_standard"], "ward": row.get("ward_standard") or None,
                    "lat": lat, "lon": lon, "tier": row["tier"], "feeder_id": match["feeder_id"], "band": match["band"],
                    "grid_km": match["grid_km"], "catchment": num(row.get("catchment_pop"), 0),
                    **catchment_fields(row),
                    "source_version": row.get("source_version"), "functional": row.get("functional")}
        rec: dict = {"sample": False, "data_version": self.data_version, "facility": facility, "match": match,
                     "refused": row["tier"] == "d_refused" or not row["has_result"],
                     "result_tier": row.get("result_tier") if isinstance(row.get("result_tier"), str) else None,
                     "results_stale": bool(row.get("results_stale"))}
        if not row["has_result"]:
            rec["refused_reason"] = ("no engine result: the registry gives no coordinates for this facility"
                                     if lat is None else "no engine result for this facility")
            return rec
        bands = self._bands_obj(row)
        fridge = jload(row.get("system_fridge"), {}) or {}
        clinic = jload(row.get("system_clinic"), {}) or {}
        rec["supply_model"] = self.supply_model(bands)
        rec["loads"] = W.loads_table(fridge.get("code"))
        rec["scenarios"] = self._scenarios(row)
        rec["scenarios_detail"] = {
            "today_domestic_technical": _iv(row, "uptime_today_technical"),
            "with_fix": _iv(row, "uptime_with_system"), "with_fix_technical": _iv(row, "uptime_with_fix_technical"),
            "note": row.get("today_scenario"),
            "technical": "technical figures assume no breakdowns; the others include the availability scenario "
                         "(0.90 to 0.99)",
        }
        rec["fix"] = self._fix(row, bands, fridge)
        rec["survival_today"], rec["survival_with_system"] = self._survival(row)
        rec["brief_metric"] = {
            "uptime_today": _iv(row, "uptime_today"), "uptime_today_pqs": _iv(row, "uptime_today_pqs"),
            "uptime_with_system": _iv(row, "uptime_with_system"),
            "doses_year": num(row.get("doses_per_year"), 0),
            "doses_protected_today": num(row.get("doses_protected_today"), 0),
            "doses_protected_today_pqs": num(row.get("doses_protected_today_pqs"), 0),
            "doses_protected_with_system": num(row.get("doses_with_system"), 0),
            "doses": {k: {"p": num(row.get(c), 0), "lo": num(row.get(f"{c}_lo"), 0), "hi": num(row.get(f"{c}_hi"), 0)}
                      for k, c in (("today", "doses_protected_today"), ("today_pqs", "doses_protected_today_pqs"),
                                   ("with_fix", "doses_with_system"))},
            "doses_note": ("Estimate: WorldPop catchment within 5 km, capped at 20,000 people, x crude birth rate "
                           "32.493 per 1,000 (World Bank 2024) x 20 doses per child in year one (FHIR IG schedule, "
                           "unofficial); 'today' assumes a domestic fridge"),
        }
        rec["recommended"] = self._recommended(row, fridge, clinic)
        rec["labels"] = jload(row.get("labels"), {})
        head = num(row.get("uptime_today"))
        rec["trace"] = self.simulate(row["unique_id"], {"loads": list(W.ROOMS), "pv_kwp": 0.0, "battery_kwh": 0.0,
                                                         "target": PLAN_TARGET, "fridge_mode": "shared",
                                                         "_prefer_held": None if head is None else head >= 0.5}
                                     )["trace"]
        rec["trace"]["draw"]["headline_uptime"] = head
        rec["trace"]["draw"]["headline_source"] = ("facility_results.parquet uptime_today (domestic scenario, "
                                                   f"{int(row.get('n_lanes') or 0)} lanes); the ring's run uses "
                                                   f"{rec['trace']['draw']['n_lanes']} lanes with the same seed")
        return rec

    @staticmethod
    def _scenarios(row) -> list[dict]:
        out = []
        dom, pqs = _iv(row, "uptime_today"), _iv(row, "uptime_today_pqs")
        if dom:
            out.append({"key": "domestic", "label": "Household or non-PQS fridge (headline)", "headline": True,
                        "uptime": dom, "note": "Today's equipment is unknown; a household fridge (4 h at 2 to 8 degC "
                                               "without power, range 1.5 to 6 h, NIST) is the headline assumption"})
        if pqs:
            out.append({"key": "pqs_icelined", "label": "PQS ice-lined fridge", "headline": False, "uptime": pqs,
                        "note": "If the clinic already has a PQS mains ice-lined fridge (holdover from the PQS sheet, "
                                "an upper bound)"})
        return out

    @staticmethod
    def _fix(row, bands, fridge: dict) -> dict | None:
        cat = row.get("fix_category")
        if cat not in FIX_CATEGORY:
            return None
        if cat == "i":
            why = ("The grid this facility is promised keeps a PQS ice-lined fridge at 2 to 8 degC on at least 99% of "
                   "days at the pessimistic end, and it is the cheapest fix that does")
        elif cat == "iii":
            why = ("No grid reaches this facility, so a PQS solar direct-drive fridge is the cold-chain fix and the "
                   "separate clinic system is the only power for the delivery room at night")
        elif bands is None:
            why = ("Today's grid supply is unknown (refused match), so only a fix that needs no grid is recommended: "
                   "a PQS solar direct-drive fridge")
        else:
            why = ("A PQS ice-lined fridge on this supply misses 99% of days at the pessimistic end; a PQS solar "
                   "direct-drive fridge meets it")
        name = fridge.get("name")
        return {"category": FIX_CATEGORY[cat], "engine_category": cat, "label": row.get("fix_label"),
                "model": name, "model_code": fridge.get("code"), "reason": why,
                "cost_ngn": num(row.get("capex_ngn"), 0),
                "cost_note": (f"{name}: PQS product sheet price, EXW, converted at the CBN central rate of "
                              f"{C.FX_DATE}; excludes freight and installation"
                              + ("" if cat != "iii" else "; the clinic system is its own optional line")),
                "target_met": bool(row.get("fix_target_met"))}

    def _survival(self, row) -> tuple[list, list]:
        today, with_ = [], []
        ft, fw = _iv(row, "uptime_today"), _iv(row, "uptime_with_system")
        if ft:
            today.append({"load": "fridge", "name": W.ROOM_NAMES["fridge"], **ft})
        if fw:
            with_.append({"load": "fridge", "name": W.ROOM_NAMES["fridge"], **fw})
        ct, cw = _iv(row, "crit_uptime_today"), _iv(row, "crit_uptime_with")
        for room in ("delivery", "oxygen", "ward"):  # the priority-1 rooms; the engine reports them together
            if ct:
                today.append({"load": room, "name": W.ROOM_NAMES[room], **ct, "combined": "priority-1 loads"})
            if cw:
                with_.append({"load": room, "name": W.ROOM_NAMES[room], **cw, "combined": "priority-1 loads",
                              "system": "the separate clinic system, at its recommended size"})
        return today, with_

    def _recommended(self, row, fridge: dict, clinic: dict) -> dict:
        cat = row.get("fix_category")
        codes = CC.ILR_FIX_MODELS if cat == "i" else CC.SDD_FIX_MODELS
        hold = [F.CATALOGUE[c].holdover_h for c in codes if F.CATALOGUE[c].holdover_h]
        design = {"i": "PQS mains ice-lined vaccine fridge on the grid the facility has",
                  "ii": "PQS solar direct-drive vaccine fridge, dedicated array, no other loads",
                  "iii": "PQS solar direct-drive vaccine fridge, dedicated array, plus the separate clinic system"
                  }.get(cat, CC.FIX_LABEL.get(cat, ""))
        diesel_counted = bool(row.get("diesel_counted"))
        pb = num(row.get("payback_months"), 0)
        return {
            "fix": {"category": cat, "label": row.get("fix_label"), "model_code": fridge.get("code"),
                    "model_name": fridge.get("name"), "kind": fridge.get("kind"), "target_met": fridge.get("target_met"),
                    "price_usd": _rng(row, "capex_usd"), "price_ngn": _rng(row, "capex_ngn"),
                    "monthly_ngn": _rng(row, "monthly_cost_ngn"),
                    "doses_gain_year": num(row.get("doses_gain"), 0),
                    "doses_per_mngn": num(row.get("doses_per_mngn_fix"), 1),
                    "price_basis": fridge.get("price_basis"),
                    "monthly_basis": "price over a 10-year fridge life, undiscounted"},
            "fridge_system": {"design": design, "holdover_h_range": [round(min(hold), 1), round(max(hold), 1)],
                              "note": "WHO PQS holdover is measured to +10 degC, an upper bound for 2 to 8 degC; "
                                      "PQS PV01.3 forbids other loads on a PQS solar fridge system"},
            "clinic_system": {"design": "Separate clinic system for priority-1 loads (interior lights, oxygen, suction, "
                                        "procedure light, fetal monitor), optional",
                              "pv_kwp": num(clinic.get("pv_kwp")), "battery_kwh": num(clinic.get("battery_kwh")),
                              "knee_pv_kwp": num(clinic.get("knee_pv_kwp")), "target_met": clinic.get("target_met"),
                              "recommended": bool(clinic.get("recommended")), "optional": True},
            # the cold-chain fix (the recommended purchase)
            "capex_usd": _rng(row, "capex_usd"), "capex_ngn": _rng(row, "capex_ngn"),
            "monthly_cost_ngn": num(row.get("monthly_cost_ngn"), 0),
            # the optional clinic line: diesel, payback and CO2 belong to it, never to the fridge
            "monthly_diesel_ngn": num(row.get("diesel_ngn_month_avoided"), 0) if diesel_counted else 0,
            "payback_months": pb, "diesel_l_avoided": num(row.get("diesel_l_avoided"), 0),
            "co2_kg_avoided": num(row.get("co2_kg_avoided"), 0),
            "clinic_line": {"capex_usd": _rng(row, "clinic_capex_usd"), "capex_ngn": _rng(row, "clinic_capex_ngn"),
                            "monthly_cost_ngn": _rng(row, "clinic_monthly_cost_ngn"),
                            "diesel_ngn_month_avoided": _rng(row, "diesel_ngn_month_avoided"),
                            "diesel_l_avoided_year": _rng(row, "diesel_l_avoided"),
                            "co2_kg_avoided_year": _rng(row, "co2_kg_avoided"),
                            "payback_months": _rng(row, "payback_months"), "diesel_counted": diesel_counted},
            "lines_note": ("capex_* and monthly_cost_ngn are the cold-chain fix; monthly_diesel_ngn, payback_months, "
                           "diesel_l_avoided and co2_kg_avoided are the optional clinic system's line (diesel counted "
                           "only for grid-connected facilities); payback_months null means it does not pay back"),
            "who_pays": WHO_PAYS, "maintains": MAINTAINS,
        }

    # ------------------------------------------------------------ what-if

    def simulate(self, fid: str, req: dict) -> dict:
        i = self.resolve(fid)
        row = self.t.iloc[i].to_dict()
        lat, lon = num(row.get("latitude")), num(row.get("longitude"))
        if lat is None or lon is None:
            raise BadInput("this facility has no coordinates in the registry, so it cannot be simulated")
        bands = self._bands_obj(row)
        from engine import solar as S

        point = S.nearest_point(lat, lon)
        rooms = sorted(set(req["loads"]), key=W.ROOMS.index)
        key_in = {"point": point, "bands": bands, "rooms": rooms, "pv": req["pv_kwp"], "bat": req["battery_kwh"],
                  "mode": req["fridge_mode"], "target": req["target"], "draws": self.s.whatif_draws,
                  "v": self.data_version, "prefer_held": req.get("_prefer_held")}
        key = "whatif:" + input_hash(key_in)
        hit = self.cache.get(key)
        snapped = bool(req.get("_snapped"))
        if hit is not None:
            return {**hit, "cached": True, "snapped": snapped}
        out = W.run(float(point[0]), float(point[1]), bands, rooms, req["pv_kwp"], req["battery_kwh"],
                    req["fridge_mode"], req["target"], self.s.whatif_draws, self.shortfall,
                    prefer_held=req.get("_prefer_held"))
        out.update({"sample": False, "input_hash": key[7:23]})
        self.cache.put(key, out)
        return {**out, "cached": False, "snapped": snapped}

    # ------------------------------------------------------------ plan

    def _state(self, state: str | None) -> str:
        st = (state or DEFAULT_PLAN_STATE).strip()
        for s_ in self.t.state_standard.dropna().unique():
            if s_.lower() == st.lower():
                return s_
        raise NotFound(f"no state '{state}' in the facility registry")

    def plan(self, state: str | None, budget_ngn: float | None, target: float | None) -> dict:
        if target is not None and abs(float(target) - PLAN_TARGET) > 1e-9:
            raise BadInput(f"results are precomputed at target {PLAN_TARGET}; another target needs an engine batch "
                           "re-run")
        st = self._state(state)
        key = "plan:" + input_hash([st, budget_ngn, self.data_version])
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        df = self.t[(self.t.state_standard == st) & self.t.has_result].copy()
        df["state"] = df.state_standard
        # a facility refused under the current match has no "today" figure, whatever an older result says
        df.loc[df.tier == "d_refused", ["doses_protected_today", "uptime_today"]] = np.nan
        budget = float(budget_ngn) if budget_ngn is not None else float(df.capex_ngn.sum(skipna=True))
        ranked = PL.rank(df, budget, "doses")
        summ = PL.summary(ranked, "doses")
        rk = ranked[ranked["rank"].notna()]
        rows = []
        for _, r in rk.iterrows():
            ut, uw = num(r.uptime_today), num(r.uptime_with_system)
            ct, lh = num(r.get("crit_uptime_today")), num(r.get("critical_load_hours_day"))
            rows.append({
                "id": r.unique_id, "code": int(r.code), "name": r.facility_name, "lga": r.lga_standard,
                "lat": num(r.latitude, 5), "lon": num(r.longitude, 5), "tier": r.tier, "rank": int(r["rank"]),
                "cost_ngn": num(r.cost_ngn, 0), "cumulative_ngn": num(r.cum_cost_ngn, 0),
                "funded": bool(r.funded), "fix": FIX_CATEGORY.get(r.fix_category), "fix_category": r.fix_category,
                "fridge_nights_saved": None if ut is None or uw is None else round((uw - ut) * 365.0, 1),
                "unmet_hours": None if ct is None or lh is None else round((1.0 - ct) * lh, 2),
                "uptime_today": ut, "uptime_today_pqs": num(r.uptime_today_pqs), "uptime_with_system": uw,
                "scenario": SCENARIO_HEADLINE, "scenarios": UPTIME_SCENARIOS,
                "doses_protected_gain": num(r.benefit, 0), "score": num(r.benefit_per_mngn, 1), "reason": r.reason,
                **catchment_fields(r),
            })
        nr = ranked[ranked["rank"].isna()]
        refused_all = self.t[(self.t.state_standard == st) & ~self.t.has_result]
        out = {
            "sample": False, "state": st, "target": PLAN_TARGET, "metric": "doses",
            "budget_ngn": budget, "budget_ngn_max": num(rk.cum_cost_ngn.max(), 0) if len(rk) else 0,
            "currency_note": f"Converted at N{C.FX_NGN_PER_USD.value:,.2f} per USD, CBN central rate, {C.FX_DATE}",
            "ranked": rows,
            "not_ranked": {"count": len(nr) + len(refused_all),
                           "unknown_supply": len(nr), "no_result": len(refused_all),
                           "reason": "not ranked: today's grid supply is unknown (refused match) or the facility has "
                                     "no engine result, so the gain cannot be computed"},
            "summary": {**summ, "capped_funded": int(rk.loc[rk.funded, "capped"].fillna(False).astype(bool).sum())},
            "field_notes": {"fridge_nights_saved": "days a year the fridge holds 2 to 8 degC gained: (uptime with the "
                                                   "fix - uptime today, domestic fridge) x 365",
                            "unmet_hours": "critical load-hours a day at risk today: (1 - share of days the priority-1 "
                                           "loads are fully served on grid alone) x their load-hours a day",
                            "score": "doses protected a year gained per N1m of the cold-chain fix (engine.plan.rank)"},
        }
        self.cache.put(key, out)
        return out

    # ------------------------------------------------------------ investment brief

    def _citation(self, row) -> dict:
        ev = jload(row.get("m_evidence"), {}) or {}
        if ev.get("order_file"):
            f = ev["order_file"]
            ck = self.check_of(f"{f}#p{ev.get('page')}#sn{ev.get('sn')}")
            return {"kind": "nerc_row", "file": f, "url": self.urls.get(f), "page": ev.get("page"), "sn": ev.get("sn"),
                    "row_text": ev.get("row_text"), "verified": ck["verified"], "checked_by": ck["checked_by"],
                    "verified_note": ck["verified_note"],
                    "text": f"NERC order {f}, page {ev.get('page')}, row {ev.get('sn')}: {ev.get('row_text')}"}
        src = ev.get("source")
        if row.get("tier") == "offgrid":
            text = f"Gridfinder: nearest line {num(ev.get('grid_km'), 1)} km; {row.get('m_reason')}"
        elif ev.get("band_counts"):
            text = (f"Band mixture over {ev.get('feeders')} feeders of {ev.get('unit')} "
                    f"({src}, order month {ev.get('order_month')})")
        else:
            text = str(row.get("m_reason") or src or "no evidence recorded")
        return {"kind": "tier_evidence", "file": None, "url": src if isinstance(src, str) and src.startswith("http")
                else None, "page": None, "sn": None, "row_text": None, "text": text}

    def brief(self, state: str | None, budget_ngn: float | None, metric: str = "doses") -> dict:
        if metric not in ("doses", "load_hours"):
            raise BadInput("metric must be 'doses' or 'load_hours'")
        st = self._state(state)
        key = "brief:" + input_hash([st, budget_ngn, metric, self.data_version])
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        all_st = self.t[self.t.state_standard == st]
        df = all_st[all_st.has_result].copy()
        df["state"] = df.state_standard
        refused_now = df.tier == "d_refused"
        df.loc[refused_now, ["doses_protected_today", "uptime_today", "crit_uptime_today"]] = np.nan
        cost_col = "clinic_capex_ngn" if metric == "load_hours" else "capex_ngn"
        budget = float(budget_ngn) if budget_ngn is not None else float(df[cost_col].sum(skipna=True))
        ranked = PL.rank(df, budget, metric)
        summ = PL.summary(ranked, metric)
        rk = ranked[ranked["rank"].notna()]
        fund = rk[rk.funded]
        unit = "vaccine doses protected a year (estimate)" if metric == "doses" else \
            "critical load-hours restored a year"
        rows = []
        for _, r in fund.iterrows():
            fridge = jload(r.get("system_fridge"), {}) or {}
            clinic = jload(r.get("system_clinic"), {}) or {}
            rows.append({
                "rank": int(r["rank"]), "id": r.unique_id, "code": int(r.code), "name": r.facility_name,
                "lga": r.lga_standard, "type": r.facility_type, "tier": r.tier,
                "fix": FIX_CATEGORY.get(r.fix_category), "fix_label": r.fix_label, "fix_model": fridge.get("name"),
                "clinic_system": ({"pv_kwp": num(clinic.get("pv_kwp")), "battery_kwh": num(clinic.get("battery_kwh"))}
                                  if metric == "load_hours" else None),
                "cost_ngn": num(r.cost_ngn, 0), "cumulative_ngn": num(r.cum_cost_ngn, 0),
                "benefit": num(r.benefit, 1), "benefit_unit": unit, "benefit_per_mngn": num(r.benefit_per_mngn, 1),
                "doses_year": num(r.doses_per_year, 0), "doses_gain": num(r.doses_gain, 0),
                "uptime_today": num(r.uptime_today, 4), "uptime_with_fix": num(r.uptime_with_system, 4),
                "scenario": SCENARIO_HEADLINE,
                "scenarios": {"uptime_today": SCENARIO_HEADLINE, "uptime_with_fix": UPTIME_SCENARIOS["uptime_with_system"]},
                "results_stale": bool(r.get("results_stale")), "citation": self._citation(r),
                **catchment_fields(r),
            })
        unfunded = rk[~rk.funded]
        unknown = ranked[ranked["rank"].isna()]
        no_result = all_st[~all_st.has_result]
        fix_counts = {FIX_CATEGORY.get(k, k): int(v) for k, v in fund.fix_category.value_counts().items()}
        fix_spend = {FIX_CATEGORY.get(k, k): num(v, 0) for k, v in fund.groupby("fix_category").cost_ngn.sum().items()}
        not_reached = [
            {"group": "ranked, over budget", "count": len(unfunded),
             "cost_ngn_to_fund_all": num(unfunded.cost_ngn.sum(), 0), "benefit_forgone": num(unfunded.benefit.sum(), 0),
             "why": "ranked lower than the funded list and the budget is spent"},
            {"group": "supply unknown (refused match)", "count": len(unknown),
             "why": "today's grid supply is unknown (the state has left NERC's orders, or no evidence), so the gain "
                    "cannot be computed; a no-grid fix (PQS solar fridge) is still listed on each facility's page"},
            {"group": "no engine result", "count": len(no_result),
             "why": "the registry gives no coordinates for these facilities, so no weather or catchment can be read"},
        ]
        assumptions = []
        for name in dir(C):
            c = getattr(C, name)
            if isinstance(c, C.Const) and c.status in ("ASSUMPTION", "UNVERIFIED"):
                assumptions.append({"name": name.lower(), "value": c.value, "lo": c.lo, "hi": c.hi, "unit": c.unit,
                                    "status": c.status, "source": c.source})
        out = {
            "sample": False, "kind": "investment_brief", "data_version": self.data_version, "state": st,
            "metric": metric, "benefit_unit": unit, "budget_ngn": budget, "target": PLAN_TARGET,
            "currency_note": f"Converted at N{C.FX_NGN_PER_USD.value:,.2f} per USD, CBN central rate, {C.FX_DATE}",
            "funded": rows,
            "totals": {"funded": len(rows), "spent_ngn": num(fund.cost_ngn.sum(), 0),
                       "left_ngn": num(budget - fund.cost_ngn.sum(), 0), "benefit": num(fund.benefit.sum(), 0),
                       "doses_protected_today": num(fund.doses_protected_today.sum(skipna=True), 0),
                       "doses_protected_with_fix": num(fund.doses_with_system.sum(skipna=True), 0),
                       "fixes": fix_counts, "spend_by_fix_ngn": fix_spend,
                       "candidates": summ["candidates"], "facilities_in_state": len(all_st),
                       "capped_funded": int(fund.capped.fillna(False).astype(bool).sum()),
                       "capped_note": "funded facilities whose catchment was capped at 20,000 people: their doses "
                                      "are counted at the cap, and doses_demand_uncapped shows the demand above it"},
            "not_reached": not_reached,
            "method": ("engine.plan.rank: benefit per naira, greedy under the budget, skipping a facility that does "
                       "not fit; benefit is " + unit + ("; cost is the cold-chain fix" if metric == "doses" else
                                                         "; cost is the separate clinic system")),
            "scenarios": [
                {"key": "domestic", "headline": True, "text": "today: a household or non-PQS fridge (4 h at 2 to 8 "
                 "degC without power, range 1.5 to 6 h, NIST lab test), because today's equipment is unknown"},
                {"key": "pqs_icelined", "headline": False, "text": "today, alongside: a PQS mains ice-lined fridge"},
                {"key": "no_fridge", "headline": False, "text": "no fridge (vaccines brought by outreach): stated, "
                 "not modelled"},
                {"key": "availability", "headline": False, "text": "every fridge figure includes an equipment "
                 "availability scenario value of 0.90 to 0.99, not sourced"},
            ],
            "labels": {"supply": "MODELLED from the NERC band promise; promised, not measured",
                       "doses": "ESTIMATE: WorldPop catchment within 5 km capped at 20,000 people, crude birth rate, "
                                "unofficial schedule",
                       "prices": "PQS product sheet prices, EXW, exclude freight, installation and voltage regulators"},
            "assumptions": assumptions,
            "sources": SOURCES,
            "staleness": self.staleness,
        }
        self.cache.put(key, out)
        return out

    # ------------------------------------------------------------ feeders

    def _naija_hist(self):
        with self._naija_lock:
            if self._naija is None:
                p = self.s.data_local / "naija-grid" / "band_history_wide.csv"
                self._naija = pd.read_csv(p, dtype=str) if p.exists() else pd.DataFrame()
            return self._naija

    def feeder(self, fid: str) -> dict:
        i = self.nerc_by_slug.get(fid)
        if i is None:
            i = self.nerc_by_key.get(fid)
        if i is None:
            raise NotFound(f"no feeder row '{fid}'")
        r = self.nerc.iloc[i]
        same = self.nerc[(self.nerc.disco == r.disco) & (self.nerc.feeder_name == r.feeder_name)]
        rows = [{"file": x.order_file, "url": self.urls.get(x.order_file), "page": int(x.page),
                 "sn": None if pd.isna(x.sn) else int(x.sn), "band": x.band, "feeder_name": x.feeder_name,
                 "location": x.location, "streets": x.streets, "min_hours": num(x.min_hours),
                 "order_month": x.order_month, "id": x.slug, **self.check_of(x.row_key),
                 "ocr_confidence": num(x.ocr_confidence, 3),
                 "crop": ("/api/evidence/crops/" + Path(x.crop_path).name) if isinstance(x.crop_path, str) else None}
                for x in same.itertuples()]
        history = [{"order_file": x.order_file, "order_month": x.order_month, "band": x.band,
                    "min_hours": num(x.min_hours), "source": "NERC order (this build's reading)"}
                   for x in same.sort_values("order_month").itertuples()]
        note = "Band history from the NERC orders read for this build"
        nh = self._naija_hist()
        if len(nh):
            hit = nh[(nh.disco == r.disco) & (nh.feeder_raw.str.upper() == str(r.feeder_name).upper())]
            if len(hit) == 1:
                months = [c for c in nh.columns if re.fullmatch(r"\d{4}-\d{2}", c)]
                h = hit.iloc[0]
                for mth in months:
                    b = h[mth]
                    if isinstance(b, str) and b in C.BAND_MIN_HOURS:
                        history.append({"order_file": "naija-grid band_history_wide.csv", "order_month": mth,
                                        "band": b, "min_hours": C.BAND_MIN_HOURS[b],
                                        "source": "naija-grid (NERC monthly orders, MIT)"})
                history.sort(key=lambda x: x["order_month"])
                note += "; plus naija-grid's monthly history for the feeder of the same name in this DisCo"
            elif len(hit) > 1:
                note += f"; naija-grid lists {len(hit)} feeders of this name in this DisCo, so its history is not joined"
            else:
                note += "; no naija-grid feeder of the same name in this DisCo"
        facs = []
        for u in self.feeder_fac.get(r.row_key, []):
            fr = self.t.iloc[self.idx[u]]
            ev = jload(fr.m_evidence, {}) or {}
            how = f"{fr.m_reason}" + (f" (matched on {ev.get('matched_on')}: '{ev.get('facility_value')}' ~ "
                                      f"'{ev.get('nerc_text')}')" if ev.get("matched_on") else "")
            facs.append({"id": u, "name": fr.facility_name, "tier": fr.tier, "how": how})
        return {"sample": False, "id": r.slug, "row_key": r.row_key, "name": r.feeder_name, "disco": r.disco,
                "band": r.band, "min_hours": num(r.min_hours), "band_history": history, "history_note": note,
                "rows": rows, "facilities": facs, "promised_not_measured": True,
                "served_summary": self.served_summary(r)}

    def served_summary(self, r) -> dict:
        """Who depends on this feeder row, and how its promise compares with any measured hours."""
        uids = self.feeder_fac.get(r.row_key, [])
        f = self.t.iloc[[self.idx[u] for u in uids]] if uids else self.t.iloc[0:0]
        typ = f.facility_type.fillna("").str.lower()
        hosp = typ.str.contains("hospital")
        phc = typ.str.contains("primary health") | typ.str.contains("health post") | typ.str.contains(
            "health center") | typ.str.contains("health centre")
        n_feeders = f.m_feeder_ids.map(lambda x: len(jload(x, []) or []))
        doses = f.doses_per_year
        promised = num(r.min_hours)
        meas = self.shortfalls[(self.shortfalls.disco == r.disco)
                               & (self.shortfalls.name_norm == _norm(r.feeder_name))]
        measured = [{"order_file": x.order_file, "file": x.order_file, "page": int(x.page), "period": x.period,
                     "measured_avg_hours": num(x.measured_avg_hours), "action": x.action,
                     "promised_hours": promised,
                     "gap_hours": None if promised is None or pd.isna(x.measured_avg_hours)
                     else round(promised - float(x.measured_avg_hours), 2)} for x in meas.itertuples()]
        d = self.shortfalls[(self.shortfalls.disco == r.disco) & self.shortfalls.measured_avg_hours.notna()]
        disco_ctx = None
        if len(d):
            med = float(d.measured_avg_hours.median())
            disco_ctx = {"failing_band_a_rows_with_measured_hours": len(d),
                         "median_measured_avg_hours": med,
                         "band_a_promise_hours": C.BAND_MIN_HOURS["A"],
                         "median_gap_hours": round(C.BAND_MIN_HOURS["A"] - med, 2),
                         "label": f"{r.disco}-wide, Band A feeders NERC published as failing; not this feeder"}
        return {
            "facilities": len(f),
            "by_tier": {k: int(v) for k, v in f.tier.value_counts().items()},
            "by_level": {(k or "not stated"): int(v) for k, v in f.facility_level.fillna("").value_counts().items()},
            "hospitals": int(hosp.sum()), "phcs": int(phc.sum()),
            "type_rule": "hospital: facility_type contains 'hospital'; PHC: primary health centre or clinic, health "
                         "post, health centre",
            "doses_year": num(doses.sum(skipna=True), 0),
            "doses_year_facilities": int(doses.notna().sum()),
            "doses_year_shared_with_other_feeders": num(doses[n_feeders > 1].sum(skipna=True), 0),
            "doses_note": "ESTIMATE (doses_per_year in facility_results.parquet); a facility matched to several feeder "
                          "rows counts in full on each of them",
            "promised_hours": promised, "measured": measured,
            "measured_note": ("NERC published measured hours for this feeder" if measured else
                              "NERC's shortfall appendices give no measured hours for this feeder (rows matched by "
                              "DisCo and exact feeder name)"),
            "disco_context": disco_ctx,
        }

    def crop_path(self, name: str) -> Path | None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.png", name or ""):
            return None
        p = self.s.work / "nerc_crops" / name
        return p if p.is_file() else None

    # ------------------------------------------------------------ results

    def results(self) -> dict:
        if self._results is None:
            self._results = R.build(self.s, self)
        return self._results

    # ------------------------------------------------------------ telephony

    def lookup_short(self, code: str) -> dict | None:
        try:
            i = self.resolve(code)
        except NotFound:
            return None
        row = self.t.iloc[i]
        return {"id": row.unique_id, "code": int(row.code), "name": row.facility_name, "tier": row.tier,
                "has_result": bool(row.has_result), "fix_category": row.get("fix_category"),
                "fix_label": row.get("fix_label"), "capex_ngn": num(row.get("capex_ngn")),
                "uptime_today": num(row.get("uptime_today")), "uptime_today_pqs": num(row.get("uptime_today_pqs")),
                "uptime_with_system": num(row.get("uptime_with_system")), "reason": row.get("m_reason")}
