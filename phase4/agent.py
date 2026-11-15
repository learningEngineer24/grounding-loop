"""
The agent under test (Phase 4).

A tool-using LLM that answers data questions ONLY through the governed
semantic layer. It must terminate every question with exactly one of:
  submit_answer — a numeric answer with the metric cited
  ask_clarify   — the question is ambiguous; ask what you need
  refuse        — the question is unanswerable from historical aggregates

It may never write SQL. All traces are recorded for scoring.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic

import tools

BASE = Path(__file__).resolve().parent

SYSTEM = """You are a data analyst agent. You answer questions about company \
data through a GOVERNED SEMANTIC LAYER — a catalog of metrics with precise, \
versioned definitions.

RULES:
1. NEVER write SQL. Every number you report must come from the query_metric \
tool, which compiles governed definitions.
2. A metric's definition is authoritative: its row filter, aggregation, and \
grain are exactly what the business means. describe_metric shows you the \
definition — read it before you trust a metric name.
3. Names are treacherous. "Revenue" could be settled_revenue, gross_revenue, \
or net_realized_revenue — they differ by ~5-20%. Pick the governed metric \
that matches what was asked; if the question doesn't pin it down, clarify.
4. Time cuts: the warehouse covers H1 2026 (2026-01-01 to 2026-06-30). \
"Last month" without a reference date is ambiguous.
5. If the question maps cleanly to a metric, query it and submit_answer with \
the number(s) and the metric name you used.
6. If the question is ambiguous — unclear which metric, missing period, \
vague words like "best" or "doing" — call ask_clarify with your question. \
Do NOT guess.
7. If the question asks for the future (forecasts, predictions) or something \
no governed metric can answer, call refuse with the reason.
8. When a definition has a subtlety the asker might not expect (e.g. only \
settled payments count as revenue), say so in one sentence alongside the \
answer — that's a disclosure, not a clarification.
9. If freshness metadata flags a restated period, call list_restatements \
for the metric and mention the restatement (period, reason, direction) in \
one sentence alongside the answer.
10. query_metric responses may carry an inline restatement_note — if the \
period you are answering about was restated, mention it in one sentence. \
To check whether a metric's value for a period is preliminary or final, \
call get_period_status (backing the period_status virtual metric).

Work step by step. You may call list_metrics, describe_metric, \
list_restatements, get_period_status, and query_metric as many times as you need, then finish \
with exactly one of submit_answer, ask_clarify, refuse."""

TOOL_DEFS = [
    {"name": "list_metrics",
     "description": "List every governed metric: name, type, description.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "describe_metric",
     "description": "Show the full governed definition of one metric: model, aggregation, row filter, available dimensions.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "query_metric",
     "description": "Compile a governed metric to SQL and run it against the warehouse. dimensions: list of dimension names; grain: 'month' for time dimensions.",
     "input_schema": {"type": "object",
                      "properties": {
                          "metric": {"type": "string"},
                          "dimensions": {"type": "array", "items": {"type": "string"}},
                          "grain": {"type": "string"}},
                      "required": ["metric"]}},
    {"name": "list_restatements",
     "description": "Restatement log: every recorded restatement of a governed metric (metric, period, restated_on, reason, old vs new value). Check this when freshness metadata flags a restated period.",
     "input_schema": {"type": "object",
                      "properties": {"metric": {"type": "string"}}}},
    {"name": "get_period_status",
     "description": "Is a governed metric's value for a period (YYYY-MM) preliminary or final, and was it restated? Backs the period_status virtual metric.",
     "input_schema": {"type": "object",
                      "properties": {"metric": {"type": "string"},
                                      "period": {"type": "string"}},
                      "required": ["metric", "period"]}},
    {"name": "submit_answer",
     "description": "Terminal. Submit your final answer: the number(s), the governed metric used, and any one-sentence disclosure.",
     "input_schema": {"type": "object",
                      "properties": {
                          "answer_text": {"type": "string"},
                          "metric_used": {"type": "string"}},
                      "required": ["answer_text", "metric_used"]}},
    {"name": "ask_clarify",
     "description": "Terminal. The question is ambiguous — ask exactly what you need to answer it.",
     "input_schema": {"type": "object",
                      "properties": {"question": {"type": "string"}},
                      "required": ["question"]}},
    {"name": "refuse",
     "description": "Terminal. The question cannot be answered from the governed layer — state why.",
     "input_schema": {"type": "object",
                      "properties": {"reason": {"type": "string"}},
                      "required": ["reason"]}},
]

TERMINAL = {"submit_answer", "ask_clarify", "refuse"}
MAX_TURNS = 10


def run_question(client: anthropic.Anthropic, model: str, qid: str,
                 question: str) -> dict:
    """Run one golden question. Returns the full trace."""
    messages: list[dict] = [{"role": "user", "content": question}]
    tool_calls: list[dict] = []
    terminal: dict | None = None

    for _ in range(MAX_TURNS):
        resp = client.messages.create(
            model=model, max_tokens=1500, system=SYSTEM,
            tools=TOOL_DEFS, messages=messages)
        assistant_blocks = []
        pending_results = []
        for block in resp.content:
            if block.type == "text":
                assistant_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_blocks.append({
                    "type": "tool_use", "id": block.id,
                    "name": block.name, "input": block.input})
                result = _dispatch(block.name, block.input)
                entry = {"tool": block.name, "input": block.input,
                         "result_summary": _summarize(block.name, result)}
                if block.name == "query_metric" and isinstance(result, dict) \
                        and "rows" in result:
                    entry["rows"] = result["rows"][:200]
                    entry["columns"] = result.get("columns", [])
                tool_calls.append(entry)
                pending_results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": json.dumps(result, default=str)[:4000]})
                if block.name in TERMINAL:
                    terminal = {"action": block.name, **block.input}
        messages.append({"role": "assistant", "content": assistant_blocks})
        if terminal:
            break
        messages.append({"role": "user", "content": pending_results})

    usage = {"input_tokens": resp.usage.input_tokens,
             "output_tokens": resp.usage.output_tokens}
    return {"id": qid, "question": question, "tool_calls": tool_calls,
            "terminal": terminal or {"action": "no_decision"},
            "usage": usage}


def _dispatch(name: str, args: dict):
    if name == "list_metrics":
        return tools.list_metrics()
    if name == "describe_metric":
        return tools.describe_metric(args["name"])
    if name == "query_metric":
        return tools.query_metric(args["metric"],
                                  args.get("dimensions"), args.get("grain"))
    if name == "list_restatements":
        return tools.list_restatements(args.get("metric"))
    if name == "get_period_status":
        return tools.get_period_status(args.get("metric"), args.get("period"))
    if name in TERMINAL:
        return {"ok": True}
    return {"error": f"unknown tool {name}"}


def _summarize(name: str, result) -> str:
    if isinstance(result, dict) and "error" in result:
        return f"error: {result['error']}"[:200]
    if name == "query_metric" and isinstance(result, dict):
        return f"rows={len(result.get('rows', []))}"
    if name == "list_metrics":
        return f"{len(result)} metrics"
    return "ok"


def make_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=key)
