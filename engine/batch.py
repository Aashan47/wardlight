"""Batch runner: matches.parquet -> facility_results.parquet (runbook contract columns plus extras).

Usage: python -m engine.batch [--matches PATH] [--limit N] [--workers N] [--draws N]
If data/work/matches.parquet (agent B) does not exist yet, a 50-facility SYNTHETIC matches file is created
and used, and every output row carries input_synthetic = True. Results depend only on the NASA POWER point
and the band mixture, so the simulation and sizing run once per unique (point, bands) key.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict

import numpy as np
import pandas as pd

from . import coldchain as CC
from . import constants as C
from . import doses as D
from . import econ as E
from . import loads as LD
from . import outage as OU
from . import paths
from . import plan as PL
from . import sim as SM
from . import size as SZ
from . import solar as S
from . import supply as SP

TIERS = ("a_named", "b_place", "c_unit_mixture", "d_refused", "offgrid")
TARGET = 0.99


def load_facilities() -> pd.DataFrame:
    if paths.FACILITIES.exists():
        return pd.read_parquet(paths.FACILITIES)
    import pyogrio

    return pyogrio.read_arrow(str(paths.GRID3_GPKG), read_geometry=False)[1].to_pandas()


def make_synthetic_matches(facilities: pd.DataFrame, n: int = 50, seed: int = 20261029) -> pd.DataFrame:
    """SYNTHETIC engine test input: real GRID3 facilities, invented tiers and bands. Never a real match."""
    rng = np.random.default_rng(seed)
    f = facilities.dropna(subset=["latitude", "longitude"])
    f = f[f.facility_level.isin(["Primary", "Secondary"])].sample(n=n, random_state=seed)
    rows = []
    for uid in f.unique_id:
        tier = TIERS[int(rng.integers(len(TIERS)))]
        if tier in ("a_named", "b_place"):
            bands = {str(rng.choice(list("ABCDE"))): 1.0}
        elif tier == "c_unit_mixture":
            w = rng.dirichlet(np.ones(5))
            bands = {b: round(float(x), 3) for b, x in zip("ABCDE", w)}
        else:
            bands = {}
        rows.append({"unique_id": uid, "tier": tier, "bands": json.dumps(bands), "feeder_ids": json.dumps([]),
                     "evidence": json.dumps({}), "grid_km": float(rng.uniform(0, 30)),
                     "reason": "SYNTHETIC: engine test input, not a real match", "synthetic": True})
    return pd.DataFrame(rows)


def bands_for(tier: str, bands_json) -> dict | str | None:
    """Tier d: unknown (None). offgrid: no grid. Otherwise the band mixture."""
    if tier == "d_refused":
        return None
    if tier == "offgrid":
        return SP.OFFGRID
    b = json.loads(bands_json) if isinstance(bands_json, str) else (bands_json or {})
    # any tier name is handled by its bands JSON; unreadable band letters ('?') are dropped and the rest
    # renormalised; nothing left means the supply is unknown
    b = {str(k).upper(): float(v) for k, v in dict(b).items() if str(k).upper() in SP.BAND_HOURS and float(v) > 0}
    return b if b else None


def _key(point: tuple[int, int], bands) -> str:
    if bands is None:
        return f"{point}|UNKNOWN"
    if isinstance(bands, str):
        return f"{point}|{bands}"
    return f"{point}|" + json.dumps({k: round(float(v), 4) for k, v in sorted(bands.items())})


def run_key(point: tuple[int, int], bands, cfg: SM.SimConfig, loads=None) -> dict:
    """The cold-chain answer and the optional clinic line for one (weather point, bands) key."""
    loads = list(loads or LD.SEFORALL_TYPE2_PHC)
    crit = LD.critical(loads)
    lat, lon = point
    pp = SM.prepare(lat, lon, bands, cfg)
    offgrid = isinstance(bands, str) and bands == SP.OFFGRID
    cc = CC.assess(pp, offgrid, cfg, TARGET)
    cs = SZ.size_clinic(lat, lon, bands, crit, TARGET, cfg=cfg, prepared=pp)
    r = SM.simulate_facility(lat, lon, bands, crit, SM.ClinicSystem(cs.chosen.pv_kwp, cs.chosen.battery_kwh),
                             cfg, prepared=pp)
    diesel_ok = pp.known and not offgrid
    clinic_off = r.clinic_offgrid_kwh_yr.point if r.clinic_offgrid_kwh_yr else 0.0
    cec = E.clinic_economics(cs.chosen.pv_kwp, cs.chosen.battery_kwh, clinic_off, diesel_ok)
    clinic = SM.ClinicSystem(cs.chosen.pv_kwp, cs.chosen.battery_kwh)
    outages = [OU.simulate_outage(pp, d, crit, clinic, cc.chosen.fix, cc.chosen.code, cfg) for d in OU.DEFAULT_DAYS]
    orfix = {d: OU.size_outage_ready(pp, crit, offgrid, cfg, days=d) for d in OU.ORFIX_SIZED_FOR}
    o7 = orfix[OU.OR_DAYS]
    orfix_eval = [OU.simulate_outage(pp, d, crit, SM.ClinicSystem(o7.pv_kwp, o7.battery_kwh), o7.fridge_kind,
                                     o7.fridge_code, cfg) for d in OU.ORFIX_EVAL_DAYS]
    return {"sim": r, "coldchain": cc, "clinic": cs, "clinic_econ": cec, "diesel_counted": diesel_ok,
            "outages": outages, "orfix": orfix, "orfix_eval": orfix_eval}


def _iv(x: SM.Interval | None, name: str) -> dict:
    if x is None:
        return {name: np.nan, f"{name}_lo": np.nan, f"{name}_hi": np.nan}
    return {name: x.point, f"{name}_lo": x.lo, f"{name}_hi": x.hi}


def _rng(row: dict, name: str, v: E.Range) -> None:
    row[name], row[f"{name}_lo"], row[f"{name}_hi"] = v.point, v.lo, v.hi


def _row(uid: str, tier: str, out: dict, doses_yr: float, synthetic: bool) -> dict:
    r: SM.SimResult = out["sim"]
    cc: CC.ColdChain = out["coldchain"]
    cs, cec = out["clinic"], out["clinic_econ"]
    fix = cc.chosen
    row = {"unique_id": uid, "tier": tier}
    # today: headline = scenario (b) domestic / non-PQS fridge; scenario (a) PQS ice-lined alongside
    row.update(_iv(cc.today_b_domestic, "uptime_today"))
    row.update(_iv(cc.today_a_pqs, "uptime_today_pqs"))
    row.update(_iv(cc.today_b_technical, "uptime_today_technical"))
    row["today_scenario"] = "b: domestic or non-PQS fridge (a: PQS ice-lined shown alongside; c: no fridge, not modelled)"
    # with the cold-chain fix
    row.update(_iv(fix.uptime, "uptime_with_system"))
    row.update(_iv(fix.uptime_technical, "uptime_with_fix_technical"))
    row["fix_category"] = cc.category
    row["fix_label"] = cc.label
    row["fix_target_met"] = cc.target_met
    row["system_fridge"] = json.dumps({
        "category": cc.category, "code": fix.code, "name": fix.name, "kind": "PQS ice-lined (mains)" if fix.fix == "i"
        else "PQS solar direct drive, dedicated (no other loads)",
        "array_kwp": None if fix.array_kwp is None else round(fix.array_kwp, 3), "target_met": cc.target_met,
        "price_basis": "PQS product sheet price, EXW, base year as printed; excludes freight and installation"})
    row["doses_per_year"] = doses_yr
    for name, iv in (("doses_protected_today", cc.today_b_domestic), ("doses_protected_today_pqs", cc.today_a_pqs),
                     ("doses_with_system", fix.uptime)):
        row[name] = doses_yr * iv.point if iv else np.nan
        row[f"{name}_lo"] = doses_yr * iv.lo if iv else np.nan
        row[f"{name}_hi"] = doses_yr * iv.hi if iv else np.nan
    _rng(row, "capex_usd", fix.capex_usd)
    _rng(row, "capex_ngn", cc.capex_ngn)
    _rng(row, "monthly_cost_ngn", cc.monthly_cost_ngn)
    gain = row["doses_with_system"] - row["doses_protected_today"]
    row["doses_gain"] = gain
    row["doses_per_mngn_fix"] = gain / (cc.capex_ngn.point / 1e6) if cc.capex_ngn.point > 0 else np.nan
    row["priority_score"] = row["doses_per_mngn_fix"]
    # the optional clinic system, its own line, never in the cold-chain price
    row["system_clinic"] = json.dumps({"pv_kwp": cs.chosen.pv_kwp, "battery_kwh": round(cs.chosen.battery_kwh, 2),
                                       "target_met": cs.target_met, "knee_pv_kwp": cs.knee.pv_kwp,
                                       "loads": "priority 1: lights, oxygen, delivery room", "optional": True,
                                       "recommended": cc.category == "iii"})
    row.update(_iv(r.critical_today, "crit_uptime_today"))
    row.update(_iv(r.critical_with, "crit_uptime_with"))
    row["critical_load_hours_day"] = PL.CRITICAL_LOAD_HOURS_PER_DAY
    _rng(row, "clinic_capex_usd", cec.capex_usd)
    _rng(row, "clinic_capex_ngn", cec.capex_ngn)
    _rng(row, "clinic_monthly_cost_ngn", cec.monthly_cost_ngn)
    _rng(row, "diesel_l_avoided", cec.diesel_l_per_year)
    _rng(row, "diesel_ngn_month_avoided", cec.diesel_ngn_per_month)
    _rng(row, "co2_kg_avoided", cec.co2_kg_per_year)
    _rng(row, "payback_months", cec.payback_months)
    row["diesel_counted"] = out["diesel_counted"]
    for o in out.get("outages", []):
        row.update(OU.columns(o))
    for d, o in out.get("orfix", {}).items():
        row.update(OU.orfix_columns(o, OU.orfix_prefix(d)))
    for r_ in out.get("orfix_eval", []):
        row.update(OU.orfix_eval_columns(r_, OU.orfix_prefix(OU.OR_DAYS)))
    row["weather_point"] = f"{r.weather_point[0]},{r.weather_point[1]}"
    row["supply_known"] = r.supply_known
    row["supply_calibrated"] = r.supply_calibrated
    row["n_lanes"] = r.n_lanes
    row["input_synthetic"] = synthetic
    row["labels"] = json.dumps({
        "doses": "ESTIMATE (WorldPop catchment capped at 20,000 people, birth rate, unofficial schedule)",
        "supply": "MODELLED from the NERC band promise; promised, not measured",
        "fridge": "PQS holdover treated as an upper bound; uptimes include an availability scenario (0.90 to 0.99)",
        "diesel": "clinic line only; counted only for grid-connected facilities, as backup-generator fuel displaced",
        "fx": "CBN central rate, same day as SOURCES-VERIFIED section 5"})
    return row


def _worker(args):
    point, bands, cfg = args
    return run_key(point, bands, cfg)


def run(matches_path=None, limit: int | None = None, workers: int = 1, n_draws: int = 48,
        shortfall: SP.ShortfallParams | None = None) -> tuple[pd.DataFrame, dict]:
    t0 = time.perf_counter()
    fac = load_facilities()
    synthetic = False
    if matches_path is None:
        if paths.MATCHES.exists():
            matches_path = paths.MATCHES
        else:
            if not paths.MATCHES_SYNTHETIC.exists():
                paths.WORK.mkdir(parents=True, exist_ok=True)
                make_synthetic_matches(fac).to_parquet(paths.MATCHES_SYNTHETIC, index=False)
            matches_path = paths.MATCHES_SYNTHETIC
    m = pd.read_parquet(matches_path)
    synthetic = bool(m.get("synthetic", pd.Series(False)).any()) or "SYNTHETIC" in str(matches_path)
    if limit:
        m = m.head(limit)
    # the facility list carries a few repeated ids; keep the row that has coordinates
    fac = fac.sort_values("latitude", na_position="last").drop_duplicates("unique_id")
    df = m.merge(fac[["unique_id", "latitude", "longitude"]], on="unique_id", how="left")
    df = df.dropna(subset=["latitude", "longitude"])
    cat = pd.read_parquet(paths.CATCHMENTS) if paths.CATCHMENTS.exists() else None
    if cat is not None:
        raw_col = "catchment_pop_raw" if "catchment_pop_raw" in cat else "catchment_pop"
        df = df.merge(cat[["unique_id", raw_col]].rename(columns={raw_col: "catchment_pop_raw"}), on="unique_id",
                      how="left")
        df["catchment_pop_raw"] = df.catchment_pop_raw.fillna(0.0)
        df["catchment_pop"] = D.apply_cap(df.catchment_pop_raw.to_numpy())[0]
    else:
        df["catchment_pop"] = df["catchment_pop_raw"] = np.nan
    supply_meta = {"calibrated": False}
    if shortfall is None:
        shortfall, supply_meta = SP.calibrated_from_work()
    cfg = SM.SimConfig(n_draws=n_draws, shortfall=shortfall)
    df["bands_obj"] = [bands_for(t, b) for t, b in zip(df.tier, df.bands)]
    df["point"] = [S.nearest_point(a, b) for a, b in zip(df.latitude, df.longitude)]
    df["key"] = [_key(p, b) for p, b in zip(df.point, df.bands_obj)]
    uniq = df.drop_duplicates("key")
    jobs = [(p, b, cfg) for p, b in zip(uniq.point, uniq.bands_obj)]
    if workers > 1:
        with ProcessPoolExecutor(workers) as ex:
            outs = list(ex.map(_worker, jobs, chunksize=4))
    else:
        outs = [_worker(j) for j in jobs]
    by_key = dict(zip(uniq.key, outs))
    rows = [_row(u, t, by_key[k], float(D.doses_per_year(c)) if np.isfinite(c) else np.nan, synthetic)
            for u, t, k, c in zip(df.unique_id, df.tier, df.key, df.catchment_pop)]
    res = pd.DataFrame(rows)
    # the cap (20,000 people, SEforALL) is exposed per facility so the UI can label it; uncapped demand breaks ties
    res["catchment_pop"] = df.catchment_pop.to_numpy()
    res["catchment_pop_raw"] = df.catchment_pop_raw.to_numpy()
    res["capped"] = (res.catchment_pop_raw > C.CATCHMENT_CAP_POP.value).to_numpy()
    res["doses_demand_uncapped"] = D.doses_per_year(res.catchment_pop_raw.to_numpy())
    meta = {"rows": len(res), "unique_keys": len(uniq), "matches_file": str(matches_path),
            "input_synthetic": synthetic, "n_draws": n_draws, "weather_years": list(cfg.years),
            "supply": asdict(cfg.shortfall), "supply_calibration": supply_meta, "target": TARGET, "runtime_s": round(time.perf_counter() - t0, 1),
            "catchments": "present" if cat is not None else "missing: doses are NaN",
            "facilities_capped": int(res.capped.sum()), "cap_pop": C.CATCHMENT_CAP_POP.value,
            "gen_l_per_kwh": [C.GEN_L_PER_KWH.value, C.GEN_L_PER_KWH.lo, C.GEN_L_PER_KWH.hi]}
    return res, meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--draws", type=int, default=48)
    ap.add_argument("--out", default=str(paths.FACILITY_RESULTS))
    a = ap.parse_args(argv)
    res, meta = run(a.matches, a.limit, a.workers, a.draws)
    res.to_parquet(a.out, index=False)
    with open(str(a.out).replace(".parquet", ".meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
