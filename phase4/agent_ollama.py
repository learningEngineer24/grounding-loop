"""
Ollama backend for the agent under test (Phase 4).

Mirrors agent.py's interface — run_question() returns the identical trace
schema — but drives the loop with Ollama's OpenAI-compatible Chat
Completions API over REST, pointed at a rented GPU pod (RunPod) serving
the model. No auth: the pod's Ollama endpoint is unauthenticated, reached
through RunPod's proxy URL.

The system prompt, tools, and terminal actions are the same as the
Anthropic backend; only the transport differs, so backend deltas measure
the model, not the harness. Tool definitions are converted verbatim from
agent.TOOL_DEFS so the backends cannot drift apart.

The endpoint URL comes from the OLLAMA_BASE_URL environment variable
(e.g. https://<pod>-11434.proxy.runpod.net); the model name from the
--model flag (e.g. hf.co/meta-models/Muse-Glimmer-30B-GGUF:...Q4_K_M).
"""
from __future__ import annotations

import json
import os
import urllib.request

import tools  # noqa: E402
from agent import SYSTEM, TOOL_DEFS, TERMINAL, MAX_TURNS, _dispatch, _summarize  # noqa: E402

BASE_URL = os.environ.get("OLLAMA_BASE_URL", "")
if not BASE_URL:
    raise RuntimeError("OLLAMA_BASE_URL is not set")

# Chat Completions takes function tools nested, unlike Responses.
OPENAI_TOOLS = [
    {"type": "function",
     "function": {"name": d["name"],
                  "description": d["description"],
                  "parameters": d["input_schema"]}}
    for d in TOOL_DEFS
]


def _post(model: str, messages: list) -> dict:
    """One chat/completions call, streamed. Retries transient errors;
    surfaces the API's error body on hard failures. Returns the accumulated
    assistant message dict.

    Streaming matters: a reasoning model can think for minutes with no
    output, and the proxy in front of the pod drops silent connections.
    SSE chunks keep the connection alive."""
    import time as _time
    import urllib.error as _urlerror

    body = json.dumps({
        "model": model,
        "max_tokens": 1500,
        "stream": True,
        "stream_options": {"include_usage": True},
        # Keep the KV cache small: the harness prompts fit in 8k tokens,
        # and the model's 32k default context would preallocate a KV
        # buffer that risks OOM on a 48GB card alongside 17GB of weights.
        "options": {"num_ctx": 8192},
        "messages": [{"role": "system", "content": SYSTEM}] + messages,
        "tools": OPENAI_TOOLS,
    }).encode("utf-8")
    last_err = None
    for attempt in range(4):
        req = urllib.request.Request(
            f"{BASE_URL}/v1/chat/completions",
            data=body, headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/126.0.0.0 Safari/537.36"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                return _read_stream(resp)
        except _urlerror.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            last_err = f"HTTP {e.code}: {detail}"
            if e.code in (429, 500, 502, 503) and attempt < 3:
                _time.sleep(2 ** attempt * 5)
                continue
            raise RuntimeError(last_err) from None
    raise RuntimeError(last_err or "chat/completions failed")


def _read_stream(resp) -> dict:
    """Accumulate an SSE chat-completions stream into one message dict."""
    import json as _json

    content_parts: list = []
    tool_calls: dict = {}
    usage: dict = {}
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = _json.loads(data)
        except _json.JSONDecodeError:
            continue
        if "usage" in chunk and chunk["usage"]:
            usage = chunk["usage"]
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            if delta.get("content"):
                content_parts.append(delta["content"])
            for tc in delta.get("tool_calls", []):
                idx = tc.get("index", 0)
                entry = tool_calls.setdefault(idx, {
                    "id": tc.get("id", ""), "type": "function",
                    "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    entry["id"] = tc["id"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    entry["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    entry["function"]["arguments"] += fn["arguments"]
    msg: dict = {"role": "assistant",
                 "content": "".join(content_parts)}
    if tool_calls:
        msg["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]
    return {"message": msg, "usage": usage}


def run_question(model: str, qid: str, question: str) -> dict:
    """Run one golden question via Ollama function calling. Same trace
    schema as agent.run_question."""
    messages: list = [{"role": "user", "content": question}]
    tool_calls: list[dict] = []
    terminal: dict | None = None
    usage = {"input_tokens": 0, "output_tokens": 0}

    for _ in range(MAX_TURNS):
        resp = _post(model, messages)
        u = resp.get("usage", {})
        usage["input_tokens"] += u.get("prompt_tokens", 0)
        usage["output_tokens"] += u.get("completion_tokens", 0)

        msg = resp.get("message", {})
        calls = msg.get("tool_calls", []) or []
        text = msg.get("content") or ""

        # content is always present (possibly "") — Ollama rejects a
        # message whose content is missing/null when it is sent back.
        assistant_msg: dict = {"role": "assistant", "content": text}
        if calls:
            assistant_msg["tool_calls"] = calls
        messages.append(assistant_msg)

        if not calls:
            messages.append({"role": "user", "content":
                "You must finish with exactly one of: submit_answer, "
                "ask_clarify, refuse."})
            continue

        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}")
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
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id"),
                "content": json.dumps(result, default=str)[:4000]})
            if name in TERMINAL:
                terminal = {"action": name, **args}
        if terminal:
            break

    return {"id": qid, "question": question, "tool_calls": tool_calls,
            "terminal": terminal or {"action": "no_decision"},
            "usage": usage}
