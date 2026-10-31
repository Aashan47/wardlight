"""Brief 13 routes for the agents stream: the city budget plan (JSON and CSV) and the site verifier and line watcher.

    GET  /api/city/{city}/plan?budget_ngn=&days=&sectors=health,water,cold[&format=csv]
    GET  /api/city/{city}/plan.csv?...                       the same plan as CSV (every in-scope site, funded or not)
    POST /api/agent/verify-site/{site_id}                    body {replies[], recorded, recording}; SSE with stream=1
    GET|POST /api/agent/watch-line?city=&budget_ngn=         the line-cut watcher (recorded by default)

The plan is `agents.city13.plan` over the same files `api/brief13_api.py` serves; nothing is simulated per request.
"""

from __future__ import annotations

import re

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .errors import BadInput, NotFound


class VerifySiteIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    replies: list[str] = Field(default_factory=list, max_length=6)
    recorded: bool = False
    recording: str | None = Field(None, max_length=80)


SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def register(app, hub, limit, ok, sse_response) -> None:
    """Add the routes (before the /api catch-all). `sse_response(hub, run, start)` comes from main."""
    from agents import city13 as C13

    def plan_for(city: str, budget_ngn: float, days: int, sectors: str | None) -> dict:
        try:
            return C13.plan(hub.city13(), city, budget_ngn, days, sectors)
        except C13.CityDataError as e:
            msg = str(e)
            raise (NotFound(msg) if "not a city" in msg or "not in the brief 13 build" in msg else BadInput(msg)) from None

    def csv_response(p: dict) -> Response:
        name = f"wardlight-plan-{p['city']}-{int(p['budget_ngn'])}-{p['days']}d.csv"
        return Response(C13.plan_csv(p), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"',
                                 "X-Data-Version": p["data_version"]})

    @app.get("/api/city/{city}/plan")
    def city_plan(request: Request, city: str, budget_ngn: float = Query(2e9, ge=0, le=1e13),
                  days: int = Query(60, ge=1, le=60), sectors: str | None = Query(None, max_length=40),
                  format: str = Query("json", pattern="^(json|csv)$")):
        limit(request, "read")
        p = plan_for(city, budget_ngn, days, sectors)
        return csv_response(p) if format == "csv" else ok(p, max_age=60)

    @app.get("/api/city/{city}/plan.csv")
    def city_plan_csv(request: Request, city: str, budget_ngn: float = Query(2e9, ge=0, le=1e13),
                      days: int = Query(60, ge=1, le=60), sectors: str | None = Query(None, max_length=40)):
        limit(request, "read")
        return csv_response(plan_for(city, budget_ngn, days, sectors))

    def started(run, stream: bool):
        return sse_response(hub, run, 0) if stream else JSONResponse(run.info(), status_code=202)

    @app.post("/api/agent/verify-site/{site_id}")
    def verify_site(request: Request, site_id: str, body: VerifySiteIn | None = None, stream: bool = False,
                    speed: float = Query(1.0, ge=0, le=20)):
        limit(request, "agent")
        body = body or VerifySiteIn()
        if not SAFE_ID.match(site_id):
            raise HTTPException(404, "no such site")
        if any(len(r) > 160 for r in body.replies):
            raise HTTPException(422, "each reply is one SMS, at most 160 characters")
        try:
            hub.city13().find_site(site_id)
        except C13.CityDataError as e:
            raise HTTPException(404, str(e)) from None
        run = hub.start("verifier", {"site_id": site_id, "replies": body.replies}, body.recorded or not body.replies,
                        body.recording, speed)
        return started(run, stream)

    @app.api_route("/api/agent/watch-line", methods=["GET", "POST"])
    def watch_line(request: Request, city: str = Query("maiduguri", max_length=20),
                   budget_ngn: float = Query(2e9, ge=0, le=1e13), recorded: bool = True,
                   recording: str | None = Query(None, max_length=80), stream: bool = False,
                   speed: float = Query(1.0, ge=0, le=20)):
        limit(request, "agent")
        try:
            c = C13.City13Data.resolve_city(city)
        except C13.CityDataError as e:
            raise HTTPException(404, str(e)) from None
        run = hub.start("watcher", {"city": c, "budget_ngn": budget_ngn}, recorded, recording, speed)
        return started(run, stream)
