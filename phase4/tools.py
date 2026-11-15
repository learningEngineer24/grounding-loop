"""
Agent-facing tools for the Grounding Loop harness (Phase 4).

The agent under test NEVER writes SQL and NEVER sees the golden answers.
Every data access goes through the governed semantic compiler (v1 — the
golden dataset is locked to definition v1).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# phase2 lives next to phase4; import the compiler from there.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "phase2"))
from semantic_compiler import SemanticCatalog  # noqa: E402

BASE = Path(__file__).resolve().parent
CATALOG_PATH = BASE.parent / "phase2" / "semantics_v1.yml"
# Phase 5 drift runs point this at a snapshot DB instead.
DB_PATH = Path(os.environ.get("GROUNDING_DB", BASE.parent / "warehouse.duckdb"))
# When set (Phase 5), describe_metric exposes freshness/restatement metadata.
DATA_AS_OF = os.environ.get("GROUNDING_DATA_AS_OF")
RESTATEMENTS_PATH = os.environ.get("GROUNDING_RESTATEMENTS")

_catalog: SemanticCatalog | None = None
_restatements: dict | None = None


def restatements() -> dict:
    """Metric -> restatement metadata (Phase 5 only; empty otherwise)."""
    global _restatements
    if _restatements is None:
        _restatements = {}
        if RESTATEMENTS_PATH and Path(RESTATEMENTS_PATH).exists():
            import json

            _restatements = json.loads(Path(RESTATEMENTS_PATH).read_text())
    return _restatements


def _freshness(name: str) -> dict:
    """Freshness/restatement metadata for one metric (Phase 5 only)."""
    if not DATA_AS_OF:
        return {}
    out = {"data_as_of": DATA_AS_OF}
    r = restatements().get(name)
    if r:
        out["restatement"] = (
            f"{r['period']} restated on {r['restated_on']}: {r['reason']}. "
            f"Figures reported before {r['restated_on']} for {r['period']} "
            f"are stale."
        )
    m = catalog().metrics.get(name, {})
    if m.get("freshness"):
        out["freshness_contract"] = m["freshness"]
    return out


def list_restatements(metric: str | None = None) -> list[dict]:
    """Restatement log: every recorded restatement of a governed metric.

    Each row names the metric, the restated period, when it was restated,
    why, and the old vs new values. Empty list when nothing was restated
    (or when the warehouse predates the log).
    """
    import duckdb

    try:
        con = duckdb.connect(str(DB_PATH), read_only=True)
        q = ("SELECT metric, period, restated_on, reason, old_value, "
             "new_value FROM restatement_log")
        params: list = []
        if metric:
            q += " WHERE metric = ?"
            params.append(metric)
        rows = con.execute(q + " ORDER BY restated_on, metric",
                           params).fetchall()
        con.close()
    except Exception:
        return []
    return [{
        "metric": r[0], "period": str(r[1]),
        "restated_on": str(r[2]), "reason": r[3],
        "old_value": float(r[4]), "new_value": float(r[5]),
        "delta": round(float(r[5]) - float(r[4]), 2),
    } for r in rows]
    """Freshness/restatement metadata for one metric (Phase 5 only)."""
    if not DATA_AS_OF:
        return {}
    out = {"data_as_of": DATA_AS_OF}
    r = restatements().get(name)
    if r:
        out["restatement"] = (
            f"{r['period']} restated on {r['restated_on']}: {r['reason']}. "
            f"Figures reported before {r['restated_on']} for {r['period']} "
            f"are stale."
        )
    m = catalog().metrics.get(name, {})
    if m.get("freshness"):
        out["freshness_contract"] = m["freshness"]
    return out


def _freshness_warning(metric_name: str) -> str | None:
    """Warn when the trailing period is incomplete relative to DATA_AS_OF.

    Only active on Phase 5 drift runs (GROUNDING_DATA_AS_OF set). Compares
    the latest event month in the metric's basis column against the
    contract's completeness window.
    """
    if not DATA_AS_OF:
        return None
    cat = catalog()
    m = cat.metrics.get(metric_name, {})
    f = m.get("freshness")
    if not f:
        return None
    model_name = m.get("model")
    if not model_name:  # derived: use first component's model
        dep = (m.get("depends_on") or [None])[0]
        model_name = cat.metrics.get(dep, {}).get("model") if dep else None
    if not model_name:
        return None
    table = cat.models[model_name]["source_table"]
    basis = f["basis"]
    try:
        import duckdb
        from datetime import date, timedelta

        asof = date.fromisoformat(DATA_AS_OF)
        max_date = duckdb.connect(str(DB_PATH), read_only=True).execute(
            f"SELECT MAX({basis}) FROM {table}").fetchone()[0]
        if max_date is None:
            return None
        month_end = date(max_date.year, max_date.month, 1) + timedelta(days=32)
        month_end = month_end.replace(day=1) - timedelta(days=1)
        final_on = month_end + timedelta(days=int(f["lag_days"]))
        if final_on > asof:
            return (
                f"{month_end.strftime('%Y-%m')} is preliminary: outside the "
                f"{f['lag_days']}-day completeness window "
                f"(final {final_on.isoformat()}). {f.get('note', '')}"
            )
    except Exception:
        return None
    return None


def catalog() -> SemanticCatalog:
    global _catalog
    if _catalog is None:
        _catalog = SemanticCatalog(CATALOG_PATH)
    return _catalog


def list_metrics() -> list[dict]:
    """Every governed metric: name, type, and business description."""
    out = []
    for name, m in catalog().metrics.items():
        out.append({
            "name": name,
            "type": m.get("type", "simple"),
            "description": m.get("description", ""),
        })
    return out


def describe_metric(name: str) -> dict:
    """Full governed definition of one metric: its model, measure,
    aggregation, row filter, and the dimensions available for cutting it."""
    cat = catalog()
    if name not in cat.metrics:
        return {"error": f"unknown metric '{name}'. Use list_metrics."}
    m = cat.metrics[name]
    if m.get("type") == "derived":
        return {
            "name": name,
            "type": "derived",
            "description": m.get("description", ""),
            "definition": f"{name} = {m['expr']}",
            "depends_on": m["depends_on"],
            "note": "Derived metrics are scalar-only in v1: no dimensional cuts.",
            **_freshness(name),
        }
    model = cat.models[m["model"]]
    measure = next(x for x in model["measures"] if x["name"] == m["measure"])
    return {
        "name": name,
        "type": "simple",
        "description": m.get("description", ""),
        "model": m["model"],
        "aggregation": f"{measure.get('agg', 'sum').upper()}({measure.get('expr', '*')})",
        "row_filter": m.get("filter") or "none — every row counts",
        "dimensions": [
            {"name": d["name"],
             "time_grain": d.get("time_granularity"),
             "description": d.get("description", "")}
            for d in model.get("dimensions", [])
        ],
        **_freshness(name),
    }


def query_metric(metric: str, dimensions: list[str] | None = None,
                 grain: str | None = None) -> dict:
    """Compile a governed metric to SQL and run it. Returns columns + rows.
    Time dimensions accept grain 'month' (DATE_TRUNC). Derived metrics accept
    no dimensions. Errors are returned as {"error": ...} so the agent can
    recover instead of crashing."""
    cat = catalog()
    try:
        sql = cat.compile(metric, dimensions, grain)
    except KeyError as e:
        return {"error": f"unknown metric or dimension: {e}. Use list_metrics / describe_metric."}
    except ValueError as e:
        return {"error": f"refused by the semantic layer: {e}"}
    try:
        rows = cat.run(DB_PATH, metric, dimensions, grain)
    except Exception as e:  # noqa: BLE001 — surface DB errors to the agent
        return {"error": f"query failed: {e}"}
    columns = list(dimensions or []) + [metric]
    result = {"columns": columns, "rows": [list(r) for r in rows], "sql": sql}
    warning = _freshness_warning(metric)
    if warning:
        result["freshness_warning"] = warning
    note = _restatement_note(metric, result)
    if note:
        result["restatement_note"] = note
    return result


def _restatement_note(metric_name: str, result: dict) -> str | None:
    """Inline restatement note for query_metric responses (Phase 5).

    Fires only when the restatement has actually happened as of DATA_AS_OF —
    on the June-30 snapshot the late batch hasn't landed yet, so there is
    nothing to disclose — and only when the query actually touches the
    restated period (or the period is ambiguous, e.g. scalar queries).
    The note names the period so the agent can judge relevance.
    """
    if not DATA_AS_OF:
        return None
    rn = restatements().get(metric_name)
    if not rn:
        return None
    try:
        from datetime import date
        if date.fromisoformat(DATA_AS_OF) < date.fromisoformat(rn["restated_on"]):
            return None
    except Exception:
        return None
    period = rn["period"]
    if not _touches_period(result, period):
        return None
    return (f"Restatement: {period} {metric_name} was restated on "
            f"{rn['restated_on']} ({rn['reason']}). Values shown are post-restatement.")


def _touches_period(result: dict, period: str) -> bool:
    """Does a query_metric result touch YYYY-MM? Scalar/ambiguous -> True."""
    cols = result.get("columns", []) or []
    rows = result.get("rows", []) or []
    if not rows:
        return True
    time_col = next((i for i, c in enumerate(cols)
                     if c in ("payment_date", "refund_date", "order_date",
                              "signup_date")), None)
    if time_col is None:
        return True  # scalar or non-time cut: period ambiguous
    for r in rows:
        v = r[time_col]
        key = v.strftime("%Y-%m") if hasattr(v, "strftime") else str(v)[:7]
        if key == period:
            return True
        # quarter aggregates ("Q1"/"Q2"): does the restated month fall in it?
        q_months = {"Q1": ("01", "02", "03"), "Q2": ("04", "05", "06"),
                    "Q3": ("07", "08", "09"), "Q4": ("10", "11", "12")}
        if key in q_months and period[5:7] in q_months[key]:
            return True
    return False


def get_period_status(metric_name: str, period: str) -> dict:
    """Governed period status: is a metric's value for a period preliminary
    or final, and was it restated? Backs the period_status virtual metric.
    period is YYYY-MM.
    """
    cat = catalog()
    m = cat.metrics.get(metric_name, {})
    try:
        from datetime import date, timedelta
        asof = date.fromisoformat(DATA_AS_OF) if DATA_AS_OF else date.today()
        month_end = date(int(period[:4]), int(period[5:7]), 1) + timedelta(days=32)
        month_end = month_end.replace(day=1) - timedelta(days=1)
        f = m.get("freshness")
        if f:
            final_on = month_end + timedelta(days=int(f["lag_days"]))
            status = "final" if asof >= final_on else "preliminary"
            detail = (f"final {final_on.isoformat()} "
                      f"({f['lag_days']}-day completeness window)")
        else:
            status, detail = "final", "no completeness window on this metric"
    except Exception:
        return {"error": f"bad period '{period}'; use YYYY-MM."}
    rn = restatements().get(metric_name) or {}
    restated = rn.get("period") == period
    try:
        from datetime import date as _d
        if restated and DATA_AS_OF and _d.fromisoformat(DATA_AS_OF) < _d.fromisoformat(rn["restated_on"]):
            restated = False
    except Exception:
        pass
    out = {"metric": metric_name, "period": period, "status": status,
           "restated": restated, "detail": detail}
    if restated:
        out["restatement"] = {"restated_on": rn["restated_on"], "reason": rn["reason"]}
    return out
