"""Wardlight API (06-PRODUCT-DESIGN.md, "API contract"; shapes in web/src/api/types.ts).

Run:  uvicorn --factory api.main:create_app --host 127.0.0.1 --port 8000   (from build/wardlight)
      WARDLIGHT_FIXTURE=1 serves data/fixtures/ only (no data/work access, no engine, no model).
"""

from __future__ import annotations

import contextvars
import csv
import gzip
import importlib
import io
import math
import os
import re
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from . import telephony as TEL
from .agent_runs import AgentHub
from .config import Settings
from .config import settings as load_settings
from .errors import BadInput, NotFound
from .limits import BodySizeLimit, RateLimiter, visitor

request_accept: contextvars.ContextVar[str] = contextvars.ContextVar("accept_encoding", default="")
RoomKey = Literal["fridge", "delivery", "oxygen", "lab", "ward"]
ROOMS = ("fridge", "delivery", "oxygen", "lab", "ward")
PV_STEP, BAT_STEP = 0.05, 0.1


class SimulateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    loads: list[RoomKey] = Field(default_factory=lambda: list(ROOMS), max_length=5)
    pv_kwp: float = Field(0.0, ge=0.0, le=50.0)
    battery_kwh: float = Field(0.0, ge=0.0, le=400.0)
    target: float = Field(0.99, ge=0.5, le=0.999)
    fridge_mode: Literal["shared", "pqs_sdd"] = "shared"


class PlanAgentIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str = Field("", max_length=600)
    recorded: bool = False
    recording: str | None = Field(None, max_length=80)


class VerifyAgentIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    replies: list[str] = Field(default_factory=list, max_length=6)
    recorded: bool = False
    recording: str | None = Field(None, max_length=80)


def _snap(x: float, step: float) -> float:
    return round(round(x / step) * step, 4)


def create_app(s: Settings | None = None) -> FastAPI:
    s = s or load_settings()
    if s.fixture:
        from .store_fixture import FixtureStore

        store = FixtureStore(s)
    else:
        from .store_live import LiveStore

        store = LiveStore(s)
    hub = AgentHub(s, s.fixture, store=store)
    limiter = RateLimiter({"read": s.rate_read, "simulate": s.rate_simulate, "agent": s.rate_agent,
                           "telephony": s.rate_telephony})

    app = FastAPI(title="Wardlight API", version="1.0", docs_url="/api/docs", openapi_url="/api/openapi.json",
                  redoc_url=None)
    app.state.store, app.state.hub, app.state.limiter, app.state.settings = store, hub, limiter, s
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(BodySizeLimit, max_bytes=s.max_body_bytes)
    origins = [o for o in os.environ.get("WARDLIGHT_CORS_ORIGINS", "").split(",") if o]
    if origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])

    def limit(request: Request, bucket: str, who: str | None = None) -> None:
        limiter.check(who or visitor(request, s.trust_cf_header), bucket)

    def ok(data, cache: str | None = None, max_age: int = 300) -> Response:
        headers = {"X-Data-Version": store.data_version}
        if cache:
            headers["X-Cache"] = cache
        if max_age:
            headers["Cache-Control"] = f"public, max-age={max_age}"
        if hasattr(data, "path") and str(data.path).endswith(".gz"):
            if "gzip" in request_accept.get().lower():
                return FileResponse(data.path, media_type="application/json",
                                    headers={**headers, "Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
            with gzip.open(data.path, "rb") as f:
                return Response(content=f.read(), media_type="application/json", headers=headers)
        if isinstance(data, (bytes, bytearray)):
            return Response(content=bytes(data), media_type="application/json", headers=headers)
        return JSONResponse(_clean(data), headers=headers)

    @app.exception_handler(NotFound)
    async def _nf(request: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(BadInput)
    async def _bi(request: Request, exc: BadInput):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    # ------------------------------------------------------------ read routes

    @app.get("/api/health")
    def health(request: Request):
        limit(request, "read")
        h = store.health()
        h["sms_ussd"] = {"sandbox": True, "sends": False}
        h["agents"] = {"cap": hub.cap(), "live_enabled": bool(s.agent_live and not s.fixture),
                       "runs": "replay" if (s.fixture or s.agent_runs == "replay") else "all",
                       "recordings": len(hub.recordings())}
        return ok(h, max_age=0)

    @app.get("/api/summary")
    def summary(request: Request):
        limit(request, "read")
        return ok(store.summary())

    @app.get("/api/facilities")
    def facilities(request: Request, state: str | None = Query(None, max_length=60),
                   lga: str | None = Query(None, max_length=80), q: str | None = Query(None, max_length=80),
                   tier: str | None = Query(None, max_length=20), limit_: int | None = Query(None, alias="limit",
                                                                                            ge=1, le=100_000)):
        limit(request, "read")
        request_accept.set(request.headers.get("accept-encoding", ""))
        return ok(store.facilities(state, lga, q, tier, limit_))

    @app.get("/api/facilities/{fid}")
    def facility(request: Request, fid: str):
        limit(request, "read")
        return ok(store.facility(fid))

    @app.post("/api/facilities/{fid}/simulate")
    def simulate(request: Request, fid: str, body: SimulateIn):
        limit(request, "simulate")
        req = body.model_dump()
        pv, bat = _snap(req["pv_kwp"], PV_STEP), _snap(req["battery_kwh"], BAT_STEP)
        req["_snapped"] = not (math.isclose(pv, req["pv_kwp"], abs_tol=1e-9)
                               and math.isclose(bat, req["battery_kwh"], abs_tol=1e-9))
        req["pv_kwp"], req["battery_kwh"] = pv, bat
        t0 = time.perf_counter()
        out = store.simulate(fid, req)
        out["api_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return ok(out, cache="hit" if out.get("cached") else "miss", max_age=0)

    @app.get("/api/plan")
    def plan(request: Request, state: str | None = Query(None, max_length=60),
             metric: Literal["doses", "load_hours", "outage_hours", "orfix_hours"] = "doses",
             days: int | None = Query(None, ge=1, le=60),
             budget_ngn: float | None = Query(None, ge=0, le=1e13), target: float | None = Query(None, ge=0, le=1)):
        limit(request, "read")
        return ok(store.plan(state, budget_ngn, target, metric, days))

    def _brief(request: Request, state, budget_ngn, metric, fmt, days=None):
        limit(request, "read")
        b = store.brief(state, budget_ngn, metric, days)
        if fmt == "csv":
            name = re.sub(r"[^A-Za-z0-9]+", "-", b["state"]).strip("-").lower()
            return Response(brief_csv(b), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="wardlight-brief-{name}-{metric}.csv"',
                                     "X-Data-Version": store.data_version})
        return ok(b)

    @app.get("/api/plan/brief")
    def plan_brief(request: Request, state: str | None = Query(None, max_length=60),
                   budget_ngn: float | None = Query(None, ge=0, le=1e13),
                   metric: Literal["doses", "load_hours", "outage_hours", "orfix_hours"] = "doses",
                   days: int | None = Query(None, ge=1, le=60),
                   format: Literal["json", "csv"] = "json"):
        return _brief(request, state, budget_ngn, metric, format, days)

    @app.get("/api/plan/brief.csv")
    def plan_brief_csv(request: Request, state: str | None = Query(None, max_length=60),
                       budget_ngn: float | None = Query(None, ge=0, le=1e13),
                       metric: Literal["doses", "load_hours", "outage_hours", "orfix_hours"] = "doses",
                   days: int | None = Query(None, ge=1, le=60)):
        return _brief(request, state, budget_ngn, metric, "csv", days)

    @app.get("/api/city")
    def city(request: Request, state: str | None = Query(None, max_length=60),
             lgas: str | None = Query(None, max_length=600), days: int | None = Query(None, ge=1, le=60),
             limit_: int = Query(500, alias="limit", ge=1, le=5000)):
        limit(request, "read")
        return ok(store.city(state, lgas, days, limit_))

    @app.get("/api/facilities/{fid}/outage_trace")
    def outage_trace(request: Request, fid: str, days: int | None = Query(None, ge=1, le=60)):
        limit(request, "simulate")
        t0 = time.perf_counter()
        out = store.outage_trace(fid, days)
        return ok({**out, "api_ms": round((time.perf_counter() - t0) * 1000, 1)}, max_age=0)

    @app.get("/api/feeders/{fid}")
    def feeder(request: Request, fid: str):
        limit(request, "read")
        return ok(store.feeder(fid))

    @app.get("/api/results")
    def results(request: Request):
        limit(request, "read")
        return ok(store.results(), max_age=60)

    @app.get("/api/evidence/crops/{name}")
    def crop(request: Request, name: str):
        limit(request, "read")
        p = store.crop_path(name)
        if p is None:
            raise HTTPException(404, "no such crop")
        return FileResponse(p, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    # ------------------------------------------------------------ agents

    def _started(request: Request, run, stream: bool, speed: float):
        if stream:
            return _sse_response(hub, run, 0)
        return JSONResponse(run.info(), status_code=202)

    @app.post("/api/agent/plan")
    def agent_plan(request: Request, body: PlanAgentIn, stream: bool = False,
                   speed: float = Query(1.0, ge=0, le=20)):
        limit(request, "agent")
        q = " ".join(body.question.split())
        if not q and not (body.recorded or body.recording):
            raise HTTPException(422, "question is required (or ask for a recording)")
        run = hub.start("planner", {"question": q}, body.recorded, body.recording, speed)
        return _started(request, run, stream, speed)

    @app.post("/api/agent/verify/{fid}")
    def agent_verify(request: Request, fid: str, body: VerifyAgentIn | None = None,
                     stream: bool = False, speed: float = Query(1.0, ge=0, le=20)):
        limit(request, "agent")
        body = body or VerifyAgentIn()
        if any(len(r) > 160 for r in body.replies):
            raise HTTPException(422, "each reply is one SMS, at most 160 characters")
        uid = fid
        if not s.fixture:
            uid = store.t.unique_id.iloc[store.resolve(fid)]
        run = hub.start("verifier", {"facility_id": uid, "replies": body.replies}, body.recorded, body.recording,
                        speed)
        return _started(request, run, stream, speed)

    @app.api_route("/api/agent/watch", methods=["GET", "POST"])
    def agent_watch(request: Request, old: str = Query("2026-09", pattern=r"^\d{4}-\d{2}$"),
                    new: str = Query("2026-10", pattern=r"^\d{4}-\d{2}$"), recorded: bool = True,
                    recording: str | None = Query(None, max_length=80), stream: bool = False,
                    speed: float = Query(1.0, ge=0, le=20), max_keys: int = Query(40, ge=1, le=2000)):
        limit(request, "agent")
        run = hub.start("watcher", {"old": old, "new": new, "max_keys": max_keys}, recorded, recording, speed)
        return _started(request, run, stream, speed)

    @app.get("/api/agent/runs/{run_id}/events")
    def agent_events(request: Request, run_id: str, from_: int = Query(0, alias="from", ge=0)):
        limit(request, "read")
        run = hub.get(run_id)
        if run is None:
            raise HTTPException(404, "no such run")
        last = request.headers.get("last-event-id")
        start = int(last) + 1 if last and last.isdigit() else from_
        return _sse_response(hub, run, start)

    @app.get("/api/agent/runs/{run_id}")
    def agent_run(request: Request, run_id: str):
        limit(request, "read")
        run = hub.get(run_id)
        if run is None:
            raise HTTPException(404, "no such run")
        return ok({**run.info(), "events": list(run.events)}, max_age=0)

    @app.get("/api/agent/recordings")
    def agent_recordings(request: Request):
        limit(request, "read")
        return ok({"recorded": True, "recordings": [{k: v for k, v in r.items() if k != "path"}
                                                    for r in hub.recordings()]}, max_age=0)

    @app.get("/api/agent/cap")
    def agent_cap(request: Request):
        limit(request, "read")
        return ok({**hub.cap(), "recorded": False}, max_age=0)

    # ------------------------------------------------------------ SMS and USSD (Africa's Talking, sandbox)

    def _verifier_ussd(uid: str, text: str) -> str:
        if s.fixture:
            raise RuntimeError("fixture mode")
        v = importlib.import_module("agents.verifier")
        fac = v.facility_from_data(hub.toolbox().data, uid)
        return v.ussd(fac, text)

    @app.post("/api/ussd")
    async def ussd(request: Request):
        form = TEL.parse_form(await request.body())
        limit(request, "telephony", "tel:" + (form.get("phoneNumber") or visitor(request, s.trust_cf_header)))
        if not form.get("sessionId"):
            raise HTTPException(422, "sessionId is required (Africa's Talking USSD callback)")
        reply = TEL.ussd_reply(store, form.get("text", ""),
                               None if (s.fixture or s.agent_runs == "replay") else _verifier_ussd)
        return PlainTextResponse(reply, headers={"X-Sandbox": "true"})

    @app.post("/api/sms/inbound")
    async def sms_inbound(request: Request):
        form = TEL.parse_form(await request.body())
        limit(request, "telephony", "tel:" + (form.get("from") or visitor(request, s.trust_cf_header)))
        if "text" not in form:
            raise HTTPException(422, "text is required (Africa's Talking incoming SMS callback)")
        reply = TEL.sms_reply(store, form.get("text", ""))
        return ok({"sandbox": True, "sent": False, "to": form.get("from"), "reply": reply, "chars": len(reply),
                   "note": "sandbox: the reply is returned here and not sent; no SMS API is called"}, max_age=0)

    # ------------------------------------------------------------ brief 13: city metrics, sites, corridor, siting

    from .brief13_api import Brief13Files
    from .brief13_api import register as register_brief13

    app.state.brief13 = Brief13Files((s.fixtures if s.fixture else s.work) / "brief13")
    register_brief13(app, app.state.brief13, limit, ok)
    from .agent13 import register as register_agent13  # brief 13 plan, site verifier, line watcher

    register_agent13(app, hub, limit, ok, _sse_response)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST"])
    def api_404(rest: str):
        raise HTTPException(404, "no such API route")

    # ------------------------------------------------------------ the web app (SPA)

    dist = s.web_dist

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if not dist.is_dir():
            return PlainTextResponse("web/dist is not built; the API is under /api", status_code=404)
        target = (dist / path).resolve()
        if path and dist.resolve() in target.parents and target.is_file():
            cache = "no-cache" if target.name in ("index.html", "sw.js", "manifest.webmanifest") else \
                "public, max-age=31536000, immutable" if "/assets/" in f"/{path}" else "public, max-age=3600"
            return FileResponse(target, headers={"Cache-Control": cache})
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def _sse_response(hub: AgentHub, run, start: int) -> StreamingResponse:
    return StreamingResponse(hub.stream(run, start), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "X-Run-Id": run.id, "X-Recorded": str(run.recorded).lower()})


def _clean(x):
    """JSON-safe: NaN and inf become null; numpy scalars become Python numbers."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        try:
            return _clean(x.item())
        except (ValueError, AttributeError):
            return str(x)
    return x


BRIEF_COLUMNS = ["rank", "id", "code", "name", "lga", "type", "tier", "fix", "fix_label", "fix_model", "cost_ngn",
                 "cumulative_ngn", "benefit", "benefit_unit", "doses_year", "doses_gain", "uptime_today",
                 "uptime_with_fix", "capped", "catchment_pop", "pop_above_cap", "doses_demand_uncapped", "citation",
                 "citation_url", "results_stale"]


def brief_csv(b: dict) -> str:
    """The funded list of an investment brief as CSV (one row per funded facility; totals stay in the JSON)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([*BRIEF_COLUMNS, "state", "metric", "sample", "data_version"])
    for r in b["funded"]:
        cit = r.get("citation") or {}
        vals = {**r, "citation": cit.get("text"), "citation_url": cit.get("url")}
        w.writerow([("" if vals.get(c) is None else vals.get(c)) for c in BRIEF_COLUMNS]
                   + [b["state"], b["metric"], "yes" if b.get("sample") else "no", b.get("data_version", "")])
    return buf.getvalue()
