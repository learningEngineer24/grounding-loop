"""
OpenAI backend for the agent under test (Phase 4).

Mirrors agent.py's interface — run_question() returns the identical trace
schema — but drives the loop with OpenAI's Responses API function calling
over REST. (Chat Completions cannot combine function tools with reasoning
on gpt-6.1-sol, so Responses is the transport.) Auth goes through the stored custom.openai connector
via the authd surrogate exchange (see ~/workspace/custom-connectors/
custom.openai/CONNECTOR.md); this file never sees the real key.

The system prompt, tools, and terminal actions are the same as the
Anthropic backend; only the transport differs, so backend deltas measure
the model, not the harness. Tool definitions are converted verbatim from
agent.TOOL_DEFS so the two backends cannot drift apart.
"""
from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import (  # noqa: E402
    add_surrogate_to_request,
    read_json_response,
)

import tools  # noqa: E402
from agent import SYSTEM, TOOL_DEFS, TERMINAL, MAX_TURNS, _dispatch, _summarize  # noqa: E402

HOST = "api.openai.com"
CREDENTIAL = "custom.openai"

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

    Chat Completions cannot combine function tools with reasoning on
    gpt-6.1-sol, so this backend uses Responses, which supports both.
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
            f"https://{HOST}/v1/responses",
            data=body, headers={"Content-Type": "application/json"},
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


def run_question(model: str, qid: str, question: str) -> dict:
    """Run one golden question via OpenAI function calling. Same trace
    schema as agent.run_question."""
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
            if name == "query_metric" and isinstance(result, dict) \
                    and "rows" in result:
                entry["rows"] = result["rows"][:200]
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
