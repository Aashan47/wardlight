"""The 20 fixed questions: the file parses and agrees with itself; the harness runs them with the scripted model.

This is a harness test, not the T8 or T9 result (those need the live model run)."""

import json
from pathlib import Path

from agent_markers import needs_work

from agents import evaluate, events, fake, planner

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "agents"


def test_questions_file_is_consistent():
    qs = evaluate.load_questions()
    assert [q["id"] for q in qs] == [f"Q{i:02d}" for i in range(1, 21)]
    kinds = [q["kind"] for q in qs]
    assert kinds.count("plan") == 16 and kinds.count("refuse") == 4
    assert sum(q.get("reason") == "out_of_scope" for q in qs) == 2
    assert sum(q.get("reason") == "data_cannot_support" for q in qs) == 2
    assert all(q["question"] for q in qs)
    text = (Path(evaluate.QUESTIONS_MD)).read_text()
    assert "\u2014" not in text


@needs_work
def test_scripted_harness_run_of_all_20():
    from agents.tools import Toolbox

    tb = Toolbox()
    qs = evaluate.load_questions()
    recs = {q["id"]: planner.run(q["question"], fake.RuleBasedPlannerModel(), tb) for q in qs}
    res = evaluate.evaluate_run(recs, tb, qs)
    assert res["counts_as_prereg_result"] is False  # scripted, never the PREREG result
    assert res["t8"]["pass"], [r for r in res["rows"] if not r["t8"]["ok"]]
    assert res["t9"]["passed"] == 20, [r for r in res["rows"] if not r["t9"]["ok"]]
    for r in recs.values():
        assert events.validate(r["events"]) == []


def test_t9_catches_a_wrong_plan():
    import synth

    tb = synth.toolbox()
    spec = {"id": "X", "kind": "plan", "state": "Kano", "budget": 3_500_000, "currency": "NGN", "metric": "doses"}
    rec = planner.run("N3.5 million for Kano. Protect the most vaccine doses.", fake.RuleBasedPlannerModel(), tb)
    assert evaluate.check_t9(spec, rec, tb)["ok"]
    rec["output"]["funded"] = rec["output"]["funded"][:-1]
    assert not evaluate.check_t9(spec, rec, tb)["ok"]
    wrong = {**spec, "metric": "load_hours"}
    assert not evaluate.check_t9(wrong, planner.run("N3.5 million for Kano. Protect the most vaccine doses.",
                                                    fake.RuleBasedPlannerModel(), tb), tb)["ok"]


def test_t8_rechecks_from_the_transcript():
    import synth

    rec = planner.run("N3.5 million for Kano. Protect the most vaccine doses.", fake.RuleBasedPlannerModel(),
                      synth.toolbox())
    assert evaluate.check_t8(rec)["ok"]
    rec["output"]["answer_markdown"] += "\nAlso 31,337 more doses [S1]."
    t8 = evaluate.check_t8(rec)
    assert not t8["ok"] and "31,337" in t8["untraced"]


def test_recorded_fixtures_are_valid_and_marked():
    files = sorted(FIXTURES.glob("*.json"))
    for p in files:
        rec = json.loads(p.read_text())
        assert rec["recorded"] is True and rec["label"], p.name
        assert events.validate(rec["events"]) == [], p.name
        assert rec["events"][-1]["recorded"] is True
        if rec["kind"] == "planner_session" and rec.get("scripted"):
            assert "scripted" in rec["label"].lower()
            assert not any(e["type"] == "reasoning" for e in rec["events"])  # nothing synthesised
        elif rec["kind"] == "planner_session":
            assert "live" in rec["label"].lower(), p.name  # a recorded live session says so
            assert all(e["source"] == "model" for e in rec["events"] if e["type"] == "reasoning")
        assert "\u2014" not in p.read_text(), p.name
