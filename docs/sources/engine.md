# Engine: every constant, its source, and the model

Scope: `engine/` (solar, supply, fridge, loads, sim, size, doses, econ, plan, batch). The machine-readable
registry is `engine/constants.py`; `tests/engine/test_constants.py` checks that every constant has a source and
a status, and that every UNVERIFIED value or ASSUMPTION is a range that contains its default.

"SV" means `SOURCES-VERIFIED.md` in the project's `research-raw/` folder (section and row). "PDF" means a file in
`data-local/reference-pdfs/`. Status: VERIFIED, VERIFIED (secondary), DERIVED (arithmetic on verified rows),
UNVERIFIED (shown only as a range), ASSUMPTION (a modelling choice, shown as a range, editable).

## Constants

| Constant | Value (range) | Source | Status |
|---|---|---|---|
| Vaccine storage range | +2 to +8 degC | SV 1a row 1; PQS E003/RF05.3 p.3, RF03-VP.2 p.2 | VERIFIED |
| Holdover end point | +10 degC | SV 1a rows 3-4 (holdover is measured to +10, so it is an upper bound on time at or below +8) | VERIFIED |
| PQS test ambient | 43 degC | SV 1a rows 6 and 8 | VERIFIED |
| Ice-lined recharge | 2 h of holdover per powered hour (lower bound) | SV 1a row 7: PQS RF03-VP.2 p.8 passes units on 16 h off / 8 h on | DERIVED |
| SDD reference irradiance | 3.5 kWh/m2/day | PDF `who_pqs_E003_RF05.3.pdf` p.4; printed on every Dulas sheet (SV 1b) | VERIFIED |
| SDD array, plausibility range | 160 to 500 W | SV 3a row 4, Energizing Health Table 3.1, PDF p.99-100 | VERIFIED |
| No other loads on a PQS solar fridge | rule | SV 1a row 12, PQS PV01.3 p.4 | VERIFIED |
| Share of PQS holdover spent at or below +8 degC | 0.75 (0.5 to 1.0) | none; 1.0 is the PQS upper bound | ASSUMPTION |
| Cabinet setpoint for heat-leak scaling | 5 degC (4 to 6) | midpoint of the PQS range | ASSUMPTION |
| Fridge models (holdover, energy, litres, price) | 10 sheets | SV 1b; PDFs `who_pqs_E003-0xxe.pdf`, p.1 | VERIFIED |
| Excluded models | E003-059e, E003-084e | SV 1b: printed energy 5.0 and 78.0 kWh/24h are data-entry errors | VERIFIED as printed |
| Crude birth rate | 32.493 per 1,000 | SV 2 row 4, World Bank SP.DYN.CBRT.IN, 2024, CC BY 4.0 | VERIFIED |
| Doses per child in year one | 20 (20 to 23 with malaria vaccine) | SV 2, derived from the NPHCDA FHIR guide, an unofficial CI build | VERIFIED (secondary) |
| Type 2 PHC population served (check only) | 10,000 to 20,000 | SV 3b row 7, SEforALL technology PDF p.11 | VERIFIED |
| Catchment radius | 5 km (3 to 10) | none | ASSUMPTION |
| Band minimum hours | A 20, B 16, C 12, D 8, E 4 | NERC APLE order p.5 s.10(g) for A; confirmed for all bands as the modal printed value in agent A's `nerc_rows.parquet` (A 20 in 854 rows, B 16 in 332, C 12 in 398, D 8 in 351, E 4 in 197; 4 outliers are OCR noise) | VERIFIED (data) |
| Outages per month | 32.8 | SV 3c row 1, Enterprise Survey, Nigeria 2014 | VERIFIED |
| Hours per outage (consistency check only) | 11.6 | SV 3c row 2 | VERIFIED |
| SEforALL Type 2 PHC load table | 18 rows, 36,046 Wh/day | SV 3b row 6 (11 rows) plus the 7 rows SV did not quote, PDF `seforall_Nigeria_technology_0.pdf` p.10; with them the rows sum to the printed total | VERIFIED |
| Load wattage ranges (comparison) | per load | SV 3a, Energizing Health Table 3.1, PDF p.99-100 | VERIFIED |
| Time of day of each load | windows in `engine/loads.py` | none; critical loads placed at night (conservative) | ASSUMPTION |
| Installed cost | $6.0/Wp ($5.3 to $6.5) | SV 3b rows 1-2, SEforALL p.3 and p.16 | VERIFIED |
| Battery per kWp in that price | 7.2 kWh/kWp | 36/5 = 72/10, SEforALL p.11 (SV 3b row 4) | DERIVED |
| SEforALL Type 2 PHC system (T5 check) | 5 to 10 kWp, 36 to 72 kWh | SV 3b row 4 | VERIFIED |
| O&M, life, replacement | 5%/yr, 15 yr, 15% at year 10 | SV 3b row 3, SEforALL p.16 | VERIFIED |
| Battery usable share | 0.8 (0.5 to 0.9) | none | ASSUMPTION |
| Battery round-trip efficiency | 0.9 (0.8 to 0.95) | none | ASSUMPTION |
| Grid charging rate | 0.2 C (0.1 to 0.5) | none | ASSUMPTION |
| Load-shedding reserve for priority 2 and 3 | 0.5 of usable battery (0.3 to 0.7) | none | ASSUMPTION |
| PV system losses | 14% (10 to 20) | none (14 is the PVGIS form default; checked by T4) | ASSUMPTION |
| PV temperature coefficient | -0.4%/degC (-0.5 to -0.3) | none | ASSUMPTION |
| PV NOCT | 45 degC (42 to 48) | none | ASSUMPTION |
| Exchange rate | N1,352.371 per USD | SV 5 row 1, CBN central rate on the day the sources were verified | VERIFIED |
| Diesel price | N3,277.47/L (low end N1,441.28) | NBS Diesel Price Watch May 2026, national average, via 21st Century Chronicle, Legit, The Sun (four outlets agree); low end SV 4 row 1 (NBS Oct 2024). Borno April 2026: N2,684.95 | VERIFIED (secondary) |
| Generator fuel use, clinic set | 0.55 L/kWh (0.40 to 0.73) | Cummins C17 D5 and C22 D5 prime fuel tables at 1/4 to 1/2 load; A2EI measured 22% average load (brief13-sources Q1). Replaces the earlier vendor-chart range 0.303 to 0.454 (SV 4 row 10); stored litres were rescaled by `engine.augment` | DERIVED |
| CO2 per litre of diesel | 2.697 kg | SV 4 row 6, EPA 10.21 kg/gal over 3.785 L/gal | DERIVED |
| EUR rate | N1,508.0289 per EUR | CBN https://www.cbn.gov.ng/api/GetAllExchangeRates, record id 65267 ('EURO', centralrate '1508.0289'), same rate date as the USD row of SV 5 (record id 65274 in the same response, centralrate '1352.3710') | VERIFIED |
| EUR to USD (Dulas prices only) | 1.1151 | CBN EUR central / CBN USD central, same day | DERIVED |
| Domestic or non-PQS fridge: hours at 2 to 8 degC without power | 4 (1.5 to 6) | Chojnacky and Rodriguez (NIST), PLOS ONE, DOI 10.1371/journal.pone.0235777, CC0, full text via Europe PMC (PMC7343171): 'maintaining vaccine temperatures between 2 degC and 8 degC for 4 to 6 hours without power' (10 to 15% water ballast); 'a 10% ballast load can be expected to provide about 4 hours'; shelf tests: 'too-warm temperature excursions within the first 1.5 hours of the outage period'. Lab tests on two US domestic units; ambient not stated, so no ambient scaling: probably generous for a hot clinic | VERIFIED |
| Domestic fridge recovery after power returns | 1 h (0.5 to 2) | none (no ice lining to refreeze) | ASSUMPTION |
| Equipment availability (breakdowns, spares, repair) | 0.95 (0.90 to 0.99) | SCENARIO VALUE: field functionality figures were searched for and none could be verified (a Benue State conference abstract returned HTTP 404) | ASSUMPTION |
| SDD array soiling | 0.95 (0.90 to 1.0) | SCENARIO VALUE | ASSUMPTION |
| Fridge life for cost per month | 10 years | PDF `who_pqs_E003_RF05.3.pdf` p.8 s.4.9: SDD 'designed to achieve a low-maintenance life of not less than 10 years'; used for ice-lined units as a scenario value | VERIFIED (SDD) |
| Catchment cap | 20,000 people per facility | SV 3b row 7, SEforALL p.11: a Type 2 PHC serves 10,000 to 20,000; applied to every facility level (a scenario choice for hospitals) | VERIFIED |
| Cold-chain fix prices | ILR: Haier HBC-80 USD 860, HBC-150 USD 999, HBC-260 USD 1,283, HBCD-90 USD 1,575 (base 2021); SDD: Dulas VC200SDD EUR 5,650, VC150SDD EUR 6,995 (base 2026) | SV 1b, PQS product sheets p.1 (`who_pqs_E003-0xxe.pdf`); EXW, exclude freight, installation and (Haier) the voltage regulator. UNICEF Supply Catalogue prices were not opened | VERIFIED |

<!-- brief13-constants:start (generated by python -m engine.sources_doc; do not edit by hand) -->
## Brief 13 constants (water, cold chain, generators, gas plant, roofs)

Full quotes and grades: `docs/sources/brief13-sources.md`. The generator curve `GEN_L_PER_KWH` (clinic set) is used for health facilities in the batch and the outage scenario; `GEN_L_PER_KWH_MID` for boreholes, cold rooms and the water works (`engine/metrics13.py`).

| Constant | Value (range) | Unit | Source | Status |
|---|---|---|---|---|
| `DIESEL_NGN_PER_L` | 3,277 (1,441 to 3,277) | NGN per litre | NBS Diesel Price Watch May 2026 via 21st Century Chronicle, Legit, The Sun; four outlets agree (N3,277.47 per litre, national average, up 86.40% from N1,758.26 in May 2025; brief 13 ref. 10, Legit.ng). The NBS page itself was not opened (blocked). lo = NBS Oct 2024, N1,441.28 (SOURCES-VERIFIED.md 4 rows 1-2), kept only as the low end Note: National average. Borno April 2026 was N2,684.95 (Legit.ng, NBS); Borno was not in May 2026's top 10 (tenth: N3,388.85). North-West zone May 2026: N3,313.60. | VERIFIED_SECONDARY |
| `GEN_L_PER_KWH` | 0.55 (0.4 to 0.73) | litres per kWh | Clinic set (15 to 20 kVA at 20 to 50% load): Cummins C17 D5 (DS338) and C22 D5 (DS340) prime fuel tables, 0.63 to 0.73 L/kWh at 1/4 load and 0.40 to 0.47 at 1/2 load; point = interpolation at about 1/3 load; A2EI (2022) measured Nigerian market sets at 22% average load (docs/sources/brief13-sources.md Q1). Replaces the earlier UNVERIFIED vendor-chart range 0.303 to 0.454 (SOURCES-VERIFIED.md 4 row 10) Note: Spec sheets are VERIFIED primary; the load fraction is the derived step. Used for health facilities. | DERIVED |
| `GEN_L_PER_KWH_MID` | 0.34 (0.31 to 0.4) | litres per kWh | 20 to 60 kVA set at 50 to 100% load: Cummins C22 D5 1/2 to full and C90 D5 (DS380) 1/4 to full prime tables, HOMER Pro 3.16 manual worked example 0.31 to 0.34 (docs/sources/brief13-sources.md Q1) Note: Used for boreholes, market cold rooms and the water works. A set idling at 1/4 load burns up to 0.63. | DERIVED |
| `GEN_OM_USD_PER_KWH` | 0.03 | USD per kWh | NESG and Heinrich Boell Stiftung, 'Comparison of Costs of Electricity Generation in Nigeria' (June 2017), Annex 'Diesel off-grid' 10 kW set: 'Variable O & M $/kWh ... 0,03' (REEEP and NESP 2016 data); brief13-sources Q2 Note: 2016 data; no current Nigerian figure was found. | VERIFIED_SECONDARY |
| `GEN_LIFE_YEARS` | 10 | years | same NESG/Boell Annex: 'Technical lifetime yr ... 10' (diesel off-grid, REEEP and NESP 2016) | VERIFIED_SECONDARY |
| `GENSET_15KVA_NGN` | 8,300,000 | NGN per set | Zit Electronics (Nigerian online retailer), Perkins soundproof diesel sets, https://www.zit.ng/collections/perkins, accessed Oct 2026 (one retailer, Lagos prices, delivery to Maiduguri not included); brief13-sources Q2: 'Perkins 15Kva ... N8,300,000' | VERIFIED_SECONDARY |
| `GENSET_20KVA_NGN` | 9,300,000 | NGN per set | Zit Electronics (Nigerian online retailer), Perkins soundproof diesel sets, https://www.zit.ng/collections/perkins, accessed Oct 2026 (one retailer, Lagos prices, delivery to Maiduguri not included); brief13-sources Q2: 'Perkins UK 20kva ... N9,300,000' | VERIFIED_SECONDARY |
| `GENSET_30KVA_NGN` | 9,960,000 | NGN per set | Zit Electronics (Nigerian online retailer), Perkins soundproof diesel sets, https://www.zit.ng/collections/perkins, accessed Oct 2026 (one retailer, Lagos prices, delivery to Maiduguri not included); brief13-sources Q2: 'Perkins UK 30Kva ... N9,960,000' | VERIFIED_SECONDARY |
| `GENSET_40KVA_NGN` | 10,945,000 | NGN per set | Zit Electronics (Nigerian online retailer), Perkins soundproof diesel sets, https://www.zit.ng/collections/perkins, accessed Oct 2026 (one retailer, Lagos prices, delivery to Maiduguri not included); brief13-sources Q2: 'Perkins UK 40kva ... N10,945,000' | VERIFIED_SECONDARY |
| `GENSET_50KVA_NGN` | 12,900,000 | NGN per set | Zit Electronics (Nigerian online retailer), Perkins soundproof diesel sets, https://www.zit.ng/collections/perkins, accessed Oct 2026 (one retailer, Lagos prices, delivery to Maiduguri not included); brief13-sources Q2: 'Perkins UK 50KVA ... N12,900,000' | VERIFIED_SECONDARY |
| `GENSET_100KVA_NGN` | 24,400,000 | NGN per set | Zit Electronics (Nigerian online retailer), Perkins soundproof diesel sets, https://www.zit.ng/collections/perkins, accessed Oct 2026 (one retailer, Lagos prices, delivery to Maiduguri not included); brief13-sources Q2: 'Perkins UK 100kva ... N24,400,000' | VERIFIED_SECONDARY |
| `GENSET_POWER_FACTOR` | 0.8 | kW per kVA | no source opened; the usual rating power factor of a diesel set | ASSUMPTION |
| `WATER_DENSITY_KG_M3` | 1,000 | kg/m3 | physical constant (fresh water, rounded) | DERIVED |
| `STANDARD_GRAVITY_M_S2` | 9.8066 | m/s2 | physical constant (standard gravity, exact by definition) | DERIVED |
| `BH_PUMP_HEAD_M` | 40 (30 to 70) | m total dynamic head (upper aquifer) | built from USGS Open-File Report 72-61 (Maiduguri GRA upper-aquifer water table about 16 m below ground, 1963 to 1968) and the World Bank 'Solar Pumping: The Basics' (2018) TDH method (static level + drawdown + tank elevation + 10% losses, x 110%); brief13-sources Q4 Note: Upper-aquifer boreholes. Deep lower-aquifer ('ruwan zafi') boreholes are sub-artesian to artesian and differ; the survey does not say which aquifer a borehole taps. | ASSUMPTION |
| `BH_PUMP_EFF` | 0.45 (0.4 to 0.6) | wire-to-water efficiency | World Bank 'Solar Pumping: The Basics' (2018): 'A typical pumping system would have a maximum efficiency of 60% at optimal operating point'; small sets run below it (brief13-sources Q4) | ASSUMPTION |
| `BH_DEFAULT_HOURS` | 8 (4 to 12) | pumping hours per day | iMMAP, 'Water sources for eleven hotspot LGAs in Borno State', March 2019, via HDX, CC BY (data-local/water/borno11/): the most common recorded 'Operating Hours' (109 of 166 rows in Maiduguri + Jere); used only where the survey left the field blank | ASSUMPTION |
| `PUMP_WINDOW_CENTRE_H` | 12 (10 to 14) | local hour | no source opened; pumping hours are placed centred on midday | ASSUMPTION |
| `SOLAR_BH_ARRAY_KWP_PER_KW` | 1.5 (1.2 to 2) | kWp of existing array per kW of pump | no source opened; the survey records the solar boreholes but not their array size Note: Today a solar borehole pumps in the hours its array output covers the pump. | ASSUMPTION |
| `WATER_WORKS_KW` | 100 (30 to 300) | kW, continuous critical process load | no source found (brief13-sources Q4: water works power or diesel not found); partner needed (the operator). Archetype for the OSM-mapped treatment site (4 clarifiers and a wastewater plant, ways 1318961730 to 1318961734) | ASSUMPTION |
| `COLDHUB_PV_KWP` | 5.5 | kWp per cold room | ColdHubs text on deutschland.de (May 2017): 'rooftop solar panels generating approximately 5.5kw, connected to a set of deep-cycle, long lasting batteries'; room 10 x 10 x 7 ft, about 2 to 3 t in 150 crates (brief13-sources Q3) Note: No kWh/day or battery size is published; the daily load is DERIVED as this array's mean daily yield at the market from the engine's NASA POWER PV model (an upper end of what the unit can run). | VERIFIED_SECONDARY |
| `COLDHUB_CAPEX_USD` | 40,000 | USD per unit | IFPRI Food Security Portal (Jul 2023), summary of a peer-reviewed study of 7 ColdHubs units in Northeast Nigeria markets (Dec 2020 to Jan 2021): 'The construction of each cold storage unit cost approximately 40,000 USD, while operational costs were around 150 USD per month' (brief13-sources Q3) | VERIFIED_SECONDARY |
| `COLDHUB_FEE_NGN_PER_CRATE_DAY` | 100 (100 to 250) | NGN per crate per day | IFPRI (2023): 'Agents paid rental fees of N100 ... per day per crate'; ColdHubs Bodija Market page: a trader quotes 'N250 per crate' (period not stated); brief13-sources Q3 | VERIFIED_SECONDARY |
| `WATER_L_PER_PERSON_DAY` | 15 | litres per person per day | Sphere Handbook, fourth edition (2018), water supply standard 2.1 (UNICEF-hosted copy, https://www.unicef.org/media/61556/file): 'Minimum of 15 litres per person per day'; brief13-sources Q4 Note: A minimum, never a maximum: Sphere notes 50 L may be the urban minimum, so people served is an upper count. | VERIFIED |
| `MEPP_SUPPORT_NGN_PER_MONTH` | 2,000,000,000 | NGN per month | Channels TV / Leadership / Arise News, Apr 2026, March 2026 to December 2028: Arise News (Apr 2026) quotes Governor Zulum, 'N2 billion monthly OPEX intervention funding from March 2026 to December 2028, totaling N68 billion'; ThisDay (Apr 2026) the same; brief 13 refs 5 and 6; brief13-sources Q5 | VERIFIED_SECONDARY |
| `MEPP_CAPACITY_MW` | 50 | MW | OSM way 1288148118 'plant:output:electricity=50 MW'; brief 13 ('a 50 MW gas plant') | VERIFIED_SECONDARY |
| `MEPP_AVG_DELIVERED_MW` | 14.2 (14.2 to 50) | MW average delivered | News Agency of Nigeria via Peoples Gazette (Feb 2025): MEPP 'is generating 32-MW with a daily average capacity of 14.20MW as at December 2024' (not attributed to a named official); brief13-sources Q5 Note: Range up to the 50 MW nameplate: support per kWh is lowest if the plant ran flat out. | VERIFIED_SECONDARY |
| `MEPP_COST_TARIFF_USC_PER_KWH` | 15.88 | US cents per kWh | News Agency of Nigeria via Peoples Gazette, 'Firm proposes 50MW gas plant to boost power in Borno' (Feb 2025): 'MEPP is operating at unsuitable tariff of 6.2USc/kWh paid by NBET vs. Cost tariff of 15.88USc/kWh for an average of 41MW CCPP as at Sep. 2024'; brief13-sources Q5 (cost-reflective tariff) | VERIFIED_SECONDARY |
| `MEPP_NBET_PAID_USC_PER_KWH` | 6.2 | US cents per kWh | News Agency of Nigeria via Peoples Gazette, 'Firm proposes 50MW gas plant to boost power in Borno' (Feb 2025): 'MEPP is operating at unsuitable tariff of 6.2USc/kWh paid by NBET vs. Cost tariff of 15.88USc/kWh for an average of 41MW CCPP as at Sep. 2024'; brief13-sources Q5 (paid by NBET) | VERIFIED_SECONDARY |
| `ROOF_NEAREST_M` | 30 (20 to 50) | m | no source opened; a point site with no building around it takes the single nearest OSM building within this distance as its own roof | ASSUMPTION |
| `ROOF_USABLE_FRACTION` | 0.5 (0.3 to 0.7) | share of footprint usable for PV | no source opened | ASSUMPTION |
| `PV_KWP_PER_M2` | 0.15 (0.12 to 0.2) | kWp per m2 of usable roof | no source opened (about 20% module efficiency with row spacing) | ASSUMPTION |
<!-- brief13-constants:end -->

## Data

| Input | Where | Licence |
|---|---|---|
| NASA POWER hourly GHI and T2M, 143 whole-degree points, three years (2021 to 2023) | `data-local/nasa-power/`, MANIFEST section 7 | CC0 by NASA policy, citation required |
| WorldPop constrained 100 m population (2026 projection, R2025A v1) | `data-local/worldpop/`, MANIFEST section 5 | CC BY 4.0, DOI 10.5258/SOTON/WP00839 |
| GRID3 Nigeria health facilities v3.0 | `data-local/grid3/` via `data/work/facilities.parquet` | CC BY 4.0 |
| NERC feeder rows and shortfalls | agent A's `data/work/nerc_rows.parquet`, `nerc_shortfalls.parquet` | NERC, no licence stated: cited, never re-hosted |
| Facility to feeder matches | agent B's `data/work/matches.parquet` | derived |
| PVGIS seriescalc (cross-check only) | cached in `data/work/pvgis_cache/` | EU reuse notice, CC BY 4.0 (SV 9, partly verified) |

## The model, in order

1. **Sun** (`solar.py`). Nearest whole-degree NASA POWER point, shifted from UTC to West Africa Time.
   Horizontal plane. Cell temperature by the NOCT model; power = G/1000 x (1 + gamma (Tc - 25)) x (1 - losses).
2. **Grid** (`supply.py`). One simulated feeder-year per lane. The band is drawn from the facility's band
   mixture; the promise is the band's minimum hours and is the ceiling. Each month the feeder meets its promise
   with probability p_meet, otherwise it falls short by a fraction drawn from Beta(alpha, beta); days vary
   around the month (Beta, concentration 10, ASSUMPTION). Outage blocks per day: 1 + Poisson(32.8/30.44 - 1),
   at most 2, placed at a uniformly random hour (no source gives time of day). Calibration: p_meet = 1 - 120
   failing Band A rows / 854 Band A rows = 0.859; the Beta is fitted by moments on the 32 rows with measured
   hours, then widened per the T3 rule (below). The same fractional shortfall is applied to every band because
   NERC only publishes measurements for Band A: likely optimistic for the lower bands. Off-grid facilities have no
   grid; tier d (refused) facilities have no "today" figure.
3. **Vaccine fridge** (`fridge.py`, `sim.py`). Cold reserve in hours of holdover. Equipment is unknown per
   facility, so today is computed under stated scenarios: (a) a PQS mains ice-lined fridge (printed holdover x a
   holdover-to-8 degC share sampled between 0.5 and 1.0, heat leak scaled by (ambient - 5)/(43 - 5), recharge 2 h
   per powered hour); (b) a domestic or non-PQS fridge (1.5 to 6 h, NIST, fixed hours, full reserve within an hour
   of power returning), **the headline today**; (c) no fridge, vaccines brought by an outreach carrier, stated and
   not modelled. Every fridge figure, today and with the fix, is multiplied by the per-lane availability scenario
   (0.90 to 0.99); the SDD array also carries the soiling scenario. "Technical" figures (no breakdowns) are kept
   alongside. A day counts when the reserve never reaches zero. Freezing is not modelled.
4. **Clinic loads** (`loads.py`). SEforALL Type 2 PHC table. Priority 1 (the clinic system's target): interior
   lights, oxygen concentrator, suction, procedure light, fetal monitor, 4.73 kWh/day. The vaccine fridge is
   never on this system (PQS PV01.3).
5. **Simulation** (`sim.py`). Hourly, three weather years x supply draws, each lane a year with a 7-day burn-in.
   Battery serves priorities in order; lower priorities may not draw below the shedding reserve. Output: share of
   days at 2 to 8 degC and share of days with priority 1 fully served, as median with 5th to 95th percentile.
6. **Cold-chain fix** (`coldchain.py`). The cheapest priced fix whose technical uptime is at least 99% of days at
   the 5th percentile: (i) a PQS ice-lined fridge on the grid the facility has (only where supply is known and not
   off-grid); (ii) a PQS solar direct-drive fridge; (iii) the same SDD plus the separate clinic system, where the
   facility has no grid at all. The target uses technical uptime because no purchase fixes breakdowns. Cost per
   month = price / 120 months, undiscounted. **Clinic system** (`size.py`), always a separate, optional line with
   its own cost: PV kWp on a geometric grid with battery at 7.2 kWh/kWp; the cheapest point serving priority 1 on
   99% of days at the 5th percentile; the knee by Kneedle.
7. **Doses** (`doses.py`). Every populated WorldPop cell goes to its nearest eligible facility within 5 km
   (eligible: has coordinates, not "Closed" or "Not-Functional"); people beyond 5 km stay unassigned and are
   reported. Each facility's catchment is then capped at 20,000 people (SEforALL), and the population above the
   cap is reported. Births = population x 32.493/1,000; doses = births x 20. Doses protected = doses x share of
   days held (sessions assumed spread evenly). An ESTIMATE.
8. **Money** (`econ.py`). The sustainability metric is **doses protected per naira of the cold-chain fix**
   (doses gained over scenario b, per N1m of the fix's price). Diesel appears only on the optional clinic line, and
   only for grid-connected facilities, as the backup-generator fuel the clinic system would displace during grid
   outages (generator use is common but not verified per facility); off-grid and unknown-supply facilities count
   none. Clinic line: capex at $/Wp; monthly cost = (capex x (1 + 0.05 x 15 + 0.15)) / 180, undiscounted;
   payback = capex / (avoided diesel - O&M).
9. **Funder ranking** (`plan.py`). Doses gained per naira of the cold-chain fix (or critical load-hours restored
   per naira of the clinic system), greedy under the budget; refused facilities are listed, never ranked. Ties,
   common among facilities at the catchment cap, break by larger uncapped demand (people above the cap still need
   doses), then lower uptime today, then lower cost, then facility id, so the order is deterministic. Each result
   row carries `capped`, `catchment_pop_raw` and `doses_demand_uncapped` so the UI can label capped facilities.

10. **Line outage** (`outage.py`, for brief 13, also brief 16). A grid-down window of N days (defaults 3, 7, 14, 40
   and 60; 60 is brief 13's "two months") is placed inside each lane's normal band supply, starting on a day drawn
   per lane from a separate random stream, so existing results do not change. The grid is off inside the window
   (the OFFGRID path) and unchanged outside it. Critical services: each priority-1 load and the vaccine fridge.
   Service-hours maintained = hours in the window a service ran while needed; summed and per service, median with
   5th to 95th percentiles. Today: no solar, fridge scenario (b) headline and (a) alongside; a labelled
   "generator" scenario covers every critical service and burns (priority-1 energy + mains-fridge energy) x
   0.40 to 0.73 L/kWh (clinic-set curve, DERIVED from Cummins sheets). With the recommended system: the cold-chain fix (an ice-lined fridge on
   the grid falls back on its holdover; a solar direct-drive fridge is unaffected) plus the clinic system, which
   was sized for the facility's normal supply, not for the outage. Diesel avoided in the window = energy the
   systems deliver to critical services in the window x the same range; litres per year stay the clinic line's
   `diesel_l_avoided`. Batch columns `out3_*`, `out7_*`, `out14_*`; `outage.aggregate` sums by state and LGA (or
   settlement for a city); `plan.rank(metric="outage_hours")` ranks by service-hours kept per naira of the
   cold-chain fix plus the clinic system.

11. **Outage-ready fix** (`outage.size_outage_ready`, columns `orfix_*`), the brief-13 answer, alongside the
   unchanged cold-chain fix columns. For an outage of 7 days (a parameter): the cheapest priced PQS fridge held for
   at least 95% of the window's hours at the 5th percentile (an ice-lined unit on the grid only where supply is
   known; with about 60 h of holdover it cannot pass a 7-day window), and the smallest clinic system (PV with
   battery at 7.2 kWh/kWp) keeping at least 95% of the priority-1 loads' needed hours at the 5th percentile. Sizes
   come from a coarse geometric grid then a fine pass between the last failing and first passing size. Capex = the
   fridge's PQS price plus the clinic system at $/Wp; cost per month = fridge price / 120 + the clinic line's
   life-cycle cost / 180. Inside the window the grid is off at every site, so the outage-ready size depends on the
   site's weather and not on its band. `outage.aggregate_city(state, lgas)` gives a city's totals (facilities, by
   level, service-hours today vs with the outage-ready fix, diesel avoided as a range, total capex) and ranks its
   facilities by service-hours kept per naira (`plan.rank(metric="orfix_hours")`). Its default city is
   Maiduguri (Maiduguri and Jere LGAs, Borno, YEDC). A 40-day window (`out40_*`) is added to 3, 7 and 14 days because
   the Damaturu to Maiduguri 330kV line was down for about 40 days (TCN, quoted by Nairametrics and Arise News; see
   BRIEF13-CITY.md in research-raw, event A). The outage-ready fix is sized for 7 days (`orfix_*`) and for 40 days
   (`orfix40_*`); the 7-day system is also run through 14-, 40- and 60-day windows (`orfix_at14_*`, `orfix_at40_*`,
   `orfix_at60_*`). `engine.augment` adds a new window to an existing results file without re-sizing (same draws).
13. **Brief 13 city view** (`sector.py`, `sites13.py`, `metrics13.py`): water, water works and market cold-room sites
   sized like the outage-ready fix, the M1 to M5 metrics, cost per kWh (solar, diesel, gas support, gas
   cost-reflective tariff), the daily-cycle cost arm, roof fit and the corridor. See `docs/BRIEF13_BUILD.md`.
12. **T5-style check for the outage-ready sizing** (`outage.t5_outage`, `data/work/t5_outage.json`). Full SEforALL
   Type 2 load (36.0 kWh/day, every load treated as critical), 7-day outage, 95% of hours at the 5th percentile:
   10.5 to 13.2 kWp with 75 to 95 kWh at four sites, above SEforALL's 5 to 10 kWp and 36 to 72 kWh. The difference
   is the design basis: SEforALL sizes for one day of autonomy; this holds a week without grid. The priority-1 load
   alone (4.7 kWh/day, 13% of SEforALL's) needs 1.3 to 1.6 kWp with 9 to 12 kWh.

## Engine checks (order of events: calibration, then the batch, then the timing run)

- **T3 (supply).** Leave-one-DisCo-out on the 32 measured failing Band A feeders, against the model's 90%
  interval for a failing feeder: 27 of 32 inside (84.4%), **a miss** against 85%; AEDC's four feeders (16.29 to
  16.81 h) fall below their held-out interval. Under the PREREG rule the interval was widened (Beta parameters
  divided by 1.5625, same mean) until the out-of-sample back-test passed: 28 of 32 (87.5%). Second arm, the
  unconditional interval for any Band A feeder: 22 of 32 (68.8%), a miss; it collapses towards the promise
  because 86% of Band A feeder-months meet it. Only 32 of 120 failing rows carry a measured value.
- **T5 (sizing).** Full SEforALL load (36.0 kWh/day), every load served on 99% of days at the 5th percentile:
  a Band C site sizes at 8.8 kWp and 63 kWh, inside SEforALL's 5 to 10 kWp and 36 to 72 kWh; off-grid sites size
  at 13 to 15 kWp, above it. The difference is the target: SEforALL sizes for one day of autonomy, we size for
  99% of days at the pessimistic end. The knee for the same off-grid site sits at 12.4 kWp (93% of days).
- **T6 (speed).** One what-if (32 draws x 3 years, ring trace): first run, before the equipment scenarios were
  added, p50 0.24 s and p95 0.31 s over 200 random matched facilities on the build laptop. Re-run after adding the
  two extra fridge scenarios: p50 0.27 s, p95 1.00 s, max 1.31 s, but with the machine at a load average of about
  110 on 15 cores from other jobs (`data/work/t6_local_contended.json`), so that run is not a clean measurement.
  PREREG names the deployed server; not yet measured there.
- **T4 (solar).** 20 facility sites (seed 20261030), NASA POWER nearest point against PVGIS seriescalc
  (SARAH3/ERA5, the same three years, 1 kWp, horizontal, 14% loss, no horizon): **20 of 20 within 10%**, median
  difference -1.0%, largest 6.2% (Kaduna). Detail in `data/work/t4_results.csv`.
- **Catchments.** First build, on GRID3's 41,778 facilities: one facility collected 963,708 people (626,275 doses a
  year). Rebuilt on agent B's facility list (61,009 ids, 54,785 eligible with coordinates): 232.3 million of 240.0
  million people within 5 km of a facility, 7.6 million unassigned. Largest raw catchment 188,322 people. After the
  20,000 cap, 980 facilities are capped and 9.0 million people above the cap are reported, not counted. Doses per
  facility per year: median 1,810, 90th percentile 5,815, **max 12,997** (the cap).
- **Fix counts** (55,035 facilities with coordinates): (i) PQS ice-lined fridge on the existing grid 25,092;
  (ii) PQS solar direct-drive fridge 20,886 (8,775 of them because supply is unknown); (iii) SDD plus the separate
  clinic system, off-grid 9,057. Every facility meets the target on technical uptime.
- **Uptime medians, share of days at 2 to 8 degC** (availability scenario included): today, scenario (b) domestic
  fridge 0.00 (interval 0.00 to 0.11); scenario (a) PQS ice-lined 0.944 (0.906 to 0.985); with the fix 0.944
  (0.906 to 0.985). Technical uptime with the fix (no breakdowns): 1.00 at the 5th percentile.
- **Doses a year, summed:** protected today under scenario (b) 2.0 million, under (a) 93.8 million; with the fix
  137.0 million. Doses per N1m of the fix (median): (i) 1,607, (ii) 211, (iii) 156.
- **Clinic line** (separate, optional; current results file, with the clinic-set generator curve and the May 2026
  diesel price): median capex USD 5,700, N81,368 a month; diesel counted for the 69% of facilities that are
  grid-connected, median N131,047 a month displaced; payback at the point estimate is finite for all of those,
  median 72 months.

## Known limits

- Failure modes not modelled: compressor or controller faults beyond the availability scenario, theft or
  vandalism of panels, shading from new buildings, door-opening and stock-loading excursions, freezing below +2
  degC, temperature-monitoring gaps, staff absence, and vaccine stock-outs.
- Today's equipment is unknown per facility; the headline uses scenario (b), with (a) alongside.
- Fridge prices are EXW catalogue prices; freight, installation and the Haier voltage regulator are not included.
- Storage volume against each facility's doses is not checked; the smallest priced unit that meets the uptime
  target is chosen.
