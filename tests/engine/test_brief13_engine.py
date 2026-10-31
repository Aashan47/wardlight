"""Brief 13: the 60-day window, new critical-load sectors, city metrics, cost bars, corridor and roofs."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from engine import augment as AU
from engine import constants as C
from engine import econ as E
from engine import metrics13 as M
from engine import outage as O
from engine import paths
from engine import sector as X
from engine import sim as SM
from engine import sites13 as ST

from .conftest import needs_nasa

CFG = SM.SimConfig(n_draws=8)
HAS_IMMAP = ST.IMMAP_CSV.exists() and ST.OSM_OBJECTS.exists()
HAS_CORRIDOR = ST.CORRIDOR.exists()
HAS_WORK = all(p.exists() for p in (paths.FACILITIES, paths.MATCHES, paths.FACILITY_RESULTS))


# ---------------------------------------------------------------- step 1: 60 days, diesel price


def test_sixty_day_window_everywhere():
    assert 60 in O.DEFAULT_DAYS and 60 in O.ORFIX_EVAL_DAYS and O.ORFIX_SIZED_FOR == (7, 40)
    m, _ = O.window_mask(3, 8760, 60, seed=2)
    assert (m.sum(axis=1) == 1440).all()


def test_diesel_price_is_the_may_2026_nbs_figure():
    c = C.DIESEL_NGN_PER_L
    assert c.value == 3277.47 and c.lo == 1441.28 and c.status == "VERIFIED_SECONDARY"
    assert "four outlets agree" in c.source and "NBS Diesel Price Watch May 2026" in c.source


def test_augment_finds_missing_windows_and_refreshes_naira():
    cols = [f"out{d}_window_h" for d in (3, 7, 14, 40)] + [f"orfix_at{d}_hours_kept" for d in (14, 40)]
    assert AU.missing(cols) == ([60], [60])
    res = pd.DataFrame({"diesel_l_avoided": [120.0], "diesel_l_avoided_lo": [96.0], "diesel_l_avoided_hi": [144.0],
                        "clinic_capex_usd": [6000.0], "clinic_capex_usd_lo": [5300.0], "clinic_capex_usd_hi": [6500.0],
                        "diesel_ngn_month_avoided": [0.0], "diesel_ngn_month_avoided_lo": [0.0],
                        "diesel_ngn_month_avoided_hi": [0.0], "payback_months": [0.0], "payback_months_lo": [0.0],
                        "payback_months_hi": [0.0]})
    out = AU.refresh_diesel_naira(res)
    assert out.diesel_ngn_month_avoided.iloc[0] == pytest.approx(120 * 3277.47 / 12)
    assert out.diesel_ngn_month_avoided_lo.iloc[0] == pytest.approx(96 * 1441.28 / 12)


@pytest.mark.skipif(not HAS_WORK, reason="data/work not built")
def test_results_carry_the_sixty_day_columns():
    import pyarrow.parquet as pq

    names = pq.ParquetFile(paths.FACILITY_RESULTS).schema.names
    for c in ("out60_window_h", "out60_hours_today", "out60_needed_h", "orfix_at60_hours_kept",
              "orfix_at60_diesel_l_avoided_hi"):
        assert c in names


# ---------------------------------------------------------------- step 2: sectors


def test_pump_power_formula_and_range():
    p = X.pump_kw(1.0)  # 1 L/s
    assert p.point == pytest.approx(1000 * 9.80665 * 40 * 0.001 / 0.45 / 1000)
    assert p.lo == pytest.approx(1000 * 9.80665 * 30 * 0.001 / 0.60 / 1000)
    assert p.hi == pytest.approx(1000 * 9.80665 * 70 * 0.001 / 0.40 / 1000)
    assert X.pump_kw(0.5).point == pytest.approx(p.point / 2)


def test_window_start_centres_on_midday():
    assert X.window_start(8) == 8 and X.window_start(12) == 6 and X.window_start(24) == 0
    ld = X.unit_load(8, 8)
    assert ld.wh_per_day == 8000 and ld.hourly_kw()[8:16].sum() == 8


def test_new_constants_are_labelled_ranges():
    for n in ("BH_PUMP_HEAD_M", "BH_PUMP_EFF", "WATER_WORKS_KW", "ROOF_USABLE_FRACTION", "PV_KWP_PER_M2",
              "SOLAR_BH_ARRAY_KWP_PER_KW"):
        c = C.REGISTRY[n]
        assert c.status == "ASSUMPTION" and c.is_range, n
    assert (C.BH_PUMP_HEAD_M.value, C.BH_PUMP_HEAD_M.lo, C.BH_PUMP_HEAD_M.hi) == (40, 30, 70)
    assert (C.BH_PUMP_EFF.value, C.BH_PUMP_EFF.lo, C.BH_PUMP_EFF.hi) == (0.45, 0.40, 0.60)
    assert C.MEPP_SUPPORT_NGN_PER_MONTH.value == 2e9 and C.MEPP_SUPPORT_NGN_PER_MONTH.status == "VERIFIED_SECONDARY"
    assert (C.MEPP_AVG_DELIVERED_MW.value, C.MEPP_AVG_DELIVERED_MW.hi) == (14.2, 50)


def test_sourced_generator_curves_and_water_standard():
    assert (C.GEN_L_PER_KWH.value, C.GEN_L_PER_KWH.lo, C.GEN_L_PER_KWH.hi) == (0.55, 0.40, 0.73)
    assert (C.GEN_L_PER_KWH_MID.value, C.GEN_L_PER_KWH_MID.lo, C.GEN_L_PER_KWH_MID.hi) == (0.34, 0.31, 0.40)
    assert C.WATER_L_PER_PERSON_DAY.value == 15 and C.WATER_L_PER_PERSON_DAY.status == "VERIFIED"
    assert C.COLDHUB_PV_KWP.value == 5.5 and C.GENSET_20KVA_NGN.value == 9.3e6
    assert "oil" not in C.MEPP_FUEL and "natural gas" in C.MEPP_FUEL
    assert M.gen_curve("health") is C.GEN_L_PER_KWH and M.gen_curve("water") is C.GEN_L_PER_KWH_MID
    assert M.genset_for("health", 0)[1] == 9.3e6 and M.genset_for("water", 3.0)[1] == 8.3e6
    assert M.genset_for("water", 100.0) == ("2 x 100 kVA sets", 2 * 24.4e6)


@needs_nasa
def test_grid_site_goes_dark_today_and_the_system_keeps_it():
    pp = SM.prepare(11.84, 13.15, {"C": 1.0}, CFG)
    r = X.run_profile(pp, 24, 0, "grid", CFG)
    w7 = r.windows[7]
    assert w7.needed_h == 168 and w7.today_h.point == 0  # the grid is off through the window
    assert r.target_met and r.crit_share_lo >= 0.95
    assert w7.with_h.lo >= 0.95 * 168 - 1e-9
    assert w7.system_kwh.point == pytest.approx(w7.with_h.point, rel=1e-6)  # 1 kW for every hour kept
    assert r.windows[60].needed_h == 1440
    assert r.annual_kwh_per_kw.point <= 24 * 366


@needs_nasa
def test_solar_borehole_pumps_in_daylight_today_and_more_with_storage():
    pp = SM.prepare(11.84, 13.15, "OFFGRID", CFG)
    r = X.run_profile(pp, 12, X.window_start(12), "solar_direct", CFG)
    w = r.windows[14]
    assert 0 < w.today_h.point < w.needed_h
    assert w.with_h.point > w.today_h.point
    assert w.base_kwh.point == pytest.approx(w.today_h.point)  # 1 kW pump: pump-hours equal kWh


@pytest.mark.skipif(not (HAS_IMMAP and HAS_WORK), reason="survey, OSM or data/work not present")
def test_maiduguri_sites_from_the_survey_and_osm():
    sites, excl = ST.city_sites("maiduguri")
    arch = pd.Series([s.archetype for s in sites]).value_counts()
    assert excl["water"]["hand_pump_no_power_need"] == 43
    assert arch["solar_borehole"] + excl["water"].get("no_yield_recorded", 0) + \
        excl["water"].get("not_operating_at_survey", 0) + arch["motorized_borehole"] == 103 + 36
    assert arch["water_works"] == 1 and arch["market_cold_room"] == 8
    names = {s.name for s in sites if s.sector == "cold"}
    assert "Bama Motor Park Shopping centre" in names and "Sahad Stores" not in names
    bama = next(s for s in sites if s.name == "Bama Motor Park Shopping centre")
    assert bama.ref["deduplicated_objects"] > 1
    umth = [s for s in sites if s.existing_onsite]
    assert umth and all("1424431051" in s.note and "1561720799" in s.note for s in umth)
    for s in sites:
        if s.archetype == "motorized_borehole":
            assert s.kw_lo < s.kw < s.kw_hi and s.mode == "grid"
        if s.archetype == "solar_borehole":
            assert s.mode == "solar_direct" and s.bands == "OFFGRID"
    d, _ = ST.city_sites("damaturu")
    assert d and all(s.sector == "health" for s in d)


# ---------------------------------------------------------------- step 3 and 4: metrics and cost bars


def _site(i, sector, onsite=False, m3=None):
    return ST.Site(f"{sector}-{i}", sector, "x", f"site {i}", "maiduguri", "Maiduguri", 11.8, 13.1, 1, 1, 1,
                   daily_m3=m3, existing_onsite=onsite)


def _res(needed, today, with_, litres, energy, lc=1.0e6, annual=1000.0, kwp=1.0):
    r = {"point": litres, "lo": litres * 0.8, "hi": litres * 1.2}
    return {"system": {"pv_kwp": kwp, "battery_kwh": kwp * 7.2, "capex_ngn": {"point": lc / 2, "lo": lc / 3,
                                                                             "hi": lc / 1.5},
                       "clinic_lifecycle_ngn": {"point": lc, "lo": lc * 0.9, "hi": lc * 1.1}},
            "annual_kwh": {"point": annual, "lo": annual * 0.9, "hi": annual * 1.05},
            "by_days": {60: {"needed_h": needed, "today_h": today, "with_h": with_, "generator_litres": r,
                             "diesel_l_avoided": r, "needed_kwh": energy, "local_today_kwh": 0.0,
                             "local_with_kwh": energy * with_ / needed, "m3_day": None}}}


def test_city_metrics_sums_sectors_and_leaves_out_existing_onsite():
    sites = [_site(1, "health"), _site(2, "water", m3=30.0), _site(3, "cold"), _site(4, "health", onsite=True)]
    res = {"health-1": _res(100, 10, 95, 20, 50), "water-2": _res(200, 100, 200, 40, 80),
           "cold-3": _res(50, 0, 50, 10, 20), "health-4": _res(1000, 0, 1000, 999, 999)}
    res["water-2"]["by_days"][60]["m3_day"] = 30.0
    siting = {s.id: {"roof": {"fit": "fits"}, "km_to_330kv": 5.0} for s in sites}
    m = M.city_metrics("maiduguri", sites, res, 60, {}, {"km_330": 745.0, "towers": 2707}, siting)
    i = m["impact"]
    assert i["csh_needed"] == 350 and i["csh_today"] == 110 and i["csh_with"] == 345
    assert i["csh_today_diesel"] == 350
    assert i["by_sector"]["health"]["sites"] == 1 and i["diesel_l_avoided"]["point"] == 70
    assert i["diesel_ngn_avoided"]["point"] == pytest.approx(70 * 3277.47)
    assert i["water_m3_per_day_kept"] == {"today": 15.0, "with": 30.0}
    assert i["people_served"]["with"] == pytest.approx(30 * 1000 / 15)
    assert m["innovation"]["new_line_km"] == 0 and m["innovation"]["corridor"]["towers"] == 2707
    assert m["innovation"]["sites"] == 3 and m["excluded"]["existing_onsite"][0]["id"] == "health-4"
    assert m["feasibility"]["roof_fit"] == {"fits": 3, "partial": 0, "ground": 0, "unknown": 0}
    assert m["sustainability"]["co2_t_avoided"]["point"] == pytest.approx(70 * 2.697 / 1000)
    assert "98.6%" in m["headline"] and "two months" in m["headline"]  # 345/350 = 0.98571, half-up
    assert "ASSUMPTION" in json.dumps(m["labels"]) and m["sources"]
    own = {o["sector"]: o for o in m["sustainability"]["ownership"]}
    assert set(own) == {"health", "water", "cold"} and "RUWASA" in own["water"]["owns"]
    assert "Water Corporation" not in json.dumps(m) and "ColdHubs" in own["cold"]["precedent"]
    sec = m["feasibility"]["security"]
    assert any("World Bank" in x["basis"] for x in sec) and any("our design standard" in x["basis"] for x in sec)
    assert chr(0x2014) not in json.dumps(m)


def test_cost_bars_and_gas_breakeven():
    sites = [_site(1, "health")]
    res = {"health-1": _res(1, 1, 1, 1, 1, lc=15e6, annual=1500.0)}
    c = M.cost_bars(sites, res)
    solar = c["cost_per_kwh_ngn"]["solar"]
    assert solar["point"] == pytest.approx(15e6 / (1500 * 15))
    assert solar["lo"] < solar["point"] < solar["hi"]
    f = c["cost_per_kwh_ngn"]["diesel_fuel_only"]
    assert f["point"] == pytest.approx(3277.47 * 0.55) and f["lo"] == pytest.approx(1441.28 * 0.40)
    d = c["cost_per_kwh_ngn"]["diesel"]
    om = 0.03 * C.FX_NGN_PER_USD.value
    assert d["point"] == pytest.approx(f["point"] + om + 9.3e6 / 10 / 1500)  # fuel + O&M + 20 kVA set over 10 years
    assert d["lo"] > f["lo"] and d["hi"] > f["hi"]
    g = c["cost_per_kwh_ngn"]["gas_support"]
    hpm = 24 * 30.4375
    assert g["point"] == pytest.approx(2e9 / (14_200 * hpm)) and g["point"] == pytest.approx(192.8, abs=0.1)
    assert g["lo"] == pytest.approx(2e9 / (50_000 * hpm)) and g["hi"] == g["point"]
    be = c["gas_breakeven"]["mw"]["point"]
    assert 2e9 / (be * 1000 * hpm) == pytest.approx(solar["point"])  # support per kWh equals solar at break-even
    assert c["gas_breakeven"]["mwh_per_month"]["point"] == pytest.approx(be * hpm)
    assert "tariff and capital not included" in c["labels"]["gas_support"]


def test_pct_rounds_half_up_and_never_claims_a_full_share():
    assert M._pct_text(0.06889) == "6.9" and M._pct_text(0.9985) == "99.9" and M._pct_text(0.06849) == "6.8"
    assert M.pct1(0.0685) == 6.9 and M._pct_text(0.99996) == "99.9" and M._pct_text(1.0) == "100"


# ---------------------------------------------------------------- corridor, roofs


def test_rdp_keeps_endpoints_and_drops_collinear_points():
    pts = [(0, 0), (1, 0.00001), (2, 0), (3, 1)]
    out = M._rdp(pts, 0.001)
    assert out[0] == (0, 0) and out[-1] == (3, 1) and (1, 0.00001) not in out


@pytest.mark.skipif(not HAS_CORRIDOR, reason="corridor extract not present")
def test_corridor_stats_and_simplified_geojson_size():
    s = M.corridor_stats()
    assert s["towers"] == 2707 and 700 < s["km_330"] < 800
    g = M.corridor_geojson()
    assert len(json.dumps(g)) < 1_000_000
    assert any(f["properties"].get("power") == "tower" for f in g["features"])


def _sq(lat, lon, half_m):
    d = half_m / 111_320.0
    return [(lat - d, lon - d), (lat - d, lon + d), (lat + d, lon + d), (lat + d, lon - d)]


def _bld(rows):
    return pd.DataFrame([{"osm_id": i, "lat": la, "lon": lo, "area_m2": (2 * h) ** 2, "ring": _sq(la, lo, h)}
                         for i, la, lo, h in rows])


def test_tight_roof_rule():
    lat, lon = 11.8, 13.1
    d = 1 / 111_320.0
    b = _bld([(1, lat, lon, 10.0), (2, lat + 20 * d, lon, 5.0), (3, lat + 100 * d, lon, 30.0)])
    r = ST.roof(lat, lon, b)
    assert r["rule"] == "contains_point" and r["buildings"] == 1 and r["footprint_m2"] == 400
    assert r["roof_kwp"]["point"] == pytest.approx(400 * 0.5 * 0.15)
    assert ST.roof_fit(10.0, r) == "fits" and ST.roof_fit(50.0, r) == "partial"
    # no building contains the point: the single nearest within 30 m (building 2's edge is 15 m away)
    r2 = ST.roof(lat - 10 * d, lon, b.iloc[1:])
    assert r2["rule"].startswith("nearest") and r2["osm_ids"] == [2]
    # nothing within 30 m but buildings mapped nearby: ground; nothing mapped within 250 m: unknown
    r3 = ST.roof(lat - 60 * d, lon, b.iloc[1:])
    assert r3["buildings"] == 0 and ST.roof_fit(1.0, r3) == "ground"
    r4 = ST.roof(lat - 2000 * d, lon, b)
    assert ST.roof_fit(1.0, r4) == "unknown"
    # a site mapped as an outline takes every building touching it
    site = _sq(lat + 60 * d, lon, 45.0)
    r5 = ST.roof(lat + 60 * d, lon, b, [site])
    assert r5["rule"] == "site_outline" and set(r5["osm_ids"]) == {2, 3}


def test_distance_to_line():
    km = ST.km_to_lines(11.8, 13.1, [[(11.7, 13.0), (11.7, 13.2)]])
    assert km == pytest.approx(ST.dist_m(11.8, 13.1, 11.7, 13.1) / 1000, rel=1e-6)  # haversine to the nearest point


@needs_nasa
def test_daily_cycle_arm_is_smaller_battery_and_reported():
    pp = SM.prepare(11.84, 13.15, {"C": 1.0}, CFG)
    r = X.run_profile(pp, 24, 0, "grid", CFG)
    assert r.daily is not None and r.daily.kwh_per_kw < r.kwh_per_kw
    assert set(r.daily.windows) == set(X.EVAL_DAYS)
    for d in (14, 40, 60):
        assert r.daily.windows[d].with_h.point <= r.daily.windows[d].needed_h


def test_cost_arms_and_gas_position():
    sites = [_site(1, "health"), _site(2, "water")]
    res = {"health-1": _res(100, 0, 100, 1, 1, lc=10e6, annual=1000.0),
           "water-2": _res(100, 0, 100, 1, 1, lc=10e6, annual=1000.0)}
    for k in res:
        res[k]["system"]["clinic_capex_ngn"] = res[k]["system"]["capex_ngn"]
        res[k]["by_days"] = {d: dict(res[k]["by_days"][60]) for d in (14, 40, 60)}
        res[k]["daily_arm"] = {"annual_kwh": {"point": 800.0, "lo": 700.0, "hi": 900.0},
                               "lifecycle_ngn": {"point": 6e6, "lo": 5e6, "hi": 7e6},
                               "capex_ngn": {"point": 3e6, "lo": 2e6, "hi": 4e6},
                               "by_days": {d: {"needed_h": 100.0, "with_h": 90.0} for d in (14, 40, 60)}}
    a = M.cost_arms(sites, res)
    assert a["outage_ready_7d"]["cost_per_kwh_ngn"]["point"] == pytest.approx(20e6 / (2000 * 15))
    assert a["daily_cycle"]["cost_per_kwh_ngn"]["point"] == pytest.approx(12e6 / (1600 * 15))
    assert a["daily_cycle"]["csh"]["60"]["share"] == pytest.approx(0.9)
    assert a["outage_ready_7d"]["csh"]["14"]["share"] == 1.0 and a["sites"] == 2
    c = M.cost_bars(sites, res)
    t = c["gas_tariff_cost_reflective"]
    assert t["ngn_per_kwh"] == pytest.approx(0.1588 * C.FX_NGN_PER_USD.value)
    assert t["nbet_paid_ngn_per_kwh"] == pytest.approx(0.062 * C.FX_NGN_PER_USD.value)
    g = M.gas_position(c)
    assert g["gas_cheaper_when_running"] and "cheaper per kWh" in g["text"]
    assert "works alongside the gas plant" in g["text"] and "road tanker" in g["fuel"]
    assert g["brief_constraint"] == "Work alongside the existing gas plant and distribution company, not replace them"


@pytest.mark.skipif(not (M.OUT / "meta.json").exists(), reason="brief 13 build not run")
def test_built_maiduguri_metrics_are_complete():
    for d in M.DAYS:
        m = json.loads((M.OUT / f"metrics-maiduguri-{d}.json").read_text())
        i = m["impact"]
        assert set(i["by_sector"]) == {"health", "water", "cold"}
        assert i["csh_today"] <= i["csh_with"] <= i["csh_needed"] + 1e-6
        assert i["diesel_l_avoided"]["lo"] <= i["diesel_l_avoided"]["point"] <= i["diesel_l_avoided"]["hi"]
        assert m["innovation"]["new_line_km"] == 0
        assert all(m["sustainability"]["cost_per_kwh_ngn"][k] for k in ("solar", "diesel", "gas_support"))
        assert not math.isnan(m["sustainability"]["gas_breakeven_mw"]["point"])
    g = json.loads((M.OUT / "sites-maiduguri.geojson").read_text())
    umth = [f for f in g["features"] if f["properties"]["existing_onsite"]]
    assert umth and all(f["properties"]["in_plan"] is False and f["properties"]["system"] is None for f in umth)
    assert np.all([f["properties"]["sector"] in ("health", "water", "cold") for f in g["features"]])


def _walk(x, path=""):
    if isinstance(x, dict):
        yield path, x
        for k, v in x.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _walk(v, f"{path}[{i}]")


def test_every_label_key_has_a_status():
    for k in M.LABELS:
        assert M.LABEL_STATUS[k] in ("VERIFIED", "VERIFIED_SECONDARY", "DERIVED", "ASSUMPTION", "UNVERIFIED")
    for s in M.SOURCES:
        assert set(s) == {"text", "url", "status"} and (s["url"] is None or s["url"].startswith("https://"))
    assert all(x["status"] in ("VERIFIED", "ASSUMPTION") for x in M.SECURITY)


@pytest.mark.skipif(not (M.OUT / "meta.json").exists(), reason="brief 13 build not run")
def test_built_payloads_carry_status_rank_ids_and_version():
    m = json.loads((M.OUT / "metrics-maiduguri-60.json").read_text())
    assert m["data_version"] and m["data_version"] == json.loads((M.OUT / "meta.json").read_text())["data_version"]
    for path, d in _walk(m):
        if "labels" in d and isinstance(d["labels"], dict):
            st = d.get("label_status")
            assert st is not None, path
            assert set(d["labels"]) <= set(st), path
    assert f"{M._pct_text(m['impact']['share_today'])}%" in m["headline"]
    g = json.loads((M.OUT / "sites-maiduguri.geojson").read_text())
    props = [f["properties"] for f in g["features"]]
    ranked = sorted((p for p in props if p["rank"]), key=lambda p: p["rank"])
    assert [p["rank"] for p in ranked] == list(range(1, len(ranked) + 1))
    gain = [p["results"]["60"]["with_h"] - (p["results"]["60"]["today_h"] or 0) for p in ranked]
    assert gain == sorted(gain, reverse=True)
    assert all(p["rank"] is None for p in props if p["existing_onsite"])
    for p in props:
        assert p["kw"] is not None and set(p["label_status"] or {}) >= set(p["labels"] or {})
        assert (p["facility_id"] == p["id"][2:]) if p["sector"] == "health" else p["facility_id"] is None


@pytest.mark.skipif(not HAS_CORRIDOR, reason="corridor extract not present")
def test_distance_is_haversine_to_any_330kv_segment_including_the_maiduguri_substation():
    lines = ST.corridor_lines()
    # the Maiduguri 330/132 kV substation outline is a target: a point on it is 0 km away
    assert any(abs(a - 11.7403) < 0.003 and abs(o - 13.0821) < 0.003 for ln in lines for a, o in ln)
    km = ST.km_to_lines(12.142116, 13.144416, lines)  # Tuba Lawanti Health Post, Jere
    best = min(ST.dist_m(12.142116, 13.144416, a1 + (a2 - a1) * k / 100, o1 + (o2 - o1) * k / 100)
               for ln in lines for (a1, o1), (a2, o2) in zip(ln, ln[1:]) for k in range(101)) / 1000
    assert km == pytest.approx(best, abs=0.02) and 38.0 < km < 38.6


@needs_nasa
def test_sector_trace_shape():
    t = X.trace(11.84, 13.15, "OFFGRID", 8, 8, "solar_direct", 1.0, 2.0, 14.4, 3, CFG)
    n = len(t["hour"])
    assert sum(t["in_outage"]) == 72 and n == 72 + 24
    for k in ("grid_on", "solar_kw", "load_kw", "battery_soc", "served_with", "served_today", "existing_array_kw"):
        assert len(t[k]) == n, k
    assert all(w >= d for w, d in zip(t["served_with"], t["served_today"]) if w is not None)
