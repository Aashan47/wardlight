"""T6 through the API: POST /api/facilities/{id}/simulate for 200 random facilities, wall time per call.

    python deploy/t6_api.py --base http://127.0.0.1:8000 [--n 200] [--seed 20261030] [--out t6_api.json]

Run it against a server started with WARDLIGHT_CACHE_ENTRIES=0, so no call is a cache hit. Facilities are drawn
with the PREREG seed from those with coordinates. The request is the web app's: all five rooms, a 2 kWp /
14.4 kWh clinic system (SEforALL's 7.2 kWh per kWp), dedicated PQS solar fridge mode.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import time

import httpx

BODY = {"loads": ["fridge", "delivery", "oxygen", "lab", "ward"], "pv_kwp": 2.0, "battery_kwh": 14.4,
        "target": 0.99, "fridge_mode": "pqs_sdd"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    with httpx.Client(base_url=a.base, timeout=60) as c:
        items = [x for x in c.get("/api/facilities").json() if x.get("lat") is not None]
        ids = [x["id"] for x in random.Random(a.seed).sample(items, a.n)]
        times, engine_ms, hits = [], [], 0
        for fid in ids:
            t0 = time.perf_counter()
            r = c.post(f"/api/facilities/{fid}/simulate", json=BODY)
            times.append(time.perf_counter() - t0)
            r.raise_for_status()
            j = r.json()
            hits += bool(j.get("cached"))
            engine_ms.append(j.get("engine_ms"))
    q = statistics.quantiles(times, n=100)
    out = {"n": len(times), "p50_s": statistics.median(times), "p95_s": q[94], "max_s": max(times),
           "first_call_s": times[0], "cache_hits": hits, "engine_p50_ms": statistics.median(engine_ms),
           "base": a.base, "machine": f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs",
           "load_average_after": os.getloadavg() if hasattr(os, "getloadavg") else None,
           "body": BODY, "seed": a.seed}
    print(json.dumps(out, indent=2))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(out, f, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
