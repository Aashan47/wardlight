"""Header-to-role mapping and value normalisation for the NERC feeder appendices."""

from __future__ import annotations

import re

# File-name prefix to the DisCo code used by naija-grid (data-local/naija-grid/feeders.csv), so the
# matcher can join on it.
DISCO_BY_PREFIX = {
    "AEDC": "AEDC",
    "APLE-MYTO": "APLE",
    "BEDC": "BEDC",
    "EEDC": "EEDC",
    "EKEDP": "EKEDC",
    "IBEDC": "IBEDC",
    "IE": "IKEDC",
    "JED": "JEDC",
    "KAEDC": "KAEDC",
    "KEDCO": "KEDCO",
    "PHED": "PHED",
    "YEDC": "YEDC",
}

ORDER_MONTH = {"APLE": "2025-02"}  # every other order is September 2026
DEFAULT_ORDER_MONTH = "2026-09"

BAND_HOURS = {"A": 20.0, "B": 16.0, "C": 12.0, "D": 8.0, "E": 4.0}

MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}


def disco_from_file(stem: str) -> str:
    prefix = stem.split("_")[0]
    return DISCO_BY_PREFIX.get(prefix, prefix)


def _norm(s: str) -> str:
    s = s.upper().replace("|", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def header_role(text: str) -> str | None:
    """Role of a column from its header text. Order matters: the most specific tests come first."""
    t = _norm(text)
    if not t:
        return None
    compact = re.sub(r"[^A-Z0-9/]", "", t)
    if compact in {"S/N", "SN", "S/NO", "SNO", "S/N0", "5/N", "S/IN", "SIN"} or compact.startswith("S/N"):
        return "sn"
    if "REMARK" in t:
        return "remark"
    if "PERFORMANCE" in t or re.search(r"\bAVE\b|\bAVG\b|AVERAGE", t) or re.search(r"\b1ST\b", t):
        return "measured"
    if "BAND" in t:
        return "band"
    if "STREET" in t or "AREAS" in t or "POPULAR" in t or "SERVED" in t:
        return "streets"
    if "LOCATION" in t or "DESCRIPTION" in t:
        return "location"
    if "MIN" in t or "DURATION" in t or "HRS" in t or "HOURS" in t:
        return "min_hours"
    if "FEEDER" in t or "NAME" in t:
        return "feeder_name"
    return None


def parse_band(text: str) -> str | None:
    t = _norm(text)
    t = re.sub(r"^BAND\s*", "", t)
    letters = re.findall(r"[A-Z]", t)
    if len(letters) == 1 and letters[0] in BAND_HOURS:
        return letters[0]
    return None


def parse_hours(text: str) -> float | None:
    """A number of hours, only when the whole cell is that number (so '2O' or '20 HRS?' stay unread)."""
    t = _norm(text).replace(",", ".").replace(" ", "").rstrip(".")
    if not re.fullmatch(r"\d{1,2}(?:\.\d{1,2})?", t):
        return None
    v = float(t)
    if not 0 <= v <= 24:
        return None
    return v


def parse_sn(text: str) -> int | None:
    t = _norm(text).strip(".,'` ")  # specks next to the number on the Aba scan read as '.5'
    if re.fullmatch(r"\d{1,4}", t):
        return int(t)
    return None


def parse_period(header: str, order_month: str) -> str:
    """'1ST - 21ST AUG PERFORMANCE' to '2026-08-01/2026-08-21'; the cleaned header when it does not parse."""
    t = _norm(header)
    m = re.search(r"(\d{1,2})\s*(?:ST|ND|RD|TH)?\s*[-~\u2013 ]+\s*(\d{1,2})\s*(?:ST|ND|RD|TH)?\s*([A-Z]{3})", t)
    m2 = re.search(r"\b([A-Z]{3})[A-Z]*\s*(\d{1,2})\s*(?:ST|ND|RD|TH)?\s*[-~\u2013 ]+\s*(\d{1,2})", t)
    if m and m.group(3) in MONTHS:
        d0, d1, mon = int(m.group(1)), int(m.group(2)), MONTHS[m.group(3)]
    elif m2 and m2.group(1) in MONTHS:  # 'AUGUST 1ST-21ST PERF' (BEDC)
        m = m2
        d0, d1, mon = int(m.group(2)), int(m.group(3)), MONTHS[m.group(1)]
    else:
        m = None
    if m and mon and 1 <= d0 <= d1 <= 31:
        year = int(order_month[:4])
        if mon > int(order_month[5:]):  # e.g. a December period quoted in a January order
            year -= 1
        return f"{year:04d}-{mon:02d}-{d0:02d}/{year:04d}-{mon:02d}-{d1:02d}"
    return t


def parse_action(remark: str, title: str = "") -> str | None:
    """compensation, downgrade, upgrade, joined with '+' when a remark orders more than one."""
    t = _norm(remark) or _norm(title)
    acts = []
    if "DOWNGRADE" in t:
        acts.append("downgrade")
    if re.search(r"\bUPGRADE", t):
        acts.append("upgrade")
    if "COMPENSAT" in t:
        acts.append("compensation")
    return "+".join(acts) if acts else None
