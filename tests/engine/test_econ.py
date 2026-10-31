import math

import pytest

from engine import econ as E


def test_clinic_capex_from_seforall_per_wp():
    c = E.clinic_capex_usd(1.0, 7.2)
    assert (c.point, c.lo, c.hi) == pytest.approx((6000, 5300, 6500))
    assert E.clinic_capex_usd(1.0, 14.4).point == pytest.approx(12000)  # battery-heavy priced by battery
    assert E.clinic_capex_usd(0, 0).point == 0


def test_fridge_capex_currencies():
    assert E.fridge_capex_usd("E003-088e").point == 999
    d = E.fridge_capex_usd("E003-040e")
    assert d.point == pytest.approx(5650 * 1508.0289 / 1352.3710)  # CBN EUR and USD central rates, same day
    assert E.fridge_capex_usd("E003-120e") is None


def test_lifecycle_and_monthly():
    cap = E.Range(1000, 1000, 1000)
    assert E.lifecycle_usd(cap).point == pytest.approx(1000 * (1 + 0.05 * 15 + 0.15))
    assert E.monthly_cost_ngn(cap).point == pytest.approx(1900 * 1352.371 / 180)


def test_diesel_and_co2_fixed_vector():
    litres = E.diesel_litres_per_year(1000)
    assert (litres.lo, litres.hi) == pytest.approx((400, 730))  # clinic-set curve, Cummins C17/C22 D5
    assert E.co2_kg(litres).lo == pytest.approx(400 * 2.697)
    m = E.diesel_cost_ngn_per_month(litres)
    assert m.lo == pytest.approx(400 * 1441.28 / 12) and m.hi == pytest.approx(730 * 3277.47 / 12)


def test_payback():
    assert E.payback_months(E.Range(1200, 1200, 1200), E.Range(110, 110, 110), E.Range(10, 10, 10)).point == 12
    assert math.isinf(E.payback_months(E.Range(1, 1, 1), E.Range(5, 5, 5), E.Range(9, 9, 9)).point)


def test_economics_bundle():
    ec = E.economics(1.0, 7.2, "E003-040e", 2000)
    assert ec.capex_usd.point == pytest.approx(6000 + 5650 * 1508.0289 / 1352.3710)
    assert ec.capex_ngn.point == pytest.approx(ec.capex_usd.point * 1352.371)
    assert ec.fx_date


def test_clinic_line_counts_diesel_only_where_plausible():
    on = E.clinic_economics(1.0, 7.2, 1000, diesel_plausible=True)
    off = E.clinic_economics(1.0, 7.2, 1000, diesel_plausible=False)
    assert on.diesel_l_per_year.lo == pytest.approx(400) and off.diesel_l_per_year.hi == 0
    assert math.isinf(off.payback_months.point)
    assert on.capex_usd.point == off.capex_usd.point == pytest.approx(6000)
