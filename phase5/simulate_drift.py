"""Phase 5: drift simulation — two as-of snapshots of the warehouse.

Quirk 3: ~5% of payments arrive more than 30 days after their order date
(batch processing lag). A "payments through June 30" freshness check looks
complete while June revenue is understated until the late batch lands.

This script builds two snapshots:
  warehouse_20260630.duckdb — what we knew at the June 30 close
  warehouse_20260715.duckdb — what we know on July 15, late batch landed

The base warehouse has no ingest timestamp, so arrived_at is synthesized
deterministically (seed 20261009): on-time payments arrive on payment_date;
late payments (payment_date > order_date + 30 days) arrive 1-15 days after
payment_date. Only the payments table differs between snapshots; orders,
customers, products, and refunds are identical.

Snapshot B contains every payment, so metric values computed on it must
exactly reproduce the locked golden answers — detect_drift.py asserts this.

Usage: python3 phase5/simulate_drift.py
Writes: phase5/warehouse_20260630.duckdb, phase5/warehouse_20260715.duckdb
        (local only, like the base warehouse — never committed)
"""
from __future__ import annotations

import random
import shutil
import sys
from datetime import timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
BASE_DB = ROOT / "warehouse.duckdb"
OUT_A = ROOT / "phase5" / "warehouse_20260630.duckdb"
OUT_B = ROOT / "phase5" / "warehouse_20260715.duckdb"

SEED = 20261009
CLOSE_A = "2026-06-30"
CLOSE_B = "2026-07-15"


def build_snapshot(out_path: Path, asof: str | None) -> dict:
    """Copy base warehouse; optionally drop payments arriving after asof."""
    if out_path.exists():
        out_path.unlink()
    shutil.copy(BASE_DB, out_path)
    con = duckdb.connect(str(out_path))
    con.execute(
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS arrived_at DATE"
    )
    rng = random.Random(SEED)
    rows = con.execute(
        """
        SELECT p.payment_id, p.payment_date, o.order_date
        FROM payments p JOIN orders o ON p.order_id = o.order_id
        ORDER BY p.payment_id
        """
    ).fetchall()
    arrivals = []
    for pid, pdate, odate in rows:
        if pdate > odate + timedelta(days=30):
            arrived = pdate + timedelta(days=rng.randint(1, 15))
        else:
            arrived = pdate
        arrivals.append((pid, arrived))
    con.execute("CREATE TEMP TABLE arrivals(payment_id INT, arrived_at DATE)")
    con.executemany("INSERT INTO arrivals VALUES (?, ?)", arrivals)
    con.execute(
        """UPDATE payments SET arrived_at = a.arrived_at
           FROM arrivals a WHERE payments.payment_id = a.payment_id"""
    )
    late = con.execute(
        """SELECT COUNT(*) FROM payments p JOIN orders o ON p.order_id = o.order_id
           WHERE p.payment_date > o.order_date + INTERVAL 30 DAY"""
    ).fetchone()[0]
    excluded = 0
    if asof:
        # refunds of late payments arrive late too — unknown at close
        con.execute(
            """DELETE FROM refunds WHERE payment_id IN
               (SELECT payment_id FROM payments WHERE arrived_at > ?)""",
            [asof],
        )
        excluded = con.execute(
            "SELECT COUNT(*) FROM payments WHERE arrived_at > ?", [asof]
        ).fetchone()[0]
        con.execute("DELETE FROM payments WHERE arrived_at > ?", [asof])
    n_pay = con.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    con.close()
    return {"payments": n_pay, "late_total": late, "excluded": excluded}


def asof_date(s: str):
    from datetime import date

    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


def main() -> None:
    stats_a = build_snapshot(OUT_A, CLOSE_A)
    stats_b = build_snapshot(OUT_B, CLOSE_B)
    # every payment must have arrived by the July 15 snapshot
    assert stats_b["excluded"] == 0, "late batch not fully landed by July 15"
    assert stats_a["excluded"] > 0, "snapshot A should exclude late arrivals"
    print(f"snapshot A ({CLOSE_A}): {stats_a['payments']} payments "
          f"({stats_a['excluded']} arrived late, excluded)")
    print(f"snapshot B ({CLOSE_B}): {stats_b['payments']} payments "
          f"(late batch fully landed)")
    print(f"late payments total: {stats_b['late_total']}")


if __name__ == "__main__":
    sys.exit(main())
