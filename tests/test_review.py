"""Reviewer decisions and exports."""
import csv
import io

from src.review import (
    CHECKLIST_COLUMNS,
    Decision,
    checklist_csv,
    client_request_text,
    default_decisions,
)
from src.schemas import Finding, FindingStatus, ReviewerStatus

FINDINGS = [
    Finding(finding_id="F1", finding=FindingStatus.MATCHED, reason="Matches P2.", form_type="1099-INT",
            current_doc_id="D1", current_filename="ally.pdf", current_issuer="Ally Bank",
            prior_entry_id="P2", prior_issuer="Ally Bank", tax_year=2025, key_amount_reference="$312.47"),
    Finding(finding_id="F2", finding=FindingStatus.NEW, reason="No prior entry.", needs_question=True,
            form_type="1099-NEC", current_doc_id="D2", current_issuer="XYZ Studio LLC", tax_year=2025),
    Finding(finding_id="F3", finding=FindingStatus.MISSING, reason="No 2025 document.", needs_question=True,
            form_type="1098", prior_entry_id="P4", prior_issuer="Rocket Mortgage", tax_year=2024),
    Finding(finding_id="F4", finding=FindingStatus.NEEDS_REVIEW, reason="Unreadable.", current_doc_id="D3"),
]
AI = {"F2": "AI question about XYZ Studio?", "F3": "AI question about Rocket Mortgage?"}


def test_defaults_are_pending_with_ai_draft():
    d = default_decisions(FINDINGS, AI)
    assert all(x.status is ReviewerStatus.PENDING for x in d.values())
    assert d["F3"].final_question == AI["F3"] and d["F1"].final_question == ""


def test_request_list_contains_only_ask_client_items_with_final_text():
    d = default_decisions(FINDINGS, AI)
    d["F2"] = Decision(status=ReviewerStatus.DISMISSED, final_question=AI["F2"])
    d["F3"] = Decision(status=ReviewerStatus.ASK_CLIENT, final_question="Edited: did you refinance?")
    d["F4"] = Decision(status=ReviewerStatus.ASK_CLIENT, final_question="Please resend a clearer copy.")
    d["F1"] = Decision(status=ReviewerStatus.CONFIRMED)
    text = client_request_text(FINDINGS, d, 2025)
    assert "1. Edited: did you refinance?" in text
    assert "2. Please resend a clearer copy." in text
    assert "AI question" not in text and "XYZ" not in text


def test_request_list_empty_without_ask_client():
    assert client_request_text(FINDINGS, default_decisions(FINDINGS, AI), 2025) == ""
    d = default_decisions(FINDINGS, {})
    d["F3"] = Decision(status=ReviewerStatus.ASK_CLIENT, final_question="  ")
    assert client_request_text(FINDINGS, d, 2025) == ""


def test_checklist_keeps_ai_draft_final_question_and_computed_finding():
    d = default_decisions(FINDINGS, AI)
    d["F3"] = Decision(status=ReviewerStatus.ASK_CLIENT, final_question="Edited question")
    rows = list(csv.DictReader(io.StringIO(checklist_csv(FINDINGS, AI, d))))
    assert list(rows[0].keys()) == CHECKLIST_COLUMNS
    f3 = rows[2]
    assert f3["finding"] == "Missing"  # reviewer action never changes the computed finding
    assert f3["ai_question"] == AI["F3"] and f3["final_question"] == "Edited question"
    assert f3["reviewer_status"] == "Ask Client"
    assert rows[0]["key_amount_reference"] == "$312.47" and rows[0]["reviewer_status"] == "Pending"
    assert len(rows) == len(FINDINGS)
