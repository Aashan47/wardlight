"""Resident memory of the API, measured the same way every time.

    python deploy/mem_api.py [--port 8767] [--out mem.json]

Starts deploy/run.sh on a spare port, then reads the server's RSS with `ps` (KB) at three points: after
/api/health answers, after one what-if (POST /simulate), and after one agent replay (a recorded planner session
streamed with speed 0). Also reports the peak RSS seen by polling during each step. Stops the server at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BODY = {"loads": ["fridge", "delivery", "oxygen", "lab", "ward"], "pv_kwp": 2.0, "battery_kwh": 14.4,
        "target": 0.99, "fridge_mode": "pqs_sdd"}


def rss_mb(pid: int) -> float:
    """RSS of the process and its children, in MB (uvicorn runs one worker in the same process)."""
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=False).stdout.split()
    kids = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True, check=False).stdout.split()
    for k in kids:
        out += subprocess.run(["ps", "-o", "rss=", "-p", k], capture_output=True, text=True, check=False).stdout.split()
    return round(sum(int(x) for x in out if x.strip()) / 1024.0, 1)


class Peak:
    def __init__(self, pid):
        self.pid, self.peak, self._stop = pid, 0.0, threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.peak = max(self.peak, rss_mb(self.pid))
            except Exception:  # noqa: BLE001, S110 - the process may be between states
                pass
            time.sleep(0.05)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--out")
    ap.add_argument("--agents", action="store_true", help="also run a scripted planner, a verifier and a watcher "
                                                          "(not replays) and record the peak during each")
    a = ap.parse_args(argv)
    env = {**os.environ, "PORT": str(a.port), "LOG_LEVEL": "warning", "WARDLIGHT_RATE_READ": "100000",
           "WARDLIGHT_RATE_SIMULATE": "100000", "WARDLIGHT_RATE_AGENT": "100000"}
    t0 = time.perf_counter()
    proc = subprocess.Popen([str(ROOT / "deploy" / "run.sh")], cwd=ROOT, env=env, start_new_session=True)
    base = f"http://127.0.0.1:{a.port}"
    try:
        with httpx.Client(base_url=base, timeout=120) as c:
            with Peak(proc.pid) as pk_start:
                for _ in range(600):
                    try:
                        if c.get("/api/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.2)
            startup_s = time.perf_counter() - t0
            after_start = rss_mb(proc.pid)
            fid = c.get("/api/facilities", params={"limit": 1, "state": "Kano"}).json()[0]["id"]
            with Peak(proc.pid) as pk_sim:
                c.post(f"/api/facilities/{fid}/simulate", json=BODY).raise_for_status()
            after_sim = rss_mb(proc.pid)
            recs = c.get("/api/agent/recordings").json()["recordings"]
            name = next((r["name"] for r in recs if r["agent"] == "planner"), None)
            with Peak(proc.pid) as pk_agent:
                if name:
                    r = c.post("/api/agent/plan", params={"stream": True, "speed": 0}, json={"recording": name})
                    r.raise_for_status()
            after_agent = rss_mb(proc.pid)
            live = {}
            if a.agents:
                runs = {
                    "planner_scripted": lambda: c.post("/api/agent/plan", params={"stream": True}, json={
                        "question": "I have N80 million for Kano this year. Protect the most vaccine doses."}),
                    "verifier": lambda: c.post(f"/api/agent/verify/{fid}", params={"stream": True},
                                               json={"replies": ["3", "about nine hours", "1"]}),
                    "watcher": lambda: c.get("/api/agent/watch", params={"stream": True, "recorded": False}),
                }
                for run_name, fn in runs.items():
                    with Peak(proc.pid) as pk:
                        r = fn()
                        r.raise_for_status()
                    events = r.text.count("event: ")
                    done = '"recorded":false' in r.text.replace(" ", "")
                    live[run_name] = {"peak_mb": pk.peak, "rss_mb_after": rss_mb(proc.pid), "events": events,
                                  "not_a_replay": done}
        out = {"startup_s": round(startup_s, 1), "rss_mb_after_start": after_start, "peak_mb_start": pk_start.peak,
               "rss_mb_after_simulate": after_sim, "peak_mb_simulate": pk_sim.peak,
               "rss_mb_after_agent_replay": after_agent, "peak_mb_agent_replay": pk_agent.peak,
               "agent_recording": name, "facility": fid, "live_agent_runs": live}
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=30)
    print(json.dumps(out, indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
