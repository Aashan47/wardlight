"""Clinic loads for the shared clinic system (never the vaccine fridge: PQS PV01.3 forbids other loads on a
PQS solar fridge system, so the vaccine fridge is always its own system).

Units, watts and hours per day: SEforALL Nigeria technology PDF p.10, Type 2 PHC load table (VERIFIED,
SOURCES-VERIFIED.md 3b row 6). Wattage ranges for comparison: Energizing Health Table 3.1, PDF p.99-100
(VERIFIED, 3a). The TIME OF DAY of each load is not in either source: the windows below are an ASSUMPTION,
editable, and place critical loads at night where possible (the conservative case for a battery).
Priority 1 is the brief's critical set: delivery room (procedure light, suction, fetal monitor), oxygen,
and interior lights.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

import numpy as np

SEFORALL_SRC = "SEforALL Nigeria technology PDF p.10, Type 2 PHC load table (SOURCES-VERIFIED.md 3b)"
SEFORALL_PDF_SRC = "SEforALL Nigeria technology PDF p.10 (data-local/reference-pdfs/seforall_Nigeria_technology_0.pdf)"
EH_SRC = "Energizing Health Table 3.1, PDF p.99-100 (SOURCES-VERIFIED.md 3a)"


@dataclass(frozen=True)
class Load:
    key: str
    name: str
    units: int
    watts: float
    hours_per_day: float
    priority: int
    start_hour: int  # ASSUMPTION: first hour of the daily window (local time)
    source: str = SEFORALL_SRC
    watts_range_eh: tuple[float, float] | None = None  # Energizing Health indicative range, if listed

    @property
    def wh_per_day(self) -> float:
        return self.units * self.watts * self.hours_per_day

    def hourly_kw(self) -> np.ndarray:
        """24-hour profile in kW. Fractional hours spread the last partial hour."""
        prof = np.zeros(24)
        full = int(np.floor(self.hours_per_day))
        frac = self.hours_per_day - full
        for i in range(full):
            prof[(self.start_hour + i) % 24] += 1.0
        if frac > 0:
            prof[(self.start_hour + full) % 24] += frac
        return prof * self.units * self.watts / 1000.0


SEFORALL_TYPE2_PHC: tuple[Load, ...] = (
    Load("gp_fridge", "General purpose refrigerator/freezer", 6, 130, 24, 2, 0, watts_range_eh=(40, 100)),
    Load("light_interior", "Lighting (interior)", 26, 10, 10, 1, 18, watts_range_eh=(10, 15)),
    Load("light_security", "Lighting (outdoor/security)", 4, 10, 10, 2, 18, watts_range_eh=(40, 240)),
    Load("fan", "Ceiling fan", 15, 50, 12, 3, 8),
    Load("oxygen", "Oxygen concentrator", 1, 200, 4, 1, 0, watts_range_eh=(70, 350)),
    Load("suction", "Suction apparatus", 1, 185, 5, 1, 19, watts_range_eh=(70, 180)),
    Load("procedure_light", "Procedure light", 2, 50, 4, 1, 20),
    Load("centrifuge", "Centrifuge", 1, 110, 2, 2, 9, watts_range_eh=(100, 200)),
    Load("microscope", "Electric microscope", 1, 30, 2, 2, 9, watts_range_eh=(20, 20)),
    Load("fetal_monitor", "Fetal heart monitor", 1, 3, 2, 1, 22, watts_range_eh=(1.5, 3)),
    Load("water_pump", "Water pump", 1, 746, 2, 3, 7),
    # Rows on the PDF page (data-local/reference-pdfs/seforall_Nigeria_technology_0.pdf p.10) that
    # SOURCES-VERIFIED.md 3b did not quote; with them the table sums to the printed total of 36,046 Wh.
    Load("laptop", "Computer (laptop)", 1, 60, 6, 3, 9, source=SEFORALL_PDF_SRC),
    Load("usb_modem", "USB Modem", 1, 2.5, 6, 3, 9, source=SEFORALL_PDF_SRC),
    Load("phones", "Mobile phones", 10, 10, 1, 3, 12, source=SEFORALL_PDF_SRC),
    Load("remote_monitoring", "Remote monitoring", 1, 5, 24, 2, 0, source=SEFORALL_PDF_SRC),
    Load("tv", "TV", 1, 100, 6, 3, 16, source=SEFORALL_PDF_SRC),
    Load("printer", "Printer", 1, 100, 2, 3, 10, source=SEFORALL_PDF_SRC),
    Load("ultrasound", "Portable ultrasound", 1, 28, 1, 2, 10, source=SEFORALL_PDF_SRC),
)
# Energizing Health lists "Laboratory refrigerator 40-100 W" for the closest analogue of the general purpose
# fridge; SEforALL's 130 W sits above it. Kept as printed by SEforALL.

CRITICAL_PRIORITY = 1


def by_key(loads: Iterable[Load] = SEFORALL_TYPE2_PHC) -> dict[str, Load]:
    return {ld.key: ld for ld in loads}


def daily_kwh(loads: Iterable[Load]) -> float:
    return sum(ld.wh_per_day for ld in loads) / 1000.0


def critical(loads: Iterable[Load] = SEFORALL_TYPE2_PHC, max_priority: int = CRITICAL_PRIORITY) -> list[Load]:
    return [ld for ld in loads if ld.priority <= max_priority]


def priority_profile(loads: Sequence[Load]) -> tuple[np.ndarray, np.ndarray]:
    """(priorities sorted ascending, kW profile per priority shape (P, 24))."""
    pr = sorted({ld.priority for ld in loads})
    prof = np.zeros((len(pr), 24))
    for ld in loads:
        prof[pr.index(ld.priority)] += ld.hourly_kw()
    return np.array(pr), prof


def edit(loads: Sequence[Load], changes: dict[str, dict]) -> list[Load]:
    """Return loads with per-key field changes, e.g. {'oxygen': {'hours_per_day': 8}}; unknown keys raise."""
    known = by_key(loads)
    for k in changes:
        if k not in known:
            raise KeyError(k)
    return [replace(ld, **changes.get(ld.key, {})) for ld in loads]


def from_dicts(items: Iterable[dict]) -> list[Load]:
    """Build loads from API input dicts (keys as the Load fields; source defaults to 'user input')."""
    out = []
    for d in items:
        d = dict(d)
        d.setdefault("source", "user input")
        d.setdefault("name", d.get("key", "load"))
        d.setdefault("units", 1)
        d.setdefault("start_hour", 18)
        if "watts_range_eh" in d and d["watts_range_eh"] is not None:
            d["watts_range_eh"] = tuple(d["watts_range_eh"])
        out.append(Load(**d))
    return out
