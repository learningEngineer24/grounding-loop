#!/bin/bash
# One-shot: retry the Gemini harness run (quota may have reset past midnight).
# Tries gemini-3.8-flash first, falls back to gemini-flash-latest.
cd ~/workspace/grounding-loop/phase4
V=.venv/bin/python

try_model() {
  local model="$1"
  $V run_harness.py --backend gemini --model "$model" --limit 3 \
      --out traces_gemini_retry.jsonl > retry_smoke.log 2>&1
  $V -c "
import json
traces = [json.loads(l) for l in open('traces_gemini_retry.jsonl')]
errs = [t['id'] for t in traces if t['terminal']['action'] in ('error', 'no_decision')]
print('smoke errors:', errs if errs else 'none')
raise SystemExit(1 if errs else 0)
" > retry_smoke_check.log 2>&1 && echo "$model"
}

MODEL="$(try_model gemini-3.8-flash)" \
  || MODEL="$(try_model gemini-flash-latest)" \
  || { echo "SMOKE FAILED on both models - quota or API still broken; see retry_smoke.log"; exit 0; }

echo "smoke passed on $MODEL - running full 50"
$V run_harness.py --backend gemini --model "$MODEL" \
    --out traces_gemini.jsonl > retry_full.log 2>&1
$V score.py --traces traces_gemini.jsonl > gemini_report.txt 2>&1
head -12 gemini_report.txt
