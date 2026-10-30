"""T8 and T9 checks (PREREG) on planner session records, against the fixed questions in docs/AGENT_QUESTIONS.md.

    python -m agents.evaluate RUN_DIR      # RUN_DIR holds one <id>.json record per question (planner.run output)

Only a live-model run is the T8/T9 result. A scripted-model run exercises this code and is labelled as such.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from . import engine_adapter as EA
from . import grounding as G
from .tools import Toolbox, ToolError

QUESTIONS_MD = Path(__file__).resolve().parents[1] / "docs" / "AGENT_QUESTIONS.md"


def load_questions(path: Path = QUESTIONS_MD) -> list[dict]:
    text = path.read_text()
    block = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    if not block:
        raise ValueError("AGENT_QUESTIONS.md has no json block")
    specs = json.loads(block.group(1))
    table = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*(Q\d\d)\s*\|\s*(.+?)\s*\|\s*(plan|refuse[^|]*?)\s*\|", line)
        if m:
            table[m.group(1)] = (m.group(2), m.group(3).strip())
    if set(table) != {s["id"] for s in specs}:
        raise ValueError("the question table and the json block list different ids")
    for s in specs:
        q, kind = table[s["id"]]
        if not kind.startswith(s["kind"]):
            raise ValueError(f"{s['id']}: table kind '{kind}' disagrees with json kind '{s['kind']}'")
        s["question"] = q
    return specs


def tool_contents(transcript: list[dict], exclude: tuple[str, ...] = ("refuse",)) -> list[str]:
    """Tool results the model saw, without the refuse tool's echo (an answer must not ground itself)."""
    names = {tc["id"]: tc["function"]["name"] for m in transcript for tc in (m.get("tool_calls") or [])}
    return [m.get("content") or "" for m in transcript
            if m.get("role") == "tool" and names.get(m.get("tool_call_id")) not in exclude]


def check_t8(record: dict) -> dict:
    """Re-check the final answer's numbers against the session's recorded tool results."""
    out = record["output"]
    cites = {c["id"] for c in out.get("citations", [])}
    # every citation id the session's tools returned is a valid id; re-derive them from the tool results
    for c in tool_contents(record["transcript"]):
        cites |= set(re.findall(r'"cite": "(S\d+)"', c))
    rep = G.check(out["answer_markdown"], tool_contents(record["transcript"]), cites,
                  require_citation=out["status"] == "answered")
    return {"n_total": rep.n_total, "n_traced": rep.n_traced, "untraced": [c.text for c in rep.unmatched]
            + rep.unknown_tokens, "ok": rep.ok}


def _rank_calls(record: dict) -> list[dict]:
    calls = []
    for m in record["transcript"]:
        for tc in m.get("tool_calls") or []:
            if tc["function"]["name"] == "rank_budget":
                try:
                    calls.append(json.loads(tc["function"]["arguments"]))
                except ValueError:
                    pass
    return calls


def check_t9(spec: dict, record: dict, toolbox: Toolbox) -> dict:
    out = record["output"]
    calls = _rank_calls(record)
    if spec["kind"] == "refuse":
        ok = (out["status"] == "refused" and (out.get("refusal") or {}).get("reason") == spec["reason"]
              and not calls)
        return {"ok": ok, "why": None if ok else f"status {out['status']}, refusal {out.get('refusal')}, "
                                                 f"rank calls {len(calls)}"}
    if out["status"] != "answered":
        return {"ok": False, "why": f"status {out['status']}"}
    expected_ngn = EA.usd_to_ngn(spec["budget"]) if spec["currency"] == "USD" else float(spec["budget"])
    data = toolbox.data
    try:
        state = data.resolve_state(spec["state"])
        lga = data.resolve_lga(state, spec["lga"]) if spec.get("lga") else None
    except ToolError as e:
        return {"ok": False, "why": f"spec does not resolve: {e}"}

    def matches(a: dict) -> bool:
        try:
            st = data.resolve_state(a.get("state", ""))
            lg = data.resolve_lga(st, a["lga"]) if a.get("lga") else None
        except ToolError:
            return False
        cur = (a.get("currency") or "NGN").upper()
        b = EA.usd_to_ngn(a.get("budget", 0)) if cur == "USD" else float(a.get("budget", 0))
        return (st == state and lg == lga and a.get("priority") == spec["metric"]
                and (a.get("facility_level") or None) == spec.get("level") and abs(b - expected_ngn) <= 1.0)

    if not any(matches(a) for a in calls):
        return {"ok": False, "why": f"no rank_budget call with the expected arguments; calls: {calls}"}
    ranked, _ = EA.rank(toolbox.plan_frame(state, lga, spec.get("level")), expected_ngn, spec["metric"])
    want = set(ranked[ranked.funded].unique_id)
    got = {f["unique_id"] for f in out["funded"]}
    t = out["totals"]
    problems = []
    if got != want:
        problems.append(f"funded set differs from plan.rank ({len(got)} vs {len(want)})")
    if t.get("spent_ngn", float("inf")) > expected_ngn + 1e-6:
        problems.append("spent more than the budget")
    if t.get("metric") != spec["metric"]:
        problems.append(f"metric {t.get('metric')} is not the stated priority {spec['metric']}")
    return {"ok": not problems, "why": "; ".join(problems) or None}


def evaluate_run(records: dict[str, dict], toolbox: Toolbox | None = None,
                 questions: list[dict] | None = None) -> dict:
    toolbox = toolbox or Toolbox()
    questions = questions or load_questions()
    rows, n_total, n_traced = [], 0, 0
    for spec in questions:
        rec = records.get(spec["id"])
        if rec is None:
            rows.append({"id": spec["id"], "t8": None, "t9": {"ok": False, "why": "no record"}})
            continue
        t8 = check_t8(rec)
        t9 = check_t9(spec, rec, toolbox)
        n_total += t8["n_total"]
        n_traced += t8["n_traced"]
        rows.append({"id": spec["id"], "status": rec["output"]["status"], "t8": t8, "t9": t9,
                     "model": rec["output"]["model"], "client_kind": rec["output"]["client_kind"]})
    t9_pass = sum(r["t9"]["ok"] for r in rows)
    kinds = {r.get("client_kind") for r in rows}
    return {"t8": {"numbers": n_total, "traced": n_traced, "share": (n_traced / n_total) if n_total else None,
                   "pass": n_total == n_traced},
            "t9": {"passed": t9_pass, "of": len(rows), "target": 18, "pass": t9_pass >= 18},
            "counts_as_prereg_result": kinds == {"live"} or kinds == {"live", "none"},
            "rows": rows}


def main(argv=None) -> int:
    run_dir = Path((argv or sys.argv[1:])[0])
    recs = {p.stem: json.loads(p.read_text()) for p in run_dir.glob("Q*.json")}
    res = evaluate_run(recs)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
    for r in res["rows"]:
        print(r["id"], r.get("status"), "T8", (r["t8"] or {}).get("ok"), "T9", r["t9"]["ok"], r["t9"].get("why") or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
