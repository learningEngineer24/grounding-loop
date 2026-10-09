"""Phase 5 canary: the golden set as a scheduled drift monitor.

Re-runs every computed golden answer against a target warehouse and diffs
against the locked golden answers. Any divergence means the data moved
underneath a stakeholder-facing answer — a semantically meaningful alert,
not just "row count dropped."

This is the productionized form of detect_drift.py: instead of comparing
two snapshots, it compares live data against the locked baseline.

Usage:
  python3 phase5/canary.py [--db warehouse.duckdb] [--out report.json]

Exit code 0 = CLEAN (no drift), 1 = STALE (answers moved).
Demo:
  CLEAN: python3 phase5/canary.py --db warehouse.duckdb
  STALE: python3 phase5/canary.py --db phase5/warehouse_20260630.duckdb
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "phase2"))
sys.path.insert(0, str(ROOT / "phase3"))

import compute_answers as ca  # noqa: E402
from semantic_compiler import SemanticCatalog  # noqa: E402

QUESTIONS = ROOT / "phase3" / "golden_questions.yml"
GOLDEN = ROOT / "phase3" / "golden_answers.yml"


def norm(v):
    if isinstance(v, dict):
        return {k: round(float(x), 2) for k, x in v.items()}
    if v is None:
        return None
    return round(float(v), 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "warehouse.duckdb"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ca.DB = Path(args.db)
    spec = yaml.safe_load(QUESTIONS.read_text())
    cat = SemanticCatalog(ROOT / "phase2" / "semantics_v1.yml")
    golden = yaml.safe_load(GOLDEN.read_text())["answers"]

    live = {q["id"]: ca.answer_question(cat, q) for q in spec["questions"]}

    stale = []
    for qid, val in live.items():
        gv, lv = norm(golden[qid]["expected"]), norm(val)
        if gv != lv:
            if isinstance(lv, dict):
                delta = {k: round(lv[k] - gv.get(k, 0), 2) for k in lv}
            else:
                delta = round(lv - gv, 2)
            stale.append({"id": qid, "golden": gv, "live": lv,
                          "delta": delta})

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "db": args.db,
        "questions_checked": len(live),
        "verdict": "STALE" if stale else "CLEAN",
        "stale_count": len(stale),
        "stale": stale,
    }
    out = args.out or str(ROOT / "phase5" / "canary_report.json")
    Path(out).write_text(json.dumps(report, indent=2))

    print(f"[{report['verdict']}] {len(live)} questions checked against "
          f"golden, {len(stale)} stale")
    for s in stale:
        print(f"  {s['id']}: golden {s['golden']} -> live {s['live']}")
    print(f"report: {out}")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
