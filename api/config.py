"""Settings, read once from the environment. Nothing here reads `.env`; the deploy unit sets variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]  # build/wardlight


def _flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    fixture: bool = field(default_factory=lambda: _flag("WARDLIGHT_FIXTURE"))
    work: Path = field(default_factory=lambda: Path(os.environ.get("WARDLIGHT_WORK", PROJECT / "data" / "work")))
    data_local: Path = field(default_factory=lambda: Path(
        os.environ.get("WARDLIGHT_DATA_LOCAL", PROJECT.parents[1] / "data-local")))
    fixtures: Path = field(default_factory=lambda: Path(
        os.environ.get("WARDLIGHT_FIXTURES", PROJECT / "data" / "fixtures")))
    docs: Path = field(default_factory=lambda: PROJECT / "docs")
    web_dist: Path = field(default_factory=lambda: Path(os.environ.get("WARDLIGHT_WEB_DIST", PROJECT / "web" / "dist")))
    # per visitor, per minute
    rate_read: int = field(default_factory=lambda: _int("WARDLIGHT_RATE_READ", 240))
    rate_simulate: int = field(default_factory=lambda: _int("WARDLIGHT_RATE_SIMULATE", 30))
    rate_agent: int = field(default_factory=lambda: _int("WARDLIGHT_RATE_AGENT", 6))
    rate_telephony: int = field(default_factory=lambda: _int("WARDLIGHT_RATE_TELEPHONY", 60))
    max_body_bytes: int = field(default_factory=lambda: _int("WARDLIGHT_MAX_BODY_BYTES", 16_384))
    cache_entries: int = field(default_factory=lambda: _int("WARDLIGHT_CACHE_ENTRIES", 4096))
    # live agent runs per UTC day across all visitors (recorded replays do not count)
    agent_daily_cap: int = field(default_factory=lambda: _int("WARDLIGHT_AGENT_DAILY_CAP", 40))
    # agent F's modules are only called when this is on; otherwise recorded sessions are replayed
    agent_live: bool = field(default_factory=lambda: _flag("WARDLIGHT_AGENT_LIVE"))
    # "all": recorded, scripted and (with agent_live) live runs; "replay": recorded sessions only. A scripted or live
    # run builds agent F's Toolbox, measured at about 1 GB resident, so a small server runs "replay".
    agent_runs: str = field(default_factory=lambda: os.environ.get("WARDLIGHT_AGENT_RUNS", "all").strip().lower())
    whatif_draws: int = field(default_factory=lambda: _int("WARDLIGHT_WHATIF_DRAWS", 32))
    # Cloudflare sets CF-Connecting-IP; trust it only behind the tunnel
    trust_cf_header: bool = field(default_factory=lambda: _flag("WARDLIGHT_TRUST_CF", True))
    # where the on-disk store (api/store_build.py) is kept; None = WARDLIGHT_CACHE_DIR or a temp folder
    cache_dir: Path | None = field(default_factory=lambda: Path(os.environ["WARDLIGHT_CACHE_DIR"])
                                   if os.environ.get("WARDLIGHT_CACHE_DIR") else None)


def settings() -> Settings:
    return Settings()
