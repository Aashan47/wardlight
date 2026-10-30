import re
from pathlib import Path

import pytest

from engine import constants as C

ENGINE = Path(__file__).resolve().parents[2] / "engine"
DOC = Path(__file__).resolve().parents[2] / "docs" / "sources" / "engine.md"


def test_every_constant_has_a_source_and_status():
    assert len(C.REGISTRY) >= 30
    for name, c in C.REGISTRY.items():
        assert c.source.strip(), name
        assert c.status in ("VERIFIED", "VERIFIED_SECONDARY", "DERIVED", "UNVERIFIED", "ASSUMPTION"), name


def test_unverified_and_assumptions_are_ranges_containing_the_default():
    for name, c in C.REGISTRY.items():
        if c.status in ("UNVERIFIED", "ASSUMPTION"):
            assert c.is_range, f"{name} must be a labelled range"
        if c.is_range:
            assert c.lo <= c.value <= c.hi, name


def test_fixed_values_from_sources():
    assert C.CRUDE_BIRTH_RATE_PER_1000.value == 32.493
    assert C.FX_NGN_PER_USD.value == 1352.371
    assert C.CO2_KG_PER_L_DIESEL.value == 2.697
    assert abs(10.21 / 3.785411784 - C.CO2_KG_PER_L_DIESEL.value) < 5e-4
    assert C.DIESEL_NGN_PER_L.lo == 1441.28
    assert C.BAND_MIN_HOURS == {"A": 20, "B": 16, "C": 12, "D": 8, "E": 4}
    assert C.BATTERY_KWH_PER_KWP.value == 36 / 5 == 72 / 10
    assert C.EUR_TO_USD.value == pytest.approx(1508.0289 / 1352.3710)
    assert (C.DOMESTIC_HOLDOVER_H.lo, C.DOMESTIC_HOLDOVER_H.hi) == (1.5, 6.0)
    assert C.CATCHMENT_CAP_POP.value == 20000 and C.FRIDGE_LIFE_YEARS.value == 10


def test_no_em_dashes_in_engine_or_its_doc():
    files = list(ENGINE.glob("*.py")) + list(Path(__file__).parent.glob("*.py")) + ([DOC] if DOC.exists() else [])
    for f in files:
        assert chr(0x2014) not in f.read_text(), f.name


def test_engine_doc_has_no_calendar_dates():
    if not DOC.exists():
        return
    text = DOC.read_text()
    months = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    assert not re.search(rf"\b\d{{1,2}} {months}\b", text)
