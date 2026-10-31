"""Record the brief 13 fixture sessions for the UI into data/fixtures/agents/ (all marked recorded).

    python -m agents.record

Planner sessions use the rule-based scripted model (no language model is called, no cost) over the real brief 13
tools and the city build. The verifier session uses typed sandbox replies. The watcher replays TCN's two 2024
statements about the line cut. Every file stores the full event list with its original seq and t_ms, so a replay is
faithful. The health-facility recordings are kept unchanged in data/fixtures/agents/archive-brief1/.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import city13 as C13
from . import events as EV
from . import fake13, planner, verifier13, watcher13
from .evaluate import load_questions13
from .tools13 import Toolbox13

OUT = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "agents"
SCRIPTED = ("Recorded session. Scripted test model: rule-based, no language model was called. Tool results are "
            "real (brief 13 city build, data version {v}).")
PLANNER_SESSIONS = [
    ("planner13_maiduguri_two_months", "C01", False,
     "Maiduguri: the line is cut for two months, N2 billion for hospitals, water and cold chain."),
    ("planner13_damaturu_health", "C02", False, "Damaturu: a 40-day cut, N500 million for health facilities."),
    ("planner13_grounding_block", "C03", True,
     "The grounding check in action: the first draft carries an invented figure, the check blocks it, the retry "
     "passes (Maiduguri water and cold chain, N1 billion)."),
    ("planner13_refusal_medical", "C12", False, "A medical-advice question, refused by the rule pre-filter."),
    ("planner13_refusal_attack", "C14", False,
     "A request to forecast attacks on the line, refused: no incident data, and Wardlight does not name targets."),
]
VERIFIER_SITE = "W-BH-589"  # MOGCOLIS CAMP (motorized borehole), Maiduguri: the first motorized borehole in plan order
VERIFIER_REPLIES = ["2", "yes we have one", "maybe 10 or 12", "10"]


def record_planner(tb: Toolbox13) -> list[Path]:
    qs = {q["id"]: q for q in load_questions13()}
    paths = []
    for name, qid, fab, what in PLANNER_SESSIONS:
        rec = planner.run(qs[qid]["question"], fake13.RuleBasedCityPlannerModel(fabricate_first=fab), tb)
        p = OUT / f"{name}.json"
        EV.save_recording(p, "planner_session", rec["events"], SCRIPTED.format(v=tb.data.version),
                          scripted=True, question_id=qid, what=what, output=rec["output"],
                          transcript=rec["transcript"], brief=13)
        paths.append(p)
    return paths


LIVE = ("Recorded live session: {model} on Nebius Token Factory, {date}. Tool results are real (brief 13 city "
        "build, data version {v}). Reasoning text is the model's own.")
LIVE_SESSIONS = [  # (fixture name, run dir, question id, what)
    ("planner13_live_maiduguri", "data/runs/live13-2026-10-31-run2", "C01",
     "Maiduguri: the line is cut for two months, N2 billion for hospitals, water and cold chain (live model)."),
]


def import_live(tb: Toolbox13) -> list[Path]:
    """Serve sessions from a live T8/T9 run (agents.live13) as recordings; no model is called here."""
    root = Path(__file__).resolve().parents[1]
    paths = []
    for name, run_dir, qid, what in LIVE_SESSIONS:
        src = root / run_dir / f"{qid}.json"
        if not src.exists():
            continue
        rec = json.loads(src.read_text())
        out = rec["output"]
        p = OUT / f"{name}.json"
        EV.save_recording(p, "planner_session", rec["events"],
                          LIVE.format(model=out["model"], date=run_dir.rsplit("live13-", 1)[-1][:10], v=tb.data.version),
                          scripted=False, question_id=qid, what=what, output=out, transcript=rec["transcript"],
                          brief=13)
        paths.append(p)
    return paths


def record_verifier(data: C13.City13Data) -> Path:
    s = verifier13.session_for(data, VERIFIER_SITE)
    for _ in s.start():
        pass
    for r in VERIFIER_REPLIES:
        for _ in s.handle(r):
            pass
    rec = s.record()
    p = OUT / "verifier13_borehole_sms.json"
    EV.save_recording(p, "verifier_session", rec["events"], f"Recorded session. {verifier13.LABEL}. Replies typed "
                      "for the demo; no site was contacted.", site=rec["site"], city=rec["city"],
                      question=f"Verify {rec['site']['name']} by SMS: does it have a generator, and how long did it run?",
                      what="SMS check with the borehole committee: pump type, generator, hours last week.",
                      answers=rec["answers"], sms=rec["sms"], facts=rec["facts"], before=rec["before"],
                      after=rec["after"], notes=rec["notes"], data_version=data.version, brief=13)
    return p


def record_watcher(data: C13.City13Data) -> Path:
    rec = watcher13.run("maiduguri", watcher13.DEFAULT_BUDGET, data=data)
    p = OUT / "watcher13_line_cut_2024.json"
    EV.save_recording(p, "watcher_run", rec["events"], watcher13.LABEL, totals=rec["totals"],
                      question="TCN reports the Gombe to Damaturu to Maiduguri line cut. Which sites run first?",
                      what="The 2024 line cut, replayed from TCN's statements: run order, then the event closed.",
                      data_version=data.version, brief=13)
    return p


def main(argv=None) -> int:
    argparse.ArgumentParser().parse_args(argv)
    data = C13.City13Data()
    tb = Toolbox13(data)
    out = record_planner(tb) + import_live(tb) + [record_verifier(data), record_watcher(data)]
    for p in out:
        rec = json.loads(p.read_text())
        print(p.name, len(rec["events"]), "events", EV.validate(rec["events"]) or "valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
