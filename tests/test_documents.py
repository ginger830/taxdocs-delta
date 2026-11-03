"""Input validation before any API call: prior-year CSV rules, file limits, readability."""
from src import documents
from src.documents import load_sample, prepare_documents, validate_prior_csv

HEADER = "entry_id,form_type,issuer_name,tax_year,key_amount,notes\n"


def csv(*rows: str) -> bytes:
    return (HEADER + "\n".join(rows) + "\n").encode()


def test_bundled_prior_csvs_are_valid():
    for name, n in [("sample_client", 5), ("difficult_client", 6)]:
        entries, errors = validate_prior_csv(load_sample(name)[0], 2024)
        assert errors == []
        assert len(entries) == n


def test_invalid_sample_csv_lists_every_error():
    entries, errors = validate_prior_csv(load_sample("difficult_client", invalid_csv=True)[0], 2024)
    assert entries == []
    joined = "\n".join(errors)
    assert "duplicate entry_id 'P2'" in joined
    assert "unknown form_type 'K-1'" in joined
    assert "tax_year 2023 does not equal the prior year 2024" in joined
    assert len(errors) == 3


def test_missing_required_column():
    _, errors = validate_prior_csv(b"entry_id,form_type,tax_year\nP1,W-2,2024\n", 2024)
    assert errors == ["Missing required column(s): issuer_name."]


def test_optional_columns_may_be_absent_and_form_type_case_is_normalized():
    entries, errors = validate_prior_csv(b"entry_id,form_type,issuer_name,tax_year\nP1,w-2,ABC,2024\n", 2024)
    assert errors == []
    assert entries[0].form_type.value == "W-2"
    assert entries[0].key_amount is None


def test_row_rules():
    _, errors = validate_prior_csv(
        csv(",W-2,ABC,2024,,", "P2,Other,Utility,2024,,", "P3,1099-INT,,2024,,",
            "P4,1098,Lender,2025,,", "P5,1098,Lender,twenty,,", "P6,1099-DIV,Fund,2024,abc,"),
        2024,
    )
    joined = "\n".join(errors)
    assert "Line 2: entry_id is empty." in joined
    assert "form_type 'Other' is not allowed" in joined
    assert "Line 4: issuer_name is empty." in joined
    assert "tax_year 2025 does not equal the prior year 2024" in joined
    assert "tax_year 'twenty' is not an integer" in joined
    assert "key_amount 'abc' is not a decimal amount" in joined


def test_prior_year_follows_configured_current_year():
    _, errors = validate_prior_csv(csv("P1,W-2,ABC,2024,,"), 2025)
    assert errors == ["Line 2: tax_year 2024 does not equal the prior year 2025."]


def test_row_limit():
    rows = [f"P{i},W-2,Employer {i},2024,," for i in range(31)]
    _, errors = validate_prior_csv(csv(*rows), 2024)
    assert any("maximum is 30" in e for e in errors)


def test_file_count_type_and_size_limits():
    assert prepare_documents([])[1] == ["Add at least one current-year PDF."]
    many = [(f"f{i}.pdf", b"%PDF") for i in range(16)]
    assert any("maximum is 15" in e for e in prepare_documents(many)[1])
    assert any("not a .pdf" in e for e in prepare_documents([("notes.txt", b"hi")])[1])
    big = [("big.pdf", b"0" * (5 * 1024 * 1024 + 1))]
    assert any("limit is 5 MB" in e for e in prepare_documents(big)[1])


def test_ids_readability_and_scanned_pdf():
    docs, errors = prepare_documents(load_sample("difficult_client")[1])
    assert errors == []
    assert [d.doc_id for d in docs] == [f"D{i}" for i in range(1, 10)]
    scan = next(d for d in docs if d.filename == "scan_0001.pdf")
    assert not scan.readable and "scanned" in scan.unreadable_reason
    assert all(d.readable for d in docs if d is not scan)


def test_corrupt_pdf_is_unreadable_not_an_error():
    docs, errors = prepare_documents([("broken.pdf", b"not really a pdf")])
    assert errors == []
    assert not docs[0].readable and "could not be opened" in docs[0].unreadable_reason


def test_text_is_capped(monkeypatch):
    monkeypatch.setattr(documents, "extract_pdf_text", lambda data: "x" * 20000)
    doc = prepare_documents([("long.pdf", b"%PDF")])[0][0]
    assert doc.readable and doc.truncated and len(doc.text) == documents.MAX_TEXT_CHARS
