# The Grounding Loop: What It Means for Your Organization

**Status:** Draft for review, October 12, 2026
**Intended:** Writing tab post (leads the Grounding Loop series)
**Repo:** https://github.com/learningEngineer24/grounding-loop
**Series:** [The Grounding Loop](WRITEUP_DRAFT_PART1.md) (does it work) · [The Grounding Loop: Managing Drift](WRITEUP_DRAFT_PART2.md) (keeping it honest as the world moves)

## TL;DR

This is a follow-up to [Data Engineering in the Agent Era](https://neboiwenofu.com/writings/data-engineering-agent-era.html). Data governance problems predate LLMs: downstream misuse, silent quality and freshness rot, and diffuse ownership. Humans were the backstop; it worked badly, but it worked. LLMs removed the backstop. Agents now act on enterprise data at machine speed, with no judgment in the loop and no one owning the wrong answer.

The answer is not better prompts. Each layer of the stack is a control, and controls need owners: encode meaning where a compiler can enforce it, disclose at serve time what the encoding knows, evaluate continuously. That means each domain's cross-functional team owns its path from source to answer, stewards inside the team operate the enforcement with real authority, and business stakeholders get a consumer contract.

---

## Common Data Governance Issues in Organizations

It is tempting to tell this story as if AI created the governance problem. It did not. It inherited it, and then made it urgent. Three issues show up in almost every organization, and they predate agents by years.

| What should exist | What usually existed |
|---|---|
| One definition of revenue | Finance's revenue, sales' revenue, the dashboard's revenue, each slightly different |
| Definitions versioned and reviewed | A wiki page last updated two reorgs ago |
| Freshness guarantees | "The dashboard is usually right by standup" |
| An owner for every metric | Everyone and no one; ask three people, get two answers and a shrug |
| Change management for definitions | A Slack message: "heads up, we changed how refunds are counted" |

The industry knew. Data contracts, data mesh's "data as a product," the semantic layer (dbt, MetricFlow, Cube): all attempts to fix exactly this. But adoption was slow, because the cost of the disease was tolerable. That is the world the semantic layer was born into: a good idea, slowly adopted, treated as a BI convenience rather than infrastructure. Nobody's bonus depended on it.

### Downstream usage of data

Most organizations do not have a data-driven culture. They have dashboards. And even in the best cases, with careful and well-intentioned users, the anti-patterns around downstream use are everywhere:

- **Confirmation bias as a query strategy.** Pulling the cut that supports the decision already made, then stopping. The data becomes decoration for a conclusion, not an input to one.
- **Partial reads.** Quoting the headline number without the segment breakdown that reverses it. Simpson's paradox as a daily occurrence: the total is up, every segment is down, nobody looks.
- **Ignored context.** Not knowing the definition changed last quarter, the period is still preliminary, or the segment silently excludes something material. The caveats live in someone's head or a wiki nobody opens before a meeting.
- **Metric shopping.** When two dashboards disagree, citing the one that helps. The disagreement itself, which should be the alarm, becomes a menu.
- **Dashboard theater.** Metrics maintained out of habit that no decision actually depends on, consuming maintenance attention the metrics that matter never receive.

The system relies on the user supplying the context the data does not carry. Most of the time, nobody does.

### Data quality and freshness

As data moves through an organization, ingested, transformed, aggregated, served, it picks up two kinds of rot. Quality: duplicates from a retried load, nulls handled three different ways in three pipelines, a dimension that quietly stopped updating weeks ago. Freshness: the number you acted on is not the number anymore.

The classic version: June revenue was $2.28M when the forecast was locked, targets were set, and hiring plans were approved in the Monday business review. Then the late partner payouts arrived and it became $2.45M. Nothing announced the change. The forecast, the plan, and the bonus math were all built on the preliminary number, and nobody re-ran the decision, because nobody knew there was a new number to re-run it on.

Quality and freshness failures share a property: they are silent. The dashboard does not say "I am stale." It says the number, confidently, in the same font as yesterday.

### Clarity in ownership

When the dashboard is wrong, who fixes it? Today the answer is a finger-pointing exercise with three participants:

- **The data engineer**, whose primary focus is that the systems run as intended. The pipeline ran green. The SQL did what the SQL said. From their seat, nothing is broken.
- **The data scientist**, spread thin across six workstreams, whose model started as a point-in-time analysis and somehow became production. It was never designed to be maintained; now it is load-bearing.
- **The product manager**, who needs the number for a decision this week, is not technical enough to debug it, and has no lever to pull except asking louder.

Everyone owns a piece; no one owns the meaning. The finger-pointing is not malice; it is structure. Each role is incentivized to keep their part running, and the seams between them belong to nobody. Definitions live in the seams.

### How LLMs and Agents have Impacted this Problem

What made all three tolerable was the human backstop: an analyst who noticed something off, asked a question, and reconciled the disagreement. Then agents became consumers of enterprise data, and the problems got worse in specific ways.

**First, the expectation gap.** The spread of LLMs has created a reasonable expectation: ask the tool about last quarter, get an answer grounded in our data. Today's disjointed setups have not delivered it. The agent answers fluently, the numbers look right, and sometimes they are invented. Getting burned once by a hallucinated number in front of stakeholders is enough. Trust does not erode gradually here; it snaps. Then the expensive licenses sit unused, because nobody wants to be the person who quoted the model.

**Second, the backstop disappeared.** An agent does not squint. It does not notice that revenue looks off this month, or that "refunds" might mean something different than last quarter. Every ambiguity that a human analyst resolved tacitly, with context, with a question, with judgment, becomes a silent wrong answer. In [Part 2](WRITEUP_DRAFT_PART2.md)'s meaning-drift experiment (n=8, one model, one run), the agent was shown the new definition outright and still used the old one 0 out of 8 times. A human would have at least asked. The agent answered confidently.

**Third, scale and speed.** A confused analyst misleads one stakeholder meeting. A confused agent misleads every user, every query, until someone notices. The canary work in [Part 2](WRITEUP_DRAFT_PART2.md) (re-running a set of known questions on a schedule to catch changed answers) exists precisely because noticing got harder, not easier. Stale answers do not announce themselves.

**Fourth, agents act.** A dashboard being wrong is a reporting problem. An agent being wrong is an operational problem: it drafts the email, files the report, triggers the workflow. The cost of a wrong definition moved from "slow decision" to "wrong action taken at machine speed."

And the fragmentation got worse, not better. Every team building its own agent wrote its own prompts, its own metric descriptions, its own tool definitions. The same metric defined N times in N prompts, drifting independently. The pre-LLM problem (everyone and no one owns the definition) replicated itself inside every agent, except now the definitions were embedded in prose that no compiler could check.

**Finally, the responsibility vacuum.** When the old issues went wrong, at least the finger-pointing stayed inside the analytics org. Now there are new candidates: the LLM vendor ("the model did what models do"), IT ("we provisioned the tool; the data isn't ours"), the analytics team ("we never approved that agent reading our tables"). Most organizations have no answer for who owns a wrong AI-generated number. So the problems grow unattended, adoption of the expensive tools stalls, and the goal they were bought for, better decisions, quietly dies.

So the old answer, "governance as documentation," stopped being sufficient. You cannot put a wiki in front of an agent and expect compliance. The problem did not change shape; it changed stakes. Governance went from a quality initiative to a prerequisite.

## How my solution addresses these problems

In Data Engineering in the Agent Era I argued the job moves up the stack in three layers: build the foundation, encode the meaning, evaluate the behavior. Read organizationally, each layer is a control, and controls need owners. The whole proposal follows from five principles:

1. Governance is a platform property, not an agent capability.
2. Nothing load-bearing depends on the model's discretion.
3. Every guarantee needs an owner, or it isn't a guarantee.
4. Disclosure the platform attaches beats disclosure the model volunteers.
5. Name the metric that would prove you wrong, and watch it.

The loop this piece is named for is the cycle the moves form: encode the meaning, disclose it at serve time, evaluate continuously, and feed what the evaluation finds back into the encoding. Everything that follows is about keeping that loop running inside every domain.

![The feedback loop: define, serve, evaluate, detect drift, feed back](../images/grounding-loop-feedback-loop.svg)

Three moves implement them. Layer 1, the data foundation, is prior work: the pipelines, quality, and contracts you need regardless. The moves live in layers 2 and 3.

**Encode the meaning where it can be enforced.** Layer 2 at build time. Definitions move out of prompts and wikis, which no machine can check, into a layer a compiler can refuse to violate. The platform says no deterministically, before the wrong answer exists. Organizationally, this is governance with teeth: a review committee can be skipped, a compiler cannot. The leadership decision is who writes the rules the compiler enforces, and who is allowed to override them.

**Disclose at serve time what the layer knows.** Layer 2 at serve time. An encoded meaning is only half the job if the answer arrives without its caveats. Freshness badges in BI are platform-rendered, not analyst-volunteered, because no serious organization stakes decisions on every analyst remembering the caveats. Agent answers need the same treatment: the serving layer attaches what the user must be told, regardless of what the model felt like mentioning. A guarantee living in infrastructure has an owner, a test suite, and an SLA. A prompt instruction has none of those. That is the difference between a control and a wish.

**Evaluate continuously, as an operating ritual.** Layer 3. Re-running the questions stakeholders actually ask, on every material data or definition change, turns "are our answers still right?" from a quarterly worry into a daily fact. The loop is a team operating cadence: someone runs it, someone triages it, someone is accountable when it goes red. For leadership, this is the observable proof the other two controls hold, and the early warning when they do not.

The platform contract, stated plainly:

| Guarantee | Enforced by | If it fails |
|---|---|---|
| Metric definitions compile to correct SQL | Compiler: the fan-out guard blocks row-multiplying joins, plus join validation | Build breaks; no query ships |
| Canonical meanings are respected | Compiler: refuses superseded dimensions | Recoverable error; agent re-queries correctly |
| Known caveats reach the user | Serving layer: attaches disclosure notes deterministically | Platform bug; owned like any serving bug, with an SLA |
| Changed answers are detected | Canary (golden-set re-runs) | STALE flag; triaged by the owning team |
| Definitions change through a process | Governance workflow (see the FAQ below) | Ungoverned change; the canary catches the answers anyway |

Notice what is not on the list: "the agent behaves well." Nothing load-bearing depends on the model's discretion. That is the whole thesis, restated organizationally: governance is a platform property, and platform properties have owners.

### Why this shape, and not the alternatives

Three architectures compete for this problem. Worth stating why this one.

**App-specific prompts and tools.** Each agent team writes its own metric descriptions into its own prompts. Maximum flexibility, zero coordination cost, the fastest way to start. But every definition now exists N times in N prompts, drifting independently, enforced by nothing. Correctness depends on every prompt author remembering every caveat. This is the pre-LLM fragmentation reproduced inside the agents. It scales the problem, not the solution.

**Better data contracts, no serving layer.** Invest in warehouse-level contracts: freshness SLOs, schema tests, quality checks. Worth doing regardless, and it fixes data correctness. But it stops at the warehouse door. Nothing governs what the agent does with correct data: misread definitions, missing caveats, silent staleness at answer time. The contract says the data is fresh; it cannot say the answer is honest.

**The serving layer, per domain (this proposal).** Each domain's definitions live once, in a form a compiler checks; guarantees are enforced deterministically; disclosure is attached by the platform. Highest correctness, but real costs: every domain builds out its own loop, and the maintenance toil the tradeoffs section weighs honestly.

| | Correctness | Flexibility | Latency | Cost | Maintainability |
|---|---|---|---|---|---|
| Per-agent prompts | Low (unenforced) | Highest | None added | Low upfront, high in incidents | Poor (definitions drift N ways) |
| Data contracts only | Medium (data, not answers) | High | None added | Moderate | Good (warehouse-native) |
| Per-domain serving layer | Highest (enforced) | Constrained | Small (compile plus attach) | Higher (platform plus toil) | Good if owned, rots if not |

The honest version: start with contracts (you need them anyway), add the serving layer where agents inform decisions at scale, and never pretend prompts are governance.

One question the table doesn't settle: build or buy. The prototype hand-rolled its compiler (MetricFlow was ruled out for the DuckDB fixture), but an enterprise adopting this should evaluate extending an existing semantic layer, dbt, MetricFlow, Cube, before building. The requirements any option must meet are the guarantees above: definitions a machine can refuse to violate, disclosure attached by the platform, and continuous evaluation. Buy the parts that are commodities. The guarantees are the part you can't outsource.

### The Tradeoffs

None of this is free, and an organization adopting it should know the price.

**Maintenance cost vs value.** The loop runs on toil: golden questions, canary triage, definition reviews. For a small team with stable definitions, this is overkill. The value concentrates where definitions change, stakes are high, and agents serve many users. Adopt it there first.

**Approved vs unapproved drift.** As the golden set grows, legitimate definition evolution looks identical to ungoverned drift, and every STALE flag trains the team to ignore the canary. The change process has to distinguish the two, or the detection system rots from false positives.

### How you know it's working

A proposal needs observable outcomes, or it's a vision deck. This is a sketch; the real numbers come from the pilot.

- **Answer correctness:** canary pass rate over time; disclosure coverage (the share of answers touching restated or redefined periods that carried the note).
- **Governance health:** definition-change lead time, from proposal to enforced; the share of changes going through the process versus around it.
- **Adoption:** analyst bypass rate (queries routed around the layer); number of domains running the loop with ownership assigned.
- **Cost:** toil hours per domain per quarter (golden questions, triage, reviews). Priced openly, not hidden.

If the bypass rate climbs, the strictness is theater and the design is wrong. That metric is the one that keeps the whole thing honest.

## What does this mean for your organization?

If meaning becomes infrastructure, the analytics organization reshapes around it.

**End-to-end ownership, per domain.** Each domain's cross-functional team owns its data flow end to end: the pipelines that produce it, the definitions that give it meaning, the dashboards and agents that serve it. There is no central owner of meaning. There are domain teams, each building out the loop by following the shared principles. When the number is wrong, there is no triangle to convene. The domain team owns it.

**Data stewards and governance functions** get teeth for the first time, from inside the domain team. Governance stops being the team that writes the wiki nobody reads; stewards sit in the cross-functional v-team (virtual team) and operate the enforcement: the change workflow, the compiler rules, the disclosure machinery. The team makes the call on any given metric; its stewards make sure the call goes through the process, and that the process has teeth. This is a promotion in practice, but it requires the organization to actually grant the authority. A steward who can be overruled by any team shipping a prompt is decoration.

**Business stakeholders (finance, sales, ops)** gain something they never had: a consumer contract. Freshness badges, disclosure notes, preliminary-vs-final labels: the caveats arrive attached to the answers instead of living in someone's head. In exchange, definition changes become governed events they participate in. When finance redefines refunds, it goes through the change process: the new definition, the effective date, the migration, the communication. More ceremony than a Slack message; fewer 2 AM reconciliation threads.

### The organizational machinery, as FAQ

Three principles sit above the specifics:

- **Iterate on structure.** Organizations must feel comfortable iterating on their structure until they find the one that lets them achieve their goals. The roles this proposal needs can sit in different org charts; what can't flex is the accountability: every domain owns its data flow, and the Captain owns the outcome.
- **Decide at the scope.** Each domain (or working team) should feel empowered to make decisions aligned to the context of its scope. Authority lives where the context lives.
- **Assign a captain.** An implementation captain navigates the ambiguity of this work: setting the high-level strategy, unblocking cross-domain collaboration, and measuring and monitoring org-level adoption, quality, and migration progress. They don't own any domain's data; they own the outcome. That makes the Captain the one deliberately centralized element in a federated design: a central authority of last resort, with power bestowed by the organization's leader. The trigger is narrow: a domain refusing to adopt the loop after support. The power is bounded to the loop's adoption. Everything else stays with the domains.

The specifics, stated plainly enough to argue with:

| Question | This proposal's answer |
|---|---|
| Who proposes a definition change? | Anyone in the organization with relevant subject-matter expertise. The data exists to drive better decisions, so if the people making the decisions, or the people closest to them, have suggestions, that input must be welcomed. |
| Who approves it? | The domain's cross-functional team. The industry trend is toward small cross-functional teams that own a product or feature. As owners, they're the ones with the most relevant prioritization mechanism in the organization, which puts them in the best position to make the call on metric changes. |
| What happens when two domains disagree about a definition? | The domain that reports the number has the final say. Finance reports revenue, so finance defines revenue. Definitional authority follows reporting accountability. |
| Where does the owning team sit? | Where the team sits is flexible, and depends on the organization's maturity. This approach works whether you're structured functionally or by product. |
| Is there a central platform owner? | No central owner of data or implementation. Domain teams own their data flow end to end, each building out its own loop by following the shared principles. The one centralized element is the Captain's accountability of last resort, described below, and it is deliberately narrow. |
| What compels a domain to comply? | The Captain: the one deliberately centralized element in this federated design, a central authority of last resort with power bestowed by the organization's leader. The Captain doesn't own implementation but is responsible for the outcome. When a domain declines, the team is responsible for fixing it with the Captain's support. Changing the team is the last resort, triggered only when a domain refuses to adopt after support, and bounded to the loop's adoption. |
| Who maintains the shared principles? | Senior leaders from each domain's v-team, in collaboration with the Captain. There's no central owner of the principles; the senior leaders maintain and evolve them together as the domains learn, and they're the ones who coordinate externally with the Captain and other domains. |
| New team, new role, or a hat someone wears? | No new team. The domain's cross-functional v-team takes this on as part of owning its data flow, with steward and coordination responsibilities assigned inside the team. Ownership lives where the data lives. |
| What happens when a team bypasses the layer? | Nothing breaks, and that's the point. The bypass is visible (bypass rate is a tracked metric), those answers carry no disclosure guarantees, and repeated bypass is a design signal, not a policy violation. If the bypass rate climbs, the strictness is theater. That covers individual queries going around the layer. A domain refusing to adopt the loop is different, and that's where the Captain's authority applies. |
| Who writes the golden questions? | Anyone who knows where the bodies are buried: which metrics get misread, which periods are treacherous, which definitions the business argues about. No definition ships without its golden questions. |
| Who triages the canary, and how fast? | The owning domain team, on a defined cadence (daily for high-churn domains). A red canary is an incident, not a backlog item. The exact SLA is set by the pilot. |
| What keeps this maintained? | Maintenance sits in the domain team's charter with a budget, not a favor. Definition authorship counts the way code review counts; canary health is a team metric, reported like uptime. |

### What it costs

Nobody has priced this yet, so treat everything here as a bracket to be validated by the pilot, not a quote.

- **The pilot:** a 2-week sprint to build an MVP of what's possible. One domain, roughly two to three people part-time: an engineer, or someone with context on how data systems work, to stand up the layer; someone with domain-specific understanding, to write the golden questions; someone who can measure the loop, to price it. The deliverable is not just a working loop but a priced one: toil hours get logged, so the steady-state number is measured instead of guessed.
- **Steady state per domain:** the toil is golden-question maintenance, canary triage, and definition reviews. It scales with definition churn, not data volume. Domains with stable definitions should find this close to zero, which is the point of adopting it where definitions change first.
- **The build-out, per domain:** each domain sets up its own loop, the compiler, disclosure attachment, and canary runner, following the shared principles. Whether that's new construction or an extension of the existing semantic layer changes the number by an order of magnitude, which is why the pilot should test the cheapest viable shape first. The principles are shared; the build-out isn't.
- **The cost of not doing it:** the licenses already bought and gathering dust after the first hallucinated number, the decisions built on preliminary figures nobody re-ran, the reconciliation threads. Most organizations are already paying this. It's just filed under different budgets.

The most expensive part of this proposal is not the platform. It's the organizational attention: the reviews, the arbitration, the triage. Price that openly, or it becomes the reason the system rots.

## What's next

This piece is a proposal argued from a prototype, not a report from production. The claims about ownership, toil, and what breaks need contact with a real analytics org to validate. The next step is the internal pilot: one real domain, a 2-week sprint to build an MVP of what's possible, then write up what broke. The false positives, the arguments about definitions, who maintained what, what it cost. That is the evidence this piece cannot supply from a fixture.

---

*This piece leads the Grounding Loop series and follows up on [Data Engineering in the Agent Era](https://neboiwenofu.com/writings/data-engineering-agent-era.html). The technical companions build the prototype this piece organizes around: [Part 1](WRITEUP_DRAFT_PART1.md) constructs the governed semantic layer, and [Part 2](WRITEUP_DRAFT_PART2.md) runs the drift machinery. Written to be lifted: the principles, the contract, the FAQ, and the metrics are built so another organization can turn them into its strategy doc. The code is public: [github.com/learningEngineer24/grounding-loop](https://github.com/learningEngineer24/grounding-loop).*
