"""Brief 13 city metrics M1 to M5 (14-SUCCESS-METRICS.md), sites GeoJSON, siting cards and the corridor.

    python -m engine.metrics13 [--cities maiduguri,damaturu,yola] [--out data/work/brief13] [--workers N]

Writes, per city, `metrics-{city}-{days}.json` for days in DAYS, `sites-{city}.geojson`, `siting-{city}.json`, and
once `corridor.geojson` and `meta.json`. The API serves these files; nothing is simulated per request.

Method, per site and outage window (engine.outage.window_mask, the same lanes as the health batch):
- Health: the batch columns. Needed and today from `out{N}_*`; with the plan = the 7-day outage-ready fix
  (`orfix_*` at 7 days, `orfix_at{N}_*` otherwise). Energy needed = the generator scenario's litres / GEN_L_PER_KWH
  point; energy the plan delivers = its diesel avoided / the same point (both are that product in engine.outage).
- Water and cold: engine.sector.run_profile at 1 kW, scaled by the site's kW.
- "Today with diesel": a labelled scenario in which every site has a generator and fuel through the window, so
  every needed hour is kept and the fuel is the generator scenario's litres.
- UMTH (existing_onsite) is shown on the map and left out of every total and of the fix list.
Sums are sums of per-site medians; lo and hi are sums of per-site low and high ends (wider than a joint interval).

Cost per kWh delivered (no discounting, as engine.econ):
- solar + storage: life-cycle cost (capex at SEforALL $/Wp, O&M 5%/yr, 15 years, 15% replacement at year 10) over
  the energy the systems deliver in 15 years when they run their critical loads first from solar (no grid). Health:
  the clinic system only (the vaccine fridge is priced in the fix but not in this bar).
- diesel: for the same critical kWh, fuel (price x the site's generator curve: clinic set for health, 20 to 60 kVA
  set otherwise) + O&M (USD 0.03/kWh, 2016 data) + the listed set's retail price over a 10-year life; fuel only is
  given as the lower bound.
- gas plant: federal operating support only (N2bn a month) over the plant's monthly output, point at the 14.2 MW daily
  average delivered (Dec 2024, NAN) and up to the 50 MW nameplate; tariff and capital not included. Break-even: the
  average MW at which that support per kWh equals the solar cost per kWh.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import constants as C
from . import econ as E
from . import fridge as F
from . import loads as LD
from . import paths
from . import sector as X
from . import sim as SM
from . import sites13 as ST
from . import solar as S
from . import supply as SP

DAYS: tuple[int, ...] = (7, 14, 40, 60)
OUT = paths.WORK / "brief13"
HOURS_PER_MONTH = 24.0 * C.DAYS_PER_MONTH.value
SECTORS = ("health", "water", "cold")
GEN = C.GEN_L_PER_KWH  # clinic set: health facilities
GEN_MID = C.GEN_L_PER_KWH_MID  # 20 to 60 kVA set: boreholes, cold rooms, the water works
WB_PUMPING = "World Bank, 'Solar Pumping: The Basics' (2018), p. 27 to 28"
GAZETTE_2024 = ("Peoples Gazette, 'Governor Zulum promises solar-powered boreholes amid water crisis in Borno', "
                "9 Apr 2024")


def gen_curve(sector: str) -> C.Const:
    return GEN if sector == "health" else GEN_MID


LABELS = {
    "scenario_today": "today: no backup; the grid is forced off for the whole window (the line, or the gas plant, "
                      "cannot reach the feeder); existing solar boreholes pump in daylight only",
    "scenario_today_diesel": "today with diesel: a labelled scenario in which every site has a generator and fuel "
                             "for the whole window; every needed hour is kept at the fuel bill shown",
    "scenario_with": "with the plan: a solar + storage system at each site, sized to keep at least 95% of its "
                     "critical hours at the pessimistic end (5th percentile) in a 7-day outage, run through this window",
    "supply": "modelled from the NERC band promise (calibrated), as for the health facilities; promised, not measured",
    "diesel": "generator fuel curves DERIVED from Cummins data sheets: clinic set 0.40 to 0.73 L/kWh (point 0.55) for "
              "health; 20 to 60 kVA set 0.31 to 0.40 (point 0.34) for water and cold; fuel replaced where a "
              "generator would run",
    "diesel_price": "N3,277.47 per litre, national average: NBS Diesel Price Watch May 2026 via four outlets "
                    "(VERIFIED_SECONDARY); low end NBS Oct 2024 N1,441.28; Borno April 2026 was N2,684.95",
    "water": "pump kW from the iMMAP 2019 yield with an ASSUMPTION upper-aquifer head (30 to 70 m, point 40) and "
             "efficiency (0.40 to 0.60, point 0.45); deep lower-aquifer boreholes differ; survey from March 2019, "
             "statuses may have changed",
    "water_works": "the water works load is an ASSUMPTION (30 to 300 kW); partner needed",
    "cold": "one ColdHubs-type cold room per named market (5.5 kWp, about 3 t, VERIFIED_SECONDARY); its kWh/day is "
            "DERIVED from that array's yield at the market (NASA POWER, engine PV model)",
    "people_served": "m3 per day / 0.015: Sphere 2018 minimum of 15 L per person per day (VERIFIED); a minimum, so "
                     "this is an upper count of people",
    "umth": ST.UMTH_NOTE + "; shown on the map, not fixed by this plan and left out of the totals",
    "sums": "sums of per-site medians; lo and hi sum per-site low and high ends, wider than a joint interval",
    "ownership": "PROPOSED model with the precedent named in each row; operators to be confirmed with partners",
    "security": "each measure names its basis: the World Bank's anti-theft list, or our design standard",
    "gas_support": "operating support only; tariff and capital not included",
    "gas_fuel": C.MEPP_FUEL,
    "gas_tariff": C.MEPP_TARIFF_NOTE,
    "cost_solar": "life-cycle cost over energy delivered in 15 years when the systems run their critical loads first "
                  "from solar; undiscounted; health counts the clinic system only",
    "cost_diesel": "fuel + O&M (USD 0.03/kWh, NESG/Boell 2017 from 2016 data) + the set's retail price (one Lagos "
                   "retailer) over a 10-year life, for the same critical kWh the solar systems deliver; fuel only is "
                   "shown as the lower bound",
    "roof": "footprints from OSM building outlines: the buildings touching the site's own OSM outline, else the "
            "buildings containing the site point, else the single nearest building within 30 m; usable roof = "
            "footprint x an ASSUMPTION usable share (0.3 to 0.7) x an ASSUMPTION 0.12 to 0.20 kWp per m2; no building: "
            "ground inside the compound, or unknown where OSM maps no building within 250 m",
}

def src(text: str, url: str | None = None, status: str | None = None) -> dict:
    """A source entry: its text, its URL where docs/sources/brief13-sources.md, engine.md or MANIFEST.md records one
    (else null), and its grade where it has one."""
    return {"text": text, "url": url, "status": status}


URL = {
    "grid3": "https://data.humdata.org/dataset/grid3-nga-health-facilities-v3-0",
    "geofabrik": "https://download.geofabrik.de/africa/nigeria-latest.osm.pbf",
    "overpass": "https://overpass-api.de/api/interpreter",
    "yedc": "https://nerc.gov.ng/wp-content/uploads/2026/09/YEDC_HOLDCO_YSS_September_2026_098.pdf",
    "nasa": "https://power.larc.nasa.gov/api/temporal/hourly/point",
    "seforall": "https://www.seforall.org/system/files/2022-06/Nigeria_technology_0.pdf",
    "diesel": "https://21stcenturychronicle.com/diesel-price-rose-from-n1758-26-to-n3277-47-in-may-nbs/",
    "diesel_legit": "https://www.legit.ng/business-economy/energy/1716140-nbs-diesel-price-rises-8640-n3277litre-2026/",
    "mepp_support": "https://www.arise.tv/tinubu-approves-n68bn-maiduguri-power-funding-as-zulum-hails-boost-to-"
                    "security-economy/",
    "mepp_nan": "https://gazettengr.com/?p=360217",
    "c17": "https://yorpower.com/wp-content/uploads/2025/07/C17D5.pdf",
    "c90": "https://yorpower.com/wp-content/uploads/2025/07/C90D5.pdf",
    "boell": "https://ng.boell.org/sites/default/files/true_cost_of_power_technical_report_final.pdf",
    "zit": "https://www.zit.ng/collections/perkins",
    "coldhubs": "https://www.deutschland.de/en/solar-powered-coldhubs-nigeria",
    "ifpri": "https://ssa.foodsecurityportal.org/node/2484",
    "sphere": "https://www.unicef.org/media/61556/file",
    "epa": "https://www.epa.gov/system/files/documents/2025-01/ghg-emission-factors-hub-2025.pdf",
    "wb_pumping": "https://documents1.worldbank.org/curated/en/880931517231654485/pdf/123018-WP-P159391-PUBLIC.pdf",
    "gazette_2024": "https://gazettengr.com/governor-zulum-promises-solar-powered-boreholes-amid-water-crisis-in-borno/",
    "humangle": "https://humanglemedia.com/maiduguri-residents-suffer-through-43c-heat-amid-unexplained-power-cuts",
    "gem": "https://www.gem.wiki/Maiduguri_power_plant",
    "ruwasa": "https://www.arise.tv/zulum-approves-n850-million-for-rehabilitation-upgrade-of-boreholes-in-flood-"
              "affected-areas/",
    "rea_eep": "https://nep.rea.gov.ng/eep-ii.html",
    "gatekeepers": "https://gatekeepersnews.com/?p=101765",
    "usgs": "https://pubs.usgs.gov/of/1972/0061/report.pdf",
}

SOURCES = [
    src(ST.SRC_GRID3, URL["grid3"], "VERIFIED"),
    src(C.B13_IMMAP, None, "VERIFIED"),
    src(ST.SRC_OSM, URL["geofabrik"], "VERIFIED"),
    src("Overpass API (OSM base 30 Oct 2026 21:58 UTC), Maiduguri box", URL["overpass"], "VERIFIED"),
    src("NERC supplementary orders, YEDC feeder band appendix, September 2026 (band of the feeder or LGA mixture)",
        URL["yedc"], "VERIFIED"),
    src("NASA POWER hourly v2.10.3, 2021 to 2023", URL["nasa"], "VERIFIED"),
    src("SEforALL Nigeria technology PDF p.3, p.11, p.16 ($/Wp, 7.2 kWh per kWp, O&M, life, replacement)",
        URL["seforall"], "VERIFIED"),
    src(C.DIESEL_NGN_PER_L.source, URL["diesel"], C.DIESEL_NGN_PER_L.status),
    src("Legit.ng, NBS diesel price May 2026 (state top 10; Borno April 2026)", URL["diesel_legit"],
        "VERIFIED_SECONDARY"),
    src(C.MEPP_SUPPORT_NGN_PER_MONTH.source, URL["mepp_support"], C.MEPP_SUPPORT_NGN_PER_MONTH.status),
    src(C.MEPP_AVG_DELIVERED_MW.source, URL["mepp_nan"], C.MEPP_AVG_DELIVERED_MW.status),
    src(C.MEPP_SRC_NAN, URL["mepp_nan"], C.MEPP_COST_TARIFF_USC_PER_KWH.status),
    src(C.GEN_L_PER_KWH.source, URL["c17"], C.GEN_L_PER_KWH.status),
    src(C.GEN_L_PER_KWH_MID.source, URL["c90"], C.GEN_L_PER_KWH_MID.status),
    src(C.GEN_OM_USD_PER_KWH.source, URL["boell"], C.GEN_OM_USD_PER_KWH.status),
    src(C.GENSET_SRC, URL["zit"], "VERIFIED_SECONDARY"),
    src(C.COLDHUB_PV_KWP.source, URL["coldhubs"], C.COLDHUB_PV_KWP.status),
    src(C.COLDHUB_CAPEX_USD.source, URL["ifpri"], C.COLDHUB_CAPEX_USD.status),
    src(C.WATER_L_PER_PERSON_DAY.source, URL["sphere"], C.WATER_L_PER_PERSON_DAY.status),
    src("Pump head: " + C.BH_PUMP_HEAD_M.source, URL["usgs"], C.BH_PUMP_HEAD_M.status),
    src(C.CO2_KG_PER_L_DIESEL.source + " (EPA GHG Emission Factors Hub 2025, Table 2)", URL["epa"],
        C.CO2_KG_PER_L_DIESEL.status),
    src(WB_PUMPING, URL["wb_pumping"], "VERIFIED"),
    src(GAZETTE_2024, URL["gazette_2024"], "VERIFIED_SECONDARY"),
    src("Arise News, 21 Apr 2025: Borno RUWASA named", URL["ruwasa"], "VERIFIED_SECONDARY"),
    src("HumAngle, 22 Mar 2024: the plant manager on gas tankers", URL["humangle"], "VERIFIED_SECONDARY"),
    src("Global Energy Monitor wiki, Maiduguri power plant", URL["gem"], "VERIFIED_SECONDARY"),
    src("Rural Electrification Agency, EEP Phase II page: UNIMAID and UMTH 12 MW, OPERATIONAL", URL["rea_eep"],
        "VERIFIED"),
    src("Gatekeepers News, 25 May 2024: 7 MWh batteries and a 10 MW diesel backup (resident engineer)",
        URL["gatekeepers"], "VERIFIED_SECONDARY"),
    src("Full quotes and grades: docs/sources/brief13-sources.md", None, None),
]

# a machine-readable grade for every label key the payloads carry (tests check that none is missing)
LABEL_STATUS = {
    "scenario_today": "ASSUMPTION", "scenario_today_diesel": "ASSUMPTION", "scenario_with": "DERIVED",
    "supply": "DERIVED", "diesel": "DERIVED", "diesel_price": "VERIFIED_SECONDARY", "water": "ASSUMPTION",
    "water_works": "ASSUMPTION", "cold": "DERIVED", "people_served": "DERIVED", "umth": "VERIFIED_SECONDARY",
    "sums": "DERIVED", "ownership": "ASSUMPTION", "security": "ASSUMPTION", "gas_support": "VERIFIED_SECONDARY",
    "gas_fuel": "VERIFIED_SECONDARY", "gas_tariff": "VERIFIED_SECONDARY", "cost_solar": "DERIVED",
    "cost_diesel": "DERIVED", "roof": "ASSUMPTION", "data": "DERIVED", "solar": "DERIVED",
    "diesel_fuel_only": "DERIVED", "breakeven": "DERIVED", "cost": "DERIVED", "pricing": "DERIVED",
    "csh": "DERIVED", "pump_kw": "ASSUMPTION", "hours": "ASSUMPTION", "today": "ASSUMPTION", "load": "DERIVED",
    "lga": "DERIVED", "kw": "DERIVED", "rank": "DERIVED", "constants": "DERIVED", "assumptions": "DERIVED",
}
SITE_SOURCES = {ST.SRC_GRID3: ("grid3", "VERIFIED"), C.B13_IMMAP: (None, "VERIFIED"),
                ST.SRC_OSM: ("geofabrik", "VERIFIED")}


def site_source(text: str) -> dict:
    key, status = SITE_SOURCES.get(text, (None, None))
    return src(text, URL[key] if key else None, status)


LABEL_STATUS_BY_ARCHETYPE = {("water_works", "load"): "ASSUMPTION"}


def label_status(labels: dict | None, archetype: str | None = None) -> dict | None:
    if labels is None:
        return None
    return {k: LABEL_STATUS_BY_ARCHETYPE.get((archetype, k), LABEL_STATUS[k]) for k in labels}


OWNERSHIP = [
    {"sector": "health", "owns": "the facility's operator (state or private owner)",
     "pays": "the facility, from the diesel budget it no longer spends (pay-as-you-save); capex from a funder grant",
     "guards": "facility staff with the community around it",
     "repairs": "a local installer on a service contract, alerted by remote monitoring",
     "precedent": None},
    {"sector": "water", "owns": "the ward borehole committee, with Borno RUWASA (Rural Water Supply and Sanitation "
                                "Agency) as the state agency",
     "pays": "a small water fee per container or per household, set by the committee",
     "guards": "the ward borehole committee", "repairs": "trained local pump mechanics; installer warranty",
     "precedent": "2024: government boreholes were 'being supplied fuel for six hours daily but ended up pumping "
                  "water for only one hour daily', and the governor said 'We are going to set up committees for the "
                  f"boreholes in each ward' ({GAZETTE_2024}); RUWASA named by Arise News, 21 Apr 2025"},
    {"sector": "cold", "owns": "a cold-room operator or the market association",
     "pays": "traders, pay per crate per day: N100 (up to N250 quoted)",
     "guards": "the market association's own security", "repairs": "the operator, paid from the storage fees",
     "precedent": "ColdHubs pay-as-you-store model: 7 units in Northeast Nigeria markets (Dec 2020 to Jan 2021), "
                  "N100 per crate per day, about USD 40,000 per unit and USD 150 a month to run (IFPRI, 2023)"},
]

SECURITY = [
    {"measure": "build community ownership (the ward committee or market association holds the asset)",
     "basis": WB_PUMPING, "status": "VERIFIED"},
    {"measure": "site arrays where people pass regularly, on roofs out of public reach where the roof fits",
     "basis": WB_PUMPING, "status": "VERIFIED"},
    {"measure": "ground arrays only inside the compound wall or a fence", "basis": WB_PUMPING, "status": "VERIFIED"},
    {"measure": "tamper-proof or spot-welded bolts and anti-theft mounting frames", "basis": WB_PUMPING,
     "status": "VERIFIED"},
    {"measure": "motion sensors and alarms; guards where the site already has them", "basis": WB_PUMPING,
     "status": "VERIFIED"},
    {"measure": "battery in a lockable room or a steel cage", "basis": "our design standard (no guide found)",
     "status": "ASSUMPTION"},
    {"measure": "remote monitoring with alerts on output, battery and door",
     "basis": "our design standard (no guide found)", "status": "ASSUMPTION"},
    {"measure": "no new exposed line: the system sits behind the meter inside the compound",
     "basis": "our design standard", "status": "ASSUMPTION"},
]


def _r(p, lo, hi) -> dict:
    return {"point": float(p), "lo": float(min(lo, hi)), "hi": float(max(lo, hi))}


def _radd(a: dict, b: dict) -> dict:
    return {k: a[k] + b[k] for k in ("point", "lo", "hi")}


ZERO = {"point": 0.0, "lo": 0.0, "hi": 0.0}


def const_labels(names) -> dict:
    out = {}
    for n in names:
        c = C.REGISTRY[n]
        out[n] = {"value": c.value, "lo": c.lo, "hi": c.hi, "unit": c.unit, "status": c.status, "source": c.source}
    return out


USED_CONSTS = ("MEPP_COST_TARIFF_USC_PER_KWH", "MEPP_NBET_PAID_USC_PER_KWH", "BH_PUMP_HEAD_M", "BH_PUMP_EFF", "BH_DEFAULT_HOURS", "PUMP_WINDOW_CENTRE_H", "SOLAR_BH_ARRAY_KWP_PER_KW",
               "WATER_WORKS_KW", "COLDHUB_PV_KWP", "COLDHUB_CAPEX_USD", "COLDHUB_FEE_NGN_PER_CRATE_DAY",
               "WATER_L_PER_PERSON_DAY", "MEPP_SUPPORT_NGN_PER_MONTH", "GEN_L_PER_KWH_MID", "GEN_OM_USD_PER_KWH",
               "GEN_LIFE_YEARS", "GENSET_15KVA_NGN", "GENSET_20KVA_NGN", "GENSET_30KVA_NGN", "GENSET_40KVA_NGN",
               "GENSET_50KVA_NGN", "GENSET_100KVA_NGN", "GENSET_POWER_FACTOR",
               "MEPP_CAPACITY_MW", "MEPP_AVG_DELIVERED_MW", "ROOF_NEAREST_M", "ROOF_USABLE_FRACTION", "PV_KWP_PER_M2",
               "DIESEL_NGN_PER_L", "GEN_L_PER_KWH", "CO2_KG_PER_L_DIESEL", "COST_USD_PER_WP", "BATTERY_KWH_PER_KWP",
               "OM_FRACTION_PER_YEAR", "SYSTEM_LIFE_YEARS", "REPLACEMENT_FRACTION_Y10", "FX_NGN_PER_USD")


# ---------------------------------------------------------------- corridor


def _seg_km(a, b) -> float:
    return ST.dist_m(a[0], a[1], b[0], b[1]) / 1000.0


def corridor_stats() -> dict:
    if not ST.CORRIDOR.exists():
        return {"km_330": None, "towers": None, "note": "corridor extract not found"}
    g = json.loads(ST.CORRIDOR.read_text())
    km = Counter()
    n = Counter()
    for f in g["features"]:
        p, geom = f["properties"], f["geometry"]
        kind = p.get("power")
        if kind == "line" and geom["type"] == "LineString":
            v = "330" if "330000" in str(p.get("voltage", "")) else "132" if "132000" in str(p.get("voltage", "")) \
                else "other"
            pts = [(c[1], c[0]) for c in geom["coordinates"]]
            km[v] += sum(_seg_km(a, b) for a, b in zip(pts, pts[1:]))
            n[f"lines_{v}"] += 1
        elif kind in ("tower", "substation", "plant"):
            n[kind] += 1
    return {"km_330": round(km["330"], 1), "km_132": round(km["132"], 1), "towers": n["tower"],
            "substations": n["substation"], "plants": n["plant"], "line_ways_330": n["lines_330"],
            "box": "Gombe to Maiduguri, 10.1 to 12.1 N, 10.9 to 13.4 E (whole OSM ways that touch the box)",
            "source": "OSM via Geofabrik nigeria-latest.osm.pbf (30 Oct 2026), osm_extract.py; mapped, not surveyed"}


def _rdp(pts, eps):
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1e-12
    d = [abs(dy * x - dx * y + x2 * y1 - y2 * x1) / L for x, y in pts[1:-1]]
    i = int(np.argmax(d)) + 1
    if d[i - 1] > eps:
        return _rdp(pts[: i + 1], eps)[:-1] + _rdp(pts[i:], eps)
    return [pts[0], pts[-1]]


MEPP_WAY = "1288148118"  # OSM way of the Maiduguri Emergency Power Plant


def corridor_geojson(eps_deg: float = 0.0003) -> dict:
    """The 330/132 kV lines (simplified), towers, substations and plants, plus the Overpass plants in the city box."""
    keep = ("power", "voltage", "name", "operator", "plant:source", "plant:output:electricity", "osm_type", "osm_id")
    feats = []
    seen = set()
    if ST.CORRIDOR.exists():
        for f in json.loads(ST.CORRIDOR.read_text())["features"]:
            p, geom = f["properties"], f["geometry"]
            props = {k: p[k] for k in keep if k in p}
            if geom["type"] == "LineString":
                pts = _rdp([tuple(c) for c in geom["coordinates"]], eps_deg)
                geom = {"type": "LineString", "coordinates": [[round(x, 5), round(y, 5)] for x, y in pts]}
            else:
                geom = {"type": "Point", "coordinates": [round(geom["coordinates"][0], 5),
                                                         round(geom["coordinates"][1], 5)]}
            if str(p.get("osm_id")) == MEPP_WAY:
                props.pop("plant:source", None)
                props["fuel"] = C.MEPP_FUEL
                props["fuel_note"] = C.MEPP_OSM_NOTE
            if p.get("power") == "plant" and geom["type"] == "LineString":
                c = geom["coordinates"]
                geom = {"type": "Point", "coordinates": [round(sum(x for x, _ in c) / len(c), 5),
                                                         round(sum(y for _, y in c) / len(c), 5)]}
            seen.add((p.get("osm_type"), p.get("osm_id")))
            feats.append({"type": "Feature", "geometry": geom, "properties": props})
    if ST.OSM_OVERPASS.exists():
        for e in json.loads(ST.OSM_OVERPASS.read_text())["elements"]:
            t = e.get("tags", {})
            if t.get("power") != "plant" or (e["type"], e["id"]) in seen:
                continue
            c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
            if c.get("lat") is None:
                continue
            props = {"osm_type": e["type"], "osm_id": e["id"], **{k: t[k] for k in keep if k in t}}
            if str(e["id"]) == MEPP_WAY:
                props.pop("plant:source", None)
                props["fuel"] = C.MEPP_FUEL
                props["fuel_note"] = C.MEPP_OSM_NOTE
                props["delivered_mw_dec_2024"] = C.MEPP_AVG_DELIVERED_MW.value
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(c["lon"], 5),
                                                                                         round(c["lat"], 5)]},
                          "properties": props})
    return {"type": "FeatureCollection", "features": feats,
            "properties": {"stats": corridor_stats(), "simplified_deg": eps_deg,
                           "source": "OpenStreetMap (ODbL), Geofabrik 30 Oct 2026 and Overpass 30 Oct 2026",
                           "note": "plant polygons shown as their centre point; OSM shows assets are mapped, not that "
                                   "they operate"}}


# ---------------------------------------------------------------- per-site results


def _profile_job(args):
    key, (point, bands, hours, start, mode, cfg) = args
    pp = SM.prepare(point[0], point[1], bands, cfg)
    return key, X.run_profile(pp, hours, start, mode, cfg)


def _health_annual_job(args):
    key, (point, kwp, kwh, cfg) = args
    pp = SM.prepare(point[0], point[1], SP.OFFGRID, cfg)
    return key, X.annual_solar_first_kwh(pp, LD.critical(), kwp, kwh, cfg)


def _health_daily_job(args):
    """The daily-cycle arm for one health key: size from the critical-load profile, run each window with the
    facility's outage-ready fridge, and the solar-first annual energy."""
    from . import outage as OU

    key, (point, bands, fridge_code, cfg, days) = args
    pp = SM.prepare(point[0], point[1], bands, cfg)
    crit = LD.critical()
    _, prof = LD.priority_profile(crit)
    kwp, kwh = X.daily_cycle_size(pp, prof.sum(axis=0), cfg)
    kind = "ii" if F.CATALOGUE[fridge_code].kind == "sdd" else "i"
    by = {}
    for d in days:
        o = OU.simulate_outage(pp, d, crit, SM.ClinicSystem(kwp, kwh), kind, fridge_code, cfg)
        by[d] = {"with_h": o.with_system.point, "needed_h": o.needed_h}
    a = X.annual_solar_first_kwh(SM.prepare(point[0], point[1], SP.OFFGRID, cfg), crit, kwp, kwh, cfg)
    return key, {"pv_kwp": kwp, "battery_kwh": kwh, "by_days": by, "annual_kwh": asdict(a)}


def _arm(kwp: dict | float, kwh: dict | float) -> dict:
    """Capex and life-cycle cost (naira, ranges) of a clinic-type system at SEforALL's bundle price."""
    k = kwp if isinstance(kwp, dict) else {"point": kwp, "lo": kwp, "hi": kwp}
    h = kwh if isinstance(kwh, dict) else {"point": kwh, "lo": kwh, "hi": kwh}
    cp, cl, ch = (E.clinic_capex_usd(k[x], h[x]) for x in ("point", "lo", "hi"))
    cap = E.Range(cp.point, cl.lo, ch.hi)
    return {"capex_ngn": E.to_ngn(cap).as_dict(), "lifecycle_ngn": E.to_ngn(E.lifecycle_usd(cap)).as_dict()}


def _pool(fn, jobs, workers):
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(workers) as ex:
            return dict(ex.map(fn, jobs, chunksize=1))
    return dict(fn(j) for j in jobs)


HEALTH_COLS = ("unique_id", "tier", "orfix_pv_kwp", "orfix_battery_kwh", "orfix_fridge_code", "orfix_category",
               "orfix_target_met", "orfix_capex_ngn", "orfix_capex_ngn_lo", "orfix_capex_ngn_hi")


def _health_cols(days) -> list[str]:
    cols = list(HEALTH_COLS)
    for d in days:
        cols += [f"out{d}_needed_h", f"out{d}_hours_today", f"out{d}_generator_litres", f"out{d}_generator_litres_lo",
                 f"out{d}_generator_litres_hi"]
        w = "orfix_" if d == 7 else f"orfix_at{d}_"
        cols += [f"{w}hours_kept", f"{w}diesel_l_avoided", f"{w}diesel_l_avoided_lo", f"{w}diesel_l_avoided_hi"]
    return list(dict.fromkeys(cols))


def site_results(sites: list[ST.Site], cfg: SM.SimConfig, days=DAYS, workers: int = 1,
                 results: pd.DataFrame | None = None) -> dict[str, dict]:
    """{site id: {"system": {...}, "by_days": {d: {...}}, "annual_kwh": {...}}} for every site."""
    out: dict[str, dict] = {}
    health = [s for s in sites if s.sector == "health"]
    other = [s for s in sites if s.sector != "health"]
    # ---- health from the batch columns
    if health:
        ids = [s.ref["unique_id"] for s in health]
        res = results if results is not None else pd.read_parquet(paths.FACILITY_RESULTS, columns=_health_cols(days))
        res = res[res.unique_id.isin(ids)].drop_duplicates("unique_id").set_index("unique_id")
        jobs = {}
        for s in health:
            r = res.loc[s.ref["unique_id"]]
            pt = S.nearest_point(s.lat, s.lon)
            kwp = float(r.orfix_pv_kwp)
            kwh = kwp * C.BATTERY_KWH_PER_KWP.value
            jobs[(pt, round(kwp, 6))] = (pt, kwp, kwh, cfg)
        annual = _pool(_health_annual_job, list(jobs.items()), workers)
        from . import augment as AU

        kk = AU.keys_for(pd.DataFrame({"unique_id": ids})).set_index("unique_id")
        djobs, dkey = {}, {}
        for s in health:
            uid = s.ref["unique_id"]
            if uid not in kk.index:
                continue
            k = (kk.loc[uid, "key"], res.loc[uid, "orfix_fridge_code"])
            dkey[s.id] = k
            djobs[k] = (kk.loc[uid, "point"], kk.loc[uid, "bands_obj"], res.loc[uid, "orfix_fridge_code"], cfg,
                        tuple(days))
        daily = _pool(_health_daily_job, list(djobs.items()), workers)
        for s in health:
            r = res.loc[s.ref["unique_id"]]
            kwp = float(r.orfix_pv_kwp)
            kwh = kwp * C.BATTERY_KWH_PER_KWP.value
            cap = E.clinic_capex_usd(kwp, kwh)
            by = {}
            for d in days:
                w = "orfix_" if d == 7 else f"orfix_at{d}_"
                gl = _r(r[f"out{d}_generator_litres"], r[f"out{d}_generator_litres_lo"],
                        r[f"out{d}_generator_litres_hi"])
                dl = _r(r[f"{w}diesel_l_avoided"], r[f"{w}diesel_l_avoided_lo"], r[f"{w}diesel_l_avoided_hi"])
                today = r[f"out{d}_hours_today"]
                by[d] = {"needed_h": float(r[f"out{d}_needed_h"]),
                         "today_h": None if pd.isna(today) else float(today),
                         "with_h": float(r[f"{w}hours_kept"]), "generator_litres": gl, "diesel_l_avoided": dl,
                         "needed_kwh": gl["point"] / GEN.value, "local_today_kwh": 0.0,
                         "local_with_kwh": dl["point"] / GEN.value, "m3_day": None}
            a = annual[(S.nearest_point(s.lat, s.lon), round(kwp, 6))]
            out[s.id] = {"system": {"pv_kwp": kwp, "battery_kwh": kwh, "fridge_code": r.orfix_fridge_code,
                                    "category": r.orfix_category, "target_met": bool(r.orfix_target_met),
                                    "capex_ngn": _r(r.orfix_capex_ngn, r.orfix_capex_ngn_lo, r.orfix_capex_ngn_hi),
                                    "clinic_capex_ngn": E.to_ngn(cap).as_dict(),
                                    "clinic_lifecycle_ngn": E.to_ngn(E.lifecycle_usd(cap)).as_dict(),
                                    "label": "outage-ready fix sized for 7 days: PQS fridge plus a clinic system for "
                                             "the priority-1 loads"},
                         "annual_kwh": asdict(a), "by_days": by, "tier": r.tier}
            uid = s.ref["unique_id"]
            if uid in kk.index:
                code = r.orfix_fridge_code
                out[s.id]["sim"] = {"kind": "health_orfix", "lat": s.lat, "lon": s.lon,
                                    "bands": kk.loc[uid, "bands_obj"], "fridge_code": code,
                                    "fix_kind": "ii" if F.CATALOGUE[code].kind == "sdd" else "i",
                                    "pv_kwp": kwp, "battery_kwh": kwh, "n_draws": cfg.n_draws}
            dd = daily.get(dkey.get(s.id))
            if dd:
                out[s.id]["daily_arm"] = {**dd, **_arm(dd["pv_kwp"], dd["battery_kwh"])}
    # ---- water and cold through engine.sector, one run per load shape and supply
    jobs = {}
    keyof = {}
    for s in other:
        pt = S.nearest_point(s.lat, s.lon)
        k = (pt, ST._bands_key(s.bands), round(s.hours, 3), s.start, s.mode)
        keyof[s.id] = k
        jobs[k] = (pt, s.bands, s.hours, s.start, s.mode, cfg)
    runs = _pool(_profile_job, list(jobs.items()), workers)
    for s in other:
        pr: X.ProfileRun = runs[keyof[s.id]]
        g = gen_curve(s.sector)
        kwp = {"point": pr.kwp_per_kw * s.kw, "lo": pr.kwp_per_kw * s.kw_lo, "hi": pr.kwp_per_kw * s.kw_hi}
        kwh = {k: v * C.BATTERY_KWH_PER_KWP.value for k, v in kwp.items()}
        cp, cl, ch = (E.clinic_capex_usd(kwp[k], kwh[k]) for k in ("point", "lo", "hi"))
        cap = E.Range(cp.point, cl.lo, ch.hi)
        by = {}
        for d in days:
            w = pr.windows[d]
            need_e = w.needed_kwh
            gen_e = need_e - w.base_kwh.point  # a generator covers what the existing array does not
            by[d] = {"needed_h": w.needed_h, "today_h": w.today_h.point, "with_h": w.with_h.point,
                     "with_h_lo": w.with_h.lo,
                     "generator_litres": _r(gen_e * s.kw * g.value, gen_e * s.kw_lo * g.lo,
                                            gen_e * s.kw_hi * g.hi),
                     "diesel_l_avoided": _r(w.system_kwh.point * s.kw * g.value,
                                            w.system_kwh.point * s.kw_lo * g.lo,
                                            w.system_kwh.point * s.kw_hi * g.hi),
                     "needed_kwh": need_e * s.kw, "local_today_kwh": w.base_kwh.point * s.kw,
                     "local_with_kwh": (w.base_kwh.point + w.system_kwh.point) * s.kw,
                     "m3_day": s.daily_m3}
        out[s.id] = {"system": {"pv_kwp": kwp, "battery_kwh": kwh, "target_met": pr.target_met,
                                "crit_share_lo_7d": pr.crit_share_lo, "capex_ngn": E.to_ngn(cap).as_dict(),
                                "clinic_capex_ngn": E.to_ngn(cap).as_dict(),
                                "clinic_lifecycle_ngn": E.to_ngn(E.lifecycle_usd(cap)).as_dict(),
                                "label": "solar + storage sized for a 7-day outage at 95% of critical hours "
                                         "(5th percentile)" + ("; the existing array is not credited"
                                                               if s.mode == "solar_direct" else "")},
                     "annual_kwh": {k: v * s.kw for k, v in asdict(pr.annual_kwh_per_kw).items()}, "by_days": by,
                     "n_draws": cfg.n_draws}
        if pr.daily:
            dk = {"point": pr.daily.kwp_per_kw * s.kw, "lo": pr.daily.kwp_per_kw * s.kw_lo,
                  "hi": pr.daily.kwp_per_kw * s.kw_hi}
            dh = {k: v * pr.daily.kwh_per_kw / max(pr.daily.kwp_per_kw, 1e-12) for k, v in dk.items()}
            out[s.id]["daily_arm"] = {
                "pv_kwp": dk["point"], "battery_kwh": dh["point"],
                "by_days": {d: {"with_h": pr.daily.windows[d].with_h.point, "needed_h": pr.daily.windows[d].needed_h}
                            for d in days},
                "annual_kwh": {k: v * s.kw for k, v in asdict(pr.daily.annual_kwh_per_kw).items()},
                **_arm(dk, dh)}
    return out


# ---------------------------------------------------------------- city metrics


def _pct(x):
    return None if x is None or not math.isfinite(x) else round(100 * x, 1)


def pct1(x: float) -> float:
    """A share as a percentage with one decimal, rounded half-up (0.06889 is 6.9). A share below 1 never reads 100:
    it is capped at 99.9, so a plan that misses hours never says it keeps them all."""
    from decimal import ROUND_HALF_UP, Decimal

    v = float(Decimal(repr(100.0 * x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    return min(v, 99.9) if x < 1 else v


def _pct_text(x) -> str:
    return f"{pct1(x):.1f}".rstrip("0").rstrip(".")


GENSET_KVA = {15: C.GENSET_15KVA_NGN, 20: C.GENSET_20KVA_NGN, 30: C.GENSET_30KVA_NGN, 40: C.GENSET_40KVA_NGN,
              50: C.GENSET_50KVA_NGN, 100: C.GENSET_100KVA_NGN}
CLINIC_SET_KVA = 20  # brief13-sources Q1: clinic sets are 15 to 20 kVA


def genset_for(sector: str, kw: float) -> tuple[str, float]:
    """(description, NGN) of the listed set(s) that would carry the site's critical load."""
    if sector == "health":
        return f"{CLINIC_SET_KVA} kVA clinic set", GENSET_KVA[CLINIC_SET_KVA].value
    kva = kw / C.GENSET_POWER_FACTOR.value
    for size in sorted(GENSET_KVA):
        if kva <= size:
            return f"{size} kVA set", GENSET_KVA[size].value
    n = math.ceil(kva / 100)
    return f"{n} x 100 kVA sets", n * GENSET_KVA[100].value


def diesel_bar(sites, res) -> dict:
    """Diesel cost per kWh for the same critical kWh the solar systems deliver a year: fuel at each site's curve,
    O&M at USD 0.03/kWh, the set's retail price over a 10-year life. lo: cheapest fuel case; hi: dearest."""
    price = E.crange(C.DIESEL_NGN_PER_L)
    om = C.GEN_OM_USD_PER_KWH.value * C.FX_NGN_PER_USD.value
    e = {"point": 0.0, "lo": 0.0, "hi": 0.0}
    fuel = {"point": 0.0, "lo": 0.0, "hi": 0.0}
    capex_yr = 0.0
    sets = Counter()
    for s in sites:
        a = res[s.id]["annual_kwh"]
        g = gen_curve(s.sector)
        for k in e:
            e[k] += a[k]
        fuel["point"] += a["point"] * g.value * price.point
        fuel["lo"] += a["point"] * g.lo * price.lo
        fuel["hi"] += a["point"] * g.hi * price.hi
        name, ngn = genset_for(s.sector, s.kw if s.sector != "health" else 0.0)
        sets[name] += 1
        capex_yr += ngn / C.GEN_LIFE_YEARS.value
    if e["point"] <= 0:
        return {"lifetime": None, "fuel_only": None}
    f = {k: fuel[k] / e["point"] for k in fuel}
    cap = {"point": capex_yr / e["point"], "lo": capex_yr / e["hi"], "hi": capex_yr / max(e["lo"], 1e-9)}
    life = _r(f["point"] + om + cap["point"], f["lo"] + om + cap["lo"], f["hi"] + om + cap["hi"])
    return {"lifetime": life, "fuel_only": _r(f["point"], f["lo"], f["hi"]), "fuel": f, "om": om, "capex": cap,
            "sets": dict(sets), "annual_kwh": e}


def cost_bars(sites, res) -> dict:
    """The three cost-per-kWh bars and the gas break-even, over every designed site."""
    life = C.SYSTEM_LIFE_YEARS.value
    lc, en = dict(ZERO), dict(ZERO)
    by = {}
    for s in sites:
        r = res[s.id]
        l = r["system"]["clinic_lifecycle_ngn"]
        e = r["annual_kwh"]
        lc = _radd(lc, l)
        en = _radd(en, {"point": e["point"] * life, "lo": e["lo"] * life, "hi": e["hi"] * life})
        b = by.setdefault(s.sector, [dict(ZERO), dict(ZERO)])
        b[0] = _radd(b[0], l)
        b[1] = _radd(b[1], {"point": e["point"] * life, "lo": e["lo"] * life, "hi": e["hi"] * life})

    def per(l, e):
        if e["point"] <= 0:
            return None
        return _r(l["point"] / e["point"], l["lo"] / max(e["hi"], 1e-9), l["hi"] / max(e["lo"], 1e-9))

    solar = per(lc, en)
    dsl = diesel_bar(sites, res)
    sup = C.MEPP_SUPPORT_NGN_PER_MONTH.value
    mw = C.MEPP_AVG_DELIVERED_MW

    def gas(m):
        return sup / (m * 1000.0 * HOURS_PER_MONTH)

    gas_bar = _r(gas(mw.value), gas(mw.hi), gas(mw.lo))
    be = None
    if solar:
        f = (lambda c: sup / (c * 1000.0 * HOURS_PER_MONTH))
        be = {"mw": _r(f(solar["point"]), f(solar["hi"]), f(solar["lo"])),
              "mwh_per_month": _r(sup / solar["point"] / 1000.0, sup / solar["hi"] / 1000.0,
                                  sup / solar["lo"] / 1000.0)}
    fx = C.FX_NGN_PER_USD.value
    tariff = C.MEPP_COST_TARIFF_USC_PER_KWH.value / 100 * fx
    nbet = C.MEPP_NBET_PAID_USC_PER_KWH.value / 100 * fx
    gas_tariff = {"ngn_per_kwh": tariff, "usc_per_kwh": C.MEPP_COST_TARIFF_USC_PER_KWH.value,
                  "nbet_paid_ngn_per_kwh": nbet, "nbet_paid_usc_per_kwh": C.MEPP_NBET_PAID_USC_PER_KWH.value,
                  "fx_ngn_per_usd": fx, "fx_date": C.FX_DATE, "source": C.MEPP_SRC_NAN, "url": URL["mepp_nan"],
                  "status": C.MEPP_COST_TARIFF_USC_PER_KWH.status,
                  "label": "the plant's cost-reflective tariff (Sep 2024) in naira at the CBN rate of " + C.FX_DATE
                           + "; NBET paid 6.2 US cents; a cost per kWh delivered by the plant, not by our systems"}
    return {"cost_per_kwh_ngn": {"solar": solar, "diesel": dsl["lifetime"], "gas_support": gas_bar,
                                 "gas_tariff_cost_reflective": _r(tariff, tariff, tariff),
                                 "diesel_fuel_only": dsl["fuel_only"]},
            "gas_tariff_cost_reflective": gas_tariff,
            "diesel_detail": dsl,
            "solar_by_sector": {k: per(*v) for k, v in by.items()},
            "solar_lifecycle_ngn": lc, "solar_lifetime_kwh": en,
            "gas_breakeven": be,
            "gas_support_at_mw": {f"{m:g}": gas(m) for m in (mw.value, 32.0, mw.hi)},
            "labels": {"solar": LABELS["cost_solar"], "diesel": LABELS["cost_diesel"],
                       "diesel_fuel_only": "fuel only (price x L/kWh): the lower bound of the diesel bar",
                       "gas_support": LABELS["gas_support"] + "; point at the 14.2 MW daily average delivered "
                                      "(Dec 2024, NAN), up to the 50 MW nameplate; 32 MW was the generating figure. "
                                      + C.MEPP_TARIFF_NOTE + ". Fuel: " + C.MEPP_FUEL,
                       "breakeven": "average delivered MW (and MWh a month) at which N2bn a month of support per kWh "
                                    "equals the solar cost per kWh; below it the support alone costs more per kWh"}}


GAS_FUEL_SRC = ("HumAngle, 'Maiduguri Residents Suffer Through 43°C Heat Amid Unexplained Power Cuts' (22 Mar 2024, "
                "archive.org copy), quoting the plant manager on gas tankers; Global Energy Monitor wiki, 'Maiduguri "
                "power plant' (natural gas, diesel second); docs/sources/brief13-sources.md Q5")
BRIEF_ALONGSIDE = "Work alongside the existing gas plant and distribution company, not replace them"


def gas_position(costs: dict) -> dict:
    """The plain statement the product shows next to the cost bars, computed from the bars (never hard-coded)."""
    c = costs["cost_per_kwh_ngn"]
    solar, sup, tar = c["solar"], c["gas_support"], c["gas_tariff_cost_reflective"]
    cheaper = solar is not None and sup["point"] < solar["point"] and tar["point"] < solar["point"]
    mw = C.MEPP_AVG_DELIVERED_MW.value
    if cheaper:
        first = (f"When it runs, the gas plant is cheaper per kWh than solar + storage: about N{sup['point']:,.0f} of "
                 f"federal operating support per kWh at {mw:g} MW delivered, or N{tar['point']:,.0f} at its "
                 f"cost-reflective tariff, against about N{solar['point']:,.0f} for the solar systems.")
    else:
        first = (f"Per kWh, federal operating support is about N{sup['point']:,.0f} at {mw:g} MW and the plant's "
                 f"cost-reflective tariff about N{tar['point']:,.0f}, against about "
                 f"N{(solar or {'point': float('nan')})['point']:,.0f} for the solar systems.")
    return {"gas_cheaper_when_running": cheaper,
            "text": first + " The plan does not replace it: it works alongside the gas plant and the distribution "
                    "company, and keeps the critical loads running when the line or the plant fails.",
            "brief_constraint": BRIEF_ALONGSIDE, "fuel": "The plant's gas arrives by road tanker.",
            "fuel_source": GAS_FUEL_SRC}


ARM_DAYS = (14, 40, 60)


def cost_arms(sites, res, days=ARM_DAYS) -> dict:
    """Solar cost per kWh delivered and critical service-hours kept, for each sizing arm, over the same sites."""
    life = C.SYSTEM_LIFE_YEARS.value
    both = [s for s in sites if "daily_arm" in res[s.id]]

    def arm(get_sys, get_days):
        lc, en, cap = dict(ZERO), dict(ZERO), dict(ZERO)
        csh = {d: {"needed": 0.0, "with": 0.0} for d in days}
        by = {}
        for s in both:
            a = get_sys(s)
            e = a["annual_kwh"]
            el = {k: e[k] * life for k in ("point", "lo", "hi")}
            lc, en, cap = _radd(lc, a["lifecycle_ngn"]), _radd(en, el), _radd(cap, a["capex_ngn"])
            b = by.setdefault(s.sector, {"lifecycle": dict(ZERO), "kwh": dict(ZERO),
                                          "csh": {d: {"needed": 0.0, "with": 0.0} for d in days}})
            b["lifecycle"], b["kwh"] = _radd(b["lifecycle"], a["lifecycle_ngn"]), _radd(b["kwh"], el)
            for d in days:
                w = get_days(s, d)
                for t in (csh[d], b["csh"][d]):
                    t["needed"] += w["needed_h"]
                    t["with"] += w["with_h"]

        def per(l, e):
            return None if e["point"] <= 0 else _r(l["point"] / e["point"], l["lo"] / e["hi"], l["hi"] / e["lo"])

        def shares(c):
            return {str(d): {**v, "share": v["with"] / v["needed"] if v["needed"] else None} for d, v in c.items()}

        return {"cost_per_kwh_ngn": per(lc, en), "capex_ngn": cap, "lifecycle_ngn": lc, "lifetime_kwh": en,
                "csh": shares(csh),
                "by_sector": {k: {"cost_per_kwh_ngn": per(v["lifecycle"], v["kwh"]), "csh": shares(v["csh"])}
                              for k, v in by.items()}}

    def sys_a(s):
        r = res[s.id]
        return {"annual_kwh": r["annual_kwh"], "lifecycle_ngn": r["system"]["clinic_lifecycle_ngn"],
                "capex_ngn": r["system"]["clinic_capex_ngn"]}

    return {
        "outage_ready_7d": {**arm(sys_a, lambda s, d: res[s.id]["by_days"][d]),
                            "label": "the plan's sizing: PV with battery at 7.2 kWh per kWp, the smallest keeping 95% "
                                     "of critical hours at the 5th percentile in a 7-day outage"},
        "daily_cycle": {**arm(lambda s: res[s.id]["daily_arm"], lambda s, d: res[s.id]["daily_arm"]["by_days"][d]),
                        "label": X.DAILY_ARM_LABEL},
        "sites": len(both),
        "labels": {"cost": LABELS["cost_solar"] + "; both arms priced the same way",
                   "pricing": "SEforALL prices PV and storage together ($/Wp at 7.2 kWh per kWp); a system with less "
                              "battery per kWp is still priced by its PV, because no separate battery price is "
                              "verified, so a smaller battery does not lower the price in this method",
                   "csh": "critical service-hours kept with each arm in the outage window (health includes the "
                          "outage-ready fridge in both arms)"},
        "label_status": {"cost": "DERIVED", "pricing": "DERIVED", "csh": "DERIVED",
                         "outage_ready_7d": "DERIVED", "daily_cycle": "ASSUMPTION"},
    }


def city_metrics(city_id: str, sites: list[ST.Site], res: dict, days: int, excl: dict, corridor: dict,
                 siting: dict, runtime_s: float | None = None, data_version: str | None = None) -> dict:
    city = ST.CITIES[city_id]
    design = [s for s in sites if not s.existing_onsite]
    tot = {"needed": 0.0, "today": 0.0, "with": 0.0, "need_e": 0.0, "loc_today": 0.0, "loc_with": 0.0}
    dl, gl, capex = dict(ZERO), dict(ZERO), dict(ZERO)
    by = {}
    m3_today = m3_with = 0.0
    for sec in SECTORS:
        ss = [s for s in design if s.sector == sec]
        b = {"sites": len(ss), "csh_needed": 0.0, "csh_today": 0.0, "csh_with": 0.0,
             "diesel_l_avoided": dict(ZERO), "generator_litres_today_scenario": dict(ZERO),
             "capex_ngn": dict(ZERO)}
        for s in ss:
            r = res[s.id]["by_days"][days]
            b["csh_needed"] += r["needed_h"]
            b["csh_today"] += r["today_h"] or 0.0
            b["csh_with"] += r["with_h"]
            b["diesel_l_avoided"] = _radd(b["diesel_l_avoided"], r["diesel_l_avoided"])
            b["generator_litres_today_scenario"] = _radd(b["generator_litres_today_scenario"], r["generator_litres"])
            b["capex_ngn"] = _radd(b["capex_ngn"], res[s.id]["system"]["capex_ngn"])
            tot["need_e"] += r["needed_kwh"]
            tot["loc_today"] += r["local_today_kwh"]
            tot["loc_with"] += r["local_with_kwh"]
            if r.get("m3_day") and r["needed_h"] > 0:
                m3_today += r["m3_day"] * (r["today_h"] or 0.0) / r["needed_h"]
                m3_with += r["m3_day"] * r["with_h"] / r["needed_h"]
        b["csh_today_diesel"] = b["csh_needed"]
        b["share_today"] = b["csh_today"] / b["csh_needed"] if b["csh_needed"] else None
        b["share_with"] = b["csh_with"] / b["csh_needed"] if b["csh_needed"] else None
        by[sec] = b
        tot["needed"] += b["csh_needed"]
        tot["today"] += b["csh_today"]
        tot["with"] += b["csh_with"]
        dl = _radd(dl, b["diesel_l_avoided"])
        gl = _radd(gl, b["generator_litres_today_scenario"])
        capex = _radd(capex, b["capex_ngn"])
    price = E.crange(C.DIESEL_NGN_PER_L)
    ngn = _r(dl["point"] * price.point, dl["lo"] * price.lo, dl["hi"] * price.hi)
    gl_ngn = _r(gl["point"] * price.point, gl["lo"] * price.lo, gl["hi"] * price.hi)
    lpp = C.WATER_L_PER_PERSON_DAY.value

    def people(m3):
        return m3 * 1000 / lpp

    share_today = tot["today"] / tot["needed"] if tot["needed"] else None
    share_with = tot["with"] / tot["needed"] if tot["needed"] else None
    co2 = {k: v * C.CO2_KG_PER_L_DIESEL.value / 1000.0 for k, v in dl.items()}
    costs = cost_bars(design, res)
    co2_year = dict(ZERO)
    for s in design:
        e, g = res[s.id]["annual_kwh"]["point"], gen_curve(s.sector)
        k = C.CO2_KG_PER_L_DIESEL.value / 1000
        co2_year = _radd(co2_year, {"point": e * g.value * k, "lo": e * g.lo * k, "hi": e * g.hi * k})
    fit = Counter(siting[s.id]["roof"]["fit"] for s in design)
    kms = [siting[s.id]["km_to_330kv"] for s in design if siting[s.id]["km_to_330kv"] is not None]
    when = "two months" if days == 60 else f"{days} days"
    headline = (f"If the line goes down for {when}, {city.name}'s critical sites keep {_pct_text(share_today)}% of "
                f"critical service-hours today and {_pct_text(share_with)}% with the plan, without burning "
                f"{dl['point']:,.0f} litres of diesel.") if share_with is not None else None
    on_corridor = city_id in ("maiduguri", "damaturu")
    data_notes = {"water": excl.get("water", {}).get("note") or "iMMAP 2019 boreholes (motorized and solar) and the "
                  "OSM water works", "cold": excl.get("cold", {}).get("note") or "named OSM marketplaces, one cold "
                  "room each", "health": "GRID3 facilities with coordinates and an engine result"}
    return {
        "city": city_id, "name": city.name, "state": city.state, "lgas": list(city.lgas), "days": days,
        "headline": headline,
        "headline_alongside": gas_position(costs)["text"],
        "impact": {
            "csh_needed": tot["needed"], "csh_today": tot["today"], "csh_today_diesel": tot["needed"],
            "csh_with": tot["with"], "share_today": share_today, "share_with": share_with,
            "share_today_diesel": 1.0 if tot["needed"] else None,
            "by_sector": by,
            "diesel_l_avoided": dl, "diesel_ngn_avoided": ngn,
            "today_diesel_scenario": {"litres": gl, "ngn": gl_ngn},
            "water_m3_per_day_kept": {"today": m3_today, "with": m3_with},
            "people_served": {"today": people(m3_today), "with": people(m3_with)},
        },
        "innovation": {
            "local_share": {"today": tot["loc_today"] / tot["need_e"] if tot["need_e"] else None,
                            "with": tot["loc_with"] / tot["need_e"] if tot["need_e"] else None,
                            "critical_kwh_needed": tot["need_e"]},
            "sites": len(design), "sites_by_sector": {k: by[k]["sites"] for k in SECTORS},
            "new_line_km": 0,
            "corridor": {**{k: corridor.get(k) for k in ("km_330", "towers", "km_132", "substations", "box",
                                                         "source")},
                         "applies_to_city": on_corridor,
                         "note": None if on_corridor else "Yola is not on the Gombe to Maiduguri 330 kV corridor; "
                                                          "the figures describe that corridor"},
        },
        "sustainability": {
            "cost_per_kwh_ngn": costs["cost_per_kwh_ngn"], "solar_by_sector": costs["solar_by_sector"],
            "gas_breakeven_mw": costs["gas_breakeven"]["mw"] if costs["gas_breakeven"] else None,
            "gas_breakeven_mwh_per_month": costs["gas_breakeven"]["mwh_per_month"] if costs["gas_breakeven"]
            else None,
            "gas_support_at_mw": costs["gas_support_at_mw"],
            "co2_t_avoided": co2, "co2_t_avoided_per_year_upper": co2_year,
            "capex_ngn": capex, "solar_lifecycle_ngn": costs["solar_lifecycle_ngn"],
            "solar_lifetime_kwh": costs["solar_lifetime_kwh"],
            "ownership": OWNERSHIP, "cost_labels": costs["labels"],
            "cost_label_status": label_status(costs["labels"]),
            "cost_arms": cost_arms(design, res),
            "gas_tariff_cost_reflective": costs["gas_tariff_cost_reflective"],
            "gas_fuel_note": {"text": "The plant's gas arrives by road tanker.", "source": GAS_FUEL_SRC},
            "gas_position": gas_position(costs),
        },
        "feasibility": {
            "roof_fit": {"fits": fit.get("fits", 0), "partial": fit.get("partial", 0), "ground": fit.get("ground", 0),
                         "unknown": fit.get("unknown", 0)},
            "new_line_km": 0, "km_to_330kv_median": float(np.median(kms)) if kms else None,
            "security": SECURITY,
            "battery_kwh_total": sum(res[s.id]["system"]["battery_kwh"]["point"]
                                     if isinstance(res[s.id]["system"]["battery_kwh"], dict)
                                     else res[s.id]["system"]["battery_kwh"] for s in design),
        },
        "scalability": {"cities": list(ST.CITIES), "build_seconds": runtime_s,
                        "data": data_notes,
                        "another_city_needs": ["a facility registry with coordinates (GRID3 covers Nigeria)",
                                               "the distribution company's feeder bands or outage records",
                                               "a water-point survey with yield and hours", "OSM markets and roofs",
                                               "hourly irradiance (NASA POWER, global)"]},
        "excluded": {"existing_onsite": [{"id": s.id, "name": s.name, "note": s.note} for s in sites
                                         if s.existing_onsite], **excl},
        "labels": {**LABELS, "data": data_notes, "constants": const_labels(USED_CONSTS),
                   "assumptions": sorted(n for n in USED_CONSTS if C.REGISTRY[n].status in ("ASSUMPTION",
                                                                                           "UNVERIFIED"))},
        "label_status": {**label_status({**LABELS, "data": 1}), "constants": "per constant (see each entry's status)",
                         "assumptions": "DERIVED"},
        "sources": SOURCES,
        "data_version": data_version,
    }


# ---------------------------------------------------------------- sites and siting




def siting_cards(sites, res, buildings, lines, outlines=None) -> dict:
    cards = {}
    outlines = outlines if outlines is not None else ST.load_site_outlines()
    for s in sites:
        r = res.get(s.id)
        sysd = r["system"] if r else None
        need = None
        if sysd:
            k = sysd["pv_kwp"]
            need = k["point"] if isinstance(k, dict) else k
        rings = [outlines[i] for i in ST.site_way_ids(s) if i in outlines]
        rf = ST.roof(s.lat, s.lon, buildings, rings)
        rf["fit"] = ST.roof_fit(need or 0.0, rf) if need is not None else None
        bat = None if not sysd else (sysd["battery_kwh"]["point"] if isinstance(sysd["battery_kwh"], dict)
                                     else sysd["battery_kwh"])
        km = ST.km_to_lines(s.lat, s.lon, lines)
        cards[s.id] = {
            "id": s.id, "name": s.name, "sector": s.sector, "archetype": s.archetype, "lat": s.lat, "lon": s.lon,
            "lga": s.lga, "existing_onsite": s.existing_onsite, "note": s.note or None,
            "pv_kwp_needed": need, "battery_kwh": bat, "roof": rf,
            "placement": None if rf["fit"] is None else {
                "fits": "on the site's own roofs", "partial": "part on the site's own roofs, the rest "
                "ground-mounted inside the compound wall", "ground": "ground-mounted inside the compound wall (no "
                "mapped building is the site's own)", "unknown": "unknown: OSM maps no building within 250 m, so "
                "the compound cannot be read from the map"}[rf["fit"]],
            "battery_room": None if bat is None else f"{bat:,.1f} kWh in a lockable room or steel cage",
            "new_line_km": 0, "km_to_330kv": None if km is None else round(km, 2),
            "security": SECURITY, "ownership": next(o for o in OWNERSHIP if o["sector"] == s.sector),
            "labels": {"roof": LABELS["roof"], "security": LABELS["security"], "ownership": LABELS["ownership"],
                       **s.labels},
            "label_status": label_status({"roof": 1, "security": 1, "ownership": 1, **s.labels}, s.archetype),
            "facility_id": s.ref.get("unique_id"),
            "sim": None if (s.existing_onsite or not sysd) else (r.get("sim") if s.sector == "health" else {
                "kind": "sector", "lat": s.lat, "lon": s.lon, "bands": s.bands, "hours": s.hours, "start": s.start,
                "mode": s.mode, "kw": s.kw, "pv_kwp": need, "battery_kwh": bat, "n_draws": r.get("n_draws", 48)}),
            "sources": [site_source(x) for x in s.sources],
        }
    return cards


HEALTH_TIER = {"a_named": "feeder band: the facility is named in a NERC row",
               "b_place": "feeder band: the facility's ward or settlement is named in a NERC row",
               "c_lga_mixture": "LGA band mixture: NERC rows naming places in the LGA",
               "offgrid": "off-grid: no grid within reach (gridfinder)",
               "d_refused": "supply unknown: the match was refused"}


RANK_DAYS = 60
RANK_RULE = (f"city plan order: critical service-hours gained in a {RANK_DAYS}-day outage (with the plan minus today), "
             "most first; ties by lower capex, then site id. Sites already powered on site (UMTH) are not ranked")
_CRIT = LD.critical()
HEALTH_KW = float(LD.priority_profile(_CRIT)[1].sum(axis=0).max())
HEALTH_KWH_DAY = LD.daily_kwh(_CRIT)
HEALTH_KW_LABEL = ("critical load of a health site: the SEforALL Type 2 PHC priority-1 loads (delivery room, oxygen, "
                   f"interior lights), peak {HEALTH_KW:.2f} kW, {HEALTH_KWH_DAY:.2f} kWh/day; an archetype, not "
                   "measured per facility; the vaccine fridge is a separate PQS system")


def plan_rank(sites, res, days: int = RANK_DAYS) -> dict[str, int]:
    rows = []
    for s in sites:
        r = res.get(s.id)
        if s.existing_onsite or not r:
            continue
        x = r["by_days"][days]
        rows.append((-(x["with_h"] - (x["today_h"] or 0.0)), r["system"]["capex_ngn"]["point"], s.id))
    return {sid: i + 1 for i, (_, _, sid) in enumerate(sorted(rows))}


def sites_geojson(sites, res, siting, days=DAYS) -> dict:
    feats = []
    ranks = plan_rank(sites, res)
    for s in sites:
        r = res.get(s.id)
        by = {}
        if r and not s.existing_onsite:
            for d in days:
                x = r["by_days"][d]
                by[str(d)] = {"needed_h": round(x["needed_h"], 1),
                              "today_h": None if x["today_h"] is None else round(x["today_h"], 1),
                              "with_h": round(x["with_h"], 1),
                              "diesel_l_avoided": round(x["diesel_l_avoided"]["point"], 2)}
        sysd = None
        if r:
            k, b = r["system"]["pv_kwp"], r["system"]["battery_kwh"]
            sysd = {"pv_kwp": round(k["point"] if isinstance(k, dict) else k, 3),
                    "battery_kwh": round(b["point"] if isinstance(b, dict) else b, 2),
                    "capex_ngn": round(r["system"]["capex_ngn"]["point"], 0)}
        sc = siting[s.id]
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(s.lon, 6),
                                                                                     round(s.lat, 6)]},
                      "properties": {"id": s.id, "facility_id": s.ref.get("unique_id"), "rank": ranks.get(s.id),
                                     "sector": s.sector, "archetype": s.archetype, "name": s.name,
                                     "lga": s.lga, "kw": round(s.kw if s.sector != "health" else HEALTH_KW, 3),
                                     "kw_range": [round(s.kw_lo, 3), round(s.kw_hi, 3)] if s.sector != "health"
                                     else None,
                                     "kwh_day": round(s.kw * min(s.hours, 24.0) if s.sector != "health"
                                                      else HEALTH_KWH_DAY, 3),
                                     "hours_per_day": s.hours if s.sector != "health" else None,
                                     "supply": s.supply_label or HEALTH_TIER.get((r or {}).get("tier")),
                                     "m3_day": s.daily_m3,
                                     "existing_onsite": s.existing_onsite, "note": s.note or None,
                                     "in_plan": not s.existing_onsite, "system": None if s.existing_onsite else sysd,
                                     "results": by or None, "siting": {"fit": sc["roof"]["fit"],
                                                               "roof_kwp": round(sc["roof"]["roof_kwp"]["point"], 2),
                                                               "km_to_330kv": sc["km_to_330kv"]},
                                     "labels": (s.labels or {}) | ({"kw": HEALTH_KW_LABEL} if s.sector == "health"
                                                                   else {}) or None,
                                     "label_status": label_status((s.labels or {}) | ({"kw": 1} if s.sector == "health"
                                                                                       else {}), s.archetype)}})
    return {"type": "FeatureCollection", "features": feats,
            "properties": {"rank_rule": RANK_RULE, "facility_id": "the GRID3 unique_id for health sites (the id "
                                                                  "/api/facilities takes); null for other sectors"}}


# ---------------------------------------------------------------- build


def config(n_draws: int = 48) -> SM.SimConfig:
    shortfall, _ = SP.calibrated_from_work()
    return SM.SimConfig(n_draws=n_draws, shortfall=shortfall)


def results_data_version() -> str | None:
    """The data version the API reports for data/work (api.store_build.data_version), so a metrics file names the
    results it was built from."""
    try:
        from api.store_build import data_version

        return data_version(paths.WORK)
    except Exception:  # noqa: BLE001 - api/ absent
        return None


def build_city(city_id: str, cfg: SM.SimConfig, workers: int = 1, buildings=None, lines=None,
               corridor=None, inputs=None, data_version: str | None = None) -> dict:
    t0 = time.perf_counter()
    fac, m = inputs or ST.load_inputs()
    sites, excl = ST.city_sites(city_id, fac, m)
    res = site_results(sites, cfg, DAYS, workers)
    buildings = buildings if buildings is not None else ST.load_buildings()
    lines = lines if lines is not None else ST.corridor_lines()
    corridor = corridor or corridor_stats()
    siting = siting_cards(sites, res, buildings, lines)
    rt = round(time.perf_counter() - t0, 1)
    dv = data_version or results_data_version()
    metrics = {d: city_metrics(city_id, sites, res, d, excl, corridor, siting, rt, dv) for d in DAYS}
    return {"sites": sites, "results": res, "siting": siting, "metrics": metrics,
            "geojson": sites_geojson(sites, res, siting), "runtime_s": rt}


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return round(f, 6) if math.isfinite(f) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def write(out_dir: Path, name: str, obj) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(_clean(obj), separators=(",", ":"), ensure_ascii=False, allow_nan=False))
    tmp.replace(p)
    return p


def build(cities=tuple(ST.CITIES), out_dir: Path = OUT, workers: int = 1, n_draws: int = 48) -> dict:
    cfg = config(n_draws)
    inputs = ST.load_inputs()
    buildings = ST.load_buildings()
    lines = ST.corridor_lines()
    corridor = corridor_stats()
    dv = results_data_version()
    meta = {"cities": {}, "days": list(DAYS), "n_draws": n_draws, "corridor": corridor, "data_version": dv}
    for c in cities:
        b = build_city(c, cfg, workers, buildings, lines, corridor, inputs, dv)
        for d, mtr in b["metrics"].items():
            write(out_dir, f"metrics-{c}-{d}.json", mtr)
        write(out_dir, f"sites-{c}.geojson", b["geojson"])
        write(out_dir, f"siting-{c}.json", b["siting"])
        meta["cities"][c] = {"sites": len(b["sites"]), "runtime_s": b["runtime_s"],
                             "by_sector": dict(Counter(s.sector for s in b["sites"]))}
    write(out_dir, "corridor.geojson", corridor_geojson())
    write(out_dir, "meta.json", meta)
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", default=",".join(ST.CITIES))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--draws", type=int, default=48)
    ap.add_argument("--fixtures", default=None, help="also copy the build to this fixtures folder")
    a = ap.parse_args(argv)
    meta = build(tuple(x for x in a.cities.split(",") if x), Path(a.out), a.workers, a.draws)
    if a.fixtures:
        write_fixtures(Path(a.out), Path(a.fixtures))
    print(json.dumps(meta, indent=1))


FIXTURE_DAYS = (14, 40, 60)


def write_fixtures(src: Path, dst: Path) -> list[str]:
    """Copy the build into the web stream's fixtures (data/fixtures/brief13): metrics at 14, 40 and 60 days, sites,
    siting, corridor, meta, and one siting card on its own. These are engine output, not invented samples."""
    import shutil

    dst.mkdir(parents=True, exist_ok=True)
    names = [p.name for p in src.iterdir() if p.suffix in (".json", ".geojson")
             and not (p.name.startswith("metrics-") and int(p.stem.rsplit("-", 1)[1]) not in FIXTURE_DAYS)]
    for n in names:
        shutil.copyfile(src / n, dst / n)
    card = json.loads((src / "siting-maiduguri.json").read_text())
    k = next((i for i in card if i.startswith("C-")), next(iter(card)))
    write(dst, "siting-card-example.json", {**card[k], "city": "maiduguri"})
    names += fixture_traces(card, dst)
    return sorted(names)


def fixture_traces(card: dict, dst: Path, days=FIXTURE_DAYS) -> list[str]:
    """Hourly traces for the 3D night in the fixtures: one solar borehole, one motorized borehole, one market cold room
    and one health facility of Maiduguri, at 14, 40 and 60 days, written as the live API serves them."""
    from fastapi.testclient import TestClient

    from api.config import Settings
    from api.main import create_app

    want = {}
    for sid, c in card.items():
        key = c["archetype"] if c["sector"] != "health" else "health"
        if key in ("solar_borehole", "motorized_borehole", "market_cold_room", "health") and key not in want \
                and not c.get("existing_onsite"):
            want[key] = sid
    out = []
    s = Settings(fixture=False, rate_read=10_000, rate_simulate=10_000)
    with TestClient(create_app(s)) as cl:
        for sid in want.values():
            for d in days:
                r = cl.get(f"/api/sites/{sid}/outage_trace", params={"days": d})
                if r.status_code == 200:
                    name = f"trace-{sid}-{d}.json"
                    (dst / name).write_bytes(r.content)
                    out.append(name)
    return out


if __name__ == "__main__":
    main()
