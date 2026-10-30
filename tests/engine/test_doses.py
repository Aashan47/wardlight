import numpy as np
import pandas as pd
import pytest

from engine import doses as D


def test_fixed_vector_doses():
    assert D.births_per_year(1000) == pytest.approx(32.493)
    assert D.doses_per_year(1000) == pytest.approx(649.86)
    assert D.doses_per_year(1000, doses_per_child=23) == pytest.approx(32.493 * 23)
    assert D.doses_protected(100, 0.9) == pytest.approx(90)
    assert D.doses_per_year(0) == 0


def test_allocation_nearest_within_radius():
    fac_lat, fac_lon = np.array([9.0, 9.0]), np.array([7.0, 7.1])  # about 11 km apart
    pt_lat = np.array([9.0, 9.0, 9.0, 10.0])
    pt_lon = np.array([7.01, 7.09, 7.04, 7.0])  # near A, near B, nearer A, 111 km away
    pop, un = D.allocate_points(fac_lat, fac_lon, pt_lat, pt_lon, np.array([10, 20, 5, 100.0]), 5.0)
    assert pop.tolist() == [15, 20] and un == 100


def test_eligible_drops_closed_and_missing_coords():
    f = pd.DataFrame({"unique_id": list("abcd"), "latitude": [9, 9, np.nan, 9], "longitude": [7, 7, 7, 7],
                      "functional": ["Functional", "Closed", "Functional", "Not-Functional"]})
    assert D.eligible(f).unique_id.tolist() == ["a"]


def test_cap_by_sourced_population_per_facility():
    capped, over = D.apply_cap(np.array([5000.0, 963708.0, 20000.0]))
    assert capped.tolist() == [5000, 20000, 20000] and over.tolist() == [0, 943708, 0]
    assert D.doses_per_year(capped).max() == pytest.approx(20000 * 32.493 / 1000 * 20)
