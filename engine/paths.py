"""Filesystem locations. Override with WARDLIGHT_DATA_LOCAL and WARDLIGHT_WORK."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]  # build/wardlight
DATA_LOCAL = Path(os.environ.get("WARDLIGHT_DATA_LOCAL", PROJECT.parents[1] / "data-local"))
WORK = Path(os.environ.get("WARDLIGHT_WORK", PROJECT / "data" / "work"))

NASA_POWER = DATA_LOCAL / "nasa-power"
WORLDPOP_TIF = DATA_LOCAL / "worldpop" / "nga_pop_2026_CN_100m_R2025A_v1.tif"
GRID3_GPKG = DATA_LOCAL / "grid3" / "grid3_nga_health_facilities_v3_0.gpkg"

MATCHES = WORK / "matches.parquet"
MATCHES_SYNTHETIC = WORK / "matches_SYNTHETIC.parquet"
FACILITIES = WORK / "facilities.parquet"
CATCHMENTS = WORK / "catchments.parquet"
NERC_SHORTFALLS = WORK / "nerc_shortfalls.parquet"
NERC_ROWS = WORK / "nerc_rows.parquet"
FACILITY_RESULTS = WORK / "facility_results.parquet"
PVGIS_CACHE = WORK / "pvgis_cache"
