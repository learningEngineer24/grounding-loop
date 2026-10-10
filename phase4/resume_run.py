"""Resume an interrupted harness run: skip questions already traced, append the rest."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import yaml

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import agent_anthropic  # noqa: E402

OUT = BASE.parent / "phase5" / "traces_drift_v3b_167.jsonl"
MODEL = "claude-haiku-4-5-20251001"

def main():
    done = set()
    if OUT.exists():
        for l in OUT.read_text().splitlines():
            l = l.strip()
            if l:
                done.add(json.loads(l)["id"])
    questions = yaml.safe_load((BASE.parent / "phase3" / "golden_questions.yml").read_text())["questions"]
    todo = [q for q in questions if q["id"] not in done]
    print(f"resuming: {len(done)} done, {len(todo)} remaining", flush=True)
    with open(OUT, "a") as f:
        for i, q in enumerate(todo, 1):
            print(f"[{len(done)+i}/{len(questions)}] {q['id']}: {q['question'][:60]}...", flush=True)
            try:
                trace = agent_anthropic.run_question(MODEL, q["id"], q["question"])
            except Exception as e:  # noqa: BLE001
                trace = {"id": q["id"], "question": q["question"], "tool_calls": [],
                         "terminal": {"action": "error", "detail": str(e)[:300]}, "usage": {}}
            trace["category"] = q["category"]
            trace["backend"] = "anthropic_conn"
            trace["model"] = MODEL
            f.write(json.dumps(trace, default=str) + "\n")
            f.flush()
            time.sleep(1)
    print(f"done: {OUT}", flush=True)

if __name__ == "__main__":
    sys.exit(main())
