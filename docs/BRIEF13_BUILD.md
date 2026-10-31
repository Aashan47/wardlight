# Brief 13 engine and API build

Written 31 Oct 2026 (engine and API stream). Spec: `../../14-SUCCESS-METRICS.md`. Sourced values:
`docs/sources/brief13-sources.md` (research stream). Numbers below come from the run of 31 Oct 2026; rerun to refresh.

## What was built

1. **60-day outage window.** `engine/outage.py`: `DEFAULT_DAYS` is (3, 7, 14, 40, 60) and the 7-day outage-ready fix
   is also run at 60 (`ORFIX_EVAL_DAYS` = 14, 40, 60). `engine/augment.py` added `out60_*` and `orfix_at60_*` to the
   existing `facility_results.parquet` for all 1,109 keys without re-sizing (same seed, lanes and calibrated supply;
   `--check` reproduces the stored 14-day columns first). A full `engine.batch` run produces the same columns.
2. **Sourced constants** (`engine/constants.py`, one block for brief 13): diesel N3,277.47/L (NBS May 2026, national
   average, VERIFIED_SECONDARY; Oct 2024 N1,441.28 as the low end); generator curves DERIVED from Cummins sheets
   (clinic set 0.55, 0.40 to 0.73 L/kWh for health; 20 to 60 kVA set 0.34, 0.31 to 0.40 for water and cold); O&M
   USD 0.03/kWh and a 10-year life (NESG/Boell 2017); Lagos retail set prices; pump head 40 m (30 to 70, upper
   aquifer, ASSUMPTION) and efficiency 0.45 (0.40 to 0.60); Sphere 15 L/person/day; ColdHubs 5.5 kWp; MEPP N2bn a
   month and 14.2 MW delivered (14.2 to 50). Stored litres were rescaled exactly to the new clinic curve
   (`engine/augment.py`, recorded as `gen_l_per_kwh` in `facility_results.meta.json`), and the clinic line's diesel
   naira and payback were recomputed at the new price.
3. **New sectors** (`engine/sites13.py`, `engine/sector.py`): iMMAP 2019 boreholes in Maiduguri + Jere (94 solar,
   31 motorized; 43 hand pumps, 6 with no yield and 8 recorded at 0 h excluded and counted), the OSM water works as
   one archetype (ASSUMPTION 30 to 300 kW, partner needed), 8 named markets with one ColdHubs-type cold room each
   (load DERIVED from 5.5 kWp at the market, about 25 kWh/day). Each site is sized like the health fix (95% of
   critical hours at the 5th percentile in a 7-day outage) and run at 7, 14, 40 and 60 days. Supply: the ward's
   NERC band where a health facility there was matched on the ward, else the LGA mixture; solar boreholes off-grid.
   UMTH (two GRID3 rows) is `existing_onsite`, on the map, out of every total.
4. **City metrics** (`engine/metrics13.py`, `python -m engine.metrics13 --workers 10 --fixtures data/fixtures/brief13`):
   M1 to M5 per city and window, the three cost bars plus fuel-only diesel, gas break-even, CO2, ownership rows with
   precedents (RUWASA and ward borehole committees; ColdHubs pay per crate), security measures with their basis
   (World Bank list or "our design standard"), roof fit from OSM building outlines
   (`data-local/osm-geofabrik/osm_site_polygons_extract.py`: the buildings touching the site's own OSM outline, else
   the building containing the point, else the single nearest within 30 m; no building is "ground inside the
   compound", or "unknown" where OSM maps nothing within 250 m), distance to the 330 kV line, corridor stats (745.1 km
   of 330 kV ways touching the box, 2,707 towers; computed). Also `cost_arms` (the 7-day outage-ready sizing against a
   daily-cycle design), the gas plant's cost-reflective tariff (15.88 US cents/kWh, about N215; NBET paid 6.2 US
   cents, about N84), the road-tanker fuel note, and `headline_alongside`, a statement computed from the bars that the
   gas plant is cheaper per kWh when it runs and that the plan works alongside it. Writes `data/work/brief13/`.
   About 25 s for three cities. `python -m engine.sources_doc` regenerates the constants block of
   `docs/sources/engine.md`.
5. **API** (`api/brief13_api.py`, wired in `api/main.py`): `GET /api/city/{city}/metrics?days=7|14|40|60` (default
   60), `/api/city/{city}/sites`, `/api/corridor` (420 KB), `/api/sites/{id}/siting`. Served from the files; RSS
   after start and all routes about 290 MB.
6. **Damaturu and Yola**: health from GRID3 (37 and 161 sites); Yola has one OSM market; neither has a water survey
   loaded, and the labels say so.

7. **API polish for the web stream.** Sites GeoJSON: `rank` (critical hours gained at 60 days, then capex, then id;
   UMTH unranked; the rule is in the collection's `properties.rank_rule`), `facility_id` (GRID3 id for health, else
   null), `kw` for health (SEforALL priority-1 peak 0.548 kW, labelled DERIVED) and `kwh_day`. Metrics: `data_version`
   (the results version the API reports), `label_status` next to every `labels` (also `cost_label_status`, the cost
   arms, siting cards and sites), `sources` as `{text, url, status}` (url null where no document records one, e.g.
   the iMMAP HDX page). Percentages round half-up to one decimal (6.9%); a share below 1 is capped at 99.9.
   `GET /api/sites/{id}/outage_trace?days=7|14|40|60`: water and cold sites run the engine live (about 1.2 s, then
   cached); health sites run the plan's outage-ready system (orfix PV, battery and fridge, the batch's 48 draws), so
   each trace's kWp, kWh and median hours kept equal the site's entry in the sites GeoJSON (tested); fixtures carry
   traces for one solar borehole, one motorized
   borehole, one cold room and one health site at 14, 40 and 60 days. Distance to the 330 kV line is now the
   haversine distance to the nearest point on any 330 kV LineString, substation outlines included (Tuba Lawanti
   Health Post: 38.3 km, was 38.1 on the local plane).

## Maiduguri headline (run of 31 Oct 2026)

| Window | CSH today | CSH with plan | Diesel litres avoided (lo to hi) |
|---|---|---|---|
| 14 days | 7.1% | 100% | 20,756 (9,537 to 55,056) |
| 40 days | 7.0% | 100% | 59,245 (27,219 to 157,172) |
| 60 days | 6.9% | 99.9% | 88,541 (40,720 to 234,674) |

Cost per kWh delivered: solar + storage N684 (307 to 1,727); diesel N1,432 (672 to 1,694), fuel only N1,227; gas
plant operating support N193 at 14.2 MW (N55 at 50 MW); gas plant cost-reflective tariff N215 (NBET paid N84).

Cost arms (Maiduguri; same sites, both priced at SEforALL's bundle $/Wp, which prices a system by its PV when it has
less than 7.2 kWh per kWp, so a smaller battery does not lower the price):

| Arm | Solar N/kWh (lo to hi) | Clinic-system capex | CSH kept at 14 / 40 / 60 days |
|---|---|---|---|
| Outage-ready, 7-day target (the plan) | 684 (307 to 1,727) | N8.19bn | 100% / 100% / 99.85% |
| Daily cycle (one night of battery) | 798 (348 to 2,045) | N8.01bn | 95.0% / 95.3% / 94.4% |

In the daily-cycle arm the solar boreholes fall to about 70% because the design rule gives a daytime pump no battery.
Damaturu is the one city where the daily-cycle arm costs less per kWh (N720 against N751), keeping 98.0% at 60 days.

Roof fit, tight rule: Maiduguri 191 fits, 16 partial, 59 ground, 13 unknown (was 255, 2, 22 under the 150 m
radius); Damaturu 3, 0, 8, 26 (OSM maps few buildings there); Yola 137, 0, 22, 3. Break-even: the support alone costs more per kWh than solar
only below about 4.0 MW average delivered (1.6 to 8.9), so at the reported 14.2 MW the support per kWh is lower
than the solar cost per kWh. Operating support only; tariff and capital are not included.

## What remains

- Water works load: no source (partner needed). It dominates water diesel and capex; shown as its own archetype.
- Solar borehole arrays: size not in the survey (ASSUMPTION 1.2 to 2.0 kWp per pump kW); the existing array is not
  credited in the price.
- Roof fit: a "fits" from the nearest building within 30 m assumes that building belongs to the site; ownership of
  roofs is not checked. Damaturu has few mapped buildings (26 of 37 "unknown"). Building relations (multipolygons)
  were skipped (37,266 nationally).
- No verified battery price: the daily-cycle arm cannot show the saving a smaller battery would bring.
- No per-aquifer split: the survey does not say which boreholes tap the deep lower aquifer.
- The web's Method page still says diesel prices after October 2024 are news-reported only; it should cite the NBS
  May 2026 figure.
