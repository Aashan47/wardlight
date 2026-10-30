import numpy as np
import pytest

from engine import loads as LD
from engine import sim as SM
from engine import size as SZ

from .conftest import needs_nasa

CFG = SM.SimConfig(n_draws=8)


def test_knee_on_a_saturating_curve():
    x = np.array([1, 2, 3, 4, 5, 6, 7, 8.0])
    y = np.array([0.2, 0.6, 0.85, 0.95, 0.98, 0.99, 0.995, 1.0])
    assert SZ.knee_index(x, y) == 2


def test_knee_degenerate():
    assert SZ.knee_index(np.array([1, 2.0]), np.array([1, 1.0])) == 0


def test_default_grid_brackets_need():
    g = SZ.default_kwp_grid(4.7, 1600)
    base = 4.7 / (1600 / 365)
    assert g.min() < base < g.max()


@needs_nasa
def test_size_clinic_offgrid_meets_target_and_curve_rises():
    s = SZ.size_clinic(9, 7, "OFFGRID", LD.critical(), cfg=CFG)
    assert s.target_met and s.chosen.uptime.lo >= 0.99
    lo = [c.uptime.lo for c in s.curve]
    assert lo[0] < lo[-1]
    assert s.chosen.battery_kwh == pytest.approx(s.chosen.pv_kwp * 7.2)
    costs = [c.capex_usd.point for c in s.curve]
    assert costs == sorted(costs)


@needs_nasa
def test_size_clinic_unreachable_target_flagged():
    s = SZ.size_clinic(9, 7, "OFFGRID", LD.critical(), kwp_grid=[0.05, 0.1], cfg=CFG)
    assert not s.target_met


@needs_nasa
def test_size_fridge_picks_cheapest_priced_sdd():
    f = SZ.size_fridge(9, 7, cfg=CFG)
    assert f.chosen.capex_usd is not None and f.chosen.code == "E003-040e"
    assert {o.code for o in f.options} == {"E003-040e", "E003-048e", "E003-129e"}
    for o in f.options:
        assert 0.16 <= o.array_kwp <= 0.6  # near the Energizing Health 160-500 W range
