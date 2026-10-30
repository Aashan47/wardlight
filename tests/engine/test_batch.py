import json

from engine import batch as B
from engine import paths
from engine import supply as SP

from .conftest import needs_grid3

CONTRACT = ["unique_id", "uptime_today", "uptime_today_lo", "uptime_today_hi", "doses_protected_today",
            "system_fridge", "system_clinic", "uptime_with_system", "doses_with_system", "capex_usd", "capex_ngn",
            "monthly_cost_ngn", "diesel_l_avoided", "co2_kg_avoided", "payback_months", "priority_score"]


def test_bands_for_is_generic_over_tier_names():
    assert B.bands_for("d_refused", '{"A": 1}') is None
    assert B.bands_for("offgrid", "{}") == SP.OFFGRID
    assert B.bands_for("c_lga_mixture", '{"A": 0.5, "C": 0.5}') == {"A": 0.5, "C": 0.5}
    assert B.bands_for("some_new_tier", '{"?": 1.0, "B": 1.0}') == {"B": 1.0}
    assert B.bands_for("b_place", '{"?": 1.0}') is None


def test_key_is_canonical():
    assert B._key((9, 7), {"B": 0.5, "A": 0.5}) == B._key((9, 7), {"A": 0.5, "B": 0.5})
    assert B._key((9, 7), None).endswith("UNKNOWN")


@needs_grid3
def test_synthetic_run_writes_contract(tmp_path, monkeypatch):
    for name in ("WORK", "MATCHES", "MATCHES_SYNTHETIC", "CATCHMENTS", "NERC_SHORTFALLS"):
        monkeypatch.setattr(paths, name, tmp_path / getattr(paths, name).name if name != "WORK" else tmp_path)
    fac = B.load_facilities()
    m = B.make_synthetic_matches(fac, n=6)
    assert m.synthetic.all() and m.reason.str.startswith("SYNTHETIC").all()
    m.to_parquet(tmp_path / "m.parquet")
    res, meta = B.run(tmp_path / "m.parquet", n_draws=4, shortfall=SP.PRIOR)
    assert meta["input_synthetic"] and res.input_synthetic.all()
    for c in CONTRACT:
        assert c in res.columns, c
    assert json.loads(res.system_fridge.iloc[0])["kind"].startswith("PQS solar direct drive")
    assert res.doses_per_year.isna().all()  # no catchments in the temp work dir
    assert "capped" in res and "doses_demand_uncapped" in res and meta["facilities_capped"] == 0
    refused = res[res.tier == "d_refused"]
    assert refused.uptime_today.isna().all()
