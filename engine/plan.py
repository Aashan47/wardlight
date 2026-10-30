"""Funder ranking: which facilities to fund first under a budget.

Benefit per facility (choose one):
- "doses": doses protected per year gained (with system minus today), an ESTIMATE;
- "load_hours": critical load-hours restored per year = (critical uptime with - today) x 365 x critical
  load-hours per day (sum of hours of the priority-1 loads).
Score = benefit per naira of capex (point). Ties (common among facilities at the 20,000-person catchment cap)
break by larger uncapped demand, then lower uptime today, then lower cost, then id. Greedy by score until the
budget is spent. Facilities whose
supply is unknown (tier d, refused) have no "today" figure, so their gain is unknown: they are listed after
the ranked ones with that reason and never funded by the ranking.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import loads as LD

CRITICAL_LOAD_HOURS_PER_DAY = float(sum(ld.hours_per_day for ld in LD.critical()))


def benefit(df: pd.DataFrame, metric: str = "doses", outage_days: int = 7) -> pd.Series:
    if metric == "outage_hours":
        return df[f"out{outage_days}_hours_with"] - df[f"out{outage_days}_hours_today"]
    if metric == "doses":
        return df.doses_with_system - df.doses_protected_today
    if metric == "load_hours":
        lh = df.get("critical_load_hours_day", pd.Series(CRITICAL_LOAD_HOURS_PER_DAY, index=df.index))
        return (df.crit_uptime_with - df.crit_uptime_today) * 365.0 * lh
    raise ValueError(metric)


def rank(results: pd.DataFrame, budget_ngn: float, metric: str = "doses", state: str | None = None,
         facilities: pd.DataFrame | None = None, outage_days: int = 7) -> pd.DataFrame:
    df = results.copy()
    if state is not None:
        if "state" not in df and facilities is not None:
            df = df.merge(facilities[["unique_id", "state_standard"]].rename(columns={"state_standard": "state"}),
                          on="unique_id", how="left")
        df = df[df.state == state]
    df["benefit"] = benefit(df, metric, outage_days)
    # doses: the cold-chain fix's cost; load-hours: the optional clinic system's own cost; outage hours: both,
    # since both keep critical services running through the outage
    if metric == "outage_hours":
        df["cost_ngn"] = df.capex_ngn.astype(float) + df.get("clinic_capex_ngn", 0.0)
    else:
        cost_col = "clinic_capex_ngn" if metric == "load_hours" and "clinic_capex_ngn" in df else "capex_ngn"
        df["cost_ngn"] = df[cost_col].astype(float)
    cost = df.cost_ngn
    df["benefit_per_mngn"] = df.benefit / (cost / 1e6)
    known = df.benefit.notna() & (cost > 0)
    # deterministic order: benefit per naira, then (ties, e.g. facilities at the catchment cap) larger uncapped
    # demand (people beyond the cap still need doses), lower uptime today, lower cost, and finally the id
    k = df[known].copy()
    k["_demand"] = k["doses_demand_uncapped"] if "doses_demand_uncapped" in k else k.get("doses_per_year", 0.0)
    k["_today"] = k["uptime_today"].fillna(1.0) if "uptime_today" in k else 0.0
    k["_bpm"] = k.benefit_per_mngn.round(9)  # treat float noise as a tie
    ranked = k.sort_values(["_bpm", "_demand", "_today", "cost_ngn", "unique_id"],
                           ascending=[False, False, True, True, True], kind="mergesort")
    ranked = ranked.drop(columns=["_demand", "_today", "_bpm"])
    ranked["cum_cost_ngn"] = ranked.cost_ngn.cumsum()
    # greedy: skip a facility that does not fit and keep going down the list
    spent, funded = 0.0, []
    for c in ranked.cost_ngn.to_numpy():
        f = spent + c <= budget_ngn
        funded.append(f)
        spent += c if f else 0.0
    ranked["funded"] = funded
    ranked["rank"] = np.arange(1, len(ranked) + 1)
    unit = {"doses": "doses/yr protected", "load_hours": "critical load-hours/yr restored",
            "outage_hours": f"critical service-hours kept in a {outage_days}-day outage"}[metric]
    ranked["reason"] = [
        f"{b:,.0f} {unit} for N{c:,.0f} ({s:,.1f} per N1m); fridge held {ft:.0%} of days today (domestic-fridge "
        f"scenario), {fw:.0%} with the fix; tier {t}"
        for b, c, s, ft, fw, t in zip(ranked.benefit, ranked.cost_ngn, ranked.benefit_per_mngn, ranked.uptime_today,
                                      ranked.uptime_with_system, ranked.get("tier", pd.Series("?", index=ranked.index)))
    ]
    rest = df[~known].sort_values("unique_id", kind="mergesort").copy()
    rest["funded"] = False
    rest["rank"] = np.nan
    rest["reason"] = "not ranked: today's grid supply is unknown (refused match), so the gain cannot be computed"
    return pd.concat([ranked, rest], ignore_index=True)


def summary(ranked: pd.DataFrame, metric: str = "doses") -> dict:
    f = ranked[ranked.funded]
    return {"funded": len(f), "spent_ngn": float(f.cost_ngn.sum()), "benefit": float(f.benefit.sum()),
            "metric": metric, "candidates": int(ranked["rank"].notna().sum()),
            "not_ranked_unknown_supply": int(ranked["rank"].isna().sum())}
