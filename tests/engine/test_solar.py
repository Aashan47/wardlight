import json

import numpy as np
import pytest

from engine import solar as S

from .conftest import needs_nasa


def test_no_sun_gives_zero_power():
    assert np.all(S.pv_kwh_per_kwp(np.zeros(24), np.full(24, 30.0)) == 0)


def test_fixed_vector_stc_like():
    # G = 1000 W/m2, Ta = 20 degC, NOCT 45: Tc = 20 + (45 - 20) / 800 * 1000 = 51.25
    out = S.pv_kwh_per_kwp(np.array([1000.0]), np.array([20.0]))[0]
    expected = 1.0 * (1 - 0.004 * (51.25 - 25)) * (1 - 0.14)
    assert out == pytest.approx(expected, rel=1e-12)


def test_negative_irradiance_clipped():
    assert S.pv_kwh_per_kwp(np.array([-5.0]), np.array([25.0]))[0] == 0


def test_nearest_point_rounds_and_clamps():
    assert S.nearest_point(9.4, 7.6) == (9, 8)
    assert S.nearest_point(2.0, 20.0) == (4, 15)
    assert S.nearest_point(20.0, 0.0) == (14, 3)
    with pytest.raises(ValueError):
        S.nearest_point(float("nan"), 7)


@needs_nasa
def test_load_weather_shape_and_local_time():
    w = S.load_weather(9.0, 7.0)
    assert w.ghi_w_m2.shape == (3, 8760) and w.t2m_c.shape == (3, 8760)
    day = w.ghi_w_m2[0, :24]
    # local noon (WAT) is the brightest hour band; midnight is dark
    assert day[0] == 0 and day[12] > 500
    y = S.annual_yield_kwh_per_kwp(9.0, 7.0)
    assert 1100 < y < 2000


def test_pvgis_parses_cached_response(tmp_path):
    hourly = [{"time": f"2021{m:02d}01:0010", "P": 1000.0} for m in range(1, 13)]
    data = {"outputs": {"hourly": hourly}, "inputs": {"meteo_data": {"radiation_db": "X", "meteo_db": "Y"}}}
    (tmp_path / "series_9.0000_7.0000_2021_2023_loss14_h0.json").write_text(json.dumps(data))
    r = S.pvgis_annual_yield(9.0, 7.0, cache_dir=tmp_path)
    assert r["kwh_per_kwp_yr"] == pytest.approx(12.0) and r["years_returned"] == ["2021"]
