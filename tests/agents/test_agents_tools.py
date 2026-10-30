import json

import synth
from agent_markers import needs_work

from agents import engine_adapter as EA
from agents.tools import TOOL_NAMES, TOOL_SPECS, Session, Toolbox


def call(name, **args):
    tb, s = synth.toolbox(), Session()
    return tb.call(name, args, s), s


def test_specs_are_valid_openai_tools():
    for t in TOOL_SPECS:
        assert t["type"] == "function" and t["function"]["parameters"]["type"] == "object"
        json.dumps(t)
    assert TOOL_NAMES == {"list_facilities", "get_facility", "what_if", "size_system", "rank_budget",
                          "get_nerc_rows", "band_history", "refuse"}


def test_list_facilities_filters_and_counts():
    r, s = call("list_facilities", state="kano", lga="gwale")
    assert r["state"] == "Kano" and r["lga"] == "Gwale" and r["count"] == 3
    assert [f["unique_id"] for f in r["facilities"]] == ["T2", "T1", "T5"]  # by doses per naira, unknown last
    assert all(f["cite"].startswith("S") for f in r["facilities"]) and "2 to 8" in r["metric_definition"]


def test_state_aliases_and_unknown_state():
    r, _ = call("list_facilities", state="Kano State")
    assert r["state"] == "Kano"
    r, _ = call("list_facilities", state="Ghana")
    assert "error" in r and "Nigeria only" in r["error"]


def test_get_facility_has_evidence():
    r, s = call("get_facility", unique_id="T1")
    assert r["match"]["tier"] == "a_named" and r["nerc_rows"][0]["page"] == 3 and r["nerc_rows"][0]["sn"] == 7
    c = s.citations[r["nerc_rows"][0]["cite"]]
    assert c["order_file"] == synth.ROW and c["sn"] == "7"
    assert r["results"]["uptime_today"] == 0.5
    r, _ = call("get_facility", unique_id="NOPE")
    assert "error" in r


def test_rank_budget_matches_engine_plan_rank():
    tb, s = synth.toolbox(), Session()
    r = tb.call("rank_budget", {"state": "Kano", "budget": 3.5e6, "priority": "doses"}, s)
    ranked, summ = EA.rank(tb.plan_frame("Kano"), 3.5e6, "doses")
    assert {f["unique_id"] for f in s.last_plan["funded"]} == set(ranked[ranked.funded].unique_id)
    assert r["totals"]["spent_ngn"] == summ["spent_ngn"] and r["totals"]["budget_ngn"] == 3.5e6
    assert r["totals"]["no_engine_result"] == 0 and r["totals"]["facilities_in_scope"] == 5
    assert r["not_reached"]["unknown_supply"]["count"] == 1


def test_rank_budget_filters_and_bad_args():
    r, s = call("rank_budget", state="Kano", budget=1e7, priority="doses", facility_level="Secondary")
    assert r["totals"]["facilities_in_scope"] == 1
    for bad in ({"priority": "votes"}, {"budget": -5}, {"currency": "EUR"}, {"lga": "Nowhere"}):
        args = {"state": "Kano", "budget": 1e6, "priority": "doses", **bad}
        r, _ = call("rank_budget", **args)
        assert "error" in r, bad


def test_nerc_rows_and_band_history():
    r, _ = call("get_nerc_rows", place="gamma")
    assert r["count"] == 1 and r["rows"][0]["band"] == "D"
    r, _ = call("band_history", feeder_name="11kv test one")
    f = r["feeders"][0]
    assert f["changes"] == [{"from_month": "2026-09", "to_month": "2026-10", "from": "A", "to": "B"}]


def test_session_citations_dedupe():
    s = Session()
    a = s.cite({"type": "x", "id": 1})
    assert s.cite({"id": 1, "type": "x"}) == a and s.cite({"type": "y"}) != a


@needs_work
def test_real_rank_equals_plan_rank():
    tb, s = Toolbox(), Session()
    r = tb.call("rank_budget", {"state": "Kaduna", "budget": 5e7, "priority": "doses"}, s)
    ranked, _ = EA.rank(tb.plan_frame("Kaduna"), 5e7, "doses")
    assert {f["unique_id"] for f in s.last_plan["funded"]} == set(ranked[ranked.funded].unique_id)
    assert r["totals"]["spent_ngn"] <= 5e7
