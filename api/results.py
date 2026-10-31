"""The pre-registered targets (docs/PREREG.md) with results from what exists in data/work/ and docs/, or the engine.

Status is 'hit' or 'miss' only when a result file or an engine run gives the number; otherwise 'not_run' with what
is missing. T7 has no target in PREREG, so its status is 'reported'. Nothing here is typed in by hand: each
result string is formatted from a file or an engine call named in its `source`.
"""

from __future__ import annotations

import json
import re

import pandas as pd

from .config import Settings

TABLE_RE = re.compile(r"^\|\s*(T\d+)\s*\|(.+?)\|(.+?)\|(.+?)\|\s*$")


def prereg_rows(s: Settings) -> list[dict]:
    p = s.docs / "PREREG.md"
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            m = TABLE_RE.match(line)
            if m:
                out.append({"id": m.group(1), "what": m.group(2).strip(), "target": m.group(3).strip(),
                            "how": m.group(4).strip()})
    except OSError:
        pass
    return out


def _read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _checked_share(path, cols: list[str]) -> tuple[int, int, int] | None:
    """(rows, rows checked, rows correct) for a by-eye sample CSV; None when absent."""
    if not path.exists():
        return None
    d = pd.read_csv(path, dtype=str).fillna("")
    if not all(c in d for c in cols):
        return None
    filled = d[cols].apply(lambda c: c.str.strip() != "").all(axis=1)
    ok = d[cols].apply(lambda c: c.str.strip().str.lower().isin(["1", "true", "yes", "y"])).all(axis=1)
    return len(d), int(filled.sum()), int((ok & filled).sum())


def _t1(s: Settings) -> dict:
    r = _checked_share(s.docs / "T1_SAMPLE.csv", ["band_ok", "feeder_name_ok", "location_ok", "streets_ok",
                                                   "min_hours_ok"])
    return _sample_result(r, 0.97, "docs/T1_SAMPLE.csv")


def _t2(s: Settings) -> dict:
    r = _checked_share(s.docs / "T2_SAMPLE.csv", ["correct"])
    return _sample_result(r, 0.90, "docs/T2_SAMPLE.csv")


def _sample_result(r, target: float, src: str) -> dict:
    if r is None:
        return {"result": None, "status": "not_run", "source": f"{src} not found"}
    n, checked, ok = r
    if checked < n:
        return {"result": f"sample of {n} drawn; {checked} of {n} rows checked by eye so far", "status": "not_run",
                "source": src}
    share = ok / n if n else 0.0
    return {"result": f"{ok} of {n} correct ({share:.1%})", "status": "hit" if share >= target else "miss",
            "source": src}


def _t3(s: Settings, store) -> dict:
    from engine import supply as SP

    sf, rows = s.work / "nerc_shortfalls.parquet", s.work / "nerc_rows.parquet"
    if not sf.exists():
        return {"result": None, "status": "not_run", "source": "nerc_shortfalls.parquet missing"}
    sh = pd.read_parquet(sf)
    n_a = int((pd.read_parquet(rows).band == "A").sum()) if rows.exists() else None
    first = SP.backtest_t3(sh, n_a)
    widened = SP.widen_until_pass(sh, n_a)
    uncond = SP.backtest_t3(sh, n_a, conditional=False)
    res = (f"{first['inside']} of {first['n']} measured failing Band A feeders inside the held-out 90% interval "
           f"({first['share']:.1%}); under the PREREG failure rule the interval was widened x{widened['factor']:g}, "
           f"after which {widened['share']:.1%} fall inside. Second arm (unconditional interval): "
           f"{uncond['inside']} of {uncond['n']} ({uncond['share']:.1%})")
    return {"result": res, "status": "hit" if first["pass"] else "miss",
            "source": "engine.supply.backtest_t3 and widen_until_pass on data/work/nerc_shortfalls.parquet"}


def _t4(s: Settings) -> dict:
    d = _read_json(s.work / "t4_summary.json")
    if not d:
        return {"result": None, "status": "not_run", "source": "data/work/t4_summary.json missing"}
    res = (f"{d['within']} of {d['n']} sites within {d['tol']:.0%}; median difference {d['median_rel_diff']:.1%}, "
           f"largest {d['max_abs_rel_diff']:.1%}")
    return {"result": res, "status": "hit" if d.get("pass_all_within") else "miss",
            "source": "data/work/t4_summary.json"}


def _t5(s: Settings) -> dict:
    d = _read_json(s.work / "t5_results.json")
    if not d:
        return {"result": None, "status": "not_run", "source": "data/work/t5_results.json missing"}
    grid = [x for x in d if x.get("bands") != "OFFGRID"]
    off = [x for x in d if x.get("bands") == "OFFGRID"]
    gi = sum(1 for x in grid if x.get("inside_seforall"))
    oi = sum(1 for x in off if x.get("inside_seforall"))
    kwp = [x["kwp"] for x in off]
    res = (f"grid-connected sites: {gi} of {len(grid)} inside SEforALL's 5 to 10 kWp, 36 to 72 kWh; off-grid sites: "
           f"{oi} of {len(off)} inside" + (f" (they size at {min(kwp):g} to {max(kwp):g} kWp)" if kwp else "")
           + "; explained by the target: 99% of days at the 5th percentile against SEforALL's one day of autonomy")
    return {"result": res, "status": "hit" if grid and gi == len(grid) else "miss",
            "source": "data/work/t5_results.json; explanation in docs/sources/engine.md"}


def _t6(s: Settings) -> dict:
    d = _read_json(s.work / "t6_local_contended.json")
    base = "PREREG names the deployed server, not yet measured there"
    if not d:
        return {"result": base, "status": "not_run", "source": "no T6 file in data/work"}
    res = (f"{base}. Build laptop under heavy load ({d.get('machine')}): p50 {d['p50_s']:.2f} s, p95 "
           f"{d['p95_s']:.2f} s over {d['n']} facilities (engine only); the API's own measurement is in "
           "docs/sources/api.md")
    return {"result": res, "status": "not_run", "source": "data/work/t6_local_contended.json"}


def _t7(store) -> dict:
    if store is None:
        return {"result": None, "status": "not_run", "source": "no data"}
    t = store.t
    n = int(t.has_result.sum())
    return {"result": f"fridge uptime and doses reported for {n:,} of {len(t):,} facilities, every input sourced in "
                      "docs/sources/engine.md; no measured uptime exists to compare against",
            "status": "reported", "source": "data/work/facility_results.parquet"}


def _agents(s: Settings, tid: str) -> dict:
    # docs/agent_results.json carries the live T8/T9 result (docs/RESULTS.md); files in data/work, if any, come first
    cands = [(s.work / n, f"data/work/{n}") for n in (f"{tid.lower()}_results.json", f"{tid.lower()}.json",
                                                       "agent_eval.json")]
    cands.append((s.docs / "agent_results.json", "docs/agent_results.json and docs/RESULTS.md"))
    for path, label in cands:
        d = _read_json(path)
        if d and isinstance(d, dict) and (tid in d or tid.lower() in d):
            v = d.get(tid) or d.get(tid.lower())
            if isinstance(v, dict) and "result" in v and "status" in v:
                return {"result": v["result"], "status": v["status"], "source": label}
    return {"result": None, "status": "not_run", "source": "no agent evaluation file in data/work yet"}


def build(s: Settings, store) -> dict:
    fns = {"T1": lambda: _t1(s), "T2": lambda: _t2(s), "T3": lambda: _t3(s, store), "T4": lambda: _t4(s),
           "T5": lambda: _t5(s), "T6": lambda: _t6(s), "T7": lambda: _t7(store), "T8": lambda: _agents(s, "T8"),
           "T9": lambda: _agents(s, "T9")}
    rows = []
    for p in prereg_rows(s):
        fn = fns.get(p["id"])
        try:
            r = fn() if fn else {"result": None, "status": "not_run", "source": "no evaluator"}
        except Exception as e:  # noqa: BLE001 - a failing evaluator is reported, never hidden
            r = {"result": f"evaluation failed: {type(e).__name__}: {e}", "status": "not_run", "source": "error"}
        rows.append({**p, **r})
    rows.sort(key=lambda x: int(x["id"][1:]))
    return {"sample": False, "prereg_url": "docs/PREREG.md", "rows": rows,
            "note": "status 'reported' marks T7, which PREREG gives no target"}
