"""Read the feeder tables on one rendered page into records.

A record is one feeder row: the grid rows covered by one S/N cell. Cells that span several records
(a shared location, for instance) give their text to each record they cover; the raw text of every
cell is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import ocr as O
from .grid import Cell, Table, binarize, deskew, find_tables, line_masks
from .schema import header_role, parse_band, parse_sn

KEY_ROLES = ("sn", "band", "feeder_name", "min_hours")
NUM_ROLES = ("sn", "min_hours", "measured")


@dataclass
class Record:
    table_idx: int
    kind: str  # "service_level" or "shortfall"
    title: str
    roles: dict[str, str]  # role -> header text
    raw: dict[str, str]  # role -> raw OCR text
    conf: dict[str, float]
    row_box: tuple[int, int, int, int]
    grid_rows: tuple[int, int]
    extra: dict = field(default_factory=dict)


@dataclass
class PageResult:
    file_stem: str
    page: int
    skew_deg: float
    records: list[Record]
    tables_seen: int
    notes: list[str]
    image: np.ndarray | None = None  # deskewed page, for crops


def _cell_cfg(role: str | None) -> str:
    if role in ("sn",):
        return O.DIGITS_CFG
    if role in ("min_hours", "measured"):
        return O.DIGITS_CFG
    if role == "band":
        return O.LINE_CFG
    return O.TEXT_CFG


def _read_cell(gray, lines, cell, role, cache):
    key = (cell.r0, cell.r1, cell.c0, cell.c1, role)
    if key in cache:
        return cache[key]
    img = O.clean_cell(gray, lines, cell.box)
    cfg = _cell_cfg(role)
    text, conf = O.ocr_text(img, cfg) if cfg == O.TEXT_CFG else O.ocr(img, cfg)
    if role == "band" and parse_band(text) is None and img is not None:
        # single-character pass with the band letters only
        t2, c2 = O.ocr(img, O.CHAR_CFG)
        if parse_band(t2) is not None:
            text, conf = t2, c2
    if role in NUM_ROLES and img is not None:
        # a plain read too: the digit template bank learns only from cells where both reads agree
        plain, pconf = O.ocr(img, O.LINE_CFG)
        cache[("num",) + key] = (img, text, plain)
        if not text or sum(ch.isalpha() for ch in plain) >= 3:
            # empty digit read, or a worded cell such as "AFFECTED BY LOW GENERATION" (PHED p11),
            # where the digit whitelist would turn letters into numbers: keep the plain read
            text, conf = plain, pconf
    if role in ("feeder_name", "location", "streets", "remark") and img is not None:
        h = img.shape[0]
        if h < 90 and not text:
            text, conf = O.ocr(img, O.LINE_CFG)
    cache[key] = (text, conf)
    return text, conf


def _title_above(gray: np.ndarray, t: Table, prev_bottom: int) -> str:
    x0, y0, x1, _ = t.bbox
    top = max(prev_bottom + 5, y0 - 260, 0)
    if y0 - top < 25:
        return ""
    strip = gray[top:y0 - 3, x0:x1]
    if (strip < 160).sum() < 50:
        return ""
    text, _ = O.ocr(np.pad(strip, 10, constant_values=255), O.TEXT_CFG, caps=False)
    return text


CONFUSABLE = set("ILOAT|![]()")  # letters tesseract gives for digits in this font ('41' -> 'AI')


def _header_rows(t: Table, gray, lines, cache) -> int:
    """Number of leading grid rows that are header: rows before the first numeric S/N cell.

    A row is data when the first-column cell reads as a number with the digit whitelist and its plain
    read has no letters beyond digit look-alikes. Two earlier rules failed: a plain-read number test
    lost rows whose '1' read as 'I'; a header-keyword test ate first data rows whose streets held words
    such as STREET (JEDC p14, PHED p14 and p17).
    """
    for r in range(min(4, t.n_rows)):
        cell = t.cell_at(r, 0)
        if cell is None or cell.r0 != r:
            continue
        plain = _read_cell(gray, lines, cell, None, cache)[0].upper()
        digits = _read_cell(gray, lines, cell, "sn", cache)[0]
        letters = {ch for ch in plain if ch.isalpha() or ch in "|![]()"}
        if parse_sn(digits) is not None and plain and letters <= CONFUSABLE:
            return max(r, 1)
    return 1


def _split_sn_cell(gray, t: Table, sc, r0: int, virtual: set[int]) -> list[tuple[int, int]]:
    """Grid-row spans of the records inside one S/N cell.

    Usually one span. When the rule between two rows is drawn in only some columns (EEDC p16, S/N 202
    and 203, ruled in the hours column only), the S/N cell covers two numbers. Split it at an internal
    grid boundary when the S/N column is blank across that boundary and has ink above and below it;
    a single number spanning merged rows has ink across the boundary, or on one side only.
    """
    x0, _, x1, _ = sc.box
    spans, start = [], r0
    for k in range(r0 + 1, sc.r1 + 1):
        y = t.ys[k]
        band = gray[y - 4:y + 5, x0 + 6:x1 - 6]
        above = gray[t.ys[start] + 4:y - 4, x0 + 6:x1 - 6]
        below = gray[y + 5:t.ys[sc.r1 + 1] - 4, x0 + 6:x1 - 6]
        if band.size and (band < 160).sum() < 3 and (above < 160).sum() > 20 and (below < 160).sum() > 20:
            spans.append((start, k - 1))
            virtual.add(k)
            start = k
    spans.append((start, sc.r1))
    return spans


def _clip(t: Table, cell, r0: int, r1: int, virtual: set[int]):
    """A cell clipped to rows r0..r1 where it crosses a virtual boundary; the cell itself otherwise."""
    a, b = cell.r0, cell.r1
    if a < r0 and r0 in virtual:
        a = r0
    if b > r1 and (r1 + 1) in virtual:
        b = r1
    if (a, b) == (cell.r0, cell.r1):
        return cell
    x0, _, x1, _ = cell.box
    return Cell(a, b, cell.c0, cell.c1, (x0, t.ys[a], x1, t.ys[b + 1]))


def read_page(path: Path, prev_roles: dict | None = None) -> PageResult:
    stem = path.stem.rsplit("_p", 1)[0]
    page = int(path.stem.rsplit("_p", 1)[1])
    g0 = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    gray, ang = deskew(g0)
    tables = find_tables(gray)
    hmask, vmask = line_masks(binarize(gray))
    lines = cv2.bitwise_or(hmask, vmask)
    notes: list[str] = []
    records: list[Record] = []
    prev_bottom = 0
    for ti, t in enumerate(tables):
        cache: dict = {}
        # header text per column (all header cells covering it, top to bottom)
        nh = _header_rows(t, gray, lines, cache)
        col_header: list[str] = []
        for c in range(t.n_cols):
            parts = []
            for r in range(nh):
                cell = t.cell_at(r, c)
                if cell is None:
                    continue
                txt, _ = _read_cell(gray, lines, cell, None, cache)
                if txt and (not parts or parts[-1] != txt):
                    parts.append(txt)
            col_header.append(" ".join(parts))
        roles: dict[str, int] = {}
        role_header: dict[str, str] = {}
        for c, h in enumerate(col_header):
            # lowest header cell decides when the top one is a banner over several columns
            low = t.cell_at(nh - 1, c)
            low_txt = cache.get((low.r0, low.r1, low.c0, low.c1, None), ("", 0))[0] if low else ""
            role = header_role(low_txt) or header_role(h)
            if role and role not in roles:
                roles[role] = c
                role_header[role] = h
        if "min_hours" in roles and "measured" in roles and "streets" not in roles:
            # Aba Power p7 to p8: the streets column is headed "1ST - 25TH JANUARY AVE PERFORMANCE"
            # in the order itself, but holds street lists (checked by eye). Read it as streets.
            roles["streets"] = roles.pop("measured")
            role_header["streets"] = role_header.pop("measured")
            notes.append(f"table {ti}: column headed '{role_header['streets']}' read as streets")
        if "feeder_name" not in roles:
            prev_bottom = t.bbox[3]
            continue  # not a feeder table (tariff, remittance, classification tables)
        title = _title_above(gray, t, prev_bottom)
        prev_bottom = t.bbox[3]
        if "min_hours" in roles:
            kind = "service_level"
        elif "remark" in roles or "measured" in roles:
            kind = "shortfall"
        else:
            notes.append(f"table {ti}: feeder table with neither min hours nor remark, skipped")
            continue
        if "sn" not in roles:
            notes.append(f"table {ti}: no S/N header found; first column used")
            roles["sn"] = 0
        sn_col = roles["sn"]
        virtual: set[int] = set()  # grid boundaries where a row rule is missing in the S/N column
        # records from S/N cells below the header
        seen = set()
        spans: list[tuple[int, int]] = []
        for r in range(nh, t.n_rows):
            sc = t.cell_at(r, sn_col)
            if sc is None or (sc.r0, sc.r1) in seen:
                continue
            seen.add((sc.r0, sc.r1))
            spans.extend(_split_sn_cell(gray, t, sc, max(sc.r0, nh), virtual))
        for r0, r1 in spans:
            raw, conf, num = {}, {}, {}
            for role, c in roles.items():
                parts, confs = [], []
                done = set()
                for rr in range(r0, r1 + 1):
                    cell = t.cell_at(rr, c)
                    if cell is None:
                        continue
                    cell = _clip(t, cell, r0, r1, virtual)
                    k = (cell.r0, cell.r1, cell.c0, cell.c1)
                    if k in done:
                        continue
                    done.add(k)
                    txt, cf = _read_cell(gray, lines, cell, role, cache)
                    if txt:
                        parts.append(txt)
                    if cf >= 0:
                        confs.append(cf)
                raw[role] = " ".join(parts)
                if role in NUM_ROLES and len(done) == 1:
                    num_entry = cache.get(("num",) + next(iter(done)) + (role,))
                    if num_entry is not None:
                        num[role] = num_entry
                conf[role] = float(np.mean(confs)) if confs else -1.0
            if not any(raw.get(k) for k in ("feeder_name", "sn", "band")):
                continue
            box = (t.xs[0] - 4, t.ys[r0] - 4, t.xs[-1] + 4, t.ys[r1 + 1] + 4)
            records.append(Record(ti, kind, title, role_header, raw, conf, box, (r0, r1), {"num": num}))
    return PageResult(stem, page, ang, records, len(tables), notes, gray)


def clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    s = re.sub(r"\s+([,.;:])", r"\1", s)
    return s
