"""
Phase 1 — Build the DuckDB warehouse with deliberate quirks.

Finance-flavored e-commerce: customers, products, orders, payments, refunds.
Deterministic (seeded RNG) so the fixture is reproducible.

Every deliberate quirk is documented in ../QUIRKS.md — they become the
trap questions in Phase 3.
"""
from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

import duckdb

RNG = random.Random(20261007)
DB_PATH = Path(__file__).resolve().parent.parent / "warehouse.duckdb"

START = dt.date(2026, 1, 1)
END = dt.date(2026, 6, 30)  # H1 2026: Q1 vs Q2 comparisons work

REGIONS = ["west", "east", "central", "intl"]
PLAN_TIERS = ["starter", "growth", "enterprise"]

# payment_status values and whether they count as realized revenue.
# Governed in Phase 2; seeded ambiguously here on purpose.
PAYMENT_STATUSES = [
    ("settled", 0.80),
    ("pending_settlement", 0.06),  # looks like revenue, is not realized
    ("failed", 0.05),
    ("chargeback", 0.02),
    ("voided", 0.02),
    ("refunded", 0.05),  # see refunds table for partial-refund nuance
]


def weighted_choice(weighted):
    r = RNG.random()
    cum = 0.0
    for value, w in weighted:
        cum += w
        if r < cum:
            return value
    return weighted[-1][0]


def rand_date(lo=START, hi=END):
    return lo + dt.timedelta(days=RNG.randint(0, (hi - lo).days))


def main():
    for suffix in ["", ".wal"]:
        p = DB_PATH.with_name(DB_PATH.name + suffix)
        if p.exists():
            p.unlink()
    con = duckdb.connect(str(DB_PATH))

    con.execute("""
        CREATE TABLE customers (
            customer_id   INTEGER PRIMARY KEY,
            email         VARCHAR,
            signup_date   DATE,
            account_type  VARCHAR,   -- 'trial' | 'paid' | 'cancelled'
            cancel_date   DATE,      -- NULL unless cancelled
            region        VARCHAR,
            plan_tier     VARCHAR
        );
        CREATE TABLE products (
            product_id    INTEGER PRIMARY KEY,
            product_name  VARCHAR,
            category      VARCHAR,
            unit_price    DECIMAL(10,2)
        );
        CREATE TABLE orders (
            order_id        INTEGER PRIMARY KEY,
            customer_id     INTEGER REFERENCES customers(customer_id),
            product_id      INTEGER REFERENCES products(product_id),
            order_date      DATE,
            quantity        INTEGER,
            gross_amount    DECIMAL(10,2),
            discount_amount DECIMAL(10,2)
        );
        CREATE TABLE payments (
            payment_id    INTEGER PRIMARY KEY,
            order_id      INTEGER REFERENCES orders(order_id),
            payment_date  DATE,
            amount        DECIMAL(10,2),
            status        VARCHAR  -- see PAYMENT_STATUSES; easy to misread
        );
        CREATE TABLE refunds (
            refund_id     INTEGER PRIMARY KEY,
            payment_id    INTEGER REFERENCES payments(payment_id),
            refund_date   DATE,
            refund_amount DECIMAL(10,2)  -- may be partial
        );
    """)

    # ---- products (one is a $0 free-tier add-on) ----
    categories = ["analytics", "storage", "compute", "support"]
    products = []
    for i in range(1, 41):
        price = round(RNG.uniform(19, 4999), 2)
        products.append((i, f"product_{i:02d}", RNG.choice(categories), price))
    products.append((41, "free_addon", "support", 0.00))  # QUIRK 6
    con.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", products)

    # ---- customers: 12% trial, 8% cancelled ----
    customers = []
    for i in range(1, 501):
        r = RNG.random()
        if r < 0.12:
            acct, cancel = "trial", None
        elif r < 0.20:
            acct = "cancelled"
            cancel = rand_date(dt.date(2026, 2, 1), END)
        else:
            acct, cancel = "paid", None
        customers.append((
            i, f"user{i:04d}@example.com", rand_date(),
            acct, cancel, RNG.choice(REGIONS), RNG.choice(PLAN_TIERS),
        ))
    con.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)", customers)

    # ---- orders: trials CAN order (product-led motion) — QUIRK 2 ----
    orders, payments, refunds = [], [], []
    oid, pid, rid = 1, 1, 1
    for _ in range(3000):
        cust = RNG.randint(1, 500)
        prod = RNG.randint(1, 41)
        qty = RNG.randint(1, 5)
        price = next(p[3] for p in products if p[0] == prod)
        gross = round(float(price) * qty, 2)
        discount = round(gross * RNG.choice([0, 0, 0, 0.1, 0.15, 0.2]), 2)
        odate = rand_date()
        orders.append((oid, cust, prod, odate, qty, gross, discount))

        status = weighted_choice(PAYMENT_STATUSES)
        # QUIRK 3: ~5% of payments land >30 days after the order (late batch)
        if RNG.random() < 0.05:
            pdate = odate + dt.timedelta(days=RNG.randint(31, 75))
        else:
            pdate = odate + dt.timedelta(days=RNG.randint(0, 3))
        pdate = min(pdate, END)
        amount = round(gross - discount, 2)
        payments.append((pid, oid, pdate, amount, status))

        # QUIRK 1/5: refunded payments get a refunds row; 30% are partial.
        # Refund date is AFTER the payment date — netting by refund date vs
        # order date gives different monthly revenue. That's the trap.
        if status == "refunded":
            if RNG.random() < 0.30:
                ramount = round(amount * RNG.uniform(0.2, 0.8), 2)
            else:
                ramount = amount
            rdate = min(pdate + dt.timedelta(days=RNG.randint(1, 45)), END)
            refunds.append((rid, pid, rdate, ramount))
            rid += 1

        oid += 1
        pid += 1

    print(f"generated {len(orders)} orders, {len(payments)} payments, {len(refunds)} refunds", flush=True)
    import time as _t
    _s = _t.time()
    con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", orders)
    con.executemany("INSERT INTO payments VALUES (?, ?, ?, ?, ?)", payments)
    if refunds:
        con.executemany("INSERT INTO refunds VALUES (?, ?, ?, ?)", refunds)
    print(f"inserts done in {round(_t.time()-_s,1)}s", flush=True)
    con.executemany("INSERT INTO payments VALUES (?, ?, ?, ?, ?)", payments)
    if refunds:
        con.executemany("INSERT INTO refunds VALUES (?, ?, ?, ?)", refunds)

    # ---- sanity summary ----
    for tbl in ["customers", "products", "orders", "payments", "refunds"]:
        n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"{tbl:10s} {n:6d} rows")
    print("payment status mix:")
    for row in con.execute(
        "SELECT status, COUNT(*) FROM payments GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        print(f"  {row[0]:20s} {row[1]:5d}")
    print("account_type mix:")
    for row in con.execute(
        "SELECT account_type, COUNT(*) FROM customers GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        print(f"  {row[0]:12s} {row[1]:5d}")

    con.close()
    print(f"\nwrote {DB_PATH}")


if __name__ == "__main__":
    main()
