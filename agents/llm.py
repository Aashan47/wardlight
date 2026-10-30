"""Chat-completions clients with tool calling: live (OpenAI-compatible HTTP), scripted (tests) and replay (fixtures).

Live client: any OpenAI-compatible `/chat/completions` endpoint (Nebius Token Factory is one), configured only by
environment variables, never by a file this code reads:
  WARDLIGHT_LLM_BASE_URL   e.g. the provider's OpenAI-compatible base URL, ending before /chat/completions
  WARDLIGHT_LLM_MODEL      the model id as the provider lists it
  WARDLIGHT_LLM_API_KEY    the key (sent as a Bearer token; never logged or returned)
  WARDLIGHT_LLM_TIMEOUT_S  optional, default 60
No package beyond httpx (already a project dependency) is needed.

Every client returns a `ChatResponse` whose `message` is an OpenAI-format assistant message:
{"role": "assistant", "content": str | None, "tool_calls": [{"id", "type": "function",
 "function": {"name", "arguments": "<json string>"}}]}.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

ENV_BASE_URL = "WARDLIGHT_LLM_BASE_URL"
ENV_MODEL = "WARDLIGHT_LLM_MODEL"
ENV_API_KEY = "WARDLIGHT_LLM_API_KEY"
ENV_TIMEOUT = "WARDLIGHT_LLM_TIMEOUT_S"


class LLMError(RuntimeError):
    pass


class ReplayMismatch(LLMError):
    """The recorded session no longer matches what the tools return now (data or code changed)."""


@dataclass
class ChatResponse:
    message: dict
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    model: str = ""


class ChatClient(Protocol):
    model_name: str
    kind: str  # "live" | "scripted" | "replay"

    def chat(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 900) -> ChatResponse:
        ...


def estimate_tokens(obj: Any) -> int:
    """Rough token count (characters / 4) for budgeting when a provider omits usage."""
    s = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return max(1, len(s) // 4)


def normalise_message(m: dict) -> dict:
    out: dict = {"role": "assistant", "content": m.get("content")}
    calls = []
    for i, tc in enumerate(m.get("tool_calls") or []):
        fn = tc.get("function", {})
        args = fn.get("arguments", "{}")
        if not isinstance(args, str):
            args = json.dumps(args)
        calls.append({"id": tc.get("id") or f"call_{i}", "type": "function",
                      "function": {"name": fn.get("name", ""), "arguments": args}})
    if calls:
        out["tool_calls"] = calls
    # Reasoning text the model itself returned (gpt-oss and similar return it beside the answer). Kept in a
    # private key that is stripped before the transcript goes back to the API; shown only as the model's own.
    r = m.get("reasoning_content") or m.get("reasoning")
    if isinstance(r, str) and r.strip():
        out["_reasoning"] = r.strip()
    return out


def tool_call(name: str, args: dict, call_id: str = "call_0") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def assistant(content: str | None = None, calls: Sequence[dict] = ()) -> dict:
    m: dict = {"role": "assistant", "content": content}
    if calls:
        m["tool_calls"] = list(calls)
    return m


# ---------------------------------------------------------------- live


class OpenAICompatClient:
    kind = "live"

    def __init__(self, base_url: str, model: str, api_key: str, timeout_s: float = 60.0,
                 transport: httpx.BaseTransport | None = None, max_retries: int = 2):
        if not (base_url and model and api_key):
            raise LLMError("base_url, model and api_key are all required")
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self._key = api_key
        self.max_retries = max_retries
        self._http = httpx.Client(timeout=timeout_s, transport=transport)

    @classmethod
    def from_env(cls, env: dict | None = None, **kw) -> OpenAICompatClient:
        e = os.environ if env is None else env
        missing = [k for k in (ENV_BASE_URL, ENV_MODEL, ENV_API_KEY) if not e.get(k)]
        if missing:
            raise LLMError(f"live model not configured: set {', '.join(missing)}")
        return cls(e[ENV_BASE_URL], e[ENV_MODEL], e[ENV_API_KEY], float(e.get(ENV_TIMEOUT, 60)), **kw)

    def __repr__(self) -> str:  # never show the key
        return f"OpenAICompatClient(base_url={self.base_url!r}, model={self.model_name!r})"

    def chat(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 900) -> ChatResponse:
        clean = [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]
        body: dict = {"model": self.model_name, "messages": clean, "max_tokens": max_tokens, "temperature": 0}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        last = None
        for attempt in range(self.max_retries + 1):
            try:
                r = self._http.post(f"{self.base_url}/chat/completions", json=body,
                                    headers={"Authorization": f"Bearer {self._key}"})
            except httpx.HTTPError as e:
                last = LLMError(f"request failed: {type(e).__name__}")
            else:
                if r.status_code == 200:
                    d = r.json()
                    try:
                        msg = d["choices"][0]["message"]
                    except (KeyError, IndexError, TypeError) as e:
                        raise LLMError("response has no choices[0].message") from e
                    u = d.get("usage") or {}
                    usage = {"prompt_tokens": int(u.get("prompt_tokens") or estimate_tokens(messages)),
                             "completion_tokens": int(u.get("completion_tokens") or estimate_tokens(msg))}
                    return ChatResponse(normalise_message(msg), usage, d.get("model") or self.model_name)
                last = LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
                if r.status_code not in (408, 429, 500, 502, 503, 504):
                    break
            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 8))
        raise last or LLMError("unknown error")


# ---------------------------------------------------------------- scripted (tests)


Step = dict | Callable[[list[dict], list[dict] | None], dict]


class ScriptedModel:
    """A fake model that plays a fixed script. Each step is an assistant message, or a function of the messages so
    far that returns one (so a scripted answer can be composed from real tool results). No model is called."""

    kind = "scripted"

    def __init__(self, steps: Sequence[Step], model_name: str = "scripted-fake"):
        self.steps = list(steps)
        self.model_name = model_name
        self.calls = 0
        self.seen: list[list[dict]] = []

    def chat(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 900) -> ChatResponse:
        self.seen.append([dict(m) for m in messages])
        if self.calls >= len(self.steps):
            raise LLMError("scripted model has no more steps")
        st = self.steps[self.calls]
        self.calls += 1
        msg = st(messages, tools) if callable(st) else st
        msg = normalise_message(msg)
        return ChatResponse(msg, {"prompt_tokens": estimate_tokens(messages), "completion_tokens": estimate_tokens(msg)},
                            self.model_name)


# ---------------------------------------------------------------- replay (fixture mode)


class ReplayClient:
    """Replays the assistant messages of a recorded session. With strict=True it also checks that each tool result
    the planner produces now equals the recorded one, so a replay never shows a stale answer as current."""

    kind = "replay"

    def __init__(self, transcript: list[dict], model_name: str = "recorded", strict: bool = True):
        self.transcript = transcript
        self.assistant_msgs = [m for m in transcript if m.get("role") == "assistant"]
        self.model_name = f"{model_name} (replay)"
        self.strict = strict
        self.i = 0

    def chat(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 900) -> ChatResponse:
        if self.strict:
            now = [m.get("content") for m in messages if m.get("role") == "tool"]
            rec = [m.get("content") for m in self.transcript if m.get("role") == "tool"][: len(now)]
            if now != rec:
                raise ReplayMismatch("tool results differ from the recording; re-record this session")
        if self.i >= len(self.assistant_msgs):
            raise ReplayMismatch("the recording has no more assistant turns")
        msg = self.assistant_msgs[self.i]
        self.i += 1
        return ChatResponse(normalise_message(msg),
                            {"prompt_tokens": estimate_tokens(messages), "completion_tokens": estimate_tokens(msg)},
                            self.model_name)
