"""Per-visitor rate limits, an input-hash cache, and a request size limit.

Visitor = the CF-Connecting-IP header when present (Cloudflare tunnel), else the client host. Limits are a
sliding one-minute window per (visitor, bucket), in memory, per process (the deploy runs one worker).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict, deque
from typing import Any

from fastapi import HTTPException, Request


def visitor(request: Request, trust_cf: bool = True) -> str:
    if trust_cf:
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()[:64]
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self, limits: dict[str, int], window_s: float = 60.0):
        self.limits = dict(limits)
        self.window = window_s
        self._hits: dict[tuple[str, str], deque] = {}
        self._lock = threading.Lock()

    def check(self, who: str, bucket: str) -> None:
        limit = self.limits.get(bucket)
        if not limit or limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault((who, bucket), deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, int(self.window - (now - q[0])) + 1)
                raise HTTPException(429, detail=f"rate limit: {limit} {bucket} requests a minute per visitor",
                                    headers={"Retry-After": str(retry)})
            q.append(now)
            if len(self._hits) > 50_000:  # drop idle visitors
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                    del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def input_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class Cache:
    """LRU keyed by the SHA-256 of the inputs. Stores only computed outputs (no visitor data)."""

    def __init__(self, max_entries: int = 4096):
        self.max = max_entries
        self._d: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str):
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
                self.hits += 1
                return self._d[key]
            self.misses += 1
            return None

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.max:
                self._d.popitem(last=False)

    def __len__(self) -> int:
        return len(self._d)


class BodySizeLimit:
    """ASGI middleware: 413 when a request body is larger than `max_bytes` (declared or streamed)."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    if int(v) > self.max:
                        return await _too_large(send, self.max)
                except ValueError:
                    return await _too_large(send, self.max)
        seen = 0

        async def limited():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max:
                    raise _TooLarge()
            return msg

        try:
            await self.app(scope, limited, send)
        except _TooLarge:
            await _too_large(send, self.max)


class _TooLarge(Exception):
    pass


async def _too_large(send, n: int):
    body = json.dumps({"detail": f"request body over {n} bytes"}).encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
