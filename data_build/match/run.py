"""Run the whole matcher.

    .venv/bin/python -m data_build.match.run            # full run on data/work/nerc_rows.parquet, draws T2
    .venv/bin/python -m data_build.match.run --fixture  # dev run on the hand-transcribed BEDC page 12 rows

The T2 sample is drawn into docs/T2_SAMPLE.csv only on a full run. A fixture run writes
data/work/matches_fixture.parquet and data/work/T2_SAMPLE_fixture.csv so nothing in docs/ is ever drawn
from partial rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

from . import facilities as fac_mod
from . import grid as grid_mod
from . import paths, sample
from .matcher import TIERS, match


def _load_rows(path, fixture: bool) -> pd.DataFrame:
    if fixture:
        return pd.read_csv(paths.FIXTURE_ROWS, dtype={"sn": str})
    if not path.exists():
        sys.exit(f"{path} not found (agent A builds it). Use --fixture for a dev run.")
    return pd.read_parquet(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", action="store_true", help="use the hand-transcribed fixture rows")
    ap.add_argument("--rows", default=str(paths.NERC_ROWS))
    ap.add_argument("--rebuild", action="store_true", help="rebuild facilities and grid distances")
    a = ap.parse_args(argv)

    if a.rebuild or not paths.FACILITIES.exists():
        fac_mod.build()
    if a.rebuild or not paths.FACILITY_GRID.exists():
        grid_mod.build()
    fac = pd.read_parquet(paths.FACILITIES)
    grd = pd.read_parquet(paths.FACILITY_GRID)
    rows = _load_rows(Path(a.rows), a.fixture)

    m, diag = match(fac, rows, grd)
    out = paths.WORK / "matches_fixture.parquet" if a.fixture else paths.MATCHES
    m.to_parquet(out, index=False)
    t2 = paths.WORK / "T2_SAMPLE_fixture.csv" if a.fixture else paths.T2_SAMPLE
    s = sample.draw(m, fac, t2)

    counts = m["tier"].value_counts().reindex(TIERS, fill_value=0)
    report = {
        "rows": diag["rows"], "rows_without_disco": diag["rows_without_disco"],
        "facilities": len(m), "tiers": counts.to_dict(),
        "refusal_reasons": m.loc[m["tier"].eq("d_refused"), "reason"].str.split(":").str[0].value_counts().to_dict(),
        "b_levels": m.loc[m["tier"].eq("b_place"), "evidence"].map(lambda e: json.loads(e)["matched_on"])
        .value_counts().to_dict(),
        "ambiguous_tier_a_mentions": len(diag["ambiguous_tier_a"]),
        "cross_state_b_names_dropped": len(diag["dropped_cross_state_b"]),
        "t2_sample": {"path": str(t2), "n": len(s)},
        "matches": str(out),
    }
    (paths.WORK / ("match_report_fixture.json" if a.fixture else "match_report.json")).write_text(
        json.dumps({**report, "diagnostics": diag}, indent=1, default=str))
    print(json.dumps(report, indent=1))
    if not a.fixture:
        _write_doc_block(m, s, Path(a.rows))
    return 0


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _write_doc_block(m: pd.DataFrame, s: pd.DataFrame, rows_path: Path) -> None:
    """Fill the current-run block of docs/sources/match.md from this run (no calendar dates)."""
    doc_path = paths.REPO / "docs" / "sources" / "match.md"
    doc = doc_path.read_text()
    start, end = "<!-- current-run:start -->", "<!-- current-run:end -->"
    if start not in doc:
        return
    n = len(m)
    ev = m["evidence"].map(json.loads)
    lines = [
        start,
        (f"**Current run** (after amendment 3), on `{rows_path.name}` SHA-256 `{_sha(rows_path)}`; "
        f"`matches.parquet` SHA-256 `{_sha(paths.MATCHES)}`."),
        "",
        "| Tier | Facilities | Share |",
        "|---|---:|---:|",
    ]
    for t in TIERS:
        k = int((m["tier"] == t).sum())
        lines.append(f"| {t} | {k:,} | {100 * k / n:.1f}% |")
    lines.append(f"| total | {n:,} | |")
    b = ev[m["tier"].eq("b_place")].map(lambda e: e["matched_on"]).value_counts().to_dict()
    unit = ev[m["tier"].eq("c_unit_mixture")].map(lambda e: e["unit"].startswith("business unit")).sum()
    ab = m["tier"].isin(["a_named", "b_place"])
    lines += [
        "",
        f"Tier (b) by level: {', '.join(f'{k} {v:,}' for k, v in b.items())}. "
        f"`c_unit_mixture` by business unit: {unit:,}. Refusal reasons: "
        + ", ".join(f"{k} {v:,}" for k, v in
                    m.loc[m["tier"].eq("d_refused"), "reason"].str.split(":").str[0].value_counts().items())
        + f". Tier (a) or (b) in states that have left NERC: "
        f"{int(m.loc[ab, 'reason'].str.contains('has left NERC').sum()):,}; more than 5 km from a line: "
        f"{int(m.loc[ab, 'reason'].str.contains('check the match').sum()):,}.",
        "",
        (f"**T2 sample:** `docs/T2_SAMPLE.csv`, {len(s)} rows drawn with "
        "`pandas.DataFrame.sample(random_state=20261031)` from the tier (a) and (b) matches sorted by "
        f"`unique_id` ({', '.join(f'{k} {v}' for k, v in s['tier'].value_counts().items())}; by level "
        f"{', '.join(f'{k} {v}' for k, v in s['matched_on'].value_counts().items())}); SHA-256 "
        f"`{_sha(paths.T2_SAMPLE)}`. **Unchecked**: `correct`, `checked_by` and `note` are empty for a human to "
        "fill by comparing the facility's fields with `row_text` and the page image. Tier (a) matches are few; "
        "check all of them as well, outside T2."),
        end,
    ]
    doc = doc[: doc.index(start)] + "\n".join(lines) + doc[doc.index(end) + len(end):]
    doc_path.write_text(doc)


if __name__ == "__main__":
    raise SystemExit(main())
