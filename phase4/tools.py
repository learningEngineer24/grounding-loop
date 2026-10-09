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
    return out


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
    return {"columns": columns, "rows": [list(r) for r in rows], "sql": sql}
