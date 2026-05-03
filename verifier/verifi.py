from __future__ import annotations

from schemas import (
    Citation,
    RetrievalHit,
    Route,
    RouterDecision,
    StructuredLLMAnswer,
    ToolResult,
    VerifiedResponse,
)


def build_citations(hits: list[RetrievalHit], limit: int = 5) -> list[Citation]:
    citations = []
    for hit in hits[:limit]:
        chunk = hit.chunk
        citations.append(
            Citation(
                chunk_id=chunk.id,
                source_name=chunk.source_name,
                page=chunk.page,
                section=chunk.section,
                snippet=chunk.content[:350].strip(),
            )
        )
    return citations


def _retrieval_confidence(hits: list[RetrievalHit]) -> float:
    if not hits:
        return 0.0
    top_scores = [max(min(hit.score, 1.0), 0.0) for hit in hits[:5]]
    return sum(top_scores) / len(top_scores)


def _tool_confidence(tool_results: list[ToolResult]) -> float:
    if not tool_results:
        return 1.0
    successes = [result for result in tool_results if result.success and result.calculation]
    if not successes:
        return 0.0
    return sum(result.calculation.confidence for result in successes if result.calculation) / len(
        tool_results
    )


def verify_response(
    draft_answer: str,
    decision: RouterDecision,
    retrieval_hits: list[RetrievalHit] | None = None,
    tool_results: list[ToolResult] | None = None,
    structured_answer: StructuredLLMAnswer | None = None,
    web_citations: list[Citation] | None = None,
    threshold: float = 0.45,
) -> VerifiedResponse:
    retrieval_hits = retrieval_hits or []
    tool_results = tool_results or []
    citations = build_citations(retrieval_hits)
    citations.extend(web_citations or [])
    calculations = [
        result.calculation
        for result in tool_results
        if result.success and result.calculation is not None
    ]
    assumptions = []
    for calculation in calculations:
        assumptions.extend(calculation.assumptions)
    if structured_answer:
        assumptions.extend(structured_answer.assumptions)

    needs_citations = decision.route in {
        Route.RETRIEVE_THEN_ANSWER,
        Route.RETRIEVE_THEN_COMPUTE_THEN_ANSWER,
        Route.MULTIMODAL_REASONING,
        Route.WEB_GROUNDED_ANSWER,
    }
    needs_tools = decision.route in {
        Route.COMPUTE_ONLY,
        Route.RETRIEVE_THEN_COMPUTE_THEN_ANSWER,
    }

    retrieval_score = _retrieval_confidence(retrieval_hits)
    tool_score = _tool_confidence(tool_results)
    citation_score = 1.0 if not needs_citations or citations else 0.0
    completeness_score = 0.0 if decision.missing_inputs else 1.0
    tool_presence_score = 1.0 if not needs_tools or calculations else 0.0
    llm_score = structured_answer.confidence if structured_answer else 1.0

    available_citation_ids = {hit.chunk.id for hit in retrieval_hits}
    available_citation_ids.update(
        citation.chunk_id for citation in citations if citation.chunk_id
    )
    used_citation_ids = set(structured_answer.used_citation_ids) if structured_answer else set()
    unsupported_citation_ids = used_citation_ids - available_citation_ids
    cited_claims = structured_answer.claims if structured_answer else []
    unsupported_claims = [
        claim
        for claim in cited_claims
        if needs_citations and not set(claim.citation_ids).intersection(available_citation_ids)
    ]

    if structured_answer and needs_citations:
        if used_citation_ids and not unsupported_citation_ids:
            citation_score = 1.0
        elif retrieval_hits:
            # Keep broad document-grounded explanations usable even when the model
            # fails to echo exact chunk IDs. The top retrieved chunks are still
            # attached as citations internally.
            citation_score = 0.7
        else:
            citation_score = 0.0
    if structured_answer and structured_answer.needs_more_data:
        completeness_score = 0.0

    confidence = (
        0.25 * retrieval_score
        + 0.25 * tool_score
        + 0.20 * citation_score
        + 0.15 * completeness_score
        + 0.10 * tool_presence_score
        + 0.05 * llm_score
    )

    if needs_citations and not citations:
        confidence = min(confidence, 0.35)
    if needs_tools and not calculations:
        confidence = min(confidence, 0.35)
    unsupported_claims_with_ids = [claim for claim in unsupported_claims if claim.citation_ids]
    if unsupported_citation_ids or unsupported_claims_with_ids:
        confidence = min(confidence, 0.35)
    if structured_answer and structured_answer.needs_more_data:
        confidence = min(confidence, 0.35)
    if decision.route == Route.ABSTAIN:
        confidence = 0.0

    confidence = round(max(min(confidence, 1.0), 0.0), 3)

    if confidence < threshold:
        answer = "Insufficient data to answer reliably."
    elif structured_answer:
        answer = structured_answer.answer.strip()
    else:
        answer = draft_answer.strip()

    return VerifiedResponse(
        answer=answer,
        citations=citations,
        calculations=calculations,
        assumptions=sorted(set(assumptions)),
        confidence=confidence,
        claims=cited_claims,
    )
