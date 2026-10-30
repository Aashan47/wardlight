"""Vaccine fridge thermal model, from WHO PQS product sheets.

State: the cold reserve x, in hours of holdover at the PQS test ambient (43 degC). Capacity
x_max = h_PQS * k, where h_PQS is the printed holdover (to +10 degC) and k (HOLDOVER_TO_8C_FRACTION, an
ASSUMPTION range 0.5 to 1.0) is the share of it spent at or below +8 degC. k = 1 is the PQS upper bound.

Each hour:
- heat leak consumes leak(Ta) = max(Ta - T_set, 0) / (43 - T_set) hours of reserve (Newton cooling scaled
  to the test condition; at 43 degC it is exactly 1 h per hour, so holdover at 43 degC equals h_PQS * k);
- mains ice-lined fridge with power: the reserve rises by ICE_LINED_RECHARGE_H_PER_H (2 h per h, DERIVED
  from the PQS 8 h on / 16 h off test cycle) up to x_max; the compressor also covers the leak;
- solar direct drive (SDD): the array's energy that hour, divided by the fridge's hourly energy at 43 degC
  (E_24h / 24), is added to the reserve; the leak is subtracted. Array size is the PQS-minimum array:
  E_24h / (3.5 kWh/m2/day x PV performance), DERIVED from RF05.3 p.4.
A day counts as held at 2 to 8 degC when the reserve stays above zero in every hour of that day.
Freezing (below +2 degC) is not modelled: PQS Grade A freeze protection is assumed (stated on /method).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import constants as C


@dataclass(frozen=True)
class FridgeModel:
    code: str
    name: str
    kind: str  # "ice_lined_mains" | "sdd"
    holdover_h: float | None
    energy_kwh_24h: float | None  # continuous power energy as printed
    storage_l: float
    price: float | None
    currency: str | None
    price_year: int | None
    autonomy_h: float | None
    usable: bool
    source: str


def _src(code: str) -> str:
    return (f"WHO PQS product sheet {code}, p.1 (data-local/reference-pdfs/who_pqs_{code}.pdf); "
            "SOURCES-VERIFIED.md 1b")


def _hm(h: int, m: int) -> float:
    return h + m / 60.0


CATALOGUE: dict[str, FridgeModel] = {m.code: m for m in [
    FridgeModel("E003-089e", "Haier HBC-80", "ice_lined_mains", _hm(59, 51), 0.57, 61, 860, "USD", 2021, None, True,
                _src("E003-089e")),
    FridgeModel("E003-088e", "Haier HBC-150", "ice_lined_mains", _hm(60, 50), 0.54, 122, 999, "USD", 2021, None, True,
                _src("E003-088e")),
    FridgeModel("E003-087e", "Haier HBC-260", "ice_lined_mains", _hm(62, 14), 1.62, 211, 1283, "USD", 2021, None, True,
                _src("E003-087e")),
    FridgeModel("E003-097e", "Haier HBCD-90 (combined)", "ice_lined_mains", _hm(63, 48), 0.70, 30, 1575, "USD", 2021,
                None, True, _src("E003-097e")),
    FridgeModel("E003-120e", "Vestfrost VLS 174Ae AC", "ice_lined_mains", _hm(57, 52), 0.504, 38, None, None, None,
                None, True, _src("E003-120e")),
    FridgeModel("E003-040e", "Dulas VC200SDD", "sdd", _hm(90, 30), 0.50, 132, 5650, "EUR", 2026, _hm(79, 29), True,
                _src("E003-040e")),
    FridgeModel("E003-048e", "Dulas VC150SDD (combined)", "sdd", _hm(83, 42), 0.88, 102, 6995, "EUR", 2026,
                _hm(77, 57), True, _src("E003-048e")),
    # Printed continuous energy 5.0 and 78.0 kWh/24h are data-entry errors (SOURCES-VERIFIED 1b): excluded.
    FridgeModel("E003-059e", "Dulas VC88SDD", "sdd", _hm(90, 2), None, 88, 5440, "EUR", 2026, _hm(80, 10), False,
                _src("E003-059e") + "; excluded: printed energy 5.0 kWh/24h is a data-entry error"),
    FridgeModel("E003-084e", "Dulas VC60SDD (combined)", "sdd", _hm(94, 11), None, 57, 6065, "EUR", 2026,
                _hm(82, 48), False, _src("E003-084e") + "; excluded: printed energy 78.0 kWh/24h is a data-entry error"),
    FridgeModel("E003-129e", "Aucma TCD-100 (combined)", "sdd", 180.0, 1.41, 48, None, None, 2022, 180.0, True,
                _src("E003-129e") + "; holdover from the sheet's comments ('180 hours of holdover')"),
]}

DEFAULT_TODAY = "E003-088e"  # HBC-150: a mid-size mains ice-lined unit (user input; the facility's real unit is unknown)


@dataclass(frozen=True)
class ThermalParams:
    setpoint_c: float = C.CABINET_SETPOINT_C.value
    test_ambient_c: float = C.PQS_TEST_AMBIENT_C.value
    k_lo: float = C.HOLDOVER_TO_8C_FRACTION.lo  # type: ignore[assignment]
    k_hi: float = C.HOLDOVER_TO_8C_FRACTION.hi  # type: ignore[assignment]
    recharge_h_per_h: float = C.ICE_LINED_RECHARGE_H_PER_H.value
    ambient_scaling: bool = True


def leak_rate(t_amb_c: np.ndarray | float, p: ThermalParams = ThermalParams()) -> np.ndarray:
    """Hours of 43 degC holdover consumed per clock hour at ambient t_amb_c."""
    t = np.asarray(t_amb_c, dtype=float)
    if not p.ambient_scaling:
        return np.ones_like(t)
    return np.clip((t - p.setpoint_c) / (p.test_ambient_c - p.setpoint_c), 0.0, None)


def sample_k(n: int, rng: np.random.Generator, p: ThermalParams = ThermalParams()) -> np.ndarray:
    return rng.uniform(p.k_lo, p.k_hi, size=n)


def sdd_array_kwp(model: FridgeModel, pv_performance: float) -> float:
    """PQS-minimum array: just meets the fridge's daily energy at 3.5 kWh/m2/day (DERIVED, RF05.3 p.4)."""
    if model.energy_kwh_24h is None:
        raise ValueError(f"{model.code}: no usable energy figure")
    return model.energy_kwh_24h / (C.SDD_REF_IRRADIANCE_KWH_M2_DAY.value * pv_performance)


def simulate_ice_lined(powered: np.ndarray, leak: np.ndarray, x_max: np.ndarray,
                       p: ThermalParams = ThermalParams()) -> np.ndarray:
    """Mains ice-lined fridge. powered (L, T) bool; leak (L, T) or (T,); x_max (L,). Returns ok (L, T)."""
    L, T = powered.shape
    leak = np.broadcast_to(leak, (L, T))
    x = x_max.astype(float).copy()
    ok = np.empty((L, T), dtype=bool)
    r = p.recharge_h_per_h
    for t in range(T):
        x = np.where(powered[:, t], np.minimum(x + r, x_max), x - leak[:, t])
        x = np.maximum(x, 0.0)
        ok[:, t] = x > 0
    return ok


def simulate_sdd(pv_kwh: np.ndarray, energy_kwh_24h: float, leak: np.ndarray, x_max: np.ndarray) -> np.ndarray:
    """Solar direct drive. pv_kwh (L, T) array energy per hour; leak (L, T) or (T,); x_max (L,)."""
    L, T = pv_kwh.shape
    leak = np.broadcast_to(leak, (L, T))
    gain = pv_kwh / (energy_kwh_24h / 24.0)
    x = x_max.astype(float).copy()
    ok = np.empty((L, T), dtype=bool)
    for t in range(T):
        x = np.clip(x + gain[:, t] - leak[:, t], 0.0, x_max)
        ok[:, t] = x > 0
    return ok


def days_held(ok_hourly: np.ndarray) -> np.ndarray:
    """(L, T) hourly ok -> (L, T // 24) day held at 2 to 8 degC."""
    L, T = ok_hourly.shape
    return ok_hourly[:, : (T // 24) * 24].reshape(L, T // 24, 24).all(axis=2)
