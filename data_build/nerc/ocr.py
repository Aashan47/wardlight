"""Cell-level OCR with tesseract (5.5.3, Homebrew) through pytesseract."""

from __future__ import annotations

import re

import cv2
import numpy as np
import pytesseract
from PIL import Image

TEXT_CFG = "--oem 1 --psm 6"
LINE_CFG = "--oem 1 --psm 7"
DIGITS_CFG = "--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789."
CHAR_CFG = "--oem 1 --psm 10 -c tessedit_char_whitelist=ABCDE"


def clean_cell(gray: np.ndarray, lines: np.ndarray, box: tuple[int, int, int, int], inset: int = 4,
               pad: int = 14) -> np.ndarray | None:
    """Crop a cell, white out ruling-line pixels, trim to ink and pad. None when the cell is empty."""
    x0, y0, x1, y1 = box
    x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    if x1 - x0 < 6 or y1 - y0 < 6:
        return None
    crop = gray[y0:y1, x0:x1].copy()
    crop[lines[y0:y1, x0:x1] > 0] = 255
    ink = crop < 160
    if ink.sum() < 12:
        return None
    ys, xs = np.where(ink)
    crop = crop[max(ys.min() - 2, 0):ys.max() + 3, max(xs.min() - 2, 0):xs.max() + 3]
    return np.pad(crop, pad, constant_values=255)


def ocr(img: np.ndarray | None, cfg: str = TEXT_CFG, scale: float = 2.0, caps: bool = True) -> tuple[str, float]:
    """Text (lines joined by a space) and mean word confidence (0 to 100; -1 when nothing read).

    Cells are upscaled 2x before OCR: on a test page this fixed '11KY' to '11KV', 'A5MVA' to '45MVA'
    and 'TIA' to 'T1A' without new errors.
    """
    if img is None:
        return "", -1.0
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    d = pytesseract.image_to_data(Image.fromarray(img), config=cfg, output_type=pytesseract.Output.DICT)
    words, confs = [], []
    for txt, conf in zip(d["text"], d["conf"]):
        txt = txt.strip()
        if not txt:
            continue
        words.append(txt)
        try:
            c = float(conf)
        except ValueError:
            c = -1.0
        if c >= 0:
            confs.append(c)
    text = " ".join(words)
    # every dash variant to a plain hyphen (the deliverables carry no long dashes)
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    if caps:  # table cells are set in capitals; titles are not
        text = fix_caps(text)
    return text, (float(np.mean(confs)) if confs else -1.0)


def fix_caps(text: str) -> str:
    """The tables are set in capitals, so lower-case output is an OCR confusion.

    'l' next to a digit, or in 'Tl' (transformer 1), becomes '1'; any other 'l' becomes 'I' (the
    font's capital I); other lower-case letters are upper-cased. Inside tokens that are digits plus a unit (e.g. '1OOMVA'), letter O becomes zero.
    """
    text = re.sub(r"(?<=\d)l|l(?=\d)|(?<=\bT)l\b", "1", text)
    text = text.replace("l", "I").upper()

    def zero(m: re.Match) -> str:
        return m.group(1) + m.group(2).replace("O", "0") + (m.group(3) or "")

    text = re.sub(r"\b(\d+)([O0]+)(MVA|KVA|KV)?\b", zero, text)
    # voltage tokens (11KV, 33KV) in this font: the narrow '1' pair is split ('1 1KV', '1 1-'),
    # read as 'T' ('1TKV', 'T1KV'), and 'V' as 'Y' ('33KY', '11KVY')
    text = re.sub(r"(?<![A-Z0-9])1 1(?=KV|-)", "11", text)
    text = re.sub(r"(?<![A-Z0-9])(?:1 ?T|T ?1)(?=KV)", "11", text)
    text = re.sub(r"(\d)(?:KY|KVY)\b", r"\1KV", text)
    # stray rule fragments at the cell edge
    text = re.sub(r"^[|_\s]+|[|_\s]+$", "", text)
    return text


def ocr_text(img: np.ndarray | None, cfg: str = TEXT_CFG) -> tuple[str, float]:
    """Text cells: read at 1x and 2x and keep the read with the higher mean word confidence.

    Neither scale wins everywhere: 2x fixed '11KY' and 'A5MVA' on IBEDC p15, 1x was better on the
    three fixture pages. Picking by confidence uses no fixture knowledge.
    """
    a = ocr(img, cfg, scale=1.0)
    b = ocr(img, cfg, scale=2.0)
    return a if a[1] >= b[1] else b
