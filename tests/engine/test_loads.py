import numpy as np
import pytest

from engine import loads as LD


def test_seforall_total_matches_printed_total():
    assert LD.daily_kwh(LD.SEFORALL_TYPE2_PHC) == pytest.approx(36.046)


def test_profiles_sum_to_daily_energy():
    for ld in LD.SEFORALL_TYPE2_PHC:
        assert ld.hourly_kw().sum() == pytest.approx(ld.wh_per_day / 1000)
    pr, prof = LD.priority_profile(LD.SEFORALL_TYPE2_PHC)
    assert list(pr) == [1, 2, 3] and prof.sum() == pytest.approx(36.046)


def test_fractional_hours_and_wraparound():
    ld = LD.Load("x", "x", 1, 1000, 2.5, 1, 23)
    p = ld.hourly_kw()
    assert p[23] == 1 and p[0] == 1 and p[1] == 0.5


def test_critical_set_is_lights_oxygen_delivery_room():
    keys = {ld.key for ld in LD.critical()}
    assert keys == {"light_interior", "oxygen", "suction", "procedure_light", "fetal_monitor"}
    assert "gp_fridge" not in keys  # the vaccine fridge never rides on the clinic system


def test_edit_and_from_dicts():
    e = LD.edit(LD.SEFORALL_TYPE2_PHC, {"oxygen": {"hours_per_day": 8}})
    assert LD.by_key(e)["oxygen"].wh_per_day == 1600
    with pytest.raises(KeyError):
        LD.edit(LD.SEFORALL_TYPE2_PHC, {"nope": {}})
    u = LD.from_dicts([{"key": "lamp", "watts": 10, "hours_per_day": 12, "priority": 1}])
    assert u[0].source == "user input" and u[0].wh_per_day == 120
    assert np.isclose(LD.daily_kwh(u), 0.12)
