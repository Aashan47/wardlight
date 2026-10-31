"""Numbers only from tools: the check that every number in a draft answer appears in that session's tool results.

What counts as a number in the answer (each is a "claim"):
- digits, with or without thousands commas or decimals: 9,137  0.93  16304523
- money: N80m, N80 million, NGN 80,000,000, US$50,000, $12k, USD 1.2 million (the currency does not change the
  value; the scale word does)
- percentages: 93%, 93 percent, 93 per cent (matched against a tool value v as v x 100 or as v itself)
- scales: k, thousand, m, mn, million, bn, billion (attached or as the next word)
- number words: one ... nineteen, twenty ... ninety, hundred, dozen, with scales ("eighty million")
- numbers glued to a known unit: 12kWh, 0.95kWp, 4h, 10km, 500W
- each side of a range or ratio: 2-8, 2 to 8, 0.90-0.99, 24/7

Rounding: a claim matches a tool value when the value, rounded at the claim's written precision, gives the claim:
|claim - value| <= half a unit in the last written place (times the scale). An integer written with trailing
zeros ("16,300,000") may also be a rounding at its last non-zero digit, but only within 1% of the value.

Tokens that mix digits and letters (a facility id "SN_BEFC69FA4D", a model code "E003-040e", a citation "S3",
a month "2026-09") must appear verbatim in the tool results; otherwise they are split at - / : and each part
is checked, and an unrecognised part blocks the answer. Ordered-list markers (1. 2. 3. at line starts, in
sequence from 1) and citation markers [S1] are not claims; citation ids must exist in the session's registry.

Known limitation (stated, not hidden): a small integer or a rounded figure can match an unrelated tool value
by coincidence, so the check proves "appears in the tool results", not "is the right number for this
sentence". The structured fields of the planner output (funded, totals) are filled by code from the tool
results, never by the model, which closes that gap for the figures that matter most.
"""

from __future__ import annotations

import bisect
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

SCALES = {
    "k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "millions": 1e6,
    "bn": 1e9, "b": 1e9, "billion": 1e9, "billions": 1e9,
}
ATTACHED_SCALES = {"k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6, "mn": 1e6, "bn": 1e9, "B": 1e9}
UNITS = {
    "kwh", "kwp", "kw", "wh", "w", "wp", "mwh", "mw", "km", "kg", "l", "h", "hr", "hrs", "hour", "hours",
    "°c", "c", "degc", "x", "pct", "d", "days", "yr", "y", "kva", "kv", "v", "a",
}
PERCENT_WORDS = {"%", "percent", "pct"}
CURRENCY_TOKENS = {"n", "₦", "ngn", "us$", "usd", "$", "naira"}

SMALL_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS_WORDS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
              "ninety": 90}
WORD_SCALES = {"hundred": 100, "thousand": 1e3, "million": 1e6, "billion": 1e9}

STRIP_CHARS = "()[]{}\"'*_`|<>;:!?,.~≈≥≤#“”‘’«»"  # curly quotes too: live models write “0”
CITE_RE = re.compile(r"\[(S\d+(?:\s*[,;]\s*S\d+)*)\]")
# gpt-oss writes citations as 【S1】 or 【S1†L3-L5】, glued to the number before them; and uses non-ASCII hyphens.
_LENTICULAR_RE = re.compile(r"\u3010\s*(S\d+)[^\u3011]*\u3011")
_NBSP_THOUSANDS_RE = re.compile(r"(?<=\d)[\u00a0\u2007\u2009\u202f](?=\d{3}(?!\d))")
_HYPHENS = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u00ad": ""})


def normalise(text: str) -> str:
    """Rewrite model-specific citation marks to [S1] (with a space before, so a glued number stands alone) and
    unusual hyphens to ASCII. Applied to the draft before checking and before it is shown."""
    text = _LENTICULAR_RE.sub(lambda m: f" [{m.group(1)}]", text or "")
    # thousands separated by no-break, narrow no-break, thin or figure spaces: 80 000 000 -> 80,000,000
    text = _NBSP_THOUSANDS_RE.sub(",", text)
    return text.translate(_HYPHENS)
LIST_MARKER_RE = re.compile(r"^(\s*)(\d+)([.)])\s+")
NUM_CORE = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
NUM_TOKEN_RE = re.compile(
    r"^(?P<sign>[-−+])?(?P<cur>₦|NGN|N|US\$|USD|\$)?(?P<num>" + NUM_CORE + r")(?P<tail>.*)$"
)
SPLIT_RE = re.compile("[-\u2013\u2014/:]")


@dataclass
class Claim:
    text: str  # as written
    value: float
    tol: float  # absolute tolerance on the value
    percent: bool
    tz_tol: float = 0.0  # extra trailing-zero tolerance (relative cap applies)
    matched: float | None = None

    @property
    def ok(self) -> bool:
        return self.matched is not None


@dataclass
class GroundingReport:
    ok: bool
    claims: list[Claim] = field(default_factory=list)
    unmatched: list[Claim] = field(default_factory=list)
    unknown_tokens: list[str] = field(default_factory=list)
    bad_citations: list[str] = field(default_factory=list)
    citations_used: list[str] = field(default_factory=list)
    missing_citation: bool = False

    @property
    def n_total(self) -> int:
        return len(self.claims) + len(self.unknown_tokens)

    @property
    def n_traced(self) -> int:
        return sum(c.ok for c in self.claims)

    def problems(self) -> list[str]:
        out = [f"number '{c.text}' does not appear in any tool result" for c in self.unmatched]
        out += [f"token '{t}' does not appear in any tool result" for t in self.unknown_tokens]
        out += [f"citation [{c}] does not exist in this session" for c in self.bad_citations]
        if self.missing_citation:
            out.append("the answer states numbers but cites no source; cite with [S#] ids from the tool results")
        return out

    def retry_message(self) -> str:
        return ("GROUNDING CHECK FAILED. " + "; ".join(self.problems()) + ". Rewrite the answer using only numbers "
                "that appear in this session's tool results (call a tool if you need a figure), keep the [S#] "
                "citations, or say plainly that the data does not give that figure.")

    def to_dict(self) -> dict:
        return {"ok": self.ok, "n_total": self.n_total, "n_traced": self.n_traced,
                "unmatched": [c.text for c in self.unmatched], "unknown_tokens": self.unknown_tokens,
                "bad_citations": self.bad_citations, "citations_used": self.citations_used,
                "missing_citation": self.missing_citation}


# ---------------------------------------------------------------- tokenising


def _strip(tok: str) -> str:
    t = tok.strip(STRIP_CHARS)
    # a leading minus survives only directly before a digit or decimal point
    while t.startswith(("-", "−")) and not re.match(r"^[-−](?:\d|\.\d)", t):
        t = t[1:].strip(STRIP_CHARS)
    return t


def _strip_list_markers(text: str) -> str:
    """Remove ordered-list markers only where a list counts 1, 2, 3 ... in order."""
    lines = text.split("\n")
    runs: list[list[int]] = []
    cur: list[int] = []
    for i, ln in enumerate(lines):
        if LIST_MARKER_RE.match(ln):
            cur.append(i)
        elif ln.strip() == "" or ln.startswith((" ", "\t")):
            continue  # blank lines and indented continuations keep a list together
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    for run in runs:
        nums = [int(LIST_MARKER_RE.match(lines[i]).group(2)) for i in run]  # type: ignore[union-attr]
        if nums == list(range(1, len(nums) + 1)):
            for i in run:
                lines[i] = LIST_MARKER_RE.sub(r"\1", lines[i], count=1)
    return "\n".join(lines)


def _decimals(num: str) -> int:
    return len(num.split(".")[1]) if "." in num else 0


def _trailing_zeros(num: str) -> int:
    if "." in num:
        return 0
    d = num.replace(",", "")
    return len(d) - len(d.rstrip("0")) if d.strip("0") else 0


def _parse_numeric(tok: str) -> tuple[float, float, bool, float, bool] | None:
    """(value, tol, percent, tz_tol, needs_scale_lookahead) for a token that is a number with affixes, else None."""
    m = NUM_TOKEN_RE.match(tok)
    if not m:
        return None
    num, tail = m.group("num"), m.group("tail")
    try:
        base = float(num.replace(",", ""))
    except ValueError:
        return None
    if m.group("sign") in ("-", "−"):
        base = -base
    d = _decimals(num)
    tz = _trailing_zeros(num)
    scale, percent = 1.0, False
    tl = tail.lower()
    if tail == "":
        pass
    elif tail == "%":
        percent = True
    elif tail in ATTACHED_SCALES:
        scale = ATTACHED_SCALES[tail]
    elif tl in SCALES and len(tl) > 2:  # "80million"
        scale = SCALES[tl]
    elif tl in UNITS or tl.rstrip(".") in UNITS:
        pass
    elif re.fullmatch(r"(st|nd|rd|th)", tl):
        pass  # ordinals: 1st, 2nd
    else:
        return None
    tol = 0.5 * 10 ** (-d) * scale
    tz_tol = 0.5 * 10 ** tz * scale if tz and scale == 1.0 else 0.0
    return base * scale, tol, percent, tz_tol, tail == ""


def _word_number(words: list[str], i: int) -> tuple[float, int] | None:
    """Parse a run of number words starting at i. Returns (value, tokens consumed)."""
    total, current, j, seen = 0.0, 0.0, i, False
    while j < len(words):
        w = words[j].lower().strip(STRIP_CHARS)
        parts = w.split("-") if "-" in w else [w]
        if all(p in SMALL_WORDS or p in TENS_WORDS for p in parts) and parts != [""]:
            current += sum(SMALL_WORDS.get(p, TENS_WORDS.get(p, 0)) for p in parts)
            seen = True
        elif w == "dozen" and (seen or j == i):
            current = (current or 1) * 12
            seen = True
        elif w in WORD_SCALES and seen:
            if w == "hundred":
                current = (current or 1) * 100
            else:
                total += (current or 1) * WORD_SCALES[w]
                current = 0
        elif w == "and" and seen and j + 1 < len(words) and words[j + 1].lower().strip(STRIP_CHARS) in {
                **SMALL_WORDS, **TENS_WORDS}:
            pass
        else:
            break
        j += 1
    if not seen:
        return None
    return total + current, j - i


def extract(text: str, known_tokens: set[str] | None = None) -> tuple[list[Claim], list[str], list[str]]:
    """Claims, unknown alphanumeric tokens, and citation ids found in `text`."""
    known = known_tokens or set()
    cites = [c.strip() for grp in CITE_RE.findall(text) for c in re.split(r"[,;]", grp)]
    body = CITE_RE.sub(" ", text)
    body = _strip_list_markers(body)
    # separate a range written with an en or em dash or a word joiner, and markdown table pipes
    body = body.replace("|", " ")
    raw = body.split()
    claims: list[Claim] = []
    unknown: list[str] = []
    i = 0
    while i < len(raw):
        tok = _strip(raw[i])
        if not tok:
            i += 1
            continue
        if not any(ch.isdigit() for ch in tok):
            wn = _word_number(raw, i)
            if wn is not None:
                val, used = wn
                nxt = _strip(raw[i + used]).lower() if i + used < len(raw) else ""
                percent = nxt in PERCENT_WORDS or (nxt == "per" and i + used + 1 < len(raw)
                                                   and _strip(raw[i + used + 1]).lower() == "cent")
                claims.append(Claim(" ".join(raw[i:i + used]), val, 0.5 if val < 1e3 else 0.5 * val * 0.01,
                                    percent))
                i += used
                continue
            i += 1
            continue
        used = _consume_numeric(raw, i, tok, known, claims, unknown)
        i += used
    return claims, unknown, cites


def _consume_numeric(raw: list[str], i: int, tok: str, known: set[str], claims: list[Claim],
                     unknown: list[str]) -> int:
    """Handle one token containing a digit; returns tokens consumed."""
    if tok in known and not NUM_TOKEN_RE.match(tok):
        return 1  # a verbatim identifier from the tool results (facility id, file name, citation id)
    p = _parse_numeric(tok)
    if p is not None:
        val, tol, pct, tz_tol, bare = p
        used = 1
        text = tok
        nxt = _strip(raw[i + 1]).lower() if i + 1 < len(raw) else ""
        if bare and nxt in SCALES and nxt not in ("b",):
            s = SCALES[nxt]
            val, tol, tz_tol = val * s, tol * s, 0.0
            used, text = 2, f"{tok} {raw[i + 1]}"
            nxt = _strip(raw[i + 2]).lower() if i + 2 < len(raw) else ""
        if not pct and nxt in PERCENT_WORDS:
            pct, used, text = True, used + 1, f"{text} %"
        elif not pct and nxt == "per" and i + used + 1 < len(raw) and _strip(raw[i + used + 1]).lower() == "cent":
            pct, used, text = True, used + 2, f"{text} per cent"
        claims.append(Claim(text, val, tol, pct, tz_tol))
        return used
    if tok in known:
        return 1
    parts = [q for q in SPLIT_RE.split(tok) if q]
    if len(parts) > 1:
        for part in parts:
            part = _strip(part)
            if not part or not any(ch.isdigit() for ch in part):
                continue
            if part in known and not NUM_TOKEN_RE.match(part):
                continue
            q = _parse_numeric(part)
            if q is None:
                if part not in known:
                    unknown.append(part)
                continue
            claims.append(Claim(part, q[0], q[1], q[2], q[3]))
        return 1
    unknown.append(tok)
    return 1


# ---------------------------------------------------------------- the pool of tool numbers


class ToolPool:
    """Every number and every token a reader could see in the session's tool results."""

    def __init__(self, results: Iterable = ()):
        self.values: list[float] = []
        self.tokens: set[str] = set()
        for r in results:
            self.add(r)
        self._sorted: list[float] | None = None

    def add(self, obj) -> None:
        self._sorted = None
        if isinstance(obj, str):
            s = obj.strip()
            if s[:1] in "{[":
                try:
                    self.add(json.loads(s))
                    return
                except (ValueError, TypeError):
                    pass
            self._add_text(s)
        elif isinstance(obj, bool) or obj is None:
            return
        elif isinstance(obj, (int, float)):
            if math.isfinite(obj):
                self.values.append(float(obj))
        elif isinstance(obj, dict):
            for k, v in obj.items():
                self._add_text(str(k))
                self.add(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                self.add(v)
        else:
            self._add_text(str(obj))

    def _add_text(self, s: str) -> None:
        for raw in s.split():
            t = _strip(raw)
            if not t:
                continue
            self.tokens.add(t)
            for part in re.split("[-\u2013\u2014/:#_.]", t):
                part = _strip(part)
                if part:
                    self.tokens.add(part)
            # file-name style ids: digit runs separated by _ - / . # count as numbers ("September_2026_088")
            if any(ch.isalpha() for ch in t):
                for run in re.findall(r"(?:^|(?<=[_\-/.#]))(\d+)(?=$|[_\-/.#])", t):
                    self.values.append(float(run))
        claims, _, _ = extract(s)
        for c in claims:
            self.values.append(c.value)
            if c.percent:
                self.values.append(c.value / 100.0)

    def sorted(self) -> list[float]:
        if self._sorted is None:
            self._sorted = sorted(set(self.values))
        return self._sorted

    def _near(self, x: float, tol: float) -> float | None:
        v = self.sorted()
        lo = bisect.bisect_left(v, x - tol - 1e-9)
        best = None
        for j in range(lo, len(v)):
            if v[j] > x + tol + 1e-9:
                break
            if best is None or abs(v[j] - x) < abs(best - x):
                best = v[j]
        return best

    def match(self, c: Claim) -> float | None:
        cands = [(c.value, c.tol)]
        if c.percent:
            cands.append((c.value / 100.0, c.tol / 100.0))
        for x, tol in cands:
            hit = self._near(x, tol)
            if hit is not None:
                return hit
        if c.tz_tol:
            hit = self._near(c.value, c.tz_tol)
            if hit is not None and abs(hit - c.value) <= 0.01 * abs(hit):
                return hit
        return None


def check(answer: str, tool_results: Iterable, citation_ids: Iterable[str] | None = None,
          require_citation: bool = True) -> GroundingReport:
    """Block the answer unless every number and digit-bearing token in it comes from the tool results."""
    answer = normalise(answer)
    pool = tool_results if isinstance(tool_results, ToolPool) else ToolPool(tool_results)
    known = set(pool.tokens)
    registry = set(citation_ids) if citation_ids is not None else None
    if registry:
        known |= registry
    claims, unknown, cites = extract(answer, known)
    for c in claims:
        c.matched = pool.match(c)
    unmatched = [c for c in claims if not c.ok]
    bad = [c for c in cites if registry is not None and c not in registry]
    missing = bool(require_citation and claims and not cites)
    ok = not unmatched and not unknown and not bad and not missing
    return GroundingReport(ok, claims, unmatched, unknown, bad, sorted(set(cites)), missing)


def numbers_in(text: str) -> list[float]:
    """Plain list of number values in `text` (used to ground a free-text SMS reply)."""
    claims, _, _ = extract(text)
    return [c.value for c in claims]
