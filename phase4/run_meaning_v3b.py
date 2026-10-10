"""Turn 4: focused agent eval against semantics v3 (meaning change).

Runs the 8 meaning-changed refund questions + 2 controls with the v3
catalog. Set GROUNDING_SEMANTICS to phase2/semantics_v3.yml.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import yaml

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import agent_anthropic  # noqa: E402

QIDS = ["Q007", "Q043", "Q044", "Q053", "Q121", "Q153", "Q164", "Q240",
        "Q006", "Q156"]
OUT = BASE.parent / "phase5" / "traces_meaning_v3b_10.jsonl"
MODEL = "claude-haiku-4-5-20251001"

def main():
    qs = {q["id"]: q for q in yaml.safe_load(
        (BASE.parent / "phase3" / "golden_questions.yml").read_text())["questions"]}
    with open(OUT, "w") as f:
        for i, qid in enumerate(QIDS, 1):
            q = qs[qid]
            print(f"[{i}/{len(QIDS)}] {qid}: {q['question'][:60]}...", flush=True)
            try:
                trace = agent_anthropic.run_question(MODEL, qid, q["question"])
            except Exception as e:  # noqa: BLE001
                trace = {"id": qid, "question": q["question"], "tool_calls": [],
                         "terminal": {"action": "error", "detail": str(e)[:300]}, "usage": {}}
            trace["category"] = q["category"]
            trace["backend"] = "anthropic_conn"
            trace["model"] = MODEL
            f.write(json.dumps(trace, default=str) + "\n")
            f.flush()
            import time; time.sleep(1)
    print(f"wrote {OUT}", flush=True)

if __name__ == "__main__":
    sys.exit(main())
