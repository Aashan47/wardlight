import json

import httpx
import pytest
import synth

from agents import events as EV
from agents import planner
from agents.fake import RuleBasedPlannerModel, compose_answer, parse_question
from agents.llm import (
    LLMError,
    OpenAICompatClient,
    ReplayClient,
    ReplayMismatch,
    ScriptedModel,
    assistant,
    tool_call,
)


def last_tool(messages, name=None):
    for m in reversed(messages):
        if m["role"] == "tool":
            return json.loads(m["content"])
    raise AssertionError("no tool result")


def plan_answer(messages, tools):
    r = last_tool(messages)
    t = r["totals"]
    return assistant(f"Funds {t['funded_count']} facilities for N{t['spent_ngn']:,.0f} of N{t['budget_ngn']:,.0f} "
                     f"[{r['cite']}].")


RANK = tool_call("rank_budget", {"state": "Kano", "budget": 3_500_000, "priority": "doses"}, "c1")


def run(steps, q="N3.5 million for Kano, doses.", **kw):
    return planner.run(q, ScriptedModel(steps), synth.toolbox(), **kw)


# ---------------------------------------------------------------- tool use and structured output


def test_tool_loop_and_structured_output_from_code():
    rec = run([assistant(calls=[RANK]), plan_answer])
    o = rec["output"]
    assert o["status"] == "answered" and o["grounded"] is True
    # synthetic doses per N1m: T2 950, T3 770, T1 490, T4 256; greedy fits T2 (N2m) and T3 (N1.5m) = N3.5m
    assert [f["unique_id"] for f in o["funded"]] == ["T2", "T3"]
    assert o["totals"]["spent_ngn"] == 3_500_000 and o["totals"]["funded_count"] == 2
    assert o["totals"]["not_ranked_unknown_supply"] == 1  # T5, refused match
    assert {n["unique_id"] for n in o["not_reached"]} == {"T1", "T4"}
    assert o["tool_calls"][0]["name"] == "rank_budget" and o["tool_calls"][0]["ok"]
    assert any(c["type"] == "engine_run" for c in o["citations"])
    assert o["client_kind"] == "scripted" and o["label"].startswith("scripted test model")


def test_usd_budget_is_converted_and_echoed():
    call = tool_call("rank_budget", {"state": "kano", "budget": 2000, "currency": "USD", "priority": "doses"}, "c1")
    rec = run([assistant(calls=[call]), lambda m, t: assistant(
        f"US$2,000 is N{last_tool(m)['budget_ngn']:,.0f} [{last_tool(m)['cite']}].")])
    o = rec["output"]
    assert o["status"] == "answered", o["grounding"]
    assert o["totals"]["budget_ngn"] == pytest.approx(2000 * 1352.371, abs=0.01)


def test_unknown_state_is_a_tool_error_not_a_crash():
    call = tool_call("rank_budget", {"state": "Accra", "budget": 1e6, "priority": "doses"}, "c1")
    rec = run([assistant(calls=[call]), assistant(calls=[tool_call("refuse", {
        "reason": "data_cannot_support", "explanation": "Accra is not in Nigeria's registry."}, "c2")])])
    assert rec["output"]["tool_calls"][0]["ok"] is False
    assert rec["output"]["status"] == "refused"
    assert rec["output"]["refusal"]["reason"] == "data_cannot_support"


# ---------------------------------------------------------------- refusal


def test_rule_prefilter_refuses_medical_advice_without_a_model_call():
    model = ScriptedModel([])
    rec = planner.run("What dose of measles vaccine should a nine-month-old get?", model, synth.toolbox())
    assert rec["output"]["status"] == "refused" and rec["output"]["refusal"]["by"] == "rule"
    assert model.calls == 0 and rec["output"]["usage"]["total_tokens"] == 0


def test_model_refusal_is_grounded():
    bad = assistant(calls=[tool_call("refuse", {"reason": "out_of_scope",
                                                "explanation": "I only do energy; 42 other topics are out."}, "c1")])
    rec = run([bad], q="Write a campaign speech.")
    o = rec["output"]
    assert o["status"] == "refused" and "42" not in o["answer_markdown"]  # ungrounded number replaced


# ---------------------------------------------------------------- grounding block and retry


def test_fabricated_number_blocked_then_retry_passes():
    fabricate = lambda m, t: assistant(f"Funds facilities and reaches 987,654 children [{last_tool(m)['cite']}].")
    rec = run([assistant(calls=[RANK]), fabricate, plan_answer])
    o = rec["output"]
    assert o["status"] == "answered" and "987,654" not in o["answer_markdown"]
    checks = [e for e in rec["events"] if e["type"] == "check"]
    assert [c["ok"] for c in checks] == [False, True]
    assert checks[0]["unmatched"] == ["987,654"]
    assert any(m["role"] == "user" and m["content"].startswith("GROUNDING CHECK FAILED") for m in rec["transcript"])


def test_second_failure_blocks_the_answer():
    fabricate = lambda m, t: assistant(f"Reaches 987,654 children [{last_tool(m)['cite']}].")
    rec = run([assistant(calls=[RANK]), fabricate, fabricate])
    o = rec["output"]
    assert o["status"] == "blocked" and o["answer_markdown"] == planner.BLOCKED_TEXT
    assert o["funded"] == [] and o["totals"] == {}
    assert "987,654" not in json.dumps(rec["events"][-2])  # the answer event never carries the number


def test_invented_citation_blocks():
    rec = run([assistant(calls=[RANK]), assistant("Spent N3,000,000 [S99]."), assistant("Spent N3,000,000 [S99].")])
    assert rec["output"]["status"] == "blocked"


def test_number_from_the_question_alone_is_not_enough():
    # the question says 3.5 million but no tool was called: the number is not a tool result
    rec = run([assistant("You have N3.5 million."), assistant("You have N3.5 million.")])
    assert rec["output"]["status"] == "blocked"


# ---------------------------------------------------------------- budgets


def test_step_budget():
    loop = [assistant(calls=[tool_call("list_facilities", {"state": "Kano"}, f"c{i}")]) for i in range(10)]
    rec = run(loop, budget=planner.Budget(max_steps=3))
    assert rec["output"]["status"] == "budget_exhausted" and rec["output"]["usage"]["steps"] == 3


def test_tool_call_budget():
    loop = [assistant(calls=[tool_call("list_facilities", {"state": "Kano"}, f"c{i}")]) for i in range(4)]
    rec = run(loop + [assistant("Nothing to report.")], budget=planner.Budget(max_tool_calls=2))
    assert rec["output"]["usage"]["tool_calls"] == 2
    errs = [json.loads(m["content"]) for m in rec["transcript"] if m["role"] == "tool"][2:]
    assert all("budget" in e["error"] for e in errs)


def test_token_budget():
    loop = [assistant(calls=[tool_call("list_facilities", {"state": "Kano", "limit": 25}, f"c{i}")]) for i in range(8)]
    rec = run(loop, budget=planner.Budget(max_tokens=1500))
    o = rec["output"]
    assert o["status"] == "budget_exhausted"
    assert any(e["type"] == "error" and "token budget" in e["message"] for e in rec["events"])


def test_long_tool_results_are_trimmed_by_whole_items():
    big = {"items": [{"n": i, "text": "x" * 50} for i in range(200)], "total": 200}
    s = planner.fit_result(big, 2000)
    d = json.loads(s)
    assert len(s) <= 2000 and d["trimmed_to_fit"] and d["total"] == 200 and len(d["items"]) < 200


# ---------------------------------------------------------------- events


def test_event_order_and_schema():
    rec = run([assistant(calls=[RANK]), plan_answer])
    evs = rec["events"]
    assert EV.validate(evs) == []
    types = [e["type"] for e in evs]
    assert types[0] == "plan" and types[-1] == "done" and types[-2] == "answer"
    assert types.index("tool_call") < types.index("tool_result") < types.index("check") < types.index("answer")
    assert "reasoning" not in types  # the scripted model returned no text with its tool calls
    chk = next(e for e in evs if e["type"] == "check")
    assert chk["kind"] == "grounding" and chk["ok"] and chk["numbers_checked"] == len(chk["matches"])
    assert all(m["matched"] is not None for m in chk["matches"])
    done = evs[-1]
    assert done["recorded"] is False and done["cost_usd"] == 0.0 and done["tokens"] > 0
    ans = evs[-2]
    assert ans["funded"] == rec["output"]["funded"] and ans["totals"] == rec["output"]["totals"]


def test_reasoning_only_when_the_model_wrote_text():
    said = assistant("I will rank Kano first.", [RANK])
    rec = run([said, plan_answer])
    rs = [e for e in rec["events"] if e["type"] == "reasoning"]
    assert [r["text"] for r in rs] == ["I will rank Kano first."] and rs[0]["source"] == "model"


def test_citation_events_carry_the_nerc_row():
    rec = run([assistant(calls=[tool_call("get_facility", {"unique_id": "T1"}, "c1")]),
               lambda m, t: assistant(f"Alpha PHC is on a Band B feeder [{last_tool(m)['nerc_rows'][0]['cite']}].")])
    cits = [e for e in rec["events"] if e["type"] == "citation"]
    assert cits and cits[0]["file"] == synth.ROW and cits[0]["page"] == 3 and cits[0]["sn"] == "7"


def test_replay_is_faithful(tmp_path):
    rec = run([assistant(calls=[RANK]), plan_answer])
    p = tmp_path / "s.json"
    EV.save_recording(p, "planner_session", rec["events"], "test")
    sleeps = []
    out = list(EV.replay(p, realtime=True, sleep=sleeps.append))
    assert [(e["seq"], e["t_ms"], e["type"]) for e in out] == [(e["seq"], e["t_ms"], e["type"]) for e in rec["events"]]
    assert out[-1]["recorded"] is True and EV.validate(out) == []
    assert sum(sleeps) == pytest.approx(rec["events"][-1]["t_ms"] / 1000, abs=1e-6)


# ---------------------------------------------------------------- clients


def test_replay_client_reruns_and_detects_changed_data():
    rec = run([assistant(calls=[RANK]), plan_answer])
    again = planner.run("N3.5 million for Kano, doses.", ReplayClient(rec["transcript"]), synth.toolbox())
    assert again["output"]["answer_markdown"] == rec["output"]["answer_markdown"]
    assert again["output"]["client_kind"] == "replay"
    tb = synth.toolbox()
    tb.data.results.loc[0, "capex_ngn"] = 900_000.0  # the data changed after recording
    with pytest.raises(ReplayMismatch):
        ReplayClient(rec["transcript"]).chat(
            rec["transcript"][:3] + [{"role": "tool", "tool_call_id": "c1", "content": "{}"}])


def test_live_client_request_shape_and_no_key_leak():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"model": "m1", "usage": {"prompt_tokens": 11, "completion_tokens": 3},
                                         "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                                             {"id": "x", "type": "function",
                                              "function": {"name": "refuse", "arguments": {"reason": "out_of_scope",
                                                                                           "explanation": "no"}}}]}}]})

    c = OpenAICompatClient("https://example.invalid/v1/", "m1", "sk-secret", transport=httpx.MockTransport(handler))
    r = c.chat([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "refuse"}}])
    assert seen["url"] == "https://example.invalid/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-secret" and seen["body"]["model"] == "m1" and seen["body"]["temperature"] == 0
    assert seen["body"]["tool_choice"] == "auto"
    assert json.loads(r.message["tool_calls"][0]["function"]["arguments"])["reason"] == "out_of_scope"
    assert r.usage == {"prompt_tokens": 11, "completion_tokens": 3}
    assert "sk-secret" not in repr(c)


def test_live_client_errors_and_env():
    with pytest.raises(LLMError, match="WARDLIGHT_LLM_API_KEY"):
        OpenAICompatClient.from_env({"WARDLIGHT_LLM_BASE_URL": "u", "WARDLIGHT_LLM_MODEL": "m"})
    c = OpenAICompatClient.from_env({"WARDLIGHT_LLM_BASE_URL": "https://e.invalid", "WARDLIGHT_LLM_MODEL": "m",
                                     "WARDLIGHT_LLM_API_KEY": "k"},
                                    transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad key")))
    with pytest.raises(LLMError, match="401"):
        c.chat([{"role": "user", "content": "hi"}])


def test_cost_needs_prices_from_env():
    assert EV.cost_usd(1_000_000, 0, "live", env={}) is None
    assert EV.cost_usd(1_000_000, 500_000, "live", env={EV.ENV_PRICE_IN: "0.2", EV.ENV_PRICE_OUT: "0.6"}) == 0.5
    assert EV.cost_usd(10, 10, "scripted") == 0.0


# ---------------------------------------------------------------- the rule-based fake


def test_fake_parser():
    p = parse_question("A donor has given US$50,000 for Kebbi. Protect the most vaccine doses.")
    assert p == {"budget": 50000.0, "currency": "USD", "state": "Kebbi", "priority": "doses"}
    p = parse_question("N20 million for Nassarawa LGA in Kano State only.")
    assert p["state"] == "Kano" and p["lga"] == "Nassarawa" and p["budget"] == 20e6
    assert parse_question("N25 million for Gombe, maternal care first")["priority"] == "load_hours"


def test_fake_end_to_end_with_fabricated_first_draft():
    rec = planner.run("N3.5 million for Kano. Protect the most vaccine doses.",
                      RuleBasedPlannerModel(fabricate_first=True), synth.toolbox())
    o = rec["output"]
    assert o["status"] == "answered" and o["grounding"]["ok"]
    assert [e["ok"] for e in rec["events"] if e["type"] == "check"] == [False, True]
    assert compose_answer  # imported for the record script


def test_unknown_tool_and_bad_json_arguments():
    bad = {"id": "c1", "type": "function", "function": {"name": "rank_budget", "arguments": "{not json"}}
    rec = run([assistant(calls=[bad, tool_call("nope", {}, "c2")]), assistant("Nothing to report.")])
    errs = [json.loads(m["content"])["error"] for m in rec["transcript"] if m["role"] == "tool"]
    assert "valid JSON" in errs[0] and "unknown tool" in errs[1]
