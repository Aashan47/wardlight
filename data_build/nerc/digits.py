"""Glyph-template reader for number cells (S/N, hours).

Tesseract misreads some numbers in the Futura-like font of these orders: "41" came out as "4" on most
DisCos, "71" as "7", and "4" alone as "A". The digits within one order are rendered from one font at
one size, so a template bank is built per order from cells tesseract reads unambiguously (the digit
count equals the glyph count, and the whitelisted and plain reads agree), and every number cell is
then read glyph by glyph against that bank. Where the bank cannot read a cell with confidence, the
tesseract read is kept and the disagreement is flagged; nothing is inferred from row order.
"""

from __future__ import annotations

from collections import defaultdict

import cv2
import numpy as np

SIZE = 32
MIN_EXEMPLARS = 3
MIN_SCORE = 0.80  # normalised correlation with the best template
MIN_MARGIN = 0.04  # best minus second-best template score


def glyph_boxes(img: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Glyph boxes (x, y, w, h) left to right; components overlapping in x are one glyph."""
    ink = (img < 160).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    comps = sorted([tuple(int(v) for v in st[i][:4]) for i in range(1, n) if st[i][4] >= 6],
                   key=lambda s: s[0])
    groups: list[list[int]] = []
    for x, y, w, h in comps:
        if groups and x < groups[-1][0] + groups[-1][2] - 2:
            g = groups[-1]
            x0, y0 = min(g[0], x), min(g[1], y)
            x1, y1 = max(g[0] + g[2], x + w), max(g[1] + g[3], y + h)
            groups[-1] = [x0, y0, x1 - x0, y1 - y0]
        else:
            groups.append([x, y, w, h])
    return [tuple(g) for g in groups]


def _split(img: np.ndarray) -> tuple[list[np.ndarray], list[str]]:
    """Tall glyph images and a parallel list of kinds ('d' digit, '.' point)."""
    boxes = glyph_boxes(img)
    if not boxes:
        return [], []
    H = max(b[3] for b in boxes)
    out, kinds = [], []
    for x, y, w, h in boxes:
        if h < 0.35 * H:
            kinds.append(".")
            out.append(None)
        else:
            kinds.append("d")
            out.append(_norm(img[y:y + h, x:x + w]))
    return out, kinds


def _norm(g: np.ndarray) -> np.ndarray:
    h, w = g.shape
    s = (SIZE - 4) / max(h, 1)
    nw = max(1, min(SIZE - 2, round(w * s)))
    r = cv2.resize(g, (nw, SIZE - 4), interpolation=cv2.INTER_AREA)
    canvas = np.full((SIZE, SIZE), 255, np.uint8)
    x0 = (SIZE - nw) // 2
    canvas[2:SIZE - 2, x0:x0 + nw] = r
    v = (255 - canvas).astype(np.float32).ravel()
    v -= v.mean()
    n = np.linalg.norm(v)
    return v / n if n else v


class Bank:
    def __init__(self) -> None:
        self.ex: dict[str, list[np.ndarray]] = defaultdict(list)
        self.templates: dict[str, np.ndarray] = {}

    def add(self, img: np.ndarray, text: str, other: str) -> None:
        """Learn from a cell when tesseract's two reads agree and the glyph count matches."""
        if img is None or not text or text != other:
            return
        if not all(ch.isdigit() or ch == "." for ch in text):
            return
        glyphs, kinds = _split(img)
        if "".join("." if k == "." else "d" for k in kinds) != "".join(
                "." if ch == "." else "d" for ch in text):
            return
        for g, ch in zip(glyphs, text):
            if ch != ".":
                self.ex[ch].append(g)

    def build(self) -> None:
        for ch, vs in self.ex.items():
            if len(vs) >= MIN_EXEMPLARS:
                t = np.median(np.stack(vs), axis=0)
                t -= t.mean()
                n = np.linalg.norm(t)
                self.templates[ch] = t / n if n else t

    def read(self, img: np.ndarray | None) -> tuple[str | None, float]:
        """Number text, and the lowest per-glyph score; None when any glyph is not confidently read."""
        if img is None or len(self.templates) < 5:
            return None, 0.0
        glyphs, kinds = _split(img)
        if not glyphs:
            return None, 0.0
        keys = list(self.templates)
        mat = np.stack([self.templates[k] for k in keys])
        out, worst = [], 1.0
        for g, k in zip(glyphs, kinds):
            if k == ".":
                out.append(".")
                continue
            sc = mat @ g
            order = np.argsort(sc)[::-1]
            best = float(sc[order[0]])
            second = float(sc[order[1]]) if len(order) > 1 else -1.0
            if best < MIN_SCORE or best - second < MIN_MARGIN:
                return None, best
            out.append(keys[order[0]])
            worst = min(worst, best)
        return "".join(out), worst
