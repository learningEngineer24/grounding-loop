# Phase 4 — Agent Harness

Runs an LLM agent against the 50-question golden set (`phase3/`) and scores
it on four dimensions: behavior, numeric accuracy, disclosure, metric selection.

## Architecture

```
phase3/golden_questions.yml ──question text only──▶ agent.py ──tools──▶ tools.py ──▶ semantic_compiler (v1) ──▶ warehouse.duckdb
                                                        │                       ▲
                                                        │ traces.jsonl          │ the agent NEVER writes SQL
                                                        ▼                       │ and NEVER sees golden answers
                                                    run_harness.py ─────────────┘
                                                        │
                                                        ▼
                                                    score.py ◀── phase3/golden_answers.yml (locked)
                                                        │
                                                        ▼
                                              console report + scores.json
```

## The agent under test (`agent.py`)

A tool-using LLM (Anthropic API, model configurable, default
`claude-sonnet-4-5`). System prompt encodes the governed-layer discipline:

- never write SQL; every number comes from `query_metric`
- metric definitions are authoritative (read `describe_metric` before trusting a name)
- names are treacherous — "revenue" is ambiguous across four governed metrics
- ambiguous question → `ask_clarify`; forecast/unanswerable → `refuse`
- trap-adjacent answers carry a one-sentence disclosure

Tools: `list_metrics`, `describe_metric`, `query_metric` (all read-only,
backed by `SemanticCatalog` on `semantics_v1.yml`), plus three terminal
actions: `submit_answer(answer_text, metric_used)`, `ask_clarify(question)`,
`refuse(reason)`. Max 10 tool turns per question.

## Scoring (`score.py`)

| Dimension | What it checks |
|---|---|
| behavior | terminal action vs `expected_behavior` (answer / clarify / refuse) |
| numeric | numbers reported in `answer_text` vs locked golden values (money ±$0.02, counts exact, rates ±1e-4; "5.2%" counts as 0.052) |
| disclosure | 12 traps: answer text contains the disclosure keywords from `golden_questions.yml` |
| metric | the agent queried the governed metric(s) the golden set names |

Report: overall + per-category accuracy, failure list with trace excerpts,
full per-question results in `scores.json`.

## Backends

- `anthropic` (default model `claude-sonnet-4-5`) — needs `ANTHROPIC_API_KEY`.
  Out-of-pocket; kept for the Anthropic-vs-Gemini comparison run.
- `gemini` (default model `gemini-3.8-flash`) — free tier, authenticated through
  the stored `custom.gemini` connector via the authd surrogate exchange
  (`~/workspace/skills/gemini/`). No key in env, no key in code.

The system prompt, tools, and terminal actions are identical across backends;
`agent_gemini.py` mirrors `agent.py`'s trace schema exactly, so score deltas
measure the model, not the harness.

## Running it

```bash
cd phase4
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# Gemini (free tier, via stored connector)
.venv/bin/python run_harness.py --backend gemini --out traces_gemini.jsonl

# Anthropic (paid)
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/python run_harness.py --backend anthropic --out traces_anthropic.jsonl

# smoke test, then score
.venv/bin/python run_harness.py --backend gemini --limit 3
.venv/bin/python score.py --traces traces_gemini.jsonl
```

## Files

- `tools.py` — agent-facing wrappers around the v1 compiler (no SQL, no answers leak)
- `agent.py` — the LLM agent loop with terminal actions
- `run_harness.py` — iterates the golden set, writes `traces.jsonl`
- `score.py` — scores traces against locked answers
- `requirements.txt` — anthropic, pyyaml, duckdb
