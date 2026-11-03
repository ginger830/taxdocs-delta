"""TaxDocs Delta — Streamlit UI only. All logic lives in src/ and is testable without Streamlit."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.compare import compute_findings, finding_counts
from src.documents import (
    input_fingerprint,
    load_sample,
    prepare_documents,
    validate_prior_csv,
)
from src.extractor import LLMError, load_settings, make_client, read_documents
from src.questions import draft_questions
from src.review import (
    Decision,
    ask_client_items,
    checklist_csv,
    client_request_text,
    default_decisions,
)
from src.schemas import FindingStatus, ReviewerStatus

st.set_page_config(page_title="TaxDocs Delta", layout="wide")

SOURCES = {
    "Sample: sample_client": ("sample_client", False),
    "Sample: difficult_client": ("difficult_client", False),
    "Sample: difficult_client with invalid prior-year CSV": ("difficult_client", True),
    "Upload my own files": (None, False),
}
BADGE = {
    FindingStatus.MATCHED: ":green[**Matched**]",
    FindingStatus.MISSING: ":orange[**Missing**]",
    FindingStatus.NEW: ":blue[**New**]",
    FindingStatus.NEEDS_REVIEW: ":red[**Needs Review**]",
}
RESULT_KEYS = ["documents_checked", "batch", "checked", "findings", "questions",
               "questions_error", "run_error", "decisions"]


def esc(text: object) -> str:
    """Escape characters Streamlit markdown would interpret ($ -> LaTeX)."""
    return str(text).replace("$", "\\$")


def reset_results() -> None:
    for k in RESULT_KEYS:
        st.session_state.pop(k, None)
    for k in [k for k in st.session_state if k.startswith(("status_", "question_"))]:
        del st.session_state[k]


# ---------------------------------------------------------------- header

st.title("TaxDocs Delta")
st.caption("Year-over-year tax document check for CPA firms: what is matched, missing, new or needs review.")
st.warning(
    "**Synthetic documents only.** This public prototype is for the bundled synthetic samples. "
    "Do not upload real tax documents or any personal information."
)

settings = load_settings()

# ---------------------------------------------------------------- inputs

col_a, col_b = st.columns([1, 2])
with col_a:
    current_year = int(st.number_input("Current tax year", min_value=2000, max_value=2100, value=2025, step=1))
    prior_year = current_year - 1
    st.caption(f"Prior tax year: {prior_year}")
with col_b:
    source = st.radio("Input", list(SOURCES), index=0)

sample_name, invalid_csv = SOURCES[source]
csv_bytes: bytes | None = None
files: list[tuple[str, bytes]] = []
if sample_name:
    csv_bytes, files = load_sample(sample_name, invalid_csv=invalid_csv)
else:
    up_csv = st.file_uploader("Prior-year document list (CSV)", type=["csv"])
    up_pdfs = st.file_uploader("Current-year documents (1–15 PDFs, ≤ 5 MB each)", type=None,
                               accept_multiple_files=True)
    if up_csv is not None:
        csv_bytes = up_csv.getvalue()
    files = [(f.name, f.getvalue()) for f in (up_pdfs or [])]

if csv_bytes is None or not files:
    st.info("Provide a prior-year CSV and at least one current-year PDF.")
    st.stop()

fingerprint = input_fingerprint(csv_bytes, files, current_year)
if st.session_state.get("input_fingerprint") != fingerprint:
    reset_results()
    st.session_state["input_fingerprint"] = fingerprint

# Validation runs on every rerun; it is local and never calls the model.
prior_entries, csv_errors = validate_prior_csv(csv_bytes, prior_year)
documents, file_errors = prepare_documents(files)

left, right = st.columns(2)
with left:
    st.subheader("Prior-year document list")
    if csv_errors:
        st.error("The prior-year CSV is invalid. Nothing will be sent to the model.\n\n"
                 + "\n".join(f"- {esc(e)}" for e in csv_errors))
    else:
        st.dataframe(pd.DataFrame([e.model_dump(mode="json") for e in prior_entries]),
                     hide_index=True, width="stretch")
with right:
    st.subheader("Current-year documents")
    if file_errors:
        st.error("\n".join(f"- {esc(e)}" for e in file_errors))
    else:
        st.dataframe(
            pd.DataFrame([
                {"doc_id": d.doc_id, "filename": d.filename, "KB": round(d.size_bytes / 1024, 1),
                 "text chars": d.char_count,
                 "status": "readable" + (" (truncated)" if d.truncated else "") if d.readable
                 else "UNREADABLE — not sent to model"}
                for d in documents
            ]),
            hide_index=True, width="stretch",
        )

readable_count = sum(d.readable for d in documents)
blocked = bool(csv_errors or file_errors)
if not blocked and readable_count == 0:
    st.error("No readable PDFs: every document is unreadable, so nothing can be sent to the model.")
    blocked = True

st.caption(
    f"Model: `{settings.model}` · reasoning effort: `{settings.reasoning_effort or 'not sent'}` · "
    f"API key: {'configured' if settings.api_key else 'NOT configured'} · "
    f"{readable_count} readable document(s) will be sent in one call"
)

# ---------------------------------------------------------------- run

if st.button("Check Documents", type="primary", disabled=blocked):
    reset_results()
    try:
        client = make_client(settings)
        with st.spinner("Reading documents (LLM call 1)…"):
            batch, checked = read_documents(client, settings, prior_entries, documents, current_year)
    except LLMError as exc:
        st.session_state["run_error"] = str(exc)
    else:
        findings = compute_findings(prior_entries, documents, checked, current_year)
        st.session_state.update(documents_checked=documents, batch=batch, checked=checked, findings=findings)
        ai_questions: dict[str, str] = {}
        try:
            with st.spinner("Drafting client questions (LLM call 2)…"):
                result = draft_questions(client, settings, findings, current_year)
            st.session_state["questions"] = result
            ai_questions = result.questions
        except LLMError as exc:
            st.session_state["questions_error"] = str(exc)
        st.session_state["decisions"] = default_decisions(findings, ai_questions)

if st.session_state.get("run_error"):
    st.error(f"**Check failed — no results were produced.** {esc(st.session_state['run_error'])}")

findings = st.session_state.get("findings")
if not findings:
    st.stop()

# ---------------------------------------------------------------- results

st.divider()
st.header("Findings")
counts = finding_counts(findings)
for col, (label, n) in zip(st.columns(4), counts.items()):
    col.metric(label, n)

questions = st.session_state.get("questions")
ai_questions = questions.questions if questions else {}
if questions and questions.summary:
    st.info(esc(questions.summary))
if st.session_state.get("questions_error"):
    st.error(f"**Client questions unavailable.** {esc(st.session_state['questions_error'])}")

with st.expander("Model readings and code checks (call 1)"):
    checked = st.session_state["checked"]
    st.dataframe(
        pd.DataFrame([
            {"doc_id": c.reading.doc_id, "form_type": c.reading.form_type.value,
             "issuer (as read)": c.reading.issuer_name, "tax_year": c.reading.tax_year,
             "key_amount": c.reading.key_amount, "amount label": c.reading.key_amount_label,
             "proposed match": c.reading.proposed_prior_entry_id,
             "accepted match": c.accepted_entry_id,
             "grounding": "ok" if not c.grounding_failures else "NOT FOUND: " + ", ".join(c.grounding_failures),
             "match rejection": c.match_rejection, "model rationale": c.reading.match_rationale}
            for c in checked
        ]),
        hide_index=True, width="stretch",
    )
    st.caption("The model reads and proposes; code verifies every value against the document text "
               "and accepts or rejects each proposed match. Amounts are for reference only and never compared.")

st.subheader("Review")
st.caption("Set a reviewer status for each finding and edit questions. Reviewer status never changes the computed finding.")
decisions: dict[str, Decision] = st.session_state["decisions"]
status_options = [s.value for s in ReviewerStatus]

for f in findings:
    d = decisions[f.finding_id]
    skey, qkey = f"status_{f.finding_id}", f"question_{f.finding_id}"
    if skey not in st.session_state:
        st.session_state[skey] = d.status.value
    if qkey not in st.session_state:
        st.session_state[qkey] = d.final_question
    with st.container(border=True):
        c1, c2 = st.columns([4, 1])
        with c1:
            parts = [p for p in [f.form_type, f.current_issuer or f.prior_issuer,
                                 str(f.tax_year) if f.tax_year else None] if p]
            doc = f" · {f.current_doc_id} `{f.current_filename}`" if f.current_doc_id else ""
            prior = f" · prior {f.prior_entry_id} ({f.prior_issuer})" if f.prior_entry_id else ""
            st.markdown(f"**{f.finding_id}** {BADGE[f.finding]} — {esc(' · '.join(parts) or 'unidentified')}"
                        f"{esc(doc)}{esc(prior)}")
            amount = (f" · Amount (reference only): {f.key_amount_reference}"
                      + (f" — {f.key_amount_label}" if f.key_amount_label else "")) if f.key_amount_reference else ""
            st.caption(esc(f.reason + amount))
        with c2:
            st.selectbox("Reviewer status", status_options, key=skey, label_visibility="collapsed")
        if f.finding is not FindingStatus.MATCHED:
            st.text_area("Client question", key=qkey, height=70,
                         placeholder="No AI draft — type a question if you want to ask the client.")
            ai = ai_questions.get(f.finding_id)
            if ai and st.session_state[qkey] != ai:
                st.caption(f"AI draft: {esc(ai)}")
    decisions[f.finding_id] = Decision(status=ReviewerStatus(st.session_state[skey]),
                                       final_question=st.session_state.get(qkey, d.final_question))

# ---------------------------------------------------------------- export

st.divider()
st.header("Export")
reviewed = sum(d.status is not ReviewerStatus.PENDING for d in decisions.values())
st.caption(f"{reviewed} of {len(findings)} findings reviewed. Nothing is sent to the client automatically.")
request_text = client_request_text(findings, decisions, current_year)
empty_asks = [f.finding_id for f, q in ask_client_items(findings, decisions) if not q]
if empty_asks:
    st.warning(f"Marked Ask Client but no question text (left out of the request list): {', '.join(empty_asks)}")

e1, e2 = st.columns(2)
with e1:
    st.download_button("Download checklist (CSV)", checklist_csv(findings, ai_questions, decisions),
                       file_name=f"document_checklist_{current_year}.csv", mime="text/csv")
with e2:
    st.download_button("Download client request list (TXT)", request_text or "",
                       file_name=f"client_request_{current_year}.txt", mime="text/plain",
                       disabled=not request_text)
if request_text:
    st.text_area("Client request list preview (Ask Client items only)", request_text, height=220, disabled=True)
else:
    st.caption("Mark findings as **Ask Client** to build the client request list.")
