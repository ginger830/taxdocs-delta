# TaxDocs Delta

**AI-assisted year-over-year tax document check for CPA firms**  
*MiraFlores AI — AI Engineer (Tax) case study prototype*

## Overview

Every tax season, a CPA firm collects tax documents from the same clients it served last year: W-2s, 1099s, mortgage interest statements and similar forms. Most of a client's documents repeat from year to year. What the preparer actually needs to know is **what changed**: which documents from last year have not arrived yet, which documents are new, and which uploads are not usable (wrong tax year, not a tax form, unreadable).

TaxDocs Delta explores that workflow. A preparer uploads the client's current-year document PDFs. A language model reads each document — whatever the issuer's layout — and identifies the form type, issuer and tax year. Deterministic code then compares the current-year set with the firm's prior-year document list and reports **missing**, **new**, **matched** and **needs-review** items. For each missing or new item, the model drafts a specific question for the client. The preparer reviews every finding before exporting a document checklist and a client request list.

**Product pitch:** Upload this year's documents → see what is missing, new or unusable compared with last year → review the drafted client questions → export a checklist and client request.

This is **not** tax preparation, tax advice, data entry into tax software, or a determination of what must be reported.

## Who it is for

- **Platform provider:** MiraFlores AI, which develops AI-driven tax and accounting workflows.
- **Business customer:** CPA firms preparing individual returns for recurring clients.
- **Primary user:** A tax preparer checking whether a client's document set is complete before preparing the return.
- **End customer:** A taxpayer who may need to send a missing document or explain a new one.

The business value is a **hypothesis**, not a measured outcome: less time manually checking uploads against last year's list, and fewer rounds of follow-up with clients. The prototype uses synthetic documents and does not demonstrate production savings.

## Core workflow

1. **Input:** The firm's prior-year document list for the client (CSV) and the client's current-year document PDFs.
2. **Read documents (AI):** One batch LLM call identifies each PDF's form type, issuer, tax year and key amount, and proposes which prior-year entry it corresponds to, even when the issuer name is written differently.
3. **Verify (code):** Extracted values must appear in the document's own text; proposed matches must be one-to-one and of the same form type.
4. **Compare (code):** Prior-year entries without a match are **Missing**; current documents without a match are **New**; wrong-year, unrecognized and unreadable files are **Needs Review**.
5. **Draft questions (AI):** One LLM call writes a short summary and a specific client question for each missing or new item.
6. **Human review:** The preparer marks each finding `Confirmed`, `Ask Client` or `Dismissed` and can edit any question.
7. **Export:** Download the reviewed document checklist (CSV) and a client request list (text). Nothing is sent automatically.

### An example

| Prior year (2024, on file) | Current year (2025, uploaded) | Finding | Next step |
|---|---|---|---|
| W-2 — ABC Design Co. | W-2 — ABC Design Co. | Matched | None |
| 1099-INT — Chase | 1099-INT — "JPMorgan Chase Bank, N.A." | Matched (name variant) | None |
| 1098 — Rocket Mortgage | — | **Missing** | Ask client: "Last year we received a mortgage interest statement (Form 1098) from Rocket Mortgage. We have not received one for 2025 — did you sell, refinance, or is it still on the way?" |
| — | 1099-NEC — XYZ Studio LLC | **New** | Ask client to confirm the new freelance income source |
| — | 1099-INT for **2024** | **Needs Review** (wrong tax year) | Ask client for the 2025 form |

All sample clients, documents, and values are synthetic.

## Inputs and expected results

Prior-year document list (CSV):

```csv
entry_id,form_type,issuer_name,tax_year,key_amount,notes
P1,W-2,ABC Design Co.,2024,85000.00,
P2,1099-INT,Ally Bank,2024,300.00,
P3,1099-INT,Chase,2024,45.00,
P4,1098,Rocket Mortgage,2024,9200.00,
P5,1099-DIV,Vanguard,2024,640.00,
```

- `entry_id`: unique nonempty value
- `form_type`: one of the supported form types (see architecture)
- `issuer_name`: nonempty text, as recorded by the firm
- `tax_year`: the prior tax year (default 2024)
- `key_amount`: optional, for reference only — the prototype does not compare amounts
- Current-year documents: 1–15 text-based PDFs, each within a size limit

Model output wording varies. **Expected behavior** is stable: a document that is not in last year's list is reported as new; a prior-year entry with no current document is reported as missing; issuer-name variants of the same institution match; wrong-year, non-tax and unreadable files are flagged rather than silently matched or dropped.

## Technology and architecture

| Area | Proposed approach |
|---|---|
| Interface | Streamlit, one-page workflow |
| Application | Python 3.12, small modular codebase |
| PDF text | `pypdf` text extraction (no OCR) |
| AI | OpenAI Python SDK, Responses API with Pydantic Structured Outputs; two calls per run |
| Validation & comparison | Pydantic + deterministic Python checks |
| State | Streamlit Session State for the current review; no persistent DB |
| Deployment | Streamlit Community Cloud connected to GitHub |
| Tests | Pytest for input validation, grounding checks, matching and export |

The rationale, component boundaries, data contracts, error states and review semantics are documented in [docs/architecture.md](docs/architecture.md). Scope, milestones, acceptance criteria and case-study deliverables are in [docs/roadmap.md](docs/roadmap.md).

## Local setup and usage

> **Project status:** This README describes the target MVP. Commands below apply once implementation files and dependencies have been added; a working deployment and test results have **not** been verified in this planning document.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Set `OPENAI_API_KEY` as a local environment variable or place it in a local, Git-ignored `.streamlit/secrets.toml`. Configure `MODEL_NAME` for a verified OpenAI model that supports Structured Outputs. Never commit API keys.

```bash
streamlit run app.py
```

Expected use: load the synthetic sample client (or upload a prior-year CSV and current-year PDFs), click **Check Documents**, review the findings and drafted questions, mark each finding, then export the checklist and client request list.

### Development tests

```bash
python -m pytest -q
```

A public demo URL, tested model identifier, and observed test results belong here **after they exist**; they are intentionally not fabricated in the planning version.

## Safety, assumptions, and limitations

- **Synthetic data only.** Sample documents use fictitious names and masked identifiers. Real tax documents contain SSNs/TINs and must not be uploaded to the public demo.
- Text-based PDFs only; scanned images are reported as unreadable (no OCR in the MVP).
- The tool reports document presence and identity, not whether amounts are correct or how they affect the return.
- AI output is checked against the document text, but a passed check does not prove the reading is correct; the preparer reviews every finding.
- API or validation failures are visible. The app does not substitute canned results for live model output.
- A public prototype is not a production-safe system for real taxpayer data.

## Case-study context

The case study evaluates problem selection, practical implementation, tradeoffs, a real working prototype, one difficult or invalid-input case, and transparent disclosure of what is implemented, mocked, or deferred. The submission includes source code, a reproducible README, a live link, a written explanation of no more than four pages, and a 5–10-minute video walkthrough.

## References

- [MiraFlores AI product](https://miraflores.ai/product)
- [IRS General Instructions for Forms W-2 and W-3](https://www.irs.gov/instructions/iw2w3)
- [IRS Publication 1099, General Instructions for Certain Information Returns](https://www.irs.gov/publications/p1099)
- [Streamlit Community Cloud deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

---

**Current status:** Project design / pre-implementation. After the app is built, this README should reflect only verified features, exact environment requirements, test results, and deployment links.
