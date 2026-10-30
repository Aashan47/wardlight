"""Record fixture sessions for the UI into data/fixtures/agents/ (all marked recorded; planner ones scripted).

    python -m agents.record [--skip-watcher] [--watcher-draws N]

Planner sessions use the rule-based scripted model (no language model is called) over the real tools and data.
The verifier session uses typed sandbox replies. The watcher run is a real diff of NERC's published orders.
Every file stores the full event list with its original seq and t_ms, so a replay is faithful.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import events as EV
from . import fake, planner, verifier, watcher
from .evaluate import load_questions
from .tools import Toolbox

OUT = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "agents"
SCRIPTED = ("Recorded session. Scripted test model: rule-based, no language model was called. Tool results are "
            "real (Wardlight data version {v}).")
PLANNER_SESSIONS = [
    ("planner_kano_doses", "Q01", False, "A budget plan for Kano, vaccine doses first."),
    ("planner_grounding_block", "Q06", True,
     "The grounding check in action: the first draft carries an invented figure, the check blocks it, the retry "
     "passes."),
    ("planner_refusal_medical", "Q17", False, "A medical-advice question, refused by the rule pre-filter."),
]
VERIFIER_REPLIES = ["we have the household one", "about nine hours", "1"]


def record_planner(tb: Toolbox) -> list[Path]:
    qs = {q["id"]: q for q in load_questions()}
    paths = []
    for name, qid, fab, what in PLANNER_SESSIONS:
        rec = planner.run(qs[qid]["question"], fake.RuleBasedPlannerModel(fabricate_first=fab), tb)
        p = OUT / f"{name}.json"
        EV.save_recording(p, "planner_session", rec["events"], SCRIPTED.format(v=tb.data.version),
                          scripted=True, question_id=qid, what=what, output=rec["output"],
                          transcript=rec["transcript"])
        paths.append(p)
    return paths


def pick_verifier_facility(tb: Toolbox) -> str:
    """A matched facility with a multi-band mixture (so the hours reply has something to narrow), first by id."""
    t = tb.data.table
    c = t[(t.match_tier == "c_lga_mixture") & t.has_result & t.match_bands.fillna("").str.contains('"E"')
          & t.match_bands.fillna("").str.contains('"A"')]
    return str(c.sort_values("unique_id").iloc[0].unique_id)


def record_verifier(tb: Toolbox) -> Path:
    uid = pick_verifier_facility(tb)
    fac = verifier.facility_from_data(tb.data, uid)
    s = verifier.VerifierSession(fac)
    for _ in s.start():
        pass
    for r in VERIFIER_REPLIES:
        for _ in s.handle(r):
            pass
    rec = s.record()
    p = OUT / "verifier_sms_sandbox.json"
    EV.save_recording(p, "verifier_session", rec["events"], f"Recorded session. {verifier.LABEL}. Replies typed "
                      "for the demo; no clinic was contacted.", facility=rec["facility"], answers=rec["answers"],
                      sms=rec["sms"], before=rec["before"], after=rec["after"], notes=rec["notes"])
    return p


def record_watcher(draws: int) -> Path:
    rec = watcher.run("2026-09", "2026-10", n_draws=draws, out_dir=OUT / "watcher")
    p = OUT / "watcher_2026-09_to_2026-10.json"
    EV.save_recording(p, "watcher_run", rec["events"], "Recorded run. Real band changes from NERC's published "
                      "orders (naija-grid caps_long.csv); no model is involved.", totals=rec["report"]["totals"])
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-watcher", action="store_true")
    ap.add_argument("--watcher-draws", type=int, default=16)
    a = ap.parse_args(argv)
    tb = Toolbox()
    out = record_planner(tb) + [record_verifier(tb)]
    if not a.skip_watcher:
        out.append(record_watcher(a.watcher_draws))
    for p in out:
        rec = json.loads(p.read_text())
        print(p.name, len(rec["events"]), "events", EV.validate(rec["events"]) or "valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
