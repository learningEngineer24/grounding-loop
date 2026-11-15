"""
Phase 4b: the no-layer ablation agent (Anthropic backend).

Same role as agent_sql_gemini.py — the agent writes its own SQL via run_sql
instead of calling governed metrics — but driven through the Anthropic API
via the stored custom.anthropic connector (urllib + surrogate exchange; the
real key is never visible here). Same trace schema, so score_4b.py works
unchanged.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import (  # noqa: E402
    add_surrogate_to_request,
    read_json_response,
)

import sql_tools  # noqa: E402
from context import CONTEXT  # noqa: E402

HOST = "api.anthropic.com"
CREDENTIAL = "custom.anthropic"
API_VERSION = "2023-06-01"

SYSTEM = """You are a data analyst agent with direct SQL access to the \
company warehouse. The full schema and the documented data quirks are given \
below — read them carefully before you write any query.

RULES:
1. Answer data questions by writing your own SQL and running it with the \
run_sql tool. Only SELECT statements are allowed.
2. The quirks below are real and they bite. "Revenue" in this warehouse is \
NOT SUM(amount) — read the status table. Trial and cancelled customers are \
NOT active. Discounts are order-level. Check the quirks before you trust a \
naive query.
3. Time cuts: the warehouse covers H1 2026 (2026-01-01 to 2026-06-30). \
"Last month" without a reference date is ambiguous.
4. If the question maps cleanly to a query, run it and submit_answer with \
the number(s).
5. If the question is ambiguous — unclear definition, missing period, vague \
words like "best" or "doing" — call ask_clarify with your question. Do NOT \
guess.
6. If the question asks for the future (forecasts, predictions) or something \
the warehouse cannot answer, call refuse with the reason.
7. When your answer depends on a subtlety the asker might not expect (e.g. \
only settled payments count as revenue), say so in one sentence alongside \
the answer.

Work step by step. You may call run_sql as many times as you need, then \
finish with exactly one of submit_answer, ask_clarify, refuse.

""" + CONTEXT + (
    f"\n\nNote: the warehouse snapshot you are querying is current as of "
    f"{os.environ['GROUNDING_DATA_AS_OF']}."
    if os.environ.get("GROUNDING_DATA_AS_OF") else ""
)

TOOL_DEFS = [
    {"name": "run_sql",
     "description": "Run a read-only SELECT query against the warehouse. Returns columns and up to 200 rows.",
     "input_schema": {"type": "object",
                      "properties": {"sql": {"type": "string"}},
                      "required": ["sql"]}},
    {"name": "submit_answer",
     "description": "Terminal. Submit your final answer: the number(s) and any one-sentence caveat.",
     "input_schema": {"type": "object",
                      "properties": {"answer_text": {"type": "string"}},
                      "required": ["answer_text"]}},
    {"name": "ask_clarify",
     "description": "Terminal. The question is ambiguous — ask exactly what you need to answer it.",
     "input_schema": {"type": "object",
                      "properties": {"question": {"type": "string"}},
                      "required": ["question"]}},
    {"name": "refuse",
     "description": "Terminal. The question cannot be answered from the warehouse — state why.",
     "input_schema": {"type": "object",
                      "properties": {"reason": {"type": "string"}},
                      "required": ["reason"]}},
]

TERMINAL = {"submit_answer", "ask_clarify", "refuse"}
MAX_TURNS = 10


def _post(model: str, messages: list) -> dict:
    import urllib.error as _urlerror

    body = json.dumps({
        "model": model,
        "max_tokens": 1500,
        "system": SYSTEM,
        "tools": TOOL_DEFS,
        "messages": messages,
    }).encode("utf-8")
    last_err = None
    for attempt in range(4):
        req = urllib.request.Request(
            f"https://{HOST}/v1/messages", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "anthropic-version": API_VERSION})
        add_surrogate_to_request(req, CREDENTIAL, allowed_hosts=[HOST])
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return read_json_response(resp)
        except _urlerror.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            last_err = f"HTTP {e.code}: {detail}"
            if e.code in (429, 500, 502, 503) and attempt < 3:
                import time as _time
                _time.sleep(2 ** attempt * 5)
                continue
            raise RuntimeError(last_err) from None
    raise RuntimeError(last_err or "messages API failed")


def _dispatch(name: str, args: dict):
    if name == "run_sql":
        return sql_tools.run_sql(args.get("sql", ""))
    if name in TERMINAL:
        return {"ok": True}
    return {"error": f"unknown tool {name}"}


def _summarize(name: str, result) -> str:
    if isinstance(result, dict) and "error" in result:
        return f"error: {result['error']}"[:200]
    if name == "run_sql" and isinstance(result, dict):
        return f"rows={result.get('row_count', 0)}"
    return "ok"


def run_question(model: str, qid: str, question: str) -> dict:
    """Run one golden question via the Anthropic API. Same trace schema as
    the other backends."""
    messages: list[dict] = [{"role": "user", "content": question}]
    tool_calls: list[dict] = []
    terminal: dict | None = None
    usage = {"input_tokens": 0, "output_tokens": 0}

    for _ in range(MAX_TURNS):
        resp = _post(model, messages)
        usage["input_tokens"] += resp.get("usage", {}).get("input_tokens", 0)
        usage["output_tokens"] += resp.get("usage", {}).get("output_tokens", 0)

        assistant_blocks = []
        pending_results = []
        for block in resp.get("content", []):
            if block.get("type") == "text":
                assistant_blocks.append(
                    {"type": "text", "text": block.get("text", "")})
            elif block.get("type") == "tool_use":
                assistant_blocks.append({
                    "type": "tool_use", "id": block["id"],
                    "name": block["name"], "input": block.get("input", {})})
                result = _dispatch(block["name"], block.get("input", {}) or {})
                entry = {"tool": block["name"], "input": block.get("input", {}),
                         "result_summary": _summarize(block["name"], result)}
                if block["name"] == "run_sql" and isinstance(result, dict) \
                        and "rows" in result:
                    entry["rows"] = result["rows"][:50]
                    entry["columns"] = result.get("columns", [])
                tool_calls.append(entry)
                pending_results.append({
                    "type": "tool_result", "tool_use_id": block["id"],
                    "content": json.dumps(result, default=str)[:6000]})
                if block["name"] in TERMINAL:
                    terminal = {"action": block["name"],
                                **(block.get("input", {}) or {})}
        messages.append({"role": "assistant", "content": assistant_blocks})
        if terminal:
            break
        messages.append({"role": "user", "content": pending_results})

    return {"id": qid, "question": question, "tool_calls": tool_calls,
            "terminal": terminal or {"action": "no_decision"},
            "usage": usage}
