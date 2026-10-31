"""Brief 13 agent routes: the city plan (JSON, CSV), the site verifier and the line watcher, in fixture mode."""

import csv
import io

from api_helpers import ROOT, make_settings, sse_events
from fastapi.testclient import TestClient

from api.main import create_app


def client():
    return TestClient(create_app(make_settings(fixtures=ROOT / "data" / "fixtures")))


def test_city_plan_json_and_csv():
    c = client()
    j = c.get("/api/city/maiduguri/plan", params={"budget_ngn": 2e9, "days": 60}).json()
    t = j["totals"]
    assert t["spent_ngn"] <= 2e9 and t["funded_count"] == len(j["funded"]) > 0
    assert j["data_version"] and j["sectors"] == ["health", "water", "cold"]
    r = c.get("/api/city/maiduguri/plan.csv", params={"budget_ngn": 1e9, "days": 14, "sectors": "water,cold"})
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert {x["sector"] for x in rows} == {"water", "cold"} and rows[0]["funded"] == "yes"
    assert c.get("/api/city/kano/plan").status_code == 404
    assert c.get("/api/city/maiduguri/plan", params={"days": 5}).status_code == 422
    assert c.get("/api/city/maiduguri/plan", params={"sectors": "roads"}).status_code == 422


def test_site_verifier_and_line_watcher_replay():
    c = client()
    r = c.post("/api/agent/verify-site/W-BH-589", params={"stream": True, "speed": 0}, json={})
    evs = [e["data"] for e in sse_events(r.text)]
    assert evs[-1]["type"] == "done" and evs[-1]["recorded"] is True
    assert any(e["type"] == "tool_call" and e["name"] == "ask_site" for e in evs)
    assert c.post("/api/agent/verify-site/NOPE", json={}).status_code == 404
    r = c.get("/api/agent/watch-line", params={"stream": True, "speed": 0})
    evs = [e["data"] for e in sse_events(r.text)]
    assert evs[-1]["recorded"] is True and any(e.get("name") == "replan_run_order" for e in evs)
    recs = c.get("/api/agent/recordings").json()["recordings"]
    assert {r["agent"] for r in recs} == {"planner", "verifier", "watcher"} and all(r["brief"] == 13 for r in recs)
