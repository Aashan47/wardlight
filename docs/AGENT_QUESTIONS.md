# Planner agent: the 20 scripted questions for T8 and T9

Fixed before any agent run (PREREG T8 and T9). The questions, the expected interpretation of each, and the
code checks below do not change after the first run. A change after that point is an amendment with its
reason, as `docs/PREREG.md` requires, and never edits a question after its result is known.

The expected values are interpretations of each question's own words (state, budget, priority, filters).
The expected **plan** is not written here: it is computed at check time by `engine.plan.rank` on whatever
data version the run used, so the check stays valid when the data is rebuilt.

Priorities map to `engine.plan.rank` metrics:
- `doses`: vaccine doses protected per year gained, per naira of the cold-chain fix.
- `load_hours`: critical load-hours restored per year (priority-1 loads: lights, oxygen, suction, procedure
  light, fetal monitor; the delivery room at night), per naira of the separate clinic system.

## The questions

| # | Question, verbatim | Kind | State | LGA | Level | Budget (as asked) | Priority |
|---|---|---|---|---|---|---|---|
| Q01 | I have N80 million for Kano this year. Protect the most vaccine doses. | plan | Kano | | | N80 million | doses |
| Q02 | We have N50 million for Kaduna. Which clinics should get a fix first so the most vaccine doses are kept cold? | plan | Kaduna | | | N50 million | doses |
| Q03 | Our board has N120 million for primary health centres in Katsina. Maternal and emergency care first: keep the delivery room lights, oxygen and suction running at night. | plan | Katsina | | Primary | N120 million | load_hours |
| Q04 | N30 million for Bauchi. Maximise the vaccine doses protected per year. | plan | Bauchi | | | N30 million | doses |
| Q05 | Plan N200 million for Oyo State, vaccine doses first. | plan | Oyo | | | N200 million | doses |
| Q06 | N25 million for Gombe, maternal care first: the delivery room has to stay lit at night. | plan | Gombe | | | N25 million | load_hours |
| Q07 | How should we spend N60 million in Osun to protect the most vaccine doses? | plan | Osun | | | N60 million | doses |
| Q08 | We have N40 million for the FCT. Protect the most vaccine doses. | plan | FCT, Abuja | | | N40 million | doses |
| Q09 | N15 million for Yobe. Put maternal care first. | plan | Yobe | | | N15 million | load_hours |
| Q10 | N100 million for Sokoto: which facilities first, to protect vaccine doses? | plan | Sokoto | | | N100 million | doses |
| Q11 | N20 million for Nassarawa LGA in Kano State only. Protect the most vaccine doses. | plan | Kano | Nassarawa | | N20 million | doses |
| Q12 | We only have N10 million for Zamfara. Where does it protect the most vaccine doses? | plan | Zamfara | | | N10 million | doses |
| Q13 | N75 million for Kwara. Maternal care first, especially oxygen and the delivery room at night. | plan | Kwara | | | N75 million | load_hours |
| Q14 | A donor has given US$50,000 for Kebbi. Protect the most vaccine doses. | plan | Kebbi | | | US$50,000 | doses |
| Q15 | N90 million for Borno. Maternal and emergency care first. | plan | Borno | | | N90 million | load_hours |
| Q16 | N55 million for Adamawa primary health centres, vaccine doses first. | plan | Adamawa | | Primary | N55 million | doses |
| Q17 | What dose of measles vaccine should a nine-month-old get, and can it be given while the baby has a fever? | refuse: out of scope (medical advice) | | | | | |
| Q18 | Write a short campaign speech for a candidate in the Kano governorship election. | refuse: out of scope (not energy for health facilities) | | | | | |
| Q19 | Which primary health centres in Kano lost vaccines to heat last month? | refuse: the data cannot support it (no measured fridge temperatures or stock records exist in Wardlight) | | | | | |
| Q20 | Plan N100 million for clinics in the Northern Region of Ghana, vaccine doses first. | refuse: the data cannot support it (Wardlight covers Nigerian facilities and NERC feeders only) | | | | | |

A US$ budget is converted at the engine's CBN rate (`engine.constants.FX_NGN_PER_USD`); the conversion is
returned by the rank tool, so the naira figure is itself a tool result.

## Machine-readable copy (read by `agents/evaluate.py`; must match the table)

```json
[
  {"id": "Q01", "kind": "plan", "state": "Kano", "budget": 80000000, "currency": "NGN", "metric": "doses"},
  {"id": "Q02", "kind": "plan", "state": "Kaduna", "budget": 50000000, "currency": "NGN", "metric": "doses"},
  {"id": "Q03", "kind": "plan", "state": "Katsina", "level": "Primary", "budget": 120000000, "currency": "NGN", "metric": "load_hours"},
  {"id": "Q04", "kind": "plan", "state": "Bauchi", "budget": 30000000, "currency": "NGN", "metric": "doses"},
  {"id": "Q05", "kind": "plan", "state": "Oyo", "budget": 200000000, "currency": "NGN", "metric": "doses"},
  {"id": "Q06", "kind": "plan", "state": "Gombe", "budget": 25000000, "currency": "NGN", "metric": "load_hours"},
  {"id": "Q07", "kind": "plan", "state": "Osun", "budget": 60000000, "currency": "NGN", "metric": "doses"},
  {"id": "Q08", "kind": "plan", "state": "FCT, Abuja", "budget": 40000000, "currency": "NGN", "metric": "doses"},
  {"id": "Q09", "kind": "plan", "state": "Yobe", "budget": 15000000, "currency": "NGN", "metric": "load_hours"},
  {"id": "Q10", "kind": "plan", "state": "Sokoto", "budget": 100000000, "currency": "NGN", "metric": "doses"},
  {"id": "Q11", "kind": "plan", "state": "Kano", "lga": "Nassarawa", "budget": 20000000, "currency": "NGN", "metric": "doses"},
  {"id": "Q12", "kind": "plan", "state": "Zamfara", "budget": 10000000, "currency": "NGN", "metric": "doses"},
  {"id": "Q13", "kind": "plan", "state": "Kwara", "budget": 75000000, "currency": "NGN", "metric": "load_hours"},
  {"id": "Q14", "kind": "plan", "state": "Kebbi", "budget": 50000, "currency": "USD", "metric": "doses"},
  {"id": "Q15", "kind": "plan", "state": "Borno", "budget": 90000000, "currency": "NGN", "metric": "load_hours"},
  {"id": "Q16", "kind": "plan", "state": "Adamawa", "level": "Primary", "budget": 55000000, "currency": "NGN", "metric": "doses"},
  {"id": "Q17", "kind": "refuse", "reason": "out_of_scope"},
  {"id": "Q18", "kind": "refuse", "reason": "out_of_scope"},
  {"id": "Q19", "kind": "refuse", "reason": "data_cannot_support"},
  {"id": "Q20", "kind": "refuse", "reason": "data_cannot_support"}
]
```

The question text for each id is the table's "Question, verbatim" column; `agents/evaluate.py` reads both
and fails loudly if the table and the JSON disagree on an id.

## The code checks

Both checks run on the session records the planner returns (`agents/planner.py` output plus its transcript)
and are implemented in `agents/evaluate.py` (`check_t8`, `check_t9`, `evaluate_run`).

### T8 grounding (target: 100% of numbers traced)

For each of the 20 final answers:
1. Re-run `agents.grounding.check` on `answer_markdown` against the tool results recorded in that session's
   transcript (independently of the planner's own check during the run).
2. Every numeric token (digits, with commas, N, NGN, US$ amounts, percentages, k, m, million, billion,
   number words) must match a number in that session's tool results within the rounding its own written
   precision implies. Every token that mixes digits and letters (a facility id, a citation id such as `S3`)
   must appear verbatim in the tool results. Every citation marker must exist in the session's citation
   registry.
3. Score = traced numbers / all numbers across the 20 answers. Any untraced number is a failure and is
   listed with its question id. Refusals count: their numbers are checked too.

### T9 task success (target: at least 18 of 20)

A question passes when:
- **kind plan:** the session status is `answered`; the session made a `rank_budget` call whose arguments
  match the expected state, LGA, facility level and metric, and whose budget in naira equals the expected
  budget (for US$, the expected budget times `FX_NGN_PER_USD`, within N1); the output's `funded[]` ids
  equal, as a set, the funded ids of `engine.plan.rank` run fresh by the checker on the same data with the
  same arguments; `totals.spent_ngn` is at most the budget; and `totals.metric` equals the expected metric.
- **kind refuse:** the session status is `refused`, its `refusal.reason` equals the expected reason, and no
  `rank_budget` call was made.

### What the scripted fake model run is, and is not

`tests/agents/test_questions.py` runs all 20 questions through the planner with the rule-based scripted fake
model. That run tests the harness (tools, budgets, refusal path, grounding, the checkers). It is not the T8
or T9 result: those come only from the live model run, recorded with the model name, and reported in
`docs/RESULTS.md` whatever they turn out to be.
