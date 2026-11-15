"""
ATEM backend for the agent under test (Phase 4) — Muse Glimmer 30B.

Glimmer does not speak OpenAI function calling. It speaks Meta's ATEM
protocol, defined by its chat template: the assistant addresses each
message to a recipient channel — `to=self` for reasoning, `to=<tool>` for
a tool call, `to=user` for the final answer — and tool calls are
<atem:function_calls> XML blocks, not JSON function calls.

This backend therefore drives the loop as raw text through Ollama's
/api/generate (raw: true, so Ollama passes our hand-rendered prompt
verbatim) instead of /api/chat or /v1/chat/completions:

  1. Prompt ends with `<|start|>assistant to=self<|message|>` — the
     reasoning channel PREFILLED. The model's stop list includes
     <|message|>, so a bare `<|start|>assistant` generation prompt stalls
     after the model emits the channel header; prefill is required.
  2. The model generates reasoning until it emits <|eom|> (or a stop).
  3. Prompt += reasoning + <|eom|> + `<|start|>assistant`; the model
     emits the next channel header (` to=<tool>` or ` to=user`) and stops
     at <|message|>.
  4. Prompt += header + `<|message|>`; the model emits the tool-call XML
     (or answer text) and stops at <|start|> / <|eot|>.
  5. Tool calls are parsed out of the XML, dispatched through the same
     _dispatch as every other backend, and the result is appended as a
     tool message. Loop back to (1) until a terminal tool fires.

The trace schema is identical to agent.run_question so score.py works
unchanged. The system prompt, tools, and terminal actions are the same as
the Anthropic backend; only the transport differs.

Endpoint: OLLAMA_BASE_URL (e.g. https://<pod>-11434.proxy.runpod.net).
Model: the Glimmer GGUF name (harness default).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

import tools  # noqa: E402
from agent import SYSTEM, TOOL_DEFS, TERMINAL, MAX_TURNS, _dispatch, _summarize  # noqa: E402

BASE_URL = os.environ.get("OLLAMA_BASE_URL", "")
if not BASE_URL:
    raise RuntimeError("OLLAMA_BASE_URL is not set")

MODEL_DEFAULT = ("hf.co/meta-models/Muse-Glimmer-30B-GGUF:"
                 "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M")

# The ATEM tool-call block the model emits.
_INVOKE_RE = re.compile(
    r'<atem:function_calls>\s*<atem:invoke name="([^"]+)">(.*?)</atem:invoke>\s*</atem:function_calls>',
    re.DOTALL)
_PARAM_RE = re.compile(
    r'<atem:parameter name="([^"]+)">(.*?)</atem:parameter>',
    re.DOTALL)
_CHANNEL_RE = re.compile(r'^\s*to=([A-Za-z0-9_.]+)')


def _render_tool_defs() -> str:
    out = ["In this environment you have access to a set of tools you can "
           "use to answer the user's question.\n\n",
           'You can invoke a function by writing a "<atem:function_calls>" '
           "block like the following:\n",
           '<atem:function_calls>\n<atem:invoke name="$FUNCTION_NAME">\n'
           '<atem:parameter name="$PARAMETER_NAME">$PARAMETER_VALUE</atem:parameter>\n'
           "...\n</atem:invoke>\n</atem:function_calls>\n\n",
           "String and scalar parameters should be specified as is, while "
           "lists and objects should use JSON format. Note that spaces for "
           "string values are not stripped. The output is not expected to "
           "be valid XML and is parsed with regular expressions.\n",
           "Here are the functions available in JSONSchema format:\n",
           "// Tool metadata\n"]
    seen: list[str] = []
    for t in TOOL_DEFS:
        tns = t["name"].split(".")[0]
        if tns not in seen:
            seen.append(tns)
    for tns in seen:
        out.append(json.dumps({"name": tns, "description": ""}) + "\n")
    out.append("// Function schemas")
    for t in TOOL_DEFS:
        out.append("\n" + json.dumps({
            "name": t["name"], "description": t["description"],
            "parameters": t["input_schema"]}))
    out.append("\n\nHere's an example of how to call a function in the "
               "tool set:\n")
    out.append("(If the tool namespace is not specified, invoke the function "
               "directly as `example_function_name` rather than "
               "`example_tool_name.example_function_name`)\n\n")
    out.append("to=example_tool_name.example_function_name\n\n")
    out.append('<atem:function_calls>\n<atem:invoke name="example_tool_name.example_function_name">\n')
    out.append('<atem:parameter name="example_parameter_1">value_1</atem:parameter>\n')
    out.append('<atem:parameter name="example_parameter_2">This is the value for the second parameter\n'
               "that can span\nmultiple lines\n</atem:parameter>\n")
    out.append("</atem:invoke>\n</atem:function_calls>")
    return "".join(out)


def _render_system_meta() -> str:
    recipients = ['"self"']
    seen: list[str] = []
    for t in TOOL_DEFS:
        tns = t["name"].split(".")[0]
        if tns not in seen:
            seen.append(tns)
    for tns in seen:
        recipients.append('"' + tns + '.*"')
    recipients.append('"user"')
    return "# Valid recipients: " + ", ".join(recipients) + "."


def _build_prompt(question: str) -> str:
    parts = ["<|start|>system<|message|>", SYSTEM]
    if "reasoning strength" not in SYSTEM.lower():
        parts.append("\n\nReasoning strength: high.")
    parts.append("\n\n")
    parts.append(_render_tool_defs())
    parts.append("\n\n")
    parts.append(_render_system_meta())
    parts.append("<|eot|>")
    parts.append("<|start|>user<|message|>")
    parts.append(question)
    parts.append("<|eot|>")
    return "".join(parts)


def _generate(prompt: str, num_predict: int) -> tuple[str, dict]:
    """One raw /api/generate call, streamed. Returns (text, usage) where
    usage counts only newly evaluated prompt tokens (cached prefix excluded)
    plus generated tokens. Retries transient connection drops."""
    body = json.dumps({
        "model": MODEL_DEFAULT, "prompt": prompt, "stream": True,
        "raw": True,
        "options": {"num_ctx": 8192, "num_predict": num_predict},
    }).encode()
    last_err = None
    for attempt in range(4):
        req = urllib.request.Request(
            f"{BASE_URL}/api/generate", data=body,
            headers={"Content-Type": "application/json",
                     "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/126.0.0.0 Safari/537.36"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                chunks: list[str] = []
                done: dict = {}
                for raw in resp:
                    try:
                        chunk = json.loads(raw.decode("utf-8", "replace"))
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("response"):
                        chunks.append(chunk["response"])
                    if chunk.get("done"):
                        done = chunk
                usage = {
                    "input_tokens": (done.get("prompt_eval_count", 0)
                                     - done.get("prompt_eval_cached_count", 0)),
                    "output_tokens": done.get("eval_count", 0)}
                return "".join(chunks), usage
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_err = f"connection dropped: {e}"
            time.sleep(2 ** attempt * 5)
            continue
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"HTTP {e.code}: {detail}") from None
    raise RuntimeError(last_err or "generate failed")


def _parse_tool_call(text: str) -> tuple[str, dict] | None:
    """Parse one ATEM <atem:function_calls> block. Returns (name, args) or
    None when the text carries no well-formed call."""
    m = _INVOKE_RE.search(text)
    if not m:
        return None
    name, body = m.group(1), m.group(2)
    args: dict = {}
    for pm in _PARAM_RE.finditer(body):
        k, v = pm.group(1), pm.group(2)
        if v == "true":
            args[k] = True
        elif v == "false":
            args[k] = False
        elif v == "null":
            args[k] = None
        else:
            try:
                args[k] = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                args[k] = v
    return name, args


def run_question(model: str, qid: str, question: str) -> dict:
    """Run one golden question via the ATEM text loop. Same trace schema
    as agent.run_question."""
    global MODEL_DEFAULT
    MODEL_DEFAULT = model
    prompt = _build_prompt(question)
    tool_calls: list[dict] = []
    terminal: dict | None = None
    usage = {"input_tokens": 0, "output_tokens": 0}

    for _ in range(MAX_TURNS):
        # (1) Reasoning, channel prefilled.
        reasoning, u = _generate(prompt + "<|start|>assistant to=self<|message|>",
                                 num_predict=2000)
        usage["input_tokens"] += u["input_tokens"]
        usage["output_tokens"] += u["output_tokens"]
        # <|eom|> is not a stop string, so the model may emit it itself;
        # strip a trailing one rather than doubling it in the transcript.
        if reasoning.endswith("<|eom|>"):
            reasoning = reasoning[:-len("<|eom|>")]
        prompt += ("<|start|>assistant to=self<|message|>" + reasoning
                   + "<|eom|>")

        # (2) Next channel: the model picks tool / user / more reasoning.
        header, u = _generate(prompt + "<|start|>assistant", num_predict=50)
        usage["input_tokens"] += u["input_tokens"]
        usage["output_tokens"] += u["output_tokens"]
        m = _CHANNEL_RE.match(header)
        if not m:
            break
        recipient = m.group(1)

        # (3) The channel's content.
        content, u = _generate(prompt + "<|start|>assistant" + header
                               + "<|message|>", num_predict=1500)
        usage["input_tokens"] += u["input_tokens"]
        usage["output_tokens"] += u["output_tokens"]
        if content.endswith("<|eom|>"):
            content = content[:-len("<|eom|>")]
        prompt += "<|start|>assistant" + header + "<|message|>" + content

        if recipient == "self":
            prompt += "<|eom|>"
            continue
        if recipient == "user":
            prompt += "<|eot|>"
            break
        parsed = _parse_tool_call(content)
        if parsed is None:
            prompt += "<|eot|>"
            break
        name, args = parsed
        result = _dispatch(name, args)
        entry = {"tool": name, "input": args,
                 "result_summary": _summarize(name, result)}
        if name == "query_metric" and isinstance(result, dict) \
                and "rows" in result:
            entry["rows"] = result["rows"][:200]
            entry["columns"] = result.get("columns", [])
        tool_calls.append(entry)
        prompt += "<|eot|>"
        prompt += ('<|start|>tool ' + name + '<|message|>'
                   '<tool_output name="' + name + '">\n'
                   + json.dumps(result, default=str)[:4000]
                   + '\n</tool_output><|eot|>')
        if name in TERMINAL:
            terminal = {"action": name, **args}
            break

    return {"id": qid, "question": question, "tool_calls": tool_calls,
            "terminal": terminal or {"action": "no_decision"},
            "usage": usage}
