"""SYNTHETIC test tables (invented facilities, rows and results) for unit tests only. Never shown to a user."""

import json

import numpy as np
import pandas as pd

from agents.tools import Toolbox, WardlightData

ROW = "TEST_ORDER_September_2026.pdf"


def frames():
    fac = pd.DataFrame({
        "unique_id": ["T1", "T2", "T3", "T4", "T5", "L1"],
        "facility_name": ["Alpha PHC", "Beta Clinic", "Gamma PHC", "Delta Health Post", "Epsilon PHC", "Lagos One"],
        "facility_level": ["Primary", "Primary", "Secondary", "Primary", "Primary", "Primary"],
        "facility_type": ["Primary Health Center"] * 6, "facility_ownership": ["Public"] * 6,
        "state_standard": ["Kano", "Kano", "Kano", "Kano", "Kano", "Lagos"],
        "lga_standard": ["Gwale", "Gwale", "Fagge", "Fagge", "Gwale", "Ikeja"],
        "ward_standard": ["W1", "W2", "W3", "W4", "W5", "W6"], "settlement_name": [""] * 6,
        "latitude": [12.0, 12.01, 12.02, 12.03, 12.04, 6.6], "longitude": [8.5, 8.51, 8.52, 8.53, 8.54, 3.3],
        "functional": ["Functional"] * 6, "flag_count": [0] * 6, "source_version": ["grid3_v3.0"] * 6})
    ev = {"order_file": ROW, "page": 3, "sn": "7", "row_text": "TEST FEEDER | GWALE | ALPHA PHC", "band": "B"}
    matches = pd.DataFrame({
        "unique_id": ["T1", "T2", "T3", "T4", "T5", "L1"],
        "tier": ["a_named", "b_place", "c_lga_mixture", "offgrid", "d_refused", "d_refused"],
        "bands": [json.dumps({"B": 1.0}), json.dumps({"E": 1.0}), json.dumps({"B": 0.5, "D": 0.5}), "{}", "{}", "{}"],
        "feeder_ids": [json.dumps([f"{ROW}#p3#sn7"]), json.dumps([f"{ROW}#p3#sn8"]),
                       json.dumps([f"{ROW}#p3#sn7", f"{ROW}#p3#sn9"]), "[]", "[]", "[]"],
        "evidence": [json.dumps(ev), json.dumps({**ev, "sn": "8", "band": "E"}), json.dumps({"source": "rows in LGA"}),
                     json.dumps({"source": "Gridfinder"}), json.dumps({"source": "state regulator"}),
                     json.dumps({"source": "state regulator"})],
        "grid_km": [0.1, 0.2, 0.3, 9.0, 0.4, 0.5],
        "reason": ["facility named in the NERC row", "ward named", "LGA mixture over 2 rows", "far from grid",
                   "state regulator", "state regulator"]})
    res = pd.DataFrame({
        "unique_id": ["T1", "T2", "T3", "T4", "T5"],
        "tier": ["a_named", "b_place", "c_lga_mixture", "offgrid", "d_refused"],
        "uptime_today": [0.5, 0.0, 0.2, 0.0, np.nan], "uptime_today_lo": [0.4, 0.0, 0.1, 0.0, np.nan],
        "uptime_today_hi": [0.6, 0.0, 0.3, 0.0, np.nan],
        "uptime_with_system": [0.99, 0.95, 0.97, 0.96, 0.96],
        "doses_per_year": [1000.0, 2000.0, 1500.0, 800.0, 900.0],
        "doses_protected_today": [500.0, 0.0, 300.0, 0.0, np.nan],
        "doses_with_system": [990.0, 1900.0, 1455.0, 768.0, 864.0],
        "crit_uptime_today": [0.5, 0.0, 0.2, 0.0, np.nan], "crit_uptime_with": [1.0, 1.0, 1.0, 1.0, 1.0],
        "capex_ngn": [1_000_000.0, 2_000_000.0, 1_500_000.0, 3_000_000.0, 1_000_000.0],
        "capex_ngn_lo": [1e6] * 5, "capex_ngn_hi": [1e6] * 5,
        "system_fridge": [json.dumps({"kind": "PQS solar direct drive, dedicated (no other loads)"})] * 5,
        "system_clinic": [json.dumps({"pv_kwp": 1.0, "battery_kwh": 7.2})] * 5,
        "priority_score": [490.0, 950.0, 770.0, 256.0, np.nan]})
    nerc = pd.DataFrame({
        "disco": ["KEDCO"] * 3, "order_file": [ROW] * 3, "order_month": ["2026-09"] * 3, "page": [3, 3, 3],
        "sn": [7, 8, 9], "band": ["B", "E", "D"], "feeder_name": ["11KV TEST ONE", "11KV TEST TWO", "11KV TEST THREE"],
        "location": ["GWALE", "GWALE", "FAGGE"], "streets": ["ALPHA PHC", "BETA ROAD", "GAMMA ROAD"],
        "min_hours": [16.0, 4.0, 8.0], "ocr_confidence": [0.9] * 3, "crop_path": ["c1.png", "c2.png", "c3.png"]})
    bh = pd.DataFrame({"feeder_id": ["f1"], "disco": ["KEDCO"], "state": ["KANO"], "feeder_raw": ["11KV TEST ONE"],
                       "2026-08": ["A"], "2026-09": ["A"], "2026-10": ["B"]})
    return fac, matches, res, nerc, bh


def data() -> WardlightData:
    fac, m, r, n, bh = frames()
    return WardlightData(facilities=fac, matches=m, results=r, nerc_rows=n, band_history=bh)


def toolbox() -> Toolbox:
    return Toolbox(data())
