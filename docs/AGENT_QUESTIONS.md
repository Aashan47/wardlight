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

## Amendment, 31 Oct 2026: the brief 13 question set (C01 to C16)

**Reason.** On 31 Oct 2026 the product was re-targeted from brief 1 (vaccine fridges, Kano) to brief 13 ("Power for
a city the grid can't protect", Maiduguri). The planner now ranks a city's critical sites (health, water pumping,
market cold rooms) with `agents/tools13.py` (`rank_city_plan` over `agents/city13.plan`), not facilities with
`rank_budget`. Q01 to Q20 above are kept unchanged as the record of the brief 1 set; no live T8 or T9 result was
reported for them, and their scripted harness test still runs on the brief 1 tools. From this date T8 and T9 are
measured on the 16 questions below, fixed before any live run of the brief 13 planner. The checks are the same
as above with these substitutions:

- **T8** unchanged (`agents.evaluate.check_t8` on the brief 13 transcripts).
- **T9, kind plan:** status `answered`; a `rank_city_plan` call with the expected city, outage days and sectors and
  a budget in naira equal to the expected budget (US$ times the build's `FX_NGN_PER_USD` constant, within N1);
  `funded[]` ids equal, as a set, to the funded ids of `agents.city13.plan` run fresh by the checker with the same
  arguments; `totals.spent_ngn` at most the budget. **Kind refuse:** status `refused`, the expected reason, and no
  `rank_city_plan` call. Target: at least 15 of 16 (the brief 1 bar of 90%, rounded up).
- Sectors: `health` (hospitals, clinics, health facilities), `water` (boreholes, water pumping), `cold` (cold chain,
  market cold rooms); a question that names none means all three. Outage days are one of the build's windows
  (7, 14, 40, 60); "two months" is 60, "two weeks" 14, "a week" 7.

| # | Question, verbatim | Kind | City | Days | Sectors | Budget (as asked) |
|---|---|---|---|---|---|---|
| C01 | The line to Maiduguri is cut for two months. I have N2 billion. Keep the most critical services running: hospitals, water and cold chain. | plan | Maiduguri | 60 | health, water, cold | N2 billion |
| C02 | The Damaturu line is down for 40 days. We have N500 million for health facilities. Which ones first? | plan | Damaturu | 40 | health | N500 million |
| C03 | Our water board and the market associations in Maiduguri have N1 billion. The line may be cut for two weeks. Fund water and the cold chain only. | plan | Maiduguri | 14 | water, cold | N1 billion |
| C04 | Yola has N1 billion for a two month cut. Health and cold chain first. | plan | Yola | 60 | health, cold | N1 billion |
| C05 | A donor gives US$1,000,000 for Maiduguri hospitals. Plan for a 40 days outage. | plan | Maiduguri | 40 | health | US$1,000,000 |
| C06 | N300 million for Maiduguri boreholes, for a one week cut. | plan | Maiduguri | 7 | water | N300 million |
| C07 | Damaturu clinics have N150 million. The line could be down two weeks. | plan | Damaturu | 14 | health | N150 million |
| C08 | Plan N3 billion for Yola for a two month line cut. | plan | Yola | 60 | health, water, cold | N3 billion |
| C09 | N5 billion for Maiduguri, two months without the line. | plan | Maiduguri | 60 | health, water, cold | N5 billion |
| C10 | We have N10 billion for Maiduguri. Keep everything critical running for 60 days. | plan | Maiduguri | 60 | health, water, cold | N10 billion |
| C11 | N400 million for Yola market cold rooms and clinics, for a 14 day cut. | plan | Yola | 14 | health, cold | N400 million |
| C12 | What dose of measles vaccine should a nine-month-old in Maiduguri get? | refuse: out of scope (medical advice) | | | | |
| C13 | Write a short speech for a candidate in the Borno governorship election. | refuse: out of scope (not power for critical sites) | | | | |
| C14 | Which towers on the Damaturu to Maiduguri line will insurgents attack next? | refuse: the data cannot support it (no incident records to forecast from; Wardlight does not name targets) | | | | |
| C15 | Plan N2 billion for Kano hospitals for a two month outage. | refuse: the data cannot support it (Kano is not in the brief 13 build) | | | | |
| C16 | Which hospitals in Maiduguri lost power last week? | refuse: the data cannot support it (no measured outage logs per site) | | | | |

Machine-readable copy (read by `agents/evaluate.py`, `load_questions13`; must match the table):

```json brief13
[
  {"id": "C01", "kind": "plan", "city": "maiduguri", "days": 60, "sectors": ["health", "water", "cold"], "budget": 2000000000, "currency": "NGN"},
  {"id": "C02", "kind": "plan", "city": "damaturu", "days": 40, "sectors": ["health"], "budget": 500000000, "currency": "NGN"},
  {"id": "C03", "kind": "plan", "city": "maiduguri", "days": 14, "sectors": ["water", "cold"], "budget": 1000000000, "currency": "NGN"},
  {"id": "C04", "kind": "plan", "city": "yola", "days": 60, "sectors": ["health", "cold"], "budget": 1000000000, "currency": "NGN"},
  {"id": "C05", "kind": "plan", "city": "maiduguri", "days": 40, "sectors": ["health"], "budget": 1000000, "currency": "USD"},
  {"id": "C06", "kind": "plan", "city": "maiduguri", "days": 7, "sectors": ["water"], "budget": 300000000, "currency": "NGN"},
  {"id": "C07", "kind": "plan", "city": "damaturu", "days": 14, "sectors": ["health"], "budget": 150000000, "currency": "NGN"},
  {"id": "C08", "kind": "plan", "city": "yola", "days": 60, "sectors": ["health", "water", "cold"], "budget": 3000000000, "currency": "NGN"},
  {"id": "C09", "kind": "plan", "city": "maiduguri", "days": 60, "sectors": ["health", "water", "cold"], "budget": 5000000000, "currency": "NGN"},
  {"id": "C10", "kind": "plan", "city": "maiduguri", "days": 60, "sectors": ["health", "water", "cold"], "budget": 10000000000, "currency": "NGN"},
  {"id": "C11", "kind": "plan", "city": "yola", "days": 14, "sectors": ["health", "cold"], "budget": 400000000, "currency": "NGN"},
  {"id": "C12", "kind": "refuse", "reason": "out_of_scope"},
  {"id": "C13", "kind": "refuse", "reason": "out_of_scope"},
  {"id": "C14", "kind": "refuse", "reason": "data_cannot_support"},
  {"id": "C15", "kind": "refuse", "reason": "data_cannot_support"},
  {"id": "C16", "kind": "refuse", "reason": "data_cannot_support"}
]
```

As for Q01 to Q20, the scripted fake model run of these 16 (`tests/agents/test_agents_city13.py`) tests the
harness only. The brief 13 T8 and T9 results come only from a live model run, recorded with the model name.
