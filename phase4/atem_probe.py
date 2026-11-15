"""Probe: hand-render the ATEM prompt for one harness question and generate.

Renders the prompt exactly as the Glimmer chat template would (system block
with tool defs + valid-recipient list, user block), but ends with the
reasoning channel PREFILLED (<|start|>assistant to=self<|message|>).
The model's stop list includes <|message|>, so a bare <|start|>assistant
generation prompt stalls after the model emits the channel header — the
channel must be prefilled for the model to produce reasoning text.

Usage: OLLAMA_BASE_URL=... python3 atem_probe.py [qid]
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent import SYSTEM, TOOL_DEFS  # noqa: E402

BASE_URL = os.environ["OLLAMA_BASE_URL"]
MODEL = "hf.co/meta-models/Muse-Glimmer-30B-GGUF:Muse-Glimmer-30B-KQuant-17GB-Q4_K_M"


def render_tool_defs(tools):
    out = []
    out.append("In this environment you have access to a set of tools you "
               "can use to answer the user's question.\n\n")
    out.append('You can invoke a function by writing a "<atem:function_calls>" '
               "block like the following:\n")
    out.append('<atem:function_calls>\n<atem:invoke name="$FUNCTION_NAME">\n'
               '<atem:parameter name="$PARAMETER_NAME">$PARAMETER_VALUE</atem:parameter>\n'
               "...\n</atem:invoke>\n</atem:function_calls>\n\n")
    out.append("String and scalar parameters should be specified as is, "
               "while lists and objects should use JSON format. Note that "
               "spaces for string values are not stripped. The output is "
               "not expected to be valid XML and is parsed with regular "
               "expressions.\n")
    out.append("Here are the functions available in JSONSchema format:\n")
    out.append("// Tool metadata\n")
    seen = []
    for t in tools:
        tns = t["name"].split(".")[0]
        if tns not in seen:
            seen.append(tns)
    for tns in seen:
        out.append(json.dumps({"name": tns, "description": ""}) + "\n")
    out.append("// Function schemas")
    for t in tools:
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


def render_system_meta(tools):
    recipients = ['"self"']
    seen = []
    for t in tools:
        tns = t["name"].split(".")[0]
        if tns not in seen:
            seen.append(tns)
    for tns in seen:
        recipients.append('"' + tns + '.*"')
    recipients.append('"user"')
    return "# Valid recipients: " + ", ".join(recipients) + "."


def build_prompt(question: str, prefill: str = " to=self<|message|>") -> str:
    sys_text = SYSTEM
    parts = ["<|start|>system<|message|>", sys_text]
    if "reasoning strength" not in sys_text.lower():
        parts.append("\n\nReasoning strength: high.")
    parts.append("\n\n")
    parts.append(render_tool_defs(TOOL_DEFS))
    parts.append("\n\n")
    parts.append(render_system_meta(TOOL_DEFS))
    parts.append("<|eot|>")
    parts.append("<|start|>user<|message|>")
    parts.append(question)
    parts.append("<|eot|>")
    parts.append("<|start|>assistant")
    parts.append(prefill)
    return "".join(parts)


def generate(prompt: str, num_predict: int = 2000) -> dict:
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": True,
        # raw: pass the hand-rendered ATEM prompt verbatim. Without this,
        # Ollama wraps the prompt (template/thinking handling) and the model
        # sees a user message containing our prompt text, not the ATEM
        # scaffold — it then re-emits the channel header and stops.
        "raw": True,
        "options": {"num_ctx": 8192, "num_predict": num_predict},
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/generate", data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/126.0.0.0 Safari/537.36"},
        method="POST")
    full = []
    done = {}
    with urllib.request.urlopen(req, timeout=600) as resp:
        for raw in resp:
            try:
                chunk = json.loads(raw.decode())
            except json.JSONDecodeError:
                continue
            if chunk.get("response"):
                full.append(chunk["response"])
                sys.stdout.write(chunk["response"])
                sys.stdout.flush()
            if chunk.get("done"):
                done = chunk
    return {"text": "".join(full), "done_reason": done.get("done_reason"),
            "eval_count": done.get("eval_count"),
            "prompt_eval_count": done.get("prompt_eval_count")}


if __name__ == "__main__":
    qid = sys.argv[1] if len(sys.argv) > 1 else "Q001"
    import yaml
    qs = yaml.safe_load(open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "../phase3/golden_questions.yml")))["questions"]
    q = next(x for x in qs if x["id"] == qid)
    prompt = build_prompt(q["question"])
    print(f"--- prompt chars: {len(prompt)} ---", file=sys.stderr)
    result = generate(prompt)
    print("\n\n=== DONE ===", file=sys.stderr)
    print(f"done_reason={result['done_reason']} eval={result['eval_count']} "
          f"prompt_eval={result['prompt_eval_count']}", file=sys.stderr)
    print(f"output chars={len(result['text'])}", file=sys.stderr)
