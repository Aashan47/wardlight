"""Tests for the NERC appendix reader.

Unit tests on parsing run anywhere. The fixture tests compare the built parquet files with three pages
transcribed by eye (IKEDC p12, PHED p11, Aba Power p8); they skip when data/work/ has not been built
(`.venv/bin/python -m data_build.nerc.build`), because the source PDFs are never committed.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data_build.nerc.evaluate import compare, compare_shortfalls, load_fixtures
from data_build.nerc.ocr import fix_caps
from data_build.nerc.schema import header_role, parse_action, parse_band, parse_hours, parse_period, parse_sn

WORK = Path(__file__).resolve().parents[2] / "data" / "work"
ROWS = WORK / "nerc_rows.parquet"
SHORTS = WORK / "nerc_shortfalls.parquet"
needs_build = pytest.mark.skipif(not ROWS.exists(), reason="data/work/nerc_rows.parquet not built")


# ---- parsing -------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,role", [
    ("S/N", "sn"), ("FEEDER NAME", "feeder_name"), ("BAND", "band"), ("CURRENT BAND", "band"),
    ("DESCRIPTION OF FEEDER LOCATION", "location"), ("FEEDER LOCATION", "location"),
    ("NAME OF MAJOR STREETS SERVED BY THE FEEDER", "streets"), ("MIN. SUPPLY DURATION (HRS)", "min_hours"),
    ("1ST- 21ST AUG PERFORMANCE", "measured"), ("REMARK", "remark"),
])
def test_header_role(text, role):
    assert header_role(text) == role


def test_parse_values():
    assert parse_band("A") == "A" and parse_band("BAND C") == "C" and parse_band("AB") is None
    assert parse_hours("20") == 20.0 and parse_hours("16.81") == 16.81 and parse_hours("2O") is None
    assert parse_hours("AFFECTED BY LOW GENERATION") is None and parse_hours("99") is None
    assert parse_sn("41") == 41 and parse_sn("4I") is None


def test_period_and_action():
    assert parse_period("1ST- 21ST AUG PERFORMANCE", "2026-09") == "2026-08-01/2026-08-21"
    assert parse_period("1ST - 25TH JAN AVE PERFORMANCE", "2025-02") == "2025-01-01/2025-01-25"
    assert parse_period("AUGUST 1ST-21ST PERF", "2026-09") == "2026-08-01/2026-08-21"
    assert parse_action("DOWNGRADE TO BAND B & COMPENSATE CUSTOMERS") == "downgrade+compensation"
    assert parse_action("COMPENSATE CUSTOMER") == "compensation"
    assert parse_action("AFFECTED BY LOW GENERATION", "Appendix 2: Compensation") is None


def test_fix_caps():
    assert fix_caps("AYEDE T1 1OOMVA") == "AYEDE T1 100MVA"
    assert fix_caps("Ul-AGBOWO") == "UI-AGBOWO"
    assert fix_caps("Tl 30MVA") == "T1 30MVA"


# ---- fixture pages -------------------------------------------------------------------------------

FIXTURES = load_fixtures()


@needs_build
@pytest.mark.parametrize("fx", FIXTURES, ids=[f"{f['disco']}_p{f['page']}" for f in FIXTURES])
def test_fixture_page(fx):
    rows = pd.read_parquet(ROWS)
    res = compare(fx, rows)
    assert res["read_rows"] == res["expected_rows"], res["misses"]
    f = res["fields"]
    n = res["expected_rows"]
    assert f["sn"]["exact"] == n
    assert f["band"]["exact"] == n, res["misses"]
    assert f["min_hours"]["exact"] == n, res["misses"]
    # feeder names exact or within two edits on every row
    assert f["feeder_name"]["within_edits"] == n, res["misses"]


@needs_build
def test_fixture_text_fields_overall():
    """Locations and streets: at least 90% within two edits over all fixture rows together.

    Checked over the 44 rows together, since one long street list on a 7-row page is 14%.
    """
    rows = pd.read_parquet(ROWS)
    for field in ("location", "streets"):
        ok = tot = 0
        for fx in FIXTURES:
            t = compare(fx, rows)["fields"][field]
            ok += t["within_edits"]
            tot += t["total"]
        assert ok >= 0.9 * tot, (field, ok, tot)


@needs_build
def test_fixture_shortfalls():
    shorts = pd.read_parquet(SHORTS)
    for fx in FIXTURES:
        res = compare_shortfalls(fx, shorts)
        if res is None:
            continue
        assert res["read"] == res["expected"]
        for chk in res["checks"]:
            assert isinstance(chk, dict) and all(chk.values()), chk


@needs_build
def test_contract_columns():
    rows = pd.read_parquet(ROWS)
    assert list(rows.columns) == ["disco", "order_file", "order_month", "page", "sn", "band", "feeder_name",
                                  "location", "streets", "min_hours", "ocr_confidence", "crop_path"]
    shorts = pd.read_parquet(SHORTS)
    assert list(shorts.columns) == ["disco", "order_file", "page", "feeder_name", "period",
                                    "measured_avg_hours", "action"]
    assert set(rows.band.dropna()) <= set("ABCDE")
    root = WORK.parents[1]
    assert all((root / p).exists() for p in rows.crop_path)
