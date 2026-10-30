"""Fixture mode: every route the web client calls, served from data/fixtures/ with no data/work access."""

from __future__ import annotations

import pandas as pd
import pytest
from api_helpers import make_settings, missing_required, ts_interfaces


def test_types_ts_parses():
    t = ts_interfaces()
    assert {"Health", "FacilityListItem", "FacilityRecord", "SimulateResponse", "Plan", "PlanRow", "Feeder",
            "Summary", "Results"} <= set(t)
    assert t["FacilityRecord"]["facility"] is True and t["FacilityRecord"]["trace"] is False


def test_health(fx_client):
    r = fx_client.get("/api/health")
    assert r.status_code == 200
    h = r.json()
    assert h["fixture"] is True and h["ok"] is True
    assert not missing_required(h, "Health")
    assert h["sms_ussd"] == {"sandbox": True, "sends": False}


def test_summary_and_list(fx_client):
    s = fx_client.get("/api/summary").json()
    assert not missing_required(s, "Summary")
    items = fx_client.get("/api/facilities").json()
    assert len(items) > 10
    for it in items:
        assert not missing_required(it, "FacilityListItem")
    edo = fx_client.get("/api/facilities", params={"state": "Edo"}).json()
    assert edo and all(f["state"] == "Edo" for f in edo)
    assert fx_client.get("/api/facilities", params={"q": "general"}).json()
    assert len(fx_client.get("/api/facilities", params={"limit": 3}).json()) == 3


def test_facility_detail_and_alias(fx_client):
    r = fx_client.get("/api/facilities/WL-0002")
    assert r.status_code == 200
    rec = r.json()
    assert not missing_required(rec, "FacilityRecord")
    assert not missing_required(rec["facility"], "Facility")
    assert not missing_required(rec["match"], "Match")
    if "fix" in rec:
        assert not missing_required(rec["fix"], "Fix")
    assert fx_client.get("/api/facilities/2").json()["facility"]["id"] == "WL-0002"
    assert fx_client.get("/api/facilities/WL-9999").status_code == 404
    assert fx_client.get("/api/facilities/..%2F..%2Fhealth").status_code == 404


def test_simulate_snaps_to_fixture_grid(fx_client):
    body = {"loads": ["fridge", "delivery"], "pv_kwp": 2.1, "battery_kwh": 4.8, "target": 0.99, "fridge_mode": "pqs_sdd"}
    r = fx_client.post("/api/facilities/WL-0002/simulate", json=body)
    assert r.status_code == 200
    out = r.json()
    assert not missing_required(out, "SimulateResponse")
    assert not missing_required(out["trace"], "HourlyTrace")
    assert out["snapped"] is True and out["sample"] is True
    assert out["trace"]["fridge_mode"] == "pqs_sdd"


@pytest.mark.parametrize("bad", [
    {"pv_kwp": -1}, {"battery_kwh": 1e6}, {"fridge_mode": "battery"}, {"loads": ["kitchen"]}, {"target": 2},
])
def test_simulate_validation(fx_client, bad):
    body = {"loads": ["fridge"], "pv_kwp": 0, "battery_kwh": 0, "target": 0.99, "fridge_mode": "shared", **bad}
    assert fx_client.post("/api/facilities/WL-0002/simulate", json=body).status_code == 422


def test_plan_feeder_results(fx_client):
    p = fx_client.get("/api/plan", params={"state": "Edo", "target": 0.99}).json()
    assert p["ranked"]
    assert all(not missing_required(r, "PlanRow") for r in p["ranked"])
    cum = [r["cumulative_ngn"] for r in p["ranked"]]
    assert cum == sorted(cum)
    f = fx_client.get("/api/feeders/bedc-govt-house").json()
    assert not missing_required(f, "Feeder")
    res = fx_client.get("/api/results").json()
    assert not missing_required(res, "Results")
    assert fx_client.get("/api/feeders/nope").status_code == 404


def test_no_data_work_access(fixture_root, tmp_path, monkeypatch):
    """Fixture mode must never read a parquet file."""
    from fastapi.testclient import TestClient

    from api.main import create_app

    def boom(*a, **k):
        raise AssertionError("fixture mode read a parquet file")

    monkeypatch.setattr(pd, "read_parquet", boom)
    c = TestClient(create_app(make_settings(fixtures=fixture_root, work=tmp_path / "absent")))
    for url in ("/api/health", "/api/summary", "/api/facilities", "/api/facilities/WL-0001", "/api/plan",
                "/api/results", "/api/feeders/bedc-govt-house"):
        assert c.get(url).status_code == 200, url
    body = {"loads": ["fridge"], "pv_kwp": 0, "battery_kwh": 0, "target": 0.99, "fridge_mode": "shared"}
    assert c.post("/api/facilities/WL-0001/simulate", json=body).status_code == 200


def test_unknown_api_route_is_json_404(fx_client):
    r = fx_client.get("/api/nope")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_spa_fallback(fixture_root, tmp_path):
    from fastapi.testclient import TestClient

    from api.main import create_app

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Wardlight</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    c = TestClient(create_app(make_settings(fixtures=fixture_root, web_dist=dist)))
    assert "Wardlight" in c.get("/").text
    assert "Wardlight" in c.get("/facility/WL-0001").text  # client route
    a = c.get("/assets/app.js")
    assert a.text == "console.log(1)" and "immutable" in a.headers["cache-control"]
    assert "Wardlight" in c.get("/../../etc/passwd").text  # traversal falls back to the app shell
