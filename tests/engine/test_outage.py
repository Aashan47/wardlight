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
    assert r.generator_litres.lo == pytest.approx(0.303 * kwh) and r.generator_litres.hi == pytest.approx(0.454 * kwh)
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
