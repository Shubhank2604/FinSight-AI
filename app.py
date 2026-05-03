from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from config import load_settings
from fallback_answers import local_educational_answer
from gemini_client import GeminiClient
from ingestion import ingest_file
from retrieval import HybridRetriever
from router import route_query
from schemas import RetrievalHit, Route, RouterDecision, StructuredLLMAnswer, ToolCalculation, ToolResult
from tools import (
    calculate_emi,
    estimate_tax,
    price_black_scholes_option,
    simulate_portfolio_growth,
)
from verifier import verify_response


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "resource_exhausted" in text or "quota" in text


CACHE_VERSION = "2026-05-03-local-embedding-v1"


def _amount_to_float(value: str, unit: str | None) -> float:
    amount = float(value.replace(",", ""))
    unit = (unit or "").lower()
    multipliers = {
        "k": 1_000,
        "lakh": 100_000,
        "lac": 100_000,
        "cr": 10_000_000,
        "crore": 10_000_000,
        "m": 1_000_000,
        "million": 1_000_000,
    }
    return amount * multipliers.get(unit, 1)


def _extract_amounts(query: str) -> list[float]:
    matches = re.findall(
        r"(\d[\d,]*(?:\.\d+)?)\s*(k|lakh|lac|cr|crore|m|million)?",
        query,
        flags=re.IGNORECASE,
    )
    return [_amount_to_float(value, unit) for value, unit in matches]


def _extract_currency(query: str) -> str:
    lowered = query.lower()
    currency_patterns = [
        (r"(\$|\busd\b|\bdollar\b|\bdollars\b)", "USD"),
        (r"(eur\b|\beuro\b|\beuros\b)", "EUR"),
        (r"(gbp\b|\bpound\b|\bpounds\b|\bsterling\b)", "GBP"),
        (r"(inr\b|\brs\.?\b|\brupee\b|\brupees\b)", "INR"),
        (r"(jpy\b|\byen\b)", "JPY"),
        (r"(cad\b|\bcanadian dollar\b)", "CAD"),
        (r"(aud\b|\baustralian dollar\b)", "AUD"),
        (r"(sgd\b|\bsingapore dollar\b)", "SGD"),
        (r"(aed\b|\bdirham\b|\bdirhams\b)", "AED"),
    ]
    if "₹" in query:
        return "INR"
    if "€" in query:
        return "EUR"
    if "£" in query:
        return "GBP"
    if "¥" in query:
        return "JPY"
    for pattern, currency in currency_patterns:
        if re.search(pattern, lowered):
            return currency
    return "USD"


def _extract_percent(query: str) -> float | None:
    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", query)
    if percent_match:
        return float(percent_match.group(1))

    keyword_match = re.search(
        r"(?:rate|interest|return|cagr)\D{0,20}(\d+(?:\.\d+)?)",
        query,
        flags=re.IGNORECASE,
    )
    if keyword_match:
        return float(keyword_match.group(1))
    return None


def _extract_years(query: str) -> float | None:
    year_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:year|years|yr|yrs)", query, re.I)
    if year_match:
        return float(year_match.group(1))

    month_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:month|months)", query, re.I)
    if month_match:
        return float(month_match.group(1)) / 12
    return None


def _run_emi_from_query(query: str) -> ToolResult:
    amounts = _extract_amounts(query)
    annual_rate_pct = _extract_percent(query)
    years = _extract_years(query)
    currency = _extract_currency(query)

    if not amounts or annual_rate_pct is None or years is None:
        missing = []
        if not amounts:
            missing.append("principal")
        if annual_rate_pct is None:
            missing.append("annual_rate_pct")
        if years is None:
            missing.append("tenure")
        return ToolResult(success=False, error=f"Missing inputs: {', '.join(missing)}")

    return calculate_emi(
        principal=amounts[0],
        annual_rate_pct=annual_rate_pct,
        tenure_months=int(round(years * 12)),
        currency=currency,
    )


def _run_portfolio_from_query(query: str) -> ToolResult:
    amounts = _extract_amounts(query)
    annual_return_pct = _extract_percent(query)
    years = _extract_years(query)
    currency = _extract_currency(query)

    if not amounts or annual_return_pct is None or years is None:
        missing = []
        if not amounts:
            missing.append("monthly_investment")
        if annual_return_pct is None:
            missing.append("annual_return_pct")
        if years is None:
            missing.append("years")
        return ToolResult(success=False, error=f"Missing inputs: {', '.join(missing)}")

    return simulate_portfolio_growth(
        monthly_investment=amounts[0],
        annual_return_pct=annual_return_pct,
        years=years,
        currency=currency,
    )


def _tool_answer(tool_result: ToolResult) -> str:
    if not tool_result.success or tool_result.calculation is None:
        return tool_result.error or "Tool execution failed."

    calc = tool_result.calculation
    currency = str(calc.result.get("currency", "USD"))
    monetary_keys = {
        "monthly_emi",
        "total_interest",
        "total_prepayment",
        "interest_saved_vs_no_prepayment",
        "future_value",
        "total_invested",
        "estimated_gain",
        "price",
        "gross_income",
        "deductions",
        "taxable_income",
        "estimated_tax",
    }
    result_lines = [f"Tool used: `{calc.tool_name}`", "", "Result:"]
    for key, value in calc.result.items():
        if key == "schedule_preview" or key == "yearly_snapshots":
            continue
        if key in monetary_keys and isinstance(value, int | float):
            result_lines.append(f"- `{key}`: {currency} {value:,.2f}")
        else:
            result_lines.append(f"- `{key}`: {value}")
    return "\n".join(result_lines)


def _run_tools(query: str, required_tools: list[str]) -> list[ToolResult]:
    results = []
    for tool_name in required_tools:
        if tool_name == "emi_calculator":
            results.append(_run_emi_from_query(query))
        elif tool_name == "portfolio_growth_simulator":
            results.append(_run_portfolio_from_query(query))
    return results


@st.cache_resource(show_spinner=False)
def _get_gemini_client(
    api_key: str,
    text_model: str,
    embedding_model: str,
    web_grounding_model: str,
    embedding_provider: str,
    cache_version: str,
) -> GeminiClient:
    settings = load_settings()
    return GeminiClient(settings)


@st.cache_resource(show_spinner=False)
def _get_retriever(
    api_key: str,
    text_model: str,
    embedding_model: str,
    web_grounding_model: str,
    embedding_provider: str,
    collection_name: str,
    qdrant_path: str,
    cache_version: str,
) -> HybridRetriever:
    settings = load_settings()
    gemini = GeminiClient(settings)
    return HybridRetriever(
        collection_name=collection_name,
        qdrant_path=qdrant_path,
        gemini=gemini,
    )


def _save_uploaded_files(uploaded_files: list) -> list[Path]:
    upload_dir = Path("data/uploads/originals")
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []

    for uploaded_file in uploaded_files:
        target = upload_dir / uploaded_file.name
        target.write_bytes(uploaded_file.getbuffer())
        saved_paths.append(target)
    return saved_paths


def _index_uploaded_files(
    uploaded_files: list, retriever: HybridRetriever
) -> tuple[int, int, list[Path]]:
    saved_paths = _save_uploaded_files(uploaded_files)
    return _index_paths(saved_paths, retriever)


def _index_paths(
    paths: list[Path], retriever: HybridRetriever
) -> tuple[int, int, list[Path]]:
    all_chunks = []
    for path in paths:
        all_chunks.extend(ingest_file(path, source_name=path.name))
    indexed_count = retriever.index_chunks(all_chunks)
    return len(all_chunks), indexed_count, paths


def _original_upload_paths() -> list[Path]:
    upload_dir = Path("data/uploads/originals")
    if not upload_dir.exists():
        return []
    return [
        path
        for path in sorted(upload_dir.iterdir())
        if path.is_file() and path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}
    ]


def _catalog_summary(retriever: HybridRetriever | None) -> list[dict[str, object]]:
    if retriever is None:
        return []
    summary: dict[str, dict[str, object]] = {}
    for chunk in retriever.chunks:
        row = summary.setdefault(
            chunk.source_name,
            {"source": chunk.source_name, "text": 0, "table": 0, "image": 0, "total": 0},
        )
        row[chunk.type.value] = int(row[chunk.type.value]) + 1
        row["total"] = int(row["total"]) + 1
    return sorted(summary.values(), key=lambda row: str(row["source"]))


def _retrieval_answer(
    gemini: GeminiClient,
    query: str,
    hits: list[RetrievalHit],
    calculations: list[ToolCalculation],
) -> StructuredLLMAnswer | None:
    if not hits and not calculations:
        return None
    return gemini.generate_grounded_answer(query, hits, calculations)


def _multimodal_answer(
    gemini: GeminiClient,
    query: str,
    image_paths: list[Path],
    hits: list[RetrievalHit],
    calculations: list[ToolCalculation],
) -> StructuredLLMAnswer | None:
    if not image_paths:
        return None
    return gemini.generate_multimodal_answer(query, image_paths, hits, calculations)


def _educational_answer(
    gemini: GeminiClient,
    query: str,
    hits: list[RetrievalHit],
    calculations: list[ToolCalculation],
) -> StructuredLLMAnswer:
    return gemini.generate_educational_answer(query, hits, calculations)


def _query_box_height(query: str) -> int:
    line_count = max(1, query.count("\n") + 1)
    estimated_wraps = max(0, len(query) // 95)
    return min(260, max(88, 62 + (line_count + estimated_wraps) * 24))


def _render_result_details(result: dict) -> None:
    return


def _render_chat_history() -> None:
    history = st.session_state.get("chat_history", [])
    pending = st.session_state.get("pending_request")
    if not history and not pending:
        st.info("Ask a question to start the verified finance chat.")
        return

    for item in history:
        with st.chat_message("user"):
            st.write(item["query"])
        with st.chat_message("assistant"):
            st.write(item["answer"])
            _render_result_details(item)

    if pending:
        with st.chat_message("user"):
            st.write(pending["query"])
        with st.chat_message("assistant"):
            st.write("Formulating answer...")


def _append_result_to_history(
    query: str,
    answer: str,
    confidence: float,
    calculations: list[ToolCalculation] | None = None,
    citations: list | None = None,
    retrieval_hits: list[RetrievalHit] | None = None,
    retrieval_diagnostics: dict[str, list[RetrievalHit]] | None = None,
    assumptions: list[str] | None = None,
    claims: list | None = None,
    router_decision: dict | None = None,
    selected_sources: list[str] | None = None,
    structured_llm_answer: dict | None = None,
) -> None:
    retrieval_hits = retrieval_hits or []
    retrieval_diagnostics = retrieval_diagnostics or {
        "dense": [],
        "sparse": [],
        "hybrid": [],
    }
    result_payload = {
        "query": query,
        "answer": answer,
        "confidence": confidence,
        "calculations": [
            calc.model_dump(mode="json") for calc in (calculations or [])
        ],
        "citations": [
            citation.model_dump(mode="json") for citation in (citations or [])
        ],
        "retrieval_hits": [hit.model_dump(mode="json") for hit in retrieval_hits],
        "retrieval_diagnostics": {
            key: [hit.model_dump(mode="json") for hit in hits]
            for key, hits in retrieval_diagnostics.items()
        },
        "assumptions": assumptions or [],
        "claims": [
            claim.model_dump(mode="json") if hasattr(claim, "model_dump") else claim
            for claim in (claims or [])
        ],
        "router_decision": router_decision,
        "selected_sources": selected_sources or [],
        "structured_llm_answer": structured_llm_answer,
    }
    st.session_state.setdefault("chat_history", []).append(result_payload)
    st.session_state["latest_result"] = result_payload


def _append_tool_result(query: str, route: Route, tool_result: ToolResult) -> None:
    if not tool_result.success or tool_result.calculation is None:
        _append_result_to_history(
            query=query,
            answer=tool_result.error or "Insufficient data to answer reliably.",
            confidence=0.0,
            assumptions=[],
            router_decision={
                "route": Route.ABSTAIN.value,
                "reason": "Deterministic tool form could not complete safely.",
            },
        )
        return

    decision = RouterDecision(
        route=route,
        required_tools=[tool_result.calculation.tool_name],
        reason="Submitted through deterministic tool form.",
    )
    draft_answer = _tool_answer(tool_result)
    verified = verify_response(
        draft_answer=draft_answer,
        decision=decision,
        tool_results=[tool_result],
    )
    _append_result_to_history(
        query=query,
        answer=verified.answer,
        confidence=verified.confidence,
        calculations=verified.calculations,
        assumptions=verified.assumptions,
        claims=verified.claims,
        router_decision=decision.model_dump(mode="json"),
    )


def _render_tool_forms() -> None:
    st.subheader("Deterministic Tool Forms")
    tabs = st.tabs(["EMI", "Portfolio", "Options", "Tax"])

    with tabs[0]:
        with st.form("emi_tool_form"):
            currency = st.selectbox(
                "Currency",
                ["USD", "INR", "EUR", "GBP", "JPY", "CAD", "AUD", "SGD", "AED"],
                key="emi_currency",
            )
            principal = st.number_input(
                "Principal",
                min_value=0.0,
                value=500000.0,
                step=1000.0,
                key="emi_principal",
            )
            annual_rate_pct = st.number_input(
                "Annual interest rate (%)",
                min_value=0.0,
                value=8.75,
                step=0.05,
                key="emi_rate",
            )
            tenure_years = st.number_input(
                "Tenure (years)",
                min_value=0.1,
                value=20.0,
                step=0.5,
                key="emi_tenure",
            )
            prepayment_month = st.number_input(
                "Optional prepayment month",
                min_value=0,
                value=0,
                step=1,
                key="emi_prepay_month",
            )
            prepayment_amount = st.number_input(
                "Optional prepayment amount",
                min_value=0.0,
                value=0.0,
                step=1000.0,
                key="emi_prepay_amount",
            )
            submitted = st.form_submit_button("Calculate EMI", type="primary")

        if submitted:
            prepayments = []
            if prepayment_month > 0 and prepayment_amount > 0:
                prepayments.append(
                    {"month": int(prepayment_month), "amount": prepayment_amount}
                )
            tool_result = calculate_emi(
                principal=principal,
                annual_rate_pct=annual_rate_pct,
                tenure_months=int(round(tenure_years * 12)),
                currency=currency,
                prepayments=prepayments,
            )
            query = (
                f"Calculate EMI for {currency} {principal:,.2f} loan at "
                f"{annual_rate_pct}% for {tenure_years} years"
            )
            _append_tool_result(query, Route.COMPUTE_ONLY, tool_result)
            st.rerun()

    with tabs[2]:
        with st.form("option_tool_form"):
            currency = st.selectbox(
                "Currency",
                ["USD", "INR", "EUR", "GBP", "JPY", "CAD", "AUD", "SGD", "AED"],
                key="option_currency",
            )
            option_type = st.selectbox("Option type", ["call", "put"], key="option_type")
            spot = st.number_input(
                "Spot price",
                min_value=0.01,
                value=100.0,
                step=1.0,
                key="option_spot",
            )
            strike = st.number_input(
                "Strike price",
                min_value=0.01,
                value=100.0,
                step=1.0,
                key="option_strike",
            )
            time_to_expiry_years = st.number_input(
                "Time to expiry (years)",
                min_value=0.001,
                value=0.5,
                step=0.05,
                key="option_expiry",
            )
            risk_free_rate_pct = st.number_input(
                "Risk-free rate (%)",
                value=5.0,
                step=0.1,
                key="option_rate",
            )
            volatility_pct = st.number_input(
                "Volatility (%)",
                min_value=0.01,
                value=22.0,
                step=0.5,
                key="option_vol",
            )
            submitted = st.form_submit_button("Price Option", type="primary")

        if submitted:
            tool_result = price_black_scholes_option(
                spot=spot,
                strike=strike,
                time_to_expiry_years=time_to_expiry_years,
                risk_free_rate_pct=risk_free_rate_pct,
                volatility_pct=volatility_pct,
                option_type=option_type,
                currency=currency,
            )
            query = (
                f"Price a {time_to_expiry_years}Y {option_type} option with spot "
                f"{currency} {spot:,.2f}, strike {strike:,.2f}, rate "
                f"{risk_free_rate_pct}%, vol {volatility_pct}%"
            )
            _append_tool_result(query, Route.COMPUTE_ONLY, tool_result)
            st.rerun()

    with tabs[3]:
        with st.form("tax_tool_form"):
            currency = st.selectbox(
                "Currency",
                ["USD", "INR", "EUR", "GBP", "JPY", "CAD", "AUD", "SGD", "AED"],
                key="tax_currency",
            )
            jurisdiction = st.text_input(
                "Jurisdiction code",
                value="US",
                help="Example: US, IN, UK. Requires a matching non-demo rule pack.",
                key="tax_jurisdiction",
            )
            tax_year = st.number_input(
                "Tax year",
                min_value=2000,
                max_value=2100,
                value=2026,
                step=1,
                key="tax_year",
            )
            filing_status = st.selectbox(
                "Filing status",
                ["single", "married_joint", "head_of_household"],
                key="tax_filing_status",
            )
            gross_income = st.number_input(
                "Gross income",
                min_value=0.0,
                value=100000.0,
                step=1000.0,
                key="tax_income",
            )
            deductions = st.number_input(
                "Deductions",
                min_value=0.0,
                value=0.0,
                step=1000.0,
                key="tax_deductions",
            )
            submitted = st.form_submit_button("Estimate Tax", type="primary")

        if submitted:
            tool_result = estimate_tax(
                jurisdiction=jurisdiction,
                tax_year=int(tax_year),
                gross_income=gross_income,
                deductions=deductions,
                filing_status=filing_status,
                currency=currency,
            )
            query = (
                f"Estimate {jurisdiction.upper()} {int(tax_year)} tax for "
                f"{currency} {gross_income:,.2f} gross income"
            )
            _append_tool_result(query, Route.COMPUTE_ONLY, tool_result)
            st.rerun()

    with tabs[1]:
        with st.form("portfolio_tool_form"):
            currency = st.selectbox(
                "Currency",
                ["USD", "INR", "EUR", "GBP", "JPY", "CAD", "AUD", "SGD", "AED"],
                key="portfolio_currency",
            )
            monthly_investment = st.number_input(
                "Monthly investment",
                min_value=0.0,
                value=1000.0,
                step=100.0,
                key="portfolio_monthly",
            )
            annual_return_pct = st.number_input(
                "Expected annual return (%)",
                value=8.0,
                step=0.25,
                key="portfolio_return",
            )
            years = st.number_input(
                "Years",
                min_value=0.1,
                value=10.0,
                step=0.5,
                key="portfolio_years",
            )
            initial_amount = st.number_input(
                "Initial amount",
                min_value=0.0,
                value=0.0,
                step=100.0,
                key="portfolio_initial",
            )
            annual_step_up_pct = st.number_input(
                "Annual contribution step-up (%)",
                min_value=0.0,
                value=0.0,
                step=0.5,
                key="portfolio_step_up",
            )
            submitted = st.form_submit_button("Simulate Portfolio", type="primary")

        if submitted:
            tool_result = simulate_portfolio_growth(
                monthly_investment=monthly_investment,
                annual_return_pct=annual_return_pct,
                years=years,
                initial_amount=initial_amount,
                annual_step_up_pct=annual_step_up_pct,
                currency=currency,
            )
            query = (
                f"Simulate investing {currency} {monthly_investment:,.2f}/month "
                f"at {annual_return_pct}% for {years} years"
            )
            _append_tool_result(query, Route.COMPUTE_ONLY, tool_result)
            st.rerun()


def main() -> None:
    settings = load_settings()
    gemini: GeminiClient | None = None
    retriever: HybridRetriever | None = None
    if settings.gemini_configured:
        gemini = _get_gemini_client(
            settings.gemini_api_key,
            settings.gemini_text_model,
            settings.gemini_embedding_model,
            settings.gemini_web_grounding_model,
            settings.embedding_provider,
            CACHE_VERSION,
        )
        retriever = _get_retriever(
            settings.gemini_api_key,
            settings.gemini_text_model,
            settings.gemini_embedding_model,
            settings.gemini_web_grounding_model,
            settings.embedding_provider,
            settings.qdrant_collection,
            settings.qdrant_path,
            CACHE_VERSION,
        )
        st.session_state["indexed_chunks"] = [
            chunk.model_dump(mode="json") for chunk in retriever.chunks
        ]

    st.set_page_config(page_title="FinSight AI", page_icon="FinSight", layout="wide")
    st.markdown(
        """
        <style>
        textarea {
            resize: none !important;
        }
        div[data-testid="stFileUploader"] section {
            padding: 0.55rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("FinSight AI")
    st.caption("Multimodal financial decision engine MVP")

    with st.sidebar:
        st.subheader("Runtime")
        st.write("Gemini key configured:", settings.gemini_configured)
        st.write("Text model:", settings.gemini_text_model)
        st.write("Embedding model:", settings.gemini_embedding_model)
        st.write("Embedding provider:", settings.embedding_provider)
        st.write("Web model:", settings.gemini_web_grounding_model)
        st.write("Indexed chunks:", len(st.session_state.get("indexed_chunks", [])))
        if st.button("Clear conversation", use_container_width=True):
            st.session_state["chat_history"] = []
            st.session_state.pop("latest_result", None)
            st.rerun()

    chat_container = st.container()
    with chat_container:
        _render_chat_history()

    st.divider()

    if "query_input_version" not in st.session_state:
        st.session_state["query_input_version"] = 0
    query_key = f"query_input_{st.session_state['query_input_version']}"

    with st.form("query_form"):
        query = st.text_input(
            "Ask a financial question",
            placeholder=(
                "Examples: Calculate EMI for $500k loan at 8.75% for 20 years; "
                "If I invest EUR 20k/month at 12% for 10 years, what will I get?"
            ),
            key=query_key,
        )

        upload_col, run_col = st.columns([5, 1])
        with upload_col:
            uploaded_files = st.file_uploader(
                "Upload PDFs, statements, charts, or screenshots",
                type=["pdf", "png", "jpg", "jpeg"],
                accept_multiple_files=True,
                label_visibility="collapsed",
            )
        with run_col:
            run_clicked = st.form_submit_button(
                "Run", type="primary", use_container_width=True
            )

    if run_clicked and query.strip():
        st.session_state["pending_request"] = {
            "query": query.strip(),
            "allow_web": True,
        }
        st.session_state["query_input_version"] += 1
        st.rerun()

    pending_request = st.session_state.get("pending_request")
    if pending_request:
        query = pending_request["query"]
        allow_web = pending_request["allow_web"]
        saved_image_paths: list[Path] = []
        selected_sources: list[str] = []
        source_filter = None

        if uploaded_files and retriever is not None:
            with st.spinner("Ingesting and indexing uploaded files..."):
                extracted_count, indexed_count, saved_paths = _index_uploaded_files(
                    uploaded_files, retriever
                )
                saved_image_paths = [
                    path
                    for path in saved_paths
                    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
                ]
                st.session_state["indexed_chunks"] = [
                    chunk.model_dump(mode="json") for chunk in retriever.chunks
                ]
            st.success(
                f"Extracted {extracted_count} chunks; indexed {indexed_count} new chunks."
            )

        indexed_chunk_count = len(st.session_state.get("indexed_chunks", []))
        has_documents = any(file.type == "application/pdf" for file in uploaded_files)
        has_images = any(file.type.startswith("image/") for file in uploaded_files)
        decision = route_query(
            query,
            has_documents=has_documents or indexed_chunk_count > 0,
            has_images=has_images,
            allow_web=allow_web,
        )

        tool_results: list[ToolResult] = []
        retrieval_hits: list[RetrievalHit] = []
        retrieval_diagnostics = {"dense": [], "sparse": [], "hybrid": []}
        web_citations = []
        draft_answer = ""
        structured_answer = None

        with st.spinner("Formulating answer..."):
            try:
                if decision.route in {
                    Route.COMPUTE_ONLY,
                    Route.RETRIEVE_THEN_COMPUTE_THEN_ANSWER,
                }:
                    tool_results = _run_tools(query, decision.required_tools)
                    successful_calculations = [
                        result.calculation
                        for result in tool_results
                        if result.success and result.calculation is not None
                    ]
                    if decision.required_retrieval and retriever is not None:
                        retrieval_diagnostics = retriever.search_with_diagnostics(
                            query,
                            dense_limit=24,
                            sparse_limit=24,
                            source_names=source_filter,
                        )
                        retrieval_hits = retriever.select_context_hits(
                            query, retrieval_diagnostics["hybrid"], limit=8
                        )
                    if decision.required_retrieval and gemini is not None:
                        structured_answer = _retrieval_answer(
                            gemini, query, retrieval_hits, successful_calculations
                        )
                        draft_answer = structured_answer.answer if structured_answer else ""
                    else:
                        draft_answer = "\n\n".join(_tool_answer(result) for result in tool_results)
                elif decision.route == Route.ABSTAIN:
                    draft_answer = decision.reason
                elif decision.route == Route.WEB_GROUNDED_ANSWER:
                    if gemini is not None:
                        structured_answer, web_citations = gemini.generate_web_grounded_answer(query)
                        draft_answer = structured_answer.answer
                    else:
                        draft_answer = "Gemini API key is required for web-grounded answers."
                elif decision.route == Route.EDUCATIONAL_ANSWER:
                    if retriever is not None:
                        retrieval_diagnostics = retriever.search_with_diagnostics(
                            query,
                            dense_limit=24,
                            sparse_limit=24,
                            source_names=source_filter,
                        )
                        retrieval_hits = retriever.select_context_hits(
                            query, retrieval_diagnostics["hybrid"], limit=8
                        )
                    if gemini is not None:
                        structured_answer = _educational_answer(
                            gemini, query, retrieval_hits, []
                        )
                        draft_answer = structured_answer.answer
                    else:
                        draft_answer = local_educational_answer(query)
                else:
                    if retriever is not None:
                        retrieval_diagnostics = retriever.search_with_diagnostics(
                            query,
                            dense_limit=24,
                            sparse_limit=24,
                            source_names=source_filter,
                        )
                        retrieval_hits = retriever.select_context_hits(
                            query,
                            retrieval_diagnostics["hybrid"],
                            limit=8,
                            include_images=decision.route == Route.MULTIMODAL_REASONING,
                        )
                    if gemini is not None:
                        if decision.route == Route.MULTIMODAL_REASONING:
                            if not saved_image_paths:
                                saved_image_paths = [
                                    Path(hit.chunk.metadata["image_path"])
                                    for hit in retrieval_hits
                                    if hit.chunk.metadata.get("image_path")
                                ]
                            structured_answer = _multimodal_answer(
                                gemini, query, saved_image_paths, retrieval_hits, []
                            )
                        else:
                            structured_answer = _retrieval_answer(gemini, query, retrieval_hits, [])
                        draft_answer = structured_answer.answer if structured_answer else ""
                    else:
                        draft_answer = "Gemini API key is required for grounded document answers."
            except Exception as exc:
                if _is_quota_error(exc):
                    draft_answer = local_educational_answer(query)
                    structured_answer = None
                    web_citations = []
                else:
                    raise

        verified = verify_response(
            draft_answer=draft_answer,
            decision=decision,
            retrieval_hits=retrieval_hits,
            tool_results=tool_results,
            structured_answer=structured_answer,
            web_citations=web_citations,
        )

        _append_result_to_history(
            query=query,
            answer=verified.answer,
            confidence=verified.confidence,
            calculations=verified.calculations,
            citations=verified.citations,
            retrieval_hits=retrieval_hits,
            retrieval_diagnostics=retrieval_diagnostics,
            assumptions=verified.assumptions,
            claims=verified.claims,
            router_decision=decision.model_dump(mode="json"),
            selected_sources=selected_sources,
            structured_llm_answer=structured_answer.model_dump(mode="json")
            if structured_answer
            else None,
        )
        st.session_state.pop("pending_request", None)
        st.rerun()


if __name__ == "__main__":
    main()
