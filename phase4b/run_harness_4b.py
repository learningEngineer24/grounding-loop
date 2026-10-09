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

DEFAULT_MODEL = "gemini-3.8-flash"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="traces_nolayer.jsonl")
    args = ap.parse_args()

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
                trace = agent_sql_gemini.run_question(
                    args.model, q["id"], q["question"])
            except Exception as e:  # noqa: BLE001 — one bad question must not kill the run
                trace = {"id": q["id"], "question": q["question"],
                         "tool_calls": [], "terminal": {"action": "error",
                         "detail": str(e)[:300]}, "usage": {}}
            trace["category"] = q["category"]
            trace["backend"] = "sql_gemini"
            trace["model"] = args.model
            f.write(json.dumps(trace, default=str) + "\n")
            f.flush()
            time.sleep(1)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    sys.exit(main())
