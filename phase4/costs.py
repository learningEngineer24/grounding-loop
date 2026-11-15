"""Per-token prices for the part 4 grid — the single source of truth.

$ per million tokens (input / output), verified Nov 15, 2026. Date-stamp all
cost figures and re-verify on pilot day: frontier prices move (Gemini 3.8
Flash doubles Jan 1, 2027).

Self-hosted Glimmer has $0 marginal token cost; the RunPod rental is billed
separately and is NOT folded into cost_usd — note it separately in run
reports. Gated traces carry their own total (gate overhead + escalations)
in trace["gate"]["total_cost_usd"]; attach_cost prefers that.
"""
from __future__ import annotations

PRICES = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "gpt-6.1-sol": (2.0, 10.0),
    "meta/muse-ember": (0.10, 0.50),
    "muse-ember-1.0": (0.10, 0.50),
}

# Self-hosted: $0 marginal token cost.
SELF_HOSTED_MODELS = {
    "hf.co/meta-models/Muse-Glimmer-30B-GGUF:Muse-Glimmer-30B-KQuant-17GB-Q4_K_M",
}


def price_for(model: str) -> tuple[float, float]:
    if model in SELF_HOSTED_MODELS:
        return (0.0, 0.0)
    return PRICES.get(model, (0.0, 0.0))


def cost_usd(model: str, usage: dict) -> float:
    pin, pout = price_for(model)
    return (usage.get("input_tokens", 0) / 1e6 * pin
            + usage.get("output_tokens", 0) / 1e6 * pout)


def attach_cost(trace: dict, model: str) -> dict:
    """Set trace["cost_usd"] in place and return the trace.

    Gated traces use the gate's own total (attempts + escalation); everything
    else is priced from the top-level usage. Error traces with no usage cost $0.
    """
    gate = trace.get("gate") or {}
    if gate.get("total_cost_usd") is not None:
        trace["cost_usd"] = round(float(gate["total_cost_usd"]), 6)
    else:
        trace["cost_usd"] = round(cost_usd(model, trace.get("usage") or {}), 6)
    return trace
