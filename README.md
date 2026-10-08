# The Grounding Loop

Practice build of the essay's feedback loop: governed semantic metrics + evals
on a toy DuckDB warehouse, proving an agent's answers verifiable and catching
drift before a board deck goes wrong. Summit material for Nov 2.

Full scope: `../goals/grow-professional-skillset/files/grounding-loop-project-scope.md`
(this is a working copy; scope is the source of truth).

## Layout
- `phase1/build_warehouse.py` — deterministic fixture builder (seed `20261007`)
- `warehouse.duckdb` — the fixture (gitignored in a real repo; local only)
- `QUIRKS.md` — deliberate data quirks; raw material for trap questions
- `phase2/semantic_compiler.py` — governed-metric YAML → DuckDB SQL compiler
- `phase2/semantics_v0.yml` — validation slice (one model, two metrics)

## Decision record — why hand-rolled, not MetricFlow (Oct 8, 2026)

Night-one risk was MetricFlow's DuckDB support. Findings:
- `dbt-metricflow` on PyPI is archived at 0.15.0 (no Python 3.12 wheels).
- The current `metricflow` package (0.213.0) ships **no CLI and no DuckDB
  SQL client** — `SqlClient` is a protocol you'd implement yourself.
- `dbt-core` 1.12 no longer ships a `sl` command; querying now wants dbt Cloud.

So "real" MetricFlow against local DuckDB means either a managed service or
writing the adapter ourselves — both wrong for a lab whose point is the
define → serve → evaluate → drift → feedback loop, not dbt's brand. The
hand-rolled compiler (`phase2/semantic_compiler.py`) implements exactly the
contract the eval harness needs: versioned YAML in, SQL out, agent never
touches raw SQL. Validated: compiled `settled_revenue` matches direct SQL to
the cent; time-grain (`DATE_TRUNC`) and dimensional grouping verified.

## Phase log
- **Phase 1 (Oct 8):** warehouse + quirks + compiler validation. Done.
- **Phase 2 (next):** full `semantics_v1.yml` — all models, governed business
  logic (net revenue ex-failed/refunded/chargeback, active customer ex-trial,
  churn as derived metric). Query until numbers are unassailable.
