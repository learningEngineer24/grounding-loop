"""
Run the agent over all 50 golden questions; write one JSONL trace per run.

Usage:
  .venv/bin/python run_harness.py [--backend anthropic|gemini|baseline] [--model ...] [--limit N] [--out traces.jsonl]

The agent only ever sees the question text — never the golden answers.
The baseline backend is deterministic and needs no API key.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

import agent

BASE = Path(__file__).resolve().parent

DEFAULT_MODELS = {"anthropic": "claude-haiku-4-5-20251001",
                "anthropic_conn": "claude-haiku-4-5-20251001",
                "gemini": "gemini-3.8-flash",
                "baseline": "deterministic-v1"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["anthropic", "anthropic_conn",
                                            "gemini", "baseline"],
                    default="anthropic")
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="traces.jsonl")
    args = ap.parse_args()
    model = args.model or DEFAULT_MODELS[args.backend]

    questions = yaml.safe_load(
        (BASE.parent / "phase3" / "golden_questions.yml").read_text())["questions"]
    if args.limit:
        questions = questions[:args.limit]

    if args.backend == "baseline":
        import baseline_agent

        def run_one(_client, model, qid, question):
            return baseline_agent.run_question(qid, question)

        client = None
    elif args.backend == "gemini":
        import agent_gemini

        def run_one(_client, model, qid, question):
            return agent_gemini.run_question(model, qid, question)

        client = None
    elif args.backend == "anthropic_conn":
        import agent_anthropic

        def run_one(_client, model, qid, question):
            return agent_anthropic.run_question(model, qid, question)

        client = None
    else:
        client = agent.make_client()
        run_one = agent.run_question

    out_path = BASE / args.out
    with open(out_path, "w") as f:
        for i, q in enumerate(questions, 1):
            print(f"[{i}/{len(questions)}] {q['id']}: {q['question'][:60]}...",
                  flush=True)
            try:
                trace = run_one(client, model, q["id"], q["question"])
            except Exception as e:  # noqa: BLE001 — one bad question must not kill the run
                trace = {"id": q["id"], "question": q["question"],
                         "tool_calls": [], "terminal": {"action": "error",
                         "detail": str(e)[:300]}, "usage": {}}
            trace["category"] = q["category"]
            trace["backend"] = args.backend
            trace["model"] = model
            f.write(json.dumps(trace, default=str) + "\n")
            f.flush()
            time.sleep(1)  # be a polite API citizen
    print(f"wrote {out_path}")


if __name__ == "__main__":
    sys.exit(main())
