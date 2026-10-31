"""Brief 13 city routes: metrics M1 to M5, critical sites, the 330 kV corridor and the siting card.

Serves the files `python -m engine.metrics13` writes (data/work/brief13/, or data/fixtures/brief13/ in fixture mode).
Nothing is simulated per request. Metrics, sites and corridor are served as the bytes on disk (no parse, small
memory); siting files are parsed once per city on first use.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import Query, Request

from .errors import BadInput, NotFound

CITIES = ("maiduguri", "damaturu", "yola")
DEFAULT_CITY = "maiduguri"
DEFAULT_DAYS = 60
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
BUILD_HINT = "the brief 13 build is not in this data directory; run python -m engine.metrics13"


class Brief13Files:
    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def available(self) -> bool:
        return (self.root / "meta.json").is_file() or any(self.root.glob("metrics-*.json"))

    def _path(self, name: str) -> Path:
        p = (self.root / name).resolve()
        if self.root.resolve() not in p.parents or not p.is_file():
            raise NotFound(BUILD_HINT if not self.available else f"not in the brief 13 build: {name}")
        return p

    @lru_cache(maxsize=64)  # noqa: B019 - one instance per app
    def _bytes(self, name: str) -> bytes:
        return self._path(name).read_bytes()

    @lru_cache(maxsize=3)  # noqa: B019
    def _siting(self, city: str) -> dict:
        try:
            return json.loads(self._bytes(f"siting-{city}.json"))
        except NotFound:
            return {}

    def city(self, city: str | None) -> str:
        c = (city or DEFAULT_CITY).strip().lower()
        if c not in CITIES:
            raise NotFound(f"no city '{city}'; one of {', '.join(CITIES)}")
        return c

    def days_available(self, city: str) -> list[int]:
        out = []
        for p in self.root.glob(f"metrics-{city}-*.json"):
            m = re.fullmatch(rf"metrics-{city}-(\d+)\.json", p.name)
            if m:
                out.append(int(m.group(1)))
        return sorted(out)

    def metrics(self, city: str | None, days: int | None) -> bytes:
        c = self.city(city)
        d = DEFAULT_DAYS if days is None else int(days)
        avail = self.days_available(c)
        if not avail:
            raise NotFound(BUILD_HINT)
        if d not in avail:
            raise BadInput(f"outage days must be one of {avail}")
        return self._bytes(f"metrics-{c}-{d}.json")

    def sites(self, city: str | None) -> bytes:
        return self._bytes(f"sites-{self.city(city)}.geojson")

    def corridor(self) -> bytes:
        return self._bytes("corridor.geojson")

    def trace_file(self, site_id: str, days: int) -> bytes | None:
        """A precomputed trace (fixtures carry a few), else None."""
        if not SAFE_ID.match(site_id or ""):
            return None
        p = self.root / f"trace-{site_id}-{int(days)}.json"
        return p.read_bytes() if p.is_file() else None

    def siting(self, site_id: str) -> dict:
        if not SAFE_ID.match(site_id or ""):
            raise NotFound(f"no site '{site_id}'")
        for c in CITIES:
            card = self._siting(c).get(site_id)
            if card is not None:
                return {**card, "city": c}
        raise NotFound(f"no site '{site_id}'" if self.available else BUILD_HINT)


TRACE_DAYS = (7, 14, 40, 60)


@lru_cache(maxsize=64)
def _live_trace(work: str, site_json: str, days: int, n_draws: int) -> str:
    """Engine run for one water or cold site (about a second); cached per site and window."""
    from engine import sector as X
    from engine import sim as SM
    from engine import supply as SP

    sim = json.loads(site_json)
    shortfall, _ = SP.calibrated_from_work(Path(work))
    cfg = SM.SimConfig(n_draws=n_draws, shortfall=shortfall)
    out = X.trace(sim["lat"], sim["lon"], sim["bands"], sim["hours"], sim["start"], sim["mode"], sim["kw"],
                  sim["pv_kwp"], sim["battery_kwh"], days, cfg)
    return json.dumps(out)


@lru_cache(maxsize=64)
def _live_health_trace(work: str, sim_json: str, days: int) -> str:
    """The plan's outage-ready system for one health site (api.outage_api.trace with the orfix PV, battery and
    fridge, and the batch's own number of draws, so the median hours kept are the batch's)."""
    from engine import supply as SP

    from . import outage_api as OA

    sim = json.loads(sim_json)
    shortfall, _ = SP.calibrated_from_work(Path(work))
    out = OA.trace(sim["lat"], sim["lon"], sim["bands"], days, sim["pv_kwp"], sim["battery_kwh"], sim["fix_kind"],
                   sim["fridge_code"], shortfall, n_draws=int(sim["n_draws"]))
    out["scenario"] = ("with the plan: the outage-ready fix sized for 7 days, PQS fridge " + sim["fridge_code"]
                       + f" and a clinic system of {sim['pv_kwp']:.3f} kWp with {sim['battery_kwh']:.2f} kWh; "
                       "rooms_today: no solar, household fridge, grid only")
    out["system"] = {"pv_kwp": sim["pv_kwp"], "battery_kwh": sim["battery_kwh"], "fridge_code": sim["fridge_code"],
                     "label": "the plan's outage-ready system (as in /api/city/{city}/sites)"}
    out["hours_kept_median"] = out["draw"]["median_service_hours_with"]
    return json.dumps(out)


def register(app, files: Brief13Files, limit, ok) -> None:
    """Add the routes (before the /api catch-all). `limit(request, bucket)` and `ok(data)` come from main."""

    @app.get("/api/city/{city}/metrics")
    def city_metrics(request: Request, city: str, days: int | None = Query(None, ge=1, le=366)):
        limit(request, "read")
        return ok(files.metrics(city, days))

    @app.get("/api/city/{city}/sites")
    def city_sites(request: Request, city: str):
        limit(request, "read")
        return ok(files.sites(city))

    @app.get("/api/corridor")
    def corridor(request: Request):
        limit(request, "read")
        return ok(files.corridor(), max_age=3600)

    @app.get("/api/sites/{site_id}/siting")
    def siting(request: Request, site_id: str):
        limit(request, "read")
        return ok(files.siting(site_id))

    @app.get("/api/sites/{site_id}/outage_trace")
    def site_trace(request: Request, site_id: str, days: int = Query(60, ge=1, le=60)):
        """Hourly trace for the 3D night with the plan's system: for health sites the outage-ready fix (as in the
        sites GeoJSON), for water and cold sites the sector design; live engine run, or a precomputed file
        (fixtures)."""
        limit(request, "simulate")
        if days not in TRACE_DAYS:
            raise BadInput(f"outage days must be one of {list(TRACE_DAYS)}")
        card = files.siting(site_id)
        pre = files.trace_file(site_id, days)
        if pre is not None:
            return ok(pre, max_age=0)
        s = app.state.settings
        if s.fixture:
            raise NotFound(f"no precomputed trace for {site_id} at {days} days in the fixtures")
        sim = card.get("sim")
        if not sim:
            raise BadInput("this site has no designed system in the plan (existing on-site power), so no trace")
        key = json.dumps(sim, sort_keys=True)
        if sim.get("kind") == "health_orfix":
            body = json.loads(_live_health_trace(str(s.work), key, days))
            return ok({**body, "site_id": site_id, "facility_id": card["facility_id"], "sector": "health",
                       "name": card["name"]}, max_age=0)
        body = json.loads(_live_trace(str(s.work), key, days, int(sim.get("n_draws") or s.whatif_draws)))
        return ok({**body, "site_id": site_id, "sector": card["sector"], "archetype": card["archetype"],
                   "name": card["name"]}, max_age=0)
