"""
Phase 4b: the no-layer ablation agent (OpenRouter backend).

Same role as agent_sql_anthropic.py — the agent writes its own SQL via run_sql
instead of calling governed metrics — but driven through OpenRouter's Responses
API function calling over REST, reaching Muse Ember through OpenRouter after
the Meta Model API proved unreachable from this machine. (Ember is a reasoning
model; Responses is the transport that supports reasoning + function tools
together, same as the OpenAI backend.) Auth goes through the stored
custom.openrouter connector via the authd surrogate exchange (see
~/workspace/custom-connectors/custom.openrouter/CONNECTOR.md); this file
never sees the real key.

The system prompt, tools, and terminal actions are the same as the Anthropic
SQL backend; only the transport differs, so backend deltas measure the model,
not the harness. Tool definitions are converted verbatim from TOOL_DEFS so
the backends cannot drift apart.
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

HOST = "openrouter.ai"
CREDENTIAL = "custom.openrouter"

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

# Responses API takes function tools flat (no nested "function" object,
# unlike Chat Completions).
OPENAI_TOOLS = [
    {"type": "function",
     "name": d["name"],
     "description": d["description"],
     "parameters": d["input_schema"]}
    for d in TOOL_DEFS
]


def _post(model: str, inputs: list) -> dict:
    """One /v1/responses call. Retries transient errors; surfaces the
    API's error body on hard failures. Returns the raw response dict.

    The system prompt goes in `instructions`; prior turns are passed back
    as input items (output items verbatim, plus function_call_output)."""
    import time as _time
    import urllib.error as _urlerror

    body = json.dumps({
        "model": model,
        "max_output_tokens": 1500,
        "instructions": SYSTEM,
        "input": inputs,
        "tools": OPENAI_TOOLS,
    }).encode("utf-8")
    last_err = None
    for attempt in range(4):
        req = urllib.request.Request(
            f"https://{HOST}/api/v1/responses",
            data=body, headers={
                "Content-Type": "application/json",
                # OpenRouter sits behind Cloudflare, which 403s (error 1010)
                # the default Python-urllib User-Agent; a browser UA passes.
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/126.0.0.0 Safari/537.36"},
            method="POST")
        add_surrogate_to_request(req, CREDENTIAL, allowed_hosts=[HOST])
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return read_json_response(resp)
        except _urlerror.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            last_err = f"HTTP {e.code}: {detail}"
            if e.code in (429, 500, 502, 503) and attempt < 3:
                _time.sleep(2 ** attempt * 5)
                continue
            raise RuntimeError(last_err) from None
    raise RuntimeError(last_err or "responses failed")


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
    """Run one golden question via OpenRouter function calling. Same trace
    schema as agent_sql_anthropic.run_question."""
    inputs: list = [{"role": "user", "content": question}]
    tool_calls: list[dict] = []
    terminal: dict | None = None
    usage = {"input_tokens": 0, "output_tokens": 0}

    for _ in range(MAX_TURNS):
        resp = _post(model, inputs)
        u = resp.get("usage", {})
        usage["input_tokens"] += u.get("input_tokens", 0)
        usage["output_tokens"] += u.get("output_tokens", 0)

        items = resp.get("output", []) or []
        calls = [it for it in items if it.get("type") == "function_call"]
        # feed the model's output items back verbatim, then the tool results
        inputs.extend(items)

        if not calls:
            inputs.append({"role": "user", "content":
                "You must finish with exactly one of: submit_answer, "
                "ask_clarify, refuse."})
            continue

        for call in calls:
            name = call.get("name")
            try:
                args = json.loads(call.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            result = _dispatch(name, args)
            entry = {"tool": name, "input": args,
                     "result_summary": _summarize(name, result)}
            if name == "run_sql" and isinstance(result, dict) \
                    and "rows" in result:
                entry["rows"] = result["rows"][:50]
                entry["columns"] = result.get("columns", [])
            tool_calls.append(entry)
            inputs.append({
                "type": "function_call_output",
                "call_id": call.get("call_id"),
                "output": json.dumps(result, default=str)[:4000]})
            if name in TERMINAL:
                terminal = {"action": name, **args}
        if terminal:
            break

    return {"id": qid, "question": question, "tool_calls": tool_calls,
            "terminal": terminal or {"action": "no_decision"},
            "usage": usage}
