import numpy as np
import pandas as pd
import pytest

from engine import supply as SP

RNG = lambda: np.random.default_rng(1)
ALWAYS_MEET = SP.ShortfallParams(p_meet=1.0)


def test_normalise_bands_forms():
    assert SP.normalise_bands("c") == {"C": 1.0}
    assert SP.normalise_bands('{"A": 1, "B": 3}') == {"A": 0.25, "B": 0.75}
    assert SP.normalise_bands(None) == {SP.OFFGRID: 1.0}
    assert SP.normalise_bands({}) == {SP.OFFGRID: 1.0}
    with pytest.raises(ValueError):
        SP.normalise_bands({"Z": 1})


def test_zero_grid_offgrid():
    g = SP.sample_supply(SP.OFFGRID, 5, 30, RNG())
    assert g.shape == (5, 720) and not g.any()


def test_full_grid():
    assert SP.sample_supply(SP.FULL, 5, 30, RNG()).all()


@pytest.mark.parametrize("band,hours", [("A", 20), ("B", 16), ("C", 12), ("D", 8), ("E", 4)])
def test_promise_met_exactly_when_p_meet_is_one(band, hours):
    g = SP.sample_supply(band, 4, 60, RNG(), ALWAYS_MEET)
    assert np.all(g.reshape(4, 60, 24).sum(axis=2) == hours)


def test_promise_is_a_ceiling():
    h, _ = SP.sample_daily_hours("A", 200, 365, RNG())
    assert h.max() <= 20 and h.min() >= 0 and h.mean() < 20


def test_daily_pattern_keeps_on_hours():
    rng = RNG()
    d = rng.integers(0, 25, size=5000)
    on = SP.daily_pattern(d, rng)
    assert np.array_equal(on.sum(axis=1), d)


def test_two_blocks_appear_at_the_survey_rate():
    rng = RNG()
    on = SP.daily_pattern(np.full(20000, 12), rng)
    switches = (on != np.roll(on, 1, axis=1)).sum(axis=1) // 2  # blocks of 'on' per day on a circle
    share_two = (switches == 2).mean()
    lam = 32.8 / 30.4375 - 1
    assert share_two == pytest.approx(1 - np.exp(-lam), abs=0.02)


def test_mixture_weights():
    _, bands = SP.sample_daily_hours({"A": 0.25, "E": 0.75}, 4000, 1, RNG())
    assert (bands == "E").mean() == pytest.approx(0.75, abs=0.03)


def test_calibration_recovers_mean_and_p_meet():
    rng = np.random.default_rng(0)
    f = rng.beta(2, 18, 400)
    df = pd.DataFrame({"disco": rng.choice(["X", "Y", "Z"], 400), "measured_avg_hours": 20 * (1 - f)})
    p = SP.calibrate_shortfall(df, n_band_a_feeders=1000)
    assert p.calibrated and p.p_meet == pytest.approx(0.6)
    assert p.alpha / (p.alpha + p.beta) == pytest.approx(0.1, abs=0.01)


def test_calibration_counts_unmeasured_failing_rows_for_p_meet():
    df = pd.DataFrame({"measured_avg_hours": [19.0, 18.5, np.nan, np.nan]})
    assert SP.calibrate_shortfall(df, 40).p_meet == pytest.approx(0.9)


def test_backtest_structure_and_widening():
    rng = np.random.default_rng(0)
    f = rng.beta(2, 18, 120)
    df = pd.DataFrame({"disco": rng.choice(["X", "Y", "Z"], 120), "measured_avg_hours": 20 * (1 - f)})
    bt = SP.backtest_t3(df, 1000)
    assert bt["n"] == 120 and 0 <= bt["share"] <= 1 and set(bt["detail"].group) == {"X", "Y", "Z"}
    assert bt["share"] >= 0.8  # data drawn from the model family
    w = SP.widen_until_pass(df, 1000)
    assert w["factor"] is not None and w["share"] >= 0.85


def test_band_hours_from_rows():
    rows = pd.DataFrame({"band": ["A", "A", "A", "C", "C"], "min_hours": [20, 20, 19, 12, 12]})
    assert SP.band_hours_from_rows(rows) == {"A": 20.0, "C": 12.0}
