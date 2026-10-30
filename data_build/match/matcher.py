"""Facility to NERC feeder-row matching: tiers a, b, c (LGA rows or naija-grid unit), d, and off-grid. Rules and thresholds: docs/sources/match.md.

Every accepted match carries the NERC row text it relied on (order file, page, S/N, the printed feeder
name, location and streets), the exact segment that matched, and the score.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from . import footprint, regulators
from .text import (
    FACILITY_NOUNS,
    IMPLIES_HOSPITAL,
    ROAD_WORDS,
    STATE_NAMES,
    clean,
    distinctive_tokens,
    is_health_mention,
    is_road,
    place_is_usable,
    segments,
    state_key,
    type_tokens,
    ward_core,
)

# ---- Thresholds, fixed before the T2 sample was drawn (docs/sources/match.md) ----------------
A_SET_RATIO = 90          # tier (a) prefilter: rapidfuzz token_set_ratio(mention, facility name) >= this
A_TOKEN_RATIO = 85        # tier (a) each distinctive token of the mention found in the name at ratio >= this
A_MAX_EXTRA_TOKENS = 1    # tier (a) facility may carry at most this many distinctive tokens the mention lacks
A_MAX_CANDIDATES = 3      # tier (a) a mention matching more facilities than this is ambiguous, not used
# Amendment 2: UNIVERSITY added ("TEACHING HOSPITAL" and "UNIVERSITY TEACHING HOSPITAL" name one place).
A_SOFT_TYPE = {"CENTRE", "CARE", "STATE", "HOME", "POST", "HEALTH", "UNIVERSITY"}
A_SPECIFIC_NAME_TOKENS = 2  # amendment 2: mentions with this many own distinctive words skip the type-extra rule
A_MAX_CONTEXT_TOKENS = 3  # amendment 2: a nameless mention borrows at most this many tokens from its row
B_FUZZY_RATIO = 90        # tier (b) rapidfuzz ratio for a place name and a row n-gram, names of >= B_FUZZY_MIN_LEN
B_FUZZY_MIN_LEN = 8       # tier (b) shorter names must match exactly after cleaning
B_MAX_NGRAM = 4
OFFGRID_KM = 5.0          # offgrid: Gridfinder line farther than this AND targets.tif cell not electrified
LEVELS = ("settlement_name", "ward_standard", "lga_standard")  # most to least specific
B_LEVELS = ("settlement_name", "ward_standard")  # amendment 2: LGA-level evidence is tier c_lga_mixture
# Fields searched for tier (b): the brief says a feeder's streets or location. Feeder names are not
# searched for places: they often name the source substation or town (BEDC p12 S/N 38 "SAPELE (EFFURUN)"
# serves Effurun), so a place hit there is not evidence that the feeder serves that place.
MATCH_FIELDS = ("location", "streets")
# Amendment 2: tier (a) also reads the feeder name, since feeders are often named after the facility they
# serve ("FMC GOMBE", "GENERAL HOSPITAL PANKSHIN"); a place in a feeder name is still not used.
A_FIELDS = ("feeder_name", "location", "streets")
DIRECTIONS = {"NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"}
EVIDENCE_ROWS_MAX = 20    # c_lga_mixture evidence lists at most this many rows; bands use all of them

TIERS = ("a_named", "b_place", "c_lga_mixture", "c_unit_mixture", "d_refused", "offgrid")


def _sn(v) -> str | None:
    return None if pd.isna(v) else str(v)


def row_key(r, i: int) -> str:
    """order_file#p<page>#sn<S/N>; rows the reader could not number get #i<row index> instead."""
    sn = _sn(r["sn"])
    return f"{r['order_file']}#p{int(r['page'])}#" + (f"sn{sn}" if sn is not None else f"i{i}")


def row_text(r) -> str:
    def s(v):
        return "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v).strip()
    return f"{s(r['feeder_name'])} | {s(r['location'])} | {s(r['streets'])}"


@dataclass
class Hit:
    row: int                 # index into the rows frame
    level: str               # 'facility_name' for tier (a), else one of LEVELS
    matched_text: str        # the facility's own field value that matched
    nerc_text: str           # the cleaned segment or n-gram of the NERC row
    nerc_field: str          # feeder_name, location or streets
    score: float


@dataclass
class Index:
    fac: pd.DataFrame
    by_state: dict[str, np.ndarray] = field(default_factory=dict)
    gaz: dict[str, dict[str, list[tuple[int, str, str]]]] = field(default_factory=dict)
    state_names: dict[str, set[str]] = field(default_factory=dict)  # place or LGA core -> states, for tier (a)


def prepare_facilities(fac: pd.DataFrame) -> Index:
    f = fac.drop_duplicates("unique_id", keep="first").reset_index(drop=True).copy()
    f["state_key"] = f["state_standard"].map(state_key)
    f["name_clean"] = f["facility_name"].map(clean)
    f["dist"] = f["name_clean"].map(distinctive_tokens)
    f["types"] = f["name_clean"].map(type_tokens)
    f["lga_clean"] = f["lga_standard"].map(clean)
    f["places"] = [
        [p for p in [clean(st), *ward_core(w), clean(lg)] if p and place_is_usable(p)]
        for st, w, lg in zip(f["settlement_name"], f["ward_standard"], f["lga_standard"])
    ]
    idx = Index(fac=f)
    for s, g in f.groupby("state_key"):
        idx.by_state[s] = g.index.to_numpy()
    for i, r in f.iterrows():
        forms = {
            "settlement_name": [clean(r["settlement_name"])],
            "ward_standard": ward_core(r["ward_standard"]),
            "lga_standard": [r["lga_clean"]],
        }
        g = idx.gaz.setdefault(r["state_key"], {})
        for level, names in forms.items():
            for n in names:
                if n and n != "UNKNOWN" and place_is_usable(n):
                    g.setdefault(n, []).append((i, level, str(r[level]).strip()))
    # Amendment 3 (state check for tier (a)): every place name, each LGA without its direction word
    # (UMUAHIA from Umuahia North), and each state's own name, mapped to the states it occurs in.
    for st, g in idx.gaz.items():
        for n in g:
            idx.state_names.setdefault(n, set()).add(st)
    for st, lga in zip(f["state_key"], f["lga_clean"]):
        core = " ".join(t for t in lga.split() if t not in DIRECTIONS)
        if core and core != lga and place_is_usable(core):
            idx.state_names.setdefault(core, set()).add(st)
    for st in idx.by_state:
        idx.state_names.setdefault(st, set()).add(st)
    idx.state_names.setdefault("ABUJA", set()).add("FCT")
    return idx


def row_states(r, idx: Index) -> set[str]:
    """States of the DisCo's footprint that the row's own place names point to, each name read only if it
    occurs in exactly one footprint state. Empty when the row names no such place."""
    out: set[str] = set()
    foot = set(r["states"])
    for fld in A_FIELDS:
        for seg in segments(r[fld]):
            if is_road(seg):
                continue
            for ng in _ngrams(seg):
                sts = idx.state_names.get(ng, set()) & foot
                if len(sts) == 1:
                    out |= sts
    return out


def prepare_rows(rows: pd.DataFrame) -> pd.DataFrame:
    r = rows.reset_index(drop=True).copy()
    r["disco_code"] = [footprint.disco_code(d, o) for d, o in zip(r["disco"], r["order_file"])]
    states = footprint.disco_states()
    r["states"] = [sorted(states.get(d, set())) for d in r["disco_code"]]
    r["row_key"] = [row_key(x, i) for i, x in r.iterrows()]
    r["row_text"] = [row_text(x) for _, x in r.iterrows()]
    r["row_clean"] = [" " + clean(t.replace("|", ",")) + " " for t in r["row_text"]]
    r["dedicated"] = [" DEDICATED " in t for t in r["row_clean"]]
    return r


def _tok_found(tok: str, toks: list[str]) -> bool:
    if tok in toks:
        return True
    if len(tok) < 5:
        return False
    return any(fuzz.ratio(tok, t) >= A_TOKEN_RATIO for t in toks if len(t) >= 4)


@dataclass
class Mention:
    field: str
    seg: str                 # cleaned segment as printed
    text: str                # segment plus implied HOSPITAL and borrowed context, what is compared
    dist: list[str]
    types: set[str]
    context: str | None      # where borrowed tokens came from, if any
    own_dist: list[str] = field(default_factory=list)  # distinctive tokens printed in the item itself


def _context_tokens(r, own_field: str) -> tuple[list[str], str | None]:
    """Distinctive tokens of the row's location, else its feeder name, skipping road and health items."""
    for fld in ("location", "feeder_name"):
        if fld == own_field:
            continue
        toks: list[str] = []
        for seg in segments(r[fld]):
            if is_road(seg) or is_health_mention(seg):
                continue
            # a state's name may be borrowed here ("FMC" at "GOMBE TOWN"): it must then be in the facility's
            # own name, which is not the LGA confusion amendment 1 guards against in tier (b)
            toks += [t for t in distinctive_tokens(seg) if not t[0].isdigit()]
        toks = list(dict.fromkeys(toks))
        if 1 <= len(toks) <= A_MAX_CONTEXT_TOKENS:
            return toks, fld
    return [], None


def mentions(r) -> list[Mention]:
    out = []
    for fld in A_FIELDS:
        for seg in segments(r[fld]):
            if not is_health_mention(seg) or is_road(seg):
                continue
            text = seg
            types = type_tokens(seg)
            if types & IMPLIES_HOSPITAL and not types & FACILITY_NOUNS:
                text, types = text + " HOSPITAL", types | {"HOSPITAL"}
            dist = [t for t in distinctive_tokens(text) if not t[0].isdigit()]
            ctx = None
            if not dist:
                extra, ctx = _context_tokens(r, fld)
                if not extra:
                    out.append(Mention(fld, seg, text, [], types, None))
                    continue
                text, dist = text + " " + " ".join(extra), extra
                out.append(Mention(fld, seg, text, dist, types, ctx, []))
                continue
            out.append(Mention(fld, seg, text, dist, types, ctx, dist))
    return out


def check_candidate(m: Mention, fr: pd.Series) -> str | None:
    """None when facility row fr passes tier (a) rules 2 to 4 for mention m, else the first failed rule."""
    if not all(_tok_found(t, fr["dist"]) for t in m.dist):
        return "name lacks a distinctive word of the mention"
    if not m.types <= fr["types"]:
        return "name lacks a type word of the mention (" + ", ".join(sorted(m.types - fr["types"])) + ")"
    # a printed proper name of 2+ words (YARIMAN BAKURA, KING FAHAD) is specific enough that the GRID3 name
    # may add type words (SPECIALIST, WOMEN AND CHILDREN); a 1-word name may add only soft ones
    if len(m.own_dist) < A_SPECIFIC_NAME_TOKENS and not (fr["types"] - m.types) <= A_SOFT_TYPE:
        return "name has another type word (" + ", ".join(sorted(fr["types"] - m.types - A_SOFT_TYPE)) + ")"
    extra = [t for t in fr["dist"] if not _tok_found(t, m.dist)]
    if len(extra) > A_MAX_EXTRA_TOKENS:
        return f"name has {len(extra)} words the mention lacks"
    return None


def _corroborated(fr: pd.Series, row_clean: str) -> bool:
    return any(f" {p} " in row_clean for p in fr["places"])


def evaluate_mention(m: Mention, r, idx: Index, cand_idx: np.ndarray, names: list[str]) -> dict:
    """Facilities accepted for one mention, or why not. Shared by the matcher and the audit."""
    f = idx.fac
    res = {"accepted": [], "best": None, "outcome": ""}
    if not m.dist:
        res["outcome"] = "no distinctive word in the item or its row"
        return res
    found = process.extract(m.text, names, scorer=fuzz.token_set_ratio, limit=None, score_cutoff=50)
    passing, best_fail = [], None
    for _n, score, pos in found:
        fi = int(cand_idx[pos])
        why = "token_set_ratio below 90" if score < A_SET_RATIO else check_candidate(m, f.loc[fi])
        if why is None:
            passing.append((fi, float(fuzz.token_sort_ratio(m.text, f.loc[fi, "name_clean"]))))
        elif best_fail is None or score > best_fail[1]:
            best_fail = (fi, float(score), why)
    rs = row_states(r, idx)
    if passing and rs:
        off = [(fi, sc) for fi, sc in passing if f.loc[fi, "state_key"] not in rs]
        passing = [(fi, sc) for fi, sc in passing if f.loc[fi, "state_key"] in rs]
        if off and not passing:
            fi = off[0][0]
            best_fail = (fi, off[0][1], "row's places are in " + ", ".join(sorted(x.title() for x in rs))
                         + f", candidate in {f.loc[fi, 'state_standard']}")
    if not passing:
        res["best"] = best_fail
        res["outcome"] = best_fail[2] if best_fail else "no GRID3 name scores 50 or more"
        return res
    states = {f.loc[fi, "state_key"] for fi, _ in passing}
    if len(states) > 1:
        kept = [(fi, sc) for fi, sc in passing if _corroborated(f.loc[fi], r["row_clean"])]
        if len({f.loc[fi, "state_key"] for fi, _ in kept}) != 1:
            res["best"] = (passing[0][0], passing[0][1], "candidates in several states")
            res["outcome"] = (f"ambiguous: {len(passing)} candidates in {len(states)} states and the row "
                              "names none of their places")
            return res
        passing = kept
    if len(passing) > A_MAX_CANDIDATES:
        res["best"] = (passing[0][0], passing[0][1], "too many candidates")
        res["outcome"] = f"ambiguous: {len(passing)} candidates"
        return res
    res["accepted"] = passing
    res["outcome"] = "matched"
    return res


def _candidates(r, idx: Index) -> tuple[np.ndarray, list[str]]:
    parts = [idx.by_state[s] for s in r["states"] if s in idx.by_state]
    cand = np.concatenate(parts).astype(int) if parts else np.array([], dtype=int)
    return cand, idx.fac.loc[cand, "name_clean"].tolist()


def tier_a_hits(rows: pd.DataFrame, idx: Index) -> tuple[dict[int, list[Hit]], list[dict]]:
    """Facility names in a feeder's name, location or streets."""
    hits: dict[int, list[Hit]] = defaultdict(list)
    ambiguous = []
    f = idx.fac
    for ri, r in rows.iterrows():
        ms = mentions(r)
        if not ms:
            continue
        cand_idx, names = _candidates(r, idx)
        if len(cand_idx) == 0:
            continue
        for m in ms:
            res = evaluate_mention(m, r, idx, cand_idx, names)
            if res["outcome"].startswith("ambiguous"):
                ambiguous.append({"row_key": r["row_key"], "mention": m.text, "outcome": res["outcome"]})
            for fi, sc in res["accepted"]:
                label = m.text if m.context is None else f"{m.text} (context from {m.context})"
                hits[fi].append(Hit(ri, "facility_name", f.loc[fi, "facility_name"], label, m.field, sc))
    return hits, ambiguous


def _ngrams(seg: str):
    toks = seg.split()
    for n in range(B_MAX_NGRAM, 0, -1):
        for i in range(len(toks) - n + 1):
            nxt = toks[i + n] if i + n < len(toks) else None
            if nxt in ROAD_WORDS:
                continue  # 'UDU ROAD' is a street named after Udu, not Udu
            yield " ".join(toks[i:i + n])


def _is_state_name(ng: str) -> bool:
    """Amendment 1: exact, or rapidfuzz ratio >= B_FUZZY_RATIO for 6+ characters (NASSARAWA)."""
    if ng in STATE_NAMES:
        return True
    return len(ng) >= 6 and process.extractOne(ng, STATE_NAMES, scorer=fuzz.ratio,
                                                score_cutoff=B_FUZZY_RATIO) is not None


def tier_b_hits(rows: pd.DataFrame, idx: Index) -> tuple[dict[int, list[Hit]], list[dict]]:
    """Settlement, ward or LGA names in a feeder's name, location or streets, within the DisCo's states."""
    hits: dict[int, list[Hit]] = defaultdict(list)
    dropped = []
    gaz_names = {s: list(g.keys()) for s, g in idx.gaz.items()}
    for ri, r in rows.iterrows():
        if r["dedicated"]:
            continue  # a dedicated feeder serves one named customer, not a town
        # (state, gazetteer name) -> (ngram, field, score)
        found: dict[tuple[str, str], tuple[str, str, float]] = {}
        for fld in MATCH_FIELDS:
            for seg in segments(r[fld]):
                if is_health_mention(seg) or is_road(seg):
                    continue
                for ng in _ngrams(seg):
                    if not place_is_usable(ng) or _is_state_name(ng):
                        continue
                    for s in r["states"]:
                        g = idx.gaz.get(s)
                        if not g:
                            continue
                        if ng in g:
                            found.setdefault((s, ng), (ng, fld, 100.0))
                        elif len(ng) >= B_FUZZY_MIN_LEN:
                            m = process.extractOne(ng, gaz_names[s], scorer=fuzz.ratio,
                                                   score_cutoff=B_FUZZY_RATIO)
                            if m:
                                found.setdefault((s, m[0]), (ng, fld, float(m[1])))
        if not found:
            continue
        # A name found in more than one of the DisCo's states is kept for a state only if the same row
        # also names an unambiguous place in that state.
        states_of = defaultdict(set)
        for s, n in found:
            states_of[n].add(s)
        unamb_states = {s for (s, n) in found if len(states_of[n]) == 1}
        for (s, n), (ng, fld, sc) in found.items():
            if len(states_of[n]) > 1 and s not in unamb_states:
                dropped.append({"row_key": r["row_key"], "name": n, "states": sorted(states_of[n])})
                continue
            for fi, level, original in idx.gaz[s][n]:
                hits[fi].append(Hit(ri, level, original, ng, fld, sc))
    return hits, dropped


def _bands_from_rows(rows: pd.DataFrame, ris: list[int]) -> dict[str, float]:
    bands = [str(rows.loc[i, "band"]).strip().upper() if pd.notna(rows.loc[i, "band"]) else "?" for i in ris]
    w = 1.0 / len(bands)
    out: dict[str, float] = defaultdict(float)
    for b in bands:
        out[b] += w
    return {k: round(v, 4) for k, v in sorted(out.items())}


def _row_evidence(rows: pd.DataFrame, h: Hit) -> dict:
    r = rows.loc[h.row]
    return {
        "order_file": r["order_file"], "page": int(r["page"]), "sn": _sn(r["sn"]), "row_text": r["row_text"],
        "band": None if pd.isna(r["band"]) else str(r["band"]),
        "min_hours": None if pd.isna(r["min_hours"]) else float(r["min_hours"]),
        "matched_on": h.level, "facility_value": h.matched_text, "nerc_text": h.nerc_text,
        "nerc_field": h.nerc_field, "score": round(h.score, 1),
    }


def _evidence_for(rows: pd.DataFrame, hs: list[Hit]) -> tuple[dict, list[str]]:
    seen, uniq = set(), []
    for h in sorted(hs, key=lambda h: (-h.score, h.row)):
        if h.row not in seen:
            seen.add(h.row)
            uniq.append(h)
    ev = _row_evidence(rows, uniq[0])
    if len(uniq) > 1:
        ev["more"] = [_row_evidence(rows, h) for h in uniq[1:]]
    return ev, [rows.loc[h.row, "row_key"] for h in uniq]


def _bu_for(fr: pd.Series, by_bu: dict) -> tuple[str, str] | None:
    s = fr["state_key"]
    for level, forms in (
        ("settlement_name", [clean(fr["settlement_name"])]),
        ("ward_standard", ward_core(fr["ward_standard"])),
        ("lga_standard", [clean(fr["lga_standard"])]),
    ):
        for n in forms:
            if n and (s, n) in by_bu:
                return n, level
    return None


def _lga_rows(b_hits: dict[int, list[Hit]], f: pd.DataFrame) -> dict[tuple[str, str], dict[int, Hit]]:
    """(state, LGA) -> the rows that name any place in that LGA (the LGA itself, a ward or a settlement)."""
    out: dict[tuple[str, str], dict[int, Hit]] = defaultdict(dict)
    for fi, hs in b_hits.items():
        key = (f.loc[fi, "state_key"], f.loc[fi, "lga_clean"])
        for h in hs:
            cur = out[key].get(h.row)
            if cur is None or LEVELS.index(h.level) < LEVELS.index(cur.level):
                out[key][h.row] = h
    return out


def _band_counts(rows: pd.DataFrame, ris) -> dict[str, int]:
    c: dict[str, int] = defaultdict(int)
    for i in ris:
        b = rows.loc[i, "band"]
        c["?" if pd.isna(b) else str(b).strip().upper()] += 1
    return dict(sorted(c.items()))


def match(facilities: pd.DataFrame, rows: pd.DataFrame, grid: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    idx = prepare_facilities(facilities)
    rows = prepare_rows(rows)
    a_hits, ambiguous = tier_a_hits(rows, idx)
    b_all, dropped = tier_b_hits(rows, idx)
    f = idx.fac
    lga_rows = _lga_rows(b_all, f)
    b_hits = {fi: [h for h in hs if h.level in B_LEVELS] for fi, hs in b_all.items()}
    b_hits = {fi: hs for fi, hs in b_hits.items() if hs}
    by_state, by_bu = footprint.mixtures()
    if grid is not None:
        g = grid.drop_duplicates("unique_id").set_index("unique_id")
        f = f.join(g[["grid_km", "grid_target"]], on="unique_id")
    else:
        f["grid_km"], f["grid_target"] = np.nan, -1

    out = []
    for fi, fr in f.iterrows():
        s = fr["state_key"]
        note = regulators.regulator_note(s)
        gk = fr["grid_km"]
        has_xy = pd.notna(gk)
        far = has_xy and gk > OFFGRID_KM and fr["grid_target"] == 0
        rec = {"unique_id": fr["unique_id"], "grid_km": None if not has_xy else round(float(gk), 3)}
        reasons = []
        lga_key = (s, fr["lga_clean"])
        if fi in a_hits or fi in b_hits:
            tier = "a_named" if fi in a_hits else "b_place"
            hs = a_hits[fi] if tier == "a_named" else b_hits[fi]
            if tier == "b_place":
                best = min(LEVELS.index(h.level) for h in hs)
                hs = [h for h in hs if LEVELS.index(h.level) == best]
            ev, keys = _evidence_for(rows, hs)
            rec.update(tier=tier, bands=_bands_from_rows(rows, sorted({h.row for h in hs})), feeder_ids=keys,
                       evidence=ev)
            reasons.append("facility named in the NERC row" if tier == "a_named"
                           else f"facility's {ev['matched_on'].replace('_standard', '').replace('_name', '')} "
                                f"named in the NERC row")
            if len(keys) > 1:
                reasons.append(f"{len(keys)} rows matched; bands are their equal-weight mixture")
            if far:
                reasons.append(f"Gridfinder line {gk:.1f} km away: check the match or the coordinates")
            if note:
                reasons.append(note)
        elif far:
            rec.update(tier="offgrid", bands={}, feeder_ids=[],
                       evidence={"source": "Gridfinder v1.1.1 grid.gpkg and targets.tif",
                                 "grid_km": round(float(gk), 3), "targets_cell": int(fr["grid_target"])})
            reasons.append(f"no NERC row names it, its ward or its settlement; nearest Gridfinder line {gk:.1f} km "
                           f"(> {OFFGRID_KM:g} km) and its cell is not predicted electrified")
            if note:
                reasons.append(note)
        elif lga_key in lga_rows:
            rmap = lga_rows[lga_key]
            ris = sorted(rmap, key=lambda i: (LEVELS.index(rmap[i].level), -rmap[i].score, i))
            counts = _band_counts(rows, ris)
            n = sum(counts.values())
            first = _row_evidence(rows, rmap[ris[0]])
            rec.update(
                tier="c_lga_mixture",
                bands={b: round(c / n, 4) for b, c in counts.items()},
                feeder_ids=[rows.loc[i, "row_key"] for i in ris],
                evidence={
                    "source": "NERC rows naming a place in the facility's LGA (the LGA, a ward or a settlement)",
                    "state": s.title(), "lga": fr["lga_standard"], "rows_total": n, "band_counts": counts,
                    "order_file": first["order_file"], "page": first["page"], "sn": first["sn"],
                    "row_text": first["row_text"],
                    "rows": [_row_evidence(rows, rmap[i]) for i in ris[:EVIDENCE_ROWS_MAX]],
                },
            )
            reasons.append(f"no NERC row names it, its ward or its settlement; band mixture over {n} rows that "
                           f"name places in {fr['lga_standard']} LGA, one vote per row")
            if not has_xy:
                reasons.append("no coordinates in GRID3: grid distance unknown")
            if note:
                reasons.append(note)
        elif s in regulators.LEFT_NERC:
            rec.update(tier="d_refused", bands={}, feeder_ids=[],
                       evidence={"source": regulators.SOURCE_URL, "quote": regulators.QUOTE_LEFT})
            reasons.append(f"state regulator: {note}")
        elif s in by_state:
            bu = _bu_for(fr, by_bu)
            mix = by_bu[(s, bu[0])] if bu else by_state[s]
            unit = f"business unit {mix['business_unit']} ({s.title()})" if bu else f"state {s.title()}"
            rec.update(tier="c_unit_mixture", bands=mix["weights"], feeder_ids=[],
                       evidence={"source": "naija-grid caps_long.csv, NERC October 2026 cap orders",
                                 "order_month": footprint.MIXTURE_MONTH, "unit": unit,
                                 "unit_matched_on": bu[1] if bu else "state_standard",
                                 "band_counts": mix["counts"], "feeders": mix["n"], "discos": mix["discos"],
                                 "row_text": None})
            reasons.append(f"no NERC row names it or a place in its LGA; band mixture over {mix['n']} feeders "
                           f"of {unit}")
            if not has_xy:
                reasons.append("no coordinates in GRID3: grid distance unknown")
            if note:
                reasons.append(note)
        else:
            rec.update(tier="d_refused", bands={}, feeder_ids=[], evidence={})
            reasons.append("no evidence: no NERC row names it and its state is not in NERC's October 2026 orders")
        rec["reason"] = "; ".join(reasons)
        out.append(rec)

    m = pd.DataFrame(out)
    for c in ("bands", "feeder_ids", "evidence"):
        m[c] = m[c].map(lambda v: json.dumps(v, ensure_ascii=False))
    m = m[["unique_id", "tier", "bands", "feeder_ids", "evidence", "grid_km", "reason"]]
    diag = {"ambiguous_tier_a": ambiguous, "dropped_cross_state_b": dropped, "rows": len(rows),
            "rows_without_disco": int(rows["disco_code"].isna().sum())}
    return m, diag
