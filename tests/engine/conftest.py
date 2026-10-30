import pytest

from engine import paths

HAS_NASA = (paths.NASA_POWER / "lat9_lon7_2021.json").exists()
HAS_GRID3 = paths.GRID3_GPKG.exists()

needs_nasa = pytest.mark.skipif(not HAS_NASA, reason="data-local/nasa-power not present")
needs_grid3 = pytest.mark.skipif(not (HAS_GRID3 and HAS_NASA), reason="data-local GRID3 or NASA POWER not present")
