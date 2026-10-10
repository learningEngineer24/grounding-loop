"""
Governed Anthropic backend for the agent under test (Phase 4).

Same system prompt, tools, terminal actions, and trace schema as agent.py —
the only difference is transport: this drives the Anthropic Messages API
over urllib through the stored custom.anthropic connector (surrogate
exchange; the real key is never visible here) instead of the SDK with an
env key.
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

HOST = "api.anthropic.com"
CREDENTIAL = "custom.anthropic"
API_VERSION = "2023-06-01"


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


def run_question(model: str, qid: str, question: str) -> dict:
    """Run one golden question via the Anthropic API. Same trace schema as
    agent.run_question."""
    messages: list[dict] = [{"role": "user", "content": question}]
    tool_calls: list[dict] = []
    terminal: dict | None = None
    usage = {"input_tokens": 0, "output_tokens": 0}
    seen_restatements: list[str] = []  # restatement notes from query_metric results

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
                if block["name"] == "query_metric" and isinstance(result, dict) \
                        and "rows" in result:
                    entry["rows"] = result["rows"][:200]
                    entry["columns"] = result.get("columns", [])
                    note = result.get("restatement_note")
                    if note and note not in seen_restatements:
                        seen_restatements.append(note)
                tool_calls.append(entry)
                pending_results.append({
                    "type": "tool_result", "tool_use_id": block["id"],
                    "content": json.dumps(result, default=str)[:4000]})
                if block["name"] in TERMINAL:
                    terminal = {"action": block["name"],
                                **(block.get("input", {}) or {})}
                    # Deterministic answer-level disclosure (serving layer):
                    # if any query in this trace touched a restated period,
                    # attach the governance note to the answer. Known-knowns
                    # are attached by the platform, not left to agent
                    # discretion.
                    if block["name"] == "submit_answer" and seen_restatements:
                        raw = terminal.get("answer_text", "")
                        caveat = (" [Governance note: "
                                  + " ".join(seen_restatements) + "]")
                        terminal["answer_text_raw"] = raw
                        terminal["answer_text"] = raw + caveat
                        terminal["system_caveat_appended"] = True
        messages.append({"role": "assistant", "content": assistant_blocks})
        if terminal:
            break
        if pending_results:
            messages.append({"role": "user", "content": pending_results})
        else:
            # Text-only turn: nudge back to the tools instead of crashing
            # on an empty user message (Anthropic 400).
            messages.append({"role": "user",
                             "content": "Continue: use one of the available tools "
                                        "(query_metric, get_period_status, list_restatements, "
                                        "describe_metric) or a terminal action."})

    return {"id": qid, "question": question, "tool_calls": tool_calls,
            "terminal": terminal or {"action": "no_decision"},
            "usage": usage}
