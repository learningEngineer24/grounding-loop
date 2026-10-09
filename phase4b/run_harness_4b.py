"""
Run the Phase 4b no-layer ablation agent over all 50 golden questions.

Same questions, same trace schema as the governed harness — the only
difference is the agent writes its own SQL instead of calling governed
metrics. Compare with phase4/scores.json to measure the semantic layer's
incremental value.

Usage:
  .venv/bin/python run_harness_4b.py [--model ...] [--limit N] [--out traces.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "phase4"))  # reuse the phase4 venv deps

import agent_sql_gemini  # noqa: E402
import agent_sql_anthropic  # noqa: E402

DEFAULT_MODELS = {"sql_gemini": "gemini-3.8-flash",
                  "sql_anthropic": "claude-haiku-4-5-20251001"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["sql_gemini", "sql_anthropic"],
                    default="sql_gemini")
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="traces_nolayer.jsonl")
    args = ap.parse_args()
    model = args.model or DEFAULT_MODELS[args.backend]
    run_one = (agent_sql_anthropic.run_question
               if args.backend == "sql_anthropic"
               else agent_sql_gemini.run_question)

    questions = yaml.safe_load(
        (BASE.parent / "phase3" / "golden_questions.yml").read_text())["questions"]
    if args.limit:
        questions = questions[:args.limit]

    out_path = BASE / args.out
    with open(out_path, "w") as f:
        for i, q in enumerate(questions, 1):
            print(f"[{i}/{len(questions)}] {q['id']}: {q['question'][:60]}...",
                  flush=True)
            try:
                trace = run_one(model, q["id"], q["question"])
            except Exception as e:  # noqa: BLE001 — one bad question must not kill the run
                trace = {"id": q["id"], "question": q["question"],
                         "tool_calls": [], "terminal": {"action": "error",
                         "detail": str(e)[:300]}, "usage": {}}
            trace["category"] = q["category"]
            trace["backend"] = args.backend
            trace["model"] = model
            f.write(json.dumps(trace, default=str) + "\n")
            f.flush()
            time.sleep(1)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    sys.exit(main())
