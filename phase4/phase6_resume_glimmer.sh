#!/bin/bash
# Phase 6 Glimmer cells: 80 frozen questions (F001-F080) x 3 Glimmer cells
# (sql_atem bare, atem layer, atem gate). Runs on a RunPod pod with Ollama.
# Requires OLLAMA_BASE_URL set to the pod, e.g.
#   OLLAMA_BASE_URL=https://<pod>-11434.proxy.runpod.net
# Same resume pattern as phase6_resume.sh: re-runs only missing questions
# per cell, drops error-terminal traces, never truncates a finished cell.
# NO SCORING here: no peeking at frozen-set scores mid-run.
# Usage: OLLAMA_BASE_URL=<pod-url> bash phase4/phase6_resume_glimmer.sh
set -u
cd "$(dirname "$0")/.." || exit 1
if [ -z "${OLLAMA_BASE_URL:-}" ]; then
  echo "OLLAMA_BASE_URL is not set — no pod to run against. Exiting." >&2
  exit 1
fi
PY=.venv/bin/python
Q=phase3/frozen_questions.yml
A=phase3/frozen_answers.yml
ALL_IDS=$(python3 -c "print(','.join('F%03d' % i for i in range(1, 81)))")
LOG=phase4/phase6_resume_glimmer.log
: > "$LOG"

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

run_cell glimmer_bare phase4b/traces_frozen_glimmer_bare.jsonl $PY phase4b/run_harness_4b.py --backend sql_atem --questions $Q
run_cell glimmer_layer phase4/traces_frozen_glimmer_layer.jsonl $PY phase4/run_harness.py --backend atem --questions $Q
run_cell glimmer_gate phase4/traces_frozen_glimmer_gate.jsonl $PY phase4/run_harness.py --backend atem --gate both --questions $Q --answers $A
echo "PHASE 6 GLIMMER RESUME DONE" | tee -a "$LOG"
