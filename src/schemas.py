"""Shared types: form types, statuses, LLM output schemas and internal records."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class FormType(str, Enum):
    W2 = "W-2"
    INT = "1099-INT"
    DIV = "1099-DIV"
    NEC = "1099-NEC"
    MISC = "1099-MISC"
    B = "1099-B"
    K = "1099-K"
    R = "1099-R"
    F1098 = "1098"
    F1098E = "1098-E"
    F1098T = "1098-T"
    OTHER = "Other"


SUPPORTED_FORM_TYPES: list[str] = [f.value for f in FormType]
PRIOR_YEAR_FORM_TYPES: list[str] = [f.value for f in FormType if f is not FormType.OTHER]


class FindingStatus(str, Enum):
    MATCHED = "Matched"
    MISSING = "Missing"
    NEW = "New"
    NEEDS_REVIEW = "Needs Review"


class ReviewerStatus(str, Enum):
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    ASK_CLIENT = "Ask Client"
    DISMISSED = "Dismissed"


# ---------------------------------------------------------------- LLM call 1


class DocumentReading(BaseModel):
    doc_id: str = Field(description="Document ID copied exactly from the input, e.g. D3.")
    form_type: FormType = Field(description="Supported form type, or Other if not one of them.")
    issuer_name: str | None = Field(
        description="Issuer/payer/employer/lender name exactly as printed, or null."
    )
    tax_year: int | None = Field(description="Tax year printed on the document, or null.")
    key_amount: str | None = Field(
        description="Main box amount exactly as printed, e.g. '12,000.00', or null."
    )
    key_amount_label: str | None = Field(
        description="Label of that box as printed, e.g. 'Box 1 Nonemployee compensation', or null."
    )
    proposed_prior_entry_id: str | None = Field(
        description="ID of the prior-year entry this document corresponds to, or null."
    )
    match_rationale: str = Field(description="One short sentence explaining the match decision.")


class DocumentBatch(BaseModel):
    readings: list[DocumentReading]


# ---------------------------------------------------------------- LLM call 2


class FindingQuestion(BaseModel):
    finding_id: str = Field(description="Finding ID copied exactly from the input, e.g. F3.")
    client_question: str = Field(description="One short, specific, polite question for the client.")


class QuestionBatch(BaseModel):
    summary: str = Field(description="2-4 sentences for the preparer.")
    questions: list[FindingQuestion]


# ---------------------------------------------------------------- internal records


class PriorEntry(BaseModel):
    entry_id: str
    form_type: FormType
    issuer_name: str
    tax_year: int
    key_amount: str | None = None
    notes: str | None = None


class CurrentDocument(BaseModel):
    doc_id: str
    filename: str
    size_bytes: int
    text: str = ""  # extracted text, capped
    char_count: int = 0  # non-whitespace characters extracted (before cap)
    truncated: bool = False
    readable: bool = True
    unreadable_reason: str | None = None


class CheckedReading(BaseModel):
    """A call-1 reading after code checks (grounding + match rules)."""

    reading: DocumentReading
    grounding_failures: list[str] = []  # fields not found in the document text
    accepted_entry_id: str | None = None
    match_rejection: str | None = None  # reason the proposed match was rejected


class Finding(BaseModel):
    finding_id: str
    finding: FindingStatus
    reason: str
    needs_question: bool = False  # Missing, New and wrong-year findings
    form_type: str | None = None
    prior_entry_id: str | None = None
    prior_issuer: str | None = None
    current_doc_id: str | None = None
    current_filename: str | None = None
    current_issuer: str | None = None
    tax_year: int | None = None
    key_amount_reference: str | None = None
    key_amount_label: str | None = None
