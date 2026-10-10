# The Grounding Loop

A working build of the feedback loop from [Data Engineering in the Agent
Era](https://neboiwenofu.com/writings/data-engineering-agent-era.html):
a governed semantic layer over a synthetic DuckDB warehouse, a golden
dataset of trap questions, an agent harness that scores whether the layer
keeps answers honest, and drift machinery that catches the layer going
stale. Small enough to hold in your head, real enough to produce genuine
failures.

Two write-ups tell the story: [Part 1: The Grounding Loop](WRITEUP_DRAFT_PART1.md)
(phases 1–4, the measurement story) and [Part 2: Managing Drift](WRITEUP_DRAFT_PART2.md)
(phase 5, the operations story). Both are drafts under review.

## Results at a glance

- **The layer's value, measured:** the same model answering the same 50
  questions scores +12 points of behavior and +11 of numeric accuracy with
  governed metrics vs. writing its own SQL, even when the no-layer agent
  gets the full schema and documented quirks as context. Enforcement beats
  documentation.
- **The $0 floor:** a deterministic baseline (no LLM, keyword-to-metric
  matching) hits 84% behavior / 81% numeric. Anything a model scores above
  that is the marginal value of the model. Its value is judgment: 75% on
  ambiguous questions vs. the baseline's 12%.
- **Disclosure under drift:** when late-arriving payments restated June
  revenue (+$167,724), agent-volunteered revision disclosure went 4% → 34%
  with a restatement log, then to 66% (audit-corrected) with a deterministic
  answer-level disclosure layer. No measurable behavior cost.
- **Meaning drift:** when finance redefined `total_refunds` attribution
  (no rows changed), the canary caught 8 changed answers but the agent used
  the new meaning 0/8 times despite reading the definition. The fix was
  platform enforcement: the compiler now refuses superseded time
  dimensions, the way the fan-out guard refuses bad joins.
- **Cost:** about $11 of a $20 Anthropic budget across all measured runs.

## Layout

- `phase1/` — deterministic warehouse fixture (500 customers, 3,000
  payments, 140 refunds) plus `QUIRKS.md`: seven documented data quirks that
  seed the trap questions. Start with `phase1/DATA_MODEL.md`.
- `phase2/` — hand-rolled YAML→SQL semantic compiler (`semantic_compiler.py`),
  governed metric catalogs (`semantics_v1.yml`, `semantics_v2.yml`,
  `semantics_v3.yml`), `CHANGELOG.md`, and validators (16/16 on v1, 24/24
  on v2 including fan-out refusals).
- `phase3/` — golden dataset: `golden_questions.yml` (167 questions, 166 scored post-audit:
  54 straightforward / 72 trap / 41 ambiguous), `compute_answers.py` (locks
  expected answers *through the compiler*, never hand-typed),
  `golden_answers.yml`, `validate_golden.py`.
- `phase4/` — agent harness: read-only metric tools, terminal actions
  (`submit_answer` / `ask_clarify` / `refuse`), four-dimension scorer
  (behavior, numeric, disclosure, metric selection). Backends: deterministic
  baseline, Anthropic (Haiku). See `phase4/HARNESS.md`.
- `phase4b/` — no-layer ablation: the same model writes its own SELECT-only
  SQL against the raw warehouse. Measures enforcement, not knowledge.
- `phase5/` — drift machinery: snapshot simulator (`simulate_drift.py`),
  golden-set canary (`canary.py`), restatement log (`restatements.json`,
  `list_restatements` tool), freshness contracts, definition-change log
  (`definition_changes.json`), expanded exam, and all run traces
  (`traces_*.jsonl`) and reports.
- `WRITEUP_DRAFT_PART1.md`, `WRITEUP_DRAFT_PART2.md` — the two project
  write-ups (drafts).

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
- **Phase 2 (Oct 8):** `semantics_v1.yml` (4 models, 16 metrics), validated
  16/16 against hand-written SQL. **v2** adds declared joins from the ER
  diagram; the compiler resolves multi-hop paths and *refuses* fan-out
  (one→many) instead of silently double-counting. 24/24 checks.
- **Phase 3 (Oct 8–9):** golden dataset, 50 questions keyed to semantics v1.
  Every expected value computed through the compiler; traps encode the naive
  answer and why it's wrong. Later audited and expanded to 167 questions (166 scored;
  54 straightforward / 72 trap / 41 ambiguous); seven golden corrections,
  delta-answer support in `compute_answers.py`.
- **Phase 4 (Oct 9):** agent harness + deterministic baseline (84% behavior,
  81% numeric, $0) + Haiku governed run (82% / 71%) + no-layer ablation
  (70% / 60%). The +12/+11 delta is the enforcement value of compiled
  definitions over documented knowledge.
- **Phase 5, turn 1 (Oct 9):** drift exercise. Thirty late-arriving payments
  restate June revenue +$167,724. Freshness contracts (prevent), golden-set
  canary (detect), restatement log + `list_restatements` (communicate).
  Three runs each: disclosure 4% → 34%, no behavior cost.
- **Phase 5, turn 2 (Oct 9):** targeted inline restatement notes (fire only
  when the query touches the restated period) + `period_status` virtual
  metric. Exam grows 127 → 167 on drift findings. Revision disclosure
  34% → 52% on identical questions, behavior 73% → 76%: push safety-critical
  context, pull the rest.
- **Phase 5, turn 3 (Oct 9):** deterministic answer-level disclosure. The
  serving layer appends a one-line governance note to any answer whose
  queries touched a restated period. Live full-exam run: 62% revision
  disclosure (66% audit-corrected). Distinguish agent-volunteered disclosure
  (capability) from system-guaranteed disclosure (safety).
- **Phase 5, turn 4 (Oct 9):** meaning drift. Semantics v3 redefines
  `total_refunds` monthly attribution (refund month → original payment
  month); zero rows change. Canary catches 8 changed answers; the agent uses
  the new meaning 0/8 despite reading the definition. Metadata visibility is
  not enforcement.
- **Phase 5, turn 5 (Oct 9–10):** platform enforcement. The compiler refuses
  queries on superseded time dimensions with a redirect to the canonical
  one. Re-run: 5/8 changed questions return exactly the v3 numbers, one
  asks a thoughtful clarify. Governance is a platform property, not an
  agent capability to be prompted into existence.
