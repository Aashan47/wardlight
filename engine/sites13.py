"""Brief 13 critical sites for a city: health facilities (GRID3 + engine results), water (iMMAP 2019 boreholes, the
OSM water works) and cold chain + markets (named OSM marketplaces, one cold room each).

Cities: `maiduguri` (Maiduguri + Jere LGAs, Borno), `damaturu` (Damaturu LGA, Yobe), `yola` (Yola North + Yola South,
Adamawa). Water and market data exist for Maiduguri + Jere (iMMAP survey of eleven Borno LGAs; OSM extracts of the
Maiduguri box). Damaturu and Yola carry health facilities, plus the named markets found in the Geofabrik pass of
their boxes (`osm_buildings_extract.py`); no public water-point survey is loaded for them, and the labels say so.

Supply for a non-health site: the band of the NERC rows naming its ward, where a health facility in the same ward was
matched on the ward name (tier b_place); else the LGA band mixture used for health facilities there (tier
c_lga_mixture); else unknown, simulated as off-grid and labelled. Solar boreholes are taken as off the grid.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

import pandas as pd

from . import constants as C
from . import paths
from . import sector as X


@dataclass(frozen=True)
class City:
    id: str
    name: str
    state: str
    lgas: tuple[str, ...]
    water_data: bool
    market_data: str  # "maiduguri" (OSM objects CSV) or "geofabrik_box" (osm_buildings_extract objects) or ""
    box: str = ""


CITIES: dict[str, City] = {
    "maiduguri": City("maiduguri", "Maiduguri", "Borno", ("Maiduguri", "Jere"), True, "maiduguri"),
    "damaturu": City("damaturu", "Damaturu", "Yobe", ("Damaturu",), False, "geofabrik_box", "damaturu"),
    "yola": City("yola", "Yola", "Adamawa", ("Yola North", "Yola South"), False, "geofabrik_box", "yola"),
}

DL = paths.DATA_LOCAL
IMMAP_CSV = DL / "water" / "borno11" / "NGA_North_East_Nigeria_Borno_WASH_WaterPoints_11LGA_Hotspots.csv"
OSM_OBJECTS = DL / "osm-geofabrik" / "maiduguri_jere_objects.csv"
OSM_OVERPASS = DL / "osm-overpass" / "maiduguri_jere_critical_2026-10-30T2158Z.json"
BOX_OBJECTS = DL / "osm-geofabrik" / "damaturu_yola_objects.csv"
BUILDINGS = DL / "osm-geofabrik" / "buildings_near_sites.csv"  # centroids only (first pass, kept for the record)
OUTLINES = DL / "osm-geofabrik" / "buildings_outlines_near_sites.csv"
SITE_OUTLINES = DL / "osm-geofabrik" / "site_outlines.csv"
CORRIDOR = DL / "osm-geofabrik" / "corridor_power.geojson"

SRC_OSM = "OpenStreetMap (ODbL, (c) OpenStreetMap contributors), Geofabrik extract 30 Oct 2026"
SRC_GRID3 = "GRID3 Nigeria health facilities v3.0 (CC BY 4.0) with the Wardlight engine results"

IMMAP_COLS = {"Unnamed: 0": "row", "LGA": "lga", "Ward": "ward", "Location Name": "location",
              "Location Type": "location_type", "Water Source": "source", "Long": "lon", "Lat": "lat",
              "Yield (Ltrs/Sec)": "yield_l_s", "Operating Hours": "hours", "Daily Production (m3)": "m3_day",
              "Optimal Level?": "optimal", "Way Forward": "way_forward"}

# the named markets of Maiduguri + Jere (brief 13 plan); unnamed marketplaces and shops are dropped
MAIDUGURI_MARKETS = ("Maiduguri Monday Market", "Baga Road Market", "Gamboru Market", "Kasuwan Shanu", "Abattoir",
                     "Vegetable Market", "Bulumkutu GSM Village", "Bama Motor Park Shopping centre")
UMTH_RX = re.compile(r"^University Of Maiduguri Teaching Hospital( Umth)?$", re.I)
UMTH_NOTE = ("12 MW UNIMAID/UMTH hybrid solar plant and a battery plant mapped in OSM (ways 1424431051, "
             "1561720799); reported by the World Bank and press. The resident engineer described 7 MWh of batteries "
             "and a 10 MW diesel backup (Gatekeepers News, 25 May 2024); the Rural Electrification Agency lists it "
             "OPERATIONAL (EEP Phase II page); the UMTH share is reported as 4.5 to 5 MW")


@dataclass
class Site:
    id: str
    sector: str  # health | water | cold
    archetype: str
    name: str
    city: str
    lga: str
    lat: float
    lon: float
    kw: float = 0.0  # running load, point
    kw_lo: float = 0.0
    kw_hi: float = 0.0
    hours: float = 24.0
    start: int = 0
    mode: str = "grid"  # grid | solar_direct
    bands: object = None
    supply_label: str = ""
    daily_m3: float | None = None
    existing_onsite: bool = False
    note: str = ""
    labels: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    ref: dict = field(default_factory=dict)  # health: unique_id; OSM ids; survey row

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- supply for non-health sites


def _bands_key(b) -> str:
    return b if isinstance(b, str) else json.dumps(b, sort_keys=True)


def supply_context(city: City, facilities: pd.DataFrame, matches: pd.DataFrame) -> dict:
    """{'ward': {(lga, ward): bands}, 'lga': {lga: bands}} from the health matches of the city's LGAs."""
    f = facilities[(facilities.state_standard == city.state) & facilities.lga_standard.isin(city.lgas)]
    m = matches.merge(f[["unique_id", "lga_standard", "ward_standard"]], on="unique_id")
    ward: dict = {}
    for (lga, w), g in m[m.tier == "b_place"].groupby(["lga_standard", "ward_standard"]):
        ev = [json.loads(e).get("matched_on") if isinstance(e, str) else None for e in g.evidence]
        g = g[[x == "ward_standard" for x in ev]]
        if len(g):
            ward[(lga.lower(), str(w).lower())] = json.loads(Counter(g.bands).most_common(1)[0][0])
    lga: dict = {}
    for name, g in m[m.tier == "c_lga_mixture"].groupby("lga_standard"):
        lga[name.lower()] = json.loads(Counter(g.bands).most_common(1)[0][0])
    return {"ward": ward, "lga": lga}


def site_supply(ctx: dict, lga: str, ward: str | None = None) -> tuple[object, str]:
    b = ctx["ward"].get((lga.lower(), (ward or "").lower()))
    if b:
        return b, f"band of the NERC rows naming {ward} ward (as matched for a health facility there)"
    b = ctx["lga"].get(lga.lower())
    if b:
        return b, f"{lga} LGA band mixture (NERC rows naming places in the LGA, as for health); no feeder match"
    return "OFFGRID", "supply unknown (no NERC row for the LGA); simulated as off-grid (UNVERIFIED)"


# ---------------------------------------------------------------- geometry helpers

R_EARTH = 6371008.8


def dist_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH * math.asin(min(1.0, math.sqrt(h)))


def nearest_lga(lat: float, lon: float, fac: pd.DataFrame) -> str:
    f = fac.dropna(subset=["latitude", "longitude"])
    d = (f.latitude - lat) ** 2 + ((f.longitude - lon) * math.cos(math.radians(lat))) ** 2
    return str(f.lga_standard.iloc[int(d.to_numpy().argmin())])


# ---------------------------------------------------------------- water


def water_sites(city: City, ctx: dict) -> tuple[list[Site], dict]:
    if not city.water_data or not IMMAP_CSV.exists():
        return [], {"note": f"no public water-point survey loaded for {city.name}"}
    w = pd.read_csv(IMMAP_CSV).rename(columns=IMMAP_COLS)
    w = w[w.lga.str.lower().isin([x.lower() for x in city.lgas])]
    excl = Counter()
    sites: list[Site] = []
    for r in w.itertuples(index=False):
        src = str(r.source).strip()
        row = int(r.row)
        lga = str(r.lga).title()
        ward = str(r.ward)
        y = float(r.yield_l_s) if pd.notna(r.yield_l_s) else 0.0
        hrs = r.hours
        if src.lower() == "hand pump":
            excl["hand_pump_no_power_need"] += 1
            continue
        if y <= 0:
            excl["no_yield_recorded"] += 1
            continue
        if pd.notna(hrs) and float(hrs) == 0:
            excl["not_operating_at_survey"] += 1
            continue
        labels = {"pump_kw": "P = rho g H Q / eta from the survey yield; head 40 to 120 m and efficiency 0.35 to 0.55 "
                             "are ASSUMPTION ranges (research stream to replace)"}
        if pd.isna(hrs):
            hrs = C.BH_DEFAULT_HOURS.value
            labels["hours"] = "operating hours blank in the survey; 8 h assumed (the survey's most common value)"
        hrs = float(hrs)
        p = X.pump_kw(y)
        solar = src.lower().startswith("solar")
        if solar:
            bands, sl = "OFFGRID", "solar borehole: taken as off the grid; the existing array pumps in daylight only"
            labels["today"] = ("existing array pumps in proportion to its output; its size is an ASSUMPTION "
                               "(1.2 to 2.0 kWp per pump kW)")
        else:
            bands, sl = site_supply(ctx, lga, ward)
        m3 = r.m3_day
        m3 = float(m3) if pd.notna(m3) and float(m3) > 0 else y * hrs * 3.6
        sites.append(Site(
            f"W-BH-{row}", "water", "solar_borehole" if solar else "motorized_borehole",
            f"{r.location} ({'solar' if solar else 'motorized'} borehole)", city.id, lga, float(r.lat),
            float(r.lon), p.point, p.lo, p.hi, hrs, X.window_start(hrs), "solar_direct" if solar else "grid",
            bands, sl, m3, labels=labels, sources=[C.B13_IMMAP],
            ref={"immap_row": row, "ward": ward, "location_type": r.location_type, "yield_l_s": y,
                 "survey_hours": None if pd.isna(r.hours) else float(r.hours),
                 "optimal_level": r.optimal, "way_forward": None if pd.isna(r.way_forward)
                 else str(r.way_forward).strip()}))
    return sites, dict(excl)


def works_site(city: City, ctx: dict) -> list[Site]:
    if city.id != "maiduguri" or not OSM_OBJECTS.exists():
        return []
    g = pd.read_csv(OSM_OBJECTS)
    t = g.tags.map(json.loads)
    k = g[[x.get("man_made") in ("clarifier", "wastewater_plant") for x in t]]
    if not len(k):
        return []
    lat, lon = float(k.lat.mean()), float(k.lon.mean())
    lga = "Jere" if lat < 11.83 and lon > 13.18 else "Maiduguri"
    bands, sl = site_supply(ctx, lga)
    c = C.WATER_WORKS_KW
    return [Site("W-WORKS-1", "water", "water_works", "Water treatment works (OSM clarifiers and wastewater plant)",
                 city.id, lga, lat, lon, c.value, c.lo, c.hi, 24.0, 0, "grid", bands, sl, None,
                 note="partner needed: load unknown",
                 labels={"load": "ASSUMPTION 30 to 300 kW continuous; partner needed (operator's load data)",
                         "lga": "LGA assigned from the location (inside Jere's boundary is not checked)"},
                 sources=[SRC_OSM], ref={"osm_ways": [int(x) for x in k.osm_id]})]


# ---------------------------------------------------------------- cold chain + markets


def market_sites(city: City, ctx: dict, fac: pd.DataFrame) -> tuple[list[Site], dict]:
    rows = []
    if city.market_data == "maiduguri" and OSM_OBJECTS.exists():
        g = pd.read_csv(OSM_OBJECTS)
        for r, t in zip(g.itertuples(index=False), g.tags.map(json.loads)):
            if t.get("amenity") == "marketplace" and isinstance(r.name, str) and r.name in MAIDUGURI_MARKETS:
                rows.append((r.name, r.osm_type, int(r.osm_id), float(r.lat), float(r.lon), t))
    elif city.market_data == "geofabrik_box" and BOX_OBJECTS.exists():
        with open(BOX_OBJECTS, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                t = json.loads(r["tags"])
                if r["box"] == city.box and t.get("amenity") == "marketplace" and r["name"].strip():
                    rows.append((r["name"], r["osm_type"], int(r["osm_id"]), float(r["lat"]), float(r["lon"]), t))
    by: dict[str, list] = {}
    for x in rows:
        by.setdefault(x[0], []).append(x)
    sites = []
    for name, xs in by.items():
        lat = sum(x[3] for x in xs) / len(xs)
        lon = sum(x[4] for x in xs) / len(xs)
        lga = nearest_lga(lat, lon, fac)
        bands, sl = site_supply(ctx, lga)
        label = name if name.lower() != "market" else f"{city.name} market (OSM name 'Market')"
        y = X.daily_yield_kwh_per_kwp(lat, lon)  # (mean, lowest year, highest year)
        kwh = [C.COLDHUB_PV_KWP.value * v for v in y]
        sites.append(Site(
            f"C-{xs[0][2]}", "cold", "market_cold_room", label, city.id, lga, lat, lon, kwh[0] / 24, kwh[1] / 24,
            kwh[2] / 24, 24.0, 0, "grid", bands, sl, None,
            labels={"load": f"one ColdHubs-type room per market (about 3 t, 150 crates, 5.5 kWp; VERIFIED_SECONDARY); "
                            f"no kWh/day is published, so the load is DERIVED as the array's mean daily yield here, "
                            f"{kwh[0]:.1f} kWh/day ({kwh[1]:.1f} to {kwh[2]:.1f} over the weather years), 24 h",
                    "lga": "LGA of the nearest health facility"},
            sources=[SRC_OSM], ref={"osm": [{"type": x[1], "id": x[2]} for x in xs],
                                    "operator": next((x[5].get("operator") for x in xs if x[5].get("operator")), None),
                                    "deduplicated_objects": len(xs)}))
    note = None if sites else f"no named marketplace mapped in OSM for {city.name}"
    return sites, {"markets": len(sites), "osm_objects": len(rows), "note": note}


# ---------------------------------------------------------------- health


def health_sites(city: City, fac: pd.DataFrame, res_ids: set[str]) -> tuple[list[Site], dict]:
    f = fac[(fac.state_standard == city.state) & fac.lga_standard.isin(city.lgas)]
    f = f.sort_values("latitude", na_position="last").drop_duplicates("unique_id")
    sites, excl = [], Counter()
    for r in f.itertuples(index=False):
        if pd.isna(r.latitude) or pd.isna(r.longitude):
            excl["no_coordinates"] += 1
            continue
        if r.unique_id not in res_ids:
            excl["no_engine_result"] += 1
            continue
        onsite = bool(UMTH_RX.match(str(r.facility_name or "")))
        s = Site(f"H-{r.unique_id}", "health", "health_facility", str(r.facility_name), city.id, str(r.lga_standard),
                 float(r.latitude), float(r.longitude), sources=[SRC_GRID3],
                 ref={"unique_id": r.unique_id, "facility_level": r.facility_level, "facility_type": r.facility_type})
        if onsite:
            s.existing_onsite = True
            s.note = UMTH_NOTE
            excl["existing_onsite"] += 1
        sites.append(s)
    return sites, dict(excl)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    fac = pd.read_parquet(paths.FACILITIES)
    m = pd.read_parquet(paths.MATCHES, columns=["unique_id", "tier", "bands", "evidence"])
    return fac, m


def city_sites(city_id: str, fac: pd.DataFrame | None = None, matches: pd.DataFrame | None = None,
               res_ids: set[str] | None = None) -> tuple[list[Site], dict]:
    city = CITIES[city_id]
    if fac is None or matches is None:
        fac, matches = load_inputs()
    if res_ids is None:
        res_ids = set(pd.read_parquet(paths.FACILITY_RESULTS, columns=["unique_id"]).unique_id)
    ctx = supply_context(city, fac, matches)
    cf = fac[(fac.state_standard == city.state) & fac.lga_standard.isin(city.lgas)]
    h, he = health_sites(city, fac, res_ids)
    w, we = water_sites(city, ctx)
    ww = works_site(city, ctx)
    m, me = market_sites(city, ctx, cf)
    return h + w + ww + m, {"health": he, "water": we, "cold": me,
                            "water_works": len(ww)}


# ---------------------------------------------------------------- roofs and corridor


def load_buildings() -> pd.DataFrame:
    """Building outlines near the sites (osm_site_polygons_extract.py): osm_id, lat, lon, area_m2, ring."""
    if not OUTLINES.exists():
        return pd.DataFrame(columns=["osm_id", "lat", "lon", "area_m2", "ring"])
    b = pd.read_csv(OUTLINES, usecols=["osm_id", "lat", "lon", "area_m2", "coords"])
    b["ring"] = [[(float(a), float(o)) for a, o in json.loads(c)] for c in b.coords]
    return b.drop(columns="coords")


def load_site_outlines() -> dict[int, list[tuple[float, float]]]:
    """{OSM way id: ring} for marketplaces, clarifiers, wastewater plants and retail areas in the city boxes."""
    if not SITE_OUTLINES.exists():
        return {}
    o = pd.read_csv(SITE_OUTLINES, usecols=["osm_id", "coords"])
    return {int(i): [(float(a), float(b)) for a, b in json.loads(c)] for i, c in zip(o.osm_id, o.coords)}


def site_way_ids(s: Site) -> list[int]:
    ids = [int(x["id"]) for x in s.ref.get("osm", []) if x.get("type") == "way"]
    return ids + [int(x) for x in s.ref.get("osm_ways", [])]


def _xy(lat0: float, lon0: float):
    kx, ky = math.cos(math.radians(lat0)) * 111_320.0, 110_574.0
    return lambda la, lo: ((lo - lon0) * kx, (la - lat0) * ky)


def in_ring(x: float, y: float, ring_xy) -> bool:
    inside = False
    n = len(ring_xy)
    for i in range(n):
        (x1, y1), (x2, y2) = ring_xy[i], ring_xy[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


def _seg_dist(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - x1 - t * dx, py - y1 - t * dy)


def ring_dist_m(x: float, y: float, ring_xy) -> float:
    """0 inside the ring, else the distance to its edge (m)."""
    if in_ring(x, y, ring_xy):
        return 0.0
    n = len(ring_xy)
    return min(_seg_dist(x, y, *ring_xy[i], *ring_xy[(i + 1) % n]) for i in range(n))


def _cross(a, b, c, d) -> bool:
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return (o(a, b, c) * o(a, b, d) <= 0) and (o(c, d, a) * o(c, d, b) <= 0)


def rings_touch(r1, r2) -> bool:
    """True when two rings overlap, one contains the other, or their edges meet."""
    if any(in_ring(x, y, r2) for x, y in r1) or any(in_ring(x, y, r1) for x, y in r2):
        return True
    e1 = list(zip(r1, r1[1:] + r1[:1]))
    e2 = list(zip(r2, r2[1:] + r2[:1]))
    return any(_cross(a, b, c, d) for a, b in e1 for c, d in e2)


def roof(site_lat: float, site_lon: float, b: pd.DataFrame, site_rings=None,
         nearest_m: float = C.ROOF_NEAREST_M.value, coverage_m: float = 250.0) -> dict:
    """The site's own roofs, by the tight rule:
    1. the site is mapped as an outline (a market, the water works): every building touching that outline;
    2. else the buildings whose footprint contains the site point;
    3. else the single nearest building within `nearest_m` of the point.
    No building: "ground" (a compound with mapped buildings around it, ground-mount inside the wall) when OSM maps
    buildings within `coverage_m`, else "unknown" (no mapped buildings: OSM coverage cannot say)."""
    to = _xy(site_lat, site_lon)
    dl = (coverage_m + 500.0) / 111_320.0
    cand = b[b.lat.between(site_lat - dl, site_lat + dl) & b.lon.between(site_lon - dl, site_lon + dl)]
    rings = {int(i): [to(a, o) for a, o in r] for i, r in zip(cand.osm_id, cand.ring)}
    dist = {i: ring_dist_m(0.0, 0.0, r) for i, r in rings.items()}
    covered = any(d <= coverage_m for d in dist.values())
    chosen: list[int] = []
    rule = "none"
    if site_rings:
        srs = [[to(a, o) for a, o in r] for r in site_rings]
        chosen = [i for i, r in rings.items() if any(rings_touch(r, sr) for sr in srs)]
        rule = "site_outline"
    if not chosen:
        chosen = [i for i, d in dist.items() if d == 0.0]
        rule = "contains_point" if chosen else rule
    if not chosen:
        near = sorted((d, i) for i, d in dist.items() if d <= nearest_m)
        chosen = [near[0][1]] if near else []
        rule = f"nearest_within_{nearest_m:g}m" if chosen else ("site_outline_no_building" if site_rings else "none")
    areas = cand.set_index("osm_id").area_m2
    area = float(sum(areas.loc[i] for i in chosen))
    big = float(max((areas.loc[i] for i in chosen), default=0.0))
    f, k = C.ROOF_USABLE_FRACTION, C.PV_KWP_PER_M2

    def kwp(a):
        return {"point": a * f.value * k.value, "lo": a * f.lo * k.lo, "hi": a * f.hi * k.hi}

    return {"buildings": len(chosen), "rule": rule, "osm_ids": chosen[:20], "footprint_m2": round(area, 1),
            "largest_m2": round(big, 1), "roof_kwp": kwp(area), "largest_roof_kwp": kwp(big),
            "mapped_buildings_nearby": covered}


def roof_fit(need_kwp: float, r: dict) -> str:
    if r["buildings"] == 0:
        return "ground" if r.get("mapped_buildings_nearby", True) else "unknown"
    return "fits" if r["roof_kwp"]["point"] >= need_kwp else "partial"


def corridor_lines() -> list[list[tuple[float, float]]]:
    """Every 330 kV LineString in the corridor extract (lines, and the outlines of 330/132 kV substations, so the
    Maiduguri substation at the end of way 282643989 counts), as (lat, lon) lists."""
    if not CORRIDOR.exists():
        return []
    g = json.loads(CORRIDOR.read_text())
    return [[(c[1], c[0]) for c in f["geometry"]["coordinates"]] for f in g["features"]
            if f["properties"].get("power") in ("line", "substation")
            and "330000" in str(f["properties"].get("voltage", "")) and f["geometry"]["type"] == "LineString"]


def km_to_lines(lat: float, lon: float, lines) -> float | None:
    """Haversine distance (km) to the nearest point on any 330 kV segment. The nearest point on each segment is
    found on a local plane around the site; the distance to it is then taken on the sphere."""
    if not lines:
        return None
    kx = math.cos(math.radians(lat)) * 111.32
    ky = 110.574
    best, at = float("inf"), None
    for ln in lines:
        for (a1, o1), (a2, o2) in zip(ln, ln[1:]):
            x1, y1, x2, y2 = (o1 - lon) * kx, (a1 - lat) * ky, (o2 - lon) * kx, (a2 - lat) * ky
            dx, dy = x2 - x1, y2 - y1
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / L2))
            d = math.hypot(x1 + t * dx, y1 + t * dy)
            if d < best:
                best, at = d, (a1 + t * (a2 - a1), o1 + t * (o2 - o1))
    return dist_m(lat, lon, at[0], at[1]) / 1000.0
