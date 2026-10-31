"""Brief 13: outage blocks, city view, outage trace, outage metrics on plan and brief, summary headline."""

from __future__ import annotations

import pandas as pd
import pytest
from api_helpers import WORK

from api import outage_api as OA

BICHI = "SN_A6457D29FB"


@pytest.fixture(scope="module")
def results():
    return pd.read_parquet(WORK / "facility_results.parquet").set_index("unique_id")


def test_detail_outage_blocks_match_parquet(live_client, results):
    rec = live_client.get(f"/api/facilities/{BICHI}").json()
    o = rec["outage"]
    r = results.loc[BICHI]
    assert o["durations"] == OA.durations(results.columns)
    for d in o["durations"]:
        b = o["by_days"][str(d)]
        assert b["needed_h"] == pytest.approx(r[f"out{d}_needed_h"])
        assert b["hours_today"]["p"] == pytest.approx(r[f"out{d}_hours_today"])
        assert b["hours_with"]["lo"] == pytest.approx(r[f"out{d}_hours_with_lo"])
        assert b["diesel_l_avoided"]["mid"] == pytest.approx(r[f"out{d}_diesel_l_avoided"])
        assert b["by_service"] and "vaccine_fridge" in b["by_service"]
    assert o["scenarios"]["hours_today"].startswith("today")


def test_list_rows_carry_outage_fields(live_client, results):
    row = live_client.get("/api/facilities", params={"q": BICHI}).json()[0]
    for d in OA.durations(results.columns):
        assert row[f"out{d}_with_h"] == pytest.approx(round(results.loc[BICHI, f"out{d}_hours_with"], 1))
        assert f"out{d}_orfix_h" in row


def test_city_totals_and_ranking(live_client, results):
    j = live_client.get("/api/city", params={"state": "Kano", "lgas": "Bichi,Kumbotso", "days": 7}).json()
    assert j["days"] == 7 and set(j["lgas"]) == {"Bichi", "Kumbotso"}
    t = j["totals"]
    ids = [r["id"] for r in j["ranked"]]
    assert t["facilities"] == j["ranked_total"] == len(ids)
    assert t["service_hours_with"] == pytest.approx(results.loc[ids, "out7_hours_with"].sum())
    assert t["diesel_l_avoided"]["mid"] == pytest.approx(results.loc[ids, "out7_diesel_l_avoided"].sum())
    gains = [r["gain_h"] for r in j["ranked"]]
    assert gains == sorted(gains, reverse=True)
    assert j["engine_aggregate"]
    assert live_client.get("/api/city", params={"state": "Kano", "days": 5}).status_code == 422
    assert live_client.get("/api/city", params={"state": "Kano", "lgas": "Nowhere"}).status_code == 404


def test_outage_trace(live_client):
    j = live_client.get(f"/api/facilities/{BICHI}/outage_trace", params={"days": 3}).json()
    n = len(j["hour"])
    assert sum(j["in_outage"]) == 72 and n == 72 + 2 * j["draw"]["pad_h"]
    assert not any(g for g, o in zip(j["grid_on"], j["in_outage"]) if o)  # grid off through the window
    for k in ("grid_on", "solar_kw", "load_kw", "battery_soc"):
        assert len(j[k]) == n
    assert set(j["rooms"]) == {"fridge", "delivery", "oxygen", "ward", "lab"}
    assert all(len(v) == n for v in j["rooms"].values())
    assert j["scenario"].startswith("with the recommended fix") and "rule" in j["draw"]
    assert j["draw"]["lane_service_hours_with"] == pytest.approx(j["draw"]["median_service_hours_with"], abs=24)
    assert j["headline"]["days"] == 3
    assert live_client.get(f"/api/facilities/{BICHI}/outage_trace", params={"days": 4}).status_code == 422


def test_plan_and_brief_accept_outage_hours(live_client, results):
    from engine import plan as PL

    params = {"state": "Kano", "budget_ngn": 8e7, "metric": "outage_hours", "days": 7}
    p = live_client.get("/api/plan", params=params).json()
    assert p["metric"] == "outage_hours" and p["outage_days"] == 7
    funded = [r for r in p["ranked"] if r["funded"]]
    assert funded and all(r["outage"]["with_h"] is not None for r in funded)
    df = results.reset_index()
    fac = pd.read_parquet(WORK / "facilities.parquet").drop_duplicates("unique_id")
    kano = df[df.unique_id.isin(fac[fac.state_standard == "Kano"].unique_id)]
    first = PL.rank(kano, 8e7, "outage_hours", outage_days=7)
    assert funded[0]["id"] == first[first.funded].iloc[0].unique_id
    b = live_client.get("/api/plan/brief", params=params).json()
    assert [r["id"] for r in b["funded"]] == [r["id"] for r in funded]
    assert "outage" in b["benefit_unit"] and b["funded"][0]["clinic_system"]["pv_kwp"] is not None
    csv_text = live_client.get("/api/plan/brief.csv", params=params).text
    assert csv_text.count("\n") == len(b["funded"]) + 1


def test_summary_leads_with_brief13(live_client):
    s = live_client.get("/api/summary").json()
    assert next(iter(s)) == "headline_metric"
    h = s["headline_metric"]
    assert h["brief"] == 13 and "line outage" in h["metric"]
    b7 = h["by_days"][str(h["default_days"])]
    assert b7["service_hours_needed"] > b7["service_hours_with"] >= b7["service_hours_today"] >= 0


def test_orfix_columns_fill_their_duration_only():
    row = {"out7_window_h": 168, "out7_needed_h": 343.0, "out7_hours_today": 2.0, "out7_hours_with": 223.0,
           "out3_window_h": 72, "out3_needed_h": 147.0, "out3_hours_today": 1.0, "out3_hours_with": 137.0,
           "orfix_days": 7, "orfix_hours_kept": 300.0, "orfix_hours_kept_lo": 280.0, "orfix_hours_kept_hi": 320.0,
           "orfix_diesel_l_avoided": 12.0, "orfix_diesel_l_avoided_lo": 10.0, "orfix_diesel_l_avoided_hi": 14.0,
           "orfix_capex_ngn": 9e6, "orfix_share_kept": 0.87, "orfix_category": "ii+c", "orfix_label": "x"}
    per, fix = OA.orfix_columns(row.keys())
    o = OA.outage_for(row, [3, 7], per, fix)
    assert o["by_days"]["7"]["hours_orfix"] == {"p": 300.0, "lo": 280.0, "hi": 320.0}
    assert o["by_days"]["7"]["orfix"]["diesel_l_avoided"]["mid"] == 12.0
    assert o["by_days"]["3"]["hours_orfix"] is None and "7 days" in o["by_days"]["3"]["orfix_note"]
    assert o["outage_ready_fix"]["category"] == "ii+c"
    assert OA.compact(row, [3, 7], per) == {
        "3": {"needed_h": 147.0, "today_h": 1.0, "with_h": 137.0, "orfix_h": None, "diesel_l_avoided": None},
        "7": {"needed_h": 343.0, "today_h": 2.0, "with_h": 223.0, "orfix_h": 300.0, "diesel_l_avoided": None}}
    t = OA.city_totals(pd.DataFrame([row, {**row, "orfix_hours_kept": 100.0}]), 7, None)
    assert t["service_hours_orfix"] == 400.0 and t["share_orfix"] == pytest.approx(400 / 686)


def test_absent_orfix_is_null_not_invented(live_client):
    o = live_client.get(f"/api/facilities/{BICHI}").json()["outage"]
    if o["outage_ready_fix"]:
        pytest.skip("this build carries the outage-ready fix")
    assert all(b["hours_orfix"] is None and b["orfix_note"] for b in o["by_days"].values())
    assert live_client.get("/api/plan", params={"state": "Kano", "metric": "orfix_hours"}).status_code == 422


def test_fixture_mode_has_no_outage_views(fx_client):
    assert fx_client.get("/api/city", params={"state": "Edo"}).status_code == 404
    assert fx_client.get("/api/facilities/WL-0002/outage_trace").status_code == 404
