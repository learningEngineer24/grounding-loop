"""Phase 5: score drift runs — standard four dimensions plus revision_ok.

Reuses phase4/score.py's score_one for behavior/numeric/metric/disclosure
(the golden answers equal snapshot-B values, so no numeric rescoring is
needed). Adds revision_ok for the questions drift_report.json flags as
changed: did the agent's answer mention that the figure was restated?

Revision keywords are deliberately narrow (restat*, revis*, late-arriving)
to avoid false positives from ordinary answer text.

Usage: python3 phase5/score_drift.py --traces <traces.jsonl>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "phase4"))

import score as governed_score  # noqa: E402

BASE = Path(__file__).resolve().parent

REVISION_KEYWORDS = ["restat", "revis", "late-arriving", "late arriving"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", required=True)
    args = ap.parse_args()

    questions = {q["id"]: q for q in yaml.safe_load(
        (ROOT / "phase3" / "golden_questions.yml").read_text())["questions"]}
    answers = yaml.safe_load(
        (ROOT / "phase3" / "golden_answers.yml").read_text())["answers"]
    traces = [json.loads(l) for l in
              Path(args.traces).read_text().splitlines()]
    changed = {c["id"] for c in json.loads(
        (BASE / "drift_report.json").read_text())["changed"]}

    scored = [governed_score.score_one(t, questions[t["id"]],
                                       answers[t["id"]]) for t in traces]
    trace_by_id = {t["id"]: t for t in traces}

    def pct(xs):
        xs = [x for x in xs if x is not None]
        return (f"{sum(xs)}/{len(xs)} = {100 * sum(xs) / len(xs):.0f}%"
                if xs else "n/a")

    print(f"## Phase 5 drift results — {len(scored)} questions\n")
    print(f"behavior accuracy : {pct([s['behavior_ok'] for s in scored])}")
    ans = [s for s in scored if s["numeric_ok"] is not None]
    print(f"numeric accuracy  : {pct([s['numeric_ok'] for s in ans])} "
          f"({len(ans)} answerable)")
    print(f"metric selection  : {pct([s['metric_ok'] for s in ans])}")
    disc = [s for s in scored if s["disclosure_ok"] is not None]
    print(f"disclosure rate   : {pct([s['disclosure_ok'] for s in disc])} "
          f"({len(disc)} disclosure-expected)")

    rev_ok = []
    rev_missed = []
    for s in scored:
        if s["id"] not in changed or s["expected_behavior"] not in (
                "answer", "answer_with_disclosure"):
            continue
        text = (trace_by_id[s["id"]].get("terminal") or {}).get(
            "answer_text", "").lower()
        ok = any(k in text for k in REVISION_KEYWORDS)
        rev_ok.append(ok)
        if not ok:
            rev_missed.append(s["id"])
    print(f"revision disclosure: {pct(rev_ok)} ({len(rev_ok)} changed answers)")
    if rev_missed:
        print(f"  missed: {', '.join(sorted(rev_missed))}")

    for cat in ["straightforward", "trap", "ambiguous"]:
        c = [s for s in scored if s["category"] == cat]
        ca = [s for s in c if s["numeric_ok"] is not None]
        line = f"  {cat:15s} behavior {pct([s['behavior_ok'] for s in c])}"
        if ca:
            line += f"  numeric {pct([s['numeric_ok'] for s in ca])}"
        print(line)


if __name__ == "__main__":
    sys.exit(main())
