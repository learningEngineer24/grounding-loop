# The Grounding Loop: A Semantic Layer You Can Evaluate

**Status:** Draft for review, October 9, 2026
**Intended:** Projects page post (companion to the Agent Era essay)
**Repo:** https://github.com/learningEngineer24/grounding-loop
**Sequel:** [Managing Drift](WRITEUP_DRAFT_PART2.md): the operations story, what happens when the data moves.

> A working build of the feedback loop from "Data Engineering in the Agent
> Era": a governed semantic layer over a synthetic warehouse, a golden
> dataset of trap questions, and an agent harness that scores whether the
> layer keeps its answers honest.

## TL;DR

I built a governed semantic layer over a synthetic warehouse and measured
whether it keeps an AI agent's answers honest, using a 50-question golden
set full of trap questions. The layer is worth +12 points of behavior and
+11 points of numeric accuracy over the same model writing raw SQL. A
deterministic baseline still computes more reliably than the LLM, but it
cannot handle ambiguity (12% vs 75% on unclear questions). The unsolved
problem is disclosure: getting the agent to surface data caveats, which no
setup did well (best 25%), and which I do not yet know how to grade.

---

This project is an instantiation of an earlier essay, [Data Engineering in
the Agent Era](https://neboiwenofu.com/writings/data-engineering-agent-era.html).
There I argued that as agents become consumers of enterprise data, the scarce
skill is making data machines can understand, trust, and act on, and that the
work comes in three layers: build the foundation, encode the
meaning, evaluate the behavior. I also sketched the loop that keeps the whole
system honest over time: **define → serve → evaluate → detect drift → feed
back**, with the versioned fix returning to define.

What follows builds that loop for real: small enough to hold in your head,
real enough to produce genuine failures.

| Loop step | In the essay | In this build |
|---|---|---|
| **1. Define** | Definitions approved and versioned as artifacts | `semantics_v1.yml` → `semantics_v2.yml`, plus a changelog that separates roadmap items from known simplifications from design decisions |
| **2. Serve** | Agents answer questions using those definitions | A harness agent with three read-only metric tools; it never writes SQL |
| **3. Evaluate** | Golden questions run on every change | 50 locked questions with answers computed through the compiler; a four-dimension scorer (behavior, numeric, disclosure, metric selection) |
| **4. Detect drift** | Classify failures: agent, semantic, or data | One trap question per documented quirk, plus a freshness trap on late-arriving payments |
| **5. Feed back** | Version the fix into the layer | v1 → v2 retired exactly one limitation; the changelog records what each version changed |

This post is the technical companion: what I built, the code that
navigates the hard parts, where the eval questions came from, and where the
whole thing falls short. The sequel post covers Phase 5 (drift management), including the golden set's growth from 50 to 167 questions.

---

## Layer 1: the warehouse fixture

A deterministic DuckDB warehouse for H1 2026: 500 customers, 41 products,
3,000 orders, 3,000 payments, 140 refunds. The interesting part isn't the
scale. It's the seven documented quirks in `QUIRKS.md`, each one a trap a
naive agent (or a hasty analyst) falls into:

- Only `settled` payments count as revenue; a raw `SUM(amount)` overstates by ~20%.
- Refunds arrive days or weeks after the payment, and 30% are partial.
- About 5% of payments land 31–75 days after the order, so June's revenue revises upward as they arrive.
- Trial customers can place orders; product 41 is a $0 free add-on that still counts in average-order-value denominators.

Every quirk exists so the eval set has something to test. A fixture without
traps teaches you nothing.

## Layer 2: the semantic layer

Fourteen governed metrics over four semantic models, compiled from YAML to
SQL by a hand-rolled compiler (~200 lines). The v2 addition is declared
joins, read straight from the ER diagram:

```yaml
# phase2/semantics_v2.yml: declared once; reverse directions are inferred
joins:
  - to: orders
    left_on: order_id
    right_on: order_id
    relationship: one_to_one
```

The compiler resolves cross-model dimensions over single- and multi-hop
paths: settled revenue by customer region compiles to
`payments → orders → customers`. And it refuses to do the wrong thing
quietly. Ask for a customer-grain metric broken down by an order-grain
dimension and you get an error, not a doubled count:

```python
# phase2/semantic_compiler.py: the fan-out guard
for (_, _, _, _, r) in new_path:
    if r not in SAFE_HOPS:
        raise ValueError(
            f"refused: dimension '{dname}' from model "
            f"'{base_model}' would fan out via a "
            f"one->many hop")
```

Derived metrics (`net_realized_revenue = settled_revenue − total_refunds`)
compile to CTEs, each one built from the *same* definition the metric would
compile to on its own, so a definition can't mean one thing standalone and
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
limitations: a limitations section that includes "not built yet" is a
marketing document.

Validation: 16/16 checks pitting compiled metrics against independently
hand-written SQL, then 24/24 after the join work. Settled revenue
$14,097,425.35; refunds $638,939.28; net realized $13,458,486.07.

## Layer 3: the golden dataset, where eval questions come from

Fifty questions: 30 straightforward, 12 traps, 8 ambiguous or adversarial.
Every numerical answer is computed *through the semantic compiler*, never
hand-typed, and a validator confirms 50/50 reproduce.

Where do eval questions come from in practice? The industry uses four
sources, usually combined:

1. **Human expert curation:** the gold standard. BIRD, the canonical
   text-to-SQL benchmark, holds 12,751 question-SQL pairs across 95
   databases, built with crowdsourced annotation under double-blind expert
   review. Thorough, expensive, slow.
2. **Production-mined:** seed from real query logs and traces, stratified
   and frequency-weighted. The standing advice is to start with real
   traffic, not synthetic queries: real users phrase things unexpectedly
   and hit edge cases demos never cover.
3. **LLM-generated + human-verified:** generate candidates cheaply, verify
   expensively.
4. **Templated / synthetic:** programmatic generation for coverage.

The non-negotiable principle across all four: answers must be independently
verifiable: computed from ground truth, never from the system under test.

This project's set is the smallest-scale version of the practice: I
authored all 50 questions by hand against two inputs: the metric catalog
(the 30 straightforward) and `QUIRKS.md` (the 12 traps, one per quirk).
Honest limitation: single author, zero production reality.

**Dashboards deserve a callout as a source.** Every dashboard tile is a real
question a stakeholder actually asks, with the metric, filters, and
group-bys already baked in: "net revenue by month" is a golden question
with a known-good answer sitting in your BI tool right now. Query history
adds frequency (which tells you what matters most), and support channels
like #data-help are gold for the ambiguous category: they contain the
clarifications analysts actually asked back. Two caveats: dashboards encode
*current* definitions, which may themselves be wrong. The golden set should
encode the *governed* definition, and where they disagree, that mismatch is
itself a drift signal. Scrub PII and dedupe before anything becomes a fixture.

## The harness

The agent under test gets three read-only tools (`list_metrics`,
`describe_metric`, `query_metric`) and three terminal actions
(`submit_answer`, `ask_clarify`, `refuse`). It never sees SQL and never sees
the golden answers. The scorer grades four dimensions: **behavior** (right
terminal action?), **numeric** (right number? 42 of the 50 questions have
numeric answers), **disclosure** (did traps get their definitional caveat?),
**metric selection** (the governed metric the golden set names?).

First run: a deterministic baseline. No LLM at all, just keyword-to-metric
matching that always answers and never clarifies. The floor, established
for $0:

| | Behavior | Numeric | Disclosure |
|---|---|---|---|
| Straightforward (30) | 100% | 87% | n/a |
| Traps (12) | 92% | 64% | 9% |
| Ambiguous (8) | 12% | n/a | n/a |

Disclosure was scored on 12 questions (11 traps, 1 ambiguous): the 9% in the
traps row is 1/11, and 2/12 overall (17%) disclosed.

Read that as the story of the project in miniature: the layer does most of
the work on clean questions (30/30 metric selection on straightforward
questions), the traps bite (it reported H1 net revenue as March's (derived
metrics need component math a naive agent can't do)), and it answers
everything instead of clarifying,
which is exactly the failure an LLM agent is supposed to avoid. Anything a
model scores above this is the marginal value of the model.

**Measured (Haiku 4.5, Oct 9):**

| | Behavior | Numeric | Disclosure |
|---|---|---|---|
| Straightforward (30) | 30/30 (100%) | 27/30 (90%) | n/a |
| Traps (12) | 5/12 (42%) | 3/11 (27%) | 2/11 (18%) |
| Ambiguous (8) | 6/8 (75%) | 0/1 | 0/1 |
| Overall | 41/50 (82%) | 30/42 (71%) | 2/12 (17%) |

(One trap question expected clarify, so numeric and disclosure were scored
on 11.)

Against the deterministic baseline (84% behavior, 81% numeric), the model
wins on judgment: 75% on ambiguous questions vs the baseline's 12%. But it
loses on raw numeric accuracy. The baseline's keyword-to-metric matching
with governed metrics still computes more reliably than the LLM; the LLM's
value is knowing when *not* to answer.

## The no-layer ablation: measuring the layer's value

A harness that scores answers can't tell you how much of the result is the
semantic layer and how much is the model. The ablation is the missing control:
the *same* model answers the *same* 50 questions, but by writing its own SQL
against the raw warehouse instead of calling governed metrics.

The design choice that makes the experiment sharp: the no-layer agent
receives the full schema DDL **and** the complete `QUIRKS.md` as context:
the same documented knowledge the semantic layer encodes. So it measures
*enforcement*, not mere knowledge: documented facts the agent must remember
to apply versus definitions compiled into guardrails it cannot forget. Its
one tool is a read-only, SELECT-only SQL executor; the trace schema and
scorer are unchanged (metric selection reports n/a; there are no metrics). One confound to name:
the two agents differ in tools, prompts, and scaffolding, not only in the
layer, so part of the gap could be prompt and tooling effects rather than the
semantic layer alone.

**Measured (Haiku 4.5, Oct 9):**

| Setup | Behavior | Numeric | Disclosure |
|---|---|---|---|
| AI + raw database | 35/50 (70%) | 25/42 (60%) | 3/12 (25%) |
| AI + governed metrics (for reference) | 82% | 71% | 17% |

Against the governed run on the same model, the semantic layer is worth
**+12 points of behavior and +11 points of numeric accuracy**. That delta is
the enforcement value of compiled definitions over documented knowledge.

One surprise: the no-layer agent disclosed *more* often (25% vs 17%).
Writing SQL by hand forces the model to articulate its assumptions ("counting
only status='settled'..."), while the governed agent trusts the metric and
stays silent about the caveat. One caution: with only 12
disclosure cases, that gap is a single question. Suggestive, not conclusive.

One methods note: Phase 4 ran each setup once. LLM runs vary run to run
(Phase 5's repeats moved behavior a few points), so treat the +12/+11 deltas
as directional rather than exact.

## The executive read: four takeaways

The full scorecard, side by side:

| Setup | Behavior | Numeric | Disclosure |
|---|---|---|---|
| Governed metrics, no AI (baseline) | 84% | 81% | 2/12 (17%) |
| AI + governed metrics | 82% | 71% | 2/12 (17%) |
| AI + raw database | 70% | 60% | 3/12 (25%) |

**1. Enforcement beats documentation.** Handing the model the schema plus
documented knowledge of every quirk still lost to the governed path by
double digits (+12 behavior, +11 numeric, same model). Compiled definitions
the agent cannot forget beat documented facts it must remember to apply.

**2. AI and rules are complements, not substitutes.** The simple rules-based
baseline still computes more reliably than the AI (81% vs 71% on straight
numbers). But it can't exercise judgment: on ambiguous questions the model
scored 75% where the baseline managed 12%. The concrete shape of the pairing:
let the platform own everything deterministic (metric math in the compiler,
the fan-out guard, freshness warnings rendered by the serving layer), and let
the model own the judgment boundary (when to clarify, when to refuse, which
metric fits an unclear question). The model should never do arithmetic the
layer can do, and the layer should never make a judgment call the model
should make. Don't pick one.

**3. Disclosure is the unsolved problem, twice over.** My governed solution
surfaced data caveats 2 times out of 12 (17%), and the best setup in the
eval managed 3 out of 12 (25%). But the honest second half: I don't yet
have a good way to test for it either. The scorer checks whether keywords
like "settled" appear in the answer text, a weak proxy for whether a
decision-maker actually grasped the caveat. Twelve cases can't support a
ranking between setups. And the eval assumes disclose-always, when the real
target is probably selective disclosure: flagging the caveat only when
misreading is likely. So disclosure needs work on both sides, a better
solution and a better yardstick. Caveats don't flow through automation for
free; they have to be designed into the system, and the way I grade them
has to be designed too.

**4. Measure cheap, govern on purpose.** All of it cost $0.93 to measure, on
a 50-question golden set. That is the evaluation discipline doing its job:
cheap, repeatable, and it tells you exactly where to invest next: in the
layer, in the judgment boundary, and in disclosure. But measuring is not
governing, and governing has a real tax: someone authors the metrics,
someone owns the YAML, every definition change queues behind them, and
versioning means migration work. Adding declared joins took a changelog entry
and compiler work here; in production, redefining a widely-used metric means
backfills and stakeholder communication.

The alternative was measured too. The no-layer agent improvising from schema
and documented quirks is what no-governance looks like, and it lost 12
points of behavior and 11 of numeric accuracy. Unmeasured improvisation is
the most expensive option because its cost is invisible. Governance is
overhead you pay deliberately, and the eval loop keeps it proportional: it
directs effort where drift actually shows up.

Part 1 stops at measurement: it can name the disclosure gap but not fix it.
The fix came later, under drift, when the project built real disclosure
machinery and measured it again. That is the sequel's story:
[Managing Drift](WRITEUP_DRAFT_PART2.md).

## Limitations

Deliberate scope choices, not oversights. The build proved the full loop
(define → serve → evaluate → measure the layer's value), so depth anywhere
else stayed shallow:

- Metric logic is v1-grade throughout: `churn_rate` is a simplification,
  derived metrics are scalar-only, and per-question cuts happen in Python
  rather than the compiler. Completeness lost priority to the harness,
  scorer, and ablation design.
- The evidence is narrow: 50 hand-authored questions, a single model, one
  run per setup. The takeaways are phrased generally; the proof is not.

## Who owns this in production

The build above is one author and fourteen metrics. Production is hundreds
of metrics across teams that actively dispute what "revenue" means, and the
honest question is who arbitrates. The essay's answer is the only one I have
seen work: ownership by proximity to artifact truth. The analyst who authored
the definitive churn definition owns its meaning; the engineer who owns the
pipeline owns its provenance. Not a committee and not whoever shouts
loudest. The person who can say where a number came from, how it was
transformed, and where it can mislead.

That principle does three jobs in the system this project built. First,
every detection routes to an owner. Agent drift goes to the model owner,
semantic drift to the definition owner, data drift to the pipeline owner.
An alarm that cannot be routed is not a detection system; it is a dashboard
no one reads. Second, the golden set is maintained by its consumers: 50 to
100 questions with known-correct answers, reviewed by the definition owners,
under one standing rule. No definition ships without its golden questions,
and no golden question passes without a versioned definition behind it.
That rule is what makes the eval a maintained system rather than a one-off
project, and Part 2 is the demonstration: the loop caught drift, and the
findings went back into the layer as new questions and contracts. Third,
evaluation itself is graded by cost. Deterministic checks run on every query
and are inexpensive; LLM judges run sampled at moderate cost; human
spot-checks run weekly. The $0.93 in this post is the deterministic tier
doing its job. The expensive tiers exist for what automation misses, not as
the default.

The pattern across all of it: ownership is cross-functional, maintenance
sits with analytics.

## Code

Everything (warehouse builder, semantic YAML, compiler, validators,
golden set, harness) is public:
[github.com/learningEngineer24/grounding-loop](https://github.com/learningEngineer24/grounding-loop).
