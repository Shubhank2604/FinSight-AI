"""FinSight Streamlit UI. All request orchestration lives in orchestration.py."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from config import load_settings
from ingestion import ingest_file
from openai_client import OpenAIClient
from orchestration import ResearchAssistant, provider_failure_reason
from retrieval import HybridRetriever
from schemas import VerifiedResponse
from ui_calculators import _render_tool_forms
from uploads import save_upload


@st.cache_resource(show_spinner=False)
def resources(settings):
    provider = OpenAIClient(settings)
    retriever = HybridRetriever(
        settings.qdrant_collection, settings.qdrant_path, provider
    )
    return retriever, provider


def display_response(response):
    if response.status == "experimental":
        st.info(
            "Experimental result: source freshness and claim support have not been verified."
        )
        st.write(response.answer)
    elif response.status != "ok":
        st.warning(
            f"{response.status.replace('_', ' ').capitalize()}: {response.answer}"
        )
    else:
        st.write(response.answer)
    for reason in response.reasons:
        st.caption(reason)
    if response.citations:
        st.markdown("**Supporting evidence**")
        for citation in response.citations:
            location = citation.source_name + (
                f", page {citation.page}" if citation.page else ""
            )
            st.markdown(f"**{location}** · `{citation.chunk_id}`")
            if citation.url:
                st.markdown(f"[{location}]({citation.url})")
            st.caption(citation.snippet)
            if citation.metadata.get("original_page"):
                st.caption(
                    f"Excerpt from original PDF page {citation.metadata['original_page']}."
                )
            if citation.metadata.get("units"):
                st.caption("Document units: " + str(citation.metadata["units"]))
    for calculation in response.calculations:
        with st.expander(f"Inputs and result: {calculation.tool_name}", expanded=True):
            st.json(calculation.inputs)
            st.json(calculation.result)
            st.caption("Formula / method: " + calculation.trace)
            if calculation.provenance:
                st.markdown("**Input sources and units**")
                st.json(calculation.provenance)
            for assumption in calculation.assumptions:
                st.caption(assumption)
    if response.assumptions:
        st.caption(" ".join(response.assumptions))
    with st.expander("Advanced diagnostics"):
        st.json(response.diagnostics)


def main():
    st.set_page_config(page_title="FinSight AI", layout="wide")
    st.title("FinSight AI")
    st.caption(
        "Financial document research and deterministic calculations. Each question is independent; earlier turns are not used as evidence."
    )
    try:
        settings = load_settings()
    except ValueError as exc:
        st.error(str(exc))
        return
    retriever, provider = None, None
    try:
        retriever, provider = resources(settings)
    except Exception as exc:
        st.error(
            "Index unavailable. Close other processes using this index, verify settings, and retry. Calculators remain available."
        )
        with st.expander("Index error"):
            st.write(type(exc).__name__)
    with st.sidebar:
        st.header("Document scope")
        uploaded = st.file_uploader(
            "Upload PDF or image (20 MB max)",
            type=["pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
        )
        if st.button("Index uploads", disabled=not retriever or not uploaded):
            for item in uploaded:
                try:
                    path = save_upload(
                        item.name, item.getvalue(), "data/uploads/originals"
                    )
                    chunks = ingest_file(
                        path, source_name=Path(item.name.replace("\\", "/")).name
                    )
                    count = retriever.index_chunks(chunks)
                    st.success(f"{item.name}: {count} new chunks")
                except Exception as exc:
                    detail = (
                        str(exc)
                        if isinstance(exc, ValueError)
                        and "Identical document content" in str(exc)
                        else f"Check the file and retry ({type(exc).__name__})."
                    )
                    st.error(
                        f"{item.name}: ingestion failed. {detail} Prior documents are preserved."
                    )
        names = retriever.source_names() if retriever else []
        selected = st.multiselect(
            "Active documents", names, default=names, key="active_documents"
        )
        if st.button(
            "Remove selected documents", disabled=not retriever or not selected
        ):
            ids = {c.document_id for c in retriever.chunks if c.source_name in selected}
            try:
                for document_id in ids:
                    retriever.delete_document(document_id)
                st.session_state.pop("active_documents", None)
                st.rerun()
            except Exception:
                st.error(
                    "Removal was interrupted. Restart the index to complete recovery, then retry."
                )
        st.caption(
            "Removal deletes indexed evidence. Original private uploads remain in your local data/uploads folder."
        )
        use_provider = st.checkbox("Use OpenAI for document explanations", value=False)
        retrieval_mode = st.selectbox(
            "Retrieval method",
            ["bm25", "dense", "hybrid"],
            help="BM25 is the measured credential-free default. Dense and hybrid use the configured embedding provider; local_hash is a regression embedding, not a semantic model.",
        )
        if use_provider and not settings.openai_configured:
            st.warning(
                "Set OPENAI_API_KEY in your local .env or environment to enable OpenAI generation."
            )
        allow_web = st.checkbox(
            "Allow web access (experimental)",
            value=False,
            disabled=not settings.web_enabled,
        )
        if not settings.web_enabled:
            st.caption(
                "Set OPENAI_WEB_ENABLED=true to enable the web option. OpenAI generation must also be selected."
            )
        st.caption(
            "Web and visual reading are experimental and excluded from verified performance. Images are accepted for ingestion; image filenames are never numerical evidence."
        )
    research_tab, calculator_tab = st.tabs(["Document research", "Calculators"])
    with research_tab:
        for item in st.session_state.get("history", []):
            with st.chat_message("user"):
                st.write(item["query"])
            with st.chat_message("assistant"):
                display_response(VerifiedResponse.model_validate(item["response"]))
        with st.form("query_form", clear_on_submit=True):
            query = st.text_area(
                "Question",
                key="query",
                placeholder="Calculate the current ratio for 2025 in the report",
            )
            submitted = st.form_submit_button("Ask", type="primary")
        if submitted:
            st.session_state["pending_request"] = query
            try:
                with st.spinner("Checking inputs and evidence..."):
                    response = ResearchAssistant(
                        retriever, provider, retrieval_mode
                    ).ask(
                        query, selected, allow_web=allow_web, use_provider=use_provider
                    )
            except Exception as exc:
                reason = provider_failure_reason(exc)
                response = VerifiedResponse(answer=reason, status="provider_failure", reasons=[reason], confidence=0.0)
            finally:
                st.session_state["pending_request"] = None
            st.session_state.setdefault("history", []).append(
                    {"query": query, "response": response.model_dump(mode="json")}
            )
            st.rerun()
    with calculator_tab:
        _render_tool_forms()
        st.caption(
            "Tax requires a reviewed jurisdiction/year rule pack; the bundled demo pack is deliberately rejected."
        )


if __name__ == "__main__":
    main()
