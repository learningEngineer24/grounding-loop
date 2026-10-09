"""Phase 3: compute golden answers through the semantic compiler.

Every expected value is derived by compiling the question's metric via
phase2/semantic_compiler.py against the DuckDB warehouse. Nothing is
hand-written SQL and nothing is hand-typed. Period cuts are applied to
compiled dimensional rows in Python.

Derived metrics with a period (net_realized_revenue, avg_order_value) are
computed from their compiled components — the compiler is scalar-only for
derived metrics in v1, so the combination happens here, transparently.

Usage: python3 phase3/compute_answers.py
Writes: phase3/golden_answers.yml (locked expected values)
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "phase2"))
from semantic_compiler import SemanticCatalog  # noqa: E402

DB = ROOT / "warehouse.duckdb"
QUESTIONS = ROOT / "phase3" / "golden_questions.yml"
OUT = ROOT / "phase3" / "golden_answers.yml"

Q1_MONTHS = ["2026-01", "2026-02", "2026-03"]
Q2_MONTHS = ["2026-04", "2026-05", "2026-06"]
H1_MONTHS = Q1_MONTHS + Q2_MONTHS

MONEY_METRICS = {
    "settled_revenue", "total_refunds", "net_realized_revenue",
    "gross_revenue", "total_discounts", "net_order_value", "avg_order_value",
}
COUNT_METRICS = {
    "total_payments", "total_orders", "total_customers", "active_customers",
    "trial_customers", "cancelled_customers",
}
RATE_METRICS = {"churn_rate"}


def month_key(ts) -> str:
    if isinstance(ts, (datetime, date)):
        return ts.strftime("%Y-%m")
    return str(ts)[:7]


def period_months(period: str) -> list[str]:
    if period == "Q1":
        return Q1_MONTHS
    if period == "Q2":
        return Q2_MONTHS
    if period == "H1":
        return H1_MONTHS
    return [period]  # YYYY-MM


def fmt(value, metric: str):
    if metric in MONEY_METRICS:
        return round(float(value), 2)
    if metric in COUNT_METRICS:
        return int(value)
    if metric in RATE_METRICS:
        return round(float(value), 4)
    return value


def monthly_series(cat: SemanticCatalog, metric: str, dim: str) -> dict[str, float]:
    rows = cat.run(DB, metric, dimensions=[dim], grain="month")
    out: dict[str, float] = {}
    for ts, val in rows:
        out[month_key(ts)] = float(val or 0)
    return out


def dim_breakdown(cat: SemanticCatalog, metric: str, dim: str) -> dict:
    rows = cat.run(DB, metric, dimensions=[dim])
    return {str(k): fmt(v, metric) for k, v in rows}


def scalar(cat: SemanticCatalog, metric: str):
    return fmt(cat.run(DB, metric)[0][0], metric)


def derived_by_period(cat: SemanticCatalog, metric: str, period: str):
    """Combine compiled components for derived metrics over a period."""
    months = period_months(period)
    spec = cat.metrics[metric]
    if metric == "net_realized_revenue":
        rev = monthly_series(cat, "settled_revenue", "payment_date")
        ref = monthly_series(cat, "total_refunds", "refund_date")
        if period in ("Q1", "Q2"):
            r = sum(rev.get(m, 0) for m in months)
            f = sum(ref.get(m, 0) for m in months)
            return {"Q1": round(r - f, 2)} if period == "Q1" else {"Q2": round(r - f, 2)}
        if len(months) == 1:
            m = months[0]
            return {m: round(rev.get(m, 0) - ref.get(m, 0), 2)}
        # H1 with grain=quarter
        return {
            "Q1": round(sum(rev.get(m, 0) for m in Q1_MONTHS) - sum(ref.get(m, 0) for m in Q1_MONTHS), 2),
            "Q2": round(sum(rev.get(m, 0) for m in Q2_MONTHS) - sum(ref.get(m, 0) for m in Q2_MONTHS), 2),
        }
    if metric == "avg_order_value":
        net = monthly_series(cat, "net_order_value", "order_date")
        cnt = monthly_series(cat, "total_orders", "order_date")
        n = sum(net.get(m, 0) for m in months)
        c = sum(cnt.get(m, 0) for m in months)
        label = period if period in ("Q1", "Q2") else months[0]
        return {label: round(n / c, 2) if c else 0.0}
    raise ValueError(f"no period logic for derived metric {metric}")


def answer_question(cat: SemanticCatalog, q: dict):
    metric = q.get("metric")
    if metric is None:
        if q.get("metrics"):  # Q111: report both governed neighbors
            return {m: scalar(cat, m) for m in q["metrics"]}
        return None  # clarify / refuse — no computable expected value
    dims = q.get("dimensions")
    grain = q.get("grain")
    period = q.get("period")
    is_derived = cat.metrics[metric].get("type") == "derived"

    if is_derived and (grain or period):
        return derived_by_period(cat, metric, period or "H1")
    if is_derived:
        return scalar(cat, metric)
    if dims and grain == "month":
        series = monthly_series(cat, metric, dims[0])
        months = period_months(period) if period else H1_MONTHS
        if period and len(months) == 1:
            return {months[0]: fmt(series.get(months[0], 0), metric)}
        if period in ("Q1", "Q2"):
            return {period: fmt(sum(series.get(m, 0) for m in months), metric)}
        return {m: fmt(series.get(m, 0), metric) for m in months}
    if dims:
        return dim_breakdown(cat, metric, dims[0])
    return scalar(cat, metric)


def main():
    spec = yaml.safe_load(QUESTIONS.read_text())
    assert spec["definition_version"] == 1
    cat = SemanticCatalog(ROOT / "phase2" / "semantics_v1.yml")

    answers = {}
    for q in spec["questions"]:
        qid = q["id"]
        try:
            val = answer_question(cat, q)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"failed to compute {qid}: {e}") from e
        answers[qid] = {
            "question": q["question"],
            "category": q["category"],
            "metric": q.get("metric") or q.get("metrics"),
            "expected_behavior": q["expected_behavior"],
            "expected": val,
            "definition_version": 1,
        }

    n_answered = sum(1 for a in answers.values() if a["expected"] is not None)
    doc = {
        "definition_version": 1,
        "question_count": len(answers),
        "answered_count": n_answered,
        "note": "Locked golden answers computed through the semantic compiler. "
                "Regenerate with phase3/compute_answers.py; do not hand-edit.",
        "answers": answers,
    }
    OUT.write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))
    print(f"wrote {OUT} — {len(answers)} questions, {n_answered} with computed expected values")


if __name__ == "__main__":
    main()
