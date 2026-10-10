# Semantic layer changelog

## v2 (Oct 8, 2026)

**Source of the joins:** the four relationships come straight from the
Phase 1 ER diagram (`phase1/data_model_diagram.png`).

### Added
- `joins:` declarations on three models (each declared once; reverse
  directions are inferred):
  - `orders → customers` — many_to_one on `customer_id`
  - `orders → products` — many_to_one on `product_id`
  - `payments → orders` — one_to_one on `order_id`
  - `refunds → payments` — many_to_one on `payment_id`
- `dimension_tables:` — `products` joins the catalog as a **dimension table**,
  not a fact model. Its grain ("one row per product") has no meaningful
  measures; its attributes (`category`, `product_name`) slice order facts
  via the `orders → products` join.
- New metric: `units_sold` (`orders.quantity` SUM; free-addon quantities
  included per Quirk 6).
- Compiler: cross-model dimension resolution. `compile('gross_revenue',
  dimensions=['category'])` now emits the JOIN. Multi-hop paths resolve via
  BFS — e.g. `settled_revenue` by `region` compiles to
  `payments → orders → customers`.
- Fan-out guard: any path containing a one→many hop *from the querying
  model's grain* is **refused with an error** instead of silently
  double-counting. E.g. `total_customers` by `order_date` raises
  `ValueError` (COUNT(*) would duplicate customers with multiple orders).

### Unchanged
- All 16 v1 metrics return byte-identical results — the v1 regression suite
  (`phase2/validate_v1.py`'s 16 checks) passes against `semantics_v2.yml`.

### Roadmap (not limitations — planned, not yet built)
- **Derived metrics by period.** Scalar-only today; resolving means grouping
  each ingredient CTE by the period and joining them on it.
- **Ad-hoc WHERE filters.** Per-query structured filters (dimension +
  operator + value), validated against the catalog and applied pre-aggregation.
  Post-compile row filtering in Python is the interim workaround.

### Known simplifications (present behavior, flagged as approximate)
- **`churn_rate` = cancelled ÷ total.** Deliberate v1 simplification —
  ignores `cancel_date`, period, and cohort. See below for the standard
  resolution.

### Design decisions (not gaps)
- **Fan-out paths are refused, never silently computed.** Joining *through*
  a one→many hop from the metric's grain raises instead of double-counting.
  This is the intended behavior, not a missing feature.

### Golden-dataset impact
`phase3/golden_answers.yml` is locked to definition **v1** and is untouched.
Under v2, three questions change status:
- **Q205** ("how many units did we sell?") → answerable via `units_sold`.
- **Q109** ("settled revenue from trial customers") → answerable via the
  `account_type` join path.
- **Q207** ("revenue per customer by region") → the join half becomes
  answerable; "revenue" and "per customer" remain ambiguous.
A v2 revision of the golden set is future work.

## v1 (Oct 8, 2026)
- Initial governed catalog: 4 semantic models (payments, refunds, orders,
  customers), 16 metrics (13 simple + 3 derived: `net_realized_revenue`,
  `avg_order_value`, `churn_rate`).
- Single-table metrics only; no joins.
- Compiler validated 16/16 against hand-written SQL (`phase2/validate_v1.py`).

## v2 -> v3 (2026-10-09)
- `total_refunds`: monthly attribution changed from refund-event month
  (`refund_date`) to original-payment month (`payment_date`, via the
  declared refunds -> payments join). Finance: refunds should match the
  revenue period they offset. H1 totals are unaffected; monthly breakdowns
  move dollars across months. Metric carries a machine-readable
  `attribution` block (time_dimension, changed_in_version, previous, reason).
