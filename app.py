"""FinSight Streamlit UI. All request orchestration lives in orchestration.py."""

from __future__ import annotations

import hashlib

import streamlit as st

from config import load_settings
from embeddings import EmbeddingClient
from openai_client import OpenAIClient
from orchestration import ResearchAssistant, provider_failure_reason
from retrieval import HybridRetriever
from schemas import VerifiedResponse
from uploads import index_upload, remove_managed_upload


@st.cache_resource(show_spinner=False)
def resources(settings):
    if settings.embedding_provider not in {'minilm', 'local_hash'}:
        raise ValueError('The app uses local document embeddings. Set EMBEDDING_PROVIDER=minilm.')
    provider = OpenAIClient(settings)
    retriever = HybridRetriever(
        settings.qdrant_collection, settings.qdrant_path, EmbeddingClient(settings)
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
            "Index unavailable. Close other processes using this index, verify settings, and retry."
        )
        with st.expander("Index error"):
            st.write(type(exc).__name__)
    with st.sidebar:
        st.header("Your documents")
        uploaded = st.file_uploader(
            "Upload PDF or image (20 MB max)",
            type=["pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"uploads_{st.session_state.get('upload_generation', 0)}",
        )
        processed = st.session_state.setdefault("processed_uploads", {})
        for item in uploaded or []:
            data = item.getvalue()
            key = (item.name, hashlib.sha256(data).hexdigest())
            if retriever is not None and key not in processed:
                try:
                    with st.spinner(f"Preparing {item.name} for questions..."):
                        index_upload(item.name, data, retriever, "data/uploads/originals")
                    processed[key] = {'status': 'ready'}
                except Exception as exc:
                    detail = (
                        str(exc)
                        if isinstance(exc, ValueError)
                        and ("Identical document content" in str(exc)
                             or "No readable content" in str(exc))
                        else f"Check the file and retry ({type(exc).__name__})."
                    )
                    processed[key] = {'status': 'failed', 'detail': detail}
            result = processed.get(key)
            if result and result['status'] == 'failed':
                st.error(f"{item.name}: upload failed. {result['detail']} Other documents are preserved.")
            elif result:
                st.success(f"{item.name}: ready for questions")
            else:
                st.info(f"{item.name}: waiting for the document index to become available.")
        if any(result['status'] == 'failed' for result in processed.values()):
            if st.button("Retry failed uploads"):
                for key in list(processed):
                    if processed[key]['status'] == 'failed':
                        del processed[key]
                st.rerun()
        st.caption("Files are prepared automatically. Add more documents at any time.")
        names = retriever.source_names() if retriever else []
        known = st.session_state.get('known_sources', [])
        active = st.session_state.get('active_documents', names)
        updated = [n for n in names if n in active or n not in known]
        if 'active_documents' not in st.session_state or active != updated:
            st.session_state['active_documents'] = updated
        st.session_state['known_sources'] = names
        selected = st.multiselect(
            "Active documents", names, key="active_documents"
        )
        delete_source = st.selectbox("Delete a document", names, index=None,
                                     placeholder="Choose a file to delete")
        pending = st.session_state.get('pending_deletion')
        if st.button("Retry document deletion" if pending else "Delete file",
                     disabled=not retriever or not (delete_source or pending)):
            ids = pending or sorted({c.document_id for c in retriever.chunks
                                     if c.source_name == delete_source})
            st.session_state['pending_deletion'] = ids
            try:
                for document_id in ids:
                    retriever.delete_document(document_id)
                    remove_managed_upload(document_id, "data/uploads/originals")
                st.session_state.pop('pending_deletion', None)
                st.session_state.pop("active_documents", None)
                # Clear the uploader so the deleted file cannot be indexed on the next rerun.
                st.session_state['upload_generation'] = st.session_state.get('upload_generation', 0) + 1
                st.session_state['processed_uploads'] = {}
                st.session_state['history'] = []
                st.rerun()
            except Exception:
                st.error(
                    "Deletion was interrupted. Retry document deletion to finish removing the file."
                )
        st.caption(
            "Delete file removes its searchable evidence and stored upload copy."
        )
        if not settings.openai_configured:
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
                "Set OPENAI_WEB_ENABLED=true to enable the web option."
            )
        st.caption(
            "Web and visual reading are experimental and excluded from verified performance. Images are accepted for ingestion; image filenames are never numerical evidence."
        )
    with st.container():
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
                        retriever, provider, "hybrid"
                    ).ask(
                        query, selected, allow_web=allow_web, use_provider=True
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


if __name__ == "__main__":
    main()
