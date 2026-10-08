# Deliberate data quirks (fixture documentation)

Seeded RNG (`20261007`) — the warehouse rebuilds identically every run.
Date range: **2026-01-01 → 2026-06-30** (H1; Q1-vs-Q2 comparisons work).

These quirks are the raw material for Phase 3 trap questions. Each one is a
way a reasonable person — or a bare LLM writing its own SQL — gets the
"wrong" answer while the governed metric gets it right.

## Quirk 1 — Refunds live in their own table, dated later
`refunds.refund_date` is days-to-weeks after the payment date. Netting refunds
by **order month** vs **refund month** gives different monthly revenue.
~5% of payments end `refunded`; 30% of those are **partial** (`refund_amount <
amount`), so "revenue" also depends on whether you subtract the full payment
or the actual refund.

## Quirk 2 — Trial accounts place orders
12% of customers are `account_type = 'trial'`, and trials **can** place orders
(product-led motion). "Active customers" under the v1 definition excludes
trials — a naive `COUNT(DISTINCT customer_id)` over orders overcounts.

## Quirk 3 — Late partitions
~5% of payments have `payment_date` more than 30 days after `order_date`
(batch processing lag; some land up to 75 days later). A freshness check on
"payments through June 30" will look complete while June revenue is
understated until the late batch lands. (Phase 5 data-drift exercise.)

## Quirk 4 — Payment statuses that look like revenue but aren't
`payments.status` values and their governed treatment (to be encoded in
Phase 2 metric YAML, **not** obvious from the column):

| status               | share | counts as revenue? |
|----------------------|-------|--------------------|
| settled              | ~80%  | yes                |
| pending_settlement   | ~6%   | **no** — not realized |
| failed               | ~5%   | no                 |
| chargeback           | ~2%   | no                 |
| voided               | ~2%   | no                 |
| refunded             | ~5%   | no (see Quirk 1)   |

`SUM(amount)` over payments overstates revenue by ~20%. The trap writes itself:
*"What was our revenue in Q1?"*

## Quirk 5 — Cancelled customers
8% of customers are `account_type = 'cancelled'` with a `cancel_date`.
"Active customers" excludes them too — and "churn" needs the cancel date,
not just the flag.

## Quirk 6 — A $0 product
`product_id = 41` ("free_addon") has `unit_price = 0.00` and appears in real
orders. Quantity-based metrics count it; revenue-based metrics don't. Trap for
"average order value" (per order? per unit? revenue-bearing only?).

## Quirk 7 — Discounts are order-level
`orders.discount_amount` reduces what the customer paid, but `gross_amount`
is the headline number. Net revenue = gross − discounts, on settled payments
only. Three compounding adjustments between "gross" and "net".

---
*Phase 2 will encode the governed answers to all of the above as versioned
metric YAML. Nothing here is a bug — it's the curriculum.*
