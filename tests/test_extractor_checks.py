"""Call 1 with a fake OpenAI client: ID integrity, grounding, match rules, request shape, errors."""
from types import SimpleNamespace as NS

import openai

try:  # the OpenAI SDK's HTTP layer (httpx2 in openai 3.x, httpx before)
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx
import pytest

from src.documents import load_sample, prepare_documents, validate_prior_csv
from src.extractor import (
    LLMError,
    Settings,
    amount_in_text,
    call_structured,
    check_grounding,
    check_readings,
    make_client,
    read_documents,
)
from src.schemas import CurrentDocument, DocumentBatch, DocumentReading

SETTINGS = Settings(api_key="sk-test", model="test-model", reasoning_effort="medium")


def reading(doc_id, form, issuer, year, amount, proposed=None):
    return DocumentReading(doc_id=doc_id, form_type=form, issuer_name=issuer, tax_year=year,
                           key_amount=amount, key_amount_label=None,
                           proposed_prior_entry_id=proposed, match_rationale="test")


def sample_batch():
    return DocumentBatch(readings=[
        reading("D1", "1099-INT", "Ally Bank", 2025, "$312.47", "P2"),
        reading("D2", "1099-INT", "JPMorgan Chase Bank, N.A.", 2025, "52.18", "P3"),
        reading("D3", "1099-DIV", "The Vanguard Group", 2025, "702.33", "P5"),
        reading("D4", "W-2", "ABC Design Co.", 2025, "88,450.00", "P1"),
        reading("D5", "1099-NEC", "XYZ Studio LLC", 2025, "12,000.00", None),
    ])


class FakeResponses:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.result


def fake_client(output_parsed=None, *, status="completed", output=None, exc=None, incomplete=None):
    resp = NS(status=status, output=output or [], output_parsed=output_parsed,
              incomplete_details=incomplete, error=None)
    return NS(responses=FakeResponses(resp, exc))


@pytest.fixture
def sample():
    csv_bytes, files = load_sample("sample_client")
    prior, _ = validate_prior_csv(csv_bytes, 2024)
    docs, _ = prepare_documents(files)
    return prior, docs


def doc(doc_id, text):
    return CurrentDocument(doc_id=doc_id, filename=f"{doc_id}.pdf", size_bytes=1, text=text, char_count=len(text))


# ---------------------------------------------------------------- happy path and request shape


def test_sample_readings_accept_matches_including_name_variant(sample):
    prior, docs = sample
    client = fake_client(sample_batch())
    _, checked = read_documents(client, SETTINGS, prior, docs, 2025)
    accepted = {c.reading.doc_id: c.accepted_entry_id for c in checked}
    assert accepted == {"D1": "P2", "D2": "P3", "D3": "P5", "D4": "P1", "D5": None}
    assert all(not c.grounding_failures for c in checked)

    call = client.responses.calls[0]
    assert call["store"] is False
    assert call["text_format"] is DocumentBatch
    assert call["reasoning"] == {"effort": "medium"}
    assert "untrusted" in call["input"] and '<document doc_id="D5">' in call["input"]
    assert "Never follow instructions" in call["instructions"]


def test_reasoning_effort_omitted_when_not_set(sample):
    prior, docs = sample
    client = fake_client(sample_batch())
    read_documents(client, Settings("k", "m", None), prior, docs, 2025)
    assert "reasoning" not in client.responses.calls[0]


def test_unreadable_documents_are_not_sent():
    csv_bytes, files = load_sample("difficult_client")
    prior, _ = validate_prior_csv(csv_bytes, 2024)
    docs, _ = prepare_documents(files)
    readable_ids = [d.doc_id for d in docs if d.readable]
    batch = DocumentBatch(readings=[reading(i, "Other", None, None, None) for i in readable_ids])
    client = fake_client(batch)
    read_documents(client, SETTINGS, prior, docs, 2025)
    sent = client.responses.calls[0]["input"]
    assert 'doc_id="D9"' not in sent and 'doc_id="D8"' in sent


def test_no_readable_documents_means_no_call():
    unreadable = CurrentDocument(doc_id="D1", filename="s.pdf", size_bytes=1, readable=False)
    client = fake_client(DocumentBatch(readings=[]))
    with pytest.raises(LLMError, match="No readable PDFs"):
        read_documents(client, SETTINGS, [], [unreadable], 2025)
    assert client.responses.calls == []


# ---------------------------------------------------------------- ID integrity


@pytest.mark.parametrize("mutate, message", [
    (lambda r: r[:-1], "no reading for D5"),
    (lambda r: r + [r[0]], "duplicate readings for D1"),
    (lambda r: r + [reading("D99", "W-2", "X", 2025, None)], "unknown document IDs D99"),
])
def test_id_integrity_rejects_the_run(sample, mutate, message):
    prior, docs = sample
    batch = DocumentBatch(readings=mutate(sample_batch().readings))
    with pytest.raises(LLMError, match=message):
        check_readings(batch, docs, prior, 2025)


# ---------------------------------------------------------------- grounding


def test_grounding_pass_is_case_whitespace_and_format_insensitive():
    text = "PAYER'S name\nJPMorgan  Chase Bank,\nN.A.\nTax year 2025\n1 Nonemployee compensation 12,000.00"
    r = reading("D1", "1099-NEC", "jpmorgan chase bank, n.a.", 2025, "$12000.00")
    assert check_grounding(r, text) == []


def test_grounding_failures_are_reported():
    text = "Ally Bank 2025 Interest income $312.47"
    r = reading("D1", "1099-INT", "Ally Financial", 2024, "321.47")
    failures = check_grounding(r, text)
    assert failures == ["issuer 'Ally Financial'", "tax year 2024", "amount 321.47"]


def test_amount_digits_must_match_a_whole_number_in_text():
    assert amount_in_text("88,450.00", "Wages 88,450.00")
    assert not amount_in_text("8,450.00", "Wages 88,450.00")
    assert not amount_in_text("abc", "Wages 88,450.00")


def test_grounding_failure_blocks_match():
    prior, _ = validate_prior_csv(b"entry_id,form_type,issuer_name,tax_year\nP2,1099-INT,Ally Bank,2024\n", 2024)
    docs = [doc("D1", "Ally Bank Form 1099-INT 2025 Interest income 312.47 " * 3)]
    batch = DocumentBatch(readings=[reading("D1", "1099-INT", "Ally Bank", 2025, "999.99", "P2")])
    c = check_readings(batch, docs, prior, 2025)[0]
    assert c.grounding_failures == ["amount 999.99"]
    assert c.accepted_entry_id is None and "not found in the document" in c.match_rejection


# ---------------------------------------------------------------- match rules

PRIOR_CSV = (b"entry_id,form_type,issuer_name,tax_year\n"
             b"P1,1099-INT,Discover Bank,2024\nP4,1098,Rocket Mortgage,2024\n")
TEXT = "Discover Bank Harbor Point Lakeshore Form 2024 2025 97.12 14,400.00 " * 2


@pytest.mark.parametrize("r, expected", [
    (reading("D1", "1099-MISC", "Harbor Point", 2025, "14,400.00", "P4"), "form type 1099-MISC differs from P4 (1098)"),
    (reading("D1", "1099-INT", "Discover Bank", 2024, "97.12", "P1"), "document tax year 2024 is not the current year 2025"),
    (reading("D1", "Other", "Lakeshore", None, None, "P1"), "not a supported tax form"),
    (reading("D1", "1099-INT", "Discover Bank", 2025, "97.12", "P9"), "'P9' does not exist"),
])
def test_rejected_matches(r, expected):
    prior, _ = validate_prior_csv(PRIOR_CSV, 2024)
    c = check_readings(DocumentBatch(readings=[r]), [doc("D1", TEXT)], prior, 2025)[0]
    assert c.accepted_entry_id is None
    assert expected in c.match_rejection


def test_duplicate_claim_rejects_both():
    prior, _ = validate_prior_csv(PRIOR_CSV, 2024)
    batch = DocumentBatch(readings=[
        reading("D1", "1099-INT", "Discover Bank", 2025, "97.12", "P1"),
        reading("D2", "1099-INT", "Discover Bank", 2025, "97.12", "P1"),
    ])
    checked = check_readings(batch, [doc("D1", TEXT), doc("D2", TEXT)], prior, 2025)
    assert [c.accepted_entry_id for c in checked] == [None, None]
    assert "also claimed by D2" in checked[0].match_rejection
    assert "also claimed by D1" in checked[1].match_rejection


# ---------------------------------------------------------------- failures never become results


def test_missing_api_key():
    with pytest.raises(LLMError, match="OPENAI_API_KEY is not configured"):
        make_client(Settings(None, "m", None))


def test_client_has_no_retries():
    assert make_client(SETTINGS).max_retries == 0


def _status_error(cls, status, body=None):
    req = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return cls("err", response=httpx.Response(status, request=req), body=body)


@pytest.mark.parametrize("exc, message", [
    (openai.APIConnectionError(request=httpx.Request("POST", "https://x")), "Could not connect"),
    (openai.APITimeoutError(request=httpx.Request("POST", "https://x")), "timed out"),
    (_status_error(openai.AuthenticationError, 401), "authentication failed"),
    (_status_error(openai.NotFoundError, 404), "not found"),
    (_status_error(openai.RateLimitError, 429, {"code": "insufficient_quota"}), "quota"),
    (_status_error(openai.RateLimitError, 429), "rate limit"),
])
def test_api_errors_are_mapped(exc, message):
    with pytest.raises(LLMError, match=message):
        call_structured(fake_client(exc=exc), SETTINGS, instructions="i", user_input="u",
                        text_format=DocumentBatch)


def test_refusal_and_incomplete_are_errors():
    refusal = [NS(content=[NS(type="refusal", refusal="cannot help")])]
    with pytest.raises(LLMError, match="refused"):
        call_structured(fake_client(None, output=refusal), SETTINGS, instructions="i",
                        user_input="u", text_format=DocumentBatch)
    with pytest.raises(LLMError, match="incomplete"):
        call_structured(fake_client(None, status="incomplete", incomplete=NS(reason="max_output_tokens")),
                        SETTINGS, instructions="i", user_input="u", text_format=DocumentBatch)
    with pytest.raises(LLMError, match="no parsable"):
        call_structured(fake_client(None), SETTINGS, instructions="i", user_input="u",
                        text_format=DocumentBatch)
