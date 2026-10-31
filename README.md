# Wardlight

**Power for a city the grid can't protect.** Wardlight shows a funder, the state or the distribution company which
critical sites in a city to put on their own solar and battery, so hospitals, water pumps and market cold rooms keep
running when the one line is cut.

Team Two to Eight (Aashan Javed). IAS Global Energy Hackathon 2026 (Anneru Solutions), brief 13, Digital Solutions,
Apps & AI/ML Tools track. Focus city **Maiduguri, Borno**; Damaturu and Yola run on the same pipeline.

**Status: proof of concept.** Supply is modelled and critical loads are archetypes; no site has been visited or metered.
The limits are listed below.

## The problem

Maiduguri hangs on one 330 kV line from Gombe through Damaturu (OSM maps 745.1 km of 330 kV line and 2,707 towers in the
Gombe to Maiduguri box, as mapped by OSM contributors). The line was cut on 21 Sep 2024 and power returned on 31 Oct 2024,
about 40 days. The city's gas plant delivered 14.2 MW on average (Dec 2024) against 50 MW nameplate, on gas brought
in by road tanker. The brief asks for a plan that works alongside the plant and the distribution company.

## What it does

1. Joins public data per site: GRID3 health facilities, the iMMAP 2019 Borno water-point survey, OSM markets, roofs and
   the 330 kV line, NASA POWER hourly sun, and the regulator's own feeder bands (NERC orders, September 2026).
2. Forces the grid off for 14, 40 or 60 days and simulates every critical site hour by hour: today with no backup,
   and with a solar and battery system sized for a 7-day outage.
3. Ranks the sites by critical service-hours gained, then cost, and walks that order for a funder's budget.
4. Three agents on top, each working only from the data: a **planner** (a budget in, a plan out), an **SMS site verifier**
   (sandbox) and a **line watcher** that replays the real 2024 cut. Every number the planner writes must match a tool
   result, or the answer is blocked.

## The brief's five metrics (Maiduguri and Jere, 60-day cut, data version 8606a23e82d2)

| Metric | Result |
|---|---|
| **Impact** | Critical service-hours kept: **6.9% today, 99.9% with the plan.** Health 0.06% to 99.9% (145 facilities), water 57% to 99.9% (126 pumping sites), market cold rooms 0% to 99.3% (8). Water pumped about 1,830 to about 4,000 m3 a day, enough for up to about 267,000 people at the Sphere minimum of 15 L a day. **Diesel avoided 88,541 L** in 60 days (range 40,720 to 234,674), about N290m at N3,277.47/L; about 239 t CO2 (110 to 633). |
| **Innovation** | 279 independent sites, each able to run on its own; **0 km of new exposed line** (every system behind the meter, inside the compound). Share of critical energy served on site during the outage: 10% today, 99.5% with the plan. |
| **Sustainability** | Lifetime cost per kWh delivered: solar and storage **N684** (N307 to N1,727); diesel **N1,432** (N672 to N1,694). When the gas plant runs it is cheaper per kWh than solar: its federal operating support alone is N193/kWh at 14.2 MW (cost-reflective tariff about N215). The plan works alongside the plant and replaces the diesel that critical sites burn when the line or the plant fails. Ownership per sector: facility operator (health), ward borehole committee with Borno RUWASA (water), market association paid per crate, N100 a day (cold rooms). |
| **Feasibility** | 191 of 279 sites fit on their own roof (16 partial, 59 ground inside the wall, 13 unknown; 150 of the fits assume the nearest building within 30 m belongs to the site). Median 13 km from the 330 kV line. Security measures from the World Bank's "Solar Pumping: The Basics" (2018), plus three labelled as our design standard. |
| **Scalability** | Three cities live: Maiduguri (13 s to build), Yola (5.6 s), Damaturu (2.0 s). Another city needs a facility registry with coordinates, the distribution company's feeder bands or outage records, a water-point survey, OSM markets and roofs, and hourly sun. |

A funder with **N2bn** for a 60-day outage in Maiduguri funds **109 of 279** sites and lifts critical service-hours
kept from 6.9% to 70.1%, with 18,645 L of diesel avoided. Health ranks first, so all 8 cold rooms stay unfunded; the
plan says so and prices the rest.

**The agent on the live model** (openai/gpt-oss-120b on Nebius, 16 questions fixed in advance): every number the
agent wrote traced back to the data in both runs. The first run missed our task target, so we fixed the causes.
Details, misses included: `docs/RESULTS.md`.

## Run it locally

Python 3.12 and Node (built and tested with Node 26).

```sh
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
WARDLIGHT_FIXTURE=1 .venv/bin/python -m pytest -q  # the test suite, as CI runs it

cd web && npm ci && npm run build && cd ..          # the web app, served by the API at /
WARDLIGHT_FIXTURE=1 PORT=8000 deploy/run.sh          # recorded engine output, no raw data needed
# open http://127.0.0.1:8000/
```

Fixture mode serves the engine's recorded outputs in `data/fixtures/brief13/` and the recorded agent sessions in
`data/fixtures/agents/`; the national health-facility search then runs over synthetic sample records, labelled as such
on screen. The full pipeline (raw downloads into `data-local/`, then `data_build.match.run`, `engine.batch`,
`engine.metrics13`) and the server setup are in `deploy/README.md` and `docs/BRIEF13_BUILD.md`.

## Data sources and licences

| Source | Licence |
|---|---|
| GRID3 Nigeria Health Facilities v3.0 and v2.0 | CC BY 4.0 |
| OpenStreetMap via Geofabrik and Overpass (markets, roofs, the 330 kV line) | ODbL, (c) OpenStreetMap contributors |
| iMMAP, water sources for eleven hotspot LGAs in Borno (2019), via HDX | CC BY |
| NASA POWER hourly (sun and temperature, 2021 to 2023) | CC0, citation requested |
| NERC multi-year tariff orders, September 2026 (feeder bands and minimum hours) | regulatory publication, licence not stated: cited and linked; no copy is hosted here |
| naija-grid (feeder band history) | MIT |
| Gridfinder (Zenodo 3628142) | CC BY 4.0 |
| WorldPop Nigeria 2026 | CC BY 4.0 |
| SEforALL Nigeria technology roadmap (loads, $/Wp), WHO PQS documents, World Bank "Solar Pumping: The Basics" | cited documents |
| NBS diesel price (May 2026), MEPP output and support, ColdHubs, Sphere, EPA emission factor | cited, quoted with grades in `docs/sources/brief13-sources.md` |

Every constant carries a label (VERIFIED, VERIFIED_SECONDARY, DERIVED or ASSUMPTION) on screen and in
`docs/sources/`. No private or non-public data is used.

## What is not proven

- Supply is modelled from the regulator's promised feeder bands; critical loads are archetypes (SEforALL Type 2
  priority-1 for health, a 3 t solar cold room per market). No site has been metered or visited.
- The water works load is an assumption (30 to 300 kW) and drives the top of the capex range (about N9.4bn for every
  site in Maiduguri, N5.0bn to N21.8bn). Existing solar-borehole arrays are assumed; Damaturu and Yola have no water
  survey loaded.
- Battery prices sit inside the SEforALL $/Wp bundle; there is no separate verified battery price.
- The SMS verifier ran on typed sandbox replies. Pre-registered targets and their results, misses included:
  `docs/PREREG.md`, `docs/RESULTS.md`.

## The ask (6 to 18 months)

- A pilot partner in Maiduguri (Borno RUWASA or a ward borehole committee, a market association, or the state primary
  health care board) to meter 10 to 20 sites and replace archetypes with measured loads.
- YEDC outage records per feeder, and the water works' pump ratings.
- Funding for a first tranche, sized by the planner (N2bn funds 109 sites at 60 days).
- A mentor with mini-grid or solar-for-health delivery in the North-East.

## Repository

`engine/` simulation and sizing · `data_build/` NERC reader and facility matcher · `agents/` planner, verifier, watcher
· `api/` FastAPI server · `web/` React app · `data/fixtures/` recorded engine output and agent sessions · `data/runs/`
the live agent runs · `docs/` pre-registration, results, sources · `deploy/` server files · `tests/`.

The health-facility routes and agent modules (vaccine fridge and dose metrics) remain because the test suite covers
them.

Licence: Apache-2.0 (`LICENSE`).
