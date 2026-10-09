"""
Deterministic baseline agent (Phase 4).

No LLM, no API, $0. Picks metrics by keyword overlap with the question,
guesses time cuts from month/quarter words, always answers, never clarifies
or refuses. Emits the identical trace schema as the LLM backends so score.py
measures it the same way.

The point: establish the floor. Anything an LLM scores above this is the
marginal value of the model; anything at or below it is the semantic layer
doing the work. A naive agent SHOULD ace straightforward questions and
faceplant on traps and ambiguity — if it doesn't, the golden set is too easy.
"""
from __future__ import annotations

import re

import tools

STOPWORDS = {
    "what", "was", "were", "the", "our", "how", "many", "much", "did",
    "does", "for", "and", "are", "with", "from", "there", "their",
    "they", "them", "that", "this", "these", "have", "has", "had",
    "which", "who", "whom", "will", "would", "should", "could", "can",
    "all", "any", "you", "your", "into", "over", "under", "between",
    "through", "during", "each", "per", "its", "than", "then", "also",
    "just", "like", "get", "got", "make", "made", "use", "used",
}

MONTHS = {
    "january": "2026-01", "february": "2026-02", "march": "2026-03",
    "april": "2026-04", "may": "2026-05", "june": "2026-06",
}
QUARTERS = {
    "q1": (["2026-01", "2026-02", "2026-03"], "Q1"),
    "q2": (["2026-04", "2026-05", "2026-06"], "Q2"),
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", text.lower())
            if t not in STOPWORDS and len(t) > 2}


def pick_metric(question: str) -> str:
    """Highest keyword overlap with metric name (3x) + description."""
    qt = _tokens(question)
    best, best_score = None, -1
    for m in tools.list_metrics():
        name_toks = set(m["name"].split("_"))
        desc_toks = _tokens(m.get("description", ""))
        score = 3 * len(qt & name_toks) + len(qt & desc_toks)
        if score > best_score:
            best, best_score = m["name"], score
    return best


def detect_cut(question: str, metric: str):
    """Returns (dimensions, grain, cut) where cut is None or a dict with
    'months' and optional 'label'."""
    q = question.lower()
    desc = tools.describe_metric(metric)
    if "error" in desc:
        return None, None, None
    dims = {d["name"]: d for d in desc.get("dimensions", [])}
    time_dim = next((n for n, d in dims.items() if d.get("time_grain")), None)

    for word, mkey in MONTHS.items():
        if re.search(rf"\b{word}\b", q) and time_dim:
            return [time_dim], "month", {"months": [mkey]}
    for qword, (months, label) in QUARTERS.items():
        if re.search(rf"\b{qword}\b", q) and time_dim:
            return [time_dim], "month", {"months": months, "label": label}
    m = re.search(r"\bby (\w+)\b", q)
    if m and m.group(1) in dims:
        return [m.group(1)], None, None
    return None, None, None


def _month_key(v) -> str:
    return v.strftime("%Y-%m") if hasattr(v, "strftime") else str(v)[:7]


def _fmt(v) -> str:
    f = float(v)
    if abs(f) < 1 and f != 0:
        return f"{f:.4f}"
    if isinstance(v, float):
        return f"{f:.2f}"
    return str(v)


def run_question(qid: str, question: str) -> dict:
    """Run one golden question deterministically. Same trace schema as the
    LLM backends."""
    tool_calls: list[dict] = []
    metric = pick_metric(question)
    dimensions, grain, cut = detect_cut(question, metric)
    result = tools.query_metric(metric, dimensions, grain)
    entry = {"tool": "query_metric",
             "input": {"metric": metric, "dimensions": dimensions, "grain": grain},
             "result_summary": f"rows={len(result.get('rows', []))}"
                               if "rows" in result else f"error: {result.get('error')}"[:120]}
    if "rows" in result:
        entry["rows"] = result["rows"][:200]
        entry["columns"] = result.get("columns", [])
    tool_calls.append(entry)

    # interpret rows like the golden answer computer does
    answer_text = f"{metric} = ?"
    if "rows" in result and result["rows"]:
        rows = result["rows"]
        if cut and cut.get("months"):
            wanted = set(cut["months"])
            series = {_month_key(r[0]): r[1] for r in rows if len(r) >= 2}
            if len(wanted) == 1:
                mk = next(iter(wanted))
                val = series.get(mk, 0)
                answer_text = f"{metric} ({mk}) = {_fmt(val)}"
            else:
                total = sum(float(series.get(m, 0) or 0) for m in wanted)
                label = cut.get("label", "period")
                answer_text = f"{metric} ({label}) = {_fmt(total)}"
        elif dimensions:
            pairs = ", ".join(f"{r[0]}: {_fmt(r[1])}" for r in rows if len(r) >= 2)
            answer_text = f"{metric} by {dimensions[0]} = {pairs}"
        else:
            answer_text = f"{metric} = {_fmt(rows[0][0])}"

    return {
        "id": qid,
        "question": question,
        "tool_calls": tool_calls,
        "terminal": {"action": "submit_answer",
                     "answer_text": answer_text,
                     "metric_used": metric},
        "usage": {},
    }
