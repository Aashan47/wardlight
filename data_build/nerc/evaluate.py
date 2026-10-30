"""Field accuracy of the reader against the hand-transcribed fixtures in tests/nerc/.

    .venv/bin/python -m data_build.nerc.evaluate
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "nerc"
WORK = ROOT / "data" / "work"
TEXT_FIELDS = ("feeder_name", "location", "streets")


def norm(s) -> str:
    s = "" if s is None or (isinstance(s, float) and pd.isna(s)) else str(s)
    s = s.upper()
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*([,.;:()/&-])\s*", r"\1", s)  # spacing around punctuation is not a reading error
    return s


def load_fixtures() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(FIXTURES.glob("fixture_*.json"))]


def compare(fx: dict, rows: pd.DataFrame, max_edits: int = 2) -> dict:
    """Per-field results for one fixture page against nerc_rows."""
    got = rows[(rows.order_file == fx["order_file"]) & (rows.page == fx["page"])]
    by_sn = {int(r.sn): r for r in got.itertuples() if pd.notna(r.sn)}
    res = {"page": f"{fx['disco']} p{fx['page']}", "expected_rows": len(fx["rows"]), "read_rows": len(got),
           "fields": {}, "misses": []}
    fields = ("sn", "band", "min_hours") + TEXT_FIELDS
    tallies = {f: [0, 0, 0] for f in fields}  # exact, within edits, total
    for exp in fx["rows"]:
        r = by_sn.get(exp["sn"])
        for f in fields:
            tallies[f][2] += 1
            if r is None:
                if f == "sn":
                    res["misses"].append((exp["sn"], f, exp[f], None))
                continue
            val = getattr(r, f)
            if f == "sn":
                ok = exact = True
            elif f == "band":
                ok = exact = val == exp["band"]
            elif f == "min_hours":
                ok = exact = pd.notna(val) and float(val) == float(exp["min_hours"])
            else:
                a, b = norm(val), norm(exp[f])
                exact = a == b
                ok = Levenshtein.distance(a, b) <= max_edits
            tallies[f][0] += int(exact)
            tallies[f][1] += int(ok)
            if not exact:
                res["misses"].append((exp["sn"], f, exp[f], None if val is None else str(val)))
    for f, (ex, ok, tot) in tallies.items():
        res["fields"][f] = {"exact": ex, "within_edits": ok, "total": tot}
    return res


def compare_shortfalls(fx: dict, shorts: pd.DataFrame) -> dict | None:
    if "shortfalls" not in fx:
        return None
    got = shorts[(shorts.order_file == fx["order_file"]) & (shorts.page == fx["page"])].reset_index(drop=True)
    out = {"expected": len(fx["shortfalls"]), "read": len(got), "checks": []}
    for i, exp in enumerate(fx["shortfalls"]):
        if i >= len(got):
            out["checks"].append((i, "missing"))
            continue
        g = got.iloc[i]
        mh_ok = (pd.isna(g.measured_avg_hours) and exp["measured_avg_hours"] is None) or (
            pd.notna(g.measured_avg_hours) and exp["measured_avg_hours"] is not None
            and float(g.measured_avg_hours) == exp["measured_avg_hours"])
        out["checks"].append({
            "feeder_name": norm(g.feeder_name) == norm(exp["feeder_name"]),
            "measured_avg_hours": bool(mh_ok), "action": g.action == exp["action"],
            "period": g.period == exp["period"]})
    return out


def main() -> None:
    rows = pd.read_parquet(WORK / "nerc_rows.parquet")
    shorts = pd.read_parquet(WORK / "nerc_shortfalls.parquet")
    total = {}
    for fx in load_fixtures():
        res = compare(fx, rows)
        print(res["page"], "rows", res["read_rows"], "/", res["expected_rows"])
        for f, t in res["fields"].items():
            print(f"  {f:12s} exact {t['exact']}/{t['total']}  within 2 edits {t['within_edits']}/{t['total']}")
            agg = total.setdefault(f, [0, 0, 0])
            agg[0] += t["exact"]
            agg[1] += t["within_edits"]
            agg[2] += t["total"]
        for m in res["misses"]:
            print("   miss", m)
        sf = compare_shortfalls(fx, shorts)
        if sf:
            print("  shortfalls", sf)
    print("ALL")
    for f, (ex, ok, tot) in total.items():
        print(f"  {f:12s} exact {ex}/{tot} ({ex / tot:.1%})  within 2 edits {ok}/{tot} ({ok / tot:.1%})")


if __name__ == "__main__":
    main()
