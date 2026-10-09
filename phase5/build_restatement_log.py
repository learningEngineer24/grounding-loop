"""Phase 5, build 3: restatement log as a first-class entity.

Creates a restatement_log table in both snapshot DBs and populates the
July-15 snapshot with the four measured restatements (June 2026 values on
snapshot A vs snapshot B, computed through the v1 compiler).

Schema: metric, period, restated_on, reason, old_value, new_value.

The governed agent queries it through the list_restatements tool
(phase4/tools.py); the log is append-only by convention — each restatement
is a new row, history is never rewritten.

Usage: python3 phase5/build_restatement_log.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "phase2"))
sys.path.insert(0, str(ROOT / "phase3"))

import compute_answers as ca  # noqa: E402
from semantic_compiler import SemanticCatalog  # noqa: E402

SNAP_A = ROOT / "phase5" / "warehouse_20260630.duckdb"
SNAP_B = ROOT / "phase5" / "warehouse_20260715.duckdb"

METRICS = ["settled_revenue", "total_refunds", "total_payments",
           "net_realized_revenue"]
PERIOD = "2026-06"
RESTATED_ON = "2026-07-15"
REASON = "late-arriving payments landed"

DDL = """
CREATE TABLE IF NOT EXISTS restatement_log (
  metric VARCHAR NOT NULL,
  period VARCHAR NOT NULL,
  restated_on DATE NOT NULL,
  reason VARCHAR NOT NULL,
  old_value DECIMAL(14,2) NOT NULL,
  new_value DECIMAL(14,2) NOT NULL
)
"""


def june_value(db: Path, metric: str) -> float:
    ca.DB = db
    cat = SemanticCatalog(ROOT / "phase2" / "semantics_v1.yml")
    dims = {"settled_revenue": "payment_date",
            "total_refunds": "refund_date",
            "total_payments": "payment_date"}.get(metric)
    if dims:
        rows = dict((str(k)[:7], float(v or 0))
                    for k, v in cat.run(db, metric, dimensions=[dims],
                                        grain="month"))
        return round(rows.get(PERIOD, 0.0), 2)
    # derived: net_realized_revenue = settled_revenue - total_refunds
    rev = june_value(db, "settled_revenue")
    ref = june_value(db, "total_refunds")
    return round(rev - ref, 2)


def main() -> None:
    rows = []
    for m in METRICS:
        old = june_value(SNAP_A, m)
        new = june_value(SNAP_B, m)
        rows.append((m, PERIOD, RESTATED_ON, REASON, old, new))
        print(f"{m}: {PERIOD} {old} -> {new} "
              f"(delta {round(new - old, 2)})")

    for snap, data in [(SNAP_A, []), (SNAP_B, rows)]:
        con = duckdb.connect(str(snap))
        con.execute("DROP TABLE IF EXISTS restatement_log")
        con.execute(DDL)
        if data:
            con.executemany(
                "INSERT INTO restatement_log VALUES (?, ?, ?, ?, ?, ?)", data)
        n = con.execute("SELECT COUNT(*) FROM restatement_log").fetchone()[0]
        con.close()
        print(f"{snap.name}: restatement_log has {n} rows")


if __name__ == "__main__":
    sys.exit(main())
