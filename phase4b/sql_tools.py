"""
The one tool of the Phase 4b no-layer agent: raw SQL against the warehouse.

Read-only DuckDB connection; only SELECT (or WITH...SELECT) statements are
executed. Anything else is refused — the agent is under test, not the
database.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import duckdb

BASE = Path(__file__).resolve().parent
# Phase 5 drift runs point this at a snapshot DB instead.
DB_PATH = Path(os.environ.get("GROUNDING_DB", BASE.parent / "warehouse.duckdb"))

_WRITE_PATTERNS = re.compile(
    r"\b(insert|update|delete|drop|create|alter|truncate|copy|attach|detach|"
    r"pragma|call|grant|revoke)\b", re.IGNORECASE)

_con = None


def _connect():
    global _con
    if _con is None:
        _con = duckdb.connect(str(DB_PATH), read_only=True)
    return _con


def run_sql(sql: str) -> dict:
    """Execute a read-only SELECT against the warehouse. Cap 200 rows."""
    sql = (sql or "").strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", sql):
        return {"error": "only SELECT / WITH...SELECT statements are allowed"}
    if _WRITE_PATTERNS.search(sql):
        return {"error": "write/DDL statements are not allowed"}
    try:
        con = _connect()
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(200)
        return {"columns": cols, "rows": [list(r) for r in rows],
                "row_count": len(rows), "truncated": len(rows) == 200}
    except Exception as e:  # noqa: BLE001 — report DB errors to the agent
        return {"error": str(e)[:400]}
