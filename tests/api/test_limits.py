"""Rate limits per visitor, request size limit, and the input-hash cache."""

from __future__ import annotations

from api_helpers import make_settings
from fastapi.testclient import TestClient

from api.limits import Cache, RateLimiter, input_hash
from api.main import create_app


def test_rate_limit_per_visitor_uses_cf_header(fixture_root):
    c = TestClient(create_app(make_settings(fixtures=fixture_root, rate_read=3)))
    a = {"CF-Connecting-IP": "203.0.113.1"}
    b = {"CF-Connecting-IP": "203.0.113.2"}
    assert [c.get("/api/summary", headers=a).status_code for _ in range(3)] == [200] * 3
    r = c.get("/api/summary", headers=a)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert c.get("/api/summary", headers=b).status_code == 200  # another visitor is not affected


def test_rate_limit_falls_back_to_client_host(fixture_root):
    c = TestClient(create_app(make_settings(fixtures=fixture_root, rate_simulate=2)))
    body = {"loads": ["fridge"], "pv_kwp": 0, "battery_kwh": 0, "target": 0.99, "fridge_mode": "shared"}
    codes = [c.post("/api/facilities/WL-0002/simulate", json=body).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_buckets_are_separate(fixture_root):
    c = TestClient(create_app(make_settings(fixtures=fixture_root, rate_agent=1)))
    assert c.get("/api/agent/watch", params={"speed": 0}).status_code == 202
    assert c.get("/api/agent/watch", params={"speed": 0}).status_code == 429
    assert c.get("/api/summary").status_code == 200


def test_body_size_limit(fixture_root):
    c = TestClient(create_app(make_settings(fixtures=fixture_root, max_body_bytes=200)))
    big = {"question": "x" * 500}
    assert c.post("/api/agent/plan", json=big).status_code == 413
    r = c.post("/api/ussd", content=b"sessionId=1&text=" + b"1" * 400,
               headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413


def test_cache_lru_and_hash():
    c = Cache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1
    c.put("c", 3)  # evicts b, the least recently used
    assert c.get("b") is None and c.get("a") == 1 and c.get("c") == 3
    assert c.hits == 3 and c.misses == 1
    assert input_hash({"x": 1, "y": [1, 2]}) == input_hash({"y": [1, 2], "x": 1})
    assert input_hash({"x": 1}) != input_hash({"x": 2})


def test_rate_limiter_window():
    rl = RateLimiter({"read": 2}, window_s=0.05)
    rl.check("v", "read")
    rl.check("v", "read")
    import time

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        rl.check("v", "read")
    time.sleep(0.06)
    rl.check("v", "read")  # the window has moved on
