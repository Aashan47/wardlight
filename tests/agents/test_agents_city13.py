"""Brief 13 agents: the city plan, the planner tools and scripted sessions, the site verifier, the line watcher, and
the recorded sessions. Runs on the committed brief 13 fixtures (data/fixtures/brief13), so it needs no work data.

The scripted planner runs are harness tests, never the T8 or T9 result (those need the live model run)."""

import json
from pathlib import Path

import pytest

from agents import city13 as C13
from agents import evaluate, events, fake13, planner, verifier13, watcher13
from agents.tools import Session
from agents.tools13 import Toolbox13

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures" / "agents"


@pytest.fixture(scope="module")
def data():
    return C13.City13Data(C13.FIX13)


@pytest.fixture(scope="module")
def tb(data):
    return Toolbox13(data)


# ---------------------------------------------------------------- the plan


def test_full_budget_reproduces_the_city_metrics(data):
    p = C13.plan(data, "maiduguri", 1e13, 60)
    m = data.metrics("maiduguri", 60)["impact"]
    assert p["totals"]["funded_count"] == p["totals"]["candidates"] == 279
    assert abs(p["totals"]["csh_needed"] - m["csh_needed"]) < 1
    assert abs(p["totals"]["share_with_funded"] - m["share_with"]) < 1e-4
    assert abs(p["totals"]["share_today"] - m["share_today"]) < 1e-4
    assert abs(p["totals"]["diesel_l_avoided"] - m["diesel_l_avoided"]["point"]) < 1
    assert abs(p["water"]["m3_per_day_with_funded"] - m["water_m3_per_day_kept"]["with"]) < 1
    assert {x["id"] for x in p["excluded"]} == {x["id"] for x in data.metrics("maiduguri", 60)["excluded"]["existing_onsite"]}


def test_budget_walk_is_greedy_in_rank_order(data):
    p = C13.plan(data, "maiduguri", 2e9, 60)
    t = p["totals"]
    assert t["spent_ngn"] <= 2e9 and t["remaining_ngn"] == pytest.approx(2e9 - t["spent_ngn"], abs=1)
    ranks = [f["rank"] for f in p["funded"]]
    assert ranks == sorted(ranks)
    # every skipped site would have broken the budget at the point it was reached
    spent = 0.0
    for r in p["rows"]:
        if r["funded"]:
            spent += r["capex_ngn"]
        else:
            assert spent + r["capex_ngn"] > 2e9
    assert t["share_today"] < t["share_with_funded"] < t["share_with_every_site"]
    assert p["by_sector"]["health"]["funded"] + p["by_sector"]["water"]["funded"] + p["by_sector"]["cold"]["funded"] \
        == t["funded_count"]


def test_sectors_and_errors(data):
    p = C13.plan(data, "maiduguri", 1e9, 14, ["water", "cold"])
    assert {f["sector"] for f in p["funded"]} <= {"water", "cold"} and p["by_sector"]["health"]["funded"] == 0
    assert C13.plan(data, "maiduguri", 0, 60)["totals"]["funded_count"] == 0
    assert C13.City13Data.resolve_sectors("hospitals, cold chain") == ("health", "cold")
    for bad in (dict(city="kano"), dict(days=5), dict(sectors=["roads"]), dict(budget_ngn=-1)):
        kw = {"city": "maiduguri", "budget_ngn": 1e9, "days": 60, "sectors": None, **bad}
        with pytest.raises(C13.CityDataError):
            C13.plan(data, **kw)
    csv = C13.plan_csv(p).splitlines()
    assert len(csv) == 1 + p["totals"]["candidates"] and csv[0].startswith("order,rank,id")


# ---------------------------------------------------------------- tools


def test_tools(tb):
    s = Session()
    r = tb.call("rank_city_plan", {"city": "Maiduguri", "budget": 1_000_000, "currency": "USD", "days": 40,
                                   "sectors": ["health"]}, s)
    fx = tb.data.constant("maiduguri", "FX_NGN_PER_USD")["value"]
    assert r["budget_ngn"] == pytest.approx(1_000_000 * fx) and r["cite"] in s.citations and s.last_plan
    site = tb.call("get_site", {"site_id": r["funded_top"][0]["id"], "days": 40}, s)
    assert site["results"]["needed_h"] > 0 and site["siting"]["line_kv"] == 330
    assert tb.call("city_metrics", {"city": "damaturu", "days": 14}, s)["impact"]["csh_needed"] > 0
    cc = tb.call("cost_compare", {"city": "maiduguri"}, s)
    assert cc["cost_per_kwh_ngn"]["solar"]["point"] < cc["cost_per_kwh_ngn"]["diesel"]["point"]
    assert "error" in tb.call("get_site", {"site_id": "nope"}, s)
    assert "error" in tb.call("rank_city_plan", {"city": "lagos", "budget": 1}, s)
    assert "error" in tb.call("rank_budget", {"state": "Kano"}, s)  # brief 1 tool is not in this toolbox


# ---------------------------------------------------------------- the 16 questions and scripted sessions


def test_questions13_file_is_consistent():
    qs = evaluate.load_questions13()
    assert [q["id"] for q in qs] == [f"C{i:02d}" for i in range(1, 17)]
    assert sum(q["kind"] == "plan" for q in qs) == 11
    assert all(q["question"] for q in qs)
    assert len(evaluate.load_questions()) == 20  # the brief 1 set is unchanged


def test_scripted_harness_run_of_all_16(tb):
    qs = evaluate.load_questions13()
    recs = {q["id"]: planner.run(q["question"], fake13.RuleBasedCityPlannerModel(), tb) for q in qs}
    res = evaluate.evaluate_run13(recs, tb, qs)
    assert res["counts_as_prereg_result"] is False
    assert res["t8"]["pass"], [r for r in res["rows"] if not r["t8"]["ok"]]
    assert res["t9"]["passed"] == 16, [r for r in res["rows"] if not r["t9"]["ok"]]
    for r in recs.values():
        assert events.validate(r["events"]) == []
        assert "—" not in r["output"]["answer_markdown"]


def test_t9_city_catches_a_wrong_plan(tb):
    spec = next(q for q in evaluate.load_questions13() if q["id"] == "C02")
    rec = planner.run(spec["question"], fake13.RuleBasedCityPlannerModel(), tb)
    assert evaluate.check_t9_city(spec, rec, tb)["ok"]
    rec["output"]["funded"] = rec["output"]["funded"][:-1]
    assert not evaluate.check_t9_city(spec, rec, tb)["ok"]
    assert not evaluate.check_t9_city({**spec, "days": 60}, planner.run(spec["question"],
                                      fake13.RuleBasedCityPlannerModel(), tb), tb)["ok"]


def test_invented_figure_is_blocked_then_retry_passes(tb):
    q = next(q for q in evaluate.load_questions13() if q["id"] == "C03")["question"]
    rec = planner.run(q, fake13.RuleBasedCityPlannerModel(fabricate_first=True), tb)
    checks = [e for e in rec["events"] if e["type"] == "check"]
    assert [c["ok"] for c in checks] == [False, True] and "987,654" in checks[0]["unmatched"]
    assert rec["output"]["status"] == "answered" and "987,654" not in rec["output"]["answer_markdown"]


# ---------------------------------------------------------------- verifier


def test_verifier_turns_the_assumption_into_reported_hours(data):
    evs = list(verifier13.run_events(data, "W-BH-589", ["2", "yes we have one", "maybe 10 or 12", "10"]))
    assert events.validate(evs) == []
    asks = [e for e in evs if e["type"] == "tool_call" and e["name"] == "ask_site"]
    assert len(asks) == 4 and asks[3]["args"]["message"].startswith("Sorry")  # the ambiguous reply is asked again
    ans = next(e for e in evs if e["type"] == "answer")
    b, a = ans["totals"]["before"], ans["totals"]["after"]
    assert b["point"] is None and b["width"] > 0 and a["point"] == 10 and a["width"] == 0
    assert all(len(x["args"]["message"]) <= 160 for x in asks)
    assert next(e for e in evs if e["type"] == "check")["ok"]


def test_verifier_contradiction_keeps_the_modelled_interval(data):
    evs = list(verifier13.run_events(data, "W-BH-589", ["1", "2"]))
    ans = next(e for e in evs if e["type"] == "answer")
    assert ans["totals"]["after"]["point"] is None and "contradicts" in ans["markdown"]
    evs = list(verifier13.run_events(data, "H-SN_0B1D15D01C", ["no", "3"]))
    ans = next(e for e in evs if e["type"] == "answer")
    assert ans["totals"]["after"]["width"] == 0 and "gen_hours" not in ans["totals"]["answers"]
    with pytest.raises(C13.CityDataError):
        verifier13.session_for(data, "H-SN_33C9871496")  # UMTH: its own plant, not in the plan


# ---------------------------------------------------------------- watcher


def test_watcher_replans_and_closes_the_2024_event(data):
    rec = watcher13.run("maiduguri", 2e9, data=data)
    assert events.validate(rec["events"]) == [] and rec["markdown"]
    ans = next(e for e in rec["events"] if e["type"] == "answer")
    fuel = ans["run_order"]["fuel_first"]
    assert [x["hours_per_litre"] for x in fuel] == sorted((x["hours_per_litre"] for x in fuel), reverse=True)
    funded = set(next(e for e in rec["events"] if e.get("id") == "w3" and e["type"] == "tool_result")["funded"])
    assert not funded & {x["id"] for x in fuel}
    assert rec["totals"]["window_days"] == 40 and 40 < rec["totals"]["duration_days"] < 41
    assert next(e for e in rec["events"] if e["type"] == "check")["ok"]


# ---------------------------------------------------------------- recordings


def test_recordings_are_brief13_only():
    files = sorted(FIXTURES.glob("*.json"))
    assert files and all(p.stem.split("_")[0] in ("planner13", "verifier13", "watcher13") for p in files)
    version = C13.City13Data(C13.FIX13).version
    for p in files:
        text = p.read_text()
        rec = json.loads(text)
        assert rec["brief"] == 13 and "Kano" not in text and "c703b8b82337" not in text and "—" not in text
        assert version in text, p.name
        if rec["kind"] == "planner_session":
            assert rec["output"]["status"] in ("answered", "refused")
            # scripted, or a live session whose label says so and names the model
            assert rec["scripted"] or ("live session" in rec["label"] and rec["output"]["model"] in rec["label"])
