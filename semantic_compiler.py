"""
Minimal governed-metric compiler (night-one validation).

Takes versioned semantic YAML (semantic models + metrics) and compiles a
metric query to DuckDB SQL. This is the "serve" step of the loop: the agent
chooses a metric name from the catalog; the platform compiles the SQL.

Full v1 YAML lives in phase2/; this module is the compiler it will use.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import yaml

AGG_FNS = {"sum": "SUM", "count": "COUNT", "avg": "AVG", "min": "MIN", "max": "MAX"}


class SemanticCatalog:
    def __init__(self, yaml_path: str | Path):
        with open(yaml_path) as f:
            spec = yaml.safe_load(f)
        self.models = {m["name"]: m for m in spec.get("semantic_models", [])}
        self.metrics = {m["name"]: m for m in spec.get("metrics", [])}

    def compile(self, metric_name: str, dimensions: list[str] | None = None,
                grain: str | None = None) -> str:
        """Compile a metric to SQL. Raises KeyError on unknown metric/dimension."""
        metric = self.metrics[metric_name]
        model = self.models[metric["model"]]
        dimensions = dimensions or []

        # resolve the measure
        measure = next(m for m in model["measures"] if m["name"] == metric["measure"])
        agg = AGG_FNS[measure.get("agg", "sum").lower()]
        measure_expr = measure.get("expr", "*")
        select_agg = f"{agg}({measure_expr})" if measure_expr != "*" else f"{agg}(*)"

        # resolve dimensions (supports time grain via DATE_TRUNC)
        dim_exprs, group_keys = [], []
        for i, dname in enumerate(dimensions):
            dim = next(d for d in model["dimensions"] if d["name"] == dname)
            expr = dim["expr"]
            if grain and dim.get("time_granularity"):
                expr = f"DATE_TRUNC('{grain}', {expr})"
            alias = f"dim_{i}"
            dim_exprs.append(f"{expr} AS {alias}")
            group_keys.append(alias)

        select_clause = ", ".join(dim_exprs + [f"{select_agg} AS {metric_name}"])
        sql = f"SELECT {select_clause}\nFROM {model['source_table']}"
        if metric.get("filter"):
            sql += f"\nWHERE {metric['filter']}"
        if group_keys:
            sql += f"\nGROUP BY {', '.join(group_keys)}"
            sql += f"\nORDER BY {', '.join(group_keys)}"
        return sql + ";"

    def run(self, db_path: str | Path, metric_name: str,
            dimensions: list[str] | None = None, grain: str | None = None):
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            return con.execute(self.compile(metric_name, dimensions, grain)).fetchall()
        finally:
            con.close()
