"""Deterministic comparison: Matched / Missing / New / Needs Review.

Input: validated prior-year entries, prepared documents and checked call-1 readings.
No model call happens here. Amounts are carried for reference only and never compared.
"""
from __future__ import annotations

from src.schemas import CheckedReading, CurrentDocument, Finding, FindingStatus, FormType, PriorEntry


def _same_name(a: str | None, b: str | None) -> bool:
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def compute_findings(
    prior_entries: list[PriorEntry],
    docs: list[CurrentDocument],
    checked: list[CheckedReading],
    current_year: int,
) -> list[Finding]:
    """One finding per current document (in upload order), then one per unmatched prior entry."""
    by_doc = {c.reading.doc_id: c for c in checked}
    by_entry = {e.entry_id: e for e in prior_entries}
    findings: list[Finding] = []

    def add(**kwargs) -> Finding:
        f = Finding(finding_id=f"F{len(findings) + 1}", **kwargs)
        findings.append(f)
        return f

    matched_entries: dict[str, str] = {}  # entry_id -> doc_id
    rejected_proposals: dict[str, list[str]] = {}  # entry_id -> ["D2 (reason)"]

    for doc in docs:
        base = dict(current_doc_id=doc.doc_id, current_filename=doc.filename)
        if not doc.readable:
            add(finding=FindingStatus.NEEDS_REVIEW, reason=f"Unreadable: {doc.unreadable_reason}", **base)
            continue
        c = by_doc.get(doc.doc_id)
        if c is None:  # cannot happen after ID integrity; never drop silently
            add(finding=FindingStatus.NEEDS_REVIEW, reason="No reading was returned for this document.", **base)
            continue
        r = c.reading
        pid = r.proposed_prior_entry_id
        if pid and c.accepted_entry_id is None and c.match_rejection:
            rejected_proposals.setdefault(pid, []).append(f"{doc.doc_id}: {c.match_rejection}")
        base.update(
            form_type=r.form_type.value,
            current_issuer=r.issuer_name,
            tax_year=r.tax_year,
            key_amount_reference=r.key_amount,
            key_amount_label=r.key_amount_label,
        )
        proposed = by_entry.get(pid) if pid else None
        rejection = f" Proposed match rejected: {c.match_rejection}." if c.match_rejection else ""

        if r.form_type is FormType.OTHER:
            add(finding=FindingStatus.NEEDS_REVIEW,
                reason=f"Not a supported tax form (read as Other).{rejection}", **base)
        elif c.grounding_failures:
            add(finding=FindingStatus.NEEDS_REVIEW,
                reason=f"Value not found in document: {', '.join(c.grounding_failures)}.{rejection}",
                **base)
        elif r.tax_year is None:
            add(finding=FindingStatus.NEEDS_REVIEW,
                reason=f"Tax year not identified on the document.{rejection}", **base)
        elif r.tax_year != current_year:
            hint = ""
            if proposed is not None and proposed.form_type == r.form_type:
                hint = f" Appears to correspond to prior-year entry {proposed.entry_id} ({proposed.issuer_name})."
            add(finding=FindingStatus.NEEDS_REVIEW,
                reason=f"Wrong tax year: document is for {r.tax_year}, expected {current_year}.{hint}",
                needs_question=True,
                prior_entry_id=proposed.entry_id if hint else None,
                prior_issuer=proposed.issuer_name if hint else None,
                **base)
        elif not r.issuer_name:
            add(finding=FindingStatus.NEEDS_REVIEW,
                reason=f"Issuer not identified on the document.{rejection}", **base)
        elif c.match_rejection:
            add(finding=FindingStatus.NEEDS_REVIEW,
                reason=f"Proposed match rejected: {c.match_rejection}.", **base)
        elif c.accepted_entry_id:
            entry = by_entry[c.accepted_entry_id]
            matched_entries[entry.entry_id] = doc.doc_id
            variant = (
                "" if _same_name(entry.issuer_name, r.issuer_name)
                else f" Issuer name variant: '{r.issuer_name}' vs. '{entry.issuer_name}' on file."
            )
            add(finding=FindingStatus.MATCHED,
                reason=f"Matches prior-year entry {entry.entry_id}.{variant}",
                prior_entry_id=entry.entry_id, prior_issuer=entry.issuer_name, **base)
        else:
            add(finding=FindingStatus.NEW,
                reason="No prior-year entry with this form type and issuer.",
                needs_question=True, **base)

    for entry in prior_entries:
        if entry.entry_id in matched_entries:
            continue
        note = ""
        if entry.entry_id in rejected_proposals:
            note = " Proposed but not accepted — " + "; ".join(rejected_proposals[entry.entry_id]) + "."
        add(finding=FindingStatus.MISSING,
            reason=f"No accepted {current_year} document for this prior-year entry.{note}",
            needs_question=True,
            form_type=entry.form_type.value,
            prior_entry_id=entry.entry_id,
            prior_issuer=entry.issuer_name,
            tax_year=entry.tax_year,
            key_amount_reference=entry.key_amount)
    return findings


def finding_counts(findings: list[Finding]) -> dict[str, int]:
    counts = {s.value: 0 for s in FindingStatus}
    for f in findings:
        counts[f.finding.value] += 1
    return counts
