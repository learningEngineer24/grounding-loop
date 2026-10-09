"""Phase 5: build restatement metadata for the drift run.

Reads phase5/drift_report.json (which questions changed between snapshots),
maps each changed question to its governed metric(s) via the golden spec,
and writes phase5/restatements.json: metric -> {period, restated_on, reason}.

The governed agent sees this through describe_metric (data_as_of +
restatement keys) during the snapshot-B run. The no-layer agent gets no
equivalent metadata — that asymmetry is part of what Phase 5 measures.

Usage: python3 phase5/build_restatements.py
Writes: phase5/restatements.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DRIFT = ROOT / "phase5" / "drift_report.json"
QUESTIONS = ROOT / "phase3" / "golden_questions.yml"
OUT = ROOT / "phase5" / "restatements.json"


def main() -> None:
    report = json.loads(DRIFT.read_text())
    spec = {q["id"]: q for q in
            yaml.safe_load(QUESTIONS.read_text())["questions"]}
    metrics: dict[str, set[str]] = {}
    for c in report["changed"]:
        q = spec[c["id"]]
        ms = q.get("metric") or q.get("metrics") or []
        if isinstance(ms, str):
            ms = [ms]
        for m in ms:
            metrics.setdefault(m, set()).add(c["id"])
    restatements = {
        m: {
            "period": "2026-06",
            "restated_on": "2026-07-15",
            "reason": "late-arriving payments landed",
            "changed_questions": sorted(qids),
        }
        for m, qids in sorted(metrics.items())
    }
    OUT.write_text(json.dumps(restatements, indent=2))
    print(f"wrote {OUT}: {len(restatements)} metrics restated")
    for m, r in restatements.items():
        print(f"  {m}: {r['changed_questions']}")


if __name__ == "__main__":
    sys.exit(main())
