# Grounding the Loop: Managing Drift

**Status:** Draft for review, October 10, 2026
**Intended:** Projects page post (sequel to The Grounding Loop)
**Repo:** https://github.com/learningEngineer24/grounding-loop
**Prequel:** [The Grounding Loop](WRITEUP_DRAFT_PART1.md): the measurement story.

> Part 1 built the apparatus: a governed semantic layer over a synthetic
> warehouse, a golden set of trap questions, and a harness that scores
> whether an AI agent's answers stay honest. This is the operations sequel:
> what happens when the world moves underneath it, and the machinery that
> keeps the answers trustworthy anyway.

## TL;DR

Part 1 built the apparatus: a governed semantic layer over a synthetic
warehouse, a golden set of trap questions, and a harness that scores whether
an AI agent's answers stay honest. But measurement is a snapshot. Data moves:
payments arrive late and restate last month's revenue. Definitions change:
finance redefines what "refunds" means and no rows move at all. A layer that
is honest today goes stale silently, and a confident agent will keep quoting
yesterday's numbers. This post is about the operations that prevent that:
the machinery that keeps answers trustworthy as the world moves underneath
them.

What happened: when late payments restated June revenue upward by $167,724,
the agent told the user 4% of the time. Giving it a first-class restatement
log took disclosure to 34% with no accuracy cost; targeted inline notes took
it to 52% without distracting the agent; attaching the caveat
deterministically at the answer level took it to 66%. When a definition
changed instead of the data, the agent ignored the new definition entirely,
so the platform now enforces it the way the fan-out guard refuses bad joins.

What it means: drift management is a circular improvement loop. The canary
detects changed answers, traces diagnose where disclosure failed, the
findings feed back into tighter definitions and new trap questions, and the
next evaluation demonstrates the fix. And the deeper lesson: governance is a
platform property, not an agent capability to be prompted into existence.

---

## The drift event

Part 1 ended with a measured layer and an open problem: disclosure. The
layer could keep answers honest, but only as long as nothing moved. This
post starts the loop running. What happens when the world moves underneath
a governed layer, and what machinery keeps the answers trustworthy anyway.

The most ordinary event in data engineering: payments arrived late. Thirty
of them landed after the June 30 close, 1–15 days after their payment dates
(the batch-processing lag documented as Quirk 3). Two snapshots tell the
story:

| Snapshot | As of | Payments |
|---|---|---|
| A: June 30 close | 2026-06-30 | 2,970 |
| B: July 15 | 2026-07-15 | 3,000 |

June settled revenue restated from $2,282,054 to $2,449,779, up $167,724,
or 7.3%. Total refunds restated +$3,358; net realized revenue +$164,366.
Twenty-nine of the 127 golden questions changed answers; Q1 was untouched. A
deterministic diff caught every stale answer. That part was easy.

The harder question: does the *agent* tell the user? On the 50-question
exam, with restatement metadata visible through `describe_metric`, the
governed agent disclosed the revision 2 times out of 15 changed answers
(13%). The no-layer agent, with no metadata at all, disclosed 0 of 15. The layer enabled revision
disclosure; the agent barely used it. A trace decomposition showed why:
on 6 of the 15, the agent never called `describe_metric` and never saw the
note; on 7 it saw the note and stayed silent anyway.

## Three practices: prevent, detect, communicate

The industry has settled patterns for this: watermarks with measured
lookback windows, freshness SLOs in data contracts, observability across
freshness/volume/schema/distribution/lineage, restatable history. The
project maps them onto the agent-serving layer as three builds:

**Prevent: freshness contracts in the semantic YAML.** Four metrics
(`settled_revenue`, `total_payments`, `total_refunds`,
`net_realized_revenue`) carry a 15-day completeness window. While the
trailing period is inside the window, `query_metric` answers with an inline
warning: June is preliminary on June 30, final on July 15. The contract
lives with the definition, not in a wiki, so every consumer inherits it.

**Detect: the golden set as a drift canary.** Warehouse observability says
the *data* changed; the canary says which *stakeholder-facing answers*
changed because of it. `phase5/canary.py` re-runs every golden question
against a target database and diffs against the locked answers: exit 0 for
CLEAN, 1 for STALE. On the June snapshot: 15 of 50 stale (29 of 127 after
the expansion below). That distinction (data changed vs. answers changed)
is the canary's whole value.

**Communicate: the restatement log as a first-class entity.** A
`restatement_log` table records every revision: metric, period, restated
date, reason, old value, new value, delta. A `list_restatements` tool
exposes it to the agent, alongside a prompt rule: when freshness metadata
flags a restated period, check the log and say so in one sentence.

## Loop turn 1: the restatement log

Re-running the drift experiment with all three practices in place:

| | Behavior | Numeric | Revision disclosure |
|---|---|---|---|
| Metadata only (v1) | 75% | 71% | 2/45 = 4% (pooled over three runs) |
| + restatement log, tool, rule (v2) | 72% | 66% | 15/45 = 33% (pooled over three runs) |

The v2 agent hit exactly 5/15 on revision disclosure in all three runs,
and the gain is stable, not a lucky draw. And the behavior difference (75% vs
72%) sits inside run-to-run noise: the drift machinery buys the disclosure
gain at no measurable accuracy cost.

Part 1 ended with disclosure as an unsolved problem twice over: a weak
solution and a weak yardstick. This is the solution half answering back:
give the agent a first-class restatement record instead of a metadata
footnote, and revision disclosure goes from 4% to 34% (10/29 on the
expanded set below). The yardstick half is still open (see below).

## Loop turn 2: push vs pull

The three builds trace a small arc that rederives an industry lesson. The
first attempt pushed restatement metadata into every `describe_metric`
response: 13% revision disclosure (2/15, single run). The second added pull tools: a
restatement log the agent could check when it suspected something: 33%
(15/45, pooled over three runs).
The third pushed harder, inlining the restatement note into every
`query_metric` response whether the query needed it or not: disclosure rose,
but the agent started tripping over caveats attached to questions they
didn't apply to.

This is the context-engineering guidance the industry has converged on:
pull, don't push. Keep the prompt lean; give the agent cheap tools to fetch
context when it needs it; reserve pushing for what's safety-critical. My
fix was to target the inline note (it now fires only when the query
actually touches the restated period) and to collapse the two overlapping
prompt rules into one. Fewer, sharper instructions beat more.

## The architectural fix: deterministic disclosure

There is a deeper resolution, and it's the core recommendation to come out
of this work. The eval measures whether the *agent* volunteers a
disclosure: did it notice the restatement and mention it? But what protects
a decision is different: did the *user* get told? Those are two separate
properties, and only the second one is load-bearing.

Known-knowns (a restated period, a preliminary status) should not depend
on the agent's discretion at all. The serving layer already injects
`freshness_warning` into query results deterministically; the platform
decides, not the model. The recommendation is to extend that pattern to the
answer level: when the agent submits an answer whose queries touched a
restated period, the layer attaches the one-line caveat itself: period,
reason, direction, before the answer reaches the user.

This dissolves the push/pull tension rather than balancing it. The agent's
prompt stays lean (no distraction cost), the pull tools stay available for
genuine judgment calls, and the disclosure guarantee holds regardless of
whether the model felt like mentioning it. The eval then measures both
halves honestly: agent-volunteered disclosure (capability: did it notice?)
and system-guaranteed disclosure (safety: was the user told?). Production
systems have always worked this way: freshness badges in BI tools are
platform-rendered, not analyst-volunteered. Agent-serving layers should be
no different.

## Loop turn 3: building the deterministic layer

The third loop turn implemented exactly that, and ran it live on the full
167-question set (166 scored; the rewritten Q167 has no trace yet). When the agent submits an answer, the serving layer checks
whether any query in the trace touched a restated period; if so, it appends
a one-line governance note naming the period, the restatement date, and the
reason. The agent's own text is preserved untouched alongside it, so the
eval can measure both halves honestly.

Results, live (audit-corrected, 166 scored questions):

| | Behavior | Numeric | Revision disclosure |
|---|---|---|---|
| Agent-volunteered | 75% | 52% | 28/56 = 50% |
| With the deterministic layer | 75% | 52% | 37/56 = **66%** |

Behavior and numeric are identical with and without the layer, confirming
it changes nothing about how the agent answers; it only changes what the
user receives. The layer appended the caveat to 47 answers in total (31 of
them on changed questions; it also fires on unchanged questions whose data
sits in a restated period, which is correct: the data was restated even if
that particular answer didn't move). The remaining misses are questions the
agent declined to answer plus two wrong-metric answers. Those are
metric-selection failures, already measured separately, not disclosure
failures.

The three turns now read as one argument, and each step is apple-to-apple:
identical questions, only the intervention changed.

Same 127 questions, turn 1 → turn 2 (targeted notes, period status):

| | Behavior | Numeric | Revision disclosure |
|---|---|---|---|
| Turn 1: restatement log + tool + rule | 73% | 67% | 34% (10/29) |
| Turn 2: + targeted inline notes | 76% | 63% | 52% (15/29) |

Same 167-question exam, turn 2 → turn 3 (deterministic layer):

| | Behavior | Numeric | Revision disclosure |
|---|---|---|---|
| Turn 2 (v3b) | 72% | 54% | 46% (26/56) |
| Turn 3 (v4): + answer-level disclosure | 75% | 52% | **66%** (37/56) |

Teach the agent (33% → 52%), don't distract it (behavior 72% → 76%, no
cost), and guarantee what matters deterministically (46% → 66% on the full
exam). Because the questions didn't change between rows, the gains belong
to the interventions, not to easier questions.

## Loop turn 4: when the meaning drifts

Every drift so far moved data. Turn 4 moved a meaning instead: finance
redefined `total_refunds` from refund-event-month attribution to
original-payment-month attribution (semantics v3). Not a single row changed;
June refunds are still June refunds, but "June refunds" now means $72,264
instead of $200,977.

**Detect:** the canary caught it anyway. Recomputing the golden set under v3
semantics changed 8 answers (every monthly refund breakdown) while H1
totals correctly stayed put. The canary doesn't care whether drift is data
or meaning; it watches answers.

**Diagnose:** the agent was completely blind to it. On the 8 changed
questions it queried `refund_date` every time; 0/8 used the new
attribution, even though 8 of 10 traces called `describe_metric` and were
shown the v3 definition stating the change outright. It looked and didn't
act. None of the existing machinery could fire: freshness contracts watch
data arrival, the restatement log watches data revisions, and the turn-3
deterministic layer watches restated periods. Meaning drift is invisible to
all three by construction.

**Feed back:** a `definition_changes.json` log (the meaning-drift parallel
to `restatements.json`), a `list_definition_changes` tool, the change
surfaced in `describe_metric` metadata, and the deterministic layer extended:
any answer touching a redefined metric now carries the definition-change
note. Re-running the 10-question focused set:

| Focused set: 10 questions | Turn 4: tell the agent |
|---|---|
| Adopted the new attribution | 0/8 |
| Governance note reached the user | 8/10 |

The turn's lesson rhymes with turn 3's: telling the agent isn't enough.
The metric's canonical time dimension, like the fan-out guard, belongs to
the platform to enforce, not the agent to remember. That enforcement
is the honest next build; turn 4 demonstrates the need.

## Loop turn 5: enforcing the canonical meaning

Turn 4 ended with an honest next build: if the agent won't act on the
definition, the platform should enforce it. Turn 5 built it. The compiler
now refuses a query that breaks a metric's canonical time attribution:
asking `total_refunds` for `refund_date` under v3 gets "refused: dimension
'refund_date' is superseded... Re-query with 'payment_date'", mirroring
the fan-out guard's philosophy: refuse rather than silently answer the
wrong question. v1/v2 semantics are untouched; the refusal surfaces as a
recoverable error, not a crash.

Re-running the same focused set:

| Focused set: 10 questions | Turn 5: enforce in the platform |
|---|---|
| Hit the refusal, re-queried `payment_date` | 6/10 |
| Returned exactly the v3 numbers | 5/8 |
| Governance note reached the user | 9/10 |

One agent (Q007) did something arguably better than answering: it asked the
user which meaning they wanted, citing the v3 change. The two misses are
questions the meaning change doesn't touch.

The turn-4/turn-5 pair is the project's thesis in miniature. Turn 4
demonstrated that telling the agent isn't enough (0/8 adopted the new
meaning). Turn 5 demonstrated that the platform can guarantee it anyway
(5/8 exact, 1 thoughtful clarify). Governance, like the fan-out guard
before it, turns out to be a platform property, not an agent capability to
be prompted into existence. The boundary matters: enforcement works for
machine-readable changes, a canonical dimension declared in YAML. A vaguer
redefinition has nothing to refuse on, and there the disclosure note
remains the only backstop. Worth naming the circularity: for those cases
the backstop is graded by the keyword scorer above, which is why the
yardstick redesign is the load-bearing open problem. One caveat on the
numbers: ten questions, one model, one run each. The direction is clear;
the exact fractions are not stable estimates.

## Closing the loop

The project is called the Grounding Loop, and until now the loop was a
diagram. It closed for the first time in turn 1, concretely:

1. **Detect:** the canary caught 29 changed answers when the late batch landed.
2. **Diagnose:** the trace decomposition showed *where* disclosure failed: the agent never looked, or looked and stayed silent.
3. **Feed back:** the findings went back into the system. Five new drift trap questions joined the golden set ("Is May revenue final?", "Was June revenue restated?", "What changed in the data after June 30?"), growing it from 50 to 127, and the disclosure scorer learned keywords for the new disclosure cases.
4. **Re-evaluate:** the expanded-set run confirmed the headline on nearly double the sample: revision disclosure 10/29 = 34%, behavior steady at 73%.

Each turn of that cycle makes the layer harder to fool: drift exposes a
weakness, the weakness becomes a trap question and a contract, the next
evaluation demonstrates the fix. That is the loop the essay sketched
(define → serve → evaluate → detect drift → feed back) running under its
own power.

## Limitations and what's next

- The 15-day completeness window is sized from this fixture's design; production would size it from measured arrival patterns.
- The canary is a runnable script, not yet a scheduled job with alerting.
- The disclosure yardstick is still keyword matching. Better than n=12, but an agent that stuffed "restatement" into every answer would score 100%, and selective disclosure (flagging the caveat only when misreading is likely) remains the real target. Grading it is an open problem.
- The golden set is locked to definition v1; three questions change status under v2's joins. A golden v2 is a separate experiment.
- Structured WHERE-filter support (the validated-triple pattern) is still on the roadmap; it unlocks cohort churn and retires the v1 simplification.

Total Phase 5 measurement spend: about $4 of the $20 budget. The loop now
runs on its own: the next drift event (late data or a definition change)
has machinery waiting for it.

## Code

The drift builds (snapshot simulator, canary, restatement-log builder,
freshness contracts, expanded golden set) are public alongside everything
else: [github.com/learningEngineer24/grounding-loop](https://github.com/learningEngineer24/grounding-loop).
