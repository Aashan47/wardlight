"""Skip markers for tests that need the locally built data (shared by the agent tests)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # build/wardlight
WORK = ROOT / "data" / "work"
DATA_LOCAL = ROOT.parents[1] / "data-local"
HAS_WORK = all((WORK / f"{n}.parquet").exists() for n in ("facilities", "matches", "facility_results", "nerc_rows"))
HAS_NAIJA = (DATA_LOCAL / "naija-grid" / "caps_long.csv").exists()
HAS_NASA = (DATA_LOCAL / "nasa-power").exists()

needs_work = pytest.mark.skipif(not HAS_WORK, reason="data/work tables not built")
needs_naija = pytest.mark.skipif(not (HAS_WORK and HAS_NAIJA), reason="naija-grid or work tables not present")
needs_engine_data = pytest.mark.skipif(not (HAS_WORK and HAS_NASA), reason="NASA POWER or work tables not present")
