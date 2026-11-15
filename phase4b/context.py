"""
Shared context for the Phase 4b no-layer ablation agent.

The agent gets the raw warehouse schema (DDL) plus the full QUIRKS.md —
the same documented knowledge the governed layer encodes. What it does NOT
get: governed metrics, the compiler, or any guardrails. The experiment
isolates enforcement: knowledge the agent must remember to apply vs.
knowledge compiled into definitions it cannot forget.
"""
from __future__ import annotations

from pathlib import Path

BASE = Path(__file__).resolve().parent

SCHEMA_DDL = """-- Warehouse: DuckDB, date range 2026-01-01 to 2026-06-30 (H1 2026).
-- All joins are on the obvious *_id keys.

CREATE TABLE customers (
  customer_id INTEGER PRIMARY KEY,
  email VARCHAR,
  signup_date DATE,
  account_type VARCHAR,   -- 'active' | 'trial' | 'cancelled'
  cancel_date DATE,        -- NULL unless account_type = 'cancelled'
  region VARCHAR,
  plan_tier VARCHAR
);  -- 500 rows

CREATE TABLE products (
  product_id INTEGER PRIMARY KEY,
  product_name VARCHAR,
  category VARCHAR,
  unit_price DECIMAL(10,2)  -- product_id 41 is a $0 free add-on
);  -- 41 rows

CREATE TABLE orders (
  order_id INTEGER PRIMARY KEY,
  customer_id INTEGER,     -- -> customers.customer_id
  product_id INTEGER,      -- -> products.product_id
  order_date DATE,
  quantity INTEGER,
  gross_amount DECIMAL(10,2),    -- headline amount BEFORE discounts
  discount_amount DECIMAL(10,2)  -- order-level discount
);  -- 3000 rows

CREATE TABLE payments (
  payment_id INTEGER PRIMARY KEY,
  order_id INTEGER,        -- -> orders.order_id (one payment per order)
  payment_date DATE,       -- may lag order_date by up to 75 days
  amount DECIMAL(10,2),
  status VARCHAR           -- 'settled' | 'pending_settlement' | 'failed'
                           -- | 'chargeback' | 'voided' | 'refunded'
);  -- 3000 rows

CREATE TABLE refunds (
  refund_id INTEGER PRIMARY KEY,
  payment_id INTEGER,      -- -> payments.payment_id
  refund_date DATE,        -- days-to-weeks AFTER the payment date
  refund_amount DECIMAL(10,2)  -- partial refunds possible
);  -- 140 rows
"""

QUIRKS = (BASE.parent / "QUIRKS.md").read_text()

CONTEXT = SCHEMA_DDL + "\n" + QUIRKS
