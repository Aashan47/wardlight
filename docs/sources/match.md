# Matcher: sources, method and thresholds

Written by build agent B. **The thresholds in section 6 were fixed before
the T2 sample was drawn**, and before the matcher was first run on agent A's full `nerc_rows.parquet`. They
were tuned only on the 30 hand-transcribed rows in `tests/match/fixtures/` and synthetic test facilities.
Any later change is an amendment: date it here, give the reason, and redraw T2 only with a new seed
recorded next to the old one.

Run: `cd build/wardlight && .venv/bin/python -m data_build.match.run` (add `--rebuild` to rebuild
`facilities.parquet` and the grid distances; `--fixture` for a dev run on the hand-transcribed rows that
writes only to `data/work/*_fixture.*`). Tests: `.venv/bin/python -m pytest tests/match`.

## 1. Inputs and licences

| Input | Source | Licence | Integrity |
|---|---|---|---|
| GRID3 NGA Health Facilities v3.0 | `data-local/grid3/grid3_nga_health_facilities_v3_0.gpkg`, HDX, CIESIN Columbia University | CC BY 4.0 (release notes: "licensed under a Creative Commons Attribution 4.0 International License") | SHA-256 db66a553...f81bd (`data-local/MANIFEST.md`) |
| GRID3 NGA Health Facilities v2.0 (amendment 3) | `data-local/grid3-v2/NGA_health_facilities_v2_0.gpkg`, HDX, CIESIN; used only for the 13 states v3.0 lacks | CC BY 4.0 (HDX "Creative Commons Attribution International (CC BY)"; release notes "CC BY 4.0") | SHA-256 cd4b90f8...7318 (MANIFEST section 8) |
| Gridfinder v1.1.1 `grid.gpkg`, `targets.tif` | Zenodo record 3628142, Arderne, Nicolas, Zorn, Koks, DOI 10.5281/zenodo.3628142 | CC BY 4.0 (Zenodo `license.id` `cc-by-4.0`) | MD5 matches Zenodo for both files (MANIFEST) |
| naija-grid `feeders.csv`, `caps_long.csv` | github.com/Godzilla-lab/naija-grid at commit `fcded18e5b31e6efb99f6a21123a316bdf03abb8` | README line 142: "Data: CC BY 4.0 ... Source documents are published by NERC; credit NERC as the original source." | SHA-256 in MANIFEST |
| naija-grid `docs/ANALYSIS.md`, `data/reference/state_regulators.csv`, `bu_state_manual.csv`, `docs/DATA_DICTIONARY.md` | same commit, fetched from raw.githubusercontent.com into `data/work/naija-grid-ref/` | as above | SHA-256 ANALYSIS.md 2dea5855...dc42; state_regulators.csv 7ce20d93...e7d |
| NERC September 2026 orders, Appendix 3 rows | agent A's `data/work/nerc_rows.parquet` | NERC, all rights reserved: cited and linked, never re-hosted | SHA-256 of the file used is recorded in section 9 |

## 2. `facilities.parquet`

The runbook's 13 GRID3 columns plus `source_version`. **Since amendment 3** the file holds GRID3 v3.0 for
the 24 states it covers and GRID3 v2.0 for the 13 it does not; each state comes from one version only
(the build fails otherwise). 61,040 rows: `grid3_v3.0` 41,778 rows in 24 states, `grid3_v2.0` 19,262 rows
in Akwa Ibom, Anambra, Benue, Cross River, Ebonyi, Edo, Ekiti, Imo, Lagos, Ondo, Plateau, Rivers and Taraba.
v2.0 columns map as: `unique_id` = "v2_" + `globalid`; `facility_type` = `facility_level_option` (same
vocabulary as v3.0's `facility_type`); `facility_ownership` = `ownership`; `state_standard` = `state`
spelled as v3.0 spells it (v2.0's "Fct" is not used, since v3.0 holds FCT as "FCT, Abuja"); `lga_standard`
= `lga`; `ward_standard` = `ward`; `settlement_name` empty, `functional` and `flag_count` null (v2.0 has
none of them). All v2.0 rows have coordinates inside Nigeria. The mapping is in
`data_build/match/facilities.py`.

The rest of this section describes v3.0, as first built. 41,778 rows, 41,747 distinct `unique_id`.
**GRID3 v3.0 itself repeats 30 ids** (61 rows, all without coordinates, same name and LGA in the cases
seen); the rows are kept as published and `matches.parquet` keeps the first row of each id, so it has
41,747 rows. 6,004 facilities have no coordinates. GRID3 v3.0 covers **24 states**: Abia, Adamawa, Bauchi,
Bayelsa, Borno, Delta, Enugu, FCT, Gombe, Jigawa, Kaduna, Kano, Katsina, Kebbi, Kogi, Kwara, Nasarawa,
Niger, Ogun, Osun, Oyo, Sokoto, Yobe, Zamfara. Before amendment 3, rows from Edo, Ondo, Ekiti, Lagos, Rivers,
Akwa Ibom, Cross River, Benue, Taraba, Ebonyi, Imo, Anambra and Plateau could match nothing. `settlement_name` is filled
for only 1,739 facilities, so tier (b) rests mostly on ward and LGA names.

## 3. Grid distance (`facility_grid.parquet`: `unique_id, grid_km, grid_target`)

- Lines: `grid.gpkg` read with pyogrio's bbox filter, Nigeria (2.6 to 14.7 E, 4.2 to 13.95 N) plus a 1 degree
  margin: 20,667 line features. Lines across the border count when they are nearest.
- Nearest line: shapely STRtree in an equirectangular plane (110.574 km per degree of latitude, 111.320 x
  cos 9 N per degree of longitude); then every line within 1.1 times that distance is re-measured in a plane
  scaled at the facility's own latitude, and the minimum kept.
- Check: 40 random facilities against a brute-force haversine distance to every vertex of the lines
  densified to 0.0005 degrees: largest difference 0.067 km, which is the densification spacing.
- `grid_target`: `targets.tif` (15 arc-second cells; 1 = predicted connected to the distribution grid, per
  the Zenodo description) read once for the Nigeria window and indexed at the facility's cell; 1 yes, 0 no,
  -1 no coordinates.
- Result: median 0.76 km, 75th percentile 3.95 km, maximum 84.6 km; 12,664 facilities in an electrified
  cell, 23,110 not, 6,004 without coordinates. No facility farther than 5 km sits in an electrified cell.
- After amendment 3 (all 61,040 rows; v3.0 distances recomputed and found identical, largest difference
  0.0 km): median 0.70 km, 75th percentile 3.26 km, maximum 102.1 km; 20,036 in an electrified cell, 35,000
  not, 6,004 without coordinates (all v3.0). 8 facilities farther than 5 km sit in an electrified cell.
  Facilities beyond each distance in a non-electrified cell: 1 km 22,709; 2 km 17,740; 5 km 9,530; 10 km
  3,625; 20 km 933.
- Gridfinder lines are a **model prediction** (2020), not a utility map; the product must say so.

## 4. State regulators (tier `d_refused`, reason "state regulator")

Source: naija-grid `docs/ANALYSIS.md` section 5 at commit `fcded18`
(https://github.com/Godzilla-lab/naija-grid/blob/fcded18e5b31e6efb99f6a21123a316bdf03abb8/docs/ANALYSIS.md):

> "For anyone living in Lagos, Enugu, Imo, Ondo, Ekiti, Kogi, Niger, Plateau, Abia, Bayelsa or Anambra, the
> federal cap no longer appears in NERC's orders. We found no published caps from the state regulators for
> those markets."

> "Six transferred states are still in NERC's orders. Oyo and Edo (deadlines February 2025), Ogun (June
> 2025), Nasarawa (February 2026) and Gombe (July 2026) are all past their transfer deadlines but still
> listed in the October 2026 orders. Akwa Ibom is still within its transition period."

The README (finding 5) says the same. The eleven states in the first quote are refused unless a NERC
September 2026 row names the facility or its place (then it keeps tier a or b, with a note). Of them,
GRID3 v3.0 holds Niger, Kogi, Abia, Enugu and Bayelsa (10,115 facilities). The six still-listed states are
matched normally, with a note in `reason`. naija-grid adds: "A state's presence in NERC's orders is what
NERC published, not a legal statement of who regulates it."

## 5. DisCo footprint and band mixtures

- A row's DisCo comes from its `disco` field, else its file prefix (IE to IKEDC, EKEDP to EKEDC, JED to
  JEDC). Its footprint is every state naija-grid `feeders.csv` lists for that DisCo in any month (Oct 2022
  to Oct 2026, `UNKNOWN` dropped), so September 2026 rows can still match in states that have since left the
  cap orders.
- Tier (c) mixture: share of each band among feeders in the **October 2026** cap orders
  (`caps_long.csv`, `order_month` 2026-10), by state; or by state and business unit when the facility's
  settlement, ward core or LGA name equals a business unit name in its state (`feeders.csv`
  `business_unit`). Ogun's mixture spans IBEDC, IKEDC and EKEDC feeders.

## 6. Matching rules and thresholds (fixed before T2)

Text is cleaned to uppercase ASCII, punctuation to spaces, abbreviations expanded (HOSP, GEN, PHC, FMC,
CHC, CENTER to CENTRE, GOVT, QTRES, RD and others in `data_build/match/text.py`). A row cell is split into
items on commas, semicolons, bars, brackets, line breaks, " AND " and "&" (not on periods, which mostly end
abbreviations). Only a row's **location** and **streets** are searched, as the brief says; feeder names are
not, because they often name the source town (BEDC p.12 S/N 38 "SAPELE (EFFURUN)" serves Effurun).

**Tier (a) `a_named`**, facility named in the row. An item is a facility mention if it contains HOSPITAL,
CLINIC, HEALTH, MEDICAL, MATERNITY, DISPENSARY, INFIRMARY, SANATORIUM, POLYCLINIC or NURSING and does not
end in a road word. A facility in the DisCo's footprint matches when all hold:
1. rapidfuzz `token_set_ratio(mention, name) >= 90`;
2. the mention has at least one distinctive token (not a type, generic or road word, 3+ letters), and each
   is found in the name at rapidfuzz `ratio >= 85` (exact for tokens under 5 letters);
3. every type word in the mention is in the name, and the name's extra type words are only CENTRE, CARE,
   STATE, HOME, POST or HEALTH (so "ASABA GENERAL HOSPITAL" does not match "Asaba Specialist Hospital");
4. the name has at most 1 distinctive token the mention lacks;
5. at most 3 facilities pass for the mention; more is ambiguous and nothing is matched.

**Tier (b) `b_place`**, the facility's settlement, ward or LGA named in the row. Gazetteer per state:
`settlement_name`; `ward_standard` whole and its core (each slash-separated part, with WARD, digits and
roman numerals removed: "Ogharefe 2" gives OGHAREFE); `lga_standard` whole (no direction stripping, so
"Warri South" needs WARRI SOUTH). A name is usable only if it has a non-generic token of 4+ letters (the
generic list includes TOWN, MARKET, GRA, CENTRAL, NORTH, SABON, GARI, GABAS and others in `text.py`).
Row n-grams of 1 to 4 tokens are compared, skipping: items that are facility mentions; items ending in a road
word; any n-gram followed by a road word ("UDU ROAD" is not Udu); and every row whose text says DEDICATED.
- exact match after cleaning; or rapidfuzz `ratio >= 90` for names of 8+ characters;
- a name present in more than one footprint state is kept for a state only if the same row also names an
  unambiguous place in that state;
- per facility only the most specific level is kept (settlement, then ward, then LGA); several rows at that
  level give an equal-weight band mixture.

**Tier (c) `c_unit_mixture`**: no (a) or (b) and the state is in the October 2026 orders: section 5 mixture.

**`offgrid`**: no (a) or (b), `grid_km > 5.0` **and** `grid_target == 0`. Chosen as a judgement (not from a
published rule) before T2; counts of facilities beyond each distance with a non-electrified cell, before
tiers (a) and (b) are applied: 1 km 15,711; 2 km 12,763; **5 km 7,336**; 10 km 2,894; 20 km 592. The
product should show the distance, not just the label. Tier (a) and (b) matches farther than 5 km keep their
tier with a warning in `reason`.

**`d_refused`**: "state regulator" (section 4) or "no evidence" (state not in the October 2026 orders and
no row names it). A facility without coordinates cannot be `offgrid`; it gets (c) or (d) with
"no coordinates" in `reason`.

Precedence: a, b, offgrid, d (state regulator), c, d (no evidence).

### Amendment 1 (after the first full run, before any sample row was checked or opened)

**Change:** a row n-gram equal to a Nigerian state name (36 states, FCT, ABUJA), or within rapidfuzz ratio
90 of one for 6+ characters, is never tier (b) evidence. **Reason:** the first full run's aggregate (not the
sample) showed tier (b) LGA matches driven by text that is a state's name and also an LGA's: NASARAWA 215
facilities, BAUCHI 222, GOMBE 91, KATSINA 98, while rows print state names in their location column (for
example IBEDC "... ORO KWARA STATE", PHED location "RIVERS"). A row naming a state is not evidence of a
feeder in the same-named LGA. **Cost:** real LGAs such as Nassarawa (Kano) and towns printed without
"STATE" lose those matches. No numeric threshold changed. The first draw is kept, unopened, at
`data/work/T2_SAMPLE_v1_superseded.csv` (SHA-256 e69a42e9...ccfe), with `matches_v1_superseded.parquet`
(e4417fca...85e0); T2 is redrawn on the amended matches with the pre-registered seed 20261031.

### Amendment 2 (after amendment 1's run; requested by the coordinator before any T2 row was checked)

Order of events: the coordinator asked for a tier (a) recall audit and for LGA-level evidence to leave tier
(b). The rules below were changed and tested on synthetic facilities and on the audit, the matcher was rerun,
and T2 was redrawn with the pre-registered seed 20261031. The second draw is kept at
`data/work/T2_SAMPLE_v2_superseded.csv` (SHA-256 48e2f455...bc65). Its rows 1 and 2 were seen while
checking that the file had been written (row 1 is quoted under section 9); no row of any draw was checked.
Numeric thresholds 90, 85, 1 and 3 are unchanged.

**Tier (a) changes**
- OCR and abbreviations: words glued to a type word are split ("MEDICALCENTERGOMBE"); a token of 6+
  letters within rapidfuzz ratio 88 of a type word is corrected ("FEDEREAL", "PHYCHIATRIC"; at 85 the
  place TACHIN became TEACHING, so 88); FED, TH, UTH, HOSPITALS, CLINICS and QTR are expanded, as GEN, FMC,
  PHC, CHC and CENTER already were.
- Feeder names are read for facility mentions (feeders are often named after the facility: "FMC GOMBE").
  They are still not read for places.
- TEACHING, SPECIALIST and PSYCHIATRIC mark a mention. TEACHING, SPECIALIST, GENERAL or PSYCHIATRIC with no
  facility noun implies HOSPITAL ("BAUCHI SPECIALIST").
- Not facility mentions: items with MINISTRY, SCHOOL, COLLEGE, QUARTERS, BOARD, OFFICE, SECRETARIAT,
  COMMISSION, AGENCY, TECHNOLOGY, SCIENCES or ROAD; an area (COMMUNITY, AREA, ESTATE, AXIS, ENVIRONS,
  JUNCTION); a landmark (BEHIND, OPPOSITE, BESIDE, NEAR, ADJACENT); UNIVERSITY without HOSPITAL.
- A mention with no distinctive word of its own ("GENERAL HOSPITAL") borrows the distinctive words of the
  row's location, else its feeder name, when there are 1 to 3 of them (a state's name may be one); the
  facility's name must then contain them. The evidence says "(context from location)".
- Word order: token_set_ratio and the set-based word checks ignore order, so "GENERAL HOSPITAL DUTSE"
  matches "Dutse General Hospital".
- UNIVERSITY joins the soft type words. A mention with 2 or more distinctive words of its own may match a
  name with extra type words ("YARIMAN BAKURA HOSPITAL" to "Yariman Bakura Specialist Hospital").
- Candidates in more than one state are kept only if the row names a place (settlement, ward, LGA) of
  candidates in exactly one state; otherwise the mention is refused as ambiguous.
- The audit removed one match that had been wrong: IBEDC p15 S/N 127, an Ogbomoso (Oyo) row whose
  "LAUTECH TEACHING HOSPITAL COMMUNITY" had matched two LAUTECH hospitals in Osun. GRID3 names the Oyo one
  "Ladoke Akintola Teaching Hospital", so an acronym is still a miss.

**Tier (b) and the new tier `c_lga_mixture`**
- Tier (b) keeps only settlement and ward matches.
- `c_lga_mixture`: a facility with no tier (a) or (b) match whose LGA is named by at least one row, either
  through the LGA's own name or through a ward or settlement in it. Its bands are a mixture over all those
  rows, one vote per row (so a feeder printed in several rows counts that many times); `feeder_ids` lists
  every row and `evidence.rows` the first 20, with `band_counts` and `rows_total`.
- Precedence: a, b, offgrid, c_lga_mixture, d (state regulator), c_unit_mixture, d (no evidence). A
  facility more than 5 km from a line with an unelectrified cell is off-grid before any mixture applies.

**Tier (a) audit.** Every row of `nerc_rows.parquet` whose text contains HOSPITAL, MEDICAL, FMC, CLINIC or
HEALTH, one line per facility mention (or per row with none), with the best GRID3 candidate in the DisCo's
states by token_set_ratio and the first rule it failed. Regenerate with
`.venv/bin/python -m data_build.match.audit` (also writes `data/work/tier_a_audit.csv`). Many misses are
rows from places outside GRID3 v3.0 (Edo, Lagos, Rivers, Anambra, Plateau): their best candidate is in
another state and fails on the distinctive word, as it should.

### Amendment 3 (after amendment 2's run; requested by the coordinator before any T2 row was checked)

A data change, not a rule change: GRID3 v2.0 supplies the 13 states that v3.0 lacks (section 2). Order of
events: `facilities.parquet` was rebuilt from both versions, grid distances recomputed for all rows, the
matcher and the tier (a) audit rerun, and T2 redrawn with seed 20261031. Every rule and threshold of
amendments 1 and 2 is unchanged. The third draw is kept at `data/work/T2_SAMPLE_v3_superseded.csv`
(SHA-256 509bff61...9c06), unopened and unchecked, with `matches_v3_superseded.parquet` and the v3.0-only
audit at `data/work/tier_a_audit_v3only_superseded.csv`. v2.0 has no settlement names, so its facilities
reach tier (b) only through ward names.

One rule was added, because the wider coverage exposed a gap the audit showed: EEDC p11 S/N 1 (location
UMUAHIA, in Abia) names "MADONNA HOSPITAL"; Abia's "Madonna Catholic Hospital" fails the type rule, and
with v2.0 an Anambra "Madonna Hospital" passed, since only one candidate passed and the cross-state rule
did not fire. **State check for tier (a):** the row's place names (location, streets and feeder name;
settlement, ward and LGA names, LGA names without NORTH, SOUTH, EAST, WEST or CENTRAL, and state names),
each read only if it occurs in exactly one state of the DisCo's footprint, give the row's states; when
there are any, a candidate in another state is rejected. Checked against the audit: it removes only the
Anambra match and keeps every other. That run's draw had already been written by the time of the rule
change; it is kept unopened at `data/work/T2_SAMPLE_v4_superseded.csv` (SHA-256 5c740d98...), and T2 was drawn again, seed
20261031, after the rule. Agent A rewrote `nerc_rows.parquet` during this step (still 2,188 rows; rows
without an S/N fell from 24 to 1); the final run, its T2 draw and the audit below all used the new file,
whose hash is in section 9.

<!-- tier-a-audit:start -->
79 rows mention a keyword; 88 audit lines (one per mention, or one per row without a mention); 22 rows give at least one tier (a) match.

| Row | DisCo states in GRID3 | Mention as compared | Best GRID3 candidate | Score | Result |
|---|---|---|---|---:|---|
| AEDC p14 S/N 5 | Fct, Kogi, Nasarawa, Niger | GARKI GENERAL HOSPITAL | Garki Hospital (FCT, Abuja) | 100 | name lacks a type word of the mention (GENERAL) |
| AEDC p14 S/N 6 | Fct, Kogi, Nasarawa, Niger | NATIONAL HOSPITAL | National Hospital Abuja (FCT, Abuja) | 85 | **matched** |
| AEDC p14 S/N 7 | Fct, Kogi, Nasarawa, Niger |  |  |  | no facility mention: keyword only in an office, school, quarters or university item (NATIONAL HOSPITAL STAFF QUARTERS) |
| AEDC p15 S/N 37 | Fct, Kogi, Nasarawa, Niger | CBN CLINIC | Cbn Staff Clinic (FCT, Abuja) | 77 | **matched** |
| AEDC p15 S/N 61 | Fct, Kogi, Nasarawa, Niger | STATE HOUSE CLINIC ASOKORO (borrowed from location) | State House Clinic ( Asokoro ) (FCT, Abuja) | 100 | **matched** |
| AEDC p16 S/N 63 | Fct, Kogi, Nasarawa, Niger | STATE HOUSE CLINIC ASOKORO (borrowed from location) | State House Clinic ( Asokoro ) (FCT, Abuja) | 100 | **matched** |
| AEDC p16 S/N 78 | Fct, Kogi, Nasarawa, Niger | GENERAL HOSPITAL ASOKORO | Nasko General Hospital (Niger) | 91 | name lacks a distinctive word of the mention |
| AEDC p17 S/N 92 | Fct, Kogi, Nasarawa, Niger | AFRICAN MEDICAL CENTRE OF EXCELLENCE | Us Medical Center (FCT, Abuja) | 90 | name lacks a distinctive word of the mention |
| AEDC p17 S/N 95 | Fct, Kogi, Nasarawa, Niger |  |  |  | no facility mention: keyword only in an office, school, quarters or university item (MINISTRY OF HEALTH) |
| AEDC p17 S/N 105 | Fct, Kogi, Nasarawa, Niger | WUSE GENERAL HOSPITAL | Wuse General Hospital (FCT, Abuja) | 100 | **matched** |
| AEDC p18 S/N 152 | Fct, Kogi, Nasarawa, Niger | ZITADEL HOSPITAL | Ideal Hospital (Kogi) | 87 | token_set_ratio below 90 |
| AEDC p18 S/N 157 | Fct, Kogi, Nasarawa, Niger | GENERAL HOSPITAL LIFE CAMP | Uke General Hospital (Nasarawa) | 89 | token_set_ratio below 90 |
| AEDC p19 S/N 176 | Fct, Kogi, Nasarawa, Niger | 132KV KUKWABA TS 33KV FDR L33 S25 EYE CLINIC | Aa Clinic (Nasarawa) | 80 | token_set_ratio below 90 |
| AEDC p19 S/N 176 | Fct, Kogi, Nasarawa, Niger | EYE CLINIC LOKOGOMA (borrowed from location) | Aa Clinic (Nasarawa) | 80 | token_set_ratio below 90 |
| AEDC p19 S/N 181 | Fct, Kogi, Nasarawa, Niger | FEDERAL MEDICAL CENTRE IDU (borrowed from location) | Bida Federal Medical Center (Niger) | 94 | name lacks a distinctive word of the mention |
| AEDC p20 S/N 210 | Fct, Kogi, Nasarawa, Niger | AREWA HOSPITAL JABI (borrowed from location) | Arewa Specialist Hospital (FCT, Abuja) | 85 | token_set_ratio below 90 |
| AEDC p20 S/N 215 | Fct, Kogi, Nasarawa, Niger | ABUJA CLINIC | Abuja Clinic Ltd (FCT, Abuja) | 86 | ambiguous: 6 candidates |
| AEDC p21 S/N 223 | Fct, Kogi, Nasarawa, Niger | HOSPITAL DEIDEI (borrowed from location) | Deda Hospital (FCT, Abuja) | 86 | token_set_ratio below 90 |
| AEDC p22 S/N 265 | Fct, Kogi, Nasarawa, Niger | GENERAL HOSPITAL ABAJI (borrowed from location) | Abaji General Hospital (FCT, Abuja) | 100 | **matched** |
| AEDC p22 S/N 266 | Fct, Kogi, Nasarawa, Niger | GENERAL HOSPITAL KWALI (borrowed from location) | Kwali General Hospital (FCT, Abuja) | 100 | **matched** |
| APLE p7 S/N 16 | Abia |  |  |  | no facility mention: keyword only in an office, school, quarters or university item (GENERAL HOSPITAL AREA ETC) |
| BEDC p12 S/N 25 | Delta, Edo, Ekiti, Ondo | OGHARA TEACHING HOSPITAL | Delta State University Teaching Hospital (Delta) | 83 | token_set_ratio below 90 |
| BEDC p12 S/N 25 | Delta, Edo, Ekiti, Ondo | DEDICATED TO OGHARA TEACHING HOSPITAL | Uniben Teaching Hospital (Edo) | 83 | token_set_ratio below 90 |
| BEDC p12 S/N 25 | Delta, Edo, Ekiti, Ondo | OGHARA TEACHING HOSPITAL | Delta State University Teaching Hospital (Delta) | 83 | token_set_ratio below 90 |
| BEDC p12 S/N 41 | Delta, Edo, Ekiti, Ondo | SPECIALIST HOSPITAL |  |  | no distinctive word in the item or its row |
| BEDC p12 S/N 41 | Delta, Edo, Ekiti, Ondo | ASABA GENERAL HOSPITAL | General Hospital (Delta) | 100 | name lacks a distinctive word of the mention |
| BEDC p13 S/N 78 | Delta, Edo, Ekiti, Ondo | PSYCHIATRIC HOSPITAL MBH (borrowed from feeder_name) | Benin Psychiatric Hospital (Edo) | 91 | name lacks a distinctive word of the mention |
| BEDC p14 S/N 108 | Delta, Edo, Ekiti, Ondo | MEDICAL USELU (borrowed from location) | Ray Medical (Ekiti) | 78 | token_set_ratio below 90 |
| BEDC p14 S/N 113 | Delta, Edo, Ekiti, Ondo | NEW GENERAL HOSPITAL |  |  | no distinctive word in the item or its row |
| BEDC p15 S/N 132 | Delta, Edo, Ekiti, Ondo | PART OF MEDICAL OKHORO (borrowed from feeder_name) | Ray Medical (Ekiti) | 78 | token_set_ratio below 90 |
| BEDC p16 S/N 196 | Delta, Edo, Ekiti, Ondo |  |  |  | no facility mention: keyword only in a road name (GENERAL HOSPITAL ROAD) |
| BEDC p18 S/N 261 | Delta, Edo, Ekiti, Ondo | CHILDREN MEDICAL SOKPONBA (borrowed from feeder_name) | God'S Children Medical Centre (Edo) | 78 | token_set_ratio below 90 |
| EEDC p11 S/N 1 | Abia, Anambra, Ebonyi, Enugu, Imo | MADONNA HOSPITAL | Madonna Hospital (Anambra) | 100 | row's places are in Abia, Imo, candidate in Anambra |
| EEDC p13 S/N 85 | Abia, Anambra, Ebonyi, Enugu, Imo | PSYCHIATRIC HOSPITAL ENUGU (borrowed from location) | Neuro-Psychiatric Hospital (Enugu) | 88 | token_set_ratio below 90 |
| EEDC p13 S/N 98 | Abia, Anambra, Ebonyi, Enugu, Imo |  |  |  | no facility mention: keyword only in an office, school, quarters or university item (STATE UNIVERSITY OF MEDICAL) |
| EEDC p14 S/N 116 | Abia, Anambra, Ebonyi, Enugu, Imo |  |  |  | no facility mention: keyword only in a road name (LIFE HOSPITAL ROAD) |
| EEDC p14 S/N 133 | Abia, Anambra, Ebonyi, Enugu, Imo | IBAGWA HEALTH CENTRE | Ibagwa Ezimo Health Centre (Enugu) | 87 | ambiguous: 4 candidates |
| EEDC p14 S/N 154 | Abia, Anambra, Ebonyi, Enugu, Imo | TEACHING HOSPITAL NNEWICHI (borrowed from location) | Mc Hospital (Abia) | 84 | token_set_ratio below 90 |
| EEDC p15 S/N 173 | Abia, Anambra, Ebonyi, Enugu, Imo | IBAGWA HEALTH CENTRE AKU NIKE | Ibagwa Health Centre (Enugu) | 100 | name lacks a distinctive word of the mention |
| EEDC p15 S/N 183 | Abia, Anambra, Ebonyi, Enugu, Imo | AMACHARA GENERAL HOSPITAL | Amachara General Hospital (Abia) | 100 | **matched** |
| IBEDC p11 S/N 7 | Kwara, Ogun, Osun, Oyo | GENERAL HOSPITAL 11KV FEEDER |  |  | no distinctive word in the item or its row |
| IBEDC p15 S/N 127 | Kwara, Ogun, Osun, Oyo |  |  |  | no facility mention: keyword only in an office, school, quarters or university item (LAUTECH TEACHING HOSPITAL COMMUNITY) |
| IBEDC p17 S/N 176 | Kwara, Ogun, Osun, Oyo |  |  |  | no facility mention: keyword only in a road name (HOSPITAL ROAD) |
| IBEDC p18 S/N 205 | Kwara, Ogun, Osun, Oyo |  |  |  | no facility mention: keyword only in an office, school, quarters or university item (ADE OYO HOSPITAL AREA) |
| IBEDC p21 S/N 267 | Kwara, Ogun, Osun, Oyo | SPECIALIST HOSPITAL 11KV FEEDER SOBI (borrowed from location) | Sobi Specialist Hospital (Kwara) | 80 | **matched** |
| IBEDC p21 S/N 267 | Kwara, Ogun, Osun, Oyo | SPECIALIST HOSPITAL SOBI (borrowed from location) | Sobi Specialist Hospital (Kwara); Sobi-Alagbado Specialist Hospital (Kwara) | 100 | **matched** |
| IBEDC p21 S/N 275 | Kwara, Ogun, Osun, Oyo | GENERAL HOSPITAL IJAYE (borrowed from feeder_name) | Hospital (Kwara) | 100 | name lacks a distinctive word of the mention |
| IBEDC p21 S/N 282 | Kwara, Ogun, Osun, Oyo |  |  |  | no facility mention: keyword only in a road name (MOLATORI HOSPITAL ROAD) |
| IBEDC p24 S/N 346 | Kwara, Ogun, Osun, Oyo | HOSPITAL BONOJO (borrowed from feeder_name) | Hospital (Kwara) | 100 | name lacks a distinctive word of the mention |
| IBEDC p24 S/N 351 | Kwara, Ogun, Osun, Oyo |  |  |  | no facility mention: keyword only in a road name (HOSPITAL ROAD) |
| IBEDC p25 S/N 364 | Kwara, Ogun, Osun, Oyo |  |  |  | no facility mention: keyword only in a road name (HOSPITAL ROAD) |
| IBEDC p25 S/N 365 | Kwara, Ogun, Osun, Oyo | GENERAL HOSPITAL ODIGBO (borrowed from location) | Hospital (Kwara) | 100 | name lacks a distinctive word of the mention |
| IKEDC p11 S/N 2 | Lagos, Ogun | IFAKO GENERAL HOSPITAL | Ifako Ijaiye General Hospital (Lagos) | 86 | **matched** |
| JEDC p11 S/N 2 | Bauchi, Benue, Gombe, Plateau | FEDERAL MEDICAL CENTRE AZARE (borrowed from location) | Azare Federal Medical Centre (Bauchi) | 100 | **matched** |
| JEDC p11 S/N 13 | Bauchi, Benue, Gombe, Plateau | TEACHING HOSPITAL BAUCHI (borrowed from location) | Keffi Hospital Bauchi (Bauchi) | 83 | token_set_ratio below 90 |
| JEDC p11 S/N 13 | Bauchi, Benue, Gombe, Plateau | TEACHING HOSPITAL BAUCHI (borrowed from location) | Keffi Hospital Bauchi (Bauchi) | 83 | token_set_ratio below 90 |
| JEDC p11 S/N 13 | Bauchi, Benue, Gombe, Plateau | BAUCHI SPECIALIST HOSPITAL | Bauchi Specialist Hospital (Bauchi) | 100 | **matched** |
| JEDC p12 S/N 38 | Bauchi, Benue, Gombe, Plateau | FEDERAL MEDICAL CENTRE GOMBE (borrowed from location) | Gombe Federal Medical Center (Gombe) | 100 | **matched** |
| JEDC p12 S/N 39 | Bauchi, Benue, Gombe, Plateau | FEDERAL MEDICAL CENTRE GOMBE | Gombe Federal Medical Center (Gombe) | 100 | **matched** |
| JEDC p12 S/N 39 | Bauchi, Benue, Gombe, Plateau | FEDERAL MEDICAL CENTRE GOMBE | Gombe Federal Medical Center (Gombe) | 100 | **matched** |
| JEDC p12 S/N 40 | Bauchi, Benue, Gombe, Plateau | FEDERAL TEACHING HOSPITAL GOMBE (borrowed from location) | Gombe Federal Teaching Hospital (Gombe); Federal Teaching Hospital Gombe (Gombe) | 100 | **matched** |
| JEDC p13 S/N 83 | Bauchi, Benue, Gombe, Plateau |  |  |  | no facility mention: keyword only in an office, school, quarters or university item (FEDERAL UNIVERSITY OF HEALTH) |
| JEDC p15 S/N 168 | Bauchi, Benue, Gombe, Plateau | GENERAL HOSPITAL PANKSHIN | Pankshin General Hospital (Plateau) | 100 | **matched** |
| JEDC p15 S/N 168 | Bauchi, Benue, Gombe, Plateau | GENERAL HOSPITAL PANKSHIN | Pankshin General Hospital (Plateau) | 100 | **matched** |
| JEDC p15 S/N 180 | Bauchi, Benue, Gombe, Plateau |  |  |  | no facility mention: keyword only in an office, school, quarters or university item (OPPOSITE PRIMARY HEALTH CENTRE CLINIC PILGANI) |
| KAEDC p11 S/N 15 | Kaduna, Kebbi, Sokoto, Zamfara | 11KV TEACHING HOSPITAL DKA | 19 Hospital (Kaduna) | 84 | token_set_ratio below 90 |
| KAEDC p12 S/N 28 | Kaduna, Kebbi, Sokoto, Zamfara |  |  |  | no facility mention: keyword only in an office, school, quarters or university item (44 NA R HOSPITAL BADIKKO JUNCTION) |
| KAEDC p12 S/N 31 | Kaduna, Kebbi, Sokoto, Zamfara | ABU TEACHING HOSPITAL SHIKA | 19 Hospital (Kaduna) | 84 | token_set_ratio below 90 |
| KAEDC p12 S/N 46 | Kaduna, Kebbi, Sokoto, Zamfara |  |  |  | no facility mention: keyword only in an office, school, quarters or university item (A A G COLLEGE OF HEALTH TECHNOLOGY) |
| KAEDC p13 S/N 61 | Kaduna, Kebbi, Sokoto, Zamfara | SIR YAHAY HOSPITAL KEBBI | Birnin Kebbi Sir Yahaya Memorial General Hospital (Kebbi) | 86 | token_set_ratio below 90 |
| KAEDC p13 S/N 84 | Kaduna, Kebbi, Sokoto, Zamfara | YARIMAN BAKURA HOSPITAL | Yariman Bakura Specialist Hospital (Zamfara) | 81 | **matched** |
| KAEDC p13 S/N 86 | Kaduna, Kebbi, Sokoto, Zamfara | GENERAL HOSPITAL ANKA | Anka General Hospital (Zamfara) | 100 | **matched** |
| KAEDC p13 S/N 92 | Kaduna, Kebbi, Sokoto, Zamfara | KING FAHAD HOSPITAL | Gusau King Fahad Women And Children Hospital (Zamfara) | 60 | **matched** |
| KAEDC p15 S/N 137 | Kaduna, Kebbi, Sokoto, Zamfara | 11KV TEACHING HOSPITAL ZAR | 19 Hospital (Kaduna) | 84 | token_set_ratio below 90 |
| KEDCO p12 S/N 42 | Jigawa, Kano, Katsina | FEDERAL TEACHING HOSPITAL KATSINA | Rasheed Shekoni Teaching Hospital Federal University Dutse (Jigawa) | 86 | token_set_ratio below 90 |
| KEDCO p13 S/N 102 | Jigawa, Kano, Katsina | GENERAL HOSPITAL DUTSE | Dutse General  Hospital (Jigawa) | 100 | **matched** |
| KEDCO p13 S/N 112 | Jigawa, Kano, Katsina | BICHI GENERAL HOSPITAL | Bichi General Hospital (Kano) | 100 | **matched** |
| KEDCO p14 S/N 143 | Jigawa, Kano, Katsina | 11KV FEDERAL MEDICAL CENTRE GUGA (borrowed from location) | Federal Medical Centre (Jigawa) | 100 | name lacks a distinctive word of the mention |
| KEDCO p14 S/N 146 | Jigawa, Kano, Katsina |  |  |  | no facility mention: keyword only in a road name (11KV HOSPITAL ROAD) |
| PHED p11 S/N 19 | Akwa Ibom, Bayelsa, Cross River, Rivers |  |  |  | no facility mention: keyword only in a road name (HOSPITAL ROAD) |
| PHED p15 S/N 141 | Akwa Ibom, Bayelsa, Cross River, Rivers |  |  |  | no facility mention: keyword only in a road name (BORROW PIT PSYCHIATRIC HOSPITAL ROAD) |
| PHED p17 S/N 196 | Akwa Ibom, Bayelsa, Cross River, Rivers | HOSPITAL AMADI (borrowed from feeder_name) | Handmaid Hospital (Akwa Ibom) | 84 | token_set_ratio below 90 |
| PHED p17 S/N 215 | Akwa Ibom, Bayelsa, Cross River, Rivers | HEALTH CENTRE RAILWAY (borrowed from feeder_name) | Atia Health Center (Akwa Ibom) | 87 | token_set_ratio below 90 |
| PHED p17 S/N 219 | Akwa Ibom, Bayelsa, Cross River, Rivers |  |  |  | no facility mention: keyword only in an office, school, quarters or university item (SCHOOL OF HEALTH) |
| YEDC p11 S/N 29 | Adamawa, Borno, Taraba, Yobe | YOBE STATE TEACHING HOSPITAL | Yo Yobe State University Teaching Hospital Damaturu (Yobe); Yobe State University Teaching Hospital (Yobe) | 84 | **matched** |
| YEDC p12 S/N 37 | Adamawa, Borno, Taraba, Yobe | 11KV FEDERAL MEDICAL CENTRE |  |  | no distinctive word in the item or its row |
| YEDC p12 S/N 47 | Adamawa, Borno, Taraba, Yobe | 11KV TEACHING HOSPITAL MERI NGOMAR COUSTAIN (borrowed from location) | City Hospital (Borno) | 76 | token_set_ratio below 90 |
| YEDC p14 S/N 128 | Adamawa, Borno, Taraba, Yobe | HOSPITAL GRA WUKARI (borrowed from location) | Wukari General Hospital (Taraba) | 90 | name has another type word (GENERAL) |
<!-- tier-a-audit:end -->

## 7. Output (`matches.parquet`)

One row per distinct `unique_id`: `unique_id, tier, bands` (JSON `{band: weight}`), `feeder_ids` (JSON list
of `order_file#p<page>#sn<S/N>`, `#i<index>` where A found no S/N), `evidence` (JSON: `order_file, page,
sn, row_text` as the contract asks, plus `band, min_hours, matched_on, facility_value, nerc_text,
nerc_field, score`, and `more` for further rows; for `c_lga_mixture` the rows naming places in the LGA
(amendment 2); for `c_unit_mixture` the naija-grid counts; for offgrid the
distance; for refusals the quote), `grid_km`, `reason`. `row_text` is "feeder name | location | streets"
as A read them.

## 8. Fixture and cross-check with agent A

`tests/match/fixtures/bedc_sep2026_p12_rows.csv`: BEDC September 2026 order, PDF page 12, S/N 25 to 54,
transcribed by eye from page renders (pypdfium2, 110 and 220 dpi), spelling as printed
("EXPREEWAY", "MID WIFERY"). Against A's `nerc_rows.parquet` (SHA-256 a5c64419...6a587): band, feeder
name, location, streets and hours agree on 30 of 30 rows after cleaning; **A read S/N 41 as 4**.

## 9. Runs and T2

<!-- current-run:start -->
**Current run** (after amendment 3), on `nerc_rows.parquet` SHA-256 `a0b8a933cc93a37dce00d47921956f50f1ba39ebcef086dacc0d7f2d9500d4c9`; `matches.parquet` SHA-256 `7d90696e79639c0325cb363679387fe25f9064b46826a99b4f13fd4d93a3eeae`.

| Tier | Facilities | Share |
|---|---:|---:|
| a_named | 23 | 0.0% |
| b_place | 9,765 | 16.0% |
| c_lga_mixture | 26,402 | 43.3% |
| c_unit_mixture | 6,824 | 11.2% |
| d_refused | 8,938 | 14.7% |
| offgrid | 9,057 | 14.8% |
| total | 61,009 | |

Tier (b) by level: ward_standard 9,410, settlement_name 355. `c_unit_mixture` by business unit: 35. Refusal reasons: state regulator 8,938. Tier (a) or (b) in states that have left NERC: 2,051; more than 5 km from a line: 473.

**T2 sample:** `docs/T2_SAMPLE.csv`, 100 rows drawn with `pandas.DataFrame.sample(random_state=20261031)` from the tier (a) and (b) matches sorted by `unique_id` (b_place 100; by level ward_standard 96, settlement_name 4); SHA-256 `9bdd4b10e687b6578802e87c0b151fd577caabb5d64f04c08325699da1492a61`. **Unchecked**: `correct`, `checked_by` and `note` are empty for a human to fill by comparing the facility's fields with `row_text` and the page image. Tier (a) matches are few; check all of them as well, outside T2.
<!-- current-run:end -->

**Superseded run (amendment 1 only)**, on agent A's `nerc_rows.parquet` of 14:53 PKT (2,188 rows, SHA-256
a5c644194fae31ad920d99524f3cee670d1d5e58f7c59823682967125c386587), with amendment 1. `matches.parquet`
SHA-256 590dd5af...78d0. A had not yet passed T1 when this ran; when A's rows change, rerun and redraw.

| Tier | Facilities | Share of 41,747 |
|---|---:|---:|
| a_named | 11 | 0.03% |
| b_place | 17,798 (LGA 10,658; ward 6,784; settlement 356) | 42.6% |
| c_unit_mixture | 11,677 (662 by business unit, the rest by state; 2,008 without coordinates) | 28.0% |
| d_refused | 7,626, all "state regulator" (Niger, Kogi, Abia, Enugu, Bayelsa); 0 "no evidence" | 18.3% |
| offgrid | 4,635 (1,093 of them in states that have left NERC) | 11.1% |

Notes: 1,396 tier (a) or (b) matches are in states that have left NERC (a September 2026 row still names
their place); 2,701 tier (a) or (b) matches are more than 5 km from a Gridfinder line and carry a warning;
7,517 of them rest on more than one row (equal-weight mixture). 324 cross-state names were dropped for lack
of corroboration. **Tier (b) is mostly LGA-level**: a row naming an LGA's town assigns every facility in
that LGA, which is coarse; T2 will measure it. Before amendment 1 the counts were a 11, b 18,568, c 11,034,
d 7,614, offgrid 4,520.

**T2 sample of that run (superseded, now `data/work/T2_SAMPLE_v2_superseded.csv`):** 100 rows drawn with `pandas.DataFrame.sample(random_state=20261031)`
from the tier (a) and (b) matches sorted by `unique_id`; SHA-256 48e2f455...bc65. It holds 100 tier (b)
rows (65 LGA, 34 ward, 1 settlement) and no tier (a) row, since only 11 of 17,809 matches are tier (a).
**Unchecked.** The `correct`, `checked_by` and `note` columns are empty for a human to fill by comparing
the facility's fields with `row_text` (and the page image). The 11 tier (a) matches are few enough to
check all of them separately; they are not part of T2.

**Known risk, seen when the file was written and left unchanged (no rule edited after the draw):** the
cross-state rule only works for states GRID3 holds. A place in a footprint state missing from GRID3 v3.0
(Lagos for IKEDC and EKEDC, Edo for BEDC, Plateau for JEDC, and others) cannot make a name ambiguous, so
it can match a same-named ward in a GRID3 state. Example, sample row 1: IKEDC's Ikorodu row lists
"KETU EPE" (Lagos), matched to Ketu ward in Ado Odo/Ota, Ogun.
