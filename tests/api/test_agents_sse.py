"""Agent runs as Server-Sent Events: start, stream, replay with original timings, resume, cap and fallbacks."""

from __future__ import annotations

import time

from api_helpers import make_settings, sse_events
from fastapi.testclient import TestClient

from api.agent_runs import AgentHub
from api.main import create_app

Q = "I have N80 million for Kano this year. Protect the most vaccine doses."


def stream(c, run_id, **kw):
    with c.stream("GET", f"/api/agent/runs/{run_id}/events", **kw) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        return sse_events("".join(r.iter_text()))


def test_plan_start_then_stream_recorded(fx_client):
    r = fx_client.post("/api/agent/plan", params={"speed": 0}, json={"question": Q})
    assert r.status_code == 202
    info = r.json()
    assert info["recorded"] is True and info["mode"] == "recorded" and info["recording"] == "planner_test"
    assert info["events_url"] == f"/api/agent/runs/{info['run_id']}/events"
    evs = stream(fx_client, info["run_id"])
    assert [e["event"] for e in evs] == ["plan", "step_start", "tool_call", "tool_result", "done"]
    assert [int(e["id"]) for e in evs] == [0, 1, 2, 3, 4]
    assert all(e["data"]["type"] == e["event"] for e in evs)
    assert evs[-1]["data"]["recorded"] is True  # set on replay even though the recording said false
    assert evs[2]["data"]["args"] == {"state": "Edo"}  # passed through unchanged


def test_replay_keeps_original_timings(fx_client):
    t0 = time.perf_counter()
    r = fx_client.post("/api/agent/plan", params={"stream": True, "speed": 1}, json={"question": Q})
    elapsed = time.perf_counter() - t0
    evs = sse_events(r.text)
    assert len(evs) == 5 and r.headers["x-recorded"] == "true"
    assert elapsed >= 0.33  # the recording spans 360 ms
    t0 = time.perf_counter()
    fx_client.post("/api/agent/plan", params={"stream": True, "speed": 0}, json={"question": Q})
    assert time.perf_counter() - t0 < 0.33


def test_resume_with_last_event_id(fx_client):
    rid = fx_client.post("/api/agent/plan", params={"speed": 0}, json={"question": Q}).json()["run_id"]
    stream(fx_client, rid)
    evs = stream(fx_client, rid, headers={"Last-Event-ID": "2"})
    assert [int(e["id"]) for e in evs] == [3, 4]
    assert [int(e["id"]) for e in stream(fx_client, rid, params={"from": 4})] == [4]
    j = fx_client.get(f"/api/agent/runs/{rid}").json()
    assert j["done"] is True and len(j["events"]) == 5 and j["recorded"] is True


def test_unmatched_question_in_fixture_mode_is_an_error_not_a_wrong_recording(fx_client):
    r = fx_client.post("/api/agent/plan", params={"stream": True, "speed": 0}, json={"question": "Plan for Oyo"})
    evs = sse_events(r.text)
    assert [e["event"] for e in evs] == ["error", "done"]
    assert evs[-1]["data"]["recorded"] is False and evs[-1]["data"]["model"] == "none"


def test_named_recording_and_listing(fx_client):
    recs = fx_client.get("/api/agent/recordings").json()
    assert recs["recorded"] is True
    assert {r["name"] for r in recs["recordings"]} == {"planner_test", "verifier_test", "watcher_test"}
    r = fx_client.post("/api/agent/plan", params={"speed": 0}, json={"recording": "planner_test"})
    assert r.json()["recording"] == "planner_test"


def test_verify_and_watch(fx_client):
    v = fx_client.post("/api/agent/verify/WL-0002", params={"speed": 0}, json={"replies": ["3", "9"]}).json()
    assert v["agent"] == "verifier" and v["recorded"] is True
    assert stream(fx_client, v["run_id"])[-1]["data"]["recorded"] is True
    assert fx_client.post("/api/agent/verify/WL-0002", json={"replies": ["x" * 161]}).status_code == 422
    w = fx_client.get("/api/agent/watch", params={"speed": 0})
    assert w.status_code == 202 and w.json()["agent"] == "watcher" and w.json()["recorded"] is True
    assert fx_client.get("/api/agent/watch", params={"old": "Sept"}).status_code == 422


def test_question_required(fx_client):
    assert fx_client.post("/api/agent/plan", json={"question": "  "}).status_code == 422
    assert fx_client.get("/api/agent/runs/nope/events").status_code == 404


def test_daily_cap_counts_runs_and_falls_back_to_recording(fixture_root):
    hub = AgentHub(make_settings(fixtures=fixture_root, agent_daily_cap=1), fixture=False)
    calls = []

    def producer(agent, inputs):
        def gen():
            calls.append(agent)
            yield {"type": "plan", "seq": 0, "t_ms": 0, "steps": []}
            yield {"type": "done", "seq": 1, "t_ms": 1, "model": "fake", "tokens": 0, "cost_usd": 0.0,
                   "recorded": False, "duration_ms": 1}
        return gen, "scripted", None

    hub._producer = producer
    r1 = hub.start("planner", {"question": Q}, speed=0)
    assert r1.mode == "scripted" and r1.meta["cap"]["used"] == 1
    r2 = hub.start("planner", {"question": Q}, speed=0)
    assert r2.mode == "recorded" and r2.meta["cap_reached"] is True and r2.recorded
    r3 = hub.start("planner", {"question": "something never recorded"}, speed=0)
    assert r3.mode == "unavailable" and r3.meta["cap_reached"] is True
    for r in (r1, r2, r3):
        r.wait(10**6, 2.0)
    assert r1.events[-1]["recorded"] is False and r2.events[-1]["recorded"] is True
    assert [e["type"] for e in r3.events] == ["error", "done"]
    assert calls == ["planner"]
    assert hub.cap()["remaining"] == 0


def test_generator_exception_becomes_error_event(fixture_root):
    hub = AgentHub(make_settings(fixtures=fixture_root), fixture=False)

    def producer(agent, inputs):
        def gen():
            yield {"type": "plan", "seq": 0, "t_ms": 0, "steps": []}
            raise RuntimeError("tool exploded")
        return gen, "scripted", None

    hub._producer = producer
    r = hub.start("planner", {"question": "x"}, speed=0)
    r.wait(10**6, 2.0)
    time.sleep(0.05)
    assert [e["type"] for e in r.events] == ["plan", "error", "done"]
    assert "tool exploded" in r.events[1]["message"] and r.events[2]["seq"] == 2


def test_cap_endpoint(fixture_root):
    c = TestClient(create_app(make_settings(fixtures=fixture_root, agent_daily_cap=7)))
    j = c.get("/api/agent/cap").json()
    assert j["limit"] == 7 and j["used"] == 0 and j["recorded"] is False


def test_agent_f_recordings_replay_valid(tmp_path):
    """Agent F's committed recordings (data/fixtures/agents) replay through the SSE route, valid by F's own checker."""
    import pytest
    from api_helpers import ROOT

    rec_dir = ROOT / "data" / "fixtures" / "agents"
    if not any(rec_dir.glob("*.json")):
        pytest.skip("no recordings in data/fixtures/agents yet")
    from agents import events as EV

    c = TestClient(create_app(make_settings(fixtures=ROOT / "data" / "fixtures")))
    recs = c.get("/api/agent/recordings").json()["recordings"]
    assert recs
    for r in recs:
        path = {"planner": "/api/agent/plan", "verifier": f"/api/agent/verify/{r['facility_id'] or 'x'}",
                "watcher": "/api/agent/watch"}[r["agent"]]
        body = {"recording": r["name"]}
        resp = (c.get(path, params={"recording": r["name"], "stream": True, "speed": 0}) if r["agent"] == "watcher"
                else c.post(path, params={"stream": True, "speed": 0}, json=body))
        data = [e["data"] for e in sse_events(resp.text)]
        assert len(data) == r["n_events"], r["name"]
        assert EV.validate(data) == [], r["name"]
        assert data[-1]["recorded"] is True
