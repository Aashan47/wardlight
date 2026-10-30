"""API test fixtures. Fixture-mode apps need only data/fixtures/web; live-mode tests skip without data/work."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # build/wardlight
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from api_helpers import HAS_WORK, WEB_FIXTURES, make_settings, planner_events, recording


@pytest.fixture()
def fixture_root(tmp_path) -> Path:
    """A fixtures root: a copy of data/fixtures/web plus test agent recordings."""
    root = tmp_path / "fixtures"
    shutil.copytree(WEB_FIXTURES, root / "web")
    ag = root / "agents"
    ag.mkdir()
    q = "I have N80 million for Kano this year. Protect the most vaccine doses."
    (ag / "planner_test.json").write_text(json.dumps(recording(planner_events(q), "planner_session",
                                                               output={"question": q})))
    ev = planner_events("")
    ev[2]["name"], ev[3]["summary"] = "ask", "asked"
    (ag / "verifier_test.json").write_text(json.dumps(recording(ev, "verifier_session",
                                                                facility={"unique_id": "WL-0002"})))
    (ag / "watcher_test.json").write_text(json.dumps(recording(planner_events("", (0, 0, 0, 0, 0)), "watcher_run")))
    (ag / "not_a_recording.json").write_text("[1, 2, 3]")
    return root


@pytest.fixture()
def fx_client(fixture_root, tmp_path):
    from fastapi.testclient import TestClient

    from api.main import create_app

    s = make_settings(fixtures=fixture_root, work=tmp_path / "no-work-here")
    with TestClient(create_app(s)) as c:
        yield c


@pytest.fixture(scope="session")
def live_client():
    if not HAS_WORK:
        pytest.skip("data/work is not built (never committed); live tests run where it exists")
    from fastapi.testclient import TestClient

    from api.main import create_app

    s = make_settings(fixture=False)
    with TestClient(create_app(s)) as c:
        yield c
