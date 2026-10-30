"""The agent event stream the UI animates (11-AGENTS-DESIGN.md, "The agent experience on screen").

Every agent (planner, verifier, watcher) is a Python generator of these events. The API sends them as
Server-Sent Events, one JSON object each, unchanged for live and recorded runs.

Each event: {"type", "seq", "t_ms", ...payload}. `seq` counts from 0; `t_ms` is milliseconds since the run
started (relative, so a recording replays with its original timings and carries no calendar date).

Payloads (required keys; extra keys are allowed and documented where emitted):
  plan        {steps: [{id, title}]}
  step_start  {id}
  reasoning   {text, source: "model"}   only text the model itself returned; never synthesised
  tool_call   {id, name, args}
  tool_result {id, summary, rows, ms}
  check       {kind: "grounding", numbers_checked, unmatched: [], matches: [{text, value, matched}], ok}
  citation    {facility_id, file, page, sn, row_text}
  answer      {markdown, funded, not_reached, totals}
  error       {message}
  done        {model, tokens, cost_usd, recorded, duration_ms}
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

SCHEMA: dict[str, tuple[str, ...]] = {
    "plan": ("steps",),
    "step_start": ("id",),
    "reasoning": ("text", "source"),
    "tool_call": ("id", "name", "args"),
    "tool_result": ("id", "summary", "rows", "ms"),
    "check": ("kind", "numbers_checked", "unmatched", "matches", "ok"),
    "citation": ("facility_id", "file", "page", "sn", "row_text"),
    "answer": ("markdown", "funded", "not_reached", "totals"),
    "error": ("message",),
    "done": ("model", "tokens", "cost_usd", "recorded", "duration_ms"),
}
TYPES = tuple(SCHEMA)
ENV_PRICE_IN = "WARDLIGHT_LLM_USD_PER_M_INPUT"
ENV_PRICE_OUT = "WARDLIGHT_LLM_USD_PER_M_OUTPUT"


class EventLog:
    """Stamps events with seq and t_ms and keeps them (the recording)."""

    def __init__(self, clock=time.perf_counter):
        self._clock = clock
        self.t0 = clock()
        self.events: list[dict] = []

    def ms(self) -> int:
        return int(round((self._clock() - self.t0) * 1000))

    def emit(self, type_: str, **payload) -> dict:
        if type_ not in SCHEMA:
            raise ValueError(f"unknown event type {type_}")
        missing = [k for k in SCHEMA[type_] if k not in payload]
        if missing:
            raise ValueError(f"{type_} event missing {missing}")
        ev = {"type": type_, "seq": len(self.events), "t_ms": self.ms(), **payload}
        self.events.append(ev)
        return ev


def validate(events: Iterable[dict]) -> list[str]:
    """Schema and order problems in an event list (empty when valid)."""
    errs: list[str] = []
    evs = list(events)
    if not evs:
        return ["no events"]
    if evs[0]["type"] != "plan":
        errs.append("first event must be plan")
    if evs[-1]["type"] != "done":
        errs.append("last event must be done")
    last_t, open_calls, plan_ids = -1, set(), set()
    for i, e in enumerate(evs):
        t = e.get("type")
        if t not in SCHEMA:
            errs.append(f"{i}: unknown type {t}")
            continue
        for k in ("seq", "t_ms", *SCHEMA[t]):
            if k not in e:
                errs.append(f"{i}: {t} missing {k}")
        if e.get("seq") != i:
            errs.append(f"{i}: seq {e.get('seq')} out of order")
        if e.get("t_ms", 0) < last_t:
            errs.append(f"{i}: time goes backwards")
        last_t = e.get("t_ms", last_t)
        if t == "plan":
            plan_ids |= {s["id"] for s in e.get("steps", [])}
        elif t == "step_start" and e.get("id") not in plan_ids:
            errs.append(f"{i}: step {e.get('id')} not in plan")
        elif t == "tool_call":
            open_calls.add(e.get("id"))
        elif t == "tool_result":
            if e.get("id") not in open_calls:
                errs.append(f"{i}: tool_result {e.get('id')} without a tool_call")
            open_calls.discard(e.get("id"))
        elif t == "reasoning" and e.get("source") != "model":
            errs.append(f"{i}: reasoning must come from the model")
        elif t == "done" and i != len(evs) - 1:
            errs.append(f"{i}: done before the end")
    if open_calls:
        errs.append(f"tool_call without result: {sorted(open_calls)}")
    return errs


def cost_usd(prompt_tokens: int, completion_tokens: int, kind: str, env: dict | None = None) -> float | None:
    """Cost of a run from the provider's per-million-token prices given in the environment (None when not set:
    the price is never guessed). Scripted and replayed runs call no model and cost 0."""
    if kind in ("scripted", "replay", "none"):
        return 0.0
    e = os.environ if env is None else env
    try:
        pin, pout = float(e[ENV_PRICE_IN]), float(e[ENV_PRICE_OUT])
    except (KeyError, ValueError):
        return None
    return round(prompt_tokens / 1e6 * pin + completion_tokens / 1e6 * pout, 6)


# ---------------------------------------------------------------- recordings


def mark_recorded(events: list[dict]) -> list[dict]:
    """Copy of a run's events for a fixture: original seq and t_ms kept; `done.recorded` set true."""
    out = [dict(e) for e in events]
    for e in out:
        if e["type"] == "done":
            e["recorded"] = True
    return out


def save_recording(path: Path, kind: str, events: list[dict], label: str, **extra) -> dict:
    rec = {"kind": kind, "recorded": True, "label": label, "events": mark_recorded(events), **extra}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str) + "\n")
    return rec


def replay(recording: dict | Path, realtime: bool = False, speed: float = 1.0,
           sleep=time.sleep) -> Iterator[dict]:
    """Yield a recording's events exactly as stored; with realtime=True, wait out the original gaps."""
    rec = json.loads(Path(recording).read_text()) if isinstance(recording, (str, Path)) else recording
    last = 0
    for e in rec["events"]:
        if realtime and speed > 0:
            gap = max(0, e["t_ms"] - last) / 1000.0 / speed
            if gap:
                sleep(gap)
        last = e["t_ms"]
        yield dict(e)
