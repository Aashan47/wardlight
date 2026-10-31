import numpy as np
import pandas as pd
import pytest

from engine import loads as LD
from engine import outage as O
from engine import plan as PL
from engine import sim as SM

from .conftest import needs_nasa

CFG = SM.SimConfig(n_draws=8)
CRIT = LD.critical()
SMALL = SM.ClinicSystem(1.0, 7.2)


def test_window_mask_length_and_placement():
    m, start = O.window_mask(50, 8760, 7, seed=1)
    assert (m.sum(axis=1) == 168).all()
    assert (start >= 0).all() and (start <= 365 - 7).all()
    m0, _ = O.window_mask(5, 8760, 0, seed=1)
    assert not m0.any()
    mfull, _ = O.window_mask(2, 240, 30, seed=1)  # longer than the year: clipped to it
    assert mfull.all()


def test_window_is_deterministic_and_separate_from_main_draws():
    a, _ = O.window_mask(10, 8760, 3, seed=7)
    b, _ = O.window_mask(10, 8760, 3, seed=7)
    assert np.array_equal(a, b)


@needs_nasa
def test_zero_day_outage_equals_today():
    pp = SM.prepare(9, 7, "C", CFG)
    r = O.simulate_outage(pp, 0, CRIT, SMALL, "i", "E003-089e", CFG)
    assert r.window_h == 0 and r.needed_h == 0 and r.with_system.hi == 0 and r.today.hi == 0
    po = O.apply_outage(pp, O.window_mask(pp.n_lanes, pp.grid.shape[1] - SM.BURN_IN_H, 0, CFG.seed)[0])
    assert np.array_equal(po.grid, pp.grid)
    base = SM.simulate_facility(9, 7, "C", CRIT, SMALL, CFG, prepared=pp)
    again = SM.simulate_facility(9, 7, "C", CRIT, SMALL, CFG, prepared=po)
    assert base.fridge_today == again.fridge_today and base.critical_with == again.critical_with


@needs_nasa
def test_offgrid_site_is_unaffected_by_the_outage():
    pp = SM.prepare(9, 7, "OFFGRID", CFG)
    on = O.simulate_outage(pp, 7, CRIT, SMALL, "ii", "E003-040e", CFG, apply=True)
    off = O.simulate_outage(pp, 7, CRIT, SMALL, "ii", "E003-040e", CFG, apply=False)
    assert on.with_system == off.with_system and on.today == off.today


@needs_nasa
@pytest.mark.parametrize("band", ["A", "C", "E", "OFFGRID", None])
@pytest.mark.parametrize("days", [3, 7, 14])
def test_hours_never_exceed_the_window(band, days):
    pp = SM.prepare(9, 7, band, CFG)
    r = O.simulate_outage(pp, days, CRIT, SMALL, "ii", "E003-040e", CFG)
    assert r.window_h == days * 24
    for s in r.services:
        assert s.needed_h <= r.window_h
        assert s.today.hi <= s.needed_h and s.with_system.hi <= s.needed_h
    assert r.with_system.hi <= r.needed_h and 0 <= r.share_with <= 1


@needs_nasa
def test_outage_hurts_a_grid_site_and_solar_fridge_rides_it_out():
    pp = SM.prepare(9, 7, "A", CFG)
    hit = O.simulate_outage(pp, 7, CRIT, SMALL, "ii", "E003-040e", CFG, apply=True)
    base = O.simulate_outage(pp, 7, CRIT, SMALL, "ii", "E003-040e", CFG, apply=False)
    assert hit.today.point < base.today.point
    fridge = {s.key: s for s in hit.services}["vaccine_fridge"]
    assert fridge.with_system.lo == 168  # SDD does not need the grid
    assert fridge.today.hi <= 6  # domestic fridge holds at most 6 h without power


@needs_nasa
def test_ice_lined_fix_falls_back_on_holdover():
    pp = SM.prepare(9, 7, "FULL", CFG)
    r = O.simulate_outage(pp, 14, CRIT, SMALL, "i", "E003-089e", CFG)
    fridge = {s.key: s for s in r.services}["vaccine_fridge"]
    assert 20 < fridge.with_system.point < 100  # about the PQS holdover, then warm


@needs_nasa
def test_generator_and_diesel_ranges():
    pp = SM.prepare(9, 7, "OFFGRID", CFG)
    r = O.simulate_outage(pp, 7, CRIT, SM.ClinicSystem(10, 72), "ii", "E003-040e", CFG)
    kwh = 7 * LD.daily_kwh(CRIT) + 0.54 / 24 * 168
    assert r.generator_litres.lo == pytest.approx(0.40 * kwh) and r.generator_litres.hi == pytest.approx(0.73 * kwh)
    assert r.diesel_l_avoided.point == pytest.approx(r.generator_litres.point, rel=1e-6)  # everything covered


def test_columns_aggregate_and_rank():
    res = pd.DataFrame({
        "unique_id": ["a", "b", "c"], "out7_needed_h": [343.0] * 3, "out7_hours_today": [0.0, 0.0, 100.0],
        "out7_hours_with": [343.0, 200.0, 343.0], "out7_generator_litres": [14.0] * 3,
        "out7_diesel_l_avoided": [14.0, 8, 14], "out7_diesel_l_avoided_lo": [11.0] * 3,
        "out7_diesel_l_avoided_hi": [16.0] * 3, "capex_ngn": [1e6, 1e6, 1e6], "clinic_capex_ngn": [1e6, 1e6, 1e6],
        "uptime_today": [0.0, 0.0, 0.0], "uptime_with_system": [1.0] * 3})
    fac = pd.DataFrame({"unique_id": ["a", "b", "c"], "state_standard": ["S1", "S1", "S2"],
                        "lga_standard": ["L1", "L1", "L2"]})
    g = O.aggregate(res, fac, 7)
    s1 = g[g.lga_standard == "L1"].iloc[0]
    assert s1.facilities == 2 and s1.service_hours_with == 543 and s1.share_today == 0
    r = PL.rank(res, budget_ngn=4e6, metric="outage_hours", outage_days=7)
    assert r.unique_id.tolist() == ["a", "c", "b"] and r.funded.tolist() == [True, True, False]
    assert "7-day outage" in r.reason.iloc[0]


# ---- outage-ready fix, city view, T5-style check

@needs_nasa
def test_outage_ready_fix_meets_target_and_beats_the_normal_fix():
    pp = SM.prepare(9, 7, "C", CFG)
    o = O.size_outage_ready(pp, CRIT, offgrid=False, cfg=CFG)
    assert o.target_met and o.category == "ii+c" and o.crit_share.lo >= 0.95
    assert o.fridge_share_lo >= 0.95 and o.battery_kwh == pytest.approx(o.pv_kwp * 7.2)
    normal = O.simulate_outage(pp, 7, CRIT, SM.ClinicSystem(0.95, 6.84), "i", "E003-089e", CFG)
    assert o.result.with_system.point >= normal.with_system.point
    assert o.capex_ngn.point == pytest.approx(o.capex_usd.point * 1352.371)
    # the next smaller size on the curve misses the target: the choice is the smallest that passes
    smaller = [c for c in o.curve if c[0] < o.pv_kwp]
    assert all(c[2] < 0.95 for c in smaller)


@needs_nasa
def test_longer_outages_never_need_a_smaller_system():
    pp = SM.prepare(9, 7, "C", CFG)
    sizes = [O.size_outage_ready(pp, CRIT, False, CFG, days=d).pv_kwp for d in (3, 7, 14)]
    assert sizes == sorted(sizes)


@needs_nasa
def test_unreachable_outage_target_is_flagged():
    pp = SM.prepare(9, 7, "C", CFG)
    o = O.size_outage_ready(pp, CRIT, False, CFG, kwp_grid=[0.1, 0.2])
    assert not o.target_met and o.category == "none"


def test_orfix_columns_and_city_aggregation():
    res = pd.DataFrame({
        "unique_id": ["a", "b", "c"], "orfix_days": [7] * 3, "orfix_needed_h": [343.0] * 3,
        "out7_hours_today": [0.0, 10.0, 0.0], "orfix_hours_kept": [343.0, 300.0, 340.0],
        "orfix_diesel_l_avoided": [14.0] * 3, "orfix_diesel_l_avoided_lo": [11.0] * 3,
        "orfix_diesel_l_avoided_hi": [17.0] * 3, "orfix_capex_ngn": [2e7, 1e7, 2e7],
        "orfix_capex_ngn_lo": [1.8e7] * 3, "orfix_capex_ngn_hi": [2.2e7] * 3,
        "uptime_today": [0.0] * 3, "uptime_with_system": [1.0] * 3})
    fac = pd.DataFrame({"unique_id": ["a", "b", "c", "d"], "facility_name": list("ABCD"),
                        "facility_level": ["Primary", "Primary", "Secondary", "Primary"],
                        "state_standard": ["Kano", "Kano", "Kano", "Oyo"],
                        "lga_standard": ["Nassarawa", "Fagge", "Nassarawa", "Ibadan North"]})
    city = O.aggregate_city("kano", ["Nassarawa", "fagge"], res, fac, budget_ngn=3e7)
    assert city["facilities"] == 3 and city["by_level"] == {"Primary": 2, "Secondary": 1}
    assert city["service_hours_with_orfix"] == 983 and city["service_hours_today"] == 10
    assert city["diesel_l_avoided"]["lo"] == 33 and city["capex_ngn"]["point"] == 5e7
    ranked = city["ranked"]
    assert ranked.unique_id.tolist() == ["b", "a", "c"]  # 29.0, 17.15 and 17.0 hours per N1m
    assert ranked.funded.tolist() == [True, True, False]
    empty = O.aggregate_city("Lagos", None, res, fac)
    assert empty["facilities"] == 0


@needs_nasa
def test_t5_outage_runs_and_reports_seforall_comparison():
    rows = O.t5_outage(sites=((9.0, 7.5, {"C": 1.0}),), cfg=CFG)
    r = rows[0]
    assert r["full_load_kwh_day"] == pytest.approx(36.046) and r["full_kwp"] > r["critical_kwp"]
    assert isinstance(r["full_inside_seforall"], bool)


def test_forty_day_window_and_default_city():
    assert 40 in O.DEFAULT_DAYS and O.ORFIX_SIZED_FOR == (7, 40)
    assert O.orfix_prefix(7) == "orfix_" and O.orfix_prefix(40) == "orfix40_"
    assert O.MAIDUGURI == ("Borno", ("Maiduguri", "Jere"))
    m, _ = O.window_mask(4, 8760, 40, seed=1)
    assert (m.sum(axis=1) == 960).all()


def test_city_view_picks_the_system_for_the_window():
    base = {"orfix_days": 7, "uptime_today": 0.0, "uptime_with_system": 1.0}
    res = pd.DataFrame([{**base, "unique_id": u, "out40_hours_today": 0.0, "out40_needed_h": 1960.0,
                         "out14_hours_today": 0.0, "out14_needed_h": 686.0,
                         "orfix40_hours_kept": 1900.0, "orfix40_capex_ngn": 3e7, "orfix40_capex_ngn_lo": 3e7,
                         "orfix40_capex_ngn_hi": 3e7, "orfix40_diesel_l_avoided": 80.0,
                         "orfix40_diesel_l_avoided_lo": 64.0, "orfix40_diesel_l_avoided_hi": 96.0,
                         "orfix_at14_hours_kept": 680.0, "orfix_at14_diesel_l_avoided": 27.0,
                         "orfix_at14_diesel_l_avoided_lo": 22.0, "orfix_at14_diesel_l_avoided_hi": 33.0,
                         "orfix_capex_ngn": 2e7, "orfix_capex_ngn_lo": 2e7, "orfix_capex_ngn_hi": 2e7}
                        for u in ("a", "b")])
    fac = pd.DataFrame({"unique_id": ["a", "b"], "facility_name": ["A", "B"], "facility_level": ["Primary"] * 2,
                        "state_standard": ["Borno"] * 2, "lga_standard": ["Maiduguri", "Jere"]})
    c40 = O.aggregate_city(results=res, facilities=fac, days=40)
    assert c40["system_sized_for_days"] == 40 and c40["service_hours_with_orfix"] == 3800
    assert c40["capex_ngn"]["point"] == 6e7 and c40["diesel_l_avoided"]["lo"] == 128
    c14 = O.aggregate_city(results=res, facilities=fac, days=14)
    assert c14["system_sized_for_days"] == 7 and c14["service_hours_with_orfix"] == 1360
    assert c14["capex_ngn"]["point"] == 4e7 and c14["share_today"] == 0
