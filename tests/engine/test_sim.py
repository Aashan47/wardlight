import time

import numpy as np
import pytest

from engine import loads as LD
from engine import sim as SM

from .conftest import needs_nasa

CFG = SM.SimConfig(n_draws=8)
CRIT = LD.critical()
_, PROF = LD.priority_profile(CRIT)


# ---- pure clinic loop on synthetic arrays (no data needed)

def test_clinic_no_grid_no_sun_battery_covers_exactly():
    # one priority, 1 kW every hour; 10 kWh usable battery, perfect efficiency, 48 h
    prof = np.ones((1, 24))
    bp = SM.BatteryParams(usable_fraction=1.0, round_trip_eff=1.0, grid_charging=False, shed_reserve=0.5)
    r = SM.simulate_clinic(np.zeros((1, 48), bool), np.zeros((1, 48)), np.array([1.0]), np.array([10.0]), prof, bp)
    assert r["days_ok"][0, 0, 0] == 0
    r = SM.simulate_clinic(np.zeros((1, 48), bool), np.zeros((1, 48)), np.array([1.0]), np.array([24.0]), prof, bp)
    assert r["days_ok"][0, 0, 0] == 1  # first day served, second not
    r = SM.simulate_clinic(np.zeros((1, 48), bool), np.zeros((1, 48)), np.array([1.0]), np.array([48.0]), prof, bp)
    assert r["days_ok"][0, 0, 0] == 2 and r["offgrid_kwh"][0, 0] == pytest.approx(48)


def test_clinic_full_grid_serves_everything_and_counts_no_offgrid_energy():
    r = SM.simulate_clinic(np.ones((2, 72), bool), np.zeros((2, 72)), np.array([0.0]), np.array([0.0]), PROF)
    assert (r["days_ok"] == 3).all() and r["offgrid_kwh"].sum() == 0


def test_clinic_zero_system_zero_grid_fails_every_day():
    r = SM.simulate_clinic(np.zeros((2, 72), bool), np.ones((2, 72)), np.array([0.0]), np.array([0.0]), PROF)
    assert (r["days_ok"] == 0).all()


def test_shedding_protects_priority_one():
    prof = np.vstack([np.r_[np.zeros(20), np.ones(4)], np.r_[np.ones(20), np.zeros(4)]])  # p1 at night, p2 by day
    bp = SM.BatteryParams(usable_fraction=1.0, round_trip_eff=1.0, grid_charging=False, shed_reserve=0.5)
    r = SM.simulate_clinic(np.zeros((1, 24), bool), np.zeros((1, 24)), np.array([1.0]), np.array([8.0]), prof, bp)
    assert r["days_ok"][0, 0, 0] == 1 and r["days_ok"][0, 0, 1] == 0


def test_vectorised_sizes_match_single_runs():
    rng = np.random.default_rng(0)
    g = rng.random((3, 24 * 20)) < 0.5
    pv = np.tile(np.r_[np.zeros(7), np.full(10, 0.6), np.zeros(7)], 20)[None, :].repeat(3, 0)
    kwp, kwh = np.array([0.5, 1.0, 2.0]), np.array([3.6, 7.2, 14.4])
    both = SM.simulate_clinic(g, pv, kwp, kwh, PROF)["days_ok"]
    for i in range(3):
        one = SM.simulate_clinic(g, pv, kwp[i : i + 1], kwh[i : i + 1], PROF)["days_ok"][0]
        assert np.array_equal(both[i], one)


def test_interval_order():
    iv = SM.Interval.of(np.r_[np.zeros(5), np.ones(95)])
    assert iv.lo <= iv.point <= iv.hi


# ---- facility runs on real NASA POWER weather

@needs_nasa
def test_edge_cases_offgrid_full_unknown():
    off = SM.simulate_facility(9, 7, "OFFGRID", CRIT, None, CFG)
    assert off.fridge_today.hi == 0.0 and off.critical_today.hi == 0.0
    full = SM.simulate_facility(9, 7, "FULL", CRIT, None, CFG)
    assert full.fridge_today_technical.lo == 1.0 and full.critical_today.lo == 1.0
    # reported figures carry the availability scenario (0.90 to 0.99), so never a flat 100%
    assert 0.90 <= full.fridge_today.lo and full.fridge_today.hi <= 0.99
    assert full.fridge_today_pqs.hi <= 0.99
    unk = SM.simulate_facility(9, 7, None, CRIT, SM.ClinicSystem(2, 14.4), CFG)
    assert unk.fridge_today is None and unk.critical_today is None and not unk.supply_known
    assert unk.critical_with is not None


@needs_nasa
def test_bands_order_today():
    a = SM.simulate_facility(9, 7, "A", CRIT, None, CFG).critical_today.point
    e = SM.simulate_facility(9, 7, "E", CRIT, None, CFG).critical_today.point
    assert a > e


@needs_nasa
def test_big_system_holds_and_no_system_fails_offgrid():
    big = SM.simulate_facility(9, 7, "OFFGRID", CRIT, SM.ClinicSystem(10, 72), CFG)
    assert big.critical_with.lo == 1.0
    none = SM.simulate_facility(9, 7, "OFFGRID", CRIT, SM.ClinicSystem(0, 0), CFG)
    assert none.critical_with.hi == 0.0


@needs_nasa
def test_deterministic_with_seed():
    a = SM.simulate_facility(6, 5, {"C": 0.5, "D": 0.5}, CRIT, SM.ClinicSystem(1, 7.2), CFG)
    b = SM.simulate_facility(6, 5, {"C": 0.5, "D": 0.5}, CRIT, SM.ClinicSystem(1, 7.2), CFG)
    assert a.fridge_today == b.fridge_today and a.critical_with == b.critical_with


@needs_nasa
def test_what_if_trace_and_speed():
    t = time.perf_counter()
    r = SM.what_if(9, 7, "E", CRIT, 1.5, 10.8)
    assert time.perf_counter() - t < 3.0  # loose CI bound; T6 is measured separately on the server
    tr = r.trace
    for k in ("grid_on", "pv_kw_clinic", "battery_soc_kwh", "priorities_served", "fridge_today_ok", "fridge_with_ok"):
        assert len(tr[k]) == 24
    assert r.to_dict()["labels"]["supply"].startswith("modelled")


@needs_nasa
def test_today_scenarios_order_domestic_worse_than_pqs():
    pp = SM.prepare(9, 7, "C", CFG)
    dom, _ = SM.domestic_on_grid(pp)
    pqs, _ = SM.ilr_on_grid(pp, "E003-088e")
    assert dom.technical.point < pqs.technical.point
    assert np.all((pp.h_dom >= 1.5) & (pp.h_dom <= 6.0)) and np.all((pp.avail >= 0.9) & (pp.avail <= 0.99))


@needs_nasa
def test_domestic_fridge_survives_outages_shorter_than_its_holdover():
    pp = SM.prepare(9, 7, "FULL", CFG)
    g = pp.grid.copy()
    g[:, ::24] = False  # one 1-hour outage a day, shorter than the 1.5 h minimum holdover
    pp2 = SM.Prepared(pp.point, pp.pv_l, pp.leak_l, pp.pr, pp.n_lanes, g, pp.k, True, pp.h_dom, pp.avail, pp.soil)
    dom, _ = SM.domestic_on_grid(pp2)
    assert dom.technical.lo == 1.0
