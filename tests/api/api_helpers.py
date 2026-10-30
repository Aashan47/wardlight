"""Helpers for the API tests (imported by conftest.py and the test modules)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # build/wardlight
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import Settings

WEB_FIXTURES = ROOT / "data" / "fixtures" / "web"
WORK = ROOT / "data" / "work"
TYPES_TS = ROOT / "web" / "src" / "api" / "types.ts"
HAS_WORK = all((WORK / f"{n}.parquet").exists() for n in ("facilities", "matches", "facility_results", "nerc_rows"))


def make_settings(**kw) -> Settings:
    base = {"fixture": True, "rate_read": 10_000, "rate_simulate": 10_000, "rate_agent": 10_000, "rate_telephony": 10_000}
    base.update(kw)
    return Settings(**base)


def recording(events: list[dict], kind: str, **extra) -> dict:
    """A recording in agents/events.py save_recording's format."""
    return {"kind": kind, "recorded": True, "label": "test recording", "events": events, **extra}


def planner_events(question: str, gaps_ms=(0, 120, 240, 360, 360)) -> list[dict]:
    t = list(gaps_ms)
    return [
        {"type": "plan", "seq": 0, "t_ms": t[0], "steps": [{"id": "gather", "title": "Read the data"}]},
        {"type": "step_start", "seq": 1, "t_ms": t[1], "id": "gather"},
        {"type": "tool_call", "seq": 2, "t_ms": t[2], "id": "c1", "name": "rank_budget", "args": {"state": "Edo"}},
        {"type": "tool_result", "seq": 3, "t_ms": t[3], "id": "c1", "summary": "ranked", "rows": 3, "ms": 5},
        {"type": "done", "seq": 4, "t_ms": t[4], "model": "scripted", "tokens": 0, "cost_usd": 0.0,
         "recorded": False, "duration_ms": t[4]},
    ]


def sse_events(text: str) -> list[dict]:
    """Parse a text/event-stream body into [{'id', 'event', 'data'}] (keep-alive comments skipped)."""
    out = []
    for block in text.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        d: dict = {}
        for line in block.split("\n"):
            if line.startswith(":"):
                continue
            k, _, v = line.partition(": ")
            d[k] = v
        if "data" in d:
            d["data"] = json.loads(d["data"])
            out.append(d)
    return out


# ------------------------------------------------------------ types.ts: required keys per interface


def _split_top(body: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in body:
        if ch in "{[(<":
            depth += 1
        elif ch in "}])>":
            depth -= 1
        if depth == 0 and ch in ";\n":
            if cur.strip():
                parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def ts_interfaces() -> dict[str, dict[str, bool]]:
    """{interface: {field: required}} for every `export interface` in web/src/api/types.ts, with inherited fields
    (bases may be declared after the interface that extends them)."""
    src = re.sub(r"/\*.*?\*/|//[^\n]*", "", TYPES_TS.read_text(), flags=re.DOTALL)
    own: dict[str, dict[str, bool]] = {}
    bases: dict[str, list[str]] = {}
    for m in re.finditer(r"export interface (\w+)(?: extends ([\w, ]+))? \{", src):
        i, depth = m.end(), 1
        j = i
        while depth:
            depth += {"{": 1, "}": -1}.get(src[j], 0)
            j += 1
        fields = {}
        for part in _split_top(src[i: j - 1]):
            fm = re.match(r"(\w+)(\??):", part)
            if fm:
                fields[fm.group(1)] = fm.group(2) != "?"
        own[m.group(1)] = fields
        bases[m.group(1)] = [b.strip() for b in (m.group(2) or "").split(",") if b.strip()]

    def resolve(name, seen=()):
        out: dict[str, bool] = {}
        for b in bases.get(name, []):
            if b in own and b not in seen:
                out.update(resolve(b, (*seen, name)))
        out.update(own.get(name, {}))
        return out

    return {n: resolve(n) for n in own}


def missing_required(obj: dict, interface: str) -> list[str]:
    req = ts_interfaces()[interface]
    return [k for k, r in req.items() if r and k not in obj]
