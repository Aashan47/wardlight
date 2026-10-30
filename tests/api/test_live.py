"""Live mode on the real data/work build (skipped where data/work does not exist, for example in CI)."""

from __future__ import annotations

import importlib.util

import pytest
from api_helpers import missing_required, sse_events

FULL = {"loads": ["fridge", "delivery", "oxygen", "lab", "ward"], "pv_kwp": 2.0, "battery_kwh": 14.4,
        "target": 0.99, "fridge_mode": "pqs_sdd"}


@pytest.fixture(scope="module")
def ids(live_client):
    items = live_client.get("/api/facilities", params={"state": "Edo"}).json()
    by_tier = {}
    for it in items:
        by_tier.setdefault(it["tier"], it["id"])
    return by_tier


def test_health_reports_data_version_sources_and_staleness(live_client):
    h = live_client.get("/api/health").json()
    assert h["fixture"] is False and len(h["data_version"]) == 12
    assert len(h["sources"]) >= 10 and not missing_required(h, "Health")
    assert "staleness" in h and "results_older_than_matches" in h["staleness"]


def test_list_and_summary(live_client):
    r = live_client.get("/api/facilities")
    items = r.json()
    assert len(items) > 50_000
    assert not missing_required(items[0], "FacilityListItem")
    s = live_client.get("/api/summary").json()
    assert not missing_required(s, "Summary")
    assert s["headline"]["facilities"] == len(items)
    assert sum(s["tiers"].values()) == len(items)
    assert set(s["fixes"]["counts"]) <= {"i", "ii", "iii", "none"}


def test_facility_record_matches_types_and_parquet(live_client, ids):
    import pandas as pd
    from api_helpers import WORK

    fid = ids["b_place"]
    rec = live_client.get(f"/api/facilities/{fid}").json()
    for key, iface in (("facility", "Facility"), ("match", "Match"), ("supply_model", "SupplyModel"),
                       ("recommended", "Recommended"), ("trace", "HourlyTrace")):
        assert not missing_required(rec[key], iface), key
    assert not missing_required(rec, "FacilityRecord")
    assert not missing_required(rec["fix"], "Fix")
    assert [x["key"] for x in rec["scenarios"]] == ["domestic", "pqs_icelined"]
    assert [x["headline"] for x in rec["scenarios"]] == [True, False]
    assert all(not missing_required(x, "Scenario") for x in rec["scenarios"])
    r = pd.read_parquet(WORK / "facility_results.parquet").set_index("unique_id").loc[fid]
    assert rec["brief_metric"]["uptime_today"]["p"] == pytest.approx(r.uptime_today)
    assert rec["brief_metric"]["uptime_with_system"]["lo"] == pytest.approx(r.uptime_with_system_lo)
    assert rec["recommended"]["fix"]["category"] == r.fix_category
    assert rec["fix"]["category"] == {"i": "pqs_icelined", "ii": "pqs_sdd", "iii": "solar_clinic"}[r.fix_category]
    assert rec["recommended"]["capex_ngn"]["mid"] == pytest.approx(r.capex_ngn)
    assert rec["scenarios"][1]["uptime"]["p"] == pytest.approx(r.uptime_today_pqs)
    assert rec["match"]["promised_not_measured"] is True
    ev = rec["match"]["evidence"]
    assert ev["file"] and ev["row_text"] and isinstance(ev["page"], int)
    if ev["crop"]:
        img = live_client.get(ev["crop"])
        assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    code = rec["facility"]["code"]
    assert live_client.get(f"/api/facilities/WL-{code}").json()["facility"]["id"] == fid


def test_refused_and_offgrid_records(live_client, ids):
    for tier in ("d_refused", "offgrid"):
        if tier in ids:
            rec = live_client.get(f"/api/facilities/{ids[tier]}").json()
            assert rec["match"]["tier"] == tier
            if tier == "d_refused":
                assert rec["refused"] is True


def test_simulate_through_engine_and_cache(live_client, ids):
    fid = ids["b_place"]
    a = live_client.post(f"/api/facilities/{fid}/simulate", json=FULL)
    assert a.status_code == 200
    out = a.json()
    assert not missing_required(out, "SimulateResponse")
    assert not missing_required(out["trace"], "HourlyTrace")
    assert len(out["trace"]["hour"]) == 24 and set(out["trace"]["rooms"]) == {"fridge", "delivery", "oxygen", "lab",
                                                                               "ward"}
    assert out["trace"]["fridge_curve"] == "illustrative"
    assert {s["load"] for s in out["survival"]} == set(FULL["loads"])
    b = live_client.post(f"/api/facilities/{fid}/simulate", json=FULL)
    assert a.headers["x-cache"] in ("miss", "hit") and b.headers["x-cache"] == "hit"
    assert b.json()["survival"] == out["survival"]
    snapped = live_client.post(f"/api/facilities/{fid}/simulate", json={**FULL, "pv_kwp": 2.01}).json()
    assert snapped["snapped"] is True and snapped["pv_kwp"] == 2.0
    shared = live_client.post(f"/api/facilities/{fid}/simulate", json={**FULL, "fridge_mode": "shared"}).json()
    assert shared["trace"]["fridge_mode"] == "shared" and shared["costs"]["fridge_usd"] is None


def test_plan(live_client):
    p = live_client.get("/api/plan", params={"state": "Edo", "budget_ngn": 5e7, "target": 0.99}).json()
    assert p["ranked"] and all(not missing_required(r, "PlanRow") for r in p["ranked"][:50])
    cum = [r["cumulative_ngn"] for r in p["ranked"]]
    assert cum == sorted(cum)
    assert {r["fix"] for r in p["ranked"]} <= {"pqs_icelined", "pqs_sdd", "solar_clinic"}
    assert p["summary"]["spent_ngn"] <= 5e7
    assert live_client.get("/api/plan", params={"state": "Atlantis"}).status_code == 404
    assert live_client.get("/api/plan", params={"state": "Edo", "target": 0.9}).status_code == 422


def test_feeder(live_client, ids):
    rec = live_client.get(f"/api/facilities/{ids['b_place']}").json()
    fid = rec["match"]["feeder_id"]
    f = live_client.get(f"/api/feeders/{fid}").json()
    assert not missing_required(f, "Feeder")
    assert any(x["id"] == ids["b_place"] for x in f["facilities"])
    assert f["band_history"] and f["rows"]
    raw = f["row_key"]
    assert live_client.get(f"/api/feeders/{raw.replace('#', '%23')}").json()["id"] == fid


def test_results(live_client):
    rows = {r["id"]: r for r in live_client.get("/api/results").json()["rows"]}
    assert {"T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9"} <= set(rows)
    assert rows["T4"]["status"] in ("hit", "miss") and rows["T3"]["status"] in ("hit", "miss")
    assert all(r["status"] in ("hit", "miss", "not_run", "reported") for r in rows.values())


def test_ussd_live(live_client, ids):
    rec = live_client.get(f"/api/facilities/{ids['b_place']}").json()
    code = rec["facility"]["code"]
    r = live_client.post("/api/ussd", data={"sessionId": "s", "serviceCode": "*384#", "phoneNumber": "+234",
                                            "text": f"1*{code}"})
    assert r.text.startswith("END ") and f"Fix ({rec['recommended']['fix']['category']})" in r.text


@pytest.mark.skipif(importlib.util.find_spec("agents.planner") is None, reason="agent F's planner not present")
def test_planner_scripted_run_streams_real_events(live_client):
    r = live_client.post("/api/agent/plan", params={"stream": True},
                         json={"question": "I have N80 million for Kano this year. Protect the most vaccine doses."})
    evs = sse_events(r.text)
    types = [e["event"] for e in evs]
    assert types[0] == "plan" and types[-1] == "done"
    done = evs[-1]["data"]
    assert done["recorded"] is False and "no language model" in done["model"]
    from agents import events as EV

    assert EV.validate([e["data"] for e in evs]) == []
