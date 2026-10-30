"""Static source list for /api/health and the quotes on /api/summary. Text and links only; no figures.

Every entry is one already listed in 06-PRODUCT-DESIGN.md, docs/sources/engine.md or data-local/MANIFEST.md.
"""

from __future__ import annotations

import re
from pathlib import Path

SOURCES = [
    {"name": "NERC multi-year tariff orders, September 2026 (feeder bands and minimum hours, 11 DisCos), and the "
             "Aba Power order of February 2025",
     "url": "https://nerc.gov.ng/media/september-2026-myto/",
     "licence": "Regulatory publication, licence not stated: cited, never re-hosted", "retrieved": "2026-10-27"},
    {"name": "GRID3 Nigeria Health Facilities v3.0 (24 states) and v2.0 (the 13 states v3.0 lacks)",
     "url": "https://data.humdata.org/", "licence": "CC BY 4.0", "retrieved": "2026-10-27"},
    {"name": "naija-grid (feeder band history and NERC monthly energy caps, ANALYSIS.md section 5)",
     "url": "https://github.com/Godzilla-lab/naija-grid", "licence": "MIT", "retrieved": "see docs/sources/match.md"},
    {"name": "Gridfinder, predictive mapping of the global power system (Zenodo 3628142)",
     "url": "https://zenodo.org/records/3628142", "licence": "CC BY 4.0", "retrieved": "2026-10-27"},
    {"name": "NASA POWER hourly API (GHI and 2 m temperature, 2021 to 2023)",
     "url": "https://power.larc.nasa.gov/docs/services/api/temporal/hourly/",
     "licence": "CC0 (NASA ESDS data policy), citation requested", "retrieved": "2026-10-27"},
    {"name": "WorldPop Nigeria 2026, constrained, R2025A v1 (DOI 10.5258/SOTON/WP00839)",
     "url": "https://hub.worldpop.org/geodata/summary?id=78608", "licence": "CC BY 4.0", "retrieved": "2026-10-27"},
    {"name": "WHO PQS E003/RF05.3 and RF03-VP.2 (2 to 8 degC rule, holdover definition) and product sheets",
     "url": "https://extranet.who.int/prequal/sites/default/files/document_files/PQS%20E03%20RF3-VP.2.pdf",
     "licence": "WHO document, no licence statement found", "retrieved": "2026-10-27"},
    {"name": "WHO PQS E003/PV01.3 (no other loads on a PQS solar fridge system)",
     "url": "https://extranet.who.int/prequal/sites/default/files/document_files/WHO%20PQS%20E003-PV01_3_20151116.pdf",
     "licence": "WHO document, no licence statement found", "retrieved": "2026-10-27"},
    {"name": "SEforALL, Powering Healthcare: Nigeria technology roadmap (load table, $/Wp, system range)",
     "url": "https://www.seforall.org/system/files/2022-06/Nigeria_technology_0.pdf",
     "licence": "Not stated in the PDF", "retrieved": "2026-10-27"},
    {"name": "Energizing Health (WHO, World Bank, IRENA, SEforALL, 2023), Table 3.1",
     "url": "https://www.seforall.org/system/files/2023-01/energizing_health.pdf", "licence": "CC BY-NC-SA 3.0 IGO",
     "retrieved": "2026-10-27"},
    {"name": "World Bank, crude birth rate, Nigeria (SP.DYN.CBRT.IN)",
     "url": "https://api.worldbank.org/v2/country/NGA/indicator/SP.DYN.CBRT.IN?format=json&per_page=20",
     "licence": "CC BY 4.0", "retrieved": "2026-10-27"},
    {"name": "Chojnacky and Rodriguez (NIST), PLOS ONE, domestic fridge hold time without power",
     "url": "https://doi.org/10.1371/journal.pone.0235777", "licence": "CC0", "retrieved": "see docs/sources/engine.md"},
    {"name": "US EPA GHG Emission Factors Hub 2025 (diesel 10.21 kg CO2 per gallon)",
     "url": "https://www.epa.gov/system/files/documents/2025-01/ghg-emission-factors-hub-2025.pdf",
     "licence": "US government work", "retrieved": "2026-10-27"},
    {"name": "Central Bank of Nigeria exchange rates", "url": "https://www.cbn.gov.ng/rates/ExchRateByCurrency.html",
     "licence": "Not stated", "retrieved": "2026-10-27"},
]

QUOTES = [
    {"text": "Close to one billion people globally are served by health-care facilities with no electricity access "
             "or with unreliable electricity",
     "source": "WHO news release, 14 January 2023",
     "url": "https://www.who.int/news/item/14-01-2023-close-to-one-billion-people-globally-are-served-by-health-care-"
            "facilities-with-no-electricity-access-or-with-unreliable-electricity"},
    {"text": "The acceptable temperature range for storing vaccine is +2°C to +8°C.",
     "source": "WHO PQS E003/RF03-VP.2, p. 2",
     "url": "https://extranet.who.int/prequal/sites/default/files/document_files/PQS%20E03%20RF3-VP.2.pdf"},
    {"text": "No additional loads, such as lighting or pumping, are to be connected to the solar power system.",
     "source": "WHO PQS E003/PV01.3, p. 4",
     "url": "https://extranet.who.int/prequal/sites/default/files/document_files/WHO%20PQS%20E003-PV01_3_20151116.pdf"},
]

_URL_RE = re.compile(r"https://nerc\.gov\.ng/wp-content/uploads/\S+?\.pdf")


def nerc_urls(manifest: Path) -> dict[str, str]:
    """order file name -> its NERC URL, from data-local/MANIFEST.md section 3 (empty when absent)."""
    out: dict[str, str] = {}
    try:
        text = manifest.read_text(encoding="utf-8")
    except OSError:
        return out
    for url in _URL_RE.findall(text):
        out.setdefault(url.rsplit("/", 1)[-1], url)
    return out
