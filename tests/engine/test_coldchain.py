import pytest

from engine import coldchain as CC
from engine import sim as SM

from .conftest import needs_nasa

CFG = SM.SimConfig(n_draws=8)


@needs_nasa
def test_good_grid_gets_the_cheap_ice_lined_fix():
    cc = CC.assess(SM.prepare(9, 7, "FULL", CFG), offgrid=False, cfg=CFG)
    assert cc.category == "i" and cc.chosen.code == "E003-089e"  # HBC-80, USD 860, cheapest priced ILR
    assert cc.chosen.capex_usd.point == 860
    assert cc.monthly_cost_ngn.point == pytest.approx(860 * 1352.371 / 120)


@needs_nasa
def test_weak_grid_gets_solar_direct_drive():
    cc = CC.assess(SM.prepare(9, 7, "E", CFG), offgrid=False, cfg=CFG)
    assert cc.category == "ii" and cc.chosen.code == "E003-040e"
    assert cc.chosen.array_kwp is not None


@needs_nasa
def test_offgrid_gets_sdd_plus_clinic_line_and_no_ice_lined_option():
    cc = CC.assess(SM.prepare(9, 7, "OFFGRID", CFG), offgrid=True, cfg=CFG)
    assert cc.category == "iii" and all(o.fix == "ii" for o in cc.options)


@needs_nasa
def test_unknown_supply_has_no_today_and_no_ice_lined_option():
    cc = CC.assess(SM.prepare(9, 7, None, CFG), offgrid=False, cfg=CFG)
    assert cc.today_b_domestic is None and cc.today_a_pqs is None
    assert cc.category == "ii"


@needs_nasa
def test_reported_uptime_below_technical():
    cc = CC.assess(SM.prepare(9, 7, "E", CFG), offgrid=False, cfg=CFG)
    assert cc.chosen.uptime.point < cc.chosen.uptime_technical.point
