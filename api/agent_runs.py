"""Agent runs as Server-Sent Events (11-AGENTS-DESIGN.md, "The agent experience on screen").

A POST starts a run and returns its id; GET /api/agent/runs/{id}/events streams the events as text/event-stream
(`id: <seq>`, `event: <type>`, `data: <the event as JSON>`). The events are agent F's generator events passed
through unchanged (agents/events.py schema), or a recorded session replayed with its original t_ms gaps and
`done.recorded` set true.

How a run is chosen (mode):
- recorded: fixture mode, or the caller asked for a recording, or the daily cap is spent and a recording fits;
- live:     WARDLIGHT_AGENT_LIVE=1 and the model is configured by WARDLIGHT_LLM_* variables (planner only);
- scripted: otherwise the planner runs over the real tools with agent F's rule-based scripted model (no language
            model is called; the done event names it), the verifier with rules only (no model), and the watcher
            as code (it has no model);
- unavailable: nothing can run (an `error` then a `done` event, recorded false, model "none").
Every non-recorded run counts against the daily cap. Recorded replays are free and do not count.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import importlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

from .config import Settings

AGENTS = ("planner", "verifier", "watcher")
KIND_FOR = {"planner": ("planner_session", "planner"), "verifier": ("verifier_session", "verifier"),
            "watcher": ("watcher_run", "watcher")}
MAX_RUNS = 256
RUN_TTL_S = 3600


class Run:
    def __init__(self, agent: str, mode: str, meta: dict):
        self.id = uuid.uuid4().hex[:16]
        self.agent = agent
        self.mode = mode
        self.meta = meta
        self.events: list[dict] = []
        self.done = False
        self.created = time.time()
        self._cond = threading.Condition()

    def add(self, ev: dict) -> None:
        with self._cond:
            self.events.append(ev)
            self._cond.notify_all()

    def finish(self) -> None:
        with self._cond:
            self.done = True
            self._cond.notify_all()

    def wait(self, idx: int, timeout: float) -> tuple[list[dict], bool]:
        with self._cond:
            if len(self.events) <= idx and not self.done:
                self._cond.wait(timeout)
            return list(self.events[idx:]), self.done

    @property
    def recorded(self) -> bool:
        return self.mode == "recorded"

    def info(self) -> dict:
        return {"run_id": self.id, "agent": self.agent, "mode": self.mode, "recorded": self.recorded,
                "events_url": f"/api/agent/runs/{self.id}/events", "done": self.done, "n_events": len(self.events),
                **self.meta}


def sse(ev: dict) -> bytes:
    return (f"id: {ev.get('seq', '')}\nevent: {ev.get('type', 'message')}\n"
            f"data: {json.dumps(ev, ensure_ascii=False, default=str, separators=(',', ':'))}\n\n").encode()


def _try_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001 - a module that is absent or broken means that path is unavailable
        return None


class AgentHub:
    def __init__(self, s: Settings, fixture: bool):
        self.s = s
        self.fixture = fixture
        self.runs: dict[str, Run] = {}
        self._lock = threading.Lock()
        self._day = ""
        self._used = 0
        self._toolbox = None
        self._recordings: list[dict] | None = None

    # ------------------------------------------------------------ cap

    def cap(self) -> dict:
        today = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
        with self._lock:
            if today != self._day:
                self._day, self._used = today, 0
            return {"used": self._used, "limit": self.s.agent_daily_cap,
                    "remaining": max(0, self.s.agent_daily_cap - self._used), "resets": "00:00 UTC"}

    def _take(self) -> bool:
        self.cap()
        with self._lock:
            if self._used >= self.s.agent_daily_cap:
                return False
            self._used += 1
            return True

    # ------------------------------------------------------------ recordings

    def recordings(self) -> list[dict]:
        if self._recordings is None:
            out = []
            root = self.s.fixtures / "agents"
            for p in sorted(root.glob("*.json")) if root.is_dir() else []:
                try:
                    rec = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(rec, dict) or not isinstance(rec.get("events"), list):
                    continue
                agent = next((a for a, keys in KIND_FOR.items()
                              if rec.get("kind") in keys or p.stem.startswith(a)), None)
                if agent is None:
                    continue
                q = (rec.get("output") or {}).get("question") or rec.get("question")
                fac = rec.get("facility") or {}
                out.append({"name": p.stem, "agent": agent, "label": rec.get("label"), "what": rec.get("what"),
                            "question": q, "facility_id": fac.get("unique_id") if isinstance(fac, dict) else None,
                            "n_events": len(rec["events"]), "path": p})
            self._recordings = out
        return self._recordings

    def find_recording(self, agent: str, name: str | None = None, question: str | None = None,
                       facility_id: str | None = None) -> dict | None:
        recs = [r for r in self.recordings() if r["agent"] == agent]
        if name:
            return next((r for r in recs if r["name"] == name), None)
        if question:
            q = " ".join(question.split()).casefold()
            return next((r for r in recs if r["question"] and " ".join(r["question"].split()).casefold() == q), None)
        if facility_id:
            return next((r for r in recs if r["facility_id"] == facility_id), None)
        return recs[0] if recs else None

    # ------------------------------------------------------------ producers

    def _replay(self, rec: dict, speed: float) -> Iterator[dict]:
        data = json.loads(Path(rec["path"]).read_text(encoding="utf-8"))
        last = 0
        for e in data["events"]:
            e = dict(e)
            t = int(e.get("t_ms", last) or 0)
            if speed > 0 and t > last:
                time.sleep(min((t - last) / 1000.0 / speed, 10.0))
            last = max(last, t)
            if e.get("type") == "done":
                e["recorded"] = True
            yield e

    def toolbox(self):
        if self._toolbox is None:
            tools = importlib.import_module("agents.tools")
            self._toolbox = tools.Toolbox()
        return self._toolbox

    def _planner_client(self):
        if self.s.agent_live:
            llm = _try_import("agents.llm")
            if llm is not None:
                try:
                    return llm.OpenAICompatClient.from_env(), "live"
                except Exception:  # noqa: BLE001, S110 - not configured: fall through to scripted
                    pass
        fake = _try_import("agents.fake")
        if fake is not None:
            return fake.RuleBasedPlannerModel(), "scripted"
        return None, "unavailable"

    def _producer(self, agent: str, inputs: dict) -> tuple[Callable[[], Iterator[dict]] | None, str, str | None]:
        """(event generator factory, mode, reason when unavailable) for a non-recorded run."""
        if self.fixture:
            return None, "unavailable", "fixture mode runs recorded sessions only"
        if agent == "planner":
            mod = _try_import("agents.planner")
            client, mode = self._planner_client()
            if mod is None or client is None:
                return None, "unavailable", "agents.planner is not available"
            return (lambda: mod.run_events(inputs["question"], client, self.toolbox())), mode, None
        if agent == "verifier":
            mod = _try_import("agents.verifier")
            if mod is None:
                return None, "unavailable", "agents.verifier is not available"

            def gen():
                fac = mod.facility_from_data(self.toolbox().data, inputs["facility_id"])
                yield from mod.run_events(fac, list(inputs.get("replies") or []))
            return gen, "scripted", None
        if agent == "watcher":
            mod = _try_import("agents.watcher")
            if mod is None:
                return None, "unavailable", "agents.watcher is not available"
            return (lambda: mod.run_events(inputs["old"], inputs["new"], data=self.toolbox().data,
                                           n_draws=int(inputs.get("n_draws", 16)),
                                           max_keys=inputs.get("max_keys"))), "scripted", None
        return None, "unavailable", f"unknown agent {agent}"

    # ------------------------------------------------------------ start

    def start(self, agent: str, inputs: dict, want_recorded: bool = False, recording: str | None = None,
              speed: float = 1.0) -> Run:
        self._gc()
        cap = self.cap()
        rec = None
        if want_recorded or recording or self.fixture:
            rec = self.find_recording(agent, recording, inputs.get("question"), inputs.get("facility_id"))
            if rec is None and not inputs.get("question") and not inputs.get("facility_id") and not recording:
                rec = self.find_recording(agent)
        gen_factory, mode, why = (None, "recorded", None) if rec else self._producer(agent, inputs)
        cap_reached = False
        if rec is None and gen_factory is not None and not self._take():
            cap_reached = True
            rec = self.find_recording(agent, None, inputs.get("question"), inputs.get("facility_id"))
            gen_factory, mode = None, "recorded" if rec else "unavailable"
            why = None if rec else "the daily cap of agent runs is spent and no recording fits this request"
        meta = {"cap": self.cap() if not cap_reached else {**cap, "remaining": 0}, "cap_reached": cap_reached,
                "recording": rec["name"] if rec else None, "recording_label": rec["label"] if rec else None,
                "recorded_question": rec["question"] if rec else None, "reason": why,
                "label": ("recorded session" if rec else "live model" if mode == "live" else
                          "no language model (scripted rules or code)" if mode == "scripted" else "unavailable")}
        run = Run(agent, "recorded" if rec else mode, meta)
        with self._lock:
            self.runs[run.id] = run

        def work():
            t0 = time.perf_counter()
            saw_done = False
            try:
                it = self._replay(rec, speed) if rec else (gen_factory() if gen_factory else iter(()))
                for ev in it:
                    saw_done = saw_done or ev.get("type") == "done"
                    run.add(ev)
                if not rec and gen_factory is None:
                    run.add({"type": "error", "seq": 0, "t_ms": 0, "message": why or "unavailable"})
            except Exception as e:  # noqa: BLE001 - surfaced to the client as an error event
                run.add({"type": "error", "seq": len(run.events), "t_ms": int((time.perf_counter() - t0) * 1000),
                         "message": f"{type(e).__name__}: {e}"[:400]})
            if not saw_done:
                run.add({"type": "done", "seq": len(run.events), "t_ms": int((time.perf_counter() - t0) * 1000),
                         "model": "none", "tokens": 0, "cost_usd": 0.0, "recorded": bool(rec),
                         "duration_ms": int((time.perf_counter() - t0) * 1000)})
            run.finish()

        threading.Thread(target=work, name=f"agent-{run.id}", daemon=True).start()
        return run

    def _gc(self) -> None:
        now = time.time()
        with self._lock:
            for k in [k for k, r in self.runs.items() if r.done and now - r.created > RUN_TTL_S]:
                del self.runs[k]
            while len(self.runs) > MAX_RUNS:
                del self.runs[next(iter(self.runs))]

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    async def stream(self, run: Run, start: int = 0, keepalive_s: float = 15.0):
        i = start
        while True:
            evs, done = await asyncio.to_thread(run.wait, i, keepalive_s)
            for ev in evs:
                yield sse(ev)
            i += len(evs)
            if done and i >= len(run.events):
                return
            if not evs:
                yield b": keep-alive\n\n"
