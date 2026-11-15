#!/bin/bash
# Phase 4 dry run: 5 golden questions (Q001-Q005) x 9 non-Glimmer cells.
# Glimmer cells (atem layer/gate, sql_atem bare) need a RunPod pod and run separately.
# Each cell writes its own trace file; all traces carry cost_usd.
set -u
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
IDS=Q001,Q002,Q003,Q004,Q005
LOG=phase4/dry_run_9cells.log
: > "$LOG"
run() {
  echo "=== $* ===" | tee -a "$LOG"
  "$@" >> "$LOG" 2>&1
  echo "exit=$? for: $*" | tee -a "$LOG"
}
run $PY phase4/run_harness.py --backend anthropic_conn --ids $IDS --out traces_dry_sonnet_layer.jsonl
run $PY phase4/run_harness.py --backend anthropic_conn --gate both --ids $IDS --out traces_dry_sonnet_gate.jsonl
run $PY phase4/run_harness.py --backend openai --ids $IDS --out traces_dry_sol_layer.jsonl
run $PY phase4/run_harness.py --backend openai --gate both --ids $IDS --out traces_dry_sol_gate.jsonl
run $PY phase4/run_harness.py --backend openrouter --ids $IDS --out traces_dry_ember_layer.jsonl
run $PY phase4/run_harness.py --backend openrouter --gate both --ids $IDS --out traces_dry_ember_gate.jsonl
run $PY phase4b/run_harness_4b.py --backend sql_anthropic --ids $IDS --out traces_dry_sonnet_bare.jsonl
run $PY phase4b/run_harness_4b.py --backend sql_openai --ids $IDS --out traces_dry_sol_bare.jsonl
run $PY phase4b/run_harness_4b.py --backend sql_openrouter --ids $IDS --out traces_dry_ember_bare.jsonl
echo "ALL 9 CELLS DONE" | tee -a "$LOG"
