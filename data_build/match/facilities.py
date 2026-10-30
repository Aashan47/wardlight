"""Build data/work/facilities.parquet from GRID3 Nigeria Health Facilities (CIESIN, CC BY 4.0).

- v3.0 for every state it covers (24 states), values as published;
- v2.0 for the states v3.0 does not cover (13 states), its columns mapped to the contract;
- a state comes wholly from one version, never both; `source_version` says which.

Column mapping for v2.0 (v2.0 has no settlement, functional status or quality flags):
    unique_id          "v2_" + globalid
    facility_name      facility_name
    facility_level     facility_level
    facility_type      facility_level_option   (same vocabulary as v3.0 facility_type, e.g. "Primary Health Center")
    facility_ownership ownership
    state_standard     state, spelled as v3.0 spells it (title case; FCT is "FCT, Abuja", v2.0 "Fct")
    lga_standard       lga
    ward_standard      ward
    settlement_name    "" (absent in v2.0)
    latitude, longitude
    functional         null (absent in v2.0)
    flag_count         null (absent in v2.0)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyogrio.raw

from . import paths
from .text import state_key

COLUMNS = [
    "unique_id", "facility_name", "facility_level", "facility_type", "facility_ownership", "state_standard",
    "lga_standard", "ward_standard", "settlement_name", "latitude", "longitude", "functional", "flag_count",
]
OUT_COLUMNS = [*COLUMNS, "source_version"]
V2_MAP = {
    "facility_name": "facility_name", "facility_level": "facility_level",
    "facility_type": "facility_level_option", "facility_ownership": "ownership", "lga_standard": "lga",
    "ward_standard": "ward", "latitude": "latitude", "longitude": "longitude",
}


def _read(gpkg: Path) -> pd.DataFrame:
    meta, _fids, _geom, fields = pyogrio.raw.read(str(gpkg), read_geometry=False)
    return pd.DataFrame({name: col for name, col in zip(meta["fields"], fields)})


def read_grid3(gpkg: Path = paths.GRID3_GPKG) -> pd.DataFrame:
    df = _read(gpkg)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"GRID3 v3.0 file lacks columns {missing}")
    out = df[COLUMNS].copy()
    out["latitude"] = pd.to_numeric(out["latitude"], errors="coerce")
    out["longitude"] = pd.to_numeric(out["longitude"], errors="coerce")
    out["flag_count"] = pd.to_numeric(out["flag_count"], errors="coerce").astype("Int64")
    out["source_version"] = "grid3_v3.0"
    # GRID3 v3.0 publishes 30 unique_id values twice or three times (61 rows, all without coordinates).
    # Rows are kept as published; matches.parquet keeps the first row of each id (docs/sources/match.md).
    out.attrs["duplicate_id_rows"] = int(out["unique_id"].duplicated(keep=False).sum())
    return out


def read_grid3_v2(gpkg: Path = paths.GRID3_V2_GPKG) -> pd.DataFrame:
    df = _read(gpkg)
    need = [*V2_MAP.values(), "globalid", "state"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"GRID3 v2.0 file lacks columns {missing}")
    out = pd.DataFrame({k: df[v] for k, v in V2_MAP.items()})
    out["unique_id"] = "v2_" + df["globalid"].astype(str)
    out["state_standard"] = df["state"].astype(str)
    out["settlement_name"] = ""
    out["functional"] = pd.Series([None] * len(df), dtype="object")
    out["flag_count"] = pd.array([pd.NA] * len(df), dtype="Int64")
    out["latitude"] = pd.to_numeric(out["latitude"], errors="coerce")
    out["longitude"] = pd.to_numeric(out["longitude"], errors="coerce")
    out["source_version"] = "grid3_v2.0"
    return out[OUT_COLUMNS]


def combine(v3: pd.DataFrame, v2: pd.DataFrame) -> pd.DataFrame:
    """v3.0 states whole, plus v2.0 states that v3.0 lacks, with v2.0 state names spelled as v3.0's."""
    v3_spelling = {state_key(s): s for s in v3["state_standard"].unique()}
    v2 = v2.copy()
    v2["_key"] = v2["state_standard"].map(state_key)
    add = v2[~v2["_key"].isin(v3_spelling)].copy()
    add["state_standard"] = add["state_standard"].str.strip()
    add = add.drop(columns="_key")
    out = pd.concat([v3[OUT_COLUMNS], add[OUT_COLUMNS]], ignore_index=True)
    by_state = out.groupby(out["state_standard"].map(state_key))["source_version"].nunique()
    if (by_state > 1).any():
        raise ValueError(f"states from two versions: {list(by_state[by_state > 1].index)}")
    if out["unique_id"][out["source_version"].eq("grid3_v2.0")].duplicated().any():
        raise ValueError("GRID3 v2.0 globalid is not unique")
    out.attrs["duplicate_id_rows"] = v3.attrs.get("duplicate_id_rows", 0)
    out.attrs["v2_states"] = sorted(add["state_standard"].unique())
    return out


def build(out: Path = paths.FACILITIES) -> pd.DataFrame:
    df = combine(read_grid3(), read_grid3_v2())
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


if __name__ == "__main__":
    d = build()
    print(f"facilities: {len(d)} rows, {d['unique_id'].nunique()} distinct ids, "
          f"{d.attrs['duplicate_id_rows']} rows share an id, "
          f"{d['latitude'].isna().sum()} without coordinates -> {paths.FACILITIES}")
    print(d.groupby("source_version").agg(rows=("unique_id", "size"), states=("state_standard", "nunique")))
    print("v2.0 states:", ", ".join(d.attrs["v2_states"]))
