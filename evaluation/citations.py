from __future__ import annotations

import json
from pathlib import Path

from router import route_query
from schemas import AnswerClaim, ChunkType, DocumentChunk, RetrievalHit, StructuredLLMAnswer
from verifier import verify_response


ABSTENTION = "Insufficient data to answer reliably."


def evaluate_citations(dataset_path: str | Path) -> dict:
    dataset = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    true_positive_citations = 0
    cited_total = 0
    expected_total = 0
    abstain_true_positive = 0
    predicted_abstain_total = 0
    expected_abstain_total = 0
    correct_decisions = 0
    case_results = []

    for case in dataset["cases"]:
        hits = [
            RetrievalHit(
                chunk=DocumentChunk(
                    id=chunk_id,
                    document_id="benchmark",
                    source_name="benchmark.pdf",
                    type=ChunkType.TEXT,
                    content=f"Evidence stored in {chunk_id}.",
                ),
                score=0.9,
                source="hybrid",
            )
            for chunk_id in case["available_ids"]
        ]
        claims = [
            AnswerClaim(text=claim["text"], citation_ids=claim["cited_ids"])
            for claim in case["claims"]
        ]
        used_ids = sorted({citation for claim in case["claims"] for citation in claim["cited_ids"]})
        structured = StructuredLLMAnswer(
            answer=" ".join(claim["text"] for claim in case["claims"]),
            used_citation_ids=used_ids,
            claims=claims,
            confidence=0.9,
            needs_more_data=case.get("needs_more_data", False),
        )
        verified = verify_response(
            draft_answer="",
            decision=route_query("Summarize this report", has_documents=True),
            retrieval_hits=hits,
            structured_answer=structured,
        )
        predicted_abstain = verified.answer == ABSTENTION
        expected_abstain = case["expected_abstain"]
        predicted_abstain_total += int(predicted_abstain)
        expected_abstain_total += int(expected_abstain)
        abstain_true_positive += int(predicted_abstain and expected_abstain)
        correct_decisions += int(predicted_abstain == expected_abstain)

        for claim in case["claims"]:
            cited = set(claim["cited_ids"])
            expected = set(claim["expected_ids"])
            true_positive_citations += len(cited & expected)
            cited_total += len(cited)
            expected_total += len(expected)

        case_results.append({
            "id": case["id"],
            "expected_abstain": expected_abstain,
            "predicted_abstain": predicted_abstain,
            "confidence": verified.confidence,
        })

    return {
        "dataset_version": dataset["version"],
        "cases": len(dataset["cases"]),
        "citation_precision": round(true_positive_citations / cited_total, 4),
        "citation_recall": round(true_positive_citations / expected_total, 4),
        "abstention_precision": round(abstain_true_positive / predicted_abstain_total, 4),
        "abstention_recall": round(abstain_true_positive / expected_abstain_total, 4),
        "decision_accuracy": round(correct_decisions / len(dataset["cases"]), 4),
        "results": case_results,
    }
