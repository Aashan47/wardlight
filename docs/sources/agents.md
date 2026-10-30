# Agents: design, guardrails and what remains for live wiring

Three agents from `11-AGENTS-DESIGN.md`, all in `build/wardlight/agents/`, each a Python generator of the event
stream the UI animates. The "AI with no data source" red flag is answered by construction: the agents can only
read Wardlight's own tables and engine through typed tools, and code checks every number they write.

## Modules

| Module | What it does |
|---|---|
| `tools.py` | `WardlightData` (facilities, matches, facility_results, nerc_rows, naija-grid band history; frames can be injected for tests), `Session` (citation registry, call log, last plan), `Toolbox` with eight tools: `list_facilities`, `get_facility`, `what_if`, `size_system`, `rank_budget`, `get_nerc_rows`, `band_history`, `refuse`. OpenAI-format specs in `TOOL_SPECS`. |
| `engine_adapter.py` | The only module that imports the engine (`plan.rank`, `coldchain.assess`, `sim.what_if`, `size.size_clinic`, `supply.sample_daily_hours`, the calibrated supply parameters). Returns plain dicts. If the engine's interfaces change, this is the one file to edit. |
| `grounding.py` | The numbers-only-from-tools check (below). |
| `planner.py` | The tool-calling loop: `run_events()` (generator) and `run()` (collected record). |
| `verifier.py` | The SMS or USSD question flow as a state machine (`VerifierSession`, `run_events`, `ussd`). |
| `watcher.py` | Band diff between two monthly orders, linking, re-run, band-change report (`run_events`, `run`, CLI). |
| `events.py` | Event schema, `EventLog`, `validate`, recordings (`save_recording`, `replay`), `cost_usd`. |
| `llm.py` | `OpenAICompatClient` (live, env-configured), `ScriptedModel` (tests), `ReplayClient` (fixture mode). |
| `fake.py` | `RuleBasedPlannerModel`: a scripted, rule-based stand-in for the planner model (not a language model). |
| `evaluate.py` | T8 and T9 checks against `docs/AGENT_QUESTIONS.md`; CLI `python -m agents.evaluate RUN_DIR`. |
| `record.py` | Records the fixture sessions in `data/fixtures/agents/`; CLI `python -m agents.record`. |

## Event stream (the contract with the API and the UI)

Every event is `{type, seq, t_ms, ...payload}`; `t_ms` is milliseconds since the run started. Required payload
keys (extra keys are allowed and listed in `events.py`):

| type | payload |
|---|---|
| `plan` | `steps: [{id, title}]` |
| `step_start` | `id` (one of the plan's ids; a step may start again, as `draft` and `check` do on a retry) |
| `reasoning` | `text, source: "model"`: only text the model returned alongside tool calls; never synthesised. The scripted model returns none, so recorded scripted sessions contain no reasoning events. |
| `tool_call` | `id, name, args` |
| `tool_result` | `id, summary, rows, ms` (+ `ok`; the verifier adds `reply, parsed, parsed_by, quote, interval`) |
| `check` | `kind: "grounding", numbers_checked, unmatched[], matches: [{text, value, matched}], ok` |
| `citation` | `facility_id, file, page, sn, row_text` (+ `cite`, `source_type`) |
| `answer` | `markdown, funded, not_reached, totals` (+ planner `status, citations`; verifier `sms, notes`; watcher `changes, facilities`) |
| `error` | `message` |
| `done` | `model, tokens, cost_usd, recorded, duration_ms` |

Order rules checked by `events.validate`: `plan` first, `done` last, `seq` consecutive, time never goes back,
every `tool_result` follows its `tool_call`, every `step_start` names a planned step. A recording keeps the
original `seq` and `t_ms`; only `done.recorded` is set true. `events.replay(path, realtime=True)` waits out the
original gaps.

## Planner output (`record["output"]`, also the `answer` event)

`{answer_markdown, funded[], not_reached[], not_reached_groups{}, totals{}, plan_args, citations[], tool_calls[],
model, client_kind, grounded: true, status, refusal, grounding, usage, budget, data_version, label}`.

- `status`: `answered`, `refused` (`refusal.reason` is `out_of_scope` or `data_cannot_support`, `refusal.by` is
  `rule` or `model`), `blocked` (the draft failed grounding twice; a fixed text with no numbers is returned) or
  `budget_exhausted`.
- `funded[]` items: `rank, unique_id, name, lga, tier, cost_ngn, benefit, uptime_today, uptime_with_fix,
  fix_label, reason, cite`. `not_reached[]`: the next ranked facilities the budget did not reach (up to 25) with
  `why_not_funded`; `not_reached_groups`: counts and reasons for ranked-not-funded, unknown supply (refused
  match) and no engine result.
- `totals`: `budget_ngn, spent_ngn, remaining_ngn, funded_count, benefit_total, metric, benefit_unit, cost_basis,
  candidates_ranked, ranked_not_funded, not_ranked_unknown_supply, no_engine_result, facilities_in_scope`.
- These structured fields are filled by code from the `rank_budget` result (the full `engine.plan.rank` output),
  never from model text. `grounded: true` holds for every emitted answer because an ungrounded draft is never
  emitted.

## Guardrails

1. **Numbers only from tools** (`grounding.check`). Every numeric token in the draft (digits with commas, N,
   NGN, US$ and $ amounts, percentages, k, m, million, bn, billion, number words, numbers glued to units, both
   ends of a range) must match a number in the tool results the model saw in that session, within the rounding
   its written precision implies; an integer with trailing zeros may also round at its last non-zero digit, within
   1%. Tokens mixing digits and letters (facility ids, file names, model codes, months) must appear verbatim in
   the tool results. Citation ids must exist in the session's registry, and an answer that states numbers must
   cite. A failure gives the model the list of problems and one retry; a second failure blocks the answer. Tool
   results echo their inputs (state, budget, priority, FX rate), so a figure the user typed is a tool result
   when repeated; a figure only in the question is not, and blocks. The refuse tool's own echo is excluded, so a
   refusal cannot ground itself (a test caught that bug).
2. **Citations**: tools register sources (`facility` with its GRID3 row, match evidence and results row;
   `nerc_row` with file, page and serial number; `engine_run`; `naija_grid`) and return `cite: "S<n>"`. Citation
   events carry the NERC file, page, serial number and row text for the evidence panel.
3. **Scope**: a narrow rule pre-filter refuses clear medical-advice requests with no model call; the model must
   call `refuse` for anything else out of scope or when the data cannot answer. Unknown states return a tool error
   that lists the valid states (Nigeria only).
4. **Budgets per session** (`planner.Budget`): 8 model steps, 24,000 tokens, 10 tool calls, 10,000 characters per
   tool result (long lists are cut by whole items and marked `trimmed_to_fit`), 900 tokens per model reply, one
   grounding retry. Exhausting any of them ends the session with an `error` event and no answer.
5. **Verifier**: rule parsing first; free text goes to the model only through `record_answer`, accepted only when
   the quote is verbatim in the reply and, for hours, the number is in the quote. One re-ask, then unknown. Every
   output says "sandbox, simulated replies"; the code sends nothing itself. A reported fridge type picks the
   equipment scenario (inside the envelope, so never wider). Reported hours enter as an observation, never as a
   band: the supply becomes daily hours drawn around the reply (normal, sd 2 h, an assumption) with the engine's
   outage timing, and the reply is scored against the prior band mixture; under 5% of the prior's modelled days
   within 2 h means it contradicts the prior, and the event says so. Every re-run event carries `width_before`,
   `width_after`, `widened`, `contradicts_prior` and a `note`; a refused facility's hours are recorded, not
   modelled.
6. **Watcher**: real changes only (feeders listed in both months whose band differs); links by exact normalised
   feeder name within the DisCo, no fuzzy guessing; its report text is grounded against its own records.

## What the scripted fake model can and cannot show

It can show: the full tool loop on the real data and engine; the event stream with real timings; the grounding
block and retry (`fabricate_first=True` inserts one invented figure in the first draft); refusals; budgets; the
T8 and T9 checkers working (all 20 questions pass the harness checks with it). It cannot show: whether a
language model chooses the right tools and arguments, writes a clear answer, stays inside its budgets, or refuses
correctly on its own. It never produces reasoning text, so no reasoning event appears in its sessions. Its runs
are never the PREREG T8 or T9 result (`evaluate_run` reports `counts_as_prereg_result: false` unless every
session ran on the live client).

## A finding from building the watcher

Wardlight reads NERC's September 2026 supply-schedule orders (`nerc_rows`). For KAEDC, those rows' bands agree
with naija-grid's October 2026 cap orders for 99% of linked feeders but with its September cap orders for 54%: the
September schedule already carries the October re-banding. So for the September to October diff, almost every
affected facility is marked `wardlight_status: "current"` (Wardlight already shows the new band) and the report
says what the change did rather than claiming an update was needed. Across all DisCos, the September rows Wardlight
reads agree with naija-grid's cap-order band for the same feeder name at rates from 50% (BEDC) to 99% (YEDC),
measured once by exact name match while building this; worth a look by the matcher (agent B), reported here,
not fixed.

## Fixtures (`data/fixtures/agents/`, all marked recorded)

- `planner_kano_doses.json` (Q01), `planner_grounding_block.json` (Q06, the blocked first draft and the passing
  retry), `planner_refusal_medical.json` (Q17, rule pre-filter): scripted model, real tools and data, full
  event list, output and transcript.
- `verifier_sms_sandbox.json`: one multi-band facility, typed sandbox replies, interval before and after.
- `watcher_2026-09_to_2026-10.json` plus `watcher/band_changes_2026-09_to_2026-10.json` and `.md`: the real
  diff and re-run. Re-record after any data rebuild with `python -m agents.record`.

## What remains for live wiring (main session, after his approval)

1. **Model choice on Nebius Token Factory.** List the models his key can reach (`GET {base_url}/models`, OpenAI
   format) at integration, with his approval of the `.env` read; pick an open model whose listing says it
   supports tool calling; set `WARDLIGHT_LLM_BASE_URL`, `WARDLIGHT_LLM_MODEL`, `WARDLIGHT_LLM_API_KEY`. The model
   name flows into `done.model` and the output.
2. **Cost per session, estimated before any spend.** Each session records `usage.prompt_tokens` and
   `usage.completion_tokens`. Run Q01 once live, read its usage, and compute cost = prompt tokens x input price +
   completion tokens x output price, using the per-million prices from the Nebius pricing page for the chosen
   model, quoted with the page. Set them as `WARDLIGHT_LLM_USD_PER_M_INPUT` and `WARDLIGHT_LLM_USD_PER_M_OUTPUT`
   so `done.cost_usd` is filled (it stays null, never guessed, when they are unset). For scale only: the scripted
   sessions measured about 6,400 to 10,700 prompt tokens over three or four steps (estimated as characters / 4);
   a live model's count will differ and is the figure to use. Twenty T8/T9 sessions = 20 times the measured per-session cost; raise it with him if the total
   would pass $0.50.
3. **API** (agent E): stream `run_events` as Server-Sent Events; cache by hash of (question, model, data
   version); per-visitor rate limit and a daily cap; fixture mode serves `events.replay` of the recordings,
   labelled "recorded session". The verifier needs the Africa's Talking sandbox callbacks to feed
   `VerifierSession.handle` (SMS) or `verifier.ussd` (USSD).
4. **The T8 and T9 run**: the 20 questions on the live model, records saved per question, then
   `python -m agents.evaluate RUN_DIR`, and the results, misses included, in `docs/RESULTS.md`.

## Packages

No package was installed: the live client uses `httpx`, already a project dependency.
