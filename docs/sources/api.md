# API: routes, where every served number comes from, and the choices the API makes

Scope: `api/` (FastAPI). Run from `build/wardlight` with
`.venv/bin/uvicorn --factory api.main:create_app` or `deploy/run.sh`. `WARDLIGHT_FIXTURE=1` serves
`data/fixtures/` only. Deploy notes: `deploy/README.md`. Tests: `tests/api/`.

Every number the API serves is one of: a value read from `data/work/*.parquet` at startup, simple arithmetic on
those values (each case is named below), an engine constant, or the result of an engine call. Text such as source
names, quotes and labels comes from `api/sources.py`, which lists only sources already in `06-PRODUCT-DESIGN.md`,
`docs/sources/engine.md` or `data-local/MANIFEST.md`.

## Routes

| Method | Path | Returns | Source |
|---|---|---|---|
| GET | `/api/health` | `Health` plus facility counts, supply calibration, staleness, FX, agent cap | parquet, engine constants |
| GET | `/api/summary` | `Summary` plus fix counts, summed doses, median uptimes, coverage note | parquet (sums, medians, counts) |
| GET | `/api/facilities?state=&lga=&q=&tier=&limit=` | `FacilityListItem[]` plus `code` | parquet |
| GET | `/api/facilities/{id}` | `FacilityRecord` | parquet; supply model and the ring trace by engine call |
| POST | `/api/facilities/{id}/simulate` | `SimulateResponse` plus costs, labels, timings | engine call (`api/whatif.py`) |
| GET | `/api/plan?state=&budget_ngn=&target=` | `Plan` | `engine.plan.rank` on parquet rows |
| GET | `/api/plan/brief?state=&budget_ngn=&metric=` | investment brief (JSON); `&format=csv` or `/api/plan/brief.csv` for the funded list as CSV | `engine.plan.rank`, parquet, engine constants |
| GET | `/api/city?state=&lgas=&days=` | brief 13 city view: totals and facilities ranked by service-hours gained | parquet sums; `engine.outage.aggregate_city` (or `aggregate`) |
| GET | `/api/facilities/{id}/outage_trace?days=` | hourly trace across one outage window, for the 3D night | engine call (`api/outage_api.py`) |
| GET | `/api/feeders/{id}` | `Feeder` plus `served_summary` | `nerc_rows.parquet`, naija-grid history, `matches.parquet`, `nerc_shortfalls.parquet` |
| GET | `/api/results` | `Results` (T1 to T9) | files in `data/work/` and `docs/`, and engine calls for T3 |
| GET | `/api/evidence/crops/{name}` | the NERC row crop (PNG) | `data/work/nerc_crops/` |
| POST | `/api/agent/plan` | starts a planner run (202 with `run_id`), or streams it with `?stream=true` | agent F |
| POST | `/api/agent/verify/{id}` | starts a verifier run with typed sandbox replies | agent F |
| GET or POST | `/api/agent/watch?old=&new=` | starts a watcher run (recorded by default) | agent F |
| GET | `/api/agent/runs/{run_id}/events` | `text/event-stream` of the run's events | agent F's generators or a recording |
| GET | `/api/agent/runs/{run_id}` | the run and its events so far, as JSON | |
| GET | `/api/agent/recordings`, `/api/agent/cap` | recordings available; today's cap | |
| POST | `/api/ussd` | Africa's Talking USSD callback, `CON`/`END` text | parquet |
| POST | `/api/sms/inbound` | Africa's Talking incoming-SMS callback; the reply is returned, not sent | parquet |
| GET | `/{path}` | the web app from `web/dist`, falling back to `index.html` | |

Unknown `/api/...` paths return a JSON 404. The OpenAPI page is at `/api/docs`.

## Facility ids and codes

`id` is GRID3's `unique_id`. Each facility also has a numeric `code`, its position in the id-sorted list (1 to
61,009 on the current build), for feature phones. `/api/facilities/{id}` accepts the id, the code, or `WL-<code>`.
Codes change only when the facility list changes; `data_version` in `/api/health` changes with it.

## What `FacilityRecord` carries, field by field

- `facility`, `match`: `facilities.parquet` and `matches.parquet`. `match.tier` is the **current** match. When
  `facility_results.parquet` was computed on an earlier match (the case on the current build: matches were rewritten
  after the batch, and 827 facilities changed tier on the build this was written against), the record carries
  `result_tier` and `results_stale: true`, and `/api/health` reports the live count. Precomputed figures for those facilities use the earlier tier until the
  engine batch is re-run; what-if runs always use the current match.
- `match.feeder_id`: a URL-safe form of the NERC row key, `<order file stem>-p<page>-sn<serial>`. The raw key
  (`<file>.pdf#p<page>#sn<serial>`) is also accepted by `/api/feeders/{id}`.
- `match.evidence`: the NERC row's file, page, serial and row text from `matches.parquet`; `url` from
  `data-local/MANIFEST.md`; `crop` from `nerc_rows.crop_path`. `verified` comes from `docs/VERIFIED_ROWS.csv`
  (order_file, page, sn, checked_by, how, result), read at startup: a listed row is verified, with `checked_by`,
  `how` and `check_result` (also as `verified_by`, `verified_how`, `verified_method`), unless its result reports a
  mismatch; every other row says "read by OCR, not checked by eye". The same flag is on feeder rows and brief
  citations.
- Catchment fields, on the facility, list rows, plan rows and brief rows: `capped` and `doses_demand_uncapped` from
  `facility_results.parquet`; `catchment_pop` and `pop_above_cap` from `catchments.parquet` (the batch's own copies
  are not served). `/api/plan` `summary.capped_funded` and the brief's `totals.capped_funded` count funded
  facilities whose catchment was capped.
- Uptime labels: list rows, plan rows and brief rows carry `scenario: "household or non-PQS fridge"` for the
  headline figure, and plan and brief rows a `scenarios` map naming the scenario of each uptime field. Tiers c, d and off-grid carry their own evidence (naija-grid counts, the state
  regulator quote, the Gridfinder distance) with `file` null.
- `supply_model`: `engine.supply.sample_daily_hours` for the facility's bands (64 draws by 365 days, seed
  20261030, calibrated and T3-widened parameters); median, 10th and 90th percentile of daily hours. Labelled
  modelled, promised not measured.
- `scenarios` (array, types.ts `Scenario[]`): `domestic` (headline, `uptime_today*`) and `pqs_icelined`
  (`uptime_today_pqs*`). `scenarios_detail` adds the technical figures and the with-fix interval.
- `fix` (types.ts `Fix`): `fix_category` mapped i to `pqs_icelined`, ii to `pqs_sdd`, iii to `solar_clinic`;
  `cost_ngn` is `capex_ngn`; the `reason` sentence is chosen by category and supply state (known grid, off-grid,
  refused), never by a number the engine did not produce.
- `brief_metric`: `uptime_today` (domestic, headline), `uptime_today_pqs`, `uptime_with_system`, `doses_year`
  (`doses_per_year`), doses protected today and with the fix, each with its interval under `doses`.
- `survival_today`, `survival_with_system`: the fridge from the uptime columns; delivery, oxygen and ward from
  `crit_uptime_today` and `crit_uptime_with`, which the engine computes for the priority-1 loads together, so the
  three rooms show the same figure and say so (`combined`). The laboratory (priority 2) has no precomputed figure
  and appears only in a what-if.
- `recommended`: `capex_usd`, `capex_ngn`, `monthly_cost_ngn` are the **cold-chain fix**. `monthly_diesel_ngn`,
  `payback_months`, `diesel_l_avoided`, `co2_kg_avoided` are the **optional clinic system's** line (diesel counted
  only for grid-connected facilities, as `engine/econ.py` does); `payback_months` is null when it never pays back.
  `recommended.fix` and `recommended.clinic_line` carry both lines with their ranges. `holdover_h_range` is the
  range of printed PQS holdover over the priced models of the chosen fix's kind. `who_pays` lists the payers named
  in `06`; `maintains` says plainly that no maintenance arrangement is sourced.
- `loads`: one entry per room from the engine's SEforALL rows (below) and the fridge catalogue.
- `trace`: a what-if with no clinic system (0 kWp, 0 kWh) in shared mode, so the ring shows today under the
  headline's own scenario (domestic fridge), from the same supply distribution, seed and weather. The night is
  chosen so it cannot contradict the headline: held when the headline uptime is at least one half, failed
  otherwise (rule under What-if). `trace.draw` names the scenario, the lane, the night, its grid hours, the
  headline it was matched to and where that headline comes from (the batch's 48 lanes; the ring's run uses 32).
- `cost_curve` is not served. Under the two-system rule the clinic system's size does not change the vaccine
  fridge, so a curve of fridge survival against clinic spend would be flat by construction; the clinic sizing
  (chosen point and knee) is in `recommended.clinic_system`.

## What-if (`POST /simulate`, `api/whatif.py`)

- Rooms map onto the engine's SEforALL load rows: delivery = suction, procedure light, fetal heart monitor
  (priority 1); oxygen = oxygen concentrator (1); ward = interior lighting (1); lab = centrifuge and microscope (2).
  The mapping is the API's choice; the rows, watts, hours and priorities are the engine's.
- `fridge_mode`: the engine never puts the vaccine fridge on the clinic battery (PQS PV01.3). `shared` therefore
  reports today's fridge on the grid it has (scenario b, domestic, the headline); `pqs_sdd` reports a dedicated
  PQS solar direct-drive fridge (Dulas VC200SDD) on its own array. The clinic sliders size only the other rooms.
- Room survival = the engine's share of days on which every load up to that room's priority is served
  (`per_priority_with`). The fridge figure carries the availability scenario; `fridge_days_technical` does not.
- The ring (`api/whatif.py ring_trace`), from the same draws as the figure it sits beside: the lane is the draw
  whose share of days held (with the availability scenario) is closest to the median over all draws, which is the
  figure shown; the night (18:00 to 17:00) is, among that lane's nights whose fridge state matches the figure
  (held when it is at least one half), the one whose grid hours are closest to the lane's median night.
  `trace.scenario` is `domestic` or `pqs_sdd`, and `trace.draw` records the lane, its uptime, the run median, the
  night, its grid hours and whether a matching night existed (`state_matched`). Room states come from the engine's served-priority trace and the grid; `battery_soc` is the share of usable
  capacity. `fridge_c` is **illustrative** (`fridge_curve: "illustrative"`): the engine tracks whether the cold
  reserve lasts, not a temperature, so held hours show the engine's setpoint constant (5 degC) and failed hours its
  PQS holdover end point (10 degC).
- `cost_usd` = clinic capex point at SEforALL $/Wp plus, in `pqs_sdd` mode, the SDD's PQS sheet price;
  `costs` gives both with ranges.
- PV snaps to 0.05 kWp and battery to 0.1 kWh (`snapped` says when); results are cached by the SHA-256 of
  (weather point, bands, rooms, PV, battery, mode, target, draws, data version), so facilities that share a weather
  point and band mixture share a cache entry. `X-Cache: hit|miss`. 32 supply draws per weather year.

## Plan (`GET /api/plan`)

`engine.plan.rank` with the doses metric on the state's facilities with results; facilities refused under the
current match are not ranked. Default state Edo; `budget_ngn` defaults to the total of all fixes; `target` must be
0.99 (the batch target) or the API says another target needs a batch re-run. Derived row fields:
`fridge_nights_saved` = (uptime with the fix - uptime today) x 365, days a year at 2 to 8 degC gained;
`unmet_hours` = (1 - `crit_uptime_today`) x `critical_load_hours_day`, critical load-hours a day at risk today;
`score` = doses gained per N1m of the fix; `cumulative_ngn` = running sum of `cost_ngn` in rank order;
`fix` is the `FixCategory`.

## Brief 13: line outages (`api/outage_api.py`)

The metric: hours of critical service maintained during a line outage, and diesel litres avoided. The engine's
batch writes, per outage length N (3, 7 and 14 days), `out{N}_*` columns (`engine/outage.py`): service-hours
needed, kept today (no solar, household fridge, clinic loads on grid), kept today with a PQS ice-lined fridge, kept
with the recommended fix, the energy the systems deliver, generator litres in a labelled generator scenario, and
diesel litres avoided, each with its 5th to 95th percentile. The outage-ready fix (`orfix_*`) is one system per
facility sized for `orfix_days`; its service-hours kept and diesel avoided fill that duration's block. Until a data
build carries `orfix_*` the blocks say so and the fields are null.

- Facility detail: `outage.by_days[N]` with every figure above, per-service hours, scenarios and labels, plus
  `outage.outage_ready_fix`. List rows: `out{N}_needed_h`, `out{N}_today_h`, `out{N}_with_h`, `out{N}_orfix_h`,
  `out{N}_diesel_l_avoided`.
- `/api/city`: a city is a state plus optional LGAs (comma-separated). Totals are sums of per-facility medians
  (lo and hi are sums of per-facility percentiles, wider than a joint interval), refused matches left out. The
  list is ranked by service-hours gained (with minus today), then cost. `engine_aggregate` is the engine's own
  `aggregate_city` when the outage-ready fix exists, else `aggregate` by state.
- `/api/facilities/{id}/outage_trace`: the engine places the window (`window_mask`, seed + 1000 + days) and turns
  the grid off in it; the draw shown is the one whose service-hours kept with the recommended systems is closest
  to the median over draws. Hourly grid, solar, critical load, battery share, and room states with the systems
  (`rooms`) and today (`rooms_today`), 12 hours either side of the window.
- `/api/plan` and `/api/plan/brief` accept `metric=outage_hours` (cost: the cold-chain fix plus the clinic system)
  and `metric=orfix_hours` (cost: the outage-ready fix, only when the columns exist), with `days`.
- `/api/summary` leads with `headline_metric`: the brief 13 totals per outage length over every facility with a
  result and a known supply.

## Data version

`data_version` is the agents' own definition, `agents.tools.WardlightData.version`: the first 12 hex characters of
a SHA-256 over the size and modification time of `facilities`, `matches`, `facility_results` and `nerc_rows`. The
API, agent tool results and agent recordings therefore carry the same id while those files are unchanged; the API
writes the same definition out for when `agents/` is absent.

## Feeders

Rows: every `nerc_rows` row with the same DisCo and feeder name. History: those rows, plus naija-grid's monthly
band history (`data-local/naija-grid/band_history_wide.csv`, MIT) when exactly one naija-grid feeder in that DisCo
has the same name; `min_hours` for a naija-grid month is the engine's band constant. `history_note` says which.
Facilities: every match whose `feeder_ids` contains the row, with the matcher's reason.

`served_summary`: the matched facilities counted by tier and by GRID3 level; hospitals (`facility_type` contains
"hospital") and PHCs (primary health centre or clinic, health post, health centre); the sum of `doses_per_year`
over them (an ESTIMATE; a facility matched to several feeder rows counts in full on each, and the share that does
is given); the promised hours; and every `nerc_shortfalls` row with the same DisCo and exactly the same feeder name
(letters and digits only), with the gap = promised hours - measured average hours. Only 1 of the 121 shortfall rows
names a feeder row this way, so most feeders say that no measured hours were published for them, and carry the
DisCo-wide median of measured hours for failing Band A feeders, labelled as not this feeder.

## Investment brief (`GET /api/plan/brief`)

The same `engine.plan.rank` call as `/api/plan`, for `metric=doses` (cost: the cold-chain fix) or
`metric=load_hours` (cost: the separate clinic system). Payload: the funded list in rank order, each row with its
fix (`FixCategory`, label, PQS model), cost, cumulative cost, benefit, doses a year and doses gained, uptime today
and with the fix, and a citation (the NERC file, page, row and row text with its URL, or the tier's own evidence:
naija-grid band counts, the Gridfinder distance, the state-regulator reason); totals (count, spent, left, benefit,
doses protected today and with the fix, fixes and spend by category); what is not reached and why (ranked but over
budget with the cost to fund them and the benefit forgone; supply unknown; no coordinates); the method; the
labelled scenarios; every engine constant marked ASSUMPTION or UNVERIFIED with its range and source; the sources;
and the staleness note. `budget_ngn` defaults to the cost of funding every candidate. The CSV has one row per
funded facility with the citation text and URL; totals stay in the JSON.


## Results (`GET /api/results`)

Targets parsed from `docs/PREREG.md`. T1 and T2 from the by-eye columns of the sample CSVs (not checked yet, so
not run). T3 from `engine.supply.backtest_t3` and `widen_until_pass` on `nerc_shortfalls.parquet` at request time
(first run, a miss, the widening and the second arm). T4 from `t4_summary.json`; T5 from `t5_results.json`; T6
not run on the deployed server, with the laptop figure from `t6_local_contended.json`; T7 `reported` (PREREG gives
no target); T8 and T9 not run until an agent evaluation file exists in `data/work/`. The status `reported` is an
addition to types.ts's three values.

## Agents: Server-Sent Events

The stream carries agent F's events unchanged (schema in `agents/events.py`): `plan`, `step_start`, `reasoning`,
`tool_call`, `tool_result`, `check`, `citation`, `answer`, `error`, `done`. Each SSE message is `id: <seq>`,
`event: <type>`, `data: <the event as JSON>`; a reconnect with `Last-Event-ID` (or `?from=`) resumes after that
event; a comment line keeps idle streams open every 15 s.

Modes, shown in the start response and in `done`:
- **recorded**: a file in `data/fixtures/agents/` replayed with its original `t_ms` gaps (`speed` scales them,
  0 sends at once) and `done.recorded` set true. Used in fixture mode, when asked for (`recorded` or
  `recording`), and when the daily cap is spent. A planner recording is replayed only for its own question, and a
  verifier recording only for its own facility; otherwise the API runs or refuses, and never shows another
  question's answer.
- **live**: the planner with the model configured by `WARDLIGHT_LLM_*`, only with `WARDLIGHT_AGENT_LIVE=1`.
- **scripted**: otherwise the planner runs over the real tools with agent F's rule-based scripted model (no
  language model; `done.model` says so), the verifier with rules only, the watcher as code.
- **unavailable**: an `error` event and a `done` event.

Every non-recorded run counts against the daily cap (`WARDLIGHT_AGENT_DAILY_CAP`, UTC day). The start, events and
cap responses all carry `recorded`. Agent starts have their own per-visitor rate limit.

## SMS and USSD (Africa's Talking format, sandbox)

- USSD: form fields `sessionId`, `serviceCode`, `phoneNumber`, `networkCode`, `text` (all inputs so far joined by
  `*`). Menu: `1` facility code then the fridge-uptime and fix lines; `2` facility code then agent F's verifier
  questions (`agents.verifier.ussd`, live data only); `3` about. A bare code goes straight to the lookup. Replies
  begin `CON ` or `END `, stay within 182 characters, and end with `SANDBOX`.
- SMS: form fields `from`, `to`, `text`, `date`, `id`, `linkId`. The reply is returned in JSON with
  `sandbox: true, sent: false`; no SMS API is called.
- The rate limit for both is per phone number.

## Limits

Per visitor (the `CF-Connecting-IP` header behind Cloudflare, else the client address), per minute: 240 reads, 30
what-ifs, 6 agent starts, 60 telephony requests. Request bodies over 16 KB get 413. All in process memory, so the
service runs one worker.

## Speed (T6 method, through the API)

`deploy/t6_api.py`: 200 facilities with coordinates drawn with seed 20261030, one `POST /simulate` each (all five
rooms, 2 kWp and 14.4 kWh, `pqs_sdd`), cache off, over HTTP to a local uvicorn. On the build laptop (Apple
silicon, 15 cores), while other jobs held the load average at about 14 to 24, after the ring began choosing a
representative draw: **p50 0.48 s, p95 0.50 s, max 0.67 s**, no cache hits. An earlier run, before that change and
at a load average of 14 to 16, gave p50 0.50 s, p95 0.73 s, max 0.78 s. After the move to the on-disk store, at
a load average of 42 to 57 from other jobs: p50 1.10 s, p95 1.25 s, max 1.34 s, of which the engine itself took
1.07 s at the median; the API's own share, including the SQLite row read, is about 30 ms. That run is not a clean
measurement. Re-measured at a load average of 3.5 to 6, same method and store: **p50 0.49 s, p95 0.63 s, max
0.66 s**, engine median 0.48 s. PREREG's T6 names the deployed server, still to be measured there. This is not the PREREG measurement, which names the deployed server.

## Memory

The production VM has 952 MB of RAM shared with three other services. Measured with `deploy/mem_api.py` on the build
laptop (Apple silicon): `deploy/run.sh` on real data, RSS from `ps` after `/api/health` answers, then after one
what-if and one agent replay (a recorded planner session streamed at speed 0).

| | After start | After a what-if | After an agent replay | Peak, scripted planner | Peak, verifier | Peak, watcher |
|---|---|---|---|---|---|---|
| Before | 2,656 MB | 2,658 MB | 2,658 MB | 1,044 MB (separate run) | | |
| After the store | 222 MB | 250 MB | 250 MB | | | |
| After the agents share it | 278 MB | 290 MB | 290 MB | 304 MB | 322 MB | 345 MB |

The last row is one process, the runs in that order, measured with `deploy/mem_api.py --agents` at a load average
of about 4. It is higher at start than the row above because the data build now carries 40-day outages and the
outage-ready fix, and because the core keeps the match columns agent F's tools filter on.

What changed:
- The merged table (facilities, matches, facility_results with about 150 columns, catchments) is no longer held in
  memory. `api/store_build.py` writes it once per data version, in a child process, to an on-disk store: each
  facility's full row as compressed JSON in SQLite (about 270 MB on disk), the feeder-row index, a core table of
  the 97 columns the routes filter, rank and sum on, the gzipped facility list, and the precomputed summary and
  supply calibration. The API loads only the core (about 60 MB) and reads full rows from SQLite per request.
- Evidence JSON, per-service hours, system specs and labels stay on disk. The unfiltered facility list is served
  from its gzipped file.
- Core strings are plain Python strings; columns that never enter a ranking or a money sum are float32; Arrow uses
  the system allocator and its pool is released after loading.
- Agent F's tools read the same store: `agents.tools.WardlightData(store=...)` takes the API's store object and
  serves `table`, `facilities`, `matches`, `nerc_rows` and `version` from the store's slim columns (renamed to the
  agents' names and tier rule), and reads a facility's full row from disk only when a tool returns it (`row`,
  `enrich`). No second copy of the frames is loaded. The watcher gets naija-grid caps for its two months only.
- The builder itself peaks at about 800 MB, so it should run on the Mac and its four files be copied to the VM
  (`deploy/README.md`).
- `WARDLIGHT_AGENT_RUNS=replay` remains as a guard that serves recorded sessions only; the unit runs all modes.

## Packages

None installed beyond `pyproject.toml`: form bodies are parsed with the standard library, and SSE uses FastAPI's
`StreamingResponse`.
