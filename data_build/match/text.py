"""Text normalisation and segmentation shared by the matching tiers.

Every rule here is listed in docs/sources/match.md. Changing a word list changes the matches, so a change
after the T2 sample is drawn is an amendment and must be dated there.
"""

from __future__ import annotations

import math
import re
import unicodedata

from rapidfuzz import fuzz

# Abbreviations expanded token by token before any comparison.
ABBREV = {
    "HOSP": "HOSPITAL",
    "HOSPT": "HOSPITAL",
    "GEN": "GENERAL",
    "GENL": "GENERAL",
    "CENTER": "CENTRE",
    "CTR": "CENTRE",
    "CNTR": "CENTRE",
    "MED": "MEDICAL",
    "UNIV": "UNIVERSITY",
    "SPEC": "SPECIALIST",
    "MATERNITY": "MATERNITY",
    "PHC": "PRIMARY HEALTH CENTRE",
    "PHCC": "PRIMARY HEALTH CARE CENTRE",
    "CHC": "COMPREHENSIVE HEALTH CENTRE",
    "FMC": "FEDERAL MEDICAL CENTRE",
    "GH": "GENERAL HOSPITAL",
    "QTRS": "QUARTERS",
    "QTRES": "QUARTERS",
    "GOVT": "GOVERNMENT",
    "RD": "ROAD",
    "STR": "STREET",
    "AVE": "AVENUE",
    # Amendment 2 (tier (a) recall audit): further abbreviations seen in the NERC rows.
    "FED": "FEDERAL",
    "TH": "TEACHING HOSPITAL",
    "UTH": "UNIVERSITY TEACHING HOSPITAL",
    "HOSPITALS": "HOSPITAL",
    "CLINICS": "CLINIC",
    "SPECIALISTS": "SPECIALIST",
    "COLL": "COLLEGE",
    "HQTRS": "HEADQUARTERS",
    "QTR": "QUARTERS",
}

# A segment that contains one of these (after expansion) is read as naming a health facility.
HEALTH_KEYWORDS = {
    "HOSPITAL", "CLINIC", "HEALTH", "MEDICAL", "MATERNITY", "DISPENSARY", "INFIRMARY",
    "SANATORIUM", "POLYCLINIC", "NURSING",
    # Amendment 2: a segment naming one of these is a facility mention even without HOSPITAL.
    "TEACHING", "SPECIALIST", "PSYCHIATRIC",
}
# Amendment 2: an item with one of these names an office, school or housing, not a facility
# ("MINISTRY OF HEALTH", "SCHOOL OF NURSING", "FMC QUARTERS", "COLLEGE OF HEALTH TECHNOLOGY").
NON_FACILITY = {
    "MINISTRY", "SCHOOL", "COLLEGE", "QUARTERS", "BOARD", "OFFICE", "SECRETARIAT", "COMMISSION", "AGENCY",
    "TECHNOLOGY", "SCIENCES", "ROAD",
    # an area around a facility, not the facility ("LAUTECH TEACHING HOSPITAL COMMUNITY", "ADE-OYO HOSPITAL AREA")
    "COMMUNITY", "AREA", "ESTATE", "AXIS", "ENVIRONS", "JUNCTION",
    # a landmark, not the customer ("BEHIND FMC KATSINA", "OPPOSITE PHC CLINIC PILGANI")
    "BEHIND", "OPPOSITE", "BESIDE", "NEAR", "ADJACENT",
}
# Amendment 2: a mention whose type words include one of these but no facility noun gets HOSPITAL added
# ("BAUCHI SPECIALIST" is read as "BAUCHI SPECIALIST HOSPITAL").
IMPLIES_HOSPITAL = {"TEACHING", "SPECIALIST", "GENERAL", "PSYCHIATRIC"}
FACILITY_NOUNS = {"HOSPITAL", "CLINIC", "CENTRE", "HOME", "POST", "DISPENSARY", "INFIRMARY", "POLYCLINIC"}

# Amendment 2: OCR glues words ("MEDICALCENTERGOMBE", "UNIVERSITYOF") and misspells type words
# ("FEDEREAL", "PHYCHIATRIC"). Glued tokens are split around these words; a token of 6+ letters within
# rapidfuzz ratio 88 of one of them is replaced by it (85 turned the place TACHIN into TEACHING).
GLUE_WORDS = [
    "PSYCHIATRIC", "SPECIALIST", "UNIVERSITY", "MATERNITY", "HOSPITAL", "TEACHING", "FEDERAL", "GENERAL",
    "MEDICAL", "CENTER", "CENTRE", "CLINIC", "HEALTH",
]
TYPO_WORDS = [
    "PSYCHIATRIC", "SPECIALIST", "UNIVERSITY", "MATERNITY", "HOSPITAL", "TEACHING", "FEDERAL", "GENERAL",
    "MEDICAL", "CLINIC",
]
TYPO_RATIO = 88

# Words that describe a facility's type. If a NERC mention uses one, the facility name must contain it.
TYPE_WORDS = {
    "HOSPITAL", "CLINIC", "HEALTH", "MEDICAL", "MATERNITY", "CENTRE", "PRIMARY", "GENERAL", "TEACHING",
    "SPECIALIST", "FEDERAL", "COTTAGE", "COMPREHENSIVE", "DISPENSARY", "INFIRMARY", "NURSING", "HOME",
    "POLYCLINIC", "UNIVERSITY", "STATE", "CARE", "POST", "MISSION", "ISLAMIC", "CATHOLIC", "BAPTIST",
    "METHODIST", "ANGLICAN", "MILITARY", "NAVAL", "POLICE", "ARMY", "PSYCHIATRIC", "ORTHOPAEDIC", "EYE",
    "DENTAL", "CHILDREN", "WOMEN", "SPECIALISED", "SPECIALIZED", "REFERENCE",
}

# A segment whose last token is one of these is a street, never a place or a facility.
ROAD_WORDS = {
    "ROAD", "STREET", "ST", "AVENUE", "CLOSE", "CRESCENT", "CRES", "WAY", "LANE", "EXPRESSWAY", "EXPREEWAY",
    "EXPRESS", "DRIVE", "BYPASS", "HIGHWAY", "LINK", "BOULEVARD",
}

# Words with no place identity on their own. A place name made only of these (or of tokens shorter than
# four letters) is never used for tier (b).
GENERIC = {
    "TOWN", "TOWNSHIP", "CENTRAL", "MARKET", "NEW", "OLD", "STATION", "CAMP", "VILLAGE", "COMMUNITY",
    "ESTATE", "INDUSTRIAL", "INDUSTRY", "COMMERCIAL", "AREA", "AREAS", "LAYOUT", "QUARTERS", "HOSPITAL",
    "AIRPORT", "BARRACKS", "UNIVERSITY", "SCHOOL", "CHURCH", "MOSQUE", "PALACE", "GOVERNMENT", "HOUSE",
    "WATER", "WORKS", "URBAN", "RURAL", "NORTH", "SOUTH", "EAST", "WEST", "UPPER", "LOWER", "GRA", "NPA",
    "PART", "PARTS", "THE", "AND", "ETC", "ENVIRON", "ENVIRONS", "DEDICATED", "FEEDER", "FDR", "LINE",
    "MAIN", "CITY", "JUNCTION", "ZONE", "PHASE", "EXTENSION", "SITE", "POLY", "GARAGE", "PARK", "BRIDGE",
    "HILL", "HILLS", "RIVER", "BANK", "FARM", "SECRETARIAT", "STADIUM", "HIGH", "COURT", "PRISON",
    "POLICE", "ARMY", "NAVY", "NAVAL", "BASE", "CANTONMENT", "SHELL", "REFINERY", "OFFICE", "POST",
    "SQUARE", "GATE", "OUTSKIRT", "OUTSKIRTS", "SURROUNDING", "SURROUNDINGS", "UNKNOWN", "WARD", "CORE",
    "SABON", "GARI", "UNGWAN", "ANGWAN", "UNGUWAN", "GIDAN", "KOFAR", "ISALE", "ALONG", "ALL", "OTHER",
    "OTHERS", "BEHIND", "OPPOSITE", "NEAR", "BY", "FIRST", "SECOND", "THIRD", "CIRCULAR",
    "COMPLEX", "HOUSING", "SUMMIT", "CUSTOMERS", "CUSTOMER", "SECTOR", "GOLF", "STATE", "LOCAL",
    "DEPUTY", "GOVERNOR", "COMMISSIONERS", "COMMISSIONER", "CENTRE", "CLINIC", "HEALTH", "MEDICAL",
    "PRIMARY", "GENERAL", "TEACHING", "SPECIALIST", "FEDERAL", "COTTAGE", "BLOCK", "UNIT", "TRANSFORMER",
    "SUBSTATION", "INJECTION", "COMMUNITIES", "VILLAGES", "TOWNS", "SETTLEMENT", "ENVIRONMENT",
    "GABAS", "YAMMA", "AREWA", "KUDU", "TSOHON", "SABUWAR", "BIRNI",
    # Amendment 2: substation and equipment words, never a facility's or a town's name.
    "ISS", "MVA", "KVA", "TCN", "TS", "LEG", "STAFF", "QUARTER", "COLLEGE", "HEADQUARTERS",
    "MINISTRY", "OF", "FOR", "IN", "ON", "AT", "PH", "TRANSMISSION", "POWER", "HOTEL", "PLAZA",
}
ROMAN = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"}

# Periods are not separators: in these lists they mostly end abbreviations (GOVT. HOUSE, E.T.C.).
_SEP = re.compile(r",|;|\||\(|\)|\n| AND | & ")


# Amendment 1: a state's name in a row is the state, not an LGA or ward of the same name
# (Bauchi, Gombe, Katsina, Nasarawa, Ekiti and others are both). Such n-grams are never tier (b) evidence.
STATE_NAMES = {
    "ABIA", "ADAMAWA", "AKWA IBOM", "ANAMBRA", "BAUCHI", "BAYELSA", "BENUE", "BORNO", "CROSS RIVER", "DELTA",
    "EBONYI", "EDO", "EKITI", "ENUGU", "GOMBE", "IMO", "JIGAWA", "KADUNA", "KANO", "KATSINA", "KEBBI", "KOGI",
    "KWARA", "LAGOS", "NASARAWA", "NIGER", "OGUN", "ONDO", "OSUN", "OYO", "PLATEAU", "RIVERS", "SOKOTO",
    "TARABA", "YOBE", "ZAMFARA", "FCT", "ABUJA", "FEDERAL CAPITAL TERRITORY",
}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def clean(s: object) -> str:
    """Uppercase ASCII, punctuation to spaces, abbreviations expanded, spaces collapsed."""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return ""
    t = _ascii(str(s)).upper()
    t = t.replace("&", " AND ")
    t = re.sub(r"\bE\.?\s?T\.?\s?C\.?", " ETC ", t)
    t = t.replace(".", " ")
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    toks = []
    for tok in t.split():
        for piece in _unglue(tok):
            piece = _fix_typo(piece)
            toks.extend(ABBREV.get(piece, piece).split())
    return " ".join(toks)


def _unglue(tok: str) -> list[str]:
    for w in GLUE_WORDS:
        if w in tok and len(tok) >= len(w) + 2:
            i = tok.index(w)
            left, right = tok[:i], tok[i + len(w):]
            return [*(_unglue(left) if left else []), w, *(_unglue(right) if right else [])]
    return [tok]


def _fix_typo(tok: str) -> str:
    if len(tok) < 6 or tok in TYPO_WORDS or tok in ABBREV or not tok.isalpha():
        return tok
    best = max(TYPO_WORDS, key=lambda w: fuzz.ratio(tok, w))
    return best if fuzz.ratio(tok, best) >= TYPO_RATIO else tok


def segments(text: object) -> list[str]:
    """Split one cell of a NERC row into its listed items, each cleaned."""
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return []
    raw = " " + _ascii(str(text)).upper().replace("\n", ", ") + " "
    parts = _SEP.split(raw)
    out = []
    for p in parts:
        c = clean(p)
        if c:
            out.append(c)
    return out


def is_road(seg: str) -> bool:
    toks = seg.split()
    return bool(toks) and toks[-1] in ROAD_WORDS


def is_health_mention(seg: str) -> bool:
    toks = set(seg.split())
    if not toks & HEALTH_KEYWORDS or toks & NON_FACILITY:
        return False
    # a university is a facility mention only when it says hospital ("FED UNIVERSITY OF HEALTH" is not)
    return not ("UNIVERSITY" in toks and "HOSPITAL" not in toks)


def distinctive_tokens(name: str) -> list[str]:
    """Tokens of a facility name that are not type words, generic words or numbers."""
    return [
        t for t in name.split()
        if t not in TYPE_WORDS and t not in GENERIC and t not in ROAD_WORDS and t not in ROMAN
        and not t.isdigit() and len(t) >= 3
    ]


def type_tokens(name: str) -> set[str]:
    return {t for t in name.split() if t in TYPE_WORDS}


def place_is_usable(name: str) -> bool:
    """A gazetteer name is usable when it has at least one non-generic token of four letters or more."""
    return any(len(t) >= 4 and t not in GENERIC and t not in ROAD_WORDS and not t.isdigit()
               for t in name.split())


def ward_core(ward: str) -> list[str]:
    """Forms of a GRID3 ward name to look for: the cleaned name, and each part of a slash-joined name,
    with 'WARD', digits and roman numerals removed (``Ogharefe 2`` gives ``OGHAREFE``)."""
    if not ward:
        return []
    forms = []
    for part in re.split(r"/", _ascii(str(ward))):
        c = clean(part)
        core = " ".join(t for t in c.split() if t != "WARD" and not t.isdigit() and t not in ROMAN)
        for f in (c, core):
            if f and f not in forms:
                forms.append(f)
    return forms


def state_key(s: object) -> str:
    """GRID3 'FCT, Abuja' and naija-grid 'FCT' both become 'FCT'; otherwise uppercase."""
    c = clean(s)
    if c.startswith("FCT") or c in {"ABUJA", "FEDERAL CAPITAL TERRITORY"}:
        return "FCT"
    return c
