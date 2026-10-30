"""End-to-end check items: headline and ring agree; one data version; feeder served_summary; investment brief."""

from __future__ import annotations

import csv
import io
import random

import pytest
from api_helpers import ROOT, WORK

AUCHI = "v2_5003bc8a-c878-4c32-b59d-7cd6c7aeeb13"  # Auchi General Hospital, the case the check found


def _night_held(trace) -> bool:
    return all(x is True for x in trace["rooms"]["fridge"])


def _sample_ids(live_client, n=12, seed=20261030):
    import pandas as pd

    r = pd.read_parquet(WORK / "facility_results.parquet", columns=["unique_id", "uptime_today"])
    r = r[r.uptime_today.notna()]
    ids = random.Random(seed).sample(sorted(r.unique_id), n)
    # make sure both sides of one half are covered when the data has them
    hi = r[r.uptime_today >= 0.5].unique_id
    if len(hi):
        ids.append(min(hi))
    return ids


def test_headline_and_ring_cannot_contradict(live_client):
    ids = _sample_ids(live_client)
    if live_client.get(f"/api/facilities/{AUCHI}").status_code == 200:
        ids.append(AUCHI)
    for fid in ids:
        rec = live_client.get(f"/api/facilities/{fid}").json()
        if rec.get("refused") or not rec.get("trace"):
            continue
        head = rec["brief_metric"]["uptime_today"]["p"]
        tr = rec["trace"]
        d = tr["draw"]
        assert tr["scenario"] == "domestic" and tr["fridge_mode"] == "shared", fid
        assert d["scenario"].startswith("domestic") and d["headline_uptime"] == pytest.approx(head)
        assert {"lane", "n_lanes", "night_index", "rule", "window_grid_hours"} <= set(d)
        if d.get("state_matched", True):
            assert _night_held(tr) == (head >= 0.5), (fid, head)
        # the night is a typical one for its draw: its grid hours are the draw's median where the state allows
        assert sum(tr["grid_on"]) == d["window_grid_hours"]


def test_auchi_shows_a_failing_night(live_client):
    r = live_client.get(f"/api/facilities/{AUCHI}")
    if r.status_code != 200:
        pytest.skip("Auchi General Hospital is not in this build")
    rec = r.json()
    assert rec["brief_metric"]["uptime_today"]["p"] < 0.5
    assert not _night_held(rec["trace"]) and not all(rec["trace"]["grid_on"])


def test_whatif_ring_follows_its_own_figure(live_client):
    body = {"loads": ["fridge", "delivery", "oxygen", "lab", "ward"], "pv_kwp": 1.0, "battery_kwh": 7.2,
            "target": 0.99}
    for mode in ("shared", "pqs_sdd"):
        out = live_client.post(f"/api/facilities/{AUCHI}/simulate", json={**body, "fridge_mode": mode}).json()
        tr, d = out["trace"], out["trace"]["draw"]
        assert tr["scenario"] == ("domestic" if mode == "shared" else "pqs_sdd")
        assert d["run_median_uptime"] == pytest.approx(out["fridge_days"]["p"])
        if d["state_matched"]:
            assert _night_held(tr) == (out["fridge_days"]["p"] >= 0.5)


def test_one_data_version_everywhere(live_client):
    from agents.tools import WardlightData

    v = live_client.get("/api/health").json()["data_version"]
    assert v == WardlightData(work_dir=WORK).version
    assert live_client.get("/api/facilities/" + AUCHI).json()["data_version"] == v
    assert live_client.get("/api/plan/brief", params={"state": "Edo", "budget_ngn": 1e7}).json()["data_version"] == v


def test_feeder_served_summary(live_client):
    rec = live_client.get(f"/api/facilities/{AUCHI}").json()
    f = live_client.get(f"/api/feeders/{rec['match']['feeder_id']}").json()
    s = f["served_summary"]
    assert s["facilities"] == len(f["facilities"]) == sum(s["by_tier"].values()) == sum(s["by_level"].values())
    assert 0 <= s["hospitals"] <= s["facilities"] and 0 <= s["phcs"] <= s["facilities"]
    assert s["doses_year"] >= 0 and "ESTIMATE" in s["doses_note"]
    assert s["promised_hours"] == f["min_hours"]


def test_served_summary_gap_from_the_shortfall_table(live_client):
    import re

    import pandas as pd

    sf = pd.read_parquet(WORK / "nerc_shortfalls.parquet")
    rows = pd.read_parquet(WORK / "nerc_rows.parquet")

    def norm(x):
        return re.sub(r"[^A-Z0-9]", "", str(x).upper())

    rows["k"] = [(d, norm(n)) for d, n in zip(rows.disco, rows.feeder_name)]
    hit = None
    for x in sf.itertuples():
        m = rows[rows.k == (x.disco, norm(x.feeder_name))]
        if len(m) and pd.notna(x.measured_avg_hours):
            hit = (m.iloc[0], x)
            break
    if hit is None:
        pytest.skip("no shortfall row names a feeder row exactly")
    row, x = hit
    slug = f"{row.order_file.removesuffix('.pdf')}-p{int(row.page)}-sn{int(row.sn)}"
    s = live_client.get(f"/api/feeders/{slug}").json()["served_summary"]
    m = next(m for m in s["measured"] if m["measured_avg_hours"] == pytest.approx(x.measured_avg_hours))
    assert m["gap_hours"] == pytest.approx(row.min_hours - x.measured_avg_hours, abs=0.01)


@pytest.mark.parametrize("metric", ["doses", "load_hours"])
def test_investment_brief(live_client, metric):
    budget = 8e7
    b = live_client.get("/api/plan/brief", params={"state": "Kano", "budget_ngn": budget, "metric": metric}).json()
    assert b["kind"] == "investment_brief" and b["metric"] == metric and b["state"] == "Kano"
    rows = b["funded"]
    assert rows and b["totals"]["funded"] == len(rows)
    assert sum(r["cost_ngn"] for r in rows) == pytest.approx(b["totals"]["spent_ngn"])
    assert b["totals"]["spent_ngn"] <= budget
    assert [r["rank"] for r in rows] == sorted(r["rank"] for r in rows)
    for r in rows:
        assert r["fix"] in ("pqs_icelined", "pqs_sdd", "solar_clinic") and r["cost_ngn"] > 0
        assert r["citation"]["text"]
        if r["citation"]["kind"] == "nerc_row":
            assert r["citation"]["file"] and r["citation"]["page"] is not None
    groups = {g["group"] for g in b["not_reached"]}
    assert {"ranked, over budget", "supply unknown (refused match)", "no engine result"} <= groups
    assert b["sources"] and b["assumptions"] and all(a["status"] in ("ASSUMPTION", "UNVERIFIED")
                                                     for a in b["assumptions"])
    assert any(s["headline"] for s in b["scenarios"])
    if metric == "load_hours":
        assert rows[0]["clinic_system"]["pv_kwp"] > 0


def test_brief_matches_the_planner_ranking(live_client):
    """The brief and /api/plan are the same engine.plan.rank call."""
    b = live_client.get("/api/plan/brief", params={"state": "Edo", "budget_ngn": 5e7}).json()
    p = live_client.get("/api/plan", params={"state": "Edo", "budget_ngn": 5e7}).json()
    funded = [r["id"] for r in p["ranked"] if r["funded"]]
    assert [r["id"] for r in b["funded"]] == funded


def test_brief_csv(live_client):
    params = {"state": "Kano", "budget_ngn": 8e7}
    j = live_client.get("/api/plan/brief", params=params).json()
    for r in (live_client.get("/api/plan/brief.csv", params=params),
              live_client.get("/api/plan/brief", params={**params, "format": "csv"})):
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        table = list(csv.DictReader(io.StringIO(r.text)))
        assert len(table) == len(j["funded"])
        assert table[0]["id"] == j["funded"][0]["id"] and table[0]["citation"]
        assert table[0]["data_version"] == j["data_version"]


def test_brief_validation(live_client):
    assert live_client.get("/api/plan/brief", params={"metric": "votes"}).status_code == 422
    assert live_client.get("/api/plan/brief", params={"state": "Atlantis"}).status_code == 404


def test_brief_in_fixture_mode(fx_client):
    b = fx_client.get("/api/plan/brief", params={"state": "Edo"}).json()
    assert b["sample"] is True and b["funded"]
    r = fx_client.get("/api/plan/brief.csv", params={"state": "Edo"})
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == len(b["funded"]) and rows[0]["sample"] == "yes"


def test_root_paths_exist():
    assert (ROOT / "api" / "main.py").exists()


def test_new_payloads_match_web_types(live_client):
    from api_helpers import missing_required

    b = live_client.get("/api/plan/brief", params={"state": "Kano", "budget_ngn": 8e7}).json()
    assert not missing_required(b, "Brief")
    assert not missing_required(b["funded"][0], "BriefRow")
    rec = live_client.get(f"/api/facilities/{AUCHI}").json()
    assert not missing_required(rec["trace"]["draw"], "TraceDraw")
    f = live_client.get(f"/api/feeders/{rec['match']['feeder_id']}").json()
    assert not missing_required(f["served_summary"], "ServedSummary")
