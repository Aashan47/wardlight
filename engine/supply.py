"""Grid supply model: band promise, shortfall below it, outage timing. Every output is MODELLED.

Generative model for one simulated feeder-year ("draw"):
1. Band: drawn from the facility's band mixture `{band: weight}` (tier a or b: one band; tier c: a
   mixture over the business unit's feeders). `OFFGRID` means no grid at all. `FULL` (24 h) exists for tests.
2. Promise H = NERC band minimum hours (A 20, B 16, C 12, D 8, E 4). The promise is the ceiling.
3. Monthly shortfall fraction f_m: 0 with probability p_meet (the feeder meets its promise that month),
   otherwise Beta(alpha, beta). Calibrated on `nerc_shortfalls.parquet` (measured average hours of failing
   Band A feeders) by `calibrate_shortfall`; until then an UNCALIBRATED PRIOR, flagged in every output.
   The fractional shortfall is applied to every band (NERC measures only Band A; transfer is an assumption).
4. Daily shortfall f_t ~ Beta with mean f_m and concentration `daily_concentration`; supply hours
   d_t = H * (1 - f_t), stochastically rounded to whole hours.
5. Timing: outage blocks per day k = 1 + Poisson(lambda - 1), lambda = 32.8 outages per month / 30.44 days
   (World Bank Enterprise Survey, Nigeria 2014), capped at 2 blocks; the on and off hours are split between the
   blocks at random and the pattern starts at a uniformly random hour. No source gives the time of day of
   outages, so timing within the day is uniform (stated on /method).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace

import numpy as np
import pandas as pd

from . import constants as C

OFFGRID = "OFFGRID"
FULL = "FULL"
BAND_HOURS: dict[str, float] = {**C.BAND_MIN_HOURS, OFFGRID: 0.0, FULL: 24.0}


@dataclass(frozen=True)
class ShortfallParams:
    p_meet: float = 0.5
    alpha: float = 2.0
    beta: float = 5.0
    daily_concentration: float = 10.0
    calibrated: bool = False
    note: str = "UNCALIBRATED PRIOR (assumption): replace with calibrate_shortfall() on nerc_shortfalls.parquet"

    def to_json(self) -> str:
        return json.dumps(asdict(self))


# Prior ranges shown with the prior (ASSUMPTION): p_meet 0.2 to 0.8, mean shortfall when failing 0.1 to 0.5.
PRIOR = ShortfallParams()


@dataclass(frozen=True)
class OutageTiming:
    events_per_month: float = C.ES_OUTAGES_PER_MONTH.value
    days_per_month: float = C.DAYS_PER_MONTH.value
    max_blocks: int = 2

    @property
    def events_per_day(self) -> float:
        return self.events_per_month / self.days_per_month


def normalise_bands(bands: Mapping[str, float] | str | None) -> dict[str, float]:
    """Accept a dict, a JSON string, a single band letter, OFFGRID, or None/empty (= OFFGRID)."""
    if bands is None:
        return {OFFGRID: 1.0}
    if isinstance(bands, str):
        s = bands.strip()
        if s.startswith("{"):
            bands = json.loads(s)
        else:
            bands = {s.upper(): 1.0}
    out = {str(k).upper(): float(v) for k, v in dict(bands).items() if float(v) > 0}
    if not out:
        return {OFFGRID: 1.0}
    bad = [k for k in out if k not in BAND_HOURS]
    if bad:
        raise ValueError(f"unknown band(s): {bad}")
    tot = sum(out.values())
    return {k: v / tot for k, v in out.items()}


def band_hours_from_rows(nerc_rows: pd.DataFrame) -> dict[str, float]:
    """Modal printed minimum hours per band from agent A's nerc_rows (to confirm BAND_MIN_HOURS)."""
    df = nerc_rows.dropna(subset=["band", "min_hours"])
    return {str(b): float(g.min_hours.mode().iloc[0]) for b, g in df.groupby("band")}


def _beta_from_mean(mean: np.ndarray, conc: float, rng: np.random.Generator) -> np.ndarray:
    m = np.clip(mean, 1e-6, 1 - 1e-6)
    return rng.beta(m * conc, (1 - m) * conc)


def sample_monthly_shortfall(n: int, params: ShortfallParams, rng: np.random.Generator) -> np.ndarray:
    fail = rng.random(n) >= params.p_meet
    f = np.zeros(n)
    f[fail] = rng.beta(params.alpha, params.beta, size=int(fail.sum()))
    return f


def sample_daily_hours(bands: Mapping[str, float] | str | None, n_draws: int, n_days: int,
                       rng: np.random.Generator, params: ShortfallParams = PRIOR) -> tuple[np.ndarray, np.ndarray]:
    """Daily supply hours, shape (n_draws, n_days), and the band letter of each draw."""
    mix = normalise_bands(bands)
    names = list(mix)
    band_idx = rng.choice(len(names), size=n_draws, p=[mix[k] for k in names])
    promise = np.array([BAND_HOURS[names[i]] for i in band_idx])
    n_months = int(np.ceil(n_days / 30.4375)) + 1
    f_month = sample_monthly_shortfall(n_draws * n_months, params, rng).reshape(n_draws, n_months)
    month_of_day = np.minimum((np.arange(n_days) / 30.4375).astype(int), n_months - 1)
    f_mean = f_month[:, month_of_day]
    f_day = np.where(f_mean > 0, _beta_from_mean(f_mean, params.daily_concentration, rng), 0.0)
    banded = np.isin(np.array(names)[band_idx], list(C.BAND_MIN_HOURS))  # FULL and OFFGRID take no shortfall
    f_day = np.where(banded[:, None], f_day, 0.0)
    hours = promise[:, None] * (1.0 - f_day)
    # stochastic rounding keeps the expected hours unbiased
    base = np.floor(hours)
    hours = base + (rng.random(hours.shape) < (hours - base))
    return np.clip(hours, 0, 24).astype(np.int16), np.array([names[i] for i in band_idx])


def daily_pattern(on_hours: np.ndarray, rng: np.random.Generator, timing: OutageTiming = OutageTiming()) -> np.ndarray:
    """Hourly on/off pattern (..., 24) bool for integer on-hours per day, with outage blocks per the ES rate."""
    d = np.asarray(on_hours, dtype=np.int16)
    off = 24 - d
    lam_extra = max(timing.events_per_day - 1.0, 0.0)
    k = 1 + np.minimum(rng.poisson(lam_extra, size=d.shape), timing.max_blocks - 1)
    two = (k >= 2) & (d >= 2) & (off >= 2)
    # split on and off hours into two blocks where two blocks are drawn
    d1 = np.where(two, 1 + np.floor(rng.random(d.shape) * (d - 1)).astype(np.int16), d)
    o1 = np.where(two, 1 + np.floor(rng.random(d.shape) * (off - 1)).astype(np.int16), off)
    d2 = d - d1
    start = np.floor(rng.random(d.shape) * 24).astype(np.int16)
    h = np.arange(24, dtype=np.int16)
    x = (h - start[..., None]) % 24
    on = (x < d1[..., None]) | ((x >= (d1 + o1)[..., None]) & (x < (d1 + o1 + d2)[..., None]))
    return on


def sample_supply(bands: Mapping[str, float] | str | None, n_draws: int, n_days: int, rng: np.random.Generator,
                  params: ShortfallParams = PRIOR, timing: OutageTiming = OutageTiming()) -> np.ndarray:
    """Hourly grid availability, shape (n_draws, n_days * 24) bool."""
    hours, _ = sample_daily_hours(bands, n_draws, n_days, rng, params)
    return daily_pattern(hours, rng, timing).reshape(n_draws, n_days * 24)


# ---------------------------------------------------------------- calibration and T3

def monthly_average_hours(band: str, params: ShortfallParams, n: int = 20000, seed: int = 0) -> np.ndarray:
    """Distribution of a feeder's monthly average supply hours under the model (for intervals)."""
    rng = np.random.default_rng(seed)
    hours, _ = sample_daily_hours({band: 1.0}, n, 30, rng, params)
    return hours.mean(axis=1)


def model_interval(band: str, params: ShortfallParams, level: float = 0.90, n: int = 20000,
                   seed: int = 0) -> tuple[float, float]:
    a = (1 - level) / 2
    m = monthly_average_hours(band, params, n, seed)
    return float(np.quantile(m, a)), float(np.quantile(m, 1 - a))


def _fit_beta_mom(x: np.ndarray) -> tuple[float, float]:
    x = np.clip(np.asarray(x, dtype=float), 1e-4, 1 - 1e-4)
    m, v = x.mean(), x.var(ddof=1) if x.size > 1 else 0.0
    if x.size < 2 or v <= 0 or v >= m * (1 - m):
        conc = 10.0  # fallback concentration when the sample cannot identify it
    else:
        conc = m * (1 - m) / v - 1
    return float(m * conc), float((1 - m) * conc)


def calibrate_shortfall(shortfalls: pd.DataFrame, n_band_a_feeders: int | None = None, band: str = "A",
                        prior: ShortfallParams = PRIOR) -> ShortfallParams:
    """Fit the failing-feeder shortfall Beta by moments on f = 1 - measured / promised.

    `shortfalls` follows the runbook contract (`measured_avg_hours`, plus `band` if present; rows without a
    band are taken to be Band A, as NERC's compensation appendices cover Band A feeders). The Beta is fitted
    on rows with a measured value; p_meet = 1 - (all failing rows, measured or not) / `n_band_a_feeders`
    when that count is known, else the prior's.
    """
    df = shortfalls.copy()
    if "band" in df:
        df = df[df.band.fillna(band).str.upper() == band]
    n_failing = len(df)
    h = pd.to_numeric(df.measured_avg_hours, errors="coerce").dropna()
    promise = BAND_HOURS[band]
    h = h[(h >= 0) & (h < promise)]
    if h.empty:
        raise ValueError("no usable shortfall rows")
    a, b = _fit_beta_mom(1.0 - h.to_numpy() / promise)
    p_meet = prior.p_meet
    if n_band_a_feeders:
        p_meet = float(np.clip(1.0 - n_failing / n_band_a_feeders, 0.0, 0.99))
    return replace(prior, p_meet=p_meet, alpha=a, beta=b, calibrated=True,
                   note=f"calibrated on {len(h)} measured of {n_failing} failing Band {band} feeder rows"
                        + (f" out of {n_band_a_feeders} Band {band} rows" if n_band_a_feeders else ""))


def backtest_t3(shortfalls: pd.DataFrame, n_band_a_feeders: int | None = None, group: str = "disco",
                level: float = 0.90, target: float = 0.85, conditional: bool = True, widen: float = 1.0) -> dict:
    """PREREG T3, leave-one-group-out: fit on the other DisCos, test each held-out failing Band A feeder.

    Pass if at least `target` of measured average hours fall inside the model's `level` interval.
    conditional=True (primary): the interval of monthly average hours for a feeder that is failing that month
    (p_meet set to 0), which is the population the measured rows come from. conditional=False: the
    unconditional interval for any Band A feeder; when most feeders meet their promise it collapses to the
    promise itself and no failing feeder can fall inside it (reported as the second arm).
    """
    df = shortfalls.copy()
    df["_h"] = pd.to_numeric(df.measured_avg_hours, errors="coerce")
    df = df[df._h < BAND_HOURS["A"]].dropna(subset=["_h"])
    use_groups = group in df and df[group].nunique() > 1
    groups = df[group].fillna("?").unique() if use_groups else np.array(["all"])
    rows = []
    for g in groups:
        test = df[df[group].fillna("?") == g] if use_groups else df
        train_all = shortfalls[shortfalls[group].fillna("?") != g] if use_groups else shortfalls
        n_tr = None
        if n_band_a_feeders:
            n_tr = max(round(n_band_a_feeders * len(train_all) / max(len(shortfalls), 1)), len(train_all) + 1)
        params = calibrate_shortfall(train_all, n_tr)
        params = replace(params, alpha=params.alpha / widen, beta=params.beta / widen)
        if conditional:
            params = replace(params, p_meet=0.0)
        lo, hi = model_interval("A", params, level)
        for h in test._h:
            rows.append({"group": g, "measured": float(h), "lo": lo, "hi": hi, "inside": lo <= h <= hi})
    res = pd.DataFrame(rows)
    share = float(res.inside.mean()) if len(res) else float("nan")
    return {"n": len(res), "inside": int(res.inside.sum()) if len(res) else 0, "share": share,
            "target": target, "pass": bool(share >= target), "conditional": conditional, "widen": widen,
            "detail": res}


def widen_until_pass(shortfalls: pd.DataFrame, n_band_a_feeders: int | None = None, max_factor: float = 8.0,
                     target: float = 0.85, step: float = 1.25) -> dict:
    """PREREG failure rule for T3: widen the interval (divide both Beta parameters by a factor, which keeps the
    mean shortfall and lowers the concentration) until the leave-one-DisCo-out back-test passes.
    Returns the factor used (None if never reached) and the widened parameters fitted on all rows."""
    factor = 1.0
    while factor <= max_factor:
        bt = backtest_t3(shortfalls, n_band_a_feeders, target=target, widen=factor)
        if bt["pass"]:
            p = calibrate_shortfall(shortfalls, n_band_a_feeders)
            p = replace(p, alpha=p.alpha / factor, beta=p.beta / factor,
                        note=p.note + f"; interval widened x{factor:g} so the T3 back-test passes (PREREG rule)")
            return {"factor": factor, "share": bt["share"], "params": p}
        factor = round(factor * step, 4)
    return {"factor": None, "share": bt["share"], "params": None}


def calibrated_from_work(work_dir=None) -> tuple[ShortfallParams, dict]:
    """The supply parameters the product uses: calibrated on agent A's files and widened per the T3 rule.
    Falls back to the uncalibrated PRIOR (flagged) when the files are absent."""
    from . import paths

    sf = (work_dir or paths.WORK) / "nerc_shortfalls.parquet"
    rows = (work_dir or paths.WORK) / "nerc_rows.parquet"
    if not sf.exists():
        return PRIOR, {"calibrated": False}
    s = pd.read_parquet(sf)
    n_a = int((pd.read_parquet(rows).band == "A").sum()) if rows.exists() else None
    w = widen_until_pass(s, n_a)
    params = w["params"] or calibrate_shortfall(s, n_a)
    return params, {"calibrated": True, "widen_factor": w["factor"], "t3_share_after": w["share"],
                    "n_band_a_rows": n_a}


@dataclass(frozen=True)
class SupplyModel:
    shortfall: ShortfallParams = field(default_factory=lambda: PRIOR)
    timing: OutageTiming = field(default_factory=OutageTiming)
