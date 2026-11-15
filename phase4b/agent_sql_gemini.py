"""
Phase 4b: the no-layer ablation agent (Gemini backend).

Identical trace schema and terminal actions as the governed harness
(agent_gemini.py), but the agent answers by writing its own SQL against the
warehouse via run_sql instead of calling governed metrics. It receives the
full schema DDL plus QUIRKS.md as context — the same documented knowledge
the semantic layer encodes — so the experiment measures ENFORCEMENT, not
mere knowledge.

Same model, same 50 questions, same scorer as the governed run.
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

import sql_tools  # noqa: E402
from context import CONTEXT  # noqa: E402

HOST = "generativelanguage.googleapis.com"
CREDENTIAL = "custom.gemini"

_PACE_SECS = 4.0
_last_call = 0.0


def _pace():
    import time as _time
    global _last_call
    now = _time.monotonic()
    wait = _PACE_SECS - (now - _last_call)
    if wait > 0:
        _time.sleep(wait)
    _last_call = _time.monotonic()

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

""" + CONTEXT

FUNC_DECLS = [
    {"name": "run_sql",
     "description": "Run a read-only SELECT query against the warehouse. Returns columns and up to 200 rows.",
     "parameters": {"type": "object",
                    "properties": {"sql": {"type": "string"}},
                    "required": ["sql"]}},
    {"name": "submit_answer",
     "description": "Terminal. Submit your final answer: the number(s) and any one-sentence caveat.",
     "parameters": {"type": "object",
                    "properties": {"answer_text": {"type": "string"}},
                    "required": ["answer_text"]}},
    {"name": "ask_clarify",
     "description": "Terminal. The question is ambiguous — ask exactly what you need to answer it.",
     "parameters": {"type": "object",
                    "properties": {"question": {"type": "string"}},
                    "required": ["question"]}},
    {"name": "refuse",
     "description": "Terminal. The question cannot be answered from the warehouse — state why.",
     "parameters": {"type": "object",
                    "properties": {"reason": {"type": "string"}},
                    "required": ["reason"]}},
]

TERMINAL = {"submit_answer", "ask_clarify", "refuse"}
MAX_TURNS = 10


def _generate(model: str, contents: list) -> dict:
    import time as _time
    import urllib.error as _urlerror

    body = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": contents,
        "tools": [{"functionDeclarations": FUNC_DECLS}],
    }).encode("utf-8")
    last_err = None
    for attempt in range(4):
        req = urllib.request.Request(
            f"https://{HOST}/v1beta/models/{model}:generateContent",
            data=body, headers={"Content-Type": "application/json"}, method="POST")
        add_surrogate_to_request(req, CREDENTIAL, allowed_hosts=[HOST])
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return read_json_response(resp)
        except _urlerror.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            last_err = f"HTTP {e.code}: {detail}"
            if e.code in (429, 500, 503) and attempt < 3:
                _time.sleep(2 ** attempt * 5)
                continue
            raise RuntimeError(last_err) from None
    raise RuntimeError(last_err or "generateContent failed")


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
    """Run one golden question via Gemini function calling. Same trace schema
    as the governed harness so score_4b.py can reuse its logic."""
    contents: list = [{"role": "user", "parts": [{"text": question}]}]
    tool_calls: list[dict] = []
    terminal: dict | None = None
    usage = {"input_tokens": 0, "output_tokens": 0}

    for _ in range(MAX_TURNS):
        _pace()
        resp = _generate(model, contents)
        um = resp.get("usageMetadata", {})
        usage["input_tokens"] += um.get("promptTokenCount", 0)
        usage["output_tokens"] += um.get("candidatesTokenCount", 0)

        cands = resp.get("candidates", [])
        parts = (cands[0].get("content", {}).get("parts", []) if cands else [])
        texts = [p["text"] for p in parts if "text" in p]
        call_parts = [p for p in parts if "functionCall" in p]
        calls = [p["functionCall"] for p in call_parts]

        model_parts: list = [{"text": t} for t in texts]
        for p, c in zip(call_parts, calls):
            fc = {"name": c.get("name"), "args": c.get("args", {})}
            # thoughtSignature is a sibling of functionCall at the PART level;
            # it must be echoed back verbatim or the API 400s on the next turn
            mp: dict = {"functionCall": fc}
            if "thoughtSignature" in p:
                mp["thoughtSignature"] = p["thoughtSignature"]
            model_parts.append(mp)
        contents.append({"role": "model", "parts": model_parts})

        if not calls:
            contents.append({"role": "user", "parts": [{
                "text": "You must finish with exactly one of: submit_answer, ask_clarify, refuse."}]})
            continue

        fr_parts = []
        for c in calls:
            name, args = c.get("name"), dict(c.get("args", {}) or {})
            result = _dispatch(name, args)
            entry = {"tool": name, "input": args,
                     "result_summary": _summarize(name, result)}
            if name == "run_sql" and isinstance(result, dict) \
                    and "rows" in result:
                entry["rows"] = result["rows"][:50]
                entry["columns"] = result.get("columns", [])
            tool_calls.append(entry)
            fr_parts.append({"functionResponse": {
                "name": name,
                "response": {"result": json.loads(
                    json.dumps(result, default=str)[:6000])}}})
            if name in TERMINAL:
                terminal = {"action": name, **args}
        contents.append({"role": "user", "parts": fr_parts})
        if terminal:
            break

    return {"id": qid, "question": question, "tool_calls": tool_calls,
            "terminal": terminal or {"action": "no_decision"},
            "usage": usage}
