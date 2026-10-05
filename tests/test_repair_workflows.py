"""Repair boundaries across input provenance, storage recovery and paid budgets."""

import uuid

import pytest

from config import Settings
from evaluation.budget import BudgetExceeded, EvaluationBudget
from ingestion import ingest_file
from openai_client import OpenAIClient
from orchestration import document_tool
from retrieval import HybridRetriever
from router import route_query
from schemas import ChunkType, DocumentChunk, RetrievalHit, Route


def hit(text, page=1):
    return RetrievalHit(
        chunk=DocumentChunk(
            id=str(uuid.uuid4()),
            document_id="loan",
            source_name="loan.pdf",
            page=page,
            type=ChunkType.TEXT,
            content=text,
        ),
        score=1,
        source="sparse",
    )


def test_joined_loan_spans_resolve_to_original_chunks():
    hits = [
        hit("Company: Cedar\nLoan principal: USD 500 thousand", 3),
        hit("Loan terms\nInterest rate: 1% per month\nDuration: 20 years", 4),
    ]
    result = document_tool("Calculate EMI in the report", "emi_calculator", hits)
    assert result.calculation.result["monthly_emi"] == 5505.43
    for origin in result.calculation.provenance.values():
        text = next(h.chunk.content for h in hits if h.chunk.id == origin["chunk_id"])
        assert text[origin["start"] : origin["end"]] == origin["text"]


def test_join_does_not_cross_documents():
    hits = [
        hit("Loan principal: USD 500 thousand"),
        hit("Interest rate: 8%\nDuration: 20 years"),
    ]
    hits[1].chunk.document_id = "other"
    from calculation_inputs import InputIssue

    with pytest.raises(InputIssue):
        document_tool("Calculate EMI in the report", "emi_calculator", hits)


def test_multiple_query_calculations_clarify():
    d = route_query("Calculate EMI and investment growth for my portfolio")
    assert d.route == Route.ABSTAIN and d.missing_inputs == ["one_operation"]


def test_budget_survives_restart_and_rejects_overspend(tmp_path):
    path = tmp_path / "budget.json"
    b = EvaluationBudget(0.01, path)
    token = b.reserve("gpt-5.4-mini-2026-03-17", 200, 1000)
    b.settle(token, {"input_tokens": 100, "output_tokens": 100})
    reloaded = EvaluationBudget(0.01, path)
    assert reloaded.data["entries"][0]["accounted_usd"] == pytest.approx(0.000525)
    with pytest.raises(BudgetExceeded):
        reloaded.reserve("gpt-5.4-mini", 100000)
    with pytest.raises(BudgetExceeded):
        reloaded.reserve("unpriced", 100)
    assert len(reloaded.data["entries"]) == 1


@pytest.mark.parametrize("values", [(-1, 0, 1), (1, -1, 1), (1, 0, 0), (True, 0, 1)])
def test_invalid_budget_limits_cannot_reduce_spend(tmp_path, values):
    with pytest.raises(ValueError):
        EvaluationBudget(2, tmp_path / "b.json").reserve("gpt-5.4-mini", *values)


def test_duplicate_alias_and_failed_rebuild_preserve_index(tmp_path, monkeypatch):
    provider = OpenAIClient(Settings(embedding_provider="local_hash"))
    r = HybridRetriever("repair", str(tmp_path / "qdrant"), provider)
    try:
        chunks = ingest_file("evals/fixtures/Cedar.pdf")
        r.index_chunks(chunks)
        with pytest.raises(ValueError, match="already indexed"):
            r.index_chunks(
                [c.model_copy(update={"source_name": "alias.pdf"}) for c in chunks]
            )
        monkeypatch.setattr(provider, "embed_texts", lambda texts: [])
        with pytest.raises(ValueError, match="count"):
            r.rebuild()
        r.load_catalog()
        assert {c.id for c in r.chunks} == {c.id for c in chunks}
        r._atomic_json(
            r.journal_path,
            {"phase": "invalid", "old_ids": [chunks[0].id], "new_ids": []},
        )
        with pytest.raises(ValueError, match="journal"):
            r._recover_transaction()
        assert r.journal_path.exists()
        assert r.client.count(r.collection_name).count == len(chunks)
    finally:
        r.close()


def test_real_excerpt_acquisition_is_displayable():
    chunks = ingest_file("evals/repair_v3/Mint-2024-CFO.pdf")
    assert chunks[0].metadata["original_page"] == 38


@pytest.mark.parametrize('mutation',['denominator','tool','extra_result','extra_prose'])
def test_calculation_scorer_rejects_mutations(mutation):
    import json
    from pathlib import Path
    from evaluation.scoring import score_outcome
    from schemas import ToolCalculation, VerifiedResponse
    case=next(c for c in json.loads(Path('evals/repair_v3/application.json').read_text())['cases'] if c['operation']=='current_ratio')
    c=ToolCalculation(tool_name='current_ratio',inputs=dict(case['expected_inputs']),result=dict(case['expected_result']),trace='independent label fixture')
    def display():return '\n'.join([c.tool_name.replace('_',' ').capitalize()]+[f"{k.replace('_',' ')}: {v}" for k,v in c.result.items() if not isinstance(v,(dict,list))])
    r=VerifiedResponse(answer=display(),calculations=[c])
    assert score_outcome(case,r)
    if mutation=='denominator':c.inputs['current_liabilities']*=2
    elif mutation=='tool':c.tool_name='debt_to_equity'
    elif mutation=='extra_result':c.result['unsupported_value']=999
    r.answer=display()+(' Cedar is insolvent.' if mutation=='extra_prose' else '')
    assert not score_outcome(case,r)
