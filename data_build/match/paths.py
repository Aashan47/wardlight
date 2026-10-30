"""File locations. Overridable with environment variables so tests and other machines can point elsewhere."""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # build/wardlight
DATA_LOCAL = Path(os.environ.get("WARDLIGHT_DATA_LOCAL", REPO.parents[1] / "data-local"))
WORK = Path(os.environ.get("WARDLIGHT_WORK", REPO / "data" / "work"))

GRID3_GPKG = DATA_LOCAL / "grid3" / "grid3_nga_health_facilities_v3_0.gpkg"
GRID3_V2_GPKG = DATA_LOCAL / "grid3-v2" / "NGA_health_facilities_v2_0.gpkg"
GRIDFINDER_GPKG = DATA_LOCAL / "gridfinder" / "grid.gpkg"
GRIDFINDER_TARGETS = DATA_LOCAL / "gridfinder" / "targets.tif"
NAIJA_FEEDERS = DATA_LOCAL / "naija-grid" / "feeders.csv"
NAIJA_CAPS = DATA_LOCAL / "naija-grid" / "caps_long.csv"

FACILITIES = WORK / "facilities.parquet"
FACILITY_GRID = WORK / "facility_grid.parquet"
NERC_ROWS = WORK / "nerc_rows.parquet"
MATCHES = WORK / "matches.parquet"
T2_SAMPLE = REPO / "docs" / "T2_SAMPLE.csv"

FIXTURE_ROWS = REPO / "tests" / "match" / "fixtures" / "bedc_sep2026_p12_rows.csv"
