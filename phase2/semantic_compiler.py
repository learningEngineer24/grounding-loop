"""
Governed-metric compiler (v2).

Takes versioned semantic YAML (semantic models + metrics) and compiles a
metric query to DuckDB SQL. This is the "serve" step of the loop: the agent
chooses a metric name from the catalog; the platform compiles the SQL.

v1: single-table metrics.
v2: declared joins. Dimensions may live on joined models or dimension tables;
    the compiler resolves the shortest join path and REFUSES paths that would
    fan out the metric's grain (one->many from the querying model) instead of
    silently double-counting.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

import duckdb
import yaml

AGG_FNS = {"sum": "SUM", "count": "COUNT", "avg": "AVG", "min": "MIN", "max": "MAX"}
REVERSE_REL = {
    "many_to_one": "one_to_many",
    "one_to_many": "many_to_one",
    "one_to_one": "one_to_one",
}
# Hop relationships (from the querying model's perspective) that cannot
# duplicate its rows. Anything else fans out and is refused.
SAFE_HOPS = {"many_to_one", "one_to_one"}


class SemanticCatalog:
    def __init__(self, yaml_path: str | Path):
        with open(yaml_path) as f:
            spec = yaml.safe_load(f)
        self.version = spec.get("version", 1)
        self.models = {m["name"]: m for m in spec.get("semantic_models", [])}
        self.dim_tables = {t["name"]: t for t in spec.get("dimension_tables", [])}
        self.metrics = {m["name"]: m for m in spec.get("metrics", [])}
        self._graph = self._build_join_graph()

    # ---- join graph ----
    def _node(self, name: str) -> dict:
        if name in self.models:
            return self.models[name]
        return self.dim_tables[name]

    def _build_join_graph(self) -> dict:
        # adjacency: node -> [(neighbor, left_on, right_on, rel_from_here)]
        # left_on belongs to the node the edge leaves from. Reverse edges are
        # inferred so each join is declared once.
        graph: dict = {}
        for n in list(self.models) + list(self.dim_tables):
            graph.setdefault(n, [])
        for mname, m in self.models.items():
            for j in m.get("joins", []):
                to, rel = j["to"], j["relationship"]
                if to not in graph:
                    raise KeyError(f"model '{mname}' joins unknown node '{to}'")
                graph[mname].append((to, j["left_on"], j["right_on"], rel))
                graph[to].append(
                    (mname, j["right_on"], j["left_on"], REVERSE_REL[rel]))
        return graph

    def _resolve_dimension(self, base_model: str, dname: str):
        """Find the provider node for dimension `dname` and the join path to it.

        Returns (provider_node, dim_spec, path); path is a list of
        (frm, to, left_on, right_on, rel_from_frm) hops from base_model.
        Raises KeyError if the dimension is unknown, ValueError if every path
        would fan out the base model's grain.
        """
        base = self.models[base_model]
        for dim in base.get("dimensions", []):
            if dim["name"] == dname:
                return base_model, dim, []
        # BFS for the nearest provider across the join graph.
        seen = {base_model}
        dq = deque([(base_model, [])])
        while dq:
            node, path = dq.popleft()
            for (nbr, left_on, right_on, rel) in self._graph.get(node, []):
                if nbr in seen:
                    continue
                seen.add(nbr)
                new_path = path + [(node, nbr, left_on, right_on, rel)]
                for dim in self._node(nbr).get("dimensions", []):
                    if dim["name"] == dname:
                        for (_, _, _, _, r) in new_path:
                            if r not in SAFE_HOPS:
                                raise ValueError(
                                    f"refused: dimension '{dname}' from model "
                                    f"'{base_model}' would fan out via a "
                                    f"one->many hop")
                        return nbr, dim, new_path
                dq.append((nbr, new_path))
        raise KeyError(f"unknown dimension '{dname}' for model '{base_model}'")

    def compile(self, metric_name: str, dimensions: list[str] | None = None,
                grain: str | None = None) -> str:
        """Compile a metric to SQL. Raises KeyError on unknown metric/dimension,
        ValueError on fan-out joins."""
        metric = self.metrics[metric_name]
        if metric.get("type") == "derived":
            return self._compile_derived(metric_name, metric)
        base = metric["model"]
        model = self.models[base]
        dimensions = dimensions or []

        # Turn 5: enforce the metric's canonical time attribution. A metric
        # whose definition names a canonical time_dimension refuses monthly
        # (or other time) breakdowns on any OTHER time dimension of its base
        # model — the old attribution is superseded, not an alternative.
        # Mirrors the fan-out guard: refuse rather than silently answer the
        # wrong question. Metrics without an attribution block are unaffected.
        canonical = (metric.get("attribution") or {}).get("time_dimension")
        if canonical:
            for dname in dimensions:
                provider, dim, _path = self._resolve_dimension(base, dname)
                if (provider == base and dim.get("time_granularity")
                        and dname != canonical):
                    prev = (metric["attribution"].get("previous")
                            or "a previous attribution")
                    raise ValueError(
                        f"refused: dimension '{dname}' is superseded for "
                        f"metric '{metric_name}' ({prev}). Monthly "
                        f"attribution is now '{canonical}'. Re-query with "
                        f"'{canonical}'.")

        # resolve the measure
        measure = next(m for m in model["measures"] if m["name"] == metric["measure"])
        agg = AGG_FNS[measure.get("agg", "sum").lower()]
        measure_expr = measure.get("expr", "*")
        select_agg = f"{agg}({measure_expr})" if measure_expr != "*" else f"{agg}(*)"

        # resolve dimensions (supports time grain via DATE_TRUNC, and
        # cross-model dimensions via declared joins)
        dim_exprs, group_keys = [], []
        join_clauses, seen_joins = [], set()
        for i, dname in enumerate(dimensions):
            provider, dim, path = self._resolve_dimension(base, dname)
            for (frm, to, left_on, right_on, _rel) in path:
                if (frm, to) not in seen_joins:
                    seen_joins.add((frm, to))
                    join_clauses.append(
                        f"JOIN {self._node(to)['source_table']} AS {to} "
                        f"ON {frm}.{left_on} = {to}.{right_on}")
            expr = dim["expr"]
            if "." not in expr:
                expr = f"{provider}.{expr}"
            if grain and dim.get("time_granularity"):
                expr = f"DATE_TRUNC('{grain}', {expr})"
            alias = f"dim_{i}"
            dim_exprs.append(f"{expr} AS {alias}")
            group_keys.append(alias)

        select_clause = ", ".join(dim_exprs + [f"{select_agg} AS {metric_name}"])
        sql = f"SELECT {select_clause}\nFROM {model['source_table']} AS {base}"
        for jc in join_clauses:
            sql += f"\n{jc}"
        if metric.get("filter"):
            sql += f"\nWHERE {metric['filter']}"
        if group_keys:
            sql += f"\nGROUP BY {', '.join(group_keys)}"
            sql += f"\nORDER BY {', '.join(group_keys)}"
        return sql + ";"

    def _compile_derived(self, metric_name: str, metric: dict) -> str:
        deps = metric["depends_on"]
        ctes = []
        for dep in deps:
            dep_sql = self.compile(dep).rstrip().rstrip(";")
            ctes.append(f"{dep} AS (\n{dep_sql}\n)")
        expr = metric["expr"]
        for dep in sorted(deps, key=len, reverse=True):
            expr = expr.replace(dep, f"(SELECT {dep} FROM {dep})")
        return ("WITH " + ",\n".join(ctes) +
                f"\nSELECT {expr} AS {metric_name};")

    def run(self, db_path: str | Path, metric_name: str,
            dimensions: list[str] | None = None, grain: str | None = None):
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            return con.execute(self.compile(metric_name, dimensions, grain)).fetchall()
        finally:
            con.close()
