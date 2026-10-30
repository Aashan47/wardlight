"""DisCo footprints and band mixtures from naija-grid (commit fcded18, data CC BY 4.0, credit NERC).

- A DisCo's footprint is every state that naija-grid's feeders.csv lists for it in any month (October 2022
  to October 2026), so a September 2026 NERC row can still be matched in a state that has since left the
  monthly cap orders.
- Tier (c) mixtures are the share of each band among the feeders in the October 2026 cap orders
  (caps_long.csv, order_month 2026-10), by state, or by state and business unit when a facility's LGA,
  ward or settlement name equals a business unit name in its state.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import paths
from .text import clean, state_key

BANDS = ["A", "B", "C", "D", "E"]
MIXTURE_MONTH = "2026-10"

# NERC file prefixes and other spellings, to naija-grid's DisCo codes.
DISCO_ALIASES = {
    "AEDC": "AEDC", "ABUJA": "AEDC",
    "BEDC": "BEDC", "BENIN": "BEDC",
    "EEDC": "EEDC", "ENUGU": "EEDC",
    "EKEDP": "EKEDC", "EKEDC": "EKEDC", "EKO": "EKEDC",
    "IBEDC": "IBEDC", "IBADAN": "IBEDC",
    "IE": "IKEDC", "IKEDC": "IKEDC", "IKEJA": "IKEDC",
    "JED": "JEDC", "JEDC": "JEDC", "JOS": "JEDC",
    "KAEDC": "KAEDC", "KADUNA": "KAEDC",
    "KEDCO": "KEDCO", "KANO": "KEDCO",
    "PHED": "PHED", "PORT HARCOURT": "PHED",
    "YEDC": "YEDC", "YOLA": "YEDC",
    "APLE": "APLE", "ABA": "APLE", "ABA POWER": "APLE",
}


def disco_code(disco: object, order_file: object = None) -> str | None:
    """naija-grid DisCo code from a row's disco field, else from the order file name's prefix."""
    for raw in (disco, order_file):
        if raw is None or (isinstance(raw, float) and math.isnan(raw)):
            continue
        s = str(raw).upper().strip()
        if s in DISCO_ALIASES:
            return DISCO_ALIASES[s]
        head = re.split(r"[_\-\s.]", s)[0]
        if head in DISCO_ALIASES:
            return DISCO_ALIASES[head]
    return None


@lru_cache(maxsize=1)
def _feeders(path: Path = paths.NAIJA_FEEDERS) -> pd.DataFrame:
    f = pd.read_csv(path, dtype=str)
    f["state_key"] = f["state"].map(state_key)
    f["bu_key"] = f["business_unit"].map(clean)
    return f


def disco_states() -> dict[str, set[str]]:
    f = _feeders()
    f = f[f["state_key"].ne("UNKNOWN") & f["state_key"].ne("")]
    return {d: set(g["state_key"]) for d, g in f.groupby("disco")}


@lru_cache(maxsize=1)
def october_feeders(path: Path = paths.NAIJA_CAPS) -> pd.DataFrame:
    """One row per feeder in the October 2026 cap orders, with state, business unit and band."""
    c = pd.read_csv(path, dtype=str, usecols=["feeder_id", "disco", "state", "order_month", "band"])
    c = c[c["order_month"].eq(MIXTURE_MONTH) & c["band"].isin(BANDS)].copy()
    c["state_key"] = c["state"].map(state_key)
    bu = _feeders()[["feeder_id", "bu_key", "business_unit"]]
    return c.merge(bu, on="feeder_id", how="left")


def _counts(df: pd.DataFrame) -> dict[str, int]:
    vc = df["band"].value_counts()
    return {b: int(vc.get(b, 0)) for b in BANDS}


def mixtures() -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    """(by state, by (state, business unit)) -> {'counts': {...}, 'weights': {...}, 'n': int, 'discos': [...]}"""
    o = october_feeders()

    def pack(g: pd.DataFrame) -> dict:
        cnt = _counts(g)
        n = sum(cnt.values())
        return {
            "counts": cnt,
            "weights": {b: round(v / n, 4) for b, v in cnt.items() if v} if n else {},
            "n": n,
            "discos": sorted(g["disco"].unique()),
            "business_unit": g["business_unit"].iloc[0] if "business_unit" in g and len(g) else None,
        }

    by_state = {s: pack(g) for s, g in o.groupby("state_key")}
    by_bu = {(s, b): pack(g) for (s, b), g in o.dropna(subset=["bu_key"]).groupby(["state_key", "bu_key"])}
    return by_state, by_bu
