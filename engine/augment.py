"""Add outage windows to an existing facility_results.parquet without re-running the sizing.

    python -m engine.augment [--workers N] [--check]

`engine.batch` sizes every system (the slow part) and then runs the outage windows in `outage.DEFAULT_DAYS` and the
7-day outage-ready fix through `outage.ORFIX_EVAL_DAYS`. When a window is added to those lists (60 days, brief 13),
this module computes only the missing `out{N}_*` and `orfix_at{N}_*` columns, per (weather point, bands) key, with
the same draws as the batch (same seed, same calibrated supply, same lanes) and the systems already chosen (read
from `system_fridge`, `system_clinic` and `orfix_*`). Batteries are re-derived as kWp x 7.2, as the sizers build them.
`--check` recomputes one existing window first and fails unless it matches the stored columns.

It also refreshes the columns that are pure arithmetic on a changed constant: litres (and CO2) when the generator
curve GEN_L_PER_KWH changes (every litres column is curve x energy, so the rescale is exact; the curve in use is
recorded in the meta file as `gen_l_per_kwh`), then the clinic line's diesel naira per month and its payback at the
current diesel price. Hours and capex are untouched.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from . import batch as BT
from . import constants as C
from . import econ as E
from . import fridge as F
from . import loads as LD
from . import outage as OU
from . import paths
from . import sim as SM
from . import solar as S
from . import supply as SP


def missing(columns) -> tuple[list[int], list[int]]:
    cols = set(columns)
    out = [d for d in OU.DEFAULT_DAYS if f"out{d}_window_h" not in cols]
    ev = [d for d in OU.ORFIX_EVAL_DAYS if f"orfix_at{d}_hours_kept" not in cols]
    return out, ev


def _fix_kind(code: str) -> str:
    return "ii" if F.CATALOGUE[code].kind == "sdd" else "i"


def run_key(point, bands, cfg: SM.SimConfig, fix_code: str, clinic_kwp: float, or_code: str, or_kwp: float,
            out_days: list[int], eval_days: list[int]) -> dict:
    crit = LD.critical()
    pp = SM.prepare(point[0], point[1], bands, cfg)
    r = C.BATTERY_KWH_PER_KWP.value
    row: dict = {}
    for d in out_days:
        o = OU.simulate_outage(pp, d, crit, SM.ClinicSystem(clinic_kwp, clinic_kwp * r), _fix_kind(fix_code),
                               fix_code, cfg)
        row.update(OU.columns(o))
    for d in eval_days:
        o = OU.simulate_outage(pp, d, crit, SM.ClinicSystem(or_kwp, or_kwp * r), _fix_kind(or_code), or_code, cfg)
        row.update(OU.orfix_eval_columns(o, OU.orfix_prefix(OU.OR_DAYS)))
    return row


def _worker(job):
    key, args = job
    return key, run_key(*args)


def keys_for(res: pd.DataFrame) -> pd.DataFrame:
    """unique_id -> (point, bands, key), rebuilt exactly as engine.batch.run does."""
    fac = BT.load_facilities().sort_values("latitude", na_position="last").drop_duplicates("unique_id")
    m = pd.read_parquet(paths.MATCHES)
    df = m.merge(fac[["unique_id", "latitude", "longitude"]], on="unique_id", how="left").dropna(
        subset=["latitude", "longitude"])
    df = df[df.unique_id.isin(res.unique_id)]
    df["bands_obj"] = [BT.bands_for(t, b) for t, b in zip(df.tier, df.bands)]
    df["point"] = [S.nearest_point(a, b) for a, b in zip(df.latitude, df.longitude)]
    df["key"] = [BT._key(p, b) for p, b in zip(df.point, df.bands_obj)]
    return df[["unique_id", "point", "bands_obj", "key"]]


OLD_GEN = (0.378, 0.303, 0.454)  # the UNVERIFIED vendor-chart curve the batch used before 31 Oct 2026
LITRE_RX = r"(diesel_l_avoided|generator_litres)(_lo|_hi)?$"


def gen_curve() -> tuple[float, float, float]:
    g = C.GEN_L_PER_KWH
    return (g.value, g.lo, g.hi)


def rescale_litres(res: pd.DataFrame, old: tuple[float, float, float],
                   new: tuple[float, float, float] | None = None) -> pd.DataFrame:
    """Every litres column is (curve point, lo, hi) x energy, so a new curve rescales it exactly; CO2 follows."""
    new = new or gen_curve()
    res = res.copy()
    for col in res.columns:
        m = re.search(LITRE_RX, col)
        if not m:
            continue
        i = {None: 0, "_lo": 1, "_hi": 2}[m.group(2)]
        res[col] = res[col] * (new[i] / old[i])
    if "co2_kg_avoided" in res and "diesel_l_avoided" in res:
        for sfx in ("", "_lo", "_hi"):
            res[f"co2_kg_avoided{sfx}"] = res[f"diesel_l_avoided{sfx}"] * C.CO2_KG_PER_L_DIESEL.value
    return res


def refresh_diesel_naira(res: pd.DataFrame) -> pd.DataFrame:
    """Clinic-line diesel naira per month and payback at the current DIESEL_NGN_PER_L (litres unchanged)."""
    if "diesel_l_avoided" not in res or "clinic_capex_usd" not in res:
        return res
    res = res.copy()
    litres = [E.Range(p, lo, hi) for p, lo, hi in zip(res.diesel_l_avoided, res.diesel_l_avoided_lo,
                                                       res.diesel_l_avoided_hi)]
    caps = [E.Range(p, lo, hi) for p, lo, hi in zip(res.clinic_capex_usd, res.clinic_capex_usd_lo,
                                                     res.clinic_capex_usd_hi)]
    dm = [E.diesel_cost_ngn_per_month(x) for x in litres]
    pb = [E.payback_months(E.to_ngn(c), d, E.monthly_om_ngn(c)) for c, d in zip(caps, dm)]
    for name, vals in (("diesel_ngn_month_avoided", dm), ("payback_months", pb)):
        if name in res:
            res[name] = [v.point for v in vals]
            res[f"{name}_lo"] = [v.lo for v in vals]
            res[f"{name}_hi"] = [v.hi for v in vals]
    return res


def augment(res: pd.DataFrame, workers: int = 1, n_draws: int = 48, check: bool = False,
            out_days: list[int] | None = None, eval_days: list[int] | None = None) -> tuple[pd.DataFrame, dict]:
    t0 = time.perf_counter()
    m_out, m_ev = missing(res.columns)
    out_days = m_out if out_days is None else out_days
    eval_days = m_ev if eval_days is None else eval_days
    shortfall, _ = SP.calibrated_from_work()
    cfg = SM.SimConfig(n_draws=n_draws, shortfall=shortfall)
    k = keys_for(res)
    df = res.merge(k, on="unique_id", how="left")
    df = df[df.key.notna()]
    first = df.drop_duplicates("key")
    jobs = []
    for r in first.itertuples(index=False):
        sf = json.loads(r.system_fridge)
        sc = json.loads(r.system_clinic)
        jobs.append((r.key, (r.point, r.bands_obj, cfg, sf["code"], float(sc["pv_kwp"]), r.orfix_fridge_code,
                             float(r.orfix_pv_kwp), out_days, eval_days)))
    meta = {"keys": len(jobs), "out_days": out_days, "eval_days": eval_days}
    if check and jobs:
        # recompute a stored window for the first few keys and compare
        d0 = 14
        for key, a in jobs[:3]:
            got = run_key(*a[:7], [d0], [d0])
            row = df[df.key == key].iloc[0]
            for c in (f"out{d0}_hours_today", f"out{d0}_hours_with", f"orfix_at{d0}_hours_kept",
                      f"out{d0}_diesel_l_avoided"):
                if not np.isclose(got[c], row[c], rtol=1e-6, atol=1e-6):
                    raise AssertionError(f"augment does not reproduce {c} for {key}: {got[c]} vs {row[c]}")
        meta["check"] = "reproduced out14 and orfix_at14 for 3 keys"
    if not out_days and not eval_days:
        return refresh_diesel_naira(res), {**meta, "runtime_s": round(time.perf_counter() - t0, 1)}
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            outs = dict(ex.map(_worker, jobs, chunksize=4))
    else:
        outs = dict(_worker(j) for j in jobs)
    add = pd.DataFrame([{"key": kk, **v} for kk, v in outs.items()])
    new = df[["unique_id", "key"]].merge(add, on="key", how="left").drop(columns="key")
    res = res.drop(columns=[c for c in new.columns if c != "unique_id" and c in res.columns])
    res = res.merge(new, on="unique_id", how="left")
    meta["runtime_s"] = round(time.perf_counter() - t0, 1)
    return refresh_diesel_naira(res), meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--path", default=str(paths.FACILITY_RESULTS))
    a = ap.parse_args(argv)
    res = pd.read_parquet(a.path)
    meta_path = a.path.replace(".parquet", ".meta.json")
    try:
        bmeta = json.load(open(meta_path))
    except OSError:
        bmeta = {}
    order = list(res.columns)
    old = tuple(bmeta.get("gen_l_per_kwh", OLD_GEN))
    if tuple(old) != gen_curve():
        res = rescale_litres(res, old)
        bmeta["gen_l_per_kwh"] = list(gen_curve())
        bmeta["gen_l_per_kwh_note"] = "litres columns rescaled from the earlier curve by engine.augment"
    out, meta = augment(res, a.workers, int(bmeta.get("n_draws", 48)), a.check)
    out = out[[*order, *[c for c in out.columns if c not in order]]]
    out.to_parquet(a.path, index=False)
    bmeta.setdefault("augmented", []).append(meta)
    with open(meta_path, "w") as f:
        json.dump(bmeta, f, indent=2)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
