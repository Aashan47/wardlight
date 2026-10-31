"""Brief 13 city data and the budget plan, read from the files `python -m engine.metrics13` writes.

    data = City13Data()                      # data/work/brief13, else data/fixtures/brief13
    p = plan(data, "maiduguri", 2e9, days=60, sectors=["health", "water", "cold"])

Nothing here simulates. Every figure is a site result the engine wrote (`sites-<city>.geojson`: critical
service-hours needed, kept today and kept with the site's planned system, per outage window; diesel litres the
system avoids; capex) or a sum of them, or a sourced constant from the metrics file (the diesel price). The plan
rule is the sites collection's own rank (critical service-hours gained in a 60-day outage, most first; ties by
lower capex, then id), walked in that order under the budget: a site that does not fit is skipped and the walk
goes on (the same greedy rule as engine.plan.rank). The API (`api/agent13.py`), the planner tools
(`agents/tools13.py`), the verifier and the watcher all call this one function.
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
WORK13 = PROJECT / "data" / "work" / "brief13"
FIX13 = PROJECT / "data" / "fixtures" / "brief13"

CITIES: dict[str, dict] = {
    "maiduguri": {"name": "Maiduguri", "state": "Borno"},
    "damaturu": {"name": "Damaturu", "state": "Yobe"},
    "yola": {"name": "Yola", "state": "Adamawa"},
}
DEFAULT_CITY = "maiduguri"
SECTORS = ("health", "water", "cold")
SECTOR_NAME = {"health": "health facilities", "water": "water (boreholes and the water works)",
               "cold": "market cold rooms (cold chain)"}
SECTOR_ALIASES = {
    "health": "health", "hospital": "health", "hospitals": "health", "clinic": "health", "clinics": "health",
    "health facilities": "health", "water": "water", "borehole": "water", "boreholes": "water",
    "water pumping": "water", "cold": "cold", "cold chain": "cold", "cold rooms": "cold", "cold room": "cold",
    "market": "cold", "markets": "cold",
}
PLAN_RULE = ("walk the city's plan order (the sites collection's rank: critical service-hours gained in a "
             "60-day outage, most first; ties by lower capex, then site id) and fund each site whose capex fits "
             "in what is left of the budget; a site that does not fit is skipped and the walk goes on. Sites "
             "already powered on site (UMTH) are not in the plan")
CSH_LABEL = ("critical service-hours: for every critical load at a site, the hours in the outage window it is "
             "needed; 'today' is kept with no backup (the grid off for the whole window), 'with the funded "
             "sites' adds what each funded site's solar + storage system keeps; unfunded sites stay at today")
SPHERE_L_PER_DAY = 15.0  # Sphere 2018 minimum, the metrics file's people_served rule


class CityDataError(ValueError):
    """Bad city, window, sector or budget; or the brief 13 build is missing."""


def default_root() -> Path:
    return WORK13 if (WORK13 / "meta.json").is_file() else FIX13


def _num(x, nd: int | None = None):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    if nd is not None:
        return round(f, nd)
    a = abs(f)
    if a >= 1000:
        return round(f, 1)
    if a >= 1:
        return round(f, 3)
    return round(f, 6)


def _share(a: float, b: float) -> float | None:
    return round(a / b, 6) if b else None


class City13Data:
    """The brief 13 build on disk: sites, metrics and siting cards per city, read once and kept."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root else default_root()
        self._cache: dict[str, object] = {}

    def _json(self, name: str):
        if name not in self._cache:
            p = self.root / name
            if not p.is_file():
                raise CityDataError(f"{name} is not in the brief 13 build ({self.root}); run python -m engine.metrics13")
            self._cache[name] = json.loads(p.read_text(encoding="utf-8"))
        return self._cache[name]

    @property
    def meta(self) -> dict:
        try:
            return self._json("meta.json")  # type: ignore[return-value]
        except CityDataError:
            return {}

    @property
    def version(self) -> str:
        return str(self.meta.get("data_version") or "unknown")

    # -------------------------------------------------- lookups

    @staticmethod
    def resolve_city(city: str | None) -> str:
        c = (city or DEFAULT_CITY).strip().lower()
        for k, v in CITIES.items():
            if c in (k, v["name"].lower()):
                return k
        raise CityDataError(f"'{city}' is not a city in the brief 13 build; cities: "
                            f"{', '.join(v['name'] for v in CITIES.values())}")

    @staticmethod
    def resolve_sectors(sectors) -> tuple[str, ...]:
        if sectors is None or sectors == [] or sectors == "":
            return SECTORS
        if isinstance(sectors, str):
            sectors = [x for x in sectors.replace(";", ",").split(",")]
        out = []
        for s in sectors:
            k = SECTOR_ALIASES.get(str(s).strip().lower())
            if k is None:
                raise CityDataError(f"unknown sector '{s}'; sectors: health, water, cold")
            if k not in out:
                out.append(k)
        return tuple(x for x in SECTORS if x in out)

    def collection(self, city: str) -> dict:
        return self._json(f"sites-{self.resolve_city(city)}.geojson")  # type: ignore[return-value]

    def sites(self, city: str) -> list[dict]:
        key = f"_sites:{self.resolve_city(city)}"
        if key not in self._cache:
            out = []
            for f in self.collection(city)["features"]:
                p = dict(f["properties"])
                lon, lat = f["geometry"]["coordinates"][:2]
                p["lon"], p["lat"] = float(lon), float(lat)
                out.append(p)
            self._cache[key] = out
        return self._cache[key]  # type: ignore[return-value]

    def rank_rule(self, city: str) -> str | None:
        return (self.collection(city).get("properties") or {}).get("rank_rule")

    def days_available(self, city: str) -> tuple[int, ...]:
        ranked = [s for s in self.sites(city) if s.get("rank") is not None]
        if not ranked:
            return ()
        keys = set(ranked[0].get("results") or {})
        for s in ranked[1:]:
            keys &= set(s.get("results") or {})
        return tuple(sorted(int(k) for k in keys if str(k).isdigit()))

    def metrics_days(self, city: str) -> tuple[int, ...]:
        c = self.resolve_city(city)
        return tuple(sorted(int(p.stem.rsplit("-", 1)[1]) for p in self.root.glob(f"metrics-{c}-*.json")))

    def metrics(self, city: str, days: int) -> dict:
        c = self.resolve_city(city)
        avail = self.metrics_days(c)
        if int(days) not in avail:
            raise CityDataError(f"no city metrics for {days} days; windows: {', '.join(map(str, avail))}")
        return self._json(f"metrics-{c}-{int(days)}.json")  # type: ignore[return-value]

    def any_metrics(self, city: str) -> dict:
        avail = self.metrics_days(city)
        if not avail:
            raise CityDataError("no city metrics in the brief 13 build")
        return self.metrics(city, 60 if 60 in avail else avail[-1])

    def siting(self, city: str) -> dict:
        try:
            return self._json(f"siting-{self.resolve_city(city)}.json")  # type: ignore[return-value]
        except CityDataError:
            return {}

    def find_site(self, site_id: str) -> tuple[str, dict, dict]:
        """(city, site properties, siting card) for a site id."""
        sid = (site_id or "").strip()
        for c in CITIES:
            try:
                hit = next((s for s in self.sites(c) if s["id"] == sid), None)
            except CityDataError:
                continue
            if hit is not None:
                return c, hit, self.siting(c).get(sid) or {}
        raise CityDataError(f"no site '{site_id}' in the brief 13 build")

    def constant(self, city: str, name: str) -> dict | None:
        consts = ((self.any_metrics(city).get("labels") or {}).get("constants") or {})
        return consts.get(name)

    def diesel_price(self, city: str) -> dict:
        c = self.constant(city, "DIESEL_NGN_PER_L") or {}
        if c.get("value") is None:
            raise CityDataError("the diesel price constant is not in the metrics file")
        return {"ngn_per_l": float(c["value"]), "lo": c.get("lo"), "hi": c.get("hi"), "status": c.get("status"),
                "source": c.get("source")}


# ---------------------------------------------------------------- the plan


def _res(site: dict, days: int) -> dict:
    r = (site.get("results") or {}).get(str(days)) or {}
    return {"needed_h": float(r.get("needed_h") or 0.0), "today_h": float(r.get("today_h") or 0.0),
            "with_h": float(r.get("with_h") or 0.0), "diesel_l_avoided": float(r.get("diesel_l_avoided") or 0.0)}


def _item(site: dict, days: int, order: int | None, cumulative: float | None) -> dict:
    r = _res(site, days)
    sysm = site.get("system") or {}
    sit = site.get("siting") or {}
    return {"order": order, "rank": site.get("rank"), "id": site["id"], "facility_id": site.get("facility_id"),
            "name": site.get("name"), "sector": site.get("sector"), "archetype": site.get("archetype"),
            "lga": site.get("lga"), "capex_ngn": _num(sysm.get("capex_ngn"), 0),
            "cumulative_ngn": _num(cumulative, 0) if cumulative is not None else None,
            "pv_kwp": _num(sysm.get("pv_kwp")), "battery_kwh": _num(sysm.get("battery_kwh")),
            "kw": _num(site.get("kw")), "needed_h": _num(r["needed_h"]), "today_h": _num(r["today_h"]),
            "with_h": _num(r["with_h"]), "gained_h": _num(r["with_h"] - r["today_h"]),
            "diesel_l_avoided": _num(r["diesel_l_avoided"]), "roof_fit": sit.get("fit"),
            "roof_kwp": _num(sit.get("roof_kwp")), "km_to_330kv": _num(sit.get("km_to_330kv")),
            "lon": site.get("lon"), "lat": site.get("lat")}


def _group(sites: list[dict], funded_ids: set[str], days: int, price: float) -> dict:
    needed = today = with_f = with_all = litres = capex_f = capex_all = 0.0
    n_f = 0
    for s in sites:
        r = _res(s, days)
        cap = float((s.get("system") or {}).get("capex_ngn") or 0.0)
        needed += r["needed_h"]
        today += r["today_h"]
        with_all += r["with_h"]
        capex_all += cap
        if s["id"] in funded_ids:
            n_f += 1
            with_f += r["with_h"]
            litres += r["diesel_l_avoided"]
            capex_f += cap
        else:
            with_f += r["today_h"]
    return {"sites": len(sites), "funded": n_f, "not_funded": len(sites) - n_f,
            "csh_needed": _num(needed), "csh_today": _num(today), "csh_with_funded": _num(with_f),
            "csh_with_every_site": _num(with_all), "csh_gained": _num(with_f - today),
            "share_today": _share(today, needed), "share_with_funded": _share(with_f, needed),
            "share_with_every_site": _share(with_all, needed),
            "diesel_l_avoided": _num(litres), "diesel_ngn_avoided": _num(litres * price, 0),
            "capex_funded_ngn": _num(capex_f, 0), "capex_every_site_ngn": _num(capex_all, 0),
            "capex_to_fund_the_rest_ngn": _num(capex_all - capex_f, 0)}


def _water(sites: list[dict], funded_ids: set[str], days: int) -> dict:
    """m3 per day kept and the people that serves at the Sphere minimum (the metrics file's own rule)."""
    m3_today = m3_with = 0.0
    for s in sites:
        r = _res(s, days)
        if s.get("m3_day") and r["needed_h"] > 0:
            m3_today += s["m3_day"] * r["today_h"] / r["needed_h"]
            kept = r["with_h"] if s["id"] in funded_ids else r["today_h"]
            m3_with += s["m3_day"] * kept / r["needed_h"]
    per = SPHERE_L_PER_DAY / 1000.0
    return {"m3_per_day_today": _num(m3_today), "m3_per_day_with_funded": _num(m3_with),
            "people_today_upper": _num(m3_today / per, 0), "people_with_funded_upper": _num(m3_with / per, 0),
            "label": "m3 per day / 0.015: the Sphere 2018 minimum of 15 L per person per day, so an upper count"}


def plan(data: City13Data, city: str, budget_ngn: float, days: int = 60, sectors=None) -> dict:
    c = data.resolve_city(city)
    secs = data.resolve_sectors(sectors)
    try:
        budget = float(budget_ngn)
    except (TypeError, ValueError):
        raise CityDataError("budget must be a number of naira") from None
    if not math.isfinite(budget) or budget < 0:
        raise CityDataError("budget must be zero or a positive number of naira")
    d = int(days)
    avail = data.days_available(c)
    if d not in avail:
        raise CityDataError(f"outage days must be one of {', '.join(map(str, avail))}")
    price = data.diesel_price(c)
    all_sites = data.sites(c)
    ranked = sorted((s for s in all_sites if s.get("rank") is not None), key=lambda s: (s["rank"], s["id"]))
    scope = [s for s in ranked if s.get("sector") in secs]
    spent, order = 0.0, 0
    funded: list[dict] = []
    skipped: list[dict] = []
    rows: list[dict] = []
    for s in scope:
        cap = float((s.get("system") or {}).get("capex_ngn") or 0.0)
        if spent + cap <= budget + 1e-6:
            spent += cap
            order += 1
            it = _item(s, d, order, spent)
            funded.append(it)
            rows.append({**it, "funded": True})
        else:
            it = _item(s, d, None, None)
            it["why_not_funded"] = ("its capex does not fit in what is left of the budget" if cap > budget - spent
                                    else "not funded")
            skipped.append(it)
            rows.append({**it, "funded": False})
    fid = {x["id"] for x in funded}
    city_g = _group(ranked, fid, d, price["ngn_per_l"])
    scope_g = _group(scope, fid, d, price["ngn_per_l"])
    by_sector = {}
    for sec in SECTORS:
        g = [s for s in ranked if s.get("sector") == sec]
        if g:
            by_sector[sec] = {**_group(g, fid, d, price["ngn_per_l"]), "in_scope": sec in secs,
                              "name": SECTOR_NAME[sec]}
    met = data.any_metrics(c)
    labels = met.get("labels") or {}
    status = met.get("label_status") or {}
    keep = ("scenario_today", "scenario_with", "supply", "diesel", "diesel_price", "water", "water_works", "cold",
            "sums")
    excluded = [{"id": s["id"], "name": s.get("name"), "note": s.get("note")} for s in all_sites
                if s.get("rank") is None]
    totals = {
        "budget_ngn": _num(budget, 0), "spent_ngn": _num(spent, 0), "remaining_ngn": _num(budget - spent, 0),
        "funded_count": len(funded), "candidates": len(scope), "not_funded_count": len(skipped),
        "city_sites": len(ranked),
        "csh_needed": scope_g["csh_needed"], "csh_today": scope_g["csh_today"],
        "csh_with_funded": scope_g["csh_with_funded"], "csh_gained": scope_g["csh_gained"],
        "share_today": scope_g["share_today"], "share_with_funded": scope_g["share_with_funded"],
        "share_with_every_site": scope_g["share_with_every_site"],
        "diesel_l_avoided": scope_g["diesel_l_avoided"], "diesel_ngn_avoided": scope_g["diesel_ngn_avoided"],
        "diesel_ngn_per_l": price["ngn_per_l"], "capex_funded_ngn": _num(spent, 0),
        "capex_every_site_in_scope_ngn": scope_g["capex_every_site_ngn"],
        "metric": "critical_service_hours", "days": d,
    }
    return {
        "city": c, "city_name": CITIES[c]["name"], "state": CITIES[c]["state"], "days": d,
        "budget_ngn": _num(budget, 0), "sectors": list(secs), "rule": PLAN_RULE,
        "rank_rule": data.rank_rule(c), "data_version": data.version,
        "totals": totals, "scope": scope_g, "city_totals": city_g, "by_sector": by_sector,
        "water": _water([s for s in ranked if s.get("sector") == "water"], fid, d),
        "funded": funded, "not_funded_next": skipped[:10], "rows": rows, "excluded": excluded,
        "diesel_price": price,
        "labels": {"csh": CSH_LABEL, "naira": "litres x the diesel price constant (national average, May 2026)",
                   **{k: labels[k] for k in keep if isinstance(labels.get(k), str)}},
        "label_status": {"csh": "DERIVED", **{k: status[k] for k in keep if k in status}},
    }


CSV_COLUMNS = ["order", "rank", "id", "name", "sector", "archetype", "lga", "funded", "capex_ngn", "cumulative_ngn",
               "pv_kwp", "battery_kwh", "needed_h", "today_h", "with_h", "gained_h", "diesel_l_avoided",
               "roof_fit", "km_to_330kv", "facility_id"]


def plan_csv(p: dict) -> str:
    """Every in-scope site in plan order, funded or not, with the plan's inputs and data version on each row."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS + ["city", "days", "budget_ngn", "sectors", "data_version"])
    for r in p["rows"]:
        w.writerow([("yes" if r[k] else "no") if k == "funded" else ("" if r.get(k) is None else r.get(k))
                    for k in CSV_COLUMNS] + [p["city_name"], p["days"], p["budget_ngn"], " ".join(p["sectors"]),
                                             p["data_version"]])
    return buf.getvalue()
