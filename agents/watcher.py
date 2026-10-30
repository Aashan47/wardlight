"""The regulator watcher: diff feeder bands between two NERC monthly orders, re-run the affected facilities, write a
band-change report. Real changes only: every change comes from naija-grid's `caps_long.csv` (NERC's monthly cap
orders, CC BY 4.0, credit NERC) and every facility link from Wardlight's own matches.

    python -m agents.watcher --old 2026-09 --new 2026-10 [--out DIR] [--max-keys N] [--draws N]

Steps:
1. diff: feeders listed in both months whose band differs (feeders added or dropped are counted, not diffed);
2. link: each changed feeder to the September NERC rows Wardlight reads (`nerc_rows`), by DisCo and normalised
   feeder name (exact match only, no fuzzy guessing); the September row's own band is reported next to
   naija-grid's, as a consistency check;
3. affected facilities:
   (a) facilities matched to a linked row (tiers a, b, c_lga_mixture): each row is one equal vote in the
       facility's band mixture (the matcher's rule). The stored vote sits at the band the NERC row Wardlight
       reads shows; the old and new mixtures put that vote at the old and the new band. Each facility is marked
       "current" when Wardlight's row already shows the new band, "stale" when it shows the old one;
   (b) unit mixtures (c_unit_mixture): their mixture is the band share among a state's or business unit's
       feeders in one order month (`evidence.order_month`); when that month is one of the two being compared,
       the mixture is recomputed for the other month and the facility is affected if it changed;
4. re-run: the engine's cold-chain assessment (fix category, today's uptime) for each affected facility under the
   old and the new bands, once per (weather point, bands) key;
5. report: JSON and markdown, grounded (every number in the markdown traced to the computed records).
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from . import engine_adapter as EA
from . import events as EV
from . import grounding as G
from .tools import NAIJA, WardlightData, _json

FIX_SHORT = {"i": "a PQS mains ice-lined fridge", "ii": "a PQS solar direct-drive fridge",
             "iii": "a solar fridge plus the clinic system", "none": "no listed fix meeting the target"}
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "agents"


def norm_name(s) -> str:
    s = re.sub(r"[^A-Z0-9 ]", " ", str(s or "").upper())
    return re.sub(r"\s+", " ", s).strip()


def state_key(s) -> str:
    c = norm_name(s)
    return "FCT" if c.startswith("FCT") or c in {"ABUJA", "FEDERAL CAPITAL TERRITORY"} else c


def load_caps(naija_dir: Path = NAIJA) -> pd.DataFrame:
    c = pd.read_csv(naija_dir / "caps_long.csv", dtype=str,
                    usecols=["feeder_id", "disco", "state", "order_month", "band", "source_file", "source_page"])
    f = pd.read_csv(naija_dir / "feeders.csv", dtype=str, usecols=["feeder_id", "feeder_raw", "business_unit"])
    return c.merge(f, on="feeder_id", how="left")


def diff_months(caps: pd.DataFrame, old: str, new: str) -> tuple[pd.DataFrame, dict]:
    a = caps[caps.order_month == old]
    b = caps[caps.order_month == new]
    if a.empty or b.empty:
        raise ValueError(f"no cap orders for {old if a.empty else new} in caps_long.csv")
    j = a.merge(b[["feeder_id", "band", "source_file", "source_page"]], on="feeder_id", suffixes=("_old", "_new"))
    ch = j[(j.band_old != j.band_new) & j.band_old.isin(EA.BANDS) & j.band_new.isin(EA.BANDS)].copy()
    ch = ch.sort_values(["disco", "state", "feeder_raw"]).reset_index(drop=True)
    counts = {"listed_old": int(a.feeder_id.nunique()), "listed_new": int(b.feeder_id.nunique()),
              "listed_both": int(j.feeder_id.nunique()), "changed": len(ch),
              "added": len(set(b.feeder_id) - set(a.feeder_id)),
              "dropped": len(set(a.feeder_id) - set(b.feeder_id))}
    return ch, counts


def link_nerc(changes: pd.DataFrame, nerc_rows: pd.DataFrame) -> pd.DataFrame:
    n = nerc_rows.copy()
    n["_k"] = n.disco.str.upper() + "|" + n.feeder_name.map(norm_name)
    if "row_key" not in n:
        n["row_key"] = [f"{f}#p{int(p)}#sn{s}" for f, p, s in zip(n.order_file, n.page, n.sn)]
    idx = n.groupby("_k").agg(row_keys=("row_key", list), nerc_band=("band", "first"),
                              nerc_month=("order_month", "first")).reset_index()
    ch = changes.copy()
    ch["_k"] = ch.disco.str.upper() + "|" + ch.feeder_raw.map(norm_name)
    ch = ch.merge(idx, on="_k", how="left").drop(columns="_k")
    ch["linked"] = ch.row_keys.notna()
    ch["row_keys"] = ch.row_keys.apply(lambda x: x if isinstance(x, list) else [])
    return ch


def unit_mixture(caps: pd.DataFrame, month: str, state: str, business_unit: str | None) -> dict:
    c = caps[(caps.order_month == month) & caps.band.isin(EA.BANDS)]
    c = c[c.state.map(state_key) == state_key(state)]
    if business_unit:
        c = c[c.business_unit.map(norm_name) == norm_name(business_unit)]
    vc = c.band.value_counts()
    counts = {b: int(vc.get(b, 0)) for b in EA.BANDS}
    n = sum(counts.values())
    return {"counts": counts, "n": n, "weights": {b: round(v / n, 4) for b, v in counts.items() if v} if n else {}}


def _parse_unit(unit: str) -> tuple[str, str | None]:
    m = re.match(r"business unit (.+) \((.+)\)$", unit or "")
    if m:
        return m.group(2), m.group(1)
    return re.sub(r"^state ", "", unit or ""), None


def affected_facilities(changes: pd.DataFrame, data: WardlightData, caps: pd.DataFrame, old: str,
                        new: str) -> tuple[pd.DataFrame, dict]:
    m = data.matches
    rows = []
    # (a) direct links through the NERC rows
    key_to_change = {}
    for _, c in changes[changes.linked].iterrows():
        for k in c.row_keys:
            key_to_change[k] = c
    if key_to_change:
        cand = m[m.tier.isin(["a_named", "b_place", "c_lga_mixture"])]
        for _, r in cand.iterrows():
            keys = _json(r.feeder_ids, []) or []
            hit = [k for k in keys if k in key_to_change]
            if not hit:
                continue
            stored = {k: float(v) for k, v in (_json(r.bands, {}) or {}).items()}
            w = 1.0 / len(keys)
            old_b, new_b, status = dict(stored), dict(stored), set()
            for k in hit:
                c = key_to_change[k]
                cur = c.nerc_band if isinstance(c.nerc_band, str) and c.nerc_band in EA.BANDS else c.band_old
                status.add("current" if cur == c.band_new else "stale" if cur == c.band_old else "differs")
                for target, b in ((c.band_old, old_b), (c.band_new, new_b)):
                    b[cur] = b.get(cur, 0.0) - w
                    b[target] = b.get(target, 0.0) + w
            clean = lambda b: {k: round(v, 4) for k, v in sorted(b.items()) if v > 1e-6}
            if clean(old_b) == clean(new_b):
                continue
            rows.append({"unique_id": r.unique_id, "tier": r.tier, "via": "nerc_row",
                         "feeders": [key_to_change[k].feeder_raw for k in hit],
                         "feeder_ids": sorted({key_to_change[k].feeder_id for k in hit}),
                         "bands_stored": stored, "bands_old": clean(old_b), "bands_new": clean(new_b),
                         "wardlight_status": status.pop() if len(status) == 1 else "mixed"})
    # (b) unit mixtures
    unit_note = None
    u = m[m.tier == "c_unit_mixture"]
    months = {old, new}
    cache: dict = {}
    if len(u):
        for _, r in u.iterrows():
            ev = _json(r.evidence, {}) or {}
            mm = ev.get("order_month")
            if mm not in months:
                unit_note = (f"unit mixtures use the {mm} orders, which are not one of the two months compared, so "
                             "this change does not alter them")
                continue
            state, bu = _parse_unit(ev.get("unit", ""))
            other = new if mm == old else old
            key = (state, bu)
            if key not in cache:
                cache[key] = (unit_mixture(caps, mm, state, bu), unit_mixture(caps, other, state, bu))
            same_m, other_m = cache[key]
            if ev.get("band_counts") and ev["band_counts"] != same_m["counts"]:
                unit_note = "a stored unit mixture differs from its recomputation; those facilities are skipped"
                continue
            stored = {k: float(v) for k, v in (_json(r.bands, {}) or {}).items()}
            o, nn = (stored, other_m["weights"]) if mm == old else (other_m["weights"], stored)
            if o == nn or not nn or not o:
                continue
            rows.append({"unique_id": r.unique_id, "tier": r.tier, "via": "unit_mixture",
                         "unit": ev.get("unit"), "feeders": [], "feeder_ids": [], "bands_stored": stored,
                         "bands_old": o, "bands_new": nn,
                         "wardlight_status": "current" if mm == new else "stale"})
    return pd.DataFrame(rows), {"unit_note": unit_note}


def rerun(aff: pd.DataFrame, data: WardlightData, n_draws: int = 16, max_keys: int | None = None,
          simulate=EA.coldchain, point=None) -> pd.DataFrame:
    """Cold-chain answer under the old and the new bands, once per (weather point, bands) key."""
    if aff.empty:
        return aff
    point = point or EA.weather_point
    f = data.facilities.set_index("unique_id")
    out = aff.merge(f[["facility_name", "state_standard", "lga_standard", "latitude", "longitude"]],
                    left_on="unique_id", right_index=True, how="left").dropna(subset=["latitude", "longitude"])
    out["point"] = [point(a, b) for a, b in zip(out.latitude, out.longitude)]
    keys: dict = {}
    for p, bo, bn in zip(out.point, out.bands_old, out.bands_new):
        for b in (bo, bn):
            keys.setdefault((p, EA.bands_key(b)), b)
    order = list(keys)
    if max_keys is not None:
        order = order[:max_keys]
    res = {k: simulate(k[0][0], k[0][1], keys[k], n_draws) for k in order}

    def get(p, b, field):
        r = res.get((p, EA.bands_key(b)))
        if r is None:
            return None
        v = r.get(field)
        return v.get("point") if isinstance(v, dict) else v

    for when in ("old", "new"):
        bcol = f"bands_{when}"
        out[f"fix_{when}"] = [get(p, b, "fix_category") for p, b in zip(out.point, out[bcol])]
        out[f"uptime_today_{when}"] = [get(p, b, "today_domestic") for p, b in zip(out.point, out[bcol])]
        out[f"uptime_today_pqs_{when}"] = [get(p, b, "today_pqs_ice_lined") for p, b in zip(out.point, out[bcol])]
    out["rerun"] = out.fix_old.notna() & out.fix_new.notna()
    return out


MAX_FEEDER_LINES = 60


def summarise(ch: pd.DataFrame, rr: pd.DataFrame) -> dict:
    """Every count the report text states, stored so the text can be checked against it."""
    out = {"linked": int(ch.linked.sum()), "affected": len(rr), "rerun": 0, "status_counts": {},
           "fix_moves": [], "facilities_per_feeder": {},
           "feeders_not_listed": max(0, len(ch) - MAX_FEEDER_LINES)}
    if len(rr):
        done = rr[rr.rerun]
        out["rerun"] = len(done)
        out["status_counts"] = {str(k): int(v) for k, v in rr.wardlight_status.value_counts().items()}
        moved = done[done.fix_old != done.fix_new]
        out["fix_moves"] = [{"from": a, "to": b, "count": len(g)}
                            for (a, b), g in moved.groupby(["fix_old", "fix_new"])]
        per = rr.explode("feeder_ids").dropna(subset=["feeder_ids"])
        out["facilities_per_feeder"] = {str(k): int(v) for k, v in per.groupby("feeder_ids").unique_id.nunique().items()}
    return out


def _md(old: str, new: str, counts: dict, ch: pd.DataFrame, sm: dict, note: str | None) -> str:
    lines = [f"# Band changes: NERC cap orders {old} to {new}", "",
             f"{counts['changed']} feeders listed in both months changed band ({counts['listed_both']} listed in "
             f"both; {counts['added']} added, {counts['dropped']} dropped). Source: naija-grid caps_long.csv, "
             "credit NERC.", "", f"{sm['linked']} of them link by name to a NERC row Wardlight reads."]
    if sm["affected"]:
        lines.append(f"{sm['affected']} facilities are affected; {sm['rerun']} were re-run.")
        st = sm["status_counts"]
        if st.get("current"):
            lines.append(f"- For {st['current']} of them Wardlight's data already shows the {new} bands (the "
                         "NERC row it reads carries the new band): the figures below say what the change did.")
        if st.get("stale"):
            lines.append(f"- For {st['stale']} of them Wardlight's data still shows the {old} bands: re-run "
                         "the batch to bring them up to date.")
        for mv in sm["fix_moves"]:
            lines.append(f"- {mv['count']} now need {FIX_SHORT.get(mv['to'], mv['to'])} (before: "
                         f"{FIX_SHORT.get(mv['from'], mv['from'])}).")
        if not sm["fix_moves"]:
            lines.append("- No affected facility's recommended fix changed.")
    else:
        lines.append("No Wardlight facility is matched to these feeders.")
    if note:
        lines += ["", f"Note: {note}."]
    lines += ["", "## Feeders", ""]
    for _, c in ch.head(MAX_FEEDER_LINES).iterrows():
        k = sm["facilities_per_feeder"].get(c.feeder_id, 0)
        lines.append(f"- {c.feeder_raw} ({c.disco}, {c.state}): Band {c.band_old} to Band {c.band_new}"
                     + (f"; {k} facilities matched" if k else "; no Wardlight facility matched to it" if c.linked
                        else "; not among the NERC rows Wardlight reads"))
    if sm["feeders_not_listed"]:
        lines.append(f"- and {sm['feeders_not_listed']} more in the JSON report")
    lines += ["", "Bands are NERC's promised minimum hours; supply is modelled, not measured."]
    return "\n".join(lines)


def run_events(old: str, new: str, data: WardlightData | None = None, caps: pd.DataFrame | None = None,
               n_draws: int = 16, max_keys: int | None = None, out_dir: Path | None = None,
               simulate=EA.coldchain, point=None, result: dict | None = None) -> Iterator[dict]:
    data = data or WardlightData()
    log = EV.EventLog()
    yield log.emit("plan", steps=[{"id": "diff", "title": f"Diff feeder bands, {old} to {new}"},
                                  {"id": "link", "title": "Link changed feeders to the NERC rows"},
                                  {"id": "affected", "title": "Find the facilities matched to them"},
                                  {"id": "rerun", "title": "Re-run those facilities"},
                                  {"id": "report", "title": "Write the band-change report"}])

    def call(cid, name, args):
        return log.emit("tool_call", id=cid, name=name, args=args), log.ms()

    yield log.emit("step_start", id="diff")
    ev, t = call("w1", "diff_months", {"old": old, "new": new, "source": "naija-grid caps_long.csv"})
    yield ev
    try:
        caps = caps if caps is not None else load_caps()
        ch, counts = diff_months(caps, old, new)
    except (ValueError, FileNotFoundError) as e:
        yield log.emit("tool_result", id="w1", summary=f"error: {e}", rows=0, ms=log.ms() - t, ok=False)
        yield log.emit("error", message=str(e))
        yield log.emit("done", model="none (code only)", tokens=0, cost_usd=0.0, recorded=False,
                       duration_ms=log.ms())
        return
    yield log.emit("tool_result", id="w1", summary=f"{counts['changed']} feeders changed band", rows=counts["changed"],
                   ms=log.ms() - t, counts=counts)
    yield log.emit("step_start", id="link")
    ev, t = call("w2", "link_nerc_rows", {"by": "DisCo and normalised feeder name, exact"})
    yield ev
    ch = link_nerc(ch, data.nerc_rows)
    agree = ch[ch.linked]
    n_agree = int((agree.nerc_band == agree.band_old).sum())
    yield log.emit("tool_result", id="w2", summary=f"{int(ch.linked.sum())} of {len(ch)} linked to NERC rows",
                   rows=int(ch.linked.sum()), ms=log.ms() - t, september_band_agrees=n_agree)
    yield log.emit("step_start", id="affected")
    ev, t = call("w3", "affected_facilities", {"tiers": ["a_named", "b_place", "c_lga_mixture", "c_unit_mixture"]})
    yield ev
    aff, meta = affected_facilities(ch, data, caps, old, new)
    yield log.emit("tool_result", id="w3", summary=f"{len(aff)} facilities affected", rows=len(aff),
                   ms=log.ms() - t)
    yield log.emit("step_start", id="rerun")
    ev, t = call("w4", "rerun_facilities", {"n_draws": n_draws, "max_keys": max_keys})
    yield ev
    rr = rerun(aff, data, n_draws, max_keys, simulate, point)
    n_rr = int(rr.rerun.sum()) if len(rr) else 0
    yield log.emit("tool_result", id="w4", summary=f"{n_rr} facilities re-run", rows=n_rr, ms=log.ms() - t)
    yield log.emit("step_start", id="report")
    sm = summarise(ch, rr)
    md = _md(old, new, counts, ch, sm, meta.get("unit_note"))
    changes = [{"feeder_id": c.feeder_id, "feeder_name": c.feeder_raw, "disco": c.disco, "state": c.state,
                "business_unit": c.business_unit if isinstance(c.business_unit, str) else None,
                "band_old": c.band_old, "band_new": c.band_new, "source_old": f"{c.source_file_old} p{c.source_page_old}",
                "source_new": f"{c.source_file_new} p{c.source_page_new}", "linked": bool(c.linked),
                "nerc_rows": list(c.row_keys), "nerc_band_september": c.nerc_band if isinstance(c.nerc_band, str)
                else None, "facilities_matched": sm["facilities_per_feeder"].get(c.feeder_id, 0)}
               for _, c in ch.iterrows()]
    facilities = []
    if len(rr):
        for _, r in rr.iterrows():
            facilities.append({"unique_id": r.unique_id, "name": r.facility_name, "state": r.state_standard,
                               "lga": r.lga_standard, "tier": r.tier, "via": r.via, "feeders": r.feeders,
                               "bands_old": r.bands_old, "bands_new": r.bands_new, "bands_stored": r.bands_stored,
                               "wardlight_status": r.wardlight_status, "fix_old": r.fix_old,
                               "fix_new": r.fix_new, "uptime_today_old": r.uptime_today_old,
                               "uptime_today_new": r.uptime_today_new, "uptime_today_pqs_old": r.uptime_today_pqs_old,
                               "uptime_today_pqs_new": r.uptime_today_pqs_new, "rerun": bool(r.rerun)})
    totals = {"old": old, "new": new, **counts, "linked": int(ch.linked.sum()), "september_band_agrees": n_agree,
              "facilities_affected": len(facilities), "facilities_rerun": n_rr,
              "fix_changed": sum(1 for f in facilities if f["rerun"] and f["fix_old"] != f["fix_new"])}
    report = {"label": "real changes from NERC's published orders (naija-grid caps_long.csv)", "totals": totals,
              "summary": sm, "unit_note": meta.get("unit_note"), "changes": changes, "facilities": facilities,
              "markdown": md}
    # the counts the text states are checked against the stored summary and records only
    rep = G.check(md, [totals, sm, [{k: v for k, v in c.items() if k != "nerc_rows"} for c in changes],
                       {"note": meta.get("unit_note"), "fixes": FIX_SHORT}], require_citation=False)
    yield log.emit("check", kind="grounding", numbers_checked=rep.n_total,
                   unmatched=[c.text for c in rep.unmatched] + rep.unknown_tokens,
                   matches=[{"text": c.text, "value": c.value, "matched": c.matched} for c in rep.claims], ok=rep.ok)
    if not rep.ok:
        yield log.emit("error", message="report text failed the grounding check; JSON records only")
        report["markdown"] = None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"band_changes_{old}_to_{new}"
        (out_dir / f"{stem}.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
        if report["markdown"]:
            (out_dir / f"{stem}.md").write_text(report["markdown"] + "\n")
    yield log.emit("answer", markdown=report["markdown"] or "", funded=[], not_reached=[], totals=totals,
                   changes=changes[:200], facilities=facilities[:200])
    yield log.emit("done", model="none (code only)", tokens=0, cost_usd=0.0, recorded=False, duration_ms=log.ms())
    if result is not None:
        result.update({"report": report, "events": log.events})


def run(old: str, new: str, **kw) -> dict:
    rec: dict = {}
    for _ in run_events(old, new, result=rec, **kw):
        pass
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="2026-09")
    ap.add_argument("--new", default="2026-10")
    ap.add_argument("--out", default=str(OUT_DIR / "watcher"))
    ap.add_argument("--max-keys", type=int)
    ap.add_argument("--draws", type=int, default=16)
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    rec = run(a.old, a.new, n_draws=a.draws, max_keys=a.max_keys, out_dir=Path(a.out))
    print(json.dumps(rec["report"]["totals"], indent=1), f"\n{time.perf_counter() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
