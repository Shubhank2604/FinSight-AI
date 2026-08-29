from __future__ import annotations

from app import _extract_currency
from config import _normalise_model_name
from fallback_answers import local_educational_answer
from ingestion.chunker import chunk_text, table_to_text
from retrieval import HybridRetriever
from router import route_query
from schemas import AnswerClaim, ChunkType, DocumentChunk, RetrievalHit, Route, StructuredLLMAnswer
from tools import calculate_emi, estimate_tax, price_black_scholes_option, simulate_portfolio_growth
from verifier import build_citations, verify_response


def test_model_alias_is_normalised() -> None:
    assert _normalise_model_name("gemini-3-flash") == "gemini-3-flash-preview"


def test_currency_defaults_to_usd() -> None:
    assert _extract_currency("Calculate EMI for 50 lakh loan") == "USD"


def test_currency_detects_explicit_query_currency() -> None:
    assert _extract_currency("Calculate EMI for INR 50 lakh loan") == "INR"
    assert _extract_currency("Invest EUR 20k per month") == "EUR"
    assert _extract_currency("Loan of $500k") == "USD"


def test_local_retirement_fallback_is_useful() -> None:
    answer = local_educational_answer(
        "Tell me how should I calculate the total amount of money I need to retire at 40 years of age?"
    )

    assert "Corpus" in answer
    assert "inflation" in answer
    assert "required inputs" not in answer.lower() or "current age" in answer


def test_emi_tool_returns_positive_payment() -> None:
    result = calculate_emi(
        principal=5_000_000,
        annual_rate_pct=8.75,
        tenure_months=240,
    )

    assert result.success
    assert result.calculation is not None
    assert result.calculation.result["monthly_emi"] > 0
    assert result.calculation.result["total_interest"] > 0


def test_portfolio_tool_returns_future_value() -> None:
    result = simulate_portfolio_growth(
        monthly_investment=20_000,
        annual_return_pct=12,
        years=10,
    )

    assert result.success
    assert result.calculation is not None
    assert result.calculation.result["future_value"] > result.calculation.result["total_invested"]


def test_option_tool_returns_price_and_greeks() -> None:
    result = price_black_scholes_option(
        spot=100,
        strike=100,
        time_to_expiry_years=0.5,
        risk_free_rate_pct=5,
        volatility_pct=22,
        option_type="call",
    )

    assert result.success
    assert result.calculation is not None
    assert result.calculation.result["price"] > 0
    assert "delta" in result.calculation.result


def test_tax_tool_abstains_without_rule_pack() -> None:
    result = estimate_tax(
        jurisdiction="US",
        tax_year=2026,
        gross_income=100000,
        rule_pack_dir="missing_rule_packs",
    )

    assert not result.success
    assert result.error is not None
    assert "No versioned rule pack" in result.error


def test_router_detects_compute_only_emi() -> None:
    decision = route_query("Calculate EMI for 50 lakh loan at 8.75% for 20 years")

    assert decision.route == Route.COMPUTE_ONLY
    assert decision.required_tools == ["emi_calculator"]


def test_router_abstains_when_document_context_missing() -> None:
    decision = route_query("Summarize this financial report", has_documents=False)

    assert decision.route == Route.ABSTAIN
    assert "document_context" in decision.missing_inputs


def test_router_uses_web_grounding_when_enabled_for_current_query() -> None:
    decision = route_query("What is the latest Fed interest rate?", allow_web=True)

    assert decision.route == Route.WEB_GROUNDED_ANSWER


def test_router_abstains_for_current_query_when_web_disabled() -> None:
    decision = route_query("What is the latest Fed interest rate?", allow_web=False)

    assert decision.route == Route.ABSTAIN


def test_router_auto_web_when_enabled_by_app() -> None:
    decision = route_query("What is the current USD to INR exchange rate?", allow_web=True)

    assert decision.route == Route.WEB_GROUNDED_ANSWER


def test_router_routes_broad_educational_queries_to_documents() -> None:
    sec_decision = route_query("Tell me about SEC filings", has_documents=True)
    retirement_decision = route_query(
        "Tell me how should I calculate the total amount of money I need to retire at 40 years of age?",
        has_documents=True,
    )

    assert sec_decision.route == Route.EDUCATIONAL_ANSWER
    assert retirement_decision.route == Route.EDUCATIONAL_ANSWER


def test_verifier_allows_tool_backed_compute_answer() -> None:
    decision = route_query("Calculate EMI for 50 lakh loan at 8.75% for 20 years")
    tool_result = calculate_emi(5_000_000, 8.75, 240)

    verified = verify_response(
        draft_answer="Tool-backed EMI result.",
        decision=decision,
        tool_results=[tool_result],
    )

    assert verified.answer == "Tool-backed EMI result."
    assert verified.confidence >= 0.7
    assert verified.calculations


def test_chunk_text_preserves_all_words() -> None:
    text = " ".join(f"word{i}" for i in range(1300))
    chunks = chunk_text(text, max_tokens=400, overlap_ratio=0.1)

    assert len(chunks) >= 3
    assert "word0" in chunks[0]
    assert "word1299" in chunks[-1]


def test_table_to_text_serializes_rows() -> None:
    table = [["Year", "Revenue"], ["2025", "100"], ["2026", "125"]]

    assert table_to_text(table) == "Year | Revenue\n2025 | 100\n2026 | 125"


def test_citation_builder_uses_chunk_metadata() -> None:
    chunk = DocumentChunk(
        id="chunk-1",
        document_id="doc-1",
        source_name="report.pdf",
        type=ChunkType.TEXT,
        content="Revenue increased because subscriptions grew.",
        page=4,
        section="Management Discussion",
    )
    citations = build_citations([RetrievalHit(chunk=chunk, score=0.9, source="hybrid")])

    assert citations[0].source_name == "report.pdf"
    assert citations[0].page == 4
    assert citations[0].section == "Management Discussion"


def test_verifier_accepts_structured_cited_answer() -> None:
    decision = route_query("Summarize this financial report", has_documents=True)
    chunk = DocumentChunk(
        id="chunk-1",
        document_id="doc-1",
        source_name="report.pdf",
        type=ChunkType.TEXT,
        content="Liquidity risk increased because short-term obligations rose.",
        page=8,
        section="Risk Factors",
    )
    structured = StructuredLLMAnswer(
        answer="Liquidity risk increased because short-term obligations rose [chunk-1].",
        used_citation_ids=["chunk-1"],
        claims=[
            AnswerClaim(
                text="Liquidity risk increased.",
                citation_ids=["chunk-1"],
            )
        ],
        confidence=0.9,
    )

    verified = verify_response(
        draft_answer="",
        decision=decision,
        retrieval_hits=[RetrievalHit(chunk=chunk, score=0.9, source="hybrid")],
        structured_answer=structured,
    )

    assert verified.answer == structured.answer
    assert verified.confidence >= 0.6
    assert verified.claims


def test_verifier_blocks_retrieved_answer_without_claim_citation_ids() -> None:
    decision = route_query("Summarize this report", has_documents=True)
    chunk = DocumentChunk(
        id="chunk-1",
        document_id="doc-1",
        source_name="Apple SEC Filing.pdf",
        type=ChunkType.TEXT,
        content="SEC filings provide company disclosures and risk information.",
        page=1,
    )
    structured = StructuredLLMAnswer(
        answer="SEC filings are company disclosure documents used by investors.",
        used_citation_ids=[],
        claims=[AnswerClaim(text="SEC filings are disclosure documents.")],
        confidence=0.7,
    )

    verified = verify_response(
        draft_answer="",
        decision=decision,
        retrieval_hits=[RetrievalHit(chunk=chunk, score=0.85, source="hybrid")],
        structured_answer=structured,
    )

    assert verified.answer == "Insufficient data to answer reliably."
    assert verified.confidence < 0.45


def test_verifier_blocks_structured_answer_with_unknown_citation() -> None:
    decision = route_query("Summarize this financial report", has_documents=True)
    chunk = DocumentChunk(
        id="chunk-1",
        document_id="doc-1",
        source_name="report.pdf",
        type=ChunkType.TEXT,
        content="Revenue grew.",
        page=2,
    )
    structured = StructuredLLMAnswer(
        answer="Revenue grew [missing-chunk].",
        used_citation_ids=["missing-chunk"],
        claims=[AnswerClaim(text="Revenue grew.", citation_ids=["missing-chunk"])],
        confidence=0.9,
    )

    verified = verify_response(
        draft_answer="",
        decision=decision,
        retrieval_hits=[RetrievalHit(chunk=chunk, score=0.9, source="hybrid")],
        structured_answer=structured,
    )

    assert verified.answer == "Insufficient data to answer reliably."


def test_verifier_blocks_numeric_claim_not_present_in_cited_evidence() -> None:
    decision = route_query("Summarize this financial report", has_documents=True)
    chunk = DocumentChunk(
        id="debt-1",
        document_id="doc-1",
        source_name="report.pdf",
        type=ChunkType.TEXT,
        content="Debt declined 8% year over year.",
        page=2,
    )
    structured = StructuredLLMAnswer(
        answer="Revenue grew 12% [debt-1].",
        used_citation_ids=["debt-1"],
        claims=[AnswerClaim(text="Revenue grew 12%.", citation_ids=["debt-1"])],
        confidence=0.9,
    )

    verified = verify_response(
        draft_answer="",
        decision=decision,
        retrieval_hits=[RetrievalHit(chunk=chunk, score=0.9, source="hybrid")],
        structured_answer=structured,
    )

    assert verified.answer == "Insufficient data to answer reliably."
    assert verified.confidence < 0.45


class FakeGemini:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * 767 for _ in texts]

    def embed_query(self, query: str) -> list[float]:
        return [1.0] + [0.0] * 767


def test_retriever_source_filter_and_diagnostics(tmp_path) -> None:
    retriever = HybridRetriever(
        collection_name="test_chunks",
        qdrant_path=str(tmp_path / "qdrant"),
        gemini=FakeGemini(),
    )
    chunks = [
        DocumentChunk(
            id="00000000-0000-0000-0000-00000000000a",
            document_id="doc-a",
            source_name="Apple.pdf",
            type=ChunkType.TEXT,
            content="apple filing risk revenue",
        ),
        DocumentChunk(
            id="00000000-0000-0000-0000-00000000000b",
            document_id="doc-b",
            source_name="NVIDIA.pdf",
            type=ChunkType.TEXT,
            content="nvidia investor presentation revenue",
        ),
    ]
    retriever.index_chunks(chunks)

    diagnostics = retriever.search_with_diagnostics(
        "revenue", source_names=["NVIDIA.pdf"]
    )

    assert set(diagnostics) == {"dense", "sparse", "hybrid"}
    assert diagnostics["hybrid"]
    assert all(hit.chunk.source_name == "NVIDIA.pdf" for hit in diagnostics["hybrid"])
    assert retriever.source_names() == ["Apple.pdf", "NVIDIA.pdf"]
    retriever.client.close()


def test_context_selector_prefers_text_over_images(tmp_path) -> None:
    retriever = HybridRetriever(
        collection_name="test_context_chunks",
        qdrant_path=str(tmp_path / "qdrant_context"),
        gemini=FakeGemini(),
    )
    image_chunk = DocumentChunk(
        id="00000000-0000-0000-0000-000000000010",
        document_id="doc",
        source_name="Report.pdf",
        type=ChunkType.IMAGE,
        content="Extracted image from report.",
    )
    text_chunk = DocumentChunk(
        id="00000000-0000-0000-0000-000000000011",
        document_id="doc",
        source_name="Report.pdf",
        type=ChunkType.TEXT,
        content="retirement corpus annual spending inflation real return withdrawals",
    )
    hits = [
        RetrievalHit(chunk=image_chunk, score=1.0, source="hybrid"),
        RetrievalHit(chunk=text_chunk, score=0.8, source="hybrid"),
    ]

    selected = retriever.select_context_hits("retirement corpus", hits, limit=2)

    assert selected[0].chunk.type == ChunkType.TEXT
    assert all(hit.chunk.type != ChunkType.IMAGE for hit in selected)
    retriever.client.close()
