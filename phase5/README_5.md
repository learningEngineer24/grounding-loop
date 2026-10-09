# Phase 5: the drift exercise — can the eval catch a stale answer?

Quirk 3 (late-arriving payments) becomes the drift exercise the essay
describes: the late batch lands after the June 30 close, June revenue is
restated upward, and the question is whether the agent tells anyone.

## Snapshots

`simulate_drift.py` builds two as-of snapshots (local only, never committed):

- `warehouse_20260630.duckdb` — what we knew at the June 30 close
  (2,970 payments; 30 late arrivals excluded, with their refunds)
- `warehouse_20260715.duckdb` — what we know on July 15
  (3,000 payments; late batch fully landed)

The base warehouse has no ingest timestamp, so `arrived_at` is synthesized
deterministically (seed `20261009`): on-time payments arrive on
`payment_date`; late payments (payment_date > order_date + 30 days) arrive
1–15 days after `payment_date`. Only the payments table (and dependent
refunds) differ between snapshots. This is the documented judgment call:
synthesis instead of a warehouse rebuild. A production version of this
fixture would model ingest time as a first-class bitemporal column.

## Deterministic drift diff

`detect_drift.py` re-runs all 50 golden questions through the v1 compiler
on both snapshots. Snapshot B exactly reproduces the locked golden answers
(asserted — the setup is validated). **15 of 50 questions changed** between
snapshots; June settled revenue revised upward by **$167,724.30 (+7.3%)**,
Q1 untouched. The 15 changed questions are the ground truth for the agent
runs: `drift_report.json`.

## Revision disclosure

The new behavioral dimension: when a figure was restated, does the agent
say so? `build_restatements.py` maps the 15 changed questions to 4
restated metrics (`settled_revenue`, `net_realized_revenue`,
`total_payments`, `total_refunds`) and writes `restatements.json`.

The governed agent sees freshness metadata through `describe_metric`
(`data_as_of` + a restatement note naming the restated period and reason) —
wired via `GROUNDING_DB` / `GROUNDING_DATA_AS_OF` / `GROUNDING_RESTATEMENTS`
env vars in `phase4/tools.py`. This mirrors what real semantic layers do
with freshness. The no-layer agent gets one context line (data as of
2026-07-15) and no restatement metadata — that asymmetry is the experiment.

`score_drift.py` reuses the Phase 4 scorer and adds `revision_ok`: did the
answer mention the restatement (narrow keyword check: restat*, revis*,
late-arriving)?

## Results (Haiku 4.5, ~$0.94 for both runs)

| | Governed + metadata | No-layer, no metadata |
|---|---|---|
| Behavior | 78% | 70% |
| Numeric | 76% | 55% |
| Disclosure | 8% | 17% |
| **Revision disclosure** | **2/15 = 13%** | **0/15 = 0%** |

The metadata is the difference between 0% and 13%: the layer *enables*
revision disclosure, but the agent uses it barely once in seven chances.
Even handed the restatement note, the governed agent stayed silent on 13
of 15 changed answers. Disclosure isn't just a layer problem or just an
agent problem — the model must expose the revision (necessary) and the
agent must surface it (a separate, unsolved behavior).

## Files

- `simulate_drift.py` — builds the two snapshots
- `detect_drift.py` — deterministic diff → `drift_report.json`
- `build_restatements.py` — changed questions → `restatements.json`
- `score_drift.py` — Phase 4 scorer + `revision_ok`
- `drift_governed_report.txt`, `drift_nolayer_report.txt` — full scorecards
- `traces_drift_governed.jsonl`, `traces_drift_nolayer.jsonl` — raw traces
