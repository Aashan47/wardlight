"""Every constant the engine uses, with its source and status.

Status values follow `SOURCES-VERIFIED.md` in the project research-raw folder ("SV" below):
VERIFIED, VERIFIED_SECONDARY, DERIVED (arithmetic on verified rows), and ASSUMPTION (no source; a
modelling choice). An ASSUMPTION or UNVERIFIED value is always a labelled range with a default that the
user can change, never a point presented as fact. `docs/sources/engine.md` is generated from this
registry plus prose, and `tests/engine/test_constants.py` enforces the rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["VERIFIED", "VERIFIED_SECONDARY", "DERIVED", "UNVERIFIED", "ASSUMPTION"]


@dataclass(frozen=True)
class Const:
    """A sourced value. `lo`/`hi` are required when status is UNVERIFIED or ASSUMPTION."""

    value: float
    unit: str
    source: str
    status: Status
    lo: float | None = None
    hi: float | None = None
    note: str = ""

    @property
    def is_range(self) -> bool:
        return self.lo is not None and self.hi is not None


SV = "SOURCES-VERIFIED.md"

# ---------------------------------------------------------------- vaccine cold chain (SV section 1)
RANGE_LO_C = Const(2.0, "degC", f"{SV} 1a row 1, PQS E003/RF05.3 p.3 and RF03-VP.2 p.2", "VERIFIED")
RANGE_HI_C = Const(8.0, "degC", f"{SV} 1a row 1, PQS E003/RF05.3 p.3 and RF03-VP.2 p.2", "VERIFIED")
HOLDOVER_LIMIT_C = Const(
    10.0, "degC", f"{SV} 1a rows 3-4: holdover is measured to +10 degC, not +8", "VERIFIED",
    note="Hence PQS holdover is an upper bound on time held at or below +8 degC.",
)
PQS_TEST_AMBIENT_C = Const(43.0, "degC", f"{SV} 1a rows 6 and 8 and 1b header: hot zone test at 43 degC", "VERIFIED")
ICE_LINED_RECHARGE_H_PER_H = Const(
    2.0, "holdover-h per powered h",
    f"{SV} 1a row 7: PQS RF03-VP.2 p.8 passes ice-lined units on a 16 h off / 8 h on cycle, so 8 h of power "
    "restores at least 16 h of holdover",
    "DERIVED",
    note="A lower bound implied by the PQS test cycle; real recharge may be faster.",
)
SDD_REF_IRRADIANCE_KWH_M2_DAY = Const(
    3.5, "kWh/m2/day",
    "PQS E003/RF05.3 p.4 (data-local/reference-pdfs/who_pqs_E003_RF05.3.pdf): 'must fully meet the stated "
    "performance requirements with a minimum solar radiation reference period of 3.5 kWh/m2/day'; also printed "
    f"on every Dulas sheet ({SV} 1b)",
    "VERIFIED",
)
SDD_ARRAY_W_RANGE = Const(
    330.0, "W", f"{SV} 3a row 4, Energizing Health Table 3.1 PDF p.99-100: SDD array 160-500 W", "VERIFIED",
    lo=160.0, hi=500.0, note="Used only as a plausibility check on the derived array size.",
)
PQS_SOLAR_NO_OTHER_LOADS = (
    f"{SV} 1a row 12, PQS E003/PV01.3 p.4: 'No additional loads, such as lighting or pumping, are to be "
    "connected to the solar power system.'"
)

# Model assumption: the share of PQS holdover (to +10 degC) spent at or below +8 degC.
HOLDOVER_TO_8C_FRACTION = Const(
    0.75, "fraction", "no published figure; PQS holdover is to +10 degC", "ASSUMPTION", lo=0.5, hi=1.0,
    note="Sampled uniformly per simulation lane between lo and hi; hi = 1.0 is the PQS upper bound.",
)
CABINET_SETPOINT_C = Const(
    5.0, "degC", "midpoint of the PQS 2-8 degC range (SV 1a row 1)", "ASSUMPTION", lo=4.0, hi=6.0,
    note="Only enters the ambient scaling of heat leak.",
)

# ---------------------------------------------------------------- doses (SV section 2)
CRUDE_BIRTH_RATE_PER_1000 = Const(
    32.493, "births per 1,000 per year", f"{SV} 2 row 4, World Bank SP.DYN.CBRT.IN, 2024, CC BY 4.0", "VERIFIED"
)
DOSES_PER_CHILD_Y1 = Const(
    20.0, "doses",
    f"{SV} 2, DERIVED row under the schedule table, from the NPHCDA FHIR IG (an unofficial CI build)",
    "VERIFIED_SECONDARY", lo=20.0, hi=23.0,
    note="20 without malaria vaccine, 23 with; labelled as from an unofficial guide.",
)
PHC_TYPE2_SERVES = Const(
    15000.0, "people", f"{SV} 3b row 7, SEforALL Nigeria technology PDF p.11: 'Serving between 10,000 to 20,000 people'",
    "VERIFIED", lo=10000.0, hi=20000.0, note="Used only as a sanity check on WorldPop catchments.",
)
CATCHMENT_RADIUS_KM = Const(
    5.0, "km", "no source opened; a modelling choice for the catchment rule", "ASSUMPTION", lo=3.0, hi=10.0,
    note="Population further than this from every facility is left unassigned and reported.",
)

# ---------------------------------------------------------------- grid supply
BAND_MIN_HOURS: dict[str, float] = {"A": 20.0, "B": 16.0, "C": 12.0, "D": 8.0, "E": 4.0}
BAND_HOURS_SOURCE = (
    "Band A 20 h: NERC APLE order Feb 2025 p.5 s.10(g) ('supply is less than an average of 20 hours' triggers "
    "compensation; data-local/nerc/APLE-MYTO_-FEB-2025_014.pdf) and naija-grid README line 9. Band C 12 h: "
    "BEDC order row 108 quoted in 06-PRODUCT-DESIGN.md. Bands B 16, D 8, E 4: the 'min. supply duration' column of "
    "the NERC feeder appendices (MANIFEST.md section 3); confirmed per band by engine.supply.band_hours_from_rows() "
    "once agent A's nerc_rows.parquet exists. Status: PARTLY VERIFIED (A, C); B, D, E pending that check."
)
ES_OUTAGES_PER_MONTH = Const(
    32.8, "outages per month", f"{SV} 3c row 1, World Bank Enterprise Survey IC.FRM.INFRA.IN2, Nigeria 2014", "VERIFIED"
)
ES_OUTAGE_HOURS = Const(
    11.6, "hours per outage", f"{SV} 3c row 2, World Bank Enterprise Survey IC.FRM.INFRA.IN3_C, Nigeria 2014", "VERIFIED"
)
DAYS_PER_MONTH = Const(30.4375, "days", "calendar average (365.25 / 12)", "DERIVED")

# ---------------------------------------------------------------- loads and system cost (SV section 3)
SEFORALL_TYPE2_DAILY_WH = Const(
    36046.0, "Wh/day", f"{SV} 3b row 6, SEforALL Nigeria technology PDF p.10 load table 'Total 36,046'", "VERIFIED"
)
SEFORALL_PV_KWP = Const(
    7.5, "kWp", f"{SV} 3b row 4, SEforALL technology PDF p.11: 'Between 5kWp to 10kWp'", "VERIFIED", lo=5.0, hi=10.0
)
SEFORALL_BATTERY_KWH = Const(
    54.0, "kWh", f"{SV} 3b row 4, SEforALL technology PDF p.11: 'Between 36kWh and 72kWh'", "VERIFIED", lo=36.0, hi=72.0
)
BATTERY_KWH_PER_KWP = Const(
    7.2, "kWh per kWp", "DERIVED from SEforALL p.11: 36/5 = 72/10 = 7.2", "DERIVED",
    note="The ratio at which SEforALL's $/Wp bundles PV and storage.",
)
COST_USD_PER_WP = Const(
    6.0, "USD/Wp", f"{SV} 3b rows 1-2, SEforALL technology PDF p.3 ($6/Wp) and p.16 ($5.3 to $6.5/Wp)", "VERIFIED",
    lo=5.3, hi=6.5,
)
OM_FRACTION_PER_YEAR = Const(0.05, "of capex per year", f"{SV} 3b row 3, SEforALL p.16", "VERIFIED")
SYSTEM_LIFE_YEARS = Const(15.0, "years", f"{SV} 3b row 3, SEforALL p.16", "VERIFIED")
REPLACEMENT_FRACTION_Y10 = Const(0.15, "of capex, year 10", f"{SV} 3b row 3, SEforALL p.16", "VERIFIED")

# Battery behaviour: no verified source; labelled assumptions with ranges.
BATTERY_USABLE_FRACTION = Const(
    0.8, "fraction of nameplate", "no source opened", "ASSUMPTION", lo=0.5, hi=0.9,
)
BATTERY_ROUND_TRIP_EFF = Const(0.9, "fraction", "no source opened", "ASSUMPTION", lo=0.8, hi=0.95)
BATTERY_GRID_CHARGE_C_RATE = Const(
    0.2, "fraction of nameplate per hour", "no source opened", "ASSUMPTION", lo=0.1, hi=0.5,
)

SHED_RESERVE = Const(
    0.5, "fraction of usable battery", "no source opened; a dispatch rule", "ASSUMPTION", lo=0.3, hi=0.7,
    note="Loads below priority 1 may only draw the battery above this share of usable capacity.",
)

# PV model: no verified source; labelled assumptions with ranges (checked against PVGIS by T4).
PV_SYSTEM_LOSS = Const(0.14, "fraction", "no source opened; PVGIS uses 14 as its form default", "ASSUMPTION",
                       lo=0.10, hi=0.20)
PV_TEMP_COEFF_PER_C = Const(-0.004, "per degC", "no source opened", "ASSUMPTION", lo=-0.005, hi=-0.003)
PV_NOCT_C = Const(45.0, "degC", "no source opened", "ASSUMPTION", lo=42.0, hi=48.0)

# ---------------------------------------------------------------- money, fuel, CO2 (SV sections 4-5)
FX_NGN_PER_USD = Const(
    1352.371, "NGN per USD", f"{SV} 5 row 1, CBN central rate 27 Oct 2026", "VERIFIED",
    note="Store the date with every conversion: rates moved 2.5% in one week.",
)
FX_DATE = "2026-10-27"
DIESEL_NGN_PER_L = Const(
    1441.28, "NGN per litre",
    f"{SV} 4 rows 1-2: lo = NBS Oct 2024 (VERIFIED, two years old); hi = N3,277.47 May 2026, news-reported only "
    "(UNVERIFIED)",
    "UNVERIFIED", lo=1441.28, hi=3277.47,
    note="Point default is the newest NBS-hosted price; the range is what is shown.",
)
GEN_L_PER_KWH = Const(
    0.378, "litres per kWh",
    f"{SV} 4 row 10: vendor chart, 20 kW set, 0.303 L/kWh at full load to 0.454 at 1/4 load (DERIVED, low grade); "
    "no published figure for 5-10 kVA",
    "UNVERIFIED", lo=0.303, hi=0.454,
    note="Placeholder range; a small clinic set likely sits at or above the high end.",
)
CO2_KG_PER_L_DIESEL = Const(2.697, "kg CO2 per litre", f"{SV} 4 row 6, EPA 10.21 kg/gal / 3.785 L/gal", "DERIVED")
EUR_NGN_CBN = Const(
    1508.0289, "NGN per EUR",
    "CBN central rate for EURO on the same rate date as the USD row of SV 5 "
    "(https://www.cbn.gov.ng/api/GetAllExchangeRates, record id 65267, centralrate '1508.0289'; the USD record "
    "id 65274 in the same response reads centralrate '1352.3710', matching SV 5)",
    "VERIFIED",
)
EUR_TO_USD = Const(
    1508.0289 / 1352.3710, "USD per EUR", "DERIVED: CBN EUR central / CBN USD central, same rate date", "DERIVED",
    note="Only converts the Dulas SDD prices, which PQS prints in EUR.",
)

# ---------------------------------------------------------------- baseline equipment and availability
DOMESTIC_HOLDOVER_H = Const(
    4.0, "hours at 2 to 8 degC without power",
    "Chojnacky and Rodriguez (NIST), 'Effect of thermal ballast loading on temperature stability of domestic "
    "refrigerators used for vaccine storage', PLOS ONE, DOI 10.1371/journal.pone.0235777, CC0 (full text via "
    "Europe PMC PMC7343171): 'maintaining vaccine temperatures between 2 degC and 8 degC for 4 to 6 hours without "
    "power' (10 to 15% water ballast); 'a less-cumbersome 10% ballast load can be expected to provide about 4 hours'; "
    "in the shelf-material tests 'vaccines experienced too-warm temperature excursions within the first 1.5 hours "
    "of the outage period'",
    "VERIFIED", lo=1.5, hi=6.0,
    note="Laboratory tests of two US domestic units; test-room ambient not stated in the text read, so no ambient "
         "scaling is applied and the figure is probably generous for a hot clinic.",
)
DOMESTIC_RECOVERY_H = Const(
    1.0, "powered hours to restore full reserve", "no source opened; a domestic unit has no ice lining to refreeze",
    "ASSUMPTION", lo=0.5, hi=2.0,
)
EQUIPMENT_AVAILABILITY = Const(
    0.95, "share of days the fridge is in working order",
    "SCENARIO VALUE, no verified source: covers breakdowns, waiting for spare parts and technicians",
    "ASSUMPTION", lo=0.90, hi=0.99,
    note="Sampled per lane and applied to every fridge scenario, today and with the fix. Field functionality "
         "data were searched for and not verified.",
)
SDD_SOILING_FACTOR = Const(
    0.95, "share of clean-array output", "SCENARIO VALUE, no verified source: dust and shading on the SDD array",
    "ASSUMPTION", lo=0.90, hi=1.0,
)
FRIDGE_LIFE_YEARS = Const(
    10.0, "years",
    "PQS E003/RF05.3 p.8 s.4.9 (data-local/reference-pdfs/who_pqs_E003_RF05.3.pdf): SDD 'designed to achieve a "
    "low-maintenance life of not less than 10 years'; the same figure is used for ice-lined units as a scenario value",
    "VERIFIED",
)
CATCHMENT_CAP_POP = Const(
    20000.0, "people per facility",
    f"{SV} 3b row 7, SEforALL technology PDF p.11: a Type 2 PHC serves 'between 10,000 to 20,000 people'; the upper "
    "end caps every facility's catchment",
    "VERIFIED", lo=10000.0, hi=20000.0,
    note="Applied to all facility levels (a scenario choice for hospitals); population above the cap is reported.",
)

# ---------------------------------------------------------------- registry
REGISTRY: dict[str, Const] = {
    name: val for name, val in dict(globals()).items() if isinstance(val, Const)
}
