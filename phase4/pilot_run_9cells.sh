#!/bin/bash
# Phase 5 priced pilot: 20 pilot questions (P001-P020) x 9 non-Glimmer cells.
# Glimmer cells (atem layer/gate, sql_atem bare) need a RunPod pod and run separately.
# Each cell writes its own trace file; all traces carry cost_usd.
# Wall-clock per cell is logged (Phase 5 needs real time per cell).
set -u
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
Q=phase3/pilot_questions.yml
LOG=phase4/pilot_run_9cells.log
: > "$LOG"
run() {
  local name="$1"; shift
  local start end
  start=$(date +%s)
  echo "=== $name started $(date -u +%H:%M:%S) ===" | tee -a "$LOG"
  "$@" >> "$LOG" 2>&1
  echo "exit=$? for: $name" | tee -a "$LOG"
  end=$(date +%s)
  echo "--- $name wall-clock: $((end - start))s ---" | tee -a "$LOG"
}
run sonnet_layer $PY phase4/run_harness.py --backend anthropic_conn --questions $Q --out traces_pilot_sonnet_layer.jsonl
run sonnet_gate $PY phase4/run_harness.py --backend anthropic_conn --gate both --questions $Q --out traces_pilot_sonnet_gate.jsonl
run sol_layer $PY phase4/run_harness.py --backend openai --questions $Q --out traces_pilot_sol_layer.jsonl
run sol_gate $PY phase4/run_harness.py --backend openai --gate both --questions $Q --out traces_pilot_sol_gate.jsonl
run ember_layer $PY phase4/run_harness.py --backend openrouter --questions $Q --out traces_pilot_ember_layer.jsonl
run ember_gate $PY phase4/run_harness.py --backend openrouter --gate both --questions $Q --out traces_pilot_ember_gate.jsonl
run sonnet_bare $PY phase4b/run_harness_4b.py --backend sql_anthropic --questions $Q --out traces_pilot_sonnet_bare.jsonl
run sol_bare $PY phase4b/run_harness_4b.py --backend sql_openai --questions $Q --out traces_pilot_sol_bare.jsonl
run ember_bare $PY phase4b/run_harness_4b.py --backend sql_openrouter --questions $Q --out traces_pilot_ember_bare.jsonl
echo "ALL 9 PILOT CELLS DONE" | tee -a "$LOG"
