# Managing Drift: Keeping a Semantic Layer Honest as Data Moves

**Status:** Draft for review — October 9, 2026
**Intended:** Projects page post (sequel to The Grounding Loop)
**Repo:** https://github.com/learningEngineer24/grounding-loop
**Prequel:** [The Grounding Loop](WRITEUP_DRAFT_PART1.md) — the measurement story.

> Part 1 built the apparatus: a governed semantic layer over a synthetic
> warehouse, a golden set of trap questions, and a harness that scores
> whether an AI agent's answers stay honest. This is the operations sequel:
> what happens when the world moves underneath it — and the machinery that
> keeps the answers trustworthy anyway.

---

## The drift event

The most ordinary event in data engineering: payments arrived late. Thirty
of them landed after the June 30 close, 1–15 days after their payment dates
— the batch-processing lag documented as Quirk 3. Two snapshots tell the
story:

| Snapshot | As of | Payments |
|---|---|---|
| A — June 30 close | 2026-06-30 | 2,970 |
| B — July 15 | 2026-07-15 | 3,000 |

June settled revenue restated from $2,282,054 to $2,449,779 — up $167,724,
or 7.3%. Total refunds restated +$3,358; net realized revenue +$164,366.
Twenty-nine of the golden questions changed answers; Q1 was untouched. A
deterministic diff caught every stale answer. That part was easy.

The harder question: does the *agent* tell the user? With restatement
metadata visible through `describe_metric`, the governed agent disclosed
the revision 2 times out of 15 changed answers (13%). The no-layer agent,
with no metadata at all, disclosed 0. The layer enabled revision
disclosure; the agent barely used it. A trace decomposition showed why:
on 6 of the 15, the agent never called `describe_metric` and never saw the
note; on 7 it saw the note and stayed silent anyway.

## Three practices: prevent, detect, communicate

The industry has settled patterns for this — watermarks with measured
lookback windows, freshness SLOs in data contracts, observability across
freshness/volume/schema/distribution/lineage, restatable history. The
project maps them onto the agent-serving layer as three builds:

**Prevent — freshness contracts in the semantic YAML.** Four metrics
(`settled_revenue`, `total_payments`, `total_refunds`,
`net_realized_revenue`) carry a 15-day completeness window. While the
trailing period is inside the window, `query_metric` answers with an inline
warning: June is preliminary on June 30, final on July 15. The contract
lives with the definition, not in a wiki — so every consumer inherits it.

**Detect — the golden set as a drift canary.** Warehouse observability says
the *data* changed; the canary says which *stakeholder-facing answers*
changed because of it. `phase5/canary.py` re-runs every golden question
against a target database and diffs against the locked answers: exit 0 for
CLEAN, 1 for STALE. On the June snapshot: 15 of 50 stale (29 of 127 after
the expansion below). That distinction — data changed vs. answers changed —
is the canary's whole value.

**Communicate — the restatement log as a first-class entity.** A
`restatement_log` table records every revision: metric, period, restated
date, reason, old value, new value, delta. A `list_restatements` tool
exposes it to the agent, alongside a prompt rule: when freshness metadata
flags a restated period, check the log and say so in one sentence.

## What changed

Re-running the drift experiment with all three practices in place:

| | Behavior | Numeric | Revision disclosure |
|---|---|---|---|
| Metadata only (v1) | 75% | 71% | 2/45 = 4% |
| + restatement log, tool, rule (v2) | 72% | 66% | 15/45 = 33% |

The v2 agent hit exactly 5/15 on revision disclosure in all three runs —
the gain is stable, not a lucky draw. And the behavior difference (75% vs
72%) sits inside run-to-run noise: the drift machinery buys the disclosure
gain at no measurable accuracy cost.

Part 1 ended with disclosure as an unsolved problem twice over — a weak
solution and a weak yardstick. This is the solution half answering back:
give the agent a first-class restatement record instead of a metadata
footnote, and revision disclosure goes from 4% to 34% (10/29 on the
expanded set below). The yardstick half is still open — see below.

## Push vs pull: what the agent can be trusted with

The three builds trace a small arc that rederives an industry lesson. The
first attempt pushed restatement metadata into every `describe_metric`
response: 13% revision disclosure. The second added pull tools — a
restatement log the agent could check when it suspected something: 33%.
The third pushed harder, inlining the restatement note into every
`query_metric` response whether the query needed it or not: disclosure rose
to 61%, but behavior fell from 86% to 79% on identical questions. The
agent was tripping over caveats attached to questions they didn't apply to.

This is the context-engineering guidance the industry has converged on:
pull, don't push. Keep the prompt lean; give the agent cheap tools to fetch
context when it needs it; reserve pushing for what's safety-critical. Our
fix was to target the inline note — it now fires only when the query
actually touches the restated period — and to collapse the two overlapping
prompt rules into one. Fewer, sharper instructions beat more.

## The architectural fix: deterministic disclosure

There is a deeper resolution, and it's the core recommendation to come out
of this work. Our eval measures whether the *agent* volunteers a
disclosure: did it notice the restatement and mention it? But what protects
a decision is different: did the *user* get told? Those are two separate
properties, and only the second one is load-bearing.

Known-knowns — a restated period, a preliminary status — should not depend
on the agent's discretion at all. The serving layer already injects
`freshness_warning` into query results deterministically; the platform
decides, not the model. The recommendation is to extend that pattern to the
answer level: when the agent submits an answer whose queries touched a
restated period, the layer attaches the one-line caveat itself — period,
reason, direction — before the answer reaches the user.

This dissolves the push/pull tension rather than balancing it. The agent's
prompt stays lean (no distraction cost), the pull tools stay available for
genuine judgment calls, and the disclosure guarantee holds regardless of
whether the model felt like mentioning it. The eval then measures both
halves honestly: agent-volunteered disclosure (capability — did it notice?)
and system-guaranteed disclosure (safety — was the user told?). Production
systems have always worked this way — freshness badges in BI tools are
platform-rendered, not analyst-volunteered. Agent-serving layers should be
no different.

## Loop turn 3: building the deterministic layer

The third loop turn implemented exactly that. When the agent submits an
answer, the serving layer checks whether the trace referenced a restated
metric in *any* tool — a query, a definition lookup, the restatement log,
the period-status check. If it did, the layer appends a one-line governance
note naming the period, the restatement date, and the reason. The trigger is
deliberately "the answer concerns restated data," not "a query touched
restated rows": four of the agent's best answers were produced straight from
the restatement log without re-querying the data, and a query-only trigger
would have missed them all.

Measured on the 167-question traces, with no new model run needed (the
caveat is pure post-processing of the trace, so applying it offline is
exactly equivalent):

- Agent-volunteered revision disclosure: 27/39 = 69% of changed questions
  the agent actually answered
- System-guaranteed: 37/39 = 95%

The two misses are wrong-metric answers (the agent used order-based
`gross_revenue` for revenue questions) — metric-selection failures, already
measured separately, not disclosure failures. The guarantee is honest about
its scope: it fires when the answer concerns restated data, and it cannot
rescue an answer built on the wrong data entirely.

The three turns now read as one argument: teach the agent (34% → 52%),
don't distract it (targeted notes, no behavior cost), and guarantee what
matters deterministically (52% → 95%).

## Closing the loop

The project is called the Grounding Loop, and until now the loop was a
diagram. Phase 5 closed it for the first time, concretely:

1. **Detect:** the canary caught 29 changed answers when the late batch landed.
2. **Diagnose:** the trace decomposition showed *where* disclosure failed — the agent never looked, or looked and stayed silent.
3. **Feed back:** the findings went back into the system. Five new drift trap questions joined the golden set ("Is May revenue final?", "Was June revenue restated?", "What changed in the data after June 30?"), growing it from 50 to 127 — and the disclosure scorer learned keywords for all 35 disclosure cases.
4. **Re-evaluate:** the expanded-set run confirmed the headline on nearly double the sample: revision disclosure 10/29 = 34%, behavior steady at 73%.

Each turn of that cycle makes the layer harder to fool: drift exposes a
weakness, the weakness becomes a trap question and a contract, the next
evaluation proves the fix. That is the loop the essay sketched —
define → serve → evaluate → detect drift → feed back — running under its
own power.

## Limitations and what's next

- The 15-day completeness window is sized from this fixture's design; production would size it from measured arrival patterns.
- The canary is a runnable script, not yet a scheduled job with alerting.
- The disclosure yardstick is still keyword matching — better than n=12, but selective disclosure (flagging the caveat only when misreading is likely) remains the real target, and grading it is an open problem.
- The golden set is locked to definition v1; three questions change status under v2's joins. A golden v2 is a separate experiment.
- Structured WHERE-filter support (the validated-triple pattern) is still on the roadmap; it unlocks cohort churn and retires the v1 simplification.

Total Phase 5 measurement spend: about $4 of the $20 budget. The loop now
runs on its own: the next drift event — late data or a definition change —
has machinery waiting for it.

## Code

The drift builds — snapshot simulator, canary, restatement-log builder,
freshness contracts, expanded golden set — are public alongside everything
else: [github.com/learningEngineer24/grounding-loop](https://github.com/learningEngineer24/grounding-loop).
