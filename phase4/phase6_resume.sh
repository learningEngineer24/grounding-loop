#!/bin/bash
# Phase 6 resume: after a VM replacement kills the full-grid run mid-cell.
# Re-runs only missing questions per cell and appends — never truncates a
# finished cell. Error-terminal traces (transport failures, not model
# results) are dropped and re-run. A crashed cell is re-run whole only
# if the harness itself is broken; otherwise this fills the gaps.
# NO SCORING here: no peeking at frozen-set scores mid-run.
# Usage: bash phase4/phase6_resume.sh
set -u
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
Q=phase3/frozen_questions.yml
A=phase3/frozen_answers.yml
ALL_IDS=$(python3 -c "print(','.join('F%03d' % i for i in range(1, 81)))")
LOG=phase4/phase6_resume.log
: > "$LOG"

# missing_ids <tracefile>: print comma-separated ids not yet answered, after
# dropping error-terminal traces from the file.
missing_ids() {
  local f="$1"
  if [ ! -f "$f" ]; then echo "$ALL_IDS"; return; fi
  $PY - "$f" <<'PYEOF'
import json, sys
f = sys.argv[1]
kept, done = [], set()
try:
    lines = open(f).read().splitlines()
except FileNotFoundError:
    lines = []
for l in lines:
    if not l.strip():
        continue
    t = json.loads(l)
    if (t.get("terminal") or {}).get("action") == "error":
        continue  # transport failure, not a model result: drop and re-run
    kept.append(l)
    done.add(t["id"])
open(f, "w").write("\n".join(kept) + ("\n" if kept else ""))
all_ids = ["F%03d" % i for i in range(1, 81)]
print(",".join(i for i in all_ids if i not in done))
PYEOF
}

run_cell() {
  local name="$1" trace="$2"; shift 2
  local missing start end tmp
  missing=$(missing_ids "$trace")
  if [ -z "$missing" ]; then
    echo "=== $name: already complete, skipping ===" | tee -a "$LOG"
    return
  fi
  tmp="${trace}.tmp"
  start=$(date +%s)
  echo "=== $name: running missing [$missing] started $(date -u +%H:%M:%S) ===" | tee -a "$LOG"
  "$@" --ids "$missing" --out "$(basename "$tmp")" >> "$LOG" 2>&1
  echo "exit=$? for: $name" | tee -a "$LOG"
  if [ -f "$tmp" ]; then cat "$tmp" >> "$trace"; rm -f "$tmp"; fi
  end=$(date +%s)
  echo "--- $name wall-clock: $((end - start))s; now $(wc -l < "$trace")/80 lines ---" | tee -a "$LOG"
}

run_cell sonnet_bare phase4b/traces_frozen_sonnet_bare.jsonl $PY phase4b/run_harness_4b.py --backend sql_anthropic --questions $Q
run_cell sol_bare phase4b/traces_frozen_sol_bare.jsonl $PY phase4b/run_harness_4b.py --backend sql_openai --questions $Q
run_cell ember_bare phase4b/traces_frozen_ember_bare.jsonl $PY phase4b/run_harness_4b.py --backend sql_openrouter --questions $Q
run_cell sonnet_layer phase4/traces_frozen_sonnet_layer.jsonl $PY phase4/run_harness.py --backend anthropic_conn --questions $Q
run_cell sol_layer phase4/traces_frozen_sol_layer.jsonl $PY phase4/run_harness.py --backend openai --questions $Q
run_cell ember_layer phase4/traces_frozen_ember_layer.jsonl $PY phase4/run_harness.py --backend openrouter --questions $Q
run_cell sonnet_gate phase4/traces_frozen_sonnet_gate.jsonl $PY phase4/run_harness.py --backend anthropic_conn --gate both --questions $Q --answers $A
run_cell sol_gate phase4/traces_frozen_sol_gate.jsonl $PY phase4/run_harness.py --backend openai --gate both --questions $Q --answers $A
run_cell ember_gate phase4/traces_frozen_ember_gate.jsonl $PY phase4/run_harness.py --backend openrouter --gate both --questions $Q --answers $A
echo "PHASE 6 RESUME DONE" | tee -a "$LOG"
