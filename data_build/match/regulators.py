"""States that have left NERC's orders for a state regulator, from naija-grid at commit fcded18.

Source: https://github.com/Godzilla-lab/naija-grid/blob/fcded18e5b31e6efb99f6a21123a316bdf03abb8/docs/ANALYSIS.md
section 5, and README.md finding 5 at the same commit (data CC BY 4.0, credit NERC).
"""

from __future__ import annotations

SOURCE_URL = (
    "https://github.com/Godzilla-lab/naija-grid/blob/fcded18e5b31e6efb99f6a21123a316bdf03abb8/docs/ANALYSIS.md"
)

QUOTE_LEFT = (
    "For anyone living in Lagos, Enugu, Imo, Ondo, Ekiti, Kogi, Niger, Plateau, Abia, Bayelsa or Anambra, "
    "the federal cap no longer appears in NERC's orders. We found no published caps from the state "
    "regulators for those markets."
)
QUOTE_STILL_LISTED = (
    "Six transferred states are still in NERC's orders. Oyo and Edo (deadlines February 2025), Ogun (June "
    "2025), Nasarawa (February 2026) and Gombe (July 2026) are all past their transfer deadlines but still "
    "listed in the October 2026 orders. Akwa Ibom is still within its transition period."
)

# The eleven states named in QUOTE_LEFT, keyed as text.state_key() produces them.
LEFT_NERC = {
    "LAGOS": "LASERC", "ENUGU": "EERC", "IMO": "ISERC", "ONDO": "OSERB", "EKITI": "EERB", "KOGI": "KSERC",
    "NIGER": "NSERC", "PLATEAU": "PSERC", "ABIA": "ASERA", "BAYELSA": "BYERA", "ANAMBRA": "ASERC",
}
# Acronyms from naija-grid data/reference/state_regulators.csv at the same commit.

# Transferred in law but still in NERC's October 2026 orders: matched normally, with a note.
STILL_LISTED_AFTER_TRANSFER = {"OYO", "EDO", "OGUN", "NASARAWA", "GOMBE", "AKWA IBOM"}


def regulator_note(state: str) -> str | None:
    if state in LEFT_NERC:
        return (f"{state.title()} has left NERC's orders for its state regulator ({LEFT_NERC[state]}); "
                "naija-grid ANALYSIS.md section 5")
    if state in STILL_LISTED_AFTER_TRANSFER:
        return (f"{state.title()} has a NERC transfer order to a state regulator but is still listed in "
                "NERC's October 2026 orders; naija-grid ANALYSIS.md section 5")
    return None
