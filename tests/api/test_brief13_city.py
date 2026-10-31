"""Brief 13 city routes (14-SUCCESS-METRICS.md API contract), against the fixtures and, where built, the live build."""

from __future__ import annotations

import json
import shutil

import pytest
from api_helpers import ROOT, WEB_FIXTURES, WORK, make_settings

B13_FIXTURES = ROOT / "data" / "fixtures" / "brief13"
pytestmark = pytest.mark.skipif(not (B13_FIXTURES / "metrics-maiduguri-60.json").exists(),
                                reason="brief 13 fixtures not written")


@pytest.fixture()
def b13_client(tmp_path):
    from fastapi.testclient import TestClient

    from api.main import create_app

    root = tmp_path / "fixtures"
    shutil.copytree(WEB_FIXTURES, root / "web")
    shutil.copytree(B13_FIXTURES, root / "brief13")
    (root / "agents").mkdir()
    with TestClient(create_app(make_settings(fixtures=root, work=tmp_path / "no-work"))) as c:
        yield c


def test_metrics_follow_the_contract(b13_client):
    for d in (14, 40, 60):
        r = b13_client.get("/api/city/maiduguri/metrics", params={"days": d})
        assert r.status_code == 200
        j = r.json()
        assert j["city"] == "maiduguri" and j["days"] == d
        i = j["impact"]
        for k in ("csh_needed", "csh_today", "csh_today_diesel", "csh_with", "by_sector", "diesel_l_avoided",
                  "diesel_ngn_avoided", "water_m3_per_day_kept", "people_served"):
            assert k in i, k
        assert set(i["by_sector"]) == {"health", "water", "cold"}
        assert set(i["diesel_l_avoided"]) == {"point", "lo", "hi"}
        n = j["innovation"]
        assert n["new_line_km"] == 0 and {"km_330", "towers"} <= set(n["corridor"]) and "local_share" in n
        s = j["sustainability"]
        assert {"solar", "diesel", "gas_support"} <= set(s["cost_per_kwh_ngn"])
        assert "gas_breakeven_mwh_per_month" in s and "co2_t_avoided" in s and s["ownership"]
        assert set(j["feasibility"]["roof_fit"]) == {"fits", "partial", "ground", "unknown"}
        assert {"outage_ready_7d", "daily_cycle"} <= set(s["cost_arms"])
        assert s["gas_tariff_cost_reflective"]["usc_per_kwh"] == 15.88 and "gas_tariff_cost_reflective" in s[
            "cost_per_kwh_ngn"]
        assert "alongside" in j["headline_alongside"]
        assert j["labels"] and j["sources"]
        assert "ASSUMPTION" in json.dumps(j["labels"]) and chr(0x2014) not in r.text


def test_metrics_default_and_errors(b13_client):
    assert b13_client.get("/api/city/maiduguri/metrics").json()["days"] == 60
    assert b13_client.get("/api/city/maiduguri/metrics", params={"days": 5}).status_code == 422
    assert b13_client.get("/api/city/lagos/metrics").status_code == 404
    for c in ("damaturu", "yola"):
        assert b13_client.get(f"/api/city/{c}/metrics", params={"days": 40}).json()["city"] == c


def test_sites_geojson_and_siting_card(b13_client):
    g = b13_client.get("/api/city/maiduguri/sites").json()
    assert g["type"] == "FeatureCollection" and g["features"]
    secs = {f["properties"]["sector"] for f in g["features"]}
    assert secs == {"health", "water", "cold"}
    umth = [f for f in g["features"] if f["properties"]["existing_onsite"]]
    assert umth and all(not f["properties"]["in_plan"] for f in umth)
    sid = next(f["properties"]["id"] for f in g["features"] if f["properties"]["sector"] == "water")
    card = b13_client.get(f"/api/sites/{sid}/siting").json()
    assert card["id"] == sid and card["new_line_km"] == 0 and card["roof"]["fit"] in ("fits", "partial", "ground", "unknown")
    assert card["city"] == "maiduguri" and card["security"] and card["ownership"]["sector"] == "water"
    assert card["roof"]["fit"] in ("fits", "partial", "ground", "unknown") and "rule" in card["roof"]
    assert b13_client.get("/api/sites/NOPE/siting").status_code == 404
    assert b13_client.get("/api/sites/..%2Fx/siting").status_code == 404


def test_corridor_is_small_geojson(b13_client):
    r = b13_client.get("/api/corridor")
    assert r.status_code == 200 and len(r.content) < 1_000_000
    j = r.json()
    assert j["type"] == "FeatureCollection" and j["properties"]["stats"]["towers"] == 2707


@pytest.mark.skipif(not (WORK / "brief13" / "meta.json").exists(), reason="live brief 13 build not present")
def test_live_build_is_read():
    from api.brief13_api import Brief13Files

    f = Brief13Files(WORK / "brief13")
    assert json.loads(f.metrics("maiduguri", 60))["days"] == 60
    assert f.days_available("maiduguri") == [7, 14, 40, 60]
    assert f.siting(next(iter(f._siting("yola"))))["city"] == "yola"


def test_site_trace_from_fixtures(b13_client):
    names = sorted(p.name for p in B13_FIXTURES.glob("trace-*-14.json"))
    assert names, "fixtures carry precomputed traces"
    for n in names:
        sid = n[len("trace-"):-len("-14.json")]
        j = b13_client.get(f"/api/sites/{sid}/outage_trace", params={"days": 14}).json()
        assert sum(j["in_outage"]) == 14 * 24 and len(j["hour"]) == len(j["grid_on"])
    assert b13_client.get(f"/api/sites/{sid}/outage_trace", params={"days": 5}).status_code == 422
    g = b13_client.get("/api/city/maiduguri/sites").json()
    other = next(f["properties"]["id"] for f in g["features"] if f["properties"]["sector"] == "water"
                 and not (B13_FIXTURES / f"trace-{f['properties']['id']}-14.json").exists())
    assert b13_client.get(f"/api/sites/{other}/outage_trace", params={"days": 14}).status_code == 404


def test_metrics_carry_version_status_and_source_urls(b13_client):
    j = b13_client.get("/api/city/maiduguri/metrics", params={"days": 60}).json()
    assert j["data_version"] and j["label_status"]["cost_solar"] == "DERIVED"
    assert all({"text", "url", "status"} <= set(s) for s in j["sources"])
    assert any(s["url"] for s in j["sources"])


def _features(path):
    return {f["properties"]["id"]: f["properties"] for f in json.loads(path.read_text())["features"]}


def _matches(t, p, d):
    assert t["system"]["pv_kwp"] == pytest.approx(p["system"]["pv_kwp"], abs=1e-3)
    assert t["system"]["battery_kwh"] == pytest.approx(p["system"]["battery_kwh"], abs=1e-2)
    assert t["hours_kept_median"] == pytest.approx(p["results"][str(d)]["with_h"], abs=0.05)


def test_fixture_traces_run_the_plans_system(b13_client):
    feats = _features(B13_FIXTURES / "sites-maiduguri.geojson")
    names = sorted(B13_FIXTURES.glob("trace-*.json"))
    assert any("-H-" in n.name for n in names)
    for n in names:
        t = json.loads(n.read_text())
        _matches(t, feats[t["site_id"]], t["days"])


@pytest.mark.skipif(not (WORK / "brief13" / "sites-maiduguri.geojson").exists(), reason="live brief 13 build absent")
def test_live_health_traces_match_the_site_features(live_client):
    feats = _features(WORK / "brief13" / "sites-maiduguri.geojson")
    health = sorted(k for k, p in feats.items() if p["sector"] == "health" and p["in_plan"])
    sample = sorted({"H-SN_0B1D15D01C", "H-SN_33083DA99E", *health[::40]} & set(health))
    for sid in sample:
        t = live_client.get(f"/api/sites/{sid}/outage_trace", params={"days": 14}).json()
        assert t["sector"] == "health" and t["facility_id"] == sid[2:]
        _matches(t, feats[sid], 14)
        assert t["pv_kwp"] == pytest.approx(feats[sid]["system"]["pv_kwp"], abs=1e-3)
    umth = next(k for k, p in feats.items() if p["existing_onsite"])
    assert live_client.get(f"/api/sites/{umth}/outage_trace", params={"days": 14}).status_code == 422
