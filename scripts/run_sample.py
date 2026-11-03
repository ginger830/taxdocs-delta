"""Dev helper: run the full live pipeline on a bundled sample without the UI.

Usage (from the repo root, with OPENAI_API_KEY configured):
    python scripts/run_sample.py sample_client
    python scripts/run_sample.py difficult_client
    python scripts/run_sample.py difficult_client --invalid-csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.compare import compute_findings, finding_counts  # noqa: E402
from src.documents import SAMPLE_CLIENTS, load_sample, prepare_documents, validate_prior_csv  # noqa: E402
from src.extractor import LLMError, load_settings, make_client, read_documents  # noqa: E402
from src.questions import draft_questions  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample", choices=SAMPLE_CLIENTS)
    ap.add_argument("--invalid-csv", action="store_true")
    ap.add_argument("--year", type=int, default=2025)
    args = ap.parse_args()

    csv_bytes, files = load_sample(args.sample, invalid_csv=args.invalid_csv)
    prior, csv_errors = validate_prior_csv(csv_bytes, args.year - 1)
    if csv_errors:
        print("INVALID CSV (no model call):")
        print("\n".join(f"  - {e}" for e in csv_errors))
        return 1
    docs, file_errors = prepare_documents(files)
    if file_errors:
        print("INVALID FILES:", file_errors)
        return 1

    settings = load_settings()
    print(f"model={settings.model} reasoning_effort={settings.reasoning_effort or '(not sent)'}")
    try:
        client = make_client(settings)
        _, checked = read_documents(client, settings, prior, docs, args.year)
    except LLMError as exc:
        print(f"CALL 1 FAILED: {exc}")
        return 1

    print("\n== Call 1 readings and checks")
    for c in checked:
        r = c.reading
        print(f"{r.doc_id}: {r.form_type.value} | {r.issuer_name} | {r.tax_year} | {r.key_amount} "
              f"| proposed={r.proposed_prior_entry_id} accepted={c.accepted_entry_id} "
              f"| grounding={'ok' if not c.grounding_failures else c.grounding_failures} "
              f"| rejection={c.match_rejection}")
        print(f"    rationale: {r.match_rationale}")

    findings = compute_findings(prior, docs, checked, args.year)
    print("\n== Findings", finding_counts(findings))
    try:
        q = draft_questions(client, settings, findings, args.year)
    except LLMError as exc:
        print(f"CALL 2 FAILED: {exc}")
        q = None
    for f in findings:
        print(f"{f.finding_id} {f.finding.value:<12} {f.current_doc_id or '-':<3} {f.prior_entry_id or '-':<3} "
              f"{f.form_type} | {f.current_issuer or f.prior_issuer} | {f.reason}")
        if q and f.finding_id in q.questions:
            print(f"    Q: {q.questions[f.finding_id]}")
    if q:
        print(f"\n== Summary\n{q.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
