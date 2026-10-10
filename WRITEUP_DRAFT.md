# The Grounding Loop: A Semantic Layer You Can Evaluate

**Status:** Draft for review — October 9, 2026
**Intended:** Projects page post (companion to the Agent Era essay)
**Repo:** https://github.com/learningEngineer24/grounding-loop

> A working build of the feedback loop from "Data Engineering in the Agent
> Era": a governed semantic layer over a synthetic warehouse, a 50-question
> golden dataset, and an agent harness that scores whether the layer keeps
> its answers honest.

---

In the essay, I argued that as agents become consumers of enterprise data,
the scarce skill is making data machines can understand, trust, and act on —
and that the work comes in three layers: build the foundation, encode the
meaning, evaluate the behavior. I also sketched the loop that keeps the whole
system honest over time: **define → serve → evaluate → detect drift → feed
back**, with the versioned fix returning to define.

This project is that loop, actualized — small enough to hold in your head,
real enough to produce genuine failures.

| Loop step | The essay | This build |
|---|---|---|
| **1 — Define** | Approved definitions, versioned as artifacts | `semantics_v1.yml` → `semantics_v2.yml`, with a changelog |
| **2 — Serve** | Agents answer questions using those definitions | A harness agent whose only data access is governed metric tools — it never writes SQL |
| **3 — Evaluate** | Golden questions run on every change | 50 locked questions; a four-dimension scorer |
| **4 — Detect drift** | Classify failures: agent, semantic, or data | Trap questions targeting known quirks; a freshness trap on late-arriving payments |
| **5 — Feed back** | Version the fix into the layer | v1 → v2 retired exactly one limitation; the changelog records what each version changed |

What follows is the technical companion: what I built, the code that
navigates the hard parts, where the eval questions came from, and where the
whole thing falls short.

---

## Layer 1: the warehouse fixture

A deterministic DuckDB warehouse for H1 2026: 500 customers, 41 products,
3,000 orders, 3,000 payments, 140 refunds. The interesting part isn't the
scale — it's the seven documented quirks in `QUIRKS.md`, each one a trap a
naive agent (or a hasty analyst) falls into:

- Only `settled` payments count as revenue — a raw `SUM(amount)` overstates by ~20%.
- Refunds arrive days or weeks after the payment, and 30% are partial.
- About 5% of payments land 31–75 days after the order — June's revenue revises upward as they arrive.
- Trial customers can place orders; product 41 is a $0 free add-on that still counts in average-order-value denominators.

Every quirk exists so the eval set has something to test. A fixture without
traps teaches you nothing.

## Layer 2: the semantic layer

Sixteen governed metrics over four semantic models, compiled from YAML to
SQL by a hand-rolled compiler (~200 lines). The v2 addition is declared
joins, read straight from the ER diagram:

```yaml
# phase2/semantics_v2.yml — declared once; reverse directions are inferred
joins:
  - to: orders
    left_on: order_id
    right_on: order_id
    relationship: one_to_one
```

The compiler resolves cross-model dimensions over single- and multi-hop
paths — settled revenue by customer region compiles to
`payments → orders → customers`. And it refuses to do the wrong thing
quietly. Ask for a customer-grain metric broken down by an order-grain
dimension and you get an error, not a doubled count:

```python
# phase2/semantic_compiler.py — the fan-out guard
for (_, _, _, _, r) in new_path:
    if r not in SAFE_HOPS:
        raise ValueError(
            f"refused: dimension '{dname}' from model "
            f"'{base_model}' would fan out via a "
            f"one->many hop")
```

Derived metrics (`net_realized_revenue = settled_revenue − total_refunds`)
compile to CTEs, each one built from the *same* definition the metric would
compile to on its own — so a definition can't mean one thing standalone and
another inside a formula:

```python
def _compile_derived(self, metric_name: str, metric: dict) -> str:
    deps = metric["depends_on"]
    ctes = []
    for dep in deps:
        dep_sql = self.compile(dep).rstrip().rstrip(";")
        ctes.append(f"{dep} AS (\n{dep_sql}\n)")
```

One process point worth stealing: the changelog enforces a taxonomy.
**Roadmap** (planned, not built) is not **known simplifications**
(present-but-approximate, flagged) is not **design decisions** (the fan-out
refusal is intended behavior, not a gap). Roadmap items are never listed as
limitations — a limitations section that includes "not built yet" is a
marketing document.

Validation: 16/16 checks pitting compiled metrics against independently
hand-written SQL, then 24/24 after the join work. Settled revenue
$14,097,425.35; refunds $638,939.28; net realized $13,458,486.07.

## Layer 3: the golden dataset — where eval questions come from

Fifty questions: 30 straightforward, 12 traps, 8 ambiguous or adversarial.
Every numerical answer is computed *through the semantic compiler*, never
hand-typed, and a validator confirms 50/50 reproduce.

Where do eval questions come from in practice? The industry uses four
sources, usually combined:

1. **Human expert curation** — the gold standard. BIRD, the canonical
   text-to-SQL benchmark, holds 12,751 question-SQL pairs across 95
   databases, built with crowdsourced annotation under double-blind expert
   review, at a reported cost near $98k. Thorough, expensive, slow.
2. **Production-mined** — seed from real query logs and traces, stratified
   and frequency-weighted. The standing advice is to start with real
   traffic, not synthetic queries: real users phrase things unexpectedly
   and hit edge cases demos never cover.
3. **LLM-generated + human-verified** — generate candidates cheaply, verify
   expensively.
4. **Templated / synthetic** — programmatic generation for coverage.

The non-negotiable principle across all four: answers must be independently
verifiable — computed from ground truth, never from the system under test.

This project's set is the smallest-scale version of the practice: I
authored all 50 questions by hand against two inputs — the metric catalog
(the 30 straightforward) and `QUIRKS.md` (the 12 traps, one per quirk).
Honest limitation: single author, zero production reality.

**Dashboards deserve a callout as a source.** Every dashboard tile is a real
question a stakeholder actually asks, with the metric, filters, and
group-bys already baked in — "net revenue by month" is a golden question
with a known-good answer sitting in your BI tool right now. Query history
adds frequency (which tells you what matters most), and support channels
like #data-help are gold for the ambiguous category: they contain the
clarifications analysts actually asked back. Two caveats: dashboards encode
*current* definitions, which may themselves be wrong — the golden set should
encode the *governed* definition, and where they disagree, that mismatch is
itself a drift signal. And you'd dedupe and scrub PII before anything
becomes a fixture.

## Layer 3, continued: the harness

The agent under test gets three read-only tools (`list_metrics`,
`describe_metric`, `query_metric`) and three terminal actions
(`submit_answer`, `ask_clarify`, `refuse`). It never sees SQL and never sees
the golden answers. The scorer grades four dimensions: **behavior** (right
terminal action?), **numeric** (right number?), **disclosure** (did traps get
their definitional caveat?), **metric selection** (the governed metric the
golden set names?).

First run: a deterministic baseline — no LLM at all, just keyword-to-metric
matching that always answers and never clarifies. The floor, established
for $0:

| | Behavior | Numeric | Disclosure |
|---|---|---|---|
| Straightforward (30) | 100% | 87% | — |
| Traps (12) | 92% | 64% | 9% |
| Ambiguous (8) | 12% | — | — |

Read that as the story of the project in miniature: the layer does most of
the work on clean questions (93% metric selection), the traps bite (it
reported H1 net revenue as March's — derived metrics need component math a
naive agent can't do), and it answers everything instead of clarifying,
which is exactly the failure an LLM agent is supposed to avoid. Anything a
model scores above this is the marginal value of the model.

> **Measured (Haiku 4.5, Oct 9):** behavior 41/50 (82%), numeric 30/42
> (71%), disclosure 2/12 (17%). Against the deterministic baseline
> (84/81/9): the model wins on judgment — 75% on ambiguous questions vs the
> baseline's 12% — but loses on raw numeric accuracy. The baseline's
> keyword-to-metric matching with governed metrics still computes more
> reliably than the LLM; the LLM's value is knowing when *not* to answer.
> (Baseline for reference: 84% behavior, 81% numeric, 17% disclosure.)

## Phase 4b: the no-layer ablation — measuring the layer's value

A harness that scores answers can't tell you how much of the result is the
semantic layer and how much is the model. Phase 4b is the missing control:
the *same* model answers the *same* 50 questions, but by writing its own SQL
against the raw warehouse instead of calling governed metrics.

The design choice that makes the experiment sharp: the no-layer agent
receives the full schema DDL **and** the complete `QUIRKS.md` as context —
the same documented knowledge the semantic layer encodes. So it measures
*enforcement*, not mere knowledge: documented facts the agent must remember
to apply versus definitions compiled into guardrails it cannot forget. Its
one tool is a read-only, SELECT-only SQL executor; the trace schema and
scorer are unchanged (metric selection reports n/a — there are no metrics).

> **Measured (Haiku 4.5, Oct 9):** behavior 35/50 (70%), numeric 25/42
> (60%), disclosure 3/12 (25%). Against the governed run on the same model
> (82/71/17): the semantic layer is worth **+12 points of behavior and +11
> points of numeric accuracy** — that delta is the enforcement value of
> compiled definitions over documented knowledge. One honest surprise: the
> no-layer agent disclosed *more* often (25% vs 17%) — writing SQL by hand
> forces the model to articulate its assumptions ("counting only
> status='settled'..."), while the governed agent trusts the metric and
> stays silent about the caveat. Though see the caution below: with only 12
> disclosure cases, that gap is a single question — suggestive, not
> conclusive.

## The executive read: three takeaways

The full scorecard, side by side:

| Setup | Behavior | Numeric | Disclosure |
|---|---|---|---|
| Governed metrics, no AI (baseline) | 84% | 81% | 17% |
| AI + governed metrics | 82% | 71% | 17% |
| AI + raw database | 70% | 60% | 25% |

**1. Governance beats raw intelligence.** Handing the model the schema plus
documented knowledge of every quirk still lost to the governed path by
double digits (+12 behavior, +11 numeric, same model). If agents are going
to answer questions about your data, the semantic layer isn't overhead —
it's the product.

**2. AI and rules are complements, not substitutes.** The simple rules-based
baseline still computes more reliably than the AI (81% vs 71% on straight
numbers). But it can't exercise judgment: on ambiguous questions the model
scored 75% where the baseline managed 12%. Pair them — rules for
computation, AI for judgment — don't pick one.

**3. Disclosure is the unsolved problem, twice over.** Our governed solution
surfaced data caveats 2 times out of 12 (17%), and the best setup in the
eval managed 3 out of 12 (25%). But the honest second half: we don't yet
have a good way to test for it either. The scorer checks whether keywords
like "settled" appear in the answer text, a weak proxy for whether a
decision-maker actually grasped the caveat. Twelve cases can't support a
ranking between setups. And the eval assumes disclose-always, when the real
target is probably selective disclosure: flagging the caveat only when
misreading is likely. So disclosure needs work on both sides, a better
solution and a better yardstick. Caveats don't flow through automation for
free; they have to be designed into the system, and the way we grade them
has to be designed too.

All of it cost $0.93 to measure, on a 50-question golden set. That is the
evaluation discipline doing its job: cheap, repeatable, and it tells you
exactly where to invest next — in the layer, in the judgment boundary, and
in disclosure.

## Limitations

These are deliberate scope choices, not oversights. The build focused on
proving the full loop (define → serve → evaluate → measure the layer's
value), so depth in any single area stayed shallow:

- `churn_rate` is cancelled ÷ total customers — a deliberate v1
  simplification, flagged as approximate. The focus was the
  metric-compile-and-evaluate machinery, not perfecting one metric's
  business logic. Cohort-based churn needs the structured filter support
  that's on the roadmap.
- Derived metrics are scalar-only: `net_realized_revenue` by month can't
  come out of the compiler yet. The focus was harness, scorer, and ablation
  design, not compiler completeness.
- No ad-hoc WHERE filters — per-question cuts are validated triples
  (dimension, operator, value) in every real semantic layer; here, period
  cuts still happen in Python after compilation. The focus was the
  governed-metric answering path being measured, not replicating a full BI
  semantic layer.
- The golden set is locked to definition v1; three questions change status
  under v2's joins. The focus was a stable measurement baseline; the v2
  revision is a separate experiment.
- The questions are hand-authored by one person. The focus was deliberate
  trap and adversarial coverage by design, not production-mined volume at
  industry scale. See the industry discussion above for what "real" looks
  like.

## What's next

Phase 5 ran the drift exercise the essay describes: Quirk 3's late batch
landed after the June 30 close, restating June settled revenue upward by
$167,724.30 (+7.3%) across 15 of the 50 golden questions. The eval caught
every stale answer deterministically — and then asked the harder question:
does the *agent* tell the user? With restatement metadata visible through
`describe_metric`, the governed agent disclosed the revision 2 times out of
15 (13%); the no-layer agent, with no metadata at all, 0 out of 15. The
layer enables revision disclosure; the agent barely uses it.

The follow-up builds attacked that gap directly. Freshness contracts in the
semantic YAML (a 15-day completeness window on the four affected metrics,
enforced as inline warnings on incomplete trailing periods), a real
`restatement_log` table with measured old/new/delta values, and a
`list_restatements` agent tool plus a prompt rule to check it. Re-running
the drift experiment: revision disclosure rose to 5 out of 15 (33%) —
two disclosures via the new tool, three more via the prompt rule acting on
metadata the agent had previously ignored. But behavior fell from 78% to
66%: the restatement machinery made the agent more hesitant overall,
clarifying or erroring on questions it had previously answered. Better
drift handling has a measurable cost, and the tradeoff is now quantified.

The canary (`phase5/canary.py`) productionizes the detector: the golden
set re-run on a schedule, exiting CLEAN or STALE. That result rewrote
takeaway #3 above and set the next research bet: selective disclosure as
a judgment problem, with a better yardstick than keyword matching.

After that: a v2 revision of the golden set, and the structured WHERE
support that unlocks cohort churn.

## Code

Everything — warehouse builder, semantic YAML, compiler, validators,
golden set, harness — is public:
[github.com/learningEngineer24/grounding-loop](https://github.com/learningEngineer24/grounding-loop).
