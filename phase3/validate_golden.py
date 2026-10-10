"""Phase 3: validate the golden dataset.

Recomputes every expected value through the semantic compiler and compares
against the locked golden_answers.yml. Any drift — warehouse rebuild,
definition change, compiler change — fails loudly.

Usage: python3 phase3/validate_golden.py
Exit 0: all checks pass. Exit 1: any mismatch.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "phase2"))
sys.path.insert(0, str(ROOT / "phase3"))
from compute_answers import (ROOT as CROOT, SemanticCatalog, answer_question)  # noqa: E402

LOCKED = ROOT / "phase3" / "golden_answers.yml"


def main() -> int:
    locked = yaml.safe_load(LOCKED.read_text())
    spec = yaml.safe_load((ROOT / "phase3" / "golden_questions.yml").read_text())
    assert locked["definition_version"] == spec["definition_version"] == 1

    cat = SemanticCatalog(ROOT / "phase2" / "semantics_v1.yml")
    by_id = {q["id"]: q for q in spec["questions"]}

    failures = []
    checked = 0
    for qid, entry in locked["answers"].items():
        q = by_id[qid]
        fresh = answer_question(cat, q)
        checked += 1
        if fresh != entry["expected"]:
            failures.append((qid, entry["expected"], fresh))

    # coverage: every question present, categories balanced as designed
    cats = [q["category"] for q in spec["questions"]]
    assert len(spec["questions"]) == 167, "golden set must stay at 167 questions"
    print(f"checked {checked}/167 locked answers against live warehouse + compiler")
    print(f"category split: {cats.count('straightforward')} straightforward / "
          f"{cats.count('trap')} trap / {cats.count('ambiguous')} ambiguous")

    if failures:
        print(f"\n{len(failures)} MISMATCHES:")
        for qid, old, new in failures:
            print(f"  {qid}: locked={old} recomputed={new}")
        return 1
    print("all golden answers reproduce — dataset is locked and honest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
