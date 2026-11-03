"""Input validation and PDF text extraction. Runs before any API call."""
from __future__ import annotations

import hashlib
import io
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from src.schemas import PRIOR_YEAR_FORM_TYPES, CurrentDocument, FormType, PriorEntry

REQUIRED_COLUMNS = ["entry_id", "form_type", "issuer_name", "tax_year"]
OPTIONAL_COLUMNS = ["key_amount", "notes"]
MAX_PRIOR_ROWS = 30

MAX_PDFS = 15
MAX_PDF_BYTES = 5 * 1024 * 1024
MIN_READABLE_CHARS = 50
MAX_TEXT_CHARS = 8000

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SAMPLE_CLIENTS = ["sample_client", "difficult_client"]

_FORM_TYPE_LOOKUP = {ft.upper(): ft for ft in PRIOR_YEAR_FORM_TYPES}


def parse_amount(value: str) -> Decimal | None:
    """'$12,000.00' -> Decimal('12000.00'); None if not a plain decimal amount."""
    cleaned = value.strip().replace("$", "").replace(",", "").replace(" ", "")
    if not cleaned:
        return None
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


# ---------------------------------------------------------------- prior-year CSV


def validate_prior_csv(data: bytes, prior_year: int) -> tuple[list[PriorEntry], list[str]]:
    """Validate the prior-year document list. Returns (entries, errors); every error is listed.

    Entries are returned only when there are no errors; no row is silently discarded.
    """
    errors: list[str] = []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["The prior-year CSV is not UTF-8 text."]
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except Exception as exc:  # pandas raises several parser error types
        return [], [f"The prior-year CSV could not be parsed: {exc}"]

    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return [], [f"Missing required column(s): {', '.join(missing)}."]
    if len(df) == 0:
        return [], ["The prior-year CSV has no rows."]
    if len(df) > MAX_PRIOR_ROWS:
        errors.append(f"The prior-year CSV has {len(df)} rows; the maximum is {MAX_PRIOR_ROWS}.")

    entries: list[PriorEntry] = []
    seen_ids: dict[str, int] = {}
    for idx, row in df.iterrows():
        line = int(idx) + 2  # header is line 1
        entry_id = row["entry_id"].strip()
        form_raw = row["form_type"].strip()
        issuer = row["issuer_name"].strip()
        year_raw = row["tax_year"].strip()
        amount_raw = row["key_amount"].strip() if "key_amount" in df.columns else ""
        notes = row["notes"].strip() if "notes" in df.columns else ""
        row_errors: list[str] = []

        if not entry_id:
            row_errors.append(f"Line {line}: entry_id is empty.")
        elif entry_id in seen_ids:
            row_errors.append(
                f"Line {line}: duplicate entry_id '{entry_id}' (first used on line {seen_ids[entry_id]})."
            )
        else:
            seen_ids[entry_id] = line

        form_type = _FORM_TYPE_LOOKUP.get(form_raw.upper())
        if form_type is None:
            if form_raw.upper() == FormType.OTHER.value.upper():
                row_errors.append(f"Line {line}: form_type 'Other' is not allowed in the prior-year list.")
            else:
                row_errors.append(
                    f"Line {line}: unknown form_type '{form_raw}'. "
                    f"Supported: {', '.join(PRIOR_YEAR_FORM_TYPES)}."
                )
        if not issuer:
            row_errors.append(f"Line {line}: issuer_name is empty.")

        year: int | None = None
        try:
            year = int(year_raw)
        except ValueError:
            row_errors.append(f"Line {line}: tax_year '{year_raw}' is not an integer.")
        if year is not None and year != prior_year:
            row_errors.append(f"Line {line}: tax_year {year} does not equal the prior year {prior_year}.")

        if amount_raw and parse_amount(amount_raw) is None:
            row_errors.append(f"Line {line}: key_amount '{amount_raw}' is not a decimal amount.")

        if row_errors:
            errors.extend(row_errors)
            continue
        entries.append(
            PriorEntry(
                entry_id=entry_id,
                form_type=FormType(form_type),
                issuer_name=issuer,
                tax_year=year,
                key_amount=amount_raw or None,
                notes=notes or None,
            )
        )
    if errors:
        return [], errors
    return entries, []


# ---------------------------------------------------------------- current-year PDFs


def extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def prepare_documents(files: list[tuple[str, bytes]]) -> tuple[list[CurrentDocument], list[str]]:
    """Validate uploads and extract text. Returns (documents, blocking errors).

    Unreadable files are not errors: they are returned with readable=False and become
    Needs Review findings without being sent to the model.
    """
    errors: list[str] = []
    if not files:
        return [], ["Add at least one current-year PDF."]
    if len(files) > MAX_PDFS:
        errors.append(f"{len(files)} PDFs were provided; the maximum is {MAX_PDFS}.")
    for name, data in files:
        if not name.lower().endswith(".pdf"):
            errors.append(f"'{name}' is not a .pdf file.")
        if len(data) > MAX_PDF_BYTES:
            errors.append(f"'{name}' is {len(data) / 1_048_576:.1f} MB; the limit is 5 MB per file.")
    if errors:
        return [], errors

    docs: list[CurrentDocument] = []
    for i, (name, data) in enumerate(files, start=1):
        doc = CurrentDocument(doc_id=f"D{i}", filename=name, size_bytes=len(data))
        try:
            text = extract_pdf_text(data)
        except Exception as exc:
            doc.readable = False
            doc.unreadable_reason = f"PDF could not be opened ({type(exc).__name__})."
            docs.append(doc)
            continue
        doc.char_count = sum(1 for ch in text if not ch.isspace())
        if doc.char_count < MIN_READABLE_CHARS:
            doc.readable = False
            doc.unreadable_reason = (
                f"Only {doc.char_count} characters of text could be extracted "
                "(likely a scanned image; OCR is not supported)."
            )
            docs.append(doc)
            continue
        doc.truncated = len(text) > MAX_TEXT_CHARS
        doc.text = text[:MAX_TEXT_CHARS]
        docs.append(doc)
    return docs, []


# ---------------------------------------------------------------- samples and fingerprint


def load_sample(name: str, invalid_csv: bool = False) -> tuple[bytes, list[tuple[str, bytes]]]:
    """Bundled synthetic sample: (prior-year CSV bytes, [(filename, pdf bytes), ...])."""
    if name not in SAMPLE_CLIENTS:
        raise ValueError(f"Unknown sample '{name}'.")
    folder = DATA_DIR / name
    csv_name = "prior_year_documents_invalid.csv" if invalid_csv else "prior_year_documents.csv"
    csv_bytes = (folder / csv_name).read_bytes()
    pdfs = [(p.name, p.read_bytes()) for p in sorted((folder / "current_year").glob("*.pdf"))]
    return csv_bytes, pdfs


def input_fingerprint(csv_bytes: bytes, files: list[tuple[str, bytes]], current_year: int) -> str:
    h = hashlib.sha256()
    h.update(str(current_year).encode())
    h.update(csv_bytes)
    for name, data in files:
        h.update(name.encode())
        h.update(hashlib.sha256(data).digest())
    return h.hexdigest()
