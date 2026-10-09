"""Phase 2b validation: semantics_v2.yml.

Part 1 — regression: all 16 v1 checks must pass unchanged against v2.
Part 2 — joins: cross-model dimensions compile to correct SQL (vs hand SQL).
Part 3 — refusals: fan-out paths raise ValueError; unknown dims raise KeyError.

Usage: cd ~/workspace/grounding-loop && .venv/bin/python phase2/validate_v2.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from semantic_compiler import SemanticCatalog
from validate_v1 import CHECKS as V1_CHECKS

import duckdb

DB = Path(__file__).resolve().parent.parent / "warehouse.duckdb"
CAT = SemanticCatalog(Path(__file__).resolve().parent / "semantics_v2.yml")

# label -> (direct SQL, compiler kwargs)
JOIN_CHECKS = {
    "gross_revenue by category": (
        """SELECT p.category, SUM(o.gross_amount) FROM orders o
           JOIN products p ON o.product_id = p.product_id
           GROUP BY 1 ORDER BY 1""",
        {"metric": "gross_revenue", "dimensions": ["category"]}),
    "units_sold": (
        "SELECT SUM(quantity) FROM orders",
        {"metric": "units_sold"}),
    "units_sold by category": (
        """SELECT p.category, SUM(o.quantity) FROM orders o
           JOIN products p ON o.product_id = p.product_id
           GROUP BY 1 ORDER BY 1""",
        {"metric": "units_sold", "dimensions": ["category"]}),
    "net_order_value by region": (
        """SELECT c.region, SUM(o.gross_amount - o.discount_amount)
           FROM orders o JOIN customers c ON o.customer_id = c.customer_id
           GROUP BY 1 ORDER BY 1""",
        {"metric": "net_order_value", "dimensions": ["region"]}),
    "settled_revenue by region (two-hop)": (
        """SELECT c.region, SUM(p.amount) FROM payments p
           JOIN orders o ON p.order_id = o.order_id
           JOIN customers c ON o.customer_id = c.customer_id
           WHERE p.status = 'settled' GROUP BY 1 ORDER BY 1""",
        {"metric": "settled_revenue", "dimensions": ["region"]}),
    "settled_revenue by product category (two-hop)": (
        """SELECT pr.category, SUM(p.amount) FROM payments p
           JOIN orders o ON p.order_id = o.order_id
           JOIN products pr ON o.product_id = pr.product_id
           WHERE p.status = 'settled' GROUP BY 1 ORDER BY 1""",
        {"metric": "settled_revenue", "dimensions": ["category"]}),
}


def norm(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


def check(label, direct_sql, kwargs, con):
    metric = kwargs.pop("metric", label)
    got = CAT.run(DB, metric, **kwargs)
    want = con.execute(direct_sql).fetchall()
    got_n = [[norm(v) for v in row] for row in got]
    want_n = [[norm(v) for v in row] for row in want]
    ok = len(got_n) == len(want_n) and all(
        all((abs(a - b) < 1e-6 if isinstance(a, float) and isinstance(b, float)
             else a == b) for a, b in zip(gr, wr))
        for gr, wr in zip(got_n, want_n))
    val = got_n[0][0] if len(got_n) == 1 and len(got_n[0]) == 1 else f"{len(got_n)} rows"
    print(f"[{'ok ' if ok else 'FAIL'}] {label:38s} = {val}")
    if not ok:
        print(f"       compiled: {got_n[:3]}")
        print(f"       direct:   {want_n[:3]}")
    return ok


def main():
    assert CAT.version == 2, "validator expects semantics_v2.yml"
    con = duckdb.connect(str(DB), read_only=True)
    failures = 0

    print("--- v1 regression (16 checks vs v2 YAML) ---")
    for label, (direct_sql, kwargs) in V1_CHECKS.items():
        if not check(label, direct_sql, dict(kwargs), con):
            failures += 1

    print("--- join checks ---")
    for label, (direct_sql, kwargs) in JOIN_CHECKS.items():
        if not check(label, direct_sql, dict(kwargs), con):
            failures += 1

    print("--- refusal checks ---")
    # customers -> orders is one->many from the customers grain: COUNT(*) would
    # duplicate customers. Must refuse, not silently double-count.
    try:
        CAT.compile("total_customers", dimensions=["order_date"])
        print("[FAIL] fan-out path did not raise")
        failures += 1
    except ValueError as e:
        print(f"[ok ] fan-out refused: {e}")
    try:
        CAT.compile("gross_revenue", dimensions=["no_such_dim"])
        print("[FAIL] unknown dimension did not raise")
        failures += 1
    except KeyError as e:
        print(f"[ok ] unknown dimension raised KeyError: {e}")

    con.close()
    total = len(V1_CHECKS) + len(JOIN_CHECKS) + 2
    print(f"\n{total - failures}/{total} checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
