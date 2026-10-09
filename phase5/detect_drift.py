"""Phase 5: drift detection — re-run golden answers on both snapshots and diff.

Reuses phase3/compute_answers.answer_question (same v1 compiler, same
question specs) against each snapshot DB. Snapshot B must exactly
reproduce the locked golden answers — asserted below. Any question whose
answer differs between A and B went stale when the late batch landed;
those are the questions the Phase 5 agent runs test for revision
disclosure.

Usage: python3 phase5/detect_drift.py
Writes: phase5/drift_report.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "phase2"))
sys.path.insert(0, str(ROOT / "phase3"))

import compute_answers as ca  # noqa: E402
from semantic_compiler import SemanticCatalog  # noqa: E402

SNAP_A = ROOT / "phase5" / "warehouse_20260630.duckdb"
SNAP_B = ROOT / "phase5" / "warehouse_20260715.duckdb"
QUESTIONS = ROOT / "phase3" / "golden_questions.yml"
GOLDEN = ROOT / "phase3" / "golden_answers.yml"
OUT = ROOT / "phase5" / "drift_report.json"


def answers_for(db_path: Path) -> dict:
    ca.DB = db_path  # compute_answers reads DB as a module constant
    spec = yaml.safe_load(QUESTIONS.read_text())
    cat = SemanticCatalog(ROOT / "phase2" / "semantics_v1.yml")
    out = {}
    for q in spec["questions"]:
        out[q["id"]] = ca.answer_question(cat, q)
    return out


def norm(v):
    if isinstance(v, dict):
        return {k: round(float(x), 2) for k, x in v.items()}
    if v is None:
        return None
    return round(float(v), 2)


def main() -> None:
    ans_a = answers_for(SNAP_A)
    ans_b = answers_for(SNAP_B)

    # snapshot B == full warehouse: must reproduce the locked golden answers
    golden = yaml.safe_load(GOLDEN.read_text())["answers"]
    mismatches = [
        qid for qid, v in ans_b.items()
        if norm(v) != norm(golden[qid]["expected"])
    ]
    assert not mismatches, f"snapshot B diverged from golden: {mismatches}"

    changed = []
    for qid in ans_a:
        va, vb = norm(ans_a[qid]), norm(ans_b[qid])
        if va != vb:
            if isinstance(va, dict):
                delta = {k: round(vb[k] - va.get(k, 0), 2) for k in vb}
            else:
                delta = round(vb - va, 2)
            changed.append({"id": qid, "as_of_jun30": va,
                            "as_of_jul15": vb, "delta": delta})

    report = {
        "snapshot_a": "2026-06-30 close (late batch not yet landed)",
        "snapshot_b": "2026-07-15 (late batch landed)",
        "questions_compared": len(ans_a),
        "changed_count": len(changed),
        "changed": changed,
        "golden_reproduced_on_b": True,
    }
    OUT.write_text(json.dumps(report, indent=2))
    print(f"compared {len(ans_a)} questions: {len(changed)} changed "
          f"between snapshots")
    for c in changed:
        print(f"  {c['id']}: {c['as_of_jun30']} -> {c['as_of_jul15']} "
              f"(delta {c['delta']})")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
