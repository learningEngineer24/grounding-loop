"""Phase 2 validation: every governed metric vs hand-written direct SQL.

"Query it until the numbers are unassailable." Each entry: the metric as
compiled by SemanticCatalog vs the same logic written by hand. Any mismatch
fails loudly.

Usage: cd ~/workspace/grounding-loop && .venv/bin/python phase2/validate_v1.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from semantic_compiler import SemanticCatalog

import duckdb

DB = Path(__file__).resolve().parent.parent / "warehouse.duckdb"
CAT = SemanticCatalog(Path(__file__).resolve().parent / "semantics_v1.yml")

# metric -> (direct SQL, optional compiler kwargs)
CHECKS = {
    "settled_revenue": (
        "SELECT SUM(amount) FROM payments WHERE status = 'settled'", {}),
    "total_payments": (
        "SELECT COUNT(*) FROM payments", {}),
    "total_refunds": (
        "SELECT SUM(refund_amount) FROM refunds", {}),
    "net_realized_revenue": (
        """SELECT (SELECT SUM(amount) FROM payments WHERE status = 'settled')
                - (SELECT SUM(refund_amount) FROM refunds)""", {}),
    "gross_revenue": (
        "SELECT SUM(gross_amount) FROM orders", {}),
    "total_discounts": (
        "SELECT SUM(discount_amount) FROM orders", {}),
    "net_order_value": (
        "SELECT SUM(gross_amount - discount_amount) FROM orders", {}),
    "total_orders": (
        "SELECT COUNT(*) FROM orders", {}),
    "avg_order_value": (
        """SELECT SUM(gross_amount - discount_amount) * 1.0 / COUNT(*)
           FROM orders""", {}),
    "total_customers": (
        "SELECT COUNT(*) FROM customers", {}),
    "active_customers": (
        "SELECT COUNT(*) FROM customers WHERE account_type = 'paid'", {}),
    "trial_customers": (
        "SELECT COUNT(*) FROM customers WHERE account_type = 'trial'", {}),
    "cancelled_customers": (
        "SELECT COUNT(*) FROM customers WHERE account_type = 'cancelled'", {}),
    "churn_rate": (
        """SELECT COUNT(*) FILTER (WHERE account_type = 'cancelled') * 1.0
                  / COUNT(*) FROM customers""", {}),
    # dimensional spot-checks: the compiler must also get GROUP BY right
    "settled_revenue_by_month": (
        """SELECT DATE_TRUNC('month', payment_date) AS m,
                  SUM(amount) FROM payments
           WHERE status = 'settled' GROUP BY 1 ORDER BY 1""",
        {"metric": "settled_revenue", "dimensions": ["payment_date"],
         "grain": "month"}),
    "active_by_region": (
        """SELECT region, COUNT(*) FROM customers
           WHERE account_type = 'paid' GROUP BY 1 ORDER BY 1""",
        {"metric": "active_customers", "dimensions": ["region"]}),
}


def main():
    con = duckdb.connect(str(DB), read_only=True)
    failures = 0
    for label, (direct_sql, kwargs) in CHECKS.items():
        metric = kwargs.pop("metric", label)
        got = CAT.run(DB, metric, **kwargs)
        want = con.execute(direct_sql).fetchall()
        # normalize values for comparison (numbers, dates, strings)
        def norm(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return str(v)
        got_n = [[norm(v) for v in row] for row in got]
        want_n = [[norm(v) for v in row] for row in want]
        ok = len(got_n) == len(want_n) and all(
            all((abs(a - b) < 1e-6 if isinstance(a, float) and isinstance(b, float)
                 else a == b) for a, b in zip(gr, wr))
            for gr, wr in zip(got_n, want_n))
        status = "ok " if ok else "FAIL"
        val = got_n[0][0] if len(got_n) == 1 and len(got_n[0]) == 1 else f"{len(got_n)} rows"
        print(f"[{status}] {label:28s} = {val}")
        if not ok:
            failures += 1
            print(f"       compiled: {got_n[:3]}")
            print(f"       direct:   {want_n[:3]}")
    con.close()
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
