"""Build the API's on-disk store from data/work, once per data version, in its own process.

    python -m api.store_build [--out DIR]

Writes three files named by the data version into the cache directory (WARDLIGHT_CACHE_DIR, default a
`wardlight-api` folder in the system temp directory):
  store-<v>.sqlite      every facility's full merged row as zlib-compressed JSON (facilities + matches + facility_results +
                        catchments, plus the derived tier, code and staleness), and the feeder-row -> facility index;
  core-<v>.parquet      the columns the routes filter, rank and sum on (no JSON text), categorical where repetitive;
  facilities-<v>.json.gz  the unfiltered facility list, gzipped, served as a file.
The API process reads only the core into memory and fetches full rows from SQLite per request, so the big JSON
columns (evidence, by-service hours, system specs) never sit in its memory. Building in a child process means its
peak memory is returned to the system when it exits. Same numbers as the parquet files: nothing is recomputed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

SCHEMA = "8"
# JSON or long text columns kept only in SQLite
HEAVY = {"m_evidence", "m_reason", "system_fridge", "system_clinic", "labels",
         "today_scenario", "weather_point", "ward_standard", "settlement_name", "facility_ownership", "functional",
         "flag_count", "input_synthetic", "supply_known", "supply_calibrated", "result_catchment_pop",
         "result_catchment_pop_raw", "result_pop_above_cap", "m_grid_km"}
# the columns the routes filter, rank and sum on (store_live, outage_api, results, engine.plan, engine.outage)
CORE = {"unique_id", "code", "facility_name", "facility_type", "facility_level", "state_standard", "lga_standard",
        "source_version", "latitude", "longitude", "tier", "has_result", "results_stale", "refusal_reason",
        "n_feeders", "fix_category", "fix_label", "fix_model", "clinic_pv_kwp", "clinic_battery_kwh",
        "uptime_today", "uptime_today_pqs", "uptime_with_system", "doses_per_year", "doses_protected_today",
        "doses_protected_today_pqs", "doses_with_system", "doses_gain", "capex_ngn", "clinic_capex_ngn",
        "crit_uptime_today", "crit_uptime_with", "critical_load_hours_day", "capped", "catchment_pop", "pop_above_cap",
        "doses_demand_uncapped",
        # for agent F's tools reading the same store: match tier, bands and feeder rows, the result's tier, the
        # ranking score, and the three evidence fields the watcher needs for unit mixtures
        "m_tier", "result_tier", "m_bands", "m_feeder_ids", "priority_score", "ev_unit_json"}
# outage columns the city view, the summary, the rankings and agent F's tools sum on; the rest (per-service hours,
# energy, other intervals, the outage-ready fix at other durations) is read from the full row on disk
CORE_RX = re.compile(r"^(out\d+_(window_h|needed_h|hours_today|hours_today_pqs|hours_with|"
                     r"(diesel_l_avoided|generator_litres)(_lo|_hi)?)|"
                     r"orfix_(days|category|label|needed_h|share_kept|pv_kwp|battery_kwh|"
                     r"(hours_kept|diesel_l_avoided|capex_ngn)(_lo|_hi)?))$")
# float64 kept where a value enters engine.plan.rank or a money sum; the rest is float32
KEEP64 = {"latitude", "longitude", "capex_ngn", "clinic_capex_ngn", "uptime_today", "uptime_with_system",
          "doses_with_system", "doses_protected_today", "doses_demand_uncapped", "doses_per_year", "crit_uptime_today",
          "crit_uptime_with", "critical_load_hours_day", "doses_gain"}
KEEP64_RX = re.compile(r"^(out\d+_(hours_today|hours_with)|orfix_(hours_kept|capex_ngn).*)$")
CATEGORICAL = {"state_standard", "lga_standard", "source_version", "fix_label", "fix_model", "fix_model_code",
               "refusal_reason", "orfix_label", "orfix_category", "orfix_fridge_code"}


def cache_dir() -> Path:
    d = Path(os.environ.get("WARDLIGHT_CACHE_DIR") or Path(tempfile.gettempdir()) / "wardlight-api")
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_version(work: Path) -> str:
    try:
        from agents.tools import WardlightData

        return WardlightData(work_dir=work).version
    except Exception:  # noqa: BLE001 - agents/ absent: the same definition written out
        import hashlib

        h = hashlib.sha256()
        for name in ("facilities", "matches", "facility_results", "nerc_rows"):
            p = work / f"{name}.parquet"
            if p.exists():
                st = p.stat()
                h.update(f"{name}:{st.st_size}:{int(st.st_mtime)}".encode())
        return h.hexdigest()[:12]


def paths(work: Path, out: Path | None = None) -> dict[str, Path]:
    v = data_version(work)
    d = out or cache_dir()
    tag = f"{v}-s{SCHEMA}"
    return {"version": v, "sqlite": d / f"store-{tag}.sqlite", "core": d / f"core-{tag}.parquet",
            "list": d / f"facilities-{tag}.json.gz", "meta": d / f"meta-{tag}.json"}


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if hasattr(v, "item"):
        try:
            return _clean(v.item())
        except (ValueError, AttributeError):
            return str(v)
    if v is getattr(__import__("pandas"), "NA", object()):
        return None
    return v


def _clean_json(v):
    return _clean(v)


def _nan_to_none(x):
    if isinstance(x, dict):
        return {k: _nan_to_none(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_nan_to_none(v) for v in x]
    return _clean(x)


def _jl(x, default):
    if not isinstance(x, str):
        return default
    try:
        return json.loads(x)
    except ValueError:
        return default


def build(work: Path, out: Path | None = None) -> dict[str, Path]:
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq

    p = paths(work, out)
    tmp = {k: v.with_suffix(v.suffix + ".tmp") for k, v in p.items() if k != "version"}
    fac = pd.read_parquet(work / "facilities.parquet")
    fac = fac.sort_values("latitude", na_position="last").drop_duplicates("unique_id")
    m = pd.read_parquet(work / "matches.parquet")
    m = m.rename(columns={c: f"m_{c}" for c in m.columns if c != "unique_id"})
    base = fac.merge(m, on="unique_id", how="left")
    del fac, m
    if (work / "catchments.parquet").exists():
        cat = pd.read_parquet(work / "catchments.parquet", columns=["unique_id", "catchment_pop", "pop_above_cap"])
        base = base.merge(cat, on="unique_id", how="left")
        del cat
    else:
        base["catchment_pop"] = np.nan
        base["pop_above_cap"] = np.nan
    base = base.sort_values("unique_id").reset_index(drop=True)
    base["code"] = np.arange(1, len(base) + 1, dtype=np.int32)
    base = base.set_index("unique_id", drop=False)

    con = sqlite3.connect(tmp["sqlite"])
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("CREATE TABLE fac (code INTEGER PRIMARY KEY, unique_id TEXT UNIQUE, row BLOB)")
    con.execute("CREATE TABLE feeder_fac (row_key TEXT, unique_id TEXT)")
    con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")

    rf = pq.ParquetFile(work / "facility_results.parquet")
    rename = {"tier": "result_tier", "catchment_pop": "result_catchment_pop",
              "catchment_pop_raw": "result_catchment_pop_raw", "pop_above_cap": "result_pop_above_cap"}
    res_cols = [rename.get(c, c) for c in rf.schema.names]
    core_parts = []
    seen: set[str] = set()

    def emit(frame: pd.DataFrame) -> None:
        frame = frame.reindex(columns=list(dict.fromkeys([*frame.columns, *res_cols])))
        frame["tier"] = frame["m_tier"].where(frame["m_tier"].notna(), frame["result_tier"]).fillna("d_refused")
        frame["results_stale"] = frame["result_tier"].notna() & (frame["result_tier"] != frame["tier"])
        frame["has_result"] = frame["uptime_with_system"].notna()
        frame["refusal_reason"] = frame["m_reason"].where(frame["tier"] == "d_refused").map(
            lambda s: s.split(";")[0].strip() if isinstance(s, str) else ("no match row" if pd.isna(s) else None))
        frame.loc[frame.tier != "d_refused", "refusal_reason"] = None
        sf = frame["system_fridge"].map(lambda x: _jl(x, {}))
        sc = frame["system_clinic"].map(lambda x: _jl(x, {}))
        frame["fix_model"] = sf.map(lambda d: d.get("name") if isinstance(d, dict) else None)
        frame["fix_model_code"] = sf.map(lambda d: d.get("code") if isinstance(d, dict) else None)
        frame["clinic_pv_kwp"] = sc.map(lambda d: d.get("pv_kwp") if isinstance(d, dict) else None).astype(float)
        frame["clinic_battery_kwh"] = sc.map(lambda d: d.get("battery_kwh") if isinstance(d, dict) else None
                                             ).astype(float)
        fids = frame["m_feeder_ids"].map(lambda x: _jl(x, []) or [])
        unit = frame["m_tier"] == "c_unit_mixture"
        frame["ev_unit_json"] = None
        frame.loc[unit, "ev_unit_json"] = frame.loc[unit, "m_evidence"].map(
            lambda x: json.dumps({k: v for k, v in (_jl(x, {}) or {}).items()
                                  if k in ("order_month", "unit", "band_counts")}))
        frame["n_feeders"] = fids.map(len).astype("int16")
        rows = []
        for rec in frame.to_dict("records"):
            rows.append((int(rec["code"]), rec["unique_id"],
                         zlib.compress(json.dumps({k: _clean(v) for k, v in rec.items()}, separators=(",", ":"),
                                                  default=str).encode(), 6)))
        con.executemany("INSERT INTO fac VALUES (?,?,?)", rows)
        con.executemany("INSERT INTO feeder_fac VALUES (?,?)",
                        [(k, u) for u, ks in zip(frame.unique_id, fids) for k in ks])
        core_parts.append(frame[[c for c in frame.columns if (c in CORE or CORE_RX.match(c)) and c not in HEAVY]])

    for batch in rf.iter_batches(batch_size=4096):
        r = batch.to_pandas().rename(columns=rename)
        r = r[r.unique_id.isin(base.index)].drop_duplicates("unique_id")
        seen.update(r.unique_id)
        emit(base.loc[r.unique_id].reset_index(drop=True).merge(r, on="unique_id", how="left"))
        del r, batch
    rest = base[~base.index.isin(seen)].reset_index(drop=True)
    for i in range(0, len(rest), 4096):
        emit(rest.iloc[i:i + 4096])
    con.execute("CREATE INDEX ff ON feeder_fac(row_key)")
    con.execute("INSERT INTO meta VALUES ('version', ?)", (p["version"],))
    con.commit()
    con.close()

    core = pd.concat(core_parts, ignore_index=True).sort_values("code").reset_index(drop=True)
    for c in core.columns:
        if core[c].dtype == np.float64 and c not in KEEP64 and not KEEP64_RX.match(c):
            core[c] = core[c].astype(np.float32)
            continue
        if c in CATEGORICAL:
            core[c] = core[c].astype("category")
        elif core[c].dtype == object:
            vals = set(core[c].dropna().map(type))
            if vals and vals <= {bool, np.bool_}:
                core[c] = core[c].astype("boolean")
            elif vals and vals <= {int, float, np.int64, np.float64}:
                core[c] = pd.to_numeric(core[c], errors="coerce")
            else:
                core[c] = core[c].astype(object)
    core.to_parquet(tmp["core"], index=False)

    from .store_live import list_frame_from

    lst = list_frame_from(core)
    with gzip.open(tmp["list"], "wt", encoding="utf-8", compresslevel=6) as f:
        f.write(lst.to_json(orient="records"))
    from dataclasses import asdict

    from engine import supply as SP

    from .store_live import build_summary

    params, cal = SP.calibrated_from_work(work)
    meta = {"version": p["version"], "schema": SCHEMA, "rows": len(core),
            "supply": {"params": asdict(params), "meta": cal}, "summary": _nan_to_none(build_summary(core))}
    tmp["meta"].write_text(json.dumps(meta, default=_clean_json, allow_nan=False))
    for k, t in tmp.items():
        os.replace(t, p[k])
    return p


def ensure(work: Path, out: Path | None = None) -> dict[str, Path]:
    """The store for this data version, building it in a child process when absent; older versions are removed."""
    p = paths(work, out)
    if not all(p[k].exists() for k in ("sqlite", "core", "list", "meta")):
        _build_in_child(work, out)
        p = paths(work, out)
    tag = p["meta"].name[len("meta-"):-len(".json")]
    for old in p["meta"].parent.glob("*-*-s*.*"):
        if old.name.split("-", 1)[0] in ("store", "core", "facilities", "meta") and tag not in old.name:
            old.unlink(missing_ok=True)
    return p


def _build_in_child(work: Path, out: Path | None) -> None:
    env = {**os.environ, "WARDLIGHT_WORK": str(work)}
    if out:
        env["WARDLIGHT_CACHE_DIR"] = str(out)
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-m", "api.store_build", "--work", str(work)], cwd=root, env=env, check=True)


def main(argv=None) -> int:
    from .config import settings

    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    work = Path(a.work) if a.work else settings().work
    p = build(work, Path(a.out) if a.out else None)
    print(json.dumps({k: str(v) for k, v in p.items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
