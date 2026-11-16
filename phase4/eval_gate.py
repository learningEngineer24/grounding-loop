"""
Eval gate (Phase 2) — repair + routing around the governed run.

The gate wraps one governed attempt per question:

  1. Initial attempt with the primary model. Grade it with the
     deterministic grader (score.score_one) — the same grader Phase 7
     uses, so the gate's decisions and the final scores cannot drift apart.
  2. Repair (if enabled): on failure, feed the grader's feedback back to
     the model for ONE retry. The feedback names which checks failed and
     one line of guidance each; it never reveals correct values, metric
     names, or the expected behavior. Cap: 1 repair attempt.
  3. Routing (if enabled, cheap legs only): on failure after repair,
     escalate the question to the frontier model *with the loop* — a fresh
     governed attempt by the frontier backend. The escalation's result
     stands. Escalated questions carry their frontier cost in the cheap
     leg's cost-per-correct.

Cost accounting: every attempt logs its tokens and dollars to the trace.
Loop overhead is a line item, not hidden. Glimmer's token cost is $0
(self-hosted); its pod rental is billed separately and noted, not folded
into the per-question token cost.

The returned trace keeps the standard schema (score.py works unchanged):
the top-level terminal/tool_calls are the final attempt's, usage is the
sum over all attempts, and a "gate" object carries the attempt history.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from costs import PRICES, SELF_HOSTED_MODELS, cost_usd, price_for  # noqa: F401
from score import score_one

BASE = Path(__file__).resolve().parent

CHEAP_BACKENDS = {"ember", "openrouter", "ollama", "atem"}

_CHECK_HINTS = {
    "behavior_ok": ("the terminal action was wrong — reconsider whether the "
                    "question is answerable as asked, or needs clarifying "
                    "or refusing instead of an answer."),
    "numeric_ok": ("the number you reported does not match the expected "
                   "value — re-check the query you ran and the rows it "
                   "returned."),
    "metric_ok": ("you queried the wrong metric — re-check the metric "
                  "definition before querying."),
    "disclosure_ok": ("your answer is missing the required disclosure "
                      "about what the number covers (e.g. settled vs "
                      "gross, pending, restatement) — say what the number "
                      "means."),
}

_QUESTIONS = None
_ANSWERS = None
_QA_FILES = (None, None)  # (questions path, answers path); None = golden set


def set_qa(questions_path, answers_path=None):
    """Point the gate's grader at a question set other than the golden set
    (e.g. the Phase 5 pilot set). answers_path defaults to the questions
    path with _questions.yml -> _answers.yml. Call before any run_gated."""
    global _QUESTIONS, _ANSWERS, _QA_FILES
    if answers_path is None:
        qp = str(questions_path)
        answers_path = (qp.replace("_questions.yml", "_answers.yml")
                        if "_questions.yml" in qp else
                        str(BASE.parent / "phase3" / "golden_answers.yml"))
    _QA_FILES = (str(questions_path), str(answers_path))
    _QUESTIONS = _ANSWERS = None


def _golden():
    global _QUESTIONS, _ANSWERS
    if _QUESTIONS is None:
        qfile, afile = _QA_FILES
        qfile = qfile or str(BASE.parent / "phase3" / "golden_questions.yml")
        afile = afile or str(BASE.parent / "phase3" / "golden_answers.yml")
        _QUESTIONS = {q["id"]: q for q in yaml.safe_load(
            Path(qfile).read_text())["questions"]}
        _ANSWERS = yaml.safe_load(Path(afile).read_text())["answers"]
    return _QUESTIONS, _ANSWERS


def grade(trace: dict, qid: str) -> dict:
    questions, answers = _golden()
    return score_one(trace, questions[qid], answers[qid])


def passed(verdict: dict) -> bool:
    return all(verdict.get(k) is not False for k in
               ("behavior_ok", "numeric_ok", "metric_ok", "disclosure_ok"))


def repair_feedback(verdict: dict) -> str:
    failed = [k for k in ("behavior_ok", "numeric_ok", "metric_ok",
                          "disclosure_ok") if verdict.get(k) is False]
    if not failed:
        return ""
    hints = " ".join(_CHECK_HINTS[k] for k in failed)
    return ("[Eval gate — repair attempt: your previous answer failed the "
            f"deterministic grader on: {', '.join(failed)}. {hints} "
            "Answer the original question again from scratch.]")


def _attempt(fn, qid, question, kind, backend, model):
    """Run one attempt, grading it. An exception becomes a failed attempt,
    never a crashed run."""
    try:
        trace = fn(qid, question)
    except Exception as e:  # noqa: BLE001 — the gate must survive a bad attempt
        trace = {"id": qid, "question": question, "tool_calls": [],
                 "terminal": {"action": "error", "detail": str(e)[:300]},
                 "usage": {}}
    verdict = grade(trace, qid)
    usage = trace.get("usage") or {}
    return {"kind": kind, "backend": backend, "model": model,
            "usage": usage, "cost_usd": round(cost_usd(model, usage), 6),
            "verdict": verdict, "trace": trace}


def run_gated(primary_fn, primary_backend, primary_model,
              escalate_fn, escalate_backend, escalate_model,
              qid, question, mode="both") -> dict:
    """Run one question through the gate. mode: repair | routing | both.
    Returns the final trace with a "gate" record attached."""
    repair_on = mode in ("repair", "both")
    routing_on = mode in ("routing", "both")
    can_route = (routing_on and primary_backend in CHEAP_BACKENDS
                 and escalate_fn is not None
                 and escalate_backend != primary_backend)

    attempts = []
    final = _attempt(primary_fn, qid, question, "initial",
                     primary_backend, primary_model)
    attempts.append(final)

    if not passed(final["verdict"]) and repair_on:
        note = repair_feedback(final["verdict"])
        repaired = _attempt(
            lambda q, qq: primary_fn(q, qq + "\n\n" + note),
            qid, question, "repair", primary_backend, primary_model)
        attempts.append(repaired)
        final = repaired

    if not passed(final["verdict"]) and can_route:
        escalated = _attempt(escalate_fn, qid, question, "escalation",
                             escalate_backend, escalate_model)
        attempts.append(escalated)
        final = escalated

    total_usage = {"input_tokens": sum(a["usage"].get("input_tokens", 0)
                                       for a in attempts),
                   "output_tokens": sum(a["usage"].get("output_tokens", 0)
                                        for a in attempts)}
    total_cost = round(sum(a["cost_usd"] for a in attempts), 6)
    out = dict(final["trace"])
    out["usage"] = total_usage
    out["gate"] = {
        "mode": mode,
        "repaired": any(a["kind"] == "repair" for a in attempts),
        "escalated": any(a["kind"] == "escalation" for a in attempts),
        "repair_succeeded": any(
            a["kind"] == "repair" and passed(a["verdict"]) for a in attempts),
        "escalation_succeeded": any(
            a["kind"] == "escalation" and passed(a["verdict"])
            for a in attempts),
        "attempts": [{k: a[k] for k in ("kind", "backend", "model", "usage",
                                       "cost_usd", "verdict")}
                     for a in attempts],
        "total_cost_usd": total_cost,
        "cost_note": ("Glimmer token cost is $0 (self-hosted); pod rental "
                      "billed separately, not in total_cost_usd.")
        if primary_model in SELF_HOSTED_MODELS else None,
    }
    out["gate_cost_usd"] = total_cost
    return out
