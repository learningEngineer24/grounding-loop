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
import agent_sql_openai  # noqa: E402
import agent_sql_openrouter  # noqa: E402
# agent_sql_atem is imported lazily in main(): it raises at import time when
# OLLAMA_BASE_URL is unset, and must not break the other backends.
from costs import attach_cost  # noqa: E402

DEFAULT_MODELS = {"sql_gemini": "gemini-3.8-flash",
                  "sql_anthropic": "claude-sonnet-5-5",
                  "sql_openai": "gpt-6.1-sol",
                  "sql_openrouter": "meta/muse-ember",
                  "sql_atem": ("hf.co/meta-models/Muse-Glimmer-30B-GGUF:"
                               "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M")}

RUNNERS = {"sql_gemini": agent_sql_gemini.run_question,
           "sql_anthropic": agent_sql_anthropic.run_question,
           "sql_openai": agent_sql_openai.run_question,
           "sql_openrouter": agent_sql_openrouter.run_question}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=list(DEFAULT_MODELS),
                    default="sql_gemini")
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default=None,
                    help="comma-separated question ids to run (overrides --limit)")
    ap.add_argument("--questions", default=None,
                    help="question file (default: phase3/golden_questions.yml)")
    ap.add_argument("--out", default="traces_nolayer.jsonl")
    args = ap.parse_args()
    model = args.model or DEFAULT_MODELS[args.backend]
    if args.backend == "sql_atem":
        import agent_sql_atem  # noqa: E402  (needs OLLAMA_BASE_URL at import)
        run_one = agent_sql_atem.run_question
    else:
        run_one = RUNNERS[args.backend]

    qfile = args.questions or str(BASE.parent / "phase3" / "golden_questions.yml")
    questions = yaml.safe_load(Path(qfile).read_text())["questions"]
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    elif args.limit:
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
            attach_cost(trace, model)
            f.write(json.dumps(trace, default=str) + "\n")
            f.flush()
            time.sleep(1)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    sys.exit(main())
