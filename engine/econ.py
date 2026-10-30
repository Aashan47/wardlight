"""Costs, diesel counterfactual, CO2 and payback. Every money figure is a range with a point default.

- Clinic system capex: SEforALL $/Wp (point 6.0, range 5.3 to 6.5, p.3 and p.16), which prices PV and storage
  together at SEforALL's bundle ratio of 7.2 kWh per kWp (p.11). A system with more battery per kWp than that
  is priced as if its PV matched its battery: kWp_priced = max(kWp, kWh / 7.2). The battery is never priced
  separately because no per-kWh price was verified.
- Fridge system capex: the PQS sheet price (Dulas SDD in EUR, includes the solar array; Haier in USD, 2021
  base). EUR is converted with EUR_TO_USD, an ASSUMPTION range.
- Life-cycle (SEforALL p.16): O&M 5% of capex a year, 15-year life, inverter and battery replacement at year 10
  costing 15% of capex. No discounting (stated).
- Diesel counterfactual: the energy the systems deliver while the grid is off, as if a generator had supplied
  it, at GEN_L_PER_KWH (UNVERIFIED placeholder range) and the diesel price range (NBS Oct 2024 to a
  news-reported May 2026 figure). CO2 2.697 kg/L (EPA, DERIVED).
- Naira at the CBN central rate of 27 Oct 2026, N1,352.371 per USD; the date travels with every conversion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import constants as C
from .fridge import CATALOGUE, FridgeModel


@dataclass(frozen=True)
class Range:
    point: float
    lo: float
    hi: float

    def __mul__(self, k: float) -> Range:
        a, b = self.lo * k, self.hi * k
        return Range(self.point * k, min(a, b), max(a, b))

    def __add__(self, o: Range) -> Range:
        return Range(self.point + o.point, self.lo + o.lo, self.hi + o.hi)

    def as_dict(self) -> dict:
        return asdict(self)


def crange(c: C.Const) -> Range:
    return Range(c.value, c.lo if c.lo is not None else c.value, c.hi if c.hi is not None else c.value)


def clinic_capex_usd(pv_kwp: float, battery_kwh: float) -> Range:
    if pv_kwp <= 0 and battery_kwh <= 0:
        return Range(0.0, 0.0, 0.0)
    kwp_priced = max(pv_kwp, battery_kwh / C.BATTERY_KWH_PER_KWP.value)
    return crange(C.COST_USD_PER_WP) * (kwp_priced * 1000.0)


def fridge_capex_usd(model: FridgeModel | str) -> Range | None:
    m = CATALOGUE[model] if isinstance(model, str) else model
    if m.price is None:
        return None
    if m.currency == "USD":
        return Range(m.price, m.price, m.price)
    if m.currency == "EUR":
        return crange(C.EUR_TO_USD) * m.price
    raise ValueError(m.currency)


def to_ngn(usd: Range) -> Range:
    return usd * C.FX_NGN_PER_USD.value


def lifecycle_usd(capex: Range) -> Range:
    """Total cost over the system life: capex + O&M + year-10 replacement (undiscounted)."""
    k = 1.0 + C.OM_FRACTION_PER_YEAR.value * C.SYSTEM_LIFE_YEARS.value + C.REPLACEMENT_FRACTION_Y10.value
    return capex * k


def monthly_cost_ngn(capex_usd: Range) -> Range:
    """Life-cycle cost spread over the life in months, in naira (the 'monthly cost' shown against diesel)."""
    return to_ngn(lifecycle_usd(capex_usd)) * (1.0 / (C.SYSTEM_LIFE_YEARS.value * 12.0))


def monthly_om_ngn(capex_usd: Range) -> Range:
    return to_ngn(capex_usd) * (C.OM_FRACTION_PER_YEAR.value / 12.0)


def diesel_litres_per_year(kwh_per_year: float) -> Range:
    return crange(C.GEN_L_PER_KWH) * kwh_per_year


def diesel_cost_ngn_per_month(litres_per_year: Range) -> Range:
    price = crange(C.DIESEL_NGN_PER_L)
    return Range(litres_per_year.point * price.point / 12.0, litres_per_year.lo * price.lo / 12.0,
                 litres_per_year.hi * price.hi / 12.0)


def co2_kg(litres: Range) -> Range:
    return litres * C.CO2_KG_PER_L_DIESEL.value


def payback_months(capex_ngn: Range, diesel_ngn_month: Range, om_ngn_month: Range) -> Range:
    """Months for the avoided diesel (net of O&M) to repay capex; inf when savings do not exceed O&M.

    lo pairs the cheapest system with the dearest diesel; hi the dearest system with the cheapest diesel.
    """
    def pb(cap: float, save: float, om: float) -> float:
        net = save - om
        return cap / net if net > 0 else float("inf")

    return Range(pb(capex_ngn.point, diesel_ngn_month.point, om_ngn_month.point),
                 pb(capex_ngn.lo, diesel_ngn_month.hi, om_ngn_month.lo),
                 pb(capex_ngn.hi, diesel_ngn_month.lo, om_ngn_month.hi))


@dataclass
class Economics:
    capex_usd: Range
    capex_ngn: Range
    monthly_cost_ngn: Range
    diesel_l_per_year: Range
    diesel_ngn_per_month: Range
    co2_kg_per_year: Range
    payback_months: Range
    fx_ngn_per_usd: float = C.FX_NGN_PER_USD.value
    fx_date: str = C.FX_DATE
    notes: tuple[str, ...] = (
        "diesel counterfactual: the energy the systems deliver while the grid is off, as if a generator had run",
        "generator litres per kWh is an UNVERIFIED placeholder range; diesel price range NBS Oct 2024 to May 2026 news",
        "undiscounted; SEforALL O&M 5%/yr, 15-year life, 15% replacement at year 10",
    )

    def to_dict(self) -> dict:
        return asdict(self)


def economics(clinic_kwp: float, clinic_kwh: float, fridge_model: str | None, offgrid_kwh_per_year: float) -> Economics:
    cap = clinic_capex_usd(clinic_kwp, clinic_kwh)
    if fridge_model:
        f = fridge_capex_usd(fridge_model)
        if f is not None:
            cap = cap + f
    cap_ngn = to_ngn(cap)
    litres = diesel_litres_per_year(offgrid_kwh_per_year)
    diesel_m = diesel_cost_ngn_per_month(litres)
    return Economics(cap, cap_ngn, monthly_cost_ngn(cap), litres, diesel_m, co2_kg(litres),
                     payback_months(cap_ngn, diesel_m, monthly_om_ngn(cap)))


def clinic_economics(pv_kwp: float, battery_kwh: float, offgrid_kwh_per_year: float,
                     diesel_plausible: bool) -> Economics:
    """The optional clinic-system line, priced on its own. Diesel is counted only where it is plausibly displaced:
    a grid-connected facility whose outages a backup generator would otherwise cover (common, not verified per
    facility). Off-grid or unknown-supply facilities count no diesel."""
    return economics(pv_kwp, battery_kwh, None, offgrid_kwh_per_year if diesel_plausible else 0.0)
