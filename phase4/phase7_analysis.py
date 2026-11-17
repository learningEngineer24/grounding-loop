"""Phase 7 analysis for Grounding Loop part 4: score the frozen cells,
compute costs and gate detail, and paired bootstrap CIs.

Reads phase4/scores_frozen_*.json, phase4b/scores_frozen_*_bare.json,
and the trace files. Writes nothing except stdout (JSON summary).
Deterministic: random.seed(0), 10,000 resamples, pure Python.

Nov 16, 2026 addendum: Glimmer cells added (bare/layer/gate) plus
Glimmer comparisons. The 9-cell rows and CIs are unchanged.
Glimmer trace cost_usd is $0 for bare/layer (self-hosted, $0 marginal
token cost per phase4/costs.py); the gate cell's $1.0084 is Sonnet
escalation cost only. RunPod rental is NOT in cost_usd — see the
addendum write-up for the rental and hosted-equivalent cost views.
"""
import json
import random
import statistics
from pathlib import Path

BASE = Path("/home/hatch/workspace/grounding-loop")
CELLS = [
    ("sonnet", "bare", "phase4b/scores_frozen_sonnet_bare.json", "phase4b/traces_frozen_sonnet_bare.jsonl"),
    ("sonnet", "layer", "phase4/scores_frozen_sonnet_layer.json", "phase4/traces_frozen_sonnet_layer.jsonl"),
    ("sonnet", "gate", "phase4/scores_frozen_sonnet_gate.json", "phase4/traces_frozen_sonnet_gate.jsonl"),
    ("sol", "bare", "phase4b/scores_frozen_sol_bare.json", "phase4b/traces_frozen_sol_bare.jsonl"),
    ("sol", "layer", "phase4/scores_frozen_sol_layer.json", "phase4/traces_frozen_sol_layer.jsonl"),
    ("sol", "gate", "phase4/scores_frozen_sol_gate.json", "phase4/traces_frozen_sol_gate.jsonl"),
    ("ember", "bare", "phase4b/scores_frozen_ember_bare.json", "phase4b/traces_frozen_ember_bare.jsonl"),
    ("ember", "layer", "phase4/scores_frozen_ember_layer.json", "phase4/traces_frozen_ember_layer.jsonl"),
    ("ember", "gate", "phase4/scores_frozen_ember_gate.json", "phase4/traces_frozen_ember_gate.jsonl"),
    ("glimmer", "bare", "phase4b/scores_frozen_glimmer_bare.json", "phase4b/traces_frozen_glimmer_bare.jsonl"),
    ("glimmer", "layer", "phase4/scores_frozen_glimmer_layer.json", "phase4/traces_frozen_glimmer_layer.jsonl"),
    ("glimmer", "gate", "phase4/scores_frozen_glimmer_gate.json", "phase4/traces_frozen_glimmer_gate.jsonl"),
]


def pct(n, d):
    return 100.0 * n / d if d else None


def summarize(scores):
    beh = [s["behavior_ok"] for s in scores]
    num = [s for s in scores if s["numeric_ok"] is not None]
    met = [s for s in scores if s["metric_ok"] is not None]
    dis = [s for s in scores if s["disclosure_ok"] is not None]
    out = {
        "behavior": (sum(beh), len(beh)),
        "numeric": (sum(s["numeric_ok"] for s in num), len(num)),
        "metric": (sum(s["metric_ok"] for s in met), len(met)) if met else (None, 0),
        "disclosure": (sum(s["disclosure_ok"] for s in dis), len(dis)) if dis else (None, 0),
    }
    # category breakdowns
    for cat in ("straightforward", "trap"):
        c = [s for s in scores if s["category"] == cat]
        cn = [s for s in c if s["numeric_ok"] is not None]
        out[f"behavior_{cat}"] = (sum(s["behavior_ok"] for s in c), len(c))
        out[f"numeric_{cat}"] = (sum(s["numeric_ok"] for s in cn), len(cn))
    return out


def gate_detail(trace_path):
    rows = [json.loads(l) for l in open(BASE / trace_path)]
    repaired_attempted = repaired_succeeded = 0
    esc_attempted = esc_succeeded = 0
    esc_cost = 0.0
    repair_cost = 0.0
    for r in rows:
        g = r.get("gate")
        if not g:
            continue
        if g.get("repaired"):
            repaired_attempted += 1
            if g.get("repair_succeeded"):
                repaired_succeeded += 1
        if g.get("escalated"):
            esc_attempted += 1
            if g.get("escalation_succeeded"):
                esc_succeeded += 1
        for a in g.get("attempts", []):
            if a.get("kind") == "repair":
                repair_cost += a.get("cost_usd") or 0.0
            elif a.get("kind") == "escalation":
                esc_cost += a.get("cost_usd") or 0.0
    return {
        "repair_attempted": repaired_attempted,
        "repair_succeeded": repaired_succeeded,
        "escalation_attempted": esc_attempted,
        "escalation_succeeded": esc_succeeded,
        "repair_cost_usd": round(repair_cost, 4),
        "escalation_cost_usd": round(esc_cost, 4),
    }


def bootstrap_paired(a, b, n_resamples=10000, seed=0):
    """Paired bootstrap CI for mean(a) - mean(b), a/b are 0/1 lists of equal length."""
    assert len(a) == len(b)
    n = len(a)
    diffs = [x - y for x, y in zip(a, b)]
    rng = random.Random(seed)
    means = []
    for _ in range(n_resamples):
        s = 0
        for _ in range(n):
            s += diffs[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int(0.025 * n_resamples)]
    hi = means[int(0.975 * n_resamples) - 1]
    return sum(diffs) / n, lo, hi


def main():
    data = {}
    for model, cond, sfile, tfile in CELLS:
        scores = json.load(open(BASE / sfile))
        assert len(scores) == 80, (sfile, len(scores))
        traces = [json.loads(l) for l in open(BASE / tfile)]
        assert len(traces) == 80, (tfile, len(traces))
        cost = sum(t.get("cost_usd") or 0.0 for t in traces)
        summ = summarize(scores)
        num_correct = summ["numeric"][0]
        cell = {
            "scores": summ,
            "cost_usd": round(cost, 4),
            "cost_per_question_usd": round(cost / 80, 5),
            "cost_per_1m_questions_usd": round(cost / 80 * 1_000_000, 0),
            "cost_per_correct_numeric_usd": round(cost / num_correct, 4) if num_correct else None,
            "gate": gate_detail(tfile) if cond == "gate" else None,
        }
        data[f"{model}_{cond}"] = cell

    # paired numeric vectors (answerable questions only, n=64, same set in all cells)
    def numeric_vec(key):
        scores = json.load(open(BASE / dict((f"{m}_{c}", s) for m, c, s, _ in CELLS)[key]))
        return [1 if s["numeric_ok"] else 0 for s in scores if s["numeric_ok"] is not None]

    vecs = {k: numeric_vec(k) for k in data}
    assert all(len(v) == 64 for v in vecs.values())

    def ci(a_key, b_key, label):
        d, lo, hi = bootstrap_paired(vecs[a_key], vecs[b_key])
        return {"label": label, "diff_pp": round(d * 100, 1),
                "ci95_pp": [round(lo * 100, 1), round(hi * 100, 1)]}

    cis = [
        ci("sonnet_layer", "sonnet_bare", "Sonnet layer minus bare (numeric)"),
        ci("sol_layer", "sol_bare", "Sol layer minus bare (numeric)"),
        ci("ember_layer", "ember_bare", "Ember layer minus bare (numeric)"),
        ci("sonnet_gate", "sonnet_layer", "Sonnet gate minus layer (numeric)"),
        ci("sol_gate", "sol_layer", "Sol gate minus layer (numeric)"),
        ci("ember_gate", "ember_layer", "Ember gate minus layer (numeric)"),
        ci("ember_gate", "sonnet_bare", "Ember gate minus Sonnet bare (numeric, claim 1)"),
        ci("ember_gate", "sol_bare", "Ember gate minus Sol bare (numeric, claim 1)"),
        ci("ember_layer", "sonnet_bare", "Ember layer minus Sonnet bare (numeric)"),
        ci("sonnet_bare", "ember_bare", "Bare gap Sonnet minus Ember (numeric)"),
        ci("sonnet_layer", "ember_layer", "Layer gap Sonnet minus Ember (numeric)"),
        ci("sonnet_gate", "ember_gate", "Gate gap Sonnet minus Ember (numeric)"),
        ci("sol_bare", "ember_bare", "Bare gap Sol minus Ember (numeric)"),
        ci("sol_gate", "ember_gate", "Gate gap Sol minus Ember (numeric)"),
        # Glimmer addendum (Nov 16, 2026)
        ci("glimmer_layer", "glimmer_bare", "Glimmer layer minus bare (numeric)"),
        ci("glimmer_gate", "glimmer_layer", "Glimmer gate minus layer (numeric)"),
        ci("glimmer_gate", "sonnet_bare", "Glimmer gate minus Sonnet bare (numeric, claim 1)"),
        ci("glimmer_gate", "sol_bare", "Glimmer gate minus Sol bare (numeric, claim 1)"),
        ci("glimmer_layer", "sonnet_bare", "Glimmer layer minus Sonnet bare (numeric)"),
        ci("glimmer_layer", "ember_layer", "Glimmer layer minus Ember layer (numeric)"),
        ci("glimmer_gate", "ember_gate", "Glimmer gate minus Ember gate (numeric)"),
        ci("sonnet_bare", "glimmer_bare", "Bare gap Sonnet minus Glimmer (numeric)"),
        ci("sonnet_layer", "glimmer_layer", "Layer gap Sonnet minus Glimmer (numeric)"),
        ci("sonnet_gate", "glimmer_gate", "Gate gap Sonnet minus Glimmer (numeric)"),
        ci("sol_bare", "glimmer_bare", "Bare gap Sol minus Glimmer (numeric)"),
        ci("sol_gate", "glimmer_gate", "Gate gap Sol minus Glimmer (numeric)"),
        ci("ember_bare", "glimmer_bare", "Bare gap Ember minus Glimmer (numeric)"),
        ci("ember_layer", "glimmer_layer", "Layer gap Ember minus Glimmer (numeric)"),
    ]
    # compression: bare gap minus gate gap (paired, same questions)
    bare_gap = [x - y for x, y in zip(vecs["sonnet_bare"], vecs["ember_bare"])]
    gate_gap = [x - y for x, y in zip(vecs["sonnet_gate"], vecs["ember_gate"])]
    comp = [b - g for b, g in zip(bare_gap, gate_gap)]
    rng = random.Random(0)
    means = sorted(sum(rng.choice(comp) for _ in range(64)) / 64 for _ in range(10000))
    cis.append({"label": "Compression: bare gap minus gate gap, Sonnet vs Ember (numeric)",
                "diff_pp": round(sum(comp) / 64 * 100, 1),
                "ci95_pp": [round(means[250] * 100, 1), round(means[9749] * 100, 1)]})

    def paired_compression(a_gap, b_gap, label):
        diff = [x - y for x, y in zip(a_gap, b_gap)]
        rng = random.Random(0)
        ms = sorted(sum(rng.choice(diff) for _ in range(64)) / 64 for _ in range(10000))
        return {"label": label, "diff_pp": round(sum(diff) / 64 * 100, 1),
                "ci95_pp": [round(ms[250] * 100, 1), round(ms[9749] * 100, 1)]}

    # Compression: bare gap minus gate gap, Sonnet vs Glimmer (numeric)
    bare_gap_g = [x - y for x, y in zip(vecs["sonnet_bare"], vecs["glimmer_bare"])]
    gate_gap_g = [x - y for x, y in zip(vecs["sonnet_gate"], vecs["glimmer_gate"])]
    cis.append(paired_compression(bare_gap_g, gate_gap_g,
                                  "Compression: bare gap minus gate gap, Sonnet vs Glimmer (numeric)"))
    # Compression: bare gap minus layer gap, Sonnet vs Glimmer (numeric)
    layer_gap_g = [x - y for x, y in zip(vecs["sonnet_layer"], vecs["glimmer_layer"])]
    cis.append(paired_compression(bare_gap_g, layer_gap_g,
                                  "Compression: bare gap minus layer gap, Sonnet vs Glimmer (numeric)"))

    print(json.dumps({"cells": data, "bootstrap_cis": cis}, indent=1))


if __name__ == "__main__":
    main()
