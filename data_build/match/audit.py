"""Tier (a) recall audit: every NERC row whose text mentions HOSPITAL, MEDICAL, FMC, CLINIC or HEALTH, with
each facility mention read from it, the best GRID3 candidate in the DisCo's states, and why it did or did
not match. Writes the table into docs/sources/match.md between the tier-a-audit markers.

    .venv/bin/python -m data_build.match.audit
"""

from __future__ import annotations

import re

import pandas as pd

from . import paths
from .matcher import _candidates, evaluate_mention, mentions, prepare_facilities, prepare_rows
from .text import is_road, segments

KEYWORDS = re.compile(r"HOSPITAL|MEDICAL|FMC|CLINIC|HEALTH")
DOC = paths.REPO / "docs" / "sources" / "match.md"
START, END = "<!-- tier-a-audit:start -->", "<!-- tier-a-audit:end -->"


def _cell(s: object) -> str:
    return str(s).replace("|", "/").replace("\n", " ").strip()


def _why_no_mention(r) -> str:
    items = [seg for fld in ("feeder_name", "location", "streets") for seg in segments(r[fld])
             if KEYWORDS.search(seg) or "FEDERAL MEDICAL" in seg]
    if items and all(is_road(x) for x in items):
        return "keyword only in a road name (" + ", ".join(items[:2]) + ")"
    return "keyword only in an office, school, quarters or university item (" + ", ".join(items[:2]) + ")"


def audit(facilities: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    idx = prepare_facilities(facilities)
    rows = prepare_rows(rows)
    f = idx.fac
    raw = (rows["feeder_name"].fillna("") + " | " + rows["location"].fillna("") + " | "
           + rows["streets"].fillna("")).str.upper()
    recs = []
    for ri in rows.index[raw.str.contains(KEYWORDS)]:
        r = rows.loc[ri]
        ref = f"{r['disco_code']} p{int(r['page'])} S/N {r['sn'] if pd.notna(r['sn']) else '?'}"
        ms = mentions(r)
        cand_idx, names = _candidates(r, idx)
        in_grid3 = ", ".join(s.title() for s in r["states"] if s in idx.by_state) or "none"
        if not ms:
            recs.append({"row": ref, "grid3_states": in_grid3, "mention": "", "best": "", "score": "",
                         "result": "no facility mention: " + _why_no_mention(r)})
            continue
        for m in ms:
            res = evaluate_mention(m, r, idx, cand_idx, names) if len(cand_idx) else {
                "accepted": [], "best": None, "outcome": "no GRID3 facilities in the DisCo's states"}
            mention = m.text + (f" (borrowed from {m.context})" if m.context else "")
            if res["accepted"]:
                best = "; ".join(f"{f.loc[fi, 'facility_name']} ({f.loc[fi, 'state_standard']})"
                                 for fi, _ in res["accepted"])
                score = max(sc for _, sc in res["accepted"])
                result = "**matched**"
            elif res["best"]:
                fi, score, _ = res["best"]
                best = f"{f.loc[fi, 'facility_name']} ({f.loc[fi, 'state_standard']})"
                result = res["outcome"]
            else:
                best, score, result = "", "", res["outcome"]
            recs.append({"row": ref, "grid3_states": in_grid3, "mention": mention, "best": best,
                         "score": score if score == "" else round(float(score)), "result": result})
    return pd.DataFrame(recs)


def to_markdown(a: pd.DataFrame) -> str:
    lines = ["| Row | DisCo states in GRID3 | Mention as compared | Best GRID3 candidate | Score | Result |",
             "|---|---|---|---|---:|---|"]
    for _, x in a.iterrows():
        lines.append("| " + " | ".join(_cell(x[c]) for c in
                                         ("row", "grid3_states", "mention", "best", "score", "result")) + " |")
    return "\n".join(lines)


def write_doc(a: pd.DataFrame, summary: str) -> None:
    doc = DOC.read_text()
    block = f"{START}\n{summary}\n\n{to_markdown(a)}\n{END}"
    if START in doc:
        doc = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _m: block, doc, flags=re.DOTALL)
    else:
        doc = doc.rstrip() + "\n\n" + block + "\n"
    DOC.write_text(doc)


def main() -> int:
    fac = pd.read_parquet(paths.FACILITIES)
    rows = pd.read_parquet(paths.NERC_ROWS)
    a = audit(fac, rows)
    n_rows = a["row"].nunique()
    n_matched_rows = a.loc[a["result"].eq("**matched**"), "row"].nunique()
    summary = (f"{n_rows} rows mention a keyword; {len(a)} audit lines (one per mention, or one per row "
               f"without a mention); {n_matched_rows} rows give at least one tier (a) match.")
    write_doc(a, summary)
    a.to_csv(paths.WORK / "tier_a_audit.csv", index=False)
    print(summary)
    print(a["result"].str.replace(r"\(.*", "", regex=True).value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
