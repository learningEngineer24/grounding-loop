"""
Score Phase 4b no-layer traces against the locked golden answers.

Reuses phase4/score.py's behavior/numeric/disclosure logic. Metric selection
is not applicable (no governed metrics in this run) — it reports n/a.
The interesting comparison is in the deltas vs phase4/scores_baseline.json:
governed vs raw-SQL, same questions.

Usage: .venv/bin/python score_4b.py [--traces traces_nolayer.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "phase4"))
import score as governed_score  # noqa: E402 — reuse behavior/numeric/disclosure


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", default="traces_nolayer.jsonl")
    args = ap.parse_args()

    questions = {q["id"]: q for q in yaml.safe_load(
        (BASE.parent / "phase3" / "golden_questions.yml").read_text())["questions"]}
    answers = yaml.safe_load(
        (BASE.parent / "phase3" / "golden_answers.yml").read_text())["answers"]
    traces = [json.loads(l) for l in (BASE / args.traces).read_text().splitlines()]

    scored = []
    for t in traces:
        s = governed_score.score_one(t, questions[t["id"]], answers[t["id"]])
        s["metric_ok"] = None  # n/a — no governed metrics in the no-layer run
        scored.append(s)

    def pct(xs):
        xs = [x for x in xs if x is not None]
        return f"{sum(xs)}/{len(xs)} = {100 * sum(xs) / len(xs):.0f}%" if xs else "n/a"

    print(f"## Phase 4b results (no semantic layer) — {len(scored)} questions\n")
    print(f"behavior accuracy : {pct([s['behavior_ok'] for s in scored])}")
    ans = [s for s in scored if s["numeric_ok"] is not None]
    print(f"numeric accuracy  : {pct([s['numeric_ok'] for s in ans])} (42 answerable)")
    traps = [s for s in scored if s["category"] == "trap"]
    print(f"disclosure rate   : {pct([s['disclosure_ok'] for s in traps])} (12 traps)")
    for cat in ["straightforward", "trap", "ambiguous"]:
        c = [s for s in scored if s["category"] == cat]
        print(f"  {cat:15s} behavior {pct([s['behavior_ok'] for s in c])}", end="")
        ca = [s for s in c if s["numeric_ok"] is not None]
        if ca:
            print(f"  numeric {pct([s['numeric_ok'] for s in ca])}", end="")
        print()

    print("\n## Failures")
    for s in scored:
        problems = [k for k in ("behavior_ok", "numeric_ok", "disclosure_ok")
                    if s[k] is False]
        if problems:
            t = next(x for x in traces if x["id"] == s["id"])
            term = t.get("terminal") or {}
            txt = term.get("answer_text") or term.get("question") or term.get("reason") or ""
            print(f"- {s['id']} [{s['category']}] failed: {', '.join(problems)} "
                  f"(terminal={s['terminal']})")
            print(f"    -> {txt[:160]}")

    (BASE / "scores_4b.json").write_text(json.dumps(scored, indent=2))
    print("\nwrote phase4b/scores_4b.json")


if __name__ == "__main__":
    sys.exit(main())
