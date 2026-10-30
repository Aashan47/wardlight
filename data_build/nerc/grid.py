"""Table grid detection on a rendered NERC order page.

The September 2026 orders are image-only PDFs, but the images are clean renders of ruled tables, so the
ruling lines can be recovered with morphology. The Aba Power order is a real paper scan, slightly
rotated, so every page is deskewed first.

Output of `find_tables`: a list of `Table` objects, each holding the row boundaries (y), column
boundaries (x) and the logical cells after merged cells are resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Cell:
    r0: int  # first grid row (inclusive)
    r1: int  # last grid row (inclusive)
    c0: int
    c1: int
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 in page pixels


@dataclass
class Table:
    bbox: tuple[int, int, int, int]
    ys: list[int]
    xs: list[int]
    cells: list[Cell] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.ys) - 1

    @property
    def n_cols(self) -> int:
        return len(self.xs) - 1

    def cell_at(self, r: int, c: int) -> Cell | None:
        for cell in self.cells:
            if cell.r0 <= r <= cell.r1 and cell.c0 <= c <= cell.c1:
                return cell
        return None


def binarize(gray: np.ndarray) -> np.ndarray:
    """Ink as 255 on 0.

    A fixed threshold of 200, not Otsu: some DisCos (EEDC p11) draw rulings in grey near 156 to 161,
    just above the Otsu cut of about 151, so Otsu dropped those column lines and merged columns.
    """
    otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    _, bw = cv2.threshold(gray, max(otsu, 200), 255, cv2.THRESH_BINARY_INV)
    return bw


def line_masks(bw: np.ndarray, h_len: int = 60, v_len: int = 40) -> tuple[np.ndarray, np.ndarray]:
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))
    # Rulings in these renders break by a pixel or two where they cross (seen on KEDCO p12, where a
    # vertical rule between two 1 px horizontals was only 36 px long and fell under the opening).
    # Close such gaps vertically before opening. (Closing horizontally as well joined the letters of
    # words into false rulings, so horizontals are opened as they are.)
    bw_h = bw
    bw_v = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 7)))
    h = cv2.morphologyEx(bw_h, cv2.MORPH_OPEN, hk)
    v = cv2.morphologyEx(bw_v, cv2.MORPH_OPEN, vk)
    # thicken so that a separator test a few pixels off still finds the line
    h = cv2.dilate(h, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3)))
    v = cv2.dilate(v, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 9)))
    return h, v


def skew_angle(gray: np.ndarray) -> float:
    """Angle in degrees of the long horizontal rulings (0 when none are found)."""
    bw = binarize(gray)
    h = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (120, 1)))
    lines = cv2.HoughLinesP(h, 1, np.pi / 1800, threshold=300, minLineLength=gray.shape[1] // 4,
                            maxLineGap=20)
    if lines is None:
        # try a looser open for rotated scans, where a straight kernel breaks the line
        h = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1)))
        lines = cv2.HoughLinesP(h, 1, np.pi / 1800, threshold=200, minLineLength=gray.shape[1] // 6,
                                maxLineGap=30)
    if lines is None:
        return 0.0
    angs = []
    for x0, y0, x1, y1 in np.asarray(lines).reshape(-1, 4):
        if x1 == x0:
            continue
        a = np.degrees(np.arctan2(y1 - y0, x1 - x0))
        if abs(a) < 5:
            angs.append(a)
    return float(np.median(angs)) if angs else 0.0


def deskew(gray: np.ndarray) -> tuple[np.ndarray, float]:
    ang = skew_angle(gray)
    if abs(ang) < 0.05:
        return gray, 0.0
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    out = cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=255)
    return out, ang


def _cluster(vals: list[int], tol: int) -> list[int]:
    vals = sorted(vals)
    groups: list[list[int]] = []
    for v in vals:
        if groups and v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [round(float(np.mean(g))) for g in groups]


def _segments(mask: np.ndarray, horizontal: bool) -> list[tuple[int, int, int]]:
    """Connected line segments as (pos, start, end): y,x0,x1 for horizontal, x,y0,y1 for vertical."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    segs = []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if horizontal:
            segs.append((y + h // 2, x, x + w))
        else:
            segs.append((x + w // 2, y, y + h))
    return segs


def find_tables(gray: np.ndarray, min_width_frac: float = 0.25) -> list[Table]:
    bw = binarize(gray)
    hmask, vmask = line_masks(bw)
    grid = cv2.bitwise_or(hmask, vmask)
    grid = cv2.dilate(grid, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(grid, connectivity=8)
    W = gray.shape[1]
    tables = []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if w < W * min_width_frac or h < 50:
            continue
        t = _build_table(hmask, vmask, (x, y, x + w, y + h))
        if t is not None and t.n_rows >= 1 and t.n_cols >= 3:
            tables.append(t)
    tables.sort(key=lambda t: t.bbox[1])
    return tables


def _coverage(mask: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> float:
    if x1 <= x0 or y1 <= y0:
        return 0.0
    sub = mask[y0:y1, x0:x1]
    return float(sub.any(axis=0).mean()) if sub.shape[1] else 0.0


def _vcoverage(mask: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> float:
    if x1 <= x0 or y1 <= y0:
        return 0.0
    sub = mask[y0:y1, x0:x1]
    return float(sub.any(axis=1).mean()) if sub.shape[0] else 0.0


def _build_table(hmask: np.ndarray, vmask: np.ndarray, bbox: tuple[int, int, int, int]) -> Table | None:
    x0, y0, x1, y1 = bbox
    tw = x1 - x0
    hsub = hmask[y0:y1 + 1, x0:x1 + 1]
    vsub = vmask[y0:y1 + 1, x0:x1 + 1]
    hsegs = [(y + y0, a + x0, b + x0) for y, a, b in _segments(hsub, True) if b - a > 40]
    vsegs = [(x + x0, a + y0, b + y0) for x, a, b in _segments(vsub, False) if b - a > 25]
    if not hsegs or not vsegs:
        return None
    ys = _cluster([s[0] for s in hsegs], 8)
    # a column boundary must run down a good part of the table; short vertical runs are text strokes
    th = y1 - y0
    xs_all = _cluster([s[0] for s in vsegs], 10)
    xs = [x for x in xs_all
          if sum(b - a for xx, a, b in vsegs if abs(xx - x) <= 10) >= 0.3 * th or x in (xs_all[0], xs_all[-1])]
    # drop columns narrower than 15 px and rows thinner than 18 px (double rules)
    xs = _dedupe(xs, 15)
    ys = _dedupe(ys, 18)
    # the outer frame must be present: keep only boundaries inside the frame
    if len(xs) < 2 or len(ys) < 2:
        return None
    # rows whose top line is very short are not boundaries of the whole table but of merged cells;
    # keep them, merges are resolved per cell below.
    if xs[-1] - xs[0] < tw * 0.6:
        return None
    t = Table(bbox=bbox, ys=ys, xs=xs)
    _resolve_cells(t, hmask, vmask)
    return t


def _dedupe(vals: list[int], gap: int) -> list[int]:
    out: list[int] = []
    for v in vals:
        if out and v - out[-1] < gap:
            continue
        out.append(v)
    return out


def _resolve_cells(t: Table, hmask: np.ndarray, vmask: np.ndarray) -> None:
    nr, nc = t.n_rows, t.n_cols
    parent = list(range(nr * nc))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    pad = 5
    for r in range(nr):
        ya, yb = t.ys[r], t.ys[r + 1]
        for c in range(nc):
            xa, xb = t.xs[c], t.xs[c + 1]
            # vertical separator between c and c+1 within row r
            if c + 1 < nc:
                xsep = t.xs[c + 1]
                cov = _vcoverage(vmask, xsep - pad, xsep + pad + 1, ya + 4, yb - 4)
                if cov < 0.5:
                    union(r * nc + c, r * nc + c + 1)
            # horizontal separator between r and r+1 within column c
            if r + 1 < nr:
                ysep = t.ys[r + 1]
                cov = _coverage(hmask, xa + 4, xb - 4, ysep - pad, ysep + pad + 1)
                if cov < 0.5:
                    union(r * nc + c, (r + 1) * nc + c)
    groups: dict[int, list[tuple[int, int]]] = {}
    for r in range(nr):
        for c in range(nc):
            groups.setdefault(find(r * nc + c), []).append((r, c))
    cells = []
    for members in groups.values():
        rs = [m[0] for m in members]
        cs = [m[1] for m in members]
        r0, r1, c0, c1 = min(rs), max(rs), min(cs), max(cs)
        cells.append(Cell(r0, r1, c0, c1, (t.xs[c0], t.ys[r0], t.xs[c1 + 1], t.ys[r1 + 1])))
    cells.sort(key=lambda k: (k.r0, k.c0))
    t.cells = cells
