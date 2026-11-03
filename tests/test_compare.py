"""Deterministic findings on both samples, plus call-2 question checks with a fake client."""
from types import SimpleNamespace as NS

import pytest

from src.compare import compute_findings, finding_counts
from src.documents import load_sample, prepare_documents, validate_prior_csv
from src.extractor import LLMError, Settings, check_readings
from src.questions import build_call2_input, check_questions, draft_questions
from src.schemas import DocumentBatch, DocumentReading, FindingQuestion, QuestionBatch


def reading(doc_id, form, issuer, year, amount, proposed=None):
    return DocumentReading(doc_id=doc_id, form_type=form, issuer_name=issuer, tax_year=year,
                           key_amount=amount, key_amount_label=None,
                           proposed_prior_entry_id=proposed, match_rationale="test")


def run(sample, readings, prior_override=None):
    csv_bytes, files = load_sample(sample)
    prior, _ = validate_prior_csv(prior_override or csv_bytes, 2024)
    docs, _ = prepare_documents(files)
    checked = check_readings(DocumentBatch(readings=readings), docs, prior, 2025)
    return compute_findings(prior, docs, checked, 2025)


SAMPLE_READINGS = [
    reading("D1", "1099-INT", "Ally Bank", 2025, "$312.47", "P2"),
    reading("D2", "1099-INT", "JPMorgan Chase Bank, N.A.", 2025, "52.18", "P3"),
    reading("D3", "1099-DIV", "The Vanguard Group", 2025, "702.33", "P5"),
    reading("D4", "W-2", "ABC Design Co.", 2025, "88,450.00", "P1"),
    reading("D5", "1099-NEC", "XYZ Studio LLC", 2025, "12,000.00", None),
]


def difficult_readings(misc_proposal):
    return [
        reading("D1", "1099-INT", "Ally Bank", 2025, "$312.47", "P2"),
        reading("D2", "1099-INT", "Discover Bank", 2024, "$97.12", "P6"),
        reading("D3", "1099-MISC", "Harbor Point Properties LLC", 2025, "14,400.00", misc_proposal),
        reading("D4", "1099-INT", "JPMorgan Chase Bank, N.A.", 2025, "52.18", "P3"),
        reading("D5", "1099-DIV", "The Vanguard Group", 2025, "702.33", "P5"),
        reading("D6", "W-2", "ABC Design Co.", 2025, "88,450.00", "P1"),
        reading("D7", "1099-NEC", "XYZ Studio LLC", 2025, "12,000.00", None),
        reading("D8", "Other", "Lakeshore Power & Light", None, None, None),
    ]


def by_key(findings):
    return {(f.current_doc_id or f.prior_entry_id): f for f in findings}


def test_sample_client_expected_findings():
    findings = run("sample_client", SAMPLE_READINGS)
    assert finding_counts(findings) == {"Matched": 4, "Missing": 1, "New": 1, "Needs Review": 0}
    f = by_key(findings)
    assert f["D2"].finding.value == "Matched" and f["D2"].prior_entry_id == "P3"
    assert "name variant" in f["D2"].reason
    assert f["P4"].finding.value == "Missing" and f["P4"].form_type == "1098" and f["P4"].needs_question
    assert f["D5"].finding.value == "New" and f["D5"].form_type == "1099-NEC" and f["D5"].needs_question
    assert [x.finding_id for x in findings if x.needs_question] == ["F5", "F6"]


@pytest.mark.parametrize("misc_proposal, misc_status", [(None, "New"), ("P4", "Needs Review")])
def test_difficult_client_expected_findings(misc_proposal, misc_status):
    """Whether or not the model follows the injected text, nothing is matched to P4."""
    findings = run("difficult_client", difficult_readings(misc_proposal))
    f = by_key(findings)
    assert f["D2"].finding.value == "Needs Review" and "Wrong tax year" in f["D2"].reason
    assert f["D2"].needs_question
    assert f["D8"].finding.value == "Needs Review" and "Other" in f["D8"].reason
    assert f["D9"].finding.value == "Needs Review" and "Unreadable" in f["D9"].reason
    assert f["D3"].finding.value == misc_status
    assert f["P4"].finding.value == "Missing" and f["P6"].finding.value == "Missing"
    assert sum(x.finding.value == "Matched" for x in findings) == 4
    # every document and every prior entry is accounted for exactly once
    assert len(findings) == 9 + 2


def test_grounding_failure_is_needs_review_and_entry_stays_missing_with_note():
    readings = list(SAMPLE_READINGS)
    readings[0] = reading("D1", "1099-INT", "Ally Bank", 2025, "999.99", "P2")
    f = by_key(run("sample_client", readings))
    assert f["D1"].finding.value == "Needs Review" and "Value not found in document" in f["D1"].reason
    assert f["P2"].finding.value == "Missing" and "D1" in f["P2"].reason


def test_amounts_are_never_compared():
    prior = (b"entry_id,form_type,issuer_name,tax_year,key_amount\n"
             b"P1,W-2,ABC Design Co.,2024,1.00\nP2,1099-INT,Ally Bank,2024,999999.00\n"
             b"P3,1099-INT,Chase,2024,\nP4,1098,Rocket Mortgage,2024,9200.00\nP5,1099-DIV,Vanguard,2024,0\n")
    changed = run("sample_client", SAMPLE_READINGS, prior_override=prior)
    base = run("sample_client", SAMPLE_READINGS)
    assert [(f.finding, f.reason) for f in changed] == [(f.finding, f.reason) for f in base]


# ---------------------------------------------------------------- call 2 checks


def fake_q_client(batch):
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return NS(status="completed", output=[], output_parsed=batch)

    return NS(responses=NS(parse=parse)), calls


def test_call2_input_has_findings_only():
    findings = run("sample_client", SAMPLE_READINGS)
    text = build_call2_input(findings, 2025)
    assert "Rocket Mortgage" in text and "XYZ Studio LLC" in text
    assert "SYNTHETIC SAMPLE" not in text  # no raw document text
    assert ".pdf" not in text and "12,000.00" not in text  # no filenames, no amounts


def test_draft_questions_accepts_complete_output():
    findings = run("sample_client", SAMPLE_READINGS)
    batch = QuestionBatch(summary="s", questions=[
        FindingQuestion(finding_id="F5", client_question="Please confirm the 1099-NEC from XYZ Studio LLC?"),
        FindingQuestion(finding_id="F6", client_question="Do you have the 2025 Form 1098 from Rocket Mortgage?"),
        FindingQuestion(finding_id="F1", client_question="Extra question for a matched item."),
    ])
    client, calls = fake_q_client(batch)
    result = draft_questions(client, Settings("k", "m", None), findings, 2025)
    assert set(result.questions) == {"F5", "F6"}  # extras for non-required findings are not used
    assert calls[0]["text_format"] is QuestionBatch and calls[0]["store"] is False


def test_missing_question_is_rejected():
    findings = run("sample_client", SAMPLE_READINGS)
    batch = QuestionBatch(summary="s", questions=[FindingQuestion(finding_id="F5", client_question="Q?")])
    with pytest.raises(LLMError, match="no question for F6"):
        check_questions(batch, findings)


def test_empty_question_is_rejected():
    findings = run("sample_client", SAMPLE_READINGS)
    batch = QuestionBatch(summary="s", questions=[
        FindingQuestion(finding_id="F5", client_question="Q?"),
        FindingQuestion(finding_id="F6", client_question="   "),
    ])
    with pytest.raises(LLMError, match="no question for F6"):
        check_questions(batch, findings)


def test_invented_finding_id_is_rejected():
    findings = run("sample_client", SAMPLE_READINGS)
    batch = QuestionBatch(summary="s", questions=[
        FindingQuestion(finding_id="F5", client_question="Q?"),
        FindingQuestion(finding_id="F6", client_question="Q?"),
        FindingQuestion(finding_id="F42", client_question="Q?"),
    ])
    with pytest.raises(LLMError, match="unknown finding IDs F42"):
        check_questions(batch, findings)
