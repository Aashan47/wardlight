"""The planner agent: a tool-calling loop that turns a budget question into a costed, cited plan.

    for ev in planner.run_events(question, client, toolbox): ...   # the event stream (agents/events.py)
    record = planner.run(question, client, toolbox)                 # same run, collected

Guardrails, all enforced by code:
- scope: a narrow rule pre-filter refuses clear medical-advice questions before any model call; otherwise the
  model must call `refuse` for out-of-scope questions or when the data cannot answer;
- budgets per session: model steps, total tokens, tool calls, characters per tool result;
- numbers only from tools: the final draft goes through `agents.grounding.check` against the tool results the
  model saw in this session; an unmatched number, an unknown id, an invented or missing citation blocks it;
  the model gets one retry with the problems listed; a second failure returns a fixed no-number message;
- the structured fields (funded, not_reached, totals, citations) are filled by code from the rank tool's
  result, never from model text.

Output schema (record["output"]):
{answer_markdown, funded[], not_reached[], totals{}, citations[], tool_calls[], model, grounded: true,
 status: answered | refused | blocked | budget_exhausted, refusal, grounding, usage, client_kind, label}
`grounded` is always true for an emitted answer: an ungrounded draft is never emitted.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass

from . import events as EV
from . import grounding as G
from .llm import ChatClient, LLMError, estimate_tokens
from .tools import TOOL_SPECS, Session, Toolbox

SYSTEM_PROMPT = """You are the Wardlight planner. You help a Nigerian state primary health care board or a funder \
decide which health facilities get a vaccine cold-chain fix (and, separately, a clinic solar system) under a budget, \
using only Wardlight's tools.

Rules:
1. Scope: only power, solar and the vaccine cold chain for Nigerian health facilities. For anything else, including \
medical or clinical advice (what dose a patient should get, symptoms, treatment), call refuse with reason \
out_of_scope. When the data cannot answer (measured temperatures, stock losses, outage logs, places outside \
Nigeria, future NERC orders), call refuse with reason data_cannot_support and say what is missing.
2. Numbers: every number you write must be copied from a tool result in this conversation; you may round it. Do \
not compute new figures (no sums, differences or percentages you were not given). Code checks every number and \
blocks the answer if one does not match.
3. Citations: after each claim about a plan total, a facility or a NERC row, cite the id the tool gave, like [S3]. \
Use only ids that tools returned.
4. For a budget question: call rank_budget once with the state, the budget (currency USD if the user gave \
dollars), the priority ('doses' for vaccines; 'load_hours' for maternal, delivery-room or emergency care at \
night) and the lga or facility_level if the user named one. Then check the evidence for the top pick with \
get_facility. Use what_if only for a borderline pick.
5. Answer in short markdown: the plan (facilities funded, spent, remaining, combined gain), the top picks with \
their fix and cost, what the money does not reach and why, and these labels: doses are estimates; grid supply \
is modelled from NERC's band promise, promised and not measured. Plain words, no em dashes.
6. Wording: facilities the budget does not reach rank below the funded ones (never call them higher-ranked). \
Write numbers with plain ASCII commas or no separators, and put the citation after a space, like 68 [S1]."""

BLOCKED_TEXT = ("No answer is shown: the draft contained figures that could not be traced to Wardlight's data "
                "in this session, and the retry did not fix them.")
BUDGET_TEXT = "No answer is shown: this session's step or token budget was spent before an answer was ready."
REFUSAL_TEXT = {
    "out_of_scope": "This is outside what Wardlight answers: power and the vaccine cold chain for Nigerian health "
                    "facilities, from its own data.",
    "data_cannot_support": "Wardlight's data cannot answer this question.",
}
NO_TOOLS_TEXT = ("That reply has no tool result behind it, so it cannot be shown. Answer the question with the tools, "
                 "or call the refuse tool with a reason and an explanation.")
MEDICAL_RULE = re.compile(
    r"\b(what dose|how many doses should|which vaccine should|symptoms?|diagnos\w*|prescri\w*|side effects?|"
    r"should (i|she|he|my child|the baby) (take|get|receive)|treatment for|is it safe to (give|take))\b", re.IGNORECASE)
# Wardlight never forecasts attacks or names targets: refused by rule, so it never depends on the model's judgement
ATTACK_RULE = re.compile(
    r"\b(predict|forecast)\w*\b[^.?!]*\b(attack|vandal|sabotag|bomb|insurgen|target)\w*"
    r"|\b(attack|vandal|sabotag|bomb|hit|target)\w*\s+next\b"
    r"|\b(which|where)\s+(\w+\s+){0,8}?(will|is likely to|are likely to)\s+(be\s+)?"
    r"(the\s+)?((insurgen\w*\s+|militant\w*\s+|they\s+)?(attack|vandal|sabotag|bomb|target)\w*"
    r"|(insurgen\w*|militant\w*|they)\s+hit)", re.IGNORECASE)  # "be hit hardest by a cut" is a fair question
ATTACK_TEXT = (" Wardlight has no incident records to forecast from, and it does not name sites or towers as "
               "targets.")

PLAN_STEPS = [
    {"id": "scope", "title": "Check the question is in scope"},
    {"id": "gather", "title": "Read the data with tools"},
    {"id": "draft", "title": "Draft the answer"},
    {"id": "check", "title": "Check every number against the tool results"},
    {"id": "answer", "title": "Answer with citations"},
]


@dataclass
class Budget:
    max_steps: int = 8
    max_tokens: int = 40000  # live run 31 Oct: a normal brief 13 plan with three tool calls used about 20,000
    max_tool_calls: int = 10
    max_tool_result_chars: int = 10000
    max_answer_tokens: int = 900
    retries: int = 1


def scope_prefilter(question: str) -> str | None:
    """'out_of_scope' for clear requests for medical advice, 'data_cannot_support' for attack forecasts and
    targets; None otherwise (the model decides the rest)."""
    if MEDICAL_RULE.search(question or ""):
        return "out_of_scope"
    return "data_cannot_support" if ATTACK_RULE.search(question or "") else None


def fit_result(res: dict, max_chars: int) -> str:
    """JSON for the model, within max_chars: long lists are shortened (whole items dropped, never a number cut
    in half) and the result says so; only as a last resort is the text cut."""
    def dump(x):
        return json.dumps(x, default=str, ensure_ascii=False)

    content = dump(res)
    if len(content) <= max_chars:
        return content
    res = json.loads(content)

    def lists(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from lists(v)
            for k, v in o.items():
                if isinstance(v, list) and len(v) > 1:
                    yield o, k
        elif isinstance(o, list):
            for v in o:
                yield from lists(v)

    while len(content) > max_chars:
        cands = sorted(lists(res), key=lambda ok: len(dump(ok[0][ok[1]])), reverse=True)
        if not cands:
            break
        o, k = cands[0]
        o[k] = o[k][: max(1, len(o[k]) // 2)]
        res["trimmed_to_fit"] = True
        content = dump(res)
    if len(content) > max_chars:
        content = content[:max_chars] + " ...[truncated]"
    return content


def _summary(name: str, res: dict) -> tuple[str, int]:
    """One-line summary and row count of a tool result, from its own fields."""
    if res.get("error"):
        return f"error: {res['error'][:160]}", 0
    if name == "rank_budget":
        t = res["totals"]
        return (f"{t['funded_count']} funded of {t['candidates_ranked']} ranked in {res['state']}; "
                f"N{t['spent_ngn']:,.0f} of N{t['budget_ngn']:,.0f}"), int(t["facilities_in_scope"])
    if name == "list_facilities":
        return f"{res['returned']} of {res['count']} facilities in {res['state']}", int(res["returned"])
    if name == "get_facility":
        return f"{res.get('name')} ({res.get('tier')}), {len(res.get('nerc_rows', []))} NERC rows", 1
    if name == "get_nerc_rows":
        return f"{res['returned']} of {res['count']} NERC rows", int(res["returned"])
    if name == "band_history":
        return f"{len(res['feeders'])} feeders matched", len(res["feeders"])
    if name in ("what_if", "size_system"):
        return f"engine run for {res.get('unique_id')}", 1
    if name == "refuse":
        return f"refused: {res.get('reason')}", 0
    return name, 0


def _citation_events(log: EV.EventLog, session: Session, cites: list[str]) -> Iterator[dict]:
    for cid in cites:
        c = session.citations.get(cid)
        if not c:
            continue
        nerc = c.get("nerc") or (c if c.get("type") == "nerc_row" else None)
        yield log.emit("citation", cite=cid, facility_id=c.get("unique_id"),
                       file=(nerc or {}).get("order_file") or c.get("file"), page=(nerc or {}).get("page"),
                       sn=(nerc or {}).get("sn"), row_text=(nerc or {}).get("row_text"), source_type=c.get("type"))


def _check_event(log: EV.EventLog, rep: G.GroundingReport) -> dict:
    return log.emit("check", kind="grounding", numbers_checked=rep.n_total,
                    unmatched=[c.text for c in rep.unmatched] + rep.unknown_tokens,
                    matches=[{"text": c.text, "value": c.value, "matched": c.matched} for c in rep.claims],
                    ok=rep.ok, bad_citations=rep.bad_citations, missing_citation=rep.missing_citation)


def run_events(question: str, client: ChatClient | None, toolbox: Toolbox | None = None,
               budget: Budget | None = None, result: dict | None = None) -> Iterator[dict]:
    """The planner as a generator of events. When `result` is a dict, the final record is stored in it."""
    budget = budget or Budget()
    toolbox = toolbox or Toolbox()
    # the toolbox brings its own prompt, specs, refusal wording and summaries (brief 13: agents.tools13.Toolbox13)
    system_prompt = getattr(toolbox, "system_prompt", SYSTEM_PROMPT)
    refusal_text = getattr(toolbox, "refusal_text", REFUSAL_TEXT)
    summarise = getattr(toolbox, "summary", _summary)
    specs = toolbox.specs() if hasattr(toolbox, "specs") else TOOL_SPECS
    log = EV.EventLog()
    session = Session()
    transcript: list[dict] = [{"role": "system", "content": system_prompt}, {"role": "user", "content": question}]
    tool_contents: list[str] = []
    usage = {"steps": 0, "prompt_tokens": 0, "completion_tokens": 0, "tool_calls": 0}
    status, answer, refusal, report = "budget_exhausted", BUDGET_TEXT, None, None
    kind = getattr(client, "kind", "none")
    model = getattr(client, "model_name", "none")

    yield log.emit("plan", steps=PLAN_STEPS)
    yield log.emit("step_start", id="scope")
    rule = scope_prefilter(question)
    if rule:
        status, refusal = "refused", {"reason": rule, "by": "rule", "explanation": refusal_text[rule]}
        answer = refusal_text[rule] + (" For medical questions, ask a health worker." if rule == "out_of_scope"
                                       else ATTACK_TEXT)
        kind_used = "none"
    else:
        kind_used = kind
        if client is None:
            raise LLMError("no model client")
        yield log.emit("step_start", id="gather")
        retries = budget.retries
        drafting = nudged = False
        while usage["steps"] < budget.max_steps:
            used = usage["prompt_tokens"] + usage["completion_tokens"]
            if used + estimate_tokens(transcript) > budget.max_tokens:
                yield log.emit("error", message="token budget for this session is spent")
                break
            try:
                resp = client.chat(transcript, specs, budget.max_answer_tokens)
            except LLMError as e:
                yield log.emit("error", message=f"model call failed: {e}")
                status, answer = "budget_exhausted", "No answer is shown: the model call failed."
                break
            usage["steps"] += 1
            usage["prompt_tokens"] += int(resp.usage.get("prompt_tokens", 0))
            usage["completion_tokens"] += int(resp.usage.get("completion_tokens", 0))
            model = resp.model or model
            msg = resp.message
            transcript.append(msg)
            calls = msg.get("tool_calls") or []
            if msg.get("_reasoning"):
                yield log.emit("reasoning", text=msg["_reasoning"], source="model")
            if calls:
                if msg.get("content"):
                    yield log.emit("reasoning", text=msg["content"], source="model")
                stop = False
                for tc in calls:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except ValueError:
                        args = None
                    yield log.emit("tool_call", id=tc["id"], name=name, args=args)
                    t_call = log.ms()
                    if args is None:
                        res = {"error": "arguments were not valid JSON"}
                    elif usage["tool_calls"] >= budget.max_tool_calls:
                        res = {"error": "the tool-call budget for this session is spent; answer with what you "
                                        "have or refuse"}
                    else:
                        usage["tool_calls"] += 1
                        res = toolbox.call(name, args, session)
                    content = fit_result(res, budget.max_tool_result_chars)
                    tool_contents.append(content)
                    transcript.append({"role": "tool", "tool_call_id": tc["id"], "content": content})
                    summ, rows = summarise(name, res)
                    yield log.emit("tool_result", id=tc["id"], summary=summ, rows=rows, ms=log.ms() - t_call,
                                   ok="error" not in res)
                    if name == "refuse" and res.get("refused"):
                        expl = str(res.get("explanation") or "")
                        # ground against the other tool results: the refuse result echoes the explanation itself
                        rep = G.check(expl, tool_contents[:-1], session.citations, require_citation=False)
                        reason = res["reason"]
                        status = "refused"
                        refusal = {"reason": reason, "by": "model", "explanation": expl if rep.ok else
                                   refusal_text[reason]}
                        answer = refusal["explanation"]
                        stop = True
                if stop:
                    break
                continue
            # a final draft. One with no tool result behind it (a bare "I can't help", or a refusal typed as text)
            # goes back once: answer from the tools, or call refuse
            if not tool_contents and not nudged:
                nudged = True
                transcript.append({"role": "user", "content": NO_TOOLS_TEXT})
                continue
            draft = G.normalise(msg.get("content") or "")
            if not drafting:
                drafting = True
                yield log.emit("step_start", id="draft")
            yield log.emit("step_start", id="check")
            report = G.check(draft, tool_contents, session.citations)
            yield _check_event(log, report)
            if report.ok:
                status, answer = "answered", draft
                break
            if retries > 0:
                retries -= 1
                transcript.append({"role": "user", "content": report.retry_message()})
                yield log.emit("step_start", id="draft")
                continue
            status, answer = "blocked", BLOCKED_TEXT
            yield log.emit("error", message="answer blocked: numbers not traced to tool results")
            break
        else:
            yield log.emit("error", message="step budget for this session is spent")

    plan = session.last_plan if status == "answered" else None
    used_cites = report.citations_used if (report and status == "answered") else []
    yield log.emit("step_start", id="answer")
    yield from _citation_events(log, session, used_cites)
    cite_ids = list(dict.fromkeys(used_cites + ([plan["cite"]] if plan else [])))
    output = {
        "question": question,
        "answer_markdown": answer,
        "funded": plan["funded"] if plan else [],
        "not_reached": plan["not_reached"] if plan else [],
        "not_reached_groups": plan["not_reached_groups"] if plan else {},
        "totals": plan["totals"] if plan else {},
        "plan_args": plan["args"] if plan else None,
        "citations": [session.citations[c] for c in cite_ids if c in session.citations],
        "tool_calls": session.calls,
        "model": model if kind_used != "none" else "none (rule pre-filter)",
        "client_kind": kind_used,
        "grounded": True,
        "status": status,
        "refusal": refusal,
        "grounding": report.to_dict() if report else None,
        "usage": {**usage, "total_tokens": usage["prompt_tokens"] + usage["completion_tokens"]},
        "budget": asdict(budget),
        "data_version": toolbox.data.version if status == "answered" or session.calls else None,
        "label": ("scripted test model: rule-based, no language model was called" if kind_used == "scripted"
                  else "recorded session (replay)" if kind_used == "replay" else
                  "live model" if kind_used == "live" else "rule pre-filter, no model was called"),
    }
    yield log.emit("answer", markdown=answer, funded=output["funded"], not_reached=output["not_reached"],
                   totals=output["totals"], status=status, citations=output["citations"])
    yield log.emit("done", model=output["model"], tokens=output["usage"]["total_tokens"],
                   cost_usd=EV.cost_usd(usage["prompt_tokens"], usage["completion_tokens"], kind_used),
                   recorded=False, duration_ms=log.ms(), status=status)
    if result is not None:
        result.update({"output": output, "transcript": transcript, "events": log.events})


def run(question: str, client: ChatClient | None, toolbox: Toolbox | None = None,
        budget: Budget | None = None) -> dict:
    """Run to completion: {"output", "transcript", "events"}."""
    rec: dict = {}
    for _ in run_events(question, client, toolbox, budget, rec):
        pass
    return rec
