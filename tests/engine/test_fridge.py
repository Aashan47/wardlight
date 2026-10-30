import numpy as np
import pytest

from engine import fridge as F

TH = F.ThermalParams()


def test_leak_scaling():
    assert F.leak_rate(43.0) == pytest.approx(1.0)
    assert F.leak_rate(5.0) == 0.0 and F.leak_rate(0.0) == 0.0
    assert F.leak_rate(24.0) == pytest.approx(19 / 38)


def test_no_power_at_test_ambient_holds_for_the_holdover():
    x_max = np.array([60.0, 30.5])
    ok = F.simulate_ice_lined(np.zeros((2, 100), bool), np.ones(100), x_max, TH)
    assert ok[0].sum() == 59  # reserve 60 -> 0 after 60 h; hour 60 reads 0
    assert ok[1].sum() == 30


def test_full_power_always_held():
    ok = F.simulate_ice_lined(np.ones((3, 500), bool), np.ones(500), np.full(3, 10.0), TH)
    assert ok.all()


def test_pqs_ice_lined_cycle_16_off_8_on_survives_at_43c():
    """PQS RF03-VP.2 p.8 cycle; with the derived recharge rate the shortest-holdover unit passes."""
    day = np.r_[np.zeros(16, bool), np.ones(8, bool)]
    powered = np.tile(day, 5)[None, :]
    m = F.CATALOGUE["E003-120e"]  # 57:52, the shortest holdover in the catalogue
    ok = F.simulate_ice_lined(powered, np.ones(120), np.array([m.holdover_h]), TH)
    assert ok.all()


def test_sdd_no_sun_fails_after_holdover_and_sun_keeps_it_cold():
    m = F.CATALOGUE["E003-040e"]
    x = np.array([m.holdover_h])
    ok = F.simulate_sdd(np.zeros((1, 200)), m.energy_kwh_24h, np.ones(200), x)
    assert ok.sum() == int(np.floor(m.holdover_h))
    sunny = np.tile(np.r_[np.zeros(8), np.full(8, 0.06), np.zeros(8)], 10)[None, :]  # 0.48 kWh/day < 0.5
    sunnier = sunny * 1.2  # 0.576 kWh/day > 0.5
    assert F.simulate_sdd(sunnier, m.energy_kwh_24h, np.ones(240), x).all()


def test_array_size_derivation():
    m = F.CATALOGUE["E003-040e"]
    assert F.sdd_array_kwp(m, 0.8) == pytest.approx(0.5 / (3.5 * 0.8))


def test_catalogue_excludes_data_entry_errors():
    assert not F.CATALOGUE["E003-059e"].usable and F.CATALOGUE["E003-059e"].energy_kwh_24h is None
    assert not F.CATALOGUE["E003-084e"].usable
    with pytest.raises(ValueError):
        F.sdd_array_kwp(F.CATALOGUE["E003-084e"], 0.8)
    for m in F.CATALOGUE.values():
        assert m.source and (m.holdover_h is None or 50 < m.holdover_h <= 180)


def test_days_held():
    ok = np.ones((1, 72), bool)
    ok[0, 30] = False
    assert F.days_held(ok).tolist() == [[True, False, True]]


def test_k_sampling_bounds():
    k = F.sample_k(1000, np.random.default_rng(0), TH)
    assert k.min() >= 0.5 and k.max() <= 1.0
