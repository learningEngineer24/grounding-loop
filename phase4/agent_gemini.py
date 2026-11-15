"""
Gemini backend for the agent under test (Phase 4).

Mirrors agent.py's interface — run_question() returns the identical trace
schema — but drives the loop with Gemini's function calling over REST.
Auth goes through the stored custom.gemini connector via the authd surrogate
exchange (see ~/workspace/skills/gemini/SKILL.md); this file never sees the
real key.

The system prompt, tools, and terminal actions are the same as the Anthropic
backend; only the transport differs, so backend deltas measure the model,
not the harness.
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
from agent import SYSTEM, TERMINAL, MAX_TURNS, _dispatch, _summarize  # noqa: E402

HOST = "generativelanguage.googleapis.com"
CREDENTIAL = "custom.gemini"

# free tier ≈ 20 RPM → one call per 3s; pace at 4s to stay under it
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

FUNC_DECLS = [
    {"name": "list_metrics",
     "description": "List every governed metric: name, type, description.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "describe_metric",
     "description": "Show the full governed definition of one metric: model, aggregation, row filter, available dimensions.",
     "parameters": {"type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"]}},
    {"name": "query_metric",
     "description": "Compile a governed metric to SQL and run it against the warehouse. dimensions: list of dimension names; grain: 'month' for time dimensions.",
     "parameters": {"type": "object",
                    "properties": {
                        "metric": {"type": "string"},
                        "dimensions": {"type": "array", "items": {"type": "string"}},
                        "grain": {"type": "string"}},
                    "required": ["metric"]}},
    {"name": "submit_answer",
     "description": "Terminal. Submit your final answer: the number(s), the governed metric used, and any one-sentence disclosure.",
     "parameters": {"type": "object",
                    "properties": {
                        "answer_text": {"type": "string"},
                        "metric_used": {"type": "string"}},
                    "required": ["answer_text", "metric_used"]}},
    {"name": "ask_clarify",
     "description": "Terminal. The question is ambiguous — ask exactly what you need to answer it.",
     "parameters": {"type": "object",
                    "properties": {"question": {"type": "string"}},
                    "required": ["question"]}},
    {"name": "refuse",
     "description": "Terminal. The question cannot be answered from the governed layer — state why.",
     "parameters": {"type": "object",
                    "properties": {"reason": {"type": "string"}},
                    "required": ["reason"]}},
]


def _generate(model: str, contents: list) -> dict:
    """One generateContent call. Retries transient errors; surfaces the API's
    error body on hard failures. Returns the raw response dict."""
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


def run_question(model: str, qid: str, question: str) -> dict:
    """Run one golden question via Gemini function calling. Same trace schema
    as agent.run_question."""
    contents: list = [{"role": "user", "parts": [{"text": question}]}]
    tool_calls: list[dict] = []
    terminal: dict | None = None
    usage = {"input_tokens": 0, "output_tokens": 0}

    for _ in range(MAX_TURNS):
        _pace()  # free tier ≈ 20 RPM; stay under it instead of tripping 429s
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
            if name == "query_metric" and isinstance(result, dict) \
                    and "rows" in result:
                entry["rows"] = result["rows"][:200]
                entry["columns"] = result.get("columns", [])
            tool_calls.append(entry)
            fr_parts.append({"functionResponse": {
                "name": name,
                "response": {"result": json.loads(
                    json.dumps(result, default=str)[:4000])}}})
            if name in TERMINAL:
                terminal = {"action": name, **args}
        contents.append({"role": "user", "parts": fr_parts})
        if terminal:
            break

    return {"id": qid, "question": question, "tool_calls": tool_calls,
            "terminal": terminal or {"action": "no_decision"},
            "usage": usage}
