"""Matcher tests. Real NERC text comes from the hand-transcribed BEDC September 2026 page 12 fixture
(S/N 25 to 54). Facilities marked SYNTHETIC are made up for the test and are not GRID3 records."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from data_build.match import footprint, paths, sample
from data_build.match.matcher import OFFGRID_KM, match
from data_build.match.text import clean, is_road, segments, ward_core

HAVE_NAIJA = paths.NAIJA_FEEDERS.exists() and paths.NAIJA_CAPS.exists()
needs_naija = pytest.mark.skipif(not HAVE_NAIJA, reason="naija-grid data-local files absent")


def fixture_rows() -> pd.DataFrame:
    return pd.read_csv(paths.FIXTURE_ROWS, dtype={"sn": str})


def fac(rows: list[dict]) -> pd.DataFrame:
    """SYNTHETIC facilities with the facilities.parquet columns."""
    base = {"facility_level": "Primary", "facility_type": "Primary Health Center", "facility_ownership": "Public",
            "settlement_name": "", "latitude": 6.2, "longitude": 6.7, "functional": "Functional", "flag_count": 0}
    out = []
    for i, r in enumerate(rows):
        d = {**base, "unique_id": f"SYN_{i:03d}", **r}
        out.append(d)
    return pd.DataFrame(out)


def grid_for(f: pd.DataFrame, km: float = 0.5, target: int = 1) -> pd.DataFrame:
    return pd.DataFrame({"unique_id": f["unique_id"], "grid_km": km, "grid_target": target})


def by_id(m: pd.DataFrame) -> dict[str, pd.Series]:
    return {r["unique_id"]: r for _, r in m.iterrows()}


# ---- text ----------------------------------------------------------------------------------------------------

def test_clean_expands_and_strips():
    assert clean("Gen. Hosp, Asaba") == "GENERAL HOSPITAL ASABA"
    assert clean("FMC  Asaba") == "FEDERAL MEDICAL CENTRE ASABA"
    assert clean(None) == "" and clean(float("nan")) == ""


def test_segments_keep_abbreviations_whole():
    segs = segments("GOVT. HOUSE, PS QTRES, COMMISSIONERS QTRES, DEPUTY GOVERNOR OFFICE.")
    assert segs[0] == "GOVERNMENT HOUSE"
    assert segments("OGWASHI-UKU AND IBUSA TOWN") == ["OGWASHI UKU", "IBUSA TOWN"]


def test_road_and_ward_core():
    assert is_road("OKPANAM ROAD") and not is_road("AIRPORT ROAD WARRI")
    assert ward_core("Okpanam/Ugbolu") == ["OKPANAM", "UGBOLU"]
    assert "OGHAREFE" in ward_core("Ogharefe 2")


def test_disco_codes():
    assert footprint.disco_code("IE") == "IKEDC"
    assert footprint.disco_code(None, "JED_HOLDCO_YSS_September_2026_094.pdf") == "JEDC"
    assert footprint.disco_code("EKEDP") == "EKEDC"


# ---- tier (a) ------------------------------------------------------------------------------------------------

@needs_naija
def test_tier_a_requires_type_words_and_distinct_name():
    rows = fixture_rows()
    synthetic_row = rows.iloc[[0]].copy()  # SYNTHETIC row text, built on a real row's metadata
    synthetic_row["sn"] = "SYN1"
    synthetic_row["location"] = "COMMERCIAL AREA"
    synthetic_row["streets"] = "FMC ASABA, NNEBISI ROAD"
    rows = pd.concat([rows, synthetic_row], ignore_index=True)
    f = fac([
        {"facility_name": "Federal Medical Centre Asaba", "state_standard": "Delta", "lga_standard": "Oshimili South",
         "ward_standard": "West End"},
        {"facility_name": "Asaba Specialist Hospital", "state_standard": "Delta", "lga_standard": "Oshimili North",
         "ward_standard": "Cable Point I"},
        {"facility_name": "Oghara General Hospital", "state_standard": "Delta", "lga_standard": "Ethiope West",
         "ward_standard": "Oghareki 2"},
    ])
    m, _ = match(f, rows, grid_for(f))
    r = by_id(m)
    # SYN1 'FMC ASABA' names the federal medical centre
    assert r["SYN_000"]["tier"] == "a_named"
    ev = json.loads(r["SYN_000"]["evidence"])
    assert ev["sn"] == "SYN1" and ev["nerc_text"] == "FEDERAL MEDICAL CENTRE ASABA"
    assert "FMC ASABA" in ev["row_text"]
    # Real S/N 41 'ASABA GENERAL HOSPITAL' must not match 'Asaba Specialist Hospital' (type words differ)
    assert r["SYN_001"]["tier"] != "a_named"
    # Real S/N 25 'OGHARA TEACHING HOSPITAL' must not match 'Oghara General Hospital'
    assert r["SYN_002"]["tier"] != "a_named"


# ---- tier (b) ------------------------------------------------------------------------------------------------

@needs_naija
def test_tier_b_ward_match_and_road_and_dedicated_exclusions():
    rows = fixture_rows()
    f = fac([
        {"facility_name": "Okpanam Health Post", "state_standard": "Delta", "lga_standard": "Oshimili North",
         "ward_standard": "Okpanam/Ugbolu"},
        {"facility_name": "Illah Primary Health Centre", "state_standard": "Delta", "lga_standard": "Oshimili North",
         "ward_standard": "Illah"},
        {"facility_name": "Woodland Clinic", "state_standard": "Delta", "lga_standard": "Warri South",
         "ward_standard": "Woodland"},
    ])
    only43 = rows[rows["sn"].eq("43")]  # 'SUMMIT, OKPANAM ROAD,ILLAH, GOVT CORE AREAS'
    m, _ = match(f, only43, grid_for(f))
    r = by_id(m)
    assert r["SYN_000"]["tier"] != "b_place", "OKPANAM ROAD is a street, not Okpanam"
    assert r["SYN_001"]["tier"] == "b_place"
    ev = json.loads(r["SYN_001"]["evidence"])
    assert ev["sn"] == "43" and ev["matched_on"] == "ward_standard" and ev["nerc_text"] == "ILLAH"

    m2, _ = match(f, rows, grid_for(f))
    r2 = by_id(m2)
    assert r2["SYN_000"]["tier"] == "b_place"  # S/N 30 location 'OKPANAM'
    assert json.loads(r2["SYN_000"]["evidence"])["sn"] == "30"
    assert r2["SYN_002"]["tier"] != "b_place", "S/N 48 is DEDICATED TO WOODLAND"


@needs_naija
def test_tier_b_prefers_most_specific_level():
    rows = fixture_rows()
    f = fac([{"facility_name": "Ugborikoko Health Centre", "state_standard": "Delta", "lga_standard": "Sapele",
              "ward_standard": "Ugborikoko"}])
    m, _ = match(f, rows, grid_for(f))
    ev = json.loads(m.iloc[0]["evidence"])
    assert m.iloc[0]["tier"] == "b_place" and ev["matched_on"] == "ward_standard"
    assert ev["nerc_text"] == "UGBERIKOKO" and ev["score"] >= 90  # printed spelling differs by one letter


@needs_naija
def test_cross_state_name_needs_corroboration():
    rows = fixture_rows().iloc[[0]].copy()  # SYNTHETIC AEDC row on real metadata columns
    rows["disco"], rows["order_file"], rows["sn"] = "AEDC", "AEDC_SYNTHETIC.pdf", "S1"
    rows["location"], rows["streets"] = "COMMERCIAL AREA", "KARSHI"
    f = fac([
        {"facility_name": "A PHC", "state_standard": "FCT, Abuja", "lga_standard": "Abuja Municipal",
         "ward_standard": "Karshi"},
        {"facility_name": "B PHC", "state_standard": "Nasarawa", "lga_standard": "Karu", "ward_standard": "Karshi"},
    ])
    m, diag = match(f, rows, grid_for(f))
    assert set(m["tier"]) != {"b_place"}
    assert diag["dropped_cross_state_b"]


# ---- tiers (c), (d) and offgrid ------------------------------------------------------------------------------

@needs_naija
def test_c_d_offgrid_and_regulator():
    rows = fixture_rows()
    f = fac([
        {"facility_name": "Unnamed Sapele PHC", "state_standard": "Delta", "lga_standard": "Sapele",
         "ward_standard": "Elume"},
        {"facility_name": "Niger PHC", "state_standard": "Niger", "lga_standard": "Bida", "ward_standard": "Masaba I"},
        {"facility_name": "Bayelsa PHC", "state_standard": "Bayelsa", "lga_standard": "Ekeremor",
         "ward_standard": "Ekeremor I"},
        {"facility_name": "Kano PHC", "state_standard": "Kano", "lga_standard": "Bichi", "ward_standard": "Bichi",
         "latitude": np.nan, "longitude": np.nan},
        {"facility_name": "Far Kano PHC", "state_standard": "Kano", "lga_standard": "Bichi", "ward_standard": "Bichi"},
    ])
    rows39 = rows[rows["sn"].ne("39")]  # drop the SAPELE row so the Sapele facility falls to tier (c)
    g = grid_for(f)
    g.loc[2, ["grid_km", "grid_target"]] = [OFFGRID_KM + 10, 0]
    g.loc[3, ["grid_km", "grid_target"]] = [np.nan, -1]
    g.loc[4, ["grid_km", "grid_target"]] = [OFFGRID_KM + 0.1, 0]
    m, _ = match(f, rows39, g)
    r = by_id(m)
    assert r["SYN_000"]["tier"] == "c_unit_mixture"
    ev = json.loads(r["SYN_000"]["evidence"])
    assert ev["unit"].startswith("business unit SAPELE") and sum(ev["band_counts"].values()) == ev["feeders"]
    assert abs(sum(json.loads(r["SYN_000"]["bands"]).values()) - 1) < 0.01
    assert r["SYN_001"]["tier"] == "d_refused" and r["SYN_001"]["reason"].startswith("state regulator")
    assert r["SYN_002"]["tier"] == "offgrid" and "Bayelsa has left NERC" in r["SYN_002"]["reason"]
    assert r["SYN_003"]["tier"] == "c_unit_mixture" and "no coordinates" in r["SYN_003"]["reason"]
    assert r["SYN_004"]["tier"] == "offgrid"


@needs_naija
def test_left_state_still_matched_when_a_row_names_it():
    rows = fixture_rows().iloc[[0]].copy()  # SYNTHETIC AEDC row naming a Niger ward
    rows["disco"], rows["order_file"], rows["sn"] = "AEDC", "AEDC_SYNTHETIC.pdf", "S2"
    rows["location"], rows["streets"] = "SULEJA", "MADALLA, SULEJA TOWN"
    f = fac([{"facility_name": "Madalla PHC", "state_standard": "Niger", "lga_standard": "Suleja",
              "ward_standard": "Madalla"}])
    m, _ = match(f, rows, grid_for(f))
    assert m.iloc[0]["tier"] == "b_place"
    assert "Niger has left NERC" in m.iloc[0]["reason"]


# ---- output contract and T2 sample ---------------------------------------------------------------------------

@needs_naija
def test_contract_and_sample(tmp_path):
    rows = fixture_rows()
    f = fac([{"facility_name": "Illah PHC", "state_standard": "Delta", "lga_standard": "Oshimili North",
              "ward_standard": "Illah"},
             {"facility_name": "Kwale PHC", "state_standard": "Delta", "lga_standard": "Ndokwa West",
              "ward_standard": "Kwale"}])
    m, _ = match(f, rows, grid_for(f))
    assert list(m.columns) == ["unique_id", "tier", "bands", "feeder_ids", "evidence", "grid_km", "reason"]
    for _, r in m[m["tier"].isin(["a_named", "b_place"])].iterrows():
        ev = json.loads(r["evidence"])
        assert {"order_file", "page", "sn", "row_text"} <= ev.keys() and ev["row_text"]
        assert clean(ev["nerc_text"]) in clean(ev["row_text"]) or ev["score"] < 100
        assert json.loads(r["feeder_ids"])
    s1 = sample.draw(m, f, tmp_path / "a.csv", n=2)
    s2 = sample.draw(m, f, tmp_path / "b.csv", n=2)
    assert s1.equals(s2) and (s1["correct"] == "").all()


@pytest.mark.skipif(not (HAVE_NAIJA and paths.FACILITIES.exists() and paths.FACILITY_GRID.exists()),
                    reason="facilities.parquet or facility_grid.parquet not built")
def test_fixture_on_real_grid3():
    f = pd.read_parquet(paths.FACILITIES)
    g = pd.read_parquet(paths.FACILITY_GRID)
    m, _ = match(f, fixture_rows(), g)
    assert m["unique_id"].is_unique and len(m) == f["unique_id"].nunique()
    ab = m[m["tier"].isin(["a_named", "b_place"])]
    assert len(ab) > 0
    # BEDC's footprint is Delta (GRID3 v3.0), Edo, Ondo and Ekiti (GRID3 v2.0)
    ids = set(ab["unique_id"])
    assert set(f[f["unique_id"].isin(ids)]["state_standard"]) <= {"Delta", "Edo", "Ondo", "Ekiti"}
    if "source_version" in f.columns:
        per_state = f.groupby("state_standard")["source_version"].nunique()
        assert (per_state == 1).all(), "a state must come from one GRID3 version"


@needs_naija
def test_amendment1_state_name_is_not_an_lga():
    rows = fixture_rows().iloc[[0]].copy()  # SYNTHETIC JEDC row on real metadata columns
    rows["disco"], rows["order_file"], rows["sn"] = "JEDC", "JED_SYNTHETIC.pdf", "S3"
    rows["location"], rows["streets"] = "BAUCHI STATE", "GOMBE, BAUCHI, KAGADAMA"
    f = fac([
        {"facility_name": "X PHC", "state_standard": "Bauchi", "lga_standard": "Bauchi", "ward_standard": "Makama"},
        {"facility_name": "Y PHC", "state_standard": "Gombe", "lga_standard": "Gombe", "ward_standard": "Herwagana"},
        {"facility_name": "Z PHC", "state_standard": "Bauchi", "lga_standard": "Bauchi",
         "ward_standard": "Kagadama"},
    ])
    m, _ = match(f, rows, grid_for(f))
    r = by_id(m)
    assert r["SYN_000"]["tier"] != "b_place" and r["SYN_001"]["tier"] != "b_place"
    assert r["SYN_002"]["tier"] == "b_place"
    assert json.loads(r["SYN_002"]["evidence"])["nerc_text"] == "KAGADAMA"


# ---- amendment 2: tier (a) recall, LGA evidence as c_lga_mixture ---------------------------------------------

def _row(disco, file, sn, feeder, location, streets, band="A"):
    """SYNTHETIC row with the nerc_rows contract columns."""
    return {"disco": disco, "order_file": file, "order_month": "2026-09", "page": 1, "sn": sn, "band": band,
            "feeder_name": feeder, "location": location, "streets": streets, "min_hours": 20.0,
            "ocr_confidence": None, "crop_path": None}


def test_clean_ocr_glue_and_typos():
    assert clean("FEDEREAL MEDICALCENTERGOMBE") == "FEDERAL MEDICAL CENTRE GOMBE"
    assert clean("BICHI GENERAL HOSPITALS.") == "BICHI GENERAL HOSPITAL"
    assert clean("PHYCHIATRIC") == "PSYCHIATRIC" and clean("TACHIN") == "TACHIN"


@needs_naija
def test_tier_a_abbreviations_word_order_and_context():
    rows = pd.DataFrame([
        _row("JEDC", "J.pdf", 1, "FMC GOMBE", "GOMBE TOWN", "FEDEREAL MEDICAL CENTER GOMBE"),
        _row("AEDC", "A.pdf", 2, "33KV FDR L4", "KWALI", "GENERAL HOSPITAL, KWALI MARKET"),
        _row("KAEDC", "K.pdf", 3, "11KV GOVT HOUSE", "POWER HOUSE", "YARIMAN BAKURA HOSPITAL, WATER BOARD"),
        _row("IBEDC", "I.pdf", 4, "OGBOMOSO 33KV", "ILORIN", "LAUTECH TEACHING HOSPITAL COMMUNITY"),
        _row("KEDCO", "K2.pdf", 5, "11KV FMC", "KOFAR GUGA", "KOFAR YANDAKA BEHIND FMC KATSINA"),
        _row("AEDC", "A.pdf", 6, "33KV FDR", "WUSE", "MINISTRY OF HEALTH AND EDUCATION"),
    ])
    f = fac([
        {"facility_name": "Gombe Federal Medical Center", "state_standard": "Gombe", "lga_standard": "Gombe",
         "ward_standard": "Herwagana"},
        {"facility_name": "Kwali General Hospital", "state_standard": "FCT, Abuja", "lga_standard": "Kwali",
         "ward_standard": "Kwali"},
        {"facility_name": "Yariman Bakura Specialist Hospital", "state_standard": "Zamfara",
         "lga_standard": "Gusau", "ward_standard": "Galadima"},
        {"facility_name": "Lautech Teaching Hospital", "state_standard": "Osun", "lga_standard": "Osogbo",
         "ward_standard": "Ataoja A"},
        {"facility_name": "Katsina Federal Medical Center", "state_standard": "Katsina", "lga_standard": "Katsina",
         "ward_standard": "Wakilin Yamma I"},
        {"facility_name": "Wuse Health Centre", "state_standard": "FCT, Abuja", "lga_standard": "Municipal Area Council",
         "ward_standard": "City Centre"},
    ])
    m, _ = match(f, rows, grid_for(f))
    r = by_id(m)
    assert [r[f"SYN_00{i}"]["tier"] for i in range(3)] == ["a_named"] * 3
    ev = json.loads(r["SYN_001"]["evidence"])
    assert "context from location" in ev["nerc_text"] and "KWALI" in ev["row_text"]
    assert r["SYN_003"]["tier"] != "a_named", "a hospital's community is an area, not the hospital"
    assert r["SYN_004"]["tier"] != "a_named", "behind FMC is a landmark, not the customer"
    assert r["SYN_005"]["tier"] != "a_named", "a ministry of health is not a facility"
    for i in range(3):
        e = json.loads(r[f"SYN_00{i}"]["evidence"])
        assert e["row_text"] and e["order_file"] and e["sn"]


@needs_naija
def test_lga_name_gives_c_lga_mixture_not_b():
    rows = fixture_rows()  # S/N 39 location 'SAPELE' names Sapele LGA; S/N 39 streets name Ugberikoko ward
    f = fac([
        {"facility_name": "Elume PHC", "state_standard": "Delta", "lga_standard": "Sapele", "ward_standard": "Elume"},
        {"facility_name": "Ugborikoko PHC", "state_standard": "Delta", "lga_standard": "Sapele",
         "ward_standard": "Ugborikoko"},
    ])
    m, _ = match(f, rows, grid_for(f))
    r = by_id(m)
    assert r["SYN_001"]["tier"] == "b_place"
    assert r["SYN_000"]["tier"] == "c_lga_mixture"
    ev = json.loads(r["SYN_000"]["evidence"])
    assert ev["rows_total"] == sum(ev["band_counts"].values()) == len(json.loads(r["SYN_000"]["feeder_ids"]))
    assert ev["sn"] == "39" and ev["row_text"] and ev["rows"]
    assert abs(sum(json.loads(r["SYN_000"]["bands"]).values()) - 1) < 0.01


@needs_naija
def test_amendment3_candidate_must_be_in_the_rows_state():
    rows = pd.DataFrame([_row("EEDC", "E.pdf", 1, "AFARA 33KV", "UMUAHIA", "GOVT. HOUSE, MADONNA HOSPITAL")])
    f = fac([
        {"facility_name": "Madonna Hospital", "state_standard": "Anambra", "lga_standard": "Onitsha North",
         "ward_standard": "Inland Town"},
        {"facility_name": "Umuahia PHC", "state_standard": "Abia", "lga_standard": "Umuahia North",
         "ward_standard": "Ibeku East I"},
    ])
    m, _ = match(f, rows, grid_for(f))
    assert by_id(m)["SYN_000"]["tier"] != "a_named", "UMUAHIA is in Abia; a Madonna Hospital in Anambra is not it"
