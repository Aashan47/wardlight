"""Draw the T2 spot-check sample: 100 tier (a) and (b) matches, seed 20261031 (docs/PREREG.md).

The sample is written unchecked. The 'correct' column is for a human, who fills it by comparing the
facility's fields with the quoted NERC row; nothing here marks a row as checked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SEED = 20261031
N = 100

COLUMNS = [
    "sample_no", "unique_id", "source_version", "facility_name", "state_standard", "lga_standard", "ward_standard",
    "settlement_name", "tier", "matched_on", "facility_value", "nerc_text", "nerc_field", "score",
    "order_file", "page", "sn", "row_text", "band", "min_hours", "other_rows", "correct", "checked_by", "note",
]


def draw(matches: pd.DataFrame, facilities: pd.DataFrame, out: Path, n: int = N, seed: int = SEED) -> pd.DataFrame:
    ab = matches[matches["tier"].isin(["a_named", "b_place"])].sort_values("unique_id").reset_index(drop=True)
    k = min(n, len(ab))
    s = ab.sample(n=k, random_state=seed).reset_index(drop=True)
    fac = facilities.drop_duplicates("unique_id").set_index("unique_id")
    recs = []
    for i, r in s.iterrows():
        ev = json.loads(r["evidence"])
        fr = fac.loc[r["unique_id"]]
        recs.append({
            "sample_no": i + 1, "unique_id": r["unique_id"],
            "source_version": fr.get("source_version", "grid3_v3.0"),
            "facility_name": fr["facility_name"],
            "state_standard": fr["state_standard"], "lga_standard": fr["lga_standard"],
            "ward_standard": fr["ward_standard"], "settlement_name": str(fr["settlement_name"]).strip(),
            "tier": r["tier"], "matched_on": ev.get("matched_on"), "facility_value": ev.get("facility_value"),
            "nerc_text": ev.get("nerc_text"), "nerc_field": ev.get("nerc_field"), "score": ev.get("score"),
            "order_file": ev.get("order_file"), "page": ev.get("page"), "sn": ev.get("sn"),
            "row_text": ev.get("row_text"), "band": ev.get("band"), "min_hours": ev.get("min_hours"),
            "other_rows": len(ev.get("more", [])), "correct": "", "checked_by": "", "note": "",
        })
    df = pd.DataFrame(recs, columns=COLUMNS)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return df
