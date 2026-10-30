# Pre-registration

Written before any data was parsed, matched or modelled. These targets are fixed. Results are
reported against them in `docs/RESULTS.md` whatever they turn out to be, misses next to hits. Any change to
this file after the sprint starts is an amendment, dated, with its reason, and never edits a target after
its result is known.

## What the product claims

For each health facility it reports (a) the share of days in a year its vaccine fridge stays at 2 to 8 °C,
today and with a recommended solar and battery system, and (b) the doses that protects per year. Grid supply
comes from NERC's published feeder band (minimum hours) where a facility can be matched to a feeder, from a
public grid map where it cannot, and is otherwise refused.

## Targets

| ID | What is measured | Target | How |
|---|---|---|---|
| T1 | Reading NERC's feeder appendices (band, feeder name, location, streets, minimum hours) | at least 97% of spot-checked rows correct | 200 rows drawn at random (seed 20261030) across all DisCos, checked by eye against the page image |
| T2 | Facility to feeder matching, tiers (a) named and (b) town or ward | at least 90% correct | a random sample of 100 tier (a) and (b) matches (seed 20261031), checked by eye against the evidence row; tier (c) and refusal shares reported with no target |
| T3 | Supply model calibration | NERC's published measured hours for failing Band A feeders fall inside the model's 90% interval for at least 85% of them | every failing feeder in the orders obtained |
| T4 | Solar resource | annual PV yield from NASA POWER within 10% of PVGIS at 20 sample sites | sites drawn at random from facility locations (seed 20261030) |
| T5 | Sizing sanity | a typical primary health centre sizes inside SEforALL's published range, or the difference is explained | the published load list, the SEforALL range quoted in `docs/SOURCES.md` |
| T6 | Speed | what-if simulation under 1 s at the 95th percentile | 200 random facilities on the deployed server |
| T8 | Agent grounding | 100% of numbers in the planner agent's final answers traced to a tool result in the same session | 20 scripted planner questions, fixed in `docs/AGENT_QUESTIONS.md` before any agent run; checked by code |
| T9 | Agent task success | the plan respects the budget and the stated priority in at least 18 of the 20 | checked by code against `plan.rank` |
| T7 | Brief metric | fridge uptime and doses protected reported per facility with every input sourced | no target: no measured uptime exists to compare against, and the product says so |

## What would count as failure

- T1 or T2 below target: the affected tier is shown with its measured error rate, and facilities that depend
  on it carry a warning.
- T3 below target: the supply interval is widened until the back-test passes, and the widening is reported.
- Any refusal is a result, never hidden.
