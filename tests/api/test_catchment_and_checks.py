"""Capped-catchment pass-through, NERC rows checked by eye (docs/VERIFIED_ROWS.csv), and uptime scenario labels."""

from __future__ import annotations

import shutil

import pytest
from api_helpers import ROOT, WORK, make_settings

BICHI = "SN_A6457D29FB"  # Bichi General Hospital
BICHI_ROW = ("KEDCO_HOLDCO_YSS_Septmeber_2026_096.pdf", 13, 112)
FIELDS = ("capped", "catchment_pop", "pop_above_cap", "doses_demand_uncapped")


@pytest.fixture(scope="module")
def truth():
    import pandas as pd

    r = pd.read_parquet(WORK / "facility_results.parquet").set_index("unique_id")
    c = pd.read_parquet(WORK / "catchments.parquet").set_index("unique_id")
    return r, c


def _expect(truth, uid):
    r, c = truth
    return {"capped": bool(r.loc[uid, "capped"]), "catchment_pop": round(float(c.loc[uid, "catchment_pop"])),
            "pop_above_cap": round(float(c.loc[uid, "pop_above_cap"])),
            "doses_demand_uncapped": round(float(r.loc[uid, "doses_demand_uncapped"]))}


def test_bichi_detail_and_list_carry_catchment(live_client, truth):
    want = _expect(truth, BICHI)
    f = live_client.get(f"/api/facilities/{BICHI}").json()["facility"]
    assert {k: f[k] for k in FIELDS} == want
    assert f["catchment"] == want["catchment_pop"]  # no longer null
    row = live_client.get("/api/facilities", params={"q": BICHI}).json()[0]
    assert {k: row[k] for k in FIELDS} == want
    full = live_client.get("/api/facilities").json()
    assert all(k in full[0] for k in FIELDS)


def test_plan_and_brief_rows_carry_catchment_and_capped_count(live_client, truth):
    params = {"state": "Kano", "budget_ngn": 8e7}
    p = live_client.get("/api/plan", params=params).json()
    funded = [r for r in p["ranked"] if r["funded"]]
    for r in funded[:20]:
        assert {k: r[k] for k in FIELDS} == _expect(truth, r["id"])
    assert p["summary"]["capped_funded"] == sum(1 for r in funded if r["capped"])
    b = live_client.get("/api/plan/brief", params=params).json()
    for r in b["funded"][:20]:
        assert {k: r[k] for k in FIELDS} == _expect(truth, r["id"])
    assert b["totals"]["capped_funded"] == sum(1 for r in b["funded"] if r["capped"]) == p["summary"]["capped_funded"]
    head = live_client.get("/api/plan/brief.csv", params=params).text.splitlines()[0].split(",")
    assert set(FIELDS) <= set(head)


def test_bichi_row_is_verified_by_eye(live_client):
    ev = live_client.get(f"/api/facilities/{BICHI}").json()["match"]["evidence"]
    assert (ev["file"], ev["page"], ev["sn"]) == BICHI_ROW
    assert ev["verified"] is True and ev["checked_by"].startswith("Aashan Javed") and "row image" in ev["how"]
    assert ev["verified_by"].startswith("Aashan Javed") and ev["verified_how"] == ev["how"] and ev["verified_method"] == "by eye"
    fid = live_client.get(f"/api/facilities/{BICHI}").json()["match"]["feeder_id"]
    rows = live_client.get(f"/api/feeders/{fid}").json()["rows"]
    assert any(r["sn"] == 112 and r["verified"] for r in rows)


def test_unlisted_rows_say_ocr(live_client):
    items = live_client.get("/api/facilities", params={"state": "Bayelsa", "tier": "b_place", "limit": 5}).json()
    for it in items:
        ev = live_client.get(f"/api/facilities/{it['id']}").json()["match"]["evidence"]
        key = (ev["file"], ev["page"], ev["sn"])
        if key != BICHI_ROW:
            assert ev["verified"] is False and ev["verified_note"] == "read by OCR, not checked by eye"


def test_verified_rows_file_is_read_at_startup_and_mismatch_is_not_verified(tmp_path):
    """A fresh docs folder: the Bichi row listed with a mismatch result is served unverified, with the result."""
    from api_helpers import HAS_WORK

    if not HAS_WORK:
        pytest.skip("data/work is not built")
    from fastapi.testclient import TestClient

    from api.main import create_app

    docs = tmp_path / "docs"
    shutil.copytree(ROOT / "docs", docs)
    f, pg, sn = BICHI_ROW
    (docs / "VERIFIED_ROWS.csv").write_text(
        "order_file,page,sn,checked_by,how,result\n"
        f"{f},{pg},{sn},tester,crop read by eye,mismatch: min hours read as 12 printed 16\n")
    c = TestClient(create_app(make_settings(fixture=False, docs=docs)))
    ev = c.get(f"/api/facilities/{BICHI}").json()["match"]["evidence"]
    assert ev["verified"] is False and ev["checked_by"] == "tester" and ev["check_result"].startswith("mismatch")


def test_uptime_scenario_labels(live_client):
    row = live_client.get("/api/facilities", params={"q": BICHI}).json()[0]
    assert row["scenario"] == "household or non-PQS fridge"
    p = live_client.get("/api/plan", params={"state": "Kano", "budget_ngn": 8e7}).json()["ranked"][0]
    assert p["scenario"] == "household or non-PQS fridge"
    assert p["scenarios"]["uptime_today"] == "household or non-PQS fridge"
    assert set(p["scenarios"]) == {"uptime_today", "uptime_today_pqs", "uptime_with_system"}
    b = live_client.get("/api/plan/brief", params={"state": "Kano", "budget_ngn": 8e7}).json()["funded"][0]
    assert b["scenario"] == "household or non-PQS fridge" and set(b["scenarios"]) == {"uptime_today",
                                                                                      "uptime_with_fix"}
