"""
Run the agent over all 50 golden questions; write one JSONL trace per run.

Usage:
  .venv/bin/python run_harness.py [--backend anthropic|gemini|openai|ember|openrouter|ollama|atem|baseline] [--model ...] [--limit N] [--out traces.jsonl]
  [--gate off|repair|routing|both] [--escalate-backend anthropic] [--escalate-model claude-sonnet-5-5]

The agent only ever sees the question text — never the golden answers.
The baseline backend is deterministic and needs no API key.

With --gate, each question runs through eval_gate (Phase 2): grade the
attempt with the deterministic grader, one repair retry on failure, and
(for cheap legs) escalation to the frontier backend with the loop.
The trace's top level is the final attempt; the "gate" object carries the
attempt history and the full cost accounting.
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
                "openai": "gpt-6.1-sol",
                "ember": "muse-ember-1.0",
                "openrouter": "meta/muse-ember",
                "ollama": "hf.co/meta-models/Muse-Glimmer-30B-GGUF:Muse-Glimmer-30B-KQuant-17GB-Q4_K_M",
                "atem": "hf.co/meta-models/Muse-Glimmer-30B-GGUF:Muse-Glimmer-30B-KQuant-17GB-Q4_K_M",
                "baseline": "deterministic-v1"}


def get_runner(backend):
    """Return (run_one, client) for a backend. run_one(client, model, qid,
    question) -> trace, mirroring agent.run_question's schema."""
    if backend == "baseline":
        import baseline_agent

        def run_one(_client, model, qid, question):
            return baseline_agent.run_question(qid, question)

        return run_one, None
    if backend == "gemini":
        import agent_gemini

        def run_one(_client, model, qid, question):
            return agent_gemini.run_question(model, qid, question)

        return run_one, None
    if backend == "openai":
        import agent_openai

        def run_one(_client, model, qid, question):
            return agent_openai.run_question(model, qid, question)

        return run_one, None
    if backend == "ember":
        import agent_ember

        def run_one(_client, model, qid, question):
            return agent_ember.run_question(model, qid, question)

        return run_one, None
    if backend == "openrouter":
        import agent_openrouter

        def run_one(_client, model, qid, question):
            return agent_openrouter.run_question(model, qid, question)

        return run_one, None
    if backend == "ollama":
        import agent_ollama

        def run_one(_client, model, qid, question):
            return agent_ollama.run_question(model, qid, question)

        return run_one, None
    if backend == "atem":
        import agent_atem

        def run_one(_client, model, qid, question):
            return agent_atem.run_question(model, qid, question)

        return run_one, None
    if backend == "anthropic_conn":
        import agent_anthropic

        def run_one(_client, model, qid, question):
            return agent_anthropic.run_question(model, qid, question)

        return run_one, None
    client = agent.make_client()
    return agent.run_question, client


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["anthropic", "anthropic_conn",
                                            "gemini", "openai", "ember",
                                            "openrouter", "ollama", "atem",
                                            "baseline"],
                    default="anthropic")
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default=None,
                    help="comma-separated question ids to run (overrides --limit)")
    ap.add_argument("--out", default="traces.jsonl")
    ap.add_argument("--gate", choices=["off", "repair", "routing", "both"],
                    default="off")
    ap.add_argument("--escalate-backend", default="anthropic_conn")
    ap.add_argument("--escalate-model", default="claude-sonnet-5-5")
    args = ap.parse_args()
    model = args.model or DEFAULT_MODELS[args.backend]

    questions = yaml.safe_load(
        (BASE.parent / "phase3" / "golden_questions.yml").read_text())["questions"]
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    elif args.limit:
        questions = questions[:args.limit]

    run_one, client = get_runner(args.backend)
    escalate_fn = None
    if args.gate != "off":
        import eval_gate
        esc_run_one, esc_client = get_runner(args.escalate_backend)
        esc_model = args.escalate_model or DEFAULT_MODELS[args.escalate_backend]

        def escalate_fn(qid, question):
            return esc_run_one(esc_client, esc_model, qid, question)

        primary = run_one
        primary_client = client
        primary_model = model

        def run_one(_client, model, qid, question):
            return eval_gate.run_gated(
                lambda q, qq: primary(primary_client, primary_model, q, qq),
                args.backend, primary_model,
                escalate_fn, args.escalate_backend, esc_model,
                qid, question, mode=args.gate)

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
