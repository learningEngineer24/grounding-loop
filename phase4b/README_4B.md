# Phase 4b — the no-layer ablation

**Question:** how much of the harness result is the semantic layer, and how
much is the model? This phase runs the *same* model over the *same* 50
golden questions, but the agent writes its own SQL against the raw warehouse
instead of calling governed metrics.

**Design (the sharp version):** the agent receives the full schema DDL **and**
the complete `QUIRKS.md` as context — the same documented knowledge the
semantic layer encodes. So the experiment isolates *enforcement*: knowledge
the agent must remember to apply versus knowledge compiled into definitions
it cannot forget.

**Files:**
- `context.py` — schema DDL + QUIRKS.md assembled into the agent's context
- `sql_tools.py` — `run_sql`: read-only, SELECT-only DuckDB execution
- `agent_sql_gemini.py` — Gemini function-calling backend (same trace schema as phase4)
- `run_harness_4b.py` — 50-question runner
- `score_4b.py` — behavior / numeric / disclosure (metric selection n/a here)

**What it should show:** straightforward questions roughly even (LLMs write
decent SQL); the gap opens on traps and disclosure. The fan-out trap is the
one to watch — hand-written joins across payments → orders → customers will
double-count where the governed compiler refuses.

**Honest caveats:** prompt quality for the SQL agent matters (it got the same
care as the governed one); one model, so the finding is "the layer helps
*this* model," not a universal constant.
