# TaxDocs Delta — Product Roadmap & Case-Study Plan

**Project:** AI-assisted tax document check for CPA firms  
**Context:** AI Engineer (Tax) take-home case study  
**Stage:** MVP implemented (see README status table for verified items)  


## 1. Project objective and business case

### Users and workflow

The direct user of this prototype is a **tax preparer**, not the taxpayer. Each season the firm collects tax documents from some recurring clients it had served before. Before preparing a return, the preparer has to establish whether the client's document set is complete: every recurring document from last year should be accounted for, new documents may signal new income or a life change, and some uploads are unusable (wrong year, not a tax form, unreadable scan).

**Problem:** Checking each client's uploads against last year's documents is repetitive manual work. Documents arrive in many layouts, issuers appear under different names, and most of a client's documents are unchanged, so the preparer spends time confirming sameness in order to find the few differences that matter.

**Proposed outcome:** A reviewed document checklist that shows what is matched, missing, new or needs review, with a drafted client question for each gap, produced in minutes and approved by the preparer.

**One-sentence pitch:** A preparer uploads a client's current-year tax documents; AI reads them, code compares them with last year's list, and the preparer gets a reviewed checklist of what is missing or new plus ready-to-send client questions.

### Business value hypothesis

- Less time manually matching uploads to last year's document list.
- Earlier detection of missing documents, before return preparation starts.
- Fewer, more specific follow-up rounds with clients.
- New documents surfaced as signals the preparer should ask about (e.g. new freelance income).

These are **hypotheses**, not measured benefits. They should be validated with CPA preparers. The prototype does not prepare returns or judge what must be reported.

## 2. Problem selection for the case study

The brief asks for **three candidate problems**, where each was encountered, who is affected, and why one was chosen, separating observation from assumption.

| Candidate problem | Where encountered / basis | Who is affected / what happens | Decision |
|---|---|---|---|
| **Checking whether recurring clients' tax documents are complete (selected)** | Work: as a financial data analyst in a finance department, I saw people spend a lot of time manually checking whether document packages were complete (reimbursements, audit preparation). Personal: comparing my old and new apartment leases with AI showed how well AI finds the few differences between long, mostly identical documents. | Tax preparers re-checking recurring clients' documents each season; missed or late documents delay returns and cause extra follow-up. | **Selected.** Recurs for every client every season; last year's list is a natural baseline; AI is needed for reading varied documents, code for exact comparison; demonstrable within the time limit. |
| Writing monthly variance commentary | Work: as a financial data analyst, analysts spent hours each month explaining budget-vs-actual variances in management reports. | Finance analysts and the managers who read the reports; reports go out late and explanations are inconsistent or superficial. | Not selected. The real reasons behind a variance usually sit outside the data (conversations with business owners), so AI could only draft surface-level commentary, and quality is hard to verify. |
| Numbers that do not match across reports | Work: in the same role, the same metric often showed different values in different reports and dashboards. | Analysts and leaders; time is lost reconciling figures, and decisions are made on conflicting numbers. | Not selected. The root cause is usually inconsistent metric definitions and upstream data pipelines; the fix is mainly data engineering and governance rather than AI. |

**Observed:** Manually checking document packages for completeness takes real time (finance department). AI reliably finds the few changes between long, similar documents (lease comparison). Commercial tax-document platforms advertise missing-document identification, which indicates firms pay to solve this.  
**Assumed:** Many CPA firms, especially smaller ones, still check client uploads against prior-year lists largely by hand; issuer-name variation and unusable uploads are common enough to matter; drafted client questions save follow-up time.

## 3. Alternative approaches and choice

| Approach | Strength | Limitation / decision |
|---|---|---|
| Manual check against last year's list | Full preparer control | Repetitive; the baseline process |
| Client self-check with a firm-provided organizer listing last year's documents | Cheap, already common | Clients miss items or cannot tell whether an upload is the right form; the preparer still verifies |
| Template/OCR document-scanning platforms (e.g. SurePrep 1040SCAN, which advertises missing-document identification) | Mature, integrated with tax software | Enterprise products; template-based reading; a credible alternative and a competitive risk |
| **LLM document reading + deterministic comparison + preparer review** | Reads unseen layouts and issuer-name variants without templates; exact, explainable comparison in code; drafts client questions | Model can misread; requires grounding checks and human review; **selected** |
| Autonomous agent that requests documents from clients | Could close the loop end to end | Removes preparer control over client communication; too broad for the time limit |

**Key design principle:** AI reads and drafts; deterministic code verifies and compares; the preparer decides.

## 4. MVP definition

### Single end-to-end workflow

1. Upload the prior-year CSV and current-year PDFs (synthetic samples in `data/`).
2. Validate the CSV and extract text from each PDF; flag unreadable files before any model call.
3. **LLM call 1:** read every readable document into a fixed schema and propose prior-year matches.
4. Verify readings against document text; accept or reject matches by rule.
5. Compute findings: Matched, Missing, New, Needs Review.
6. **LLM call 2:** draft a short summary and a client question for each Missing, New and wrong-year finding.
7. Preparer review: Confirmed / Ask Client / Dismissed; edit questions.
8. Export the reviewed checklist (CSV) and a client request list (text).

### Concrete demo situations

Tax year 2025 (income year 2025, filed in 2026) compared with tax year 2024.

| Prior year 2024 (on file) | Current year 2025 (uploaded) | Expected finding |
|---|---|---|
| W-2, ABC Design Co. | W-2, ABC Design Co. | Matched |
| 1099-INT, Ally Bank | 1099-INT, Ally Bank | Matched |
| 1099-INT, Chase | 1099-INT, "JPMorgan Chase Bank, N.A." | Matched (issuer-name variant) |
| 1099-DIV, Vanguard | 1099-DIV, "The Vanguard Group" | Matched |
| 1098, Rocket Mortgage | — | **Missing** → client question |
| — | 1099-NEC, XYZ Studio LLC | **New** → client question |

Difficult sample (additional uploads):

- A **2024** 1099-INT uploaded by mistake → Needs Review (wrong tax year); the 2025 form is requested.
- A utility bill PDF → Needs Review (`Other`, not a tax form).
- A scanned image PDF with no text layer → Needs Review (unreadable), not sent to the model.
- A document whose text contains an instruction to the model → ignored; reading based on document facts.
- An invalid prior-year CSV (duplicate ID, unknown form type) → clear error, no model call.

### Deliberately excluded from the MVP

Amount comparison or variance thresholds. Amounts are extracted and shown for reference only; the MVP is about **document completeness and identity**. Amount variance is a listed next step.

## 5. Explicit scope boundary

### Included

- One-page Streamlit UI with file upload (synthetic samples provided in `data/`).
- Prior-year CSV validation; 1–15 text-based PDFs per run.
- Two LLM calls with Pydantic Structured Outputs; grounding and match-rule checks in code.
- Deterministic findings; editable drafted client questions; reviewer statuses; exports.
- Focused Pytest tests; public demo (deployed on Render); README, written submission, video.

### Not included

- OCR, scanned-image reading, handwriting.
- Field-level data entry into tax software; amount comparison; tax calculations or advice.
- Client portals, email, e-signature, multi-client queues, authentication, persistence.
- RAG over tax law, autonomous agents, fine-tuning, a benchmarking harness.

**Input assumption:** the firm has a prior-year document list per client (from its own records or last year's return), and the client's current-year documents are text-based PDFs. This is a conscious MVP shortcut.

## 6. Engineering and architecture outline

- **Streamlit:** inputs, Check Documents action, findings review, downloads.
- **pypdf:** text extraction; readability check.
- **Pydantic:** form-type enum, reading and question schemas.
- **OpenAI Python SDK + Responses API:** two structured calls per run, configurable by `MODEL_NAME` (subject to verified access and billing). Credentials from `OPENAI_API_KEY` in environment variables or Streamlit secrets; `store=False`.
- **Python comparison logic:** grounding, match rules, findings — fully unit-tested.
- **Session State:** current review only; no database.
- **reportlab (dev only):** generates synthetic sample PDFs.
- **GitHub + Render:** source control and public deployment.

The detailed contracts, checks and failure behavior are in [architecture.md](architecture.md).

## 7. Work plan and stage gates

| Phase | Target | Minutes | Completion evidence |
|---|---|---:|---|
| 0. Repository and model access | Repo, Python env, one successful structured API call | 15 | Live model access confirmed |
| 1. Samples and contracts | Synthetic PDFs + prior-year CSVs; schemas; CSV/PDF validation | 30 | Samples generate; invalid CSV fails clearly; scanned PDF detected |
| 2. Document reading | LLM call 1, ID integrity, grounding, match rules | 45 | Real readings for all sample documents; name variant matched |
| 3. Comparison + questions | Findings logic; LLM call 2 | 30 | Correct Missing/New/Needs Review; specific questions |
| 4. UI, review, export | Streamlit flow, reviewer statuses, editable questions, downloads | 40 | Local input → check → review → export works |
| 5. Focused tests | Pytest for checks, comparison, export; manual difficult case | 15 | Tests pass |
| 6. Deployment | GitHub push, Cloud secrets, public URL smoke test | 20 | Unauthenticated evaluator can use the demo |
| 7. Written materials | README, ≤4-page submission, walkthrough script | 25 | Documents match the actual build |
| 8. Video | 5–10-minute walkthrough | 20 | Shareable video exists |
| **Total** | | **240** | Four-hour stop rule |

If time is short, cut visual polish and the call-2 summary paragraph first; keep document reading, comparison, client questions, deployment, minimum documentation and the video.

## 8. Acceptance criteria

- [x] Findings change when inputs change; outputs are not hardcoded or prerecorded.
- [x] Real structured LLM readings with exactly one reading per readable document.
- [x] Extracted issuer, tax year and amount are verified against document text; failures are flagged.
- [x] Issuer-name variants of the same institution match; different form types never match.
- [x] Missing and New findings are correct on both sample sets.
- [x] Wrong-year, non-tax and unreadable files are flagged, never silently matched or dropped.
- [x] Each Missing/New finding has a specific, editable client question.
- [x] Preparer can confirm, ask client or dismiss; decisions survive reruns and appear in exports.
- [x] Invalid CSV and API/output failures are visible and never replaced with fake results.
- [x] Tests run, app works on a public link, secrets are not in the repo.
- [x] Written submission and 5–10-minute walkthrough satisfy the brief.

## 9. Case-study written submission (up to four pages)

1. **Three candidate problems** (§2) and why the document check was chosen; observed vs assumed.
2. **Customer and workflow:** preparer checking recurring clients' document sets before preparing returns.
3. **Current process vs proposed workflow;** credible alternatives (organizer self-check, template/OCR platforms) and why this first step.
4. **Where AI vs code:** AI reads heterogeneous documents and drafts questions; code grounds, matches and decides findings; preparer approves. Why not a general chatbot.
5. **Demo and verification:** standard and difficult samples; implemented, mocked (synthetic documents) and deferred; tests and limitations.
6. **Reflection:** actual time, AI tools used and how output was checked, prior work reused, next investigations, reasons to stop.

## 10. Other deliverables

| Deliverable | Content | Important note |
|---|---|---|
| Live prototype URL | Public app running real LLM calls (Render) | Verified |
| Source repository | Modules, synthetic samples and generator, `requirements.txt`, tests | No credentials or real documents in Git history |
| `README.md` | What it does, users, input formats, setup/run commands, example inputs and expected outputs, architecture, limits, demo URL | Describes only completed functionality after build |
| Written submission | Concise response to all brief prompts, max four pages | Observed vs assumed; implemented vs mocked vs deferred |
| Video walkthrough | 5–10 minutes | Recorded |

## 11. What comes next — and what would invalidate the idea?

**Next:** OCR or a document-AI service for scanned uploads; importing last year's document list from the firm's tax software instead of a hand-made CSV; year-over-year amount variance flags with preparer-set thresholds; a per-firm issuer alias table learned from corrections; a multi-client queue ordered by deadlines; measuring reading accuracy, match precision and preparer time on CPA-labelled document sets.

**What would invalidate it:** target firms already use a document platform that reliably flags missing documents; preparers spend little time on this step; reading or matching errors force full manual re-checks; or clients' uploads are mostly scanned images that require OCR beyond the MVP.

## 12. Factual references

- IRS General Instructions for Forms W-2 and W-3: https://www.irs.gov/instructions/iw2w3
- IRS Publication 1099 (General Instructions for Certain Information Returns): https://www.irs.gov/publications/p1099
- SurePrep 1040SCAN version comparison (vendor material): https://corp.sureprep.com/wp-content/uploads/1040SCAN-Version-Comparison-Web.pdf
- Render web service deployment: https://render.com/docs/your-first-deploy
- OpenAI Structured Outputs: https://developers.openai.com/api/docs/guides/structured-outputs

**Status:** Original plan, updated where the build differs. Verified build status is tracked in the README status table.
