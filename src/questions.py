"""LLM call 2: preparer summary and one client question per Missing / New / wrong-year finding.

The model sees only the computed findings (no raw document text, no filenames, no amounts).
Code checks the output; on failure the findings remain usable without questions.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from pydantic import BaseModel

from src.extractor import LLMError, Settings, call_structured
from src.schemas import Finding, QuestionBatch

CALL2_INSTRUCTIONS = """You draft short client follow-up questions for a tax preparer at a CPA firm. \
The input is the computed result of a document completeness check comparing the client's current-year \
tax documents with the firm's prior-year document list. You are not a tax adviser.

For EVERY finding with needs_question = true, write exactly one question (copy finding_id exactly):
- Missing: name the form type and issuer, say we received it last year, and ask the client to send the \
current-year form or tell us why it no longer applies.
- New: name the form type and issuer, say we received it this year but not last year, and ask the client \
to confirm it is theirs and a new source this year.
- Needs Review with a wrong tax year: name the form type, issuer and the year we received, and ask the \
client to send the form for the current tax year.

Each question: one or two sentences, polite, plain language, addressed to the client as "you", asking \
exactly one concrete thing. Do not give tax advice or mention tax consequences, deductions or what must \
be reported. Do not mention amounts, internal IDs (such as P1, D3 or F2), software or AI. Do not write \
questions for findings with needs_question = false.

summary: 2-4 sentences for the preparer describing what is matched, missing, new and needs review, \
and the most important follow-ups. No tax advice."""


class QuestionResult(BaseModel):
    summary: str
    questions: dict[str, str]  # finding_id -> AI-drafted question


def build_call2_input(findings: list[Finding], current_year: int) -> str:
    rows = [
        {
            "finding_id": f.finding_id,
            "finding": f.finding.value,
            "reason": f.reason,
            "form_type": f.form_type,
            "prior_year_issuer": f.prior_issuer,
            "current_year_issuer": f.current_issuer,
            "document_tax_year": f.tax_year,
            "needs_question": f.needs_question,
        }
        for f in findings
    ]
    return (
        f"Current tax year: {current_year}. Prior tax year: {current_year - 1}.\n"
        "Findings:\n" + "\n".join(json.dumps(r) for r in rows)
    )


def check_questions(batch: QuestionBatch, findings: list[Finding]) -> QuestionResult:
    """Every required finding gets exactly one nonempty question; no invented finding IDs."""
    all_ids = {f.finding_id for f in findings}
    required = [f.finding_id for f in findings if f.needs_question]
    counts = Counter(q.finding_id for q in batch.questions)
    invented = sorted(i for i in counts if i not in all_ids)
    duplicates = sorted(i for i, n in counts.items() if n > 1)
    nonempty = {q.finding_id for q in batch.questions if q.client_question.strip()}
    missing = [i for i in required if i not in nonempty]
    problems = []
    if invented:
        problems.append(f"questions for unknown finding IDs {', '.join(invented)}")
    if duplicates:
        problems.append(f"more than one question for {', '.join(duplicates)}")
    if missing:
        problems.append(f"no question for {', '.join(missing)}")
    if problems:
        raise LLMError(
            "The drafted client questions were rejected (" + "; ".join(problems) + "). "
            "Findings are shown without questions; you can type questions yourself or try again."
        )
    required_set = set(required)
    questions = {
        q.finding_id: q.client_question.strip()
        for q in batch.questions
        if q.finding_id in required_set
    }
    return QuestionResult(summary=batch.summary.strip(), questions=questions)


def draft_questions(
    client: Any, settings: Settings, findings: list[Finding], current_year: int
) -> QuestionResult:
    if not any(f.needs_question for f in findings):
        return QuestionResult(summary="No findings need a client question.", questions={})
    batch = call_structured(
        client,
        settings,
        instructions=CALL2_INSTRUCTIONS,
        user_input=build_call2_input(findings, current_year),
        text_format=QuestionBatch,
    )
    return check_questions(batch, findings)
