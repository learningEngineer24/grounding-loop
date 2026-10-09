"""
Score harness traces against the locked golden answers (Phase 4).

Dimensions scored per question:
  behavior   — did the agent pick the right terminal action?
               (submit_answer vs ask_clarify vs refuse vs expected_behavior)
  numeric    — for the 42 answerable: does the reported number match the
               golden value within tolerance?
  disclosure — for the 12 traps: does the answer carry the definitional
               disclosure (keyword check on the answer text)?
  metric     — did the agent query the governed metric(s) the golden set names?

Usage: .venv/bin/python score.py [--traces traces.jsonl]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent

# Trap disclosures -> required keywords (case-insensitive, any-of per trap
# unless marked ALL). Derived from the `disclosure` field in golden_questions.yml.
DISCLOSURE_KEYWORDS = {
    "Q101": ["settled"],
    "Q102": ["event date", "event dates", "netting"],
    "Q103": ["paid"],
    "Q104": ["actual"],
    "Q105": ["free", "add-on", "addon"],
    "Q106": ["gross"],
    "Q107": ["simplification", "cancelled"],
    "Q108": ["pending"],
    "Q110": ["fresh", "late", "revis"],
    "Q111": ["total_payments", "settled_revenue"],  # ALL required
    "Q112": ["total_payments", "status"],
    "Q208": ["settled", "governed"],
    "Q113": ["total_payments", "settled_revenue"],
    "Q114": ["settled"],
    "Q116": ["pending"],
    "Q117": ["settled"],
    "Q118": ["event date", "netting"],
    "Q121": ["actual"],
    "Q123": ["preliminary", "late"],
    "Q124": ["trial", "cancelled"],
    "Q128": ["simplification", "cancelled"],
    "Q129": ["cancelled"],
    "Q131": ["free", "add-on", "addon"],
    "Q134": ["discount", "gross"],
    "Q135": ["all orders", "settlement"],
    "Q137": ["gross", "discount"],
    "Q138": ["final", "window"],
    "Q139": ["preliminary", "late"],
    "Q140": ["restatement", "late"],
    "Q141": ["restat", "late"],
    "Q142": ["restat", "late"],
    "Q217": ["settled", "governed"],
    "Q218": ["pending", "governed", "definition"],
    "Q219": ["paid", "governed", "trial"],
    "Q227": ["governed"],
}
DISCLOSURE_ALL = {"Q111"}

MONEY_TOL = 0.02
RATE_TOL = 1e-4


def close(a, b) -> bool:
    a, b = float(a), float(b)
    if float(int(b)) == b and abs(a - b) < 0.5 and b < 1e6:
        return True  # counts: exact
    tol = RATE_TOL if abs(b) < 1 else MONEY_TOL
    return abs(a - b) <= tol


def numbers_in(text: str) -> list[float]:
    out = []
    for m in re.finditer(r"\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(%?)", text):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.append(v)
        if m.group(2) == "%":
            out.append(v / 100)  # "5.2%" also counts as 0.052
    return out


def norm_key(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m")
    return str(v)


def agent_rows_dict(trace) -> dict:
    """Last query_metric call -> {normalized_key: value} (scalar -> {'_scalar': v})."""
    queries = [c for c in trace["tool_calls"] if c["tool"] == "query_metric"
               and "rows" in c]
    if not queries:
        return {}
    q = queries[-1]
    rows = q["rows"]
    if len(q.get("columns", [])) == 1 and len(rows) == 1 and len(rows[0]) == 1:
        return {"_scalar": rows[0][0]}
    return {norm_key(r[0]): r[1] for r in rows if len(r) >= 2}


def score_one(trace, q, ans) -> dict:
    qid = q["id"]
    expected_behavior = q["expected_behavior"]
    terminal = (trace.get("terminal") or {}).get("action", "no_decision")
    want_action = {"answer": "submit_answer",
                   "answer_with_disclosure": "submit_answer",
                   "clarify": "ask_clarify",
                   "refuse": "refuse"}[expected_behavior]
    behavior_ok = terminal == want_action

    result = {"id": qid, "category": q["category"],
              "expected_behavior": expected_behavior,
              "terminal": terminal, "behavior_ok": behavior_ok,
              "numeric_ok": None, "metric_ok": None, "disclosure_ok": None}

    expected = ans["expected"]
    if expected is None:
        return result  # clarify / refuse — behavior is the whole score

    # --- metric selection ---
    golden_metrics = q.get("metric") or q.get("metrics")
    if isinstance(golden_metrics, str):
        golden_metrics = [golden_metrics]
    queried = [c["input"]["metric"] for c in trace["tool_calls"]
               if c["tool"] == "query_metric" and "metric" in c["input"]]
    result["metric_ok"] = all(m in queried for m in golden_metrics)

    # --- numeric: what the agent REPORTED ---
    text = (trace.get("terminal") or {}).get("answer_text", "")
    reported = numbers_in(text)
    if isinstance(expected, dict):
        exp_vals = list(expected.values())
        result["numeric_ok"] = all(
            any(close(n, e) for n in reported) for e in exp_vals)
    else:
        result["numeric_ok"] = any(close(n, expected) for n in reported)

    # --- disclosure (expected_behavior gate: 11 traps + Q208) ---
    if q.get("expected_behavior") == "answer_with_disclosure" and qid in DISCLOSURE_KEYWORDS:
        kws = DISCLOSURE_KEYWORDS[qid]
        low = text.lower()
        hits = [k for k in kws if k in low]
        result["disclosure_ok"] = (len(hits) == len(kws)
                                   if qid in DISCLOSURE_ALL else bool(hits))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", default="traces.jsonl")
    args = ap.parse_args()

    questions = {q["id"]: q for q in yaml.safe_load(
        (BASE.parent / "phase3" / "golden_questions.yml").read_text())["questions"]}
    answers = yaml.safe_load(
        (BASE.parent / "phase3" / "golden_answers.yml").read_text())["answers"]
    traces = [json.loads(l) for l in (BASE / args.traces).read_text().splitlines()]

    scored = [score_one(t, questions[t["id"]], answers[t["id"]]) for t in traces]

    def pct(xs):
        xs = [x for x in xs if x is not None]
        return f"{sum(xs)}/{len(xs)} = {100 * sum(xs) / len(xs):.0f}%" if xs else "n/a"

    print(f"## Harness results — {len(scored)} questions\n")
    print(f"behavior accuracy : {pct([s['behavior_ok'] for s in scored])}")
    ans = [s for s in scored if s["numeric_ok"] is not None]
    print(f"numeric accuracy  : {pct([s['numeric_ok'] for s in ans])} (42 answerable)")
    print(f"metric selection  : {pct([s['metric_ok'] for s in ans])}")
    disc = [s for s in scored if s["disclosure_ok"] is not None]
    print(f"disclosure rate   : {pct([s['disclosure_ok'] for s in disc])} (12 disclosure-expected)")
    for cat in ["straightforward", "trap", "ambiguous"]:
        c = [s for s in scored if s["category"] == cat]
        print(f"  {cat:15s} behavior {pct([s['behavior_ok'] for s in c])}", end="")
        ca = [s for s in c if s["numeric_ok"] is not None]
        if ca:
            print(f"  numeric {pct([s['numeric_ok'] for s in ca])}", end="")
        print()

    print("\n## Failures")
    for s in scored:
        problems = [k for k in ("behavior_ok", "numeric_ok", "metric_ok",
                                "disclosure_ok") if s[k] is False]
        if problems:
            t = next(x for x in traces if x["id"] == s["id"])
            term = t.get("terminal") or {}
            txt = term.get("answer_text") or term.get("question") or term.get("reason") or ""
            print(f"- {s['id']} [{s['category']}] failed: {', '.join(problems)} "
                  f"(terminal={s['terminal']})")
            print(f"    -> {txt[:160]}")

    (BASE / "scores.json").write_text(json.dumps(scored, indent=2))
    print("\nwrote phase4/scores.json")


if __name__ == "__main__":
    sys.exit(main())
