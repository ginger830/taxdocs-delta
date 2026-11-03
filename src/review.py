"""Reviewer decisions and exports. Reviewer actions never change the computed finding."""
from __future__ import annotations

import csv
import io

from pydantic import BaseModel

from src.schemas import Finding, ReviewerStatus

CHECKLIST_COLUMNS = [
    "finding_id",
    "finding",
    "reason",
    "form_type",
    "prior_entry_id",
    "prior_issuer",
    "current_doc_id",
    "current_filename",
    "current_issuer",
    "tax_year",
    "key_amount_reference",
    "ai_question",
    "final_question",
    "reviewer_status",
]


class Decision(BaseModel):
    status: ReviewerStatus = ReviewerStatus.PENDING
    final_question: str = ""


def default_decisions(findings: list[Finding], ai_questions: dict[str, str]) -> dict[str, Decision]:
    return {
        f.finding_id: Decision(final_question=ai_questions.get(f.finding_id, ""))
        for f in findings
    }


def checklist_rows(
    findings: list[Finding], ai_questions: dict[str, str], decisions: dict[str, Decision]
) -> list[dict[str, str]]:
    rows = []
    for f in findings:
        d = decisions.get(f.finding_id, Decision())
        rows.append(
            {
                "finding_id": f.finding_id,
                "finding": f.finding.value,
                "reason": f.reason,
                "form_type": f.form_type or "",
                "prior_entry_id": f.prior_entry_id or "",
                "prior_issuer": f.prior_issuer or "",
                "current_doc_id": f.current_doc_id or "",
                "current_filename": f.current_filename or "",
                "current_issuer": f.current_issuer or "",
                "tax_year": "" if f.tax_year is None else str(f.tax_year),
                "key_amount_reference": f.key_amount_reference or "",
                "ai_question": ai_questions.get(f.finding_id, ""),
                "final_question": d.final_question,
                "reviewer_status": d.status.value,
            }
        )
    return rows


def checklist_csv(
    findings: list[Finding], ai_questions: dict[str, str], decisions: dict[str, Decision]
) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CHECKLIST_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(checklist_rows(findings, ai_questions, decisions))
    return buf.getvalue()


def ask_client_items(findings: list[Finding], decisions: dict[str, Decision]) -> list[tuple[Finding, str]]:
    """(finding, final question) for every finding marked Ask Client, in finding order."""
    items = []
    for f in findings:
        d = decisions.get(f.finding_id)
        if d is not None and d.status is ReviewerStatus.ASK_CLIENT:
            items.append((f, d.final_question.strip()))
    return items


def client_request_text(
    findings: list[Finding], decisions: dict[str, Decision], current_year: int
) -> str:
    """Client request list built only from Ask Client findings, using the final question text."""
    questions = [q for _, q in ask_client_items(findings, decisions) if q]
    if not questions:
        return ""
    lines = [
        f"Tax year {current_year} — documents we still need from you",
        "",
        f"Hello, while checking your {current_year} tax documents we have the following questions:",
        "",
    ]
    lines += [f"{i}. {q}" for i, q in enumerate(questions, start=1)]
    lines += ["", "Thank you — please reply or upload the documents through the usual channel."]
    return "\n".join(lines) + "\n"
