"""Run the brief 13 planner questions (docs/AGENT_QUESTIONS.md, C01 to C16) on the live model: the T8/T9 run.

    python -m agents.live13 RUN_DIR [C01 C03 ...]     # no ids: all 16
    python -m agents.evaluate RUN_DIR

The model comes only from the WARDLIGHT_LLM_* variables (agents/llm.py) and the prices from
WARDLIGHT_LLM_USD_PER_M_INPUT / _OUTPUT, so cost_usd is computed, never guessed. One <id>.json record per question.
An existing record is kept, so a rerun after a network drop only spends on what is missing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import planner
from .evaluate import load_questions13
from .llm import OpenAICompatClient
from .tools13 import Toolbox13


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    run_dir = Path(args.pop(0))
    run_dir.mkdir(parents=True, exist_ok=True)
    qs = [q for q in load_questions13() if not args or q["id"] in args]
    client = OpenAICompatClient.from_env()
    tb = Toolbox13()
    total = 0.0
    for q in qs:
        p = run_dir / f"{q['id']}.json"
        if p.exists():
            print(q["id"], "kept (already recorded)")
            continue
        rec = planner.run(q["question"], client, tb)
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        done = next(e for e in reversed(rec["events"]) if e["type"] == "done")
        total += done.get("cost_usd") or 0.0
        print(q["id"], rec["output"]["status"], "tokens", done["tokens"], "cost_usd", done.get("cost_usd"),
              "ms", done["duration_ms"], flush=True)
    print("run cost_usd", round(total, 6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
