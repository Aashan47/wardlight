import numpy as np
import pandas as pd

from engine import plan as PL


def _df():
    return pd.DataFrame({
        "unique_id": ["a", "b", "c", "d"], "tier": ["b_place", "offgrid", "c_unit_mixture", "d_refused"],
        "doses_with_system": [1000.0, 1000, 500, 800], "doses_protected_today": [900.0, 0, 0, np.nan],
        "uptime_today": [0.9, 0, 0, np.nan], "uptime_with_system": [1.0, 1, 1, 1],
        "crit_uptime_today": [0.5, 0, 0, np.nan], "crit_uptime_with": [1.0, 1, 1, 1],
        "capex_ngn": [1e6, 2e6, 1e6, 1e6]})


def test_greedy_under_budget_and_unknown_not_ranked():
    r = PL.rank(_df(), budget_ngn=3e6)
    ranked = r[r["rank"].notna()]
    # 500, 500 and 100 doses per N1m; b and c tie, same uptime today, so the lower cost (c) goes first
    assert ranked.unique_id.tolist() == ["c", "b", "a"]
    assert ranked.funded.tolist() == [True, True, False]
    d = r[r.unique_id == "d"].iloc[0]
    assert not d.funded and "unknown" in d.reason
    s = PL.summary(r)
    assert s["funded"] == 2 and s["spent_ngn"] == 3e6 and s["not_ranked_unknown_supply"] == 1


def test_load_hours_metric():
    r = PL.rank(_df(), budget_ngn=10e6, metric="load_hours")
    a = r[r.unique_id == "a"].iloc[0]
    assert a.benefit == 0.5 * 365 * PL.CRITICAL_LOAD_HOURS_PER_DAY
    assert "load-hours" in a.reason


def test_ties_break_by_uncapped_demand_then_today_then_cost_then_id():
    base = {"tier": "b_place", "doses_with_system": 1000.0, "doses_protected_today": 0.0, "uptime_today": 0.0,
            "uptime_with_system": 1.0, "crit_uptime_today": 0.0, "crit_uptime_with": 1.0, "capex_ngn": 1e6}
    rows = [
        {**base, "unique_id": "z", "doses_demand_uncapped": 5000.0},
        {**base, "unique_id": "y", "doses_demand_uncapped": 9000.0},
        {**base, "unique_id": "x", "doses_demand_uncapped": 5000.0, "uptime_today": 0.0},
        {**base, "unique_id": "w", "doses_demand_uncapped": 5000.0, "uptime_today": 0.5,
         "doses_protected_today": 0.0},
    ]
    r = PL.rank(pd.DataFrame(rows), budget_ngn=10e6)
    assert r.unique_id.tolist() == ["y", "x", "z", "w"]
    assert r.equals(PL.rank(pd.DataFrame(rows[::-1]), budget_ngn=10e6))
