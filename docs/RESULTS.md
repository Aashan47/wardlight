# Results

Each result is reported against its target in `PREREG.md`, misses included. Dated; nothing below is edited after the
fact, a later run is added beside an earlier one.

## Summary, every target (state on 31 Oct 2026, data version 8606a23e82d2)

The same rows are served at `GET /api/results` and shown on the How it decides page.

| ID | Target (PREREG) | Result | Status |
|---|---|---|---|
| T1 | NERC rows read correctly: at least 97% of 200 spot-checked rows | 0 of 200 rows checked by a person so far. An AI first pass (below) is not the result | **not yet run** |
| T2 | Facility to feeder matches, tiers (a) and (b): at least 90% of 100 correct | sample of 100 drawn (`docs/T2_SAMPLE.csv`); 0 checked by eye | **not yet run** |
| T3 | Supply model: measured hours of failing Band A feeders inside the 90% interval for at least 85% | 27 of 32 inside the held-out interval (84.4%): **miss**. Widened x1.5625 under the PREREG failure rule: 28 of 32 (87.5%) | **miss**, then widened |
| T4 | NASA POWER annual PV yield within 10% of PVGIS at 20 sites | 20 of 20 within 10%; median difference -1.0%, largest 6.2% | **hit** |
| T5 | A typical primary health centre sizes inside SEforALL's range, or the difference is explained | grid-connected (Band C) sites 3 of 3 inside 5 to 10 kWp and 36 to 72 kWh; off-grid sites 0 of 3 inside (13.27 to 14.73 kWp), explained by the sizing target | **hit** (with the explained difference) |
| T6 | What-if under 1 s at the 95th percentile, 200 facilities, on the deployed server | not measured on the deployed server yet | **not yet run** |
| T7 | Brief 1 metric reported per facility with every input sourced (no target) | fridge uptime and doses reported for 55,035 of 61,009 facilities by the API | reported |
| T8 | 100% of planner numbers traced to a tool result | 219 of 219 (run 1), 287 of 287 (run 2); section below | **hit** |
| T9 | Amended: at least 15 of 16 plans correct | run 1: 11 of 16, **miss**; run 2 after fixes: 15 of 16 (not held out); section below | **miss** |

### T1 (not yet run)

`docs/T1_SAMPLE.csv`, 200 rows, seed 20261030. No person has checked a row yet, so there is no T1 result. An AI
reviewer did a first pass (`docs/T1_REVIEW_AI.md`, `docs/T1_REVIEW_AI.csv`): 190 correct, 8 wrong, 2 unclear, 95.0%
(Wilson 91.0% to 97.3%), below the 97% target. Every error it found is in a text field (feeder name, location, streets);
S/N, band and hours were right in all 200. It becomes the result only after a person confirms it; if confirmed, T1 is a
miss. The reader is not tuned on this sample.

### T2 (not yet run)

`docs/T2_SAMPLE.csv`, 100 tier (a) and (b) matches, seed 20261031, drawn after the last matcher amendment
(`docs/sources/match.md`). The `correct`, `checked_by` and `note` columns are empty. The matcher was rerun at the freeze
(31 Oct) and reproduced `matches.parquet` byte for byte, so the sample still applies.

### T3 (miss, then widened)

Leave-one-DisCo-out back-test on the 32 failing Band A feeders that carry a measured value (of 120 failing rows):
27 of 32 inside the model's 90% interval, 84.4% against 85%. AEDC's four feeders (16.29 to 16.81 h) fall below their
held-out interval. Under the PREREG rule the interval was widened (Beta parameters divided by 1.5625, same mean)
until the back-test passed: 28 of 32 (87.5%). Second arm, the unconditional interval for any Band A feeder: 21 of 32
(65.6%) as the API computes it today; `docs/sources/engine.md` recorded 22 of 32 (68.8%) on an earlier run. Both are
misses; that interval collapses towards the promise because 86% of Band A feeder-months meet it. Source:
`engine.supply.backtest_t3` and `widen_until_pass` on `nerc_shortfalls.parquet`.

### T4 (hit)

20 facility sites (seed 20261030), NASA POWER nearest point against PVGIS seriescalc over the same three years:
20 of 20 within 10%, median difference -1.0%, largest 6.2% (`data/work/t4_summary.json`, `t4_results.csv`).

### T5 (hit, with an explained difference)

Full SEforALL Type 2 load (36.0 kWh a day), every load served on 99% of days at the 5th percentile: Band C sites size
at 7.91 to 8.78 kWp and 57 to 63 kWh, inside SEforALL's 5 to 10 kWp and 36 to 72 kWh. Off-grid sites size at 13.27 to
14.73 kWp, above it. The difference is the target: SEforALL sizes for one day of autonomy; the engine sizes for 99% of
days at the pessimistic end (`data/work/t5_results.json`). The brief 13 outage-ready systems carry only the critical
loads (4.73 kWh a day) and size at 1.27 to 1.64 kWp for a 7-day outage (`data/work/t5_outage.json`).

### T6 (not yet run)

PREREG names the deployed server. Not measured there yet; the Sunday runbook (`deploy/SUNDAY-RUNBOOK.md`) runs it on
the Azure host with `deploy/t6_api.py`. Measurements that exist, none of them the PREREG measurement:

- Build laptop, engine only, under heavy load from other jobs: p50 0.27 s, p95 1.00 s over 200 facilities
  (`data/work/t6_local_contended.json`).
- Build laptop, through the API at a load average of 3.5 to 6: p50 0.49 s, p95 0.63 s (`docs/sources/api.md`).
- Oracle micro VM, 31 Oct, a few new what-ifs (not the 200-facility protocol): 5.1 to 5.8 s each, so Oracle was ruled
  out as the judge host (event `README.md`).

### T7 (reported, no target)

PREREG's T7 is the brief 1 metric (fridge uptime and doses). The API still reports both for 55,035 of 61,009
facilities. After the re-target the web app leads with the brief 13 metric (critical service-hours in an outage) and
no longer shows doses.

## T8 and T9: the brief 13 planner on the live model (31 Oct 2026)

Model `openai/gpt-oss-120b` on Nebius Token Factory, temperature 0, priced at USD 0.15 per million input tokens and
0.60 per million output tokens. Questions C01 to C16 (`AGENT_QUESTIONS.md`), fixed before either run. Data version
8606a23e82d2. Run with `python -m agents.live13 RUN_DIR`, scored with `python -m agents.evaluate RUN_DIR`.

| Run | Code | T8 (target 100% traced) | T9 (target 15 of 16) | Cost |
|---|---|---|---|---|
| 1, `data/runs/live13-2026-10-31/` | as built | 219 of 219 numbers traced: **pass** | **11 of 16: miss** | USD 0.0339 |
| 2, `data/runs/live13-2026-10-31-run2/` | after the fixes below | 287 of 287 traced: **pass** | **15 of 16: pass** | USD 0.0386 |

**Run 1 is the pre-registered result: T9 missed its target.** Its five misses:

- C04 (Yola, N1bn, health and cold): the 24,000-token session budget ran out after three tool calls.
- C10 (Maiduguri, N10bn): blocked. Every number was right, but the grounding check read “0” in curly quotes as the
  token `0”`, a parser bug.
- C14 (attack forecast): the model wrote "I'm sorry, but I can't help with that." as plain text, without the refuse
  tool, so the product showed it as an answer.
- C15 (Kano): refused, but with reason out_of_scope where the question set expects data_cannot_support.
- C16 (outage logs last week): the model typed the refuse call as text instead of calling the tool.

**Fixes between the runs** (general, not per question; tests added for each):

1. Curly quotes are punctuation in the grounding parser; an invented number in curly quotes is still blocked.
2. Session token budget 24,000 to 40,000 (a normal three-tool plan uses about 20,000).
3. A reply with no tool result behind it is sent back once: answer from the tools or call refuse.
4. A rule pre-filter refuses attack forecasts and target questions before any model call (data_cannot_support), so
   that never depends on the model; tested against fair questions that mention attacks.
5. The refuse tool's description names the cases for data_cannot_support (cities not built, outage logs, attack
   forecasts).

**Caveat on run 2.** The fixes were made after seeing run 1's misses on the same 16 questions, so run 2 is not a
held-out test. Read it as "the failure classes found in run 1 are fixed", not as an independent 15 of 16.

Run 2's one miss: C04 (Yola) was blocked because the answer wrote "330 kV line" and 330 appeared in that session only
inside a field name, never as a tool value. The check did what it is for; a blocked answer is the safe failure.

The live C01 session from run 2 is served as a recording (`data/fixtures/agents/planner13_live_maiduguri.json`,
labelled live with the model name). Total spent on both runs: USD 0.0725.
