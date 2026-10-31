"""The on-disk store: built once per data version, the gzipped list served as a file, full rows from SQLite."""

from __future__ import annotations

import gzip
import json

from api_helpers import WORK


def test_list_is_served_gzipped_from_disk(live_client):
    raw = live_client.get("/api/facilities", headers={"Accept-Encoding": "gzip"})
    assert raw.status_code == 200
    items = raw.json()  # httpx decodes Content-Encoding: gzip
    assert len(items) > 50_000 and raw.headers.get("content-encoding") == "gzip"
    plain = live_client.get("/api/facilities", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.json() == items


def test_store_files_and_rows(live_client):
    from api import store_build as SB

    store = live_client.app.state.store
    p = store.files
    assert p["version"] == SB.data_version(WORK) == store.data_version
    meta = json.loads(p["meta"].read_text())
    assert meta["rows"] == len(store.t) and meta["summary"]["headline_metric"]["brief"] == 13
    with gzip.open(p["list"], "rt") as f:
        assert len(json.load(f)) == len(store.t)
    row = store._row(0)
    assert row["unique_id"] == store.t.unique_id.iloc[0] and "m_evidence" in row
    assert "m_evidence" not in store.t.columns  # the JSON text stays on disk
    same = [f for f in p["meta"].parent.glob("meta-*.json")]
    assert same == [p["meta"]]  # older versions are removed


def test_core_keeps_ranking_columns_exact(live_client):
    import numpy as np

    t = live_client.app.state.store.t
    for c in ("capex_ngn", "clinic_capex_ngn", "uptime_today", "doses_with_system", "out7_hours_with"):
        assert t[c].dtype == np.float64, c


def test_agent_toolbox_shares_the_store(live_client):
    """Live agent runs read the API's store: same core frame, full rows from disk, one data version."""
    app = live_client.app
    tb = app.state.hub.toolbox()
    store = app.state.store
    assert tb.data._store is store and tb.data.version == store.data_version
    assert tb.data.facilities.shape[0] == len(store.t)
    uid = store.t[store.t.has_result].unique_id.iloc[0]
    r = tb.data.row(uid)
    assert r["unique_id"] == uid and "match_evidence" in r.index and "system_fridge" in r.index
    t = tb.data.table
    assert "match_tier" in t and "match_evidence" not in t  # JSON stays on disk until a tool returns the row
    from agents.tools import Session

    out = tb.call("rank_budget", {"state": "Kano", "budget": 8e7, "currency": "NGN", "priority": "doses", "top": 3},
                  Session())
    assert "error" not in out and out["funded_top"][0]["fix_label"] and out["funded_top"][0]["cite"]
