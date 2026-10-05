"""Adjacent failures found while checking the completion prompt."""
import json
import uuid
from pathlib import Path

import pytest

from calculation_inputs import InputIssue
from config import Settings
from evaluation.scoring import score_outcome
from ingestion import ingest_file
from openai_client import OpenAIClient
from orchestration import document_tool
from retrieval import HybridRetriever
from router import route_query
from schemas import DocumentChunk, RetrievalHit, ToolCalculation, VerifiedResponse
from verifier import verify_response


def hit(text, metadata=None):
    return RetrievalHit(chunk=DocumentChunk(id=str(uuid.uuid4()), document_id='loan',
        source_name='loan.pdf', type='text', content=text, page=1, metadata=metadata or {}), score=1, source='sparse')


@pytest.mark.parametrize('other', [
    'Loan principal: USD 900000',
    'Annual interest rate: 9%',
    'Duration: 30 years',
])
def test_complete_loan_cannot_hide_partial_conflict(other):
    hits = [hit('Loan principal: USD 500000\nAnnual interest rate: 8%\nDuration: 20 years'), hit(other)]
    with pytest.raises(InputIssue, match='Conflicting'):
        document_tool('Calculate EMI in the report', 'emi_calculator', hits)


def test_loan_join_cannot_cross_company_titles():
    hits = [hit('Company: Cedar\nLoan principal: USD 500000'),
            hit('Company: Harbor\nAnnual interest rate: 8%\nDuration: 20 years')]
    with pytest.raises(InputIssue, match='conflicting company'):
        document_tool('Calculate EMI in the report', 'emi_calculator', hits)


@pytest.mark.parametrize('mutation', ['span', 'input', 'normalized'])
def test_document_loan_provenance_resolves_at_final_boundary(mutation):
    from schemas import ToolResult
    hits = [hit('Loan principal: USD 500000\nAnnual interest rate: 8%\nDuration: 20 years')]
    result = document_tool('Calculate EMI in the report', 'emi_calculator', hits)
    decision = route_query('Calculate EMI in the report', has_documents=True)
    assert verify_response('', decision, hits, [result]).status == 'ok'
    c = result.calculation
    if mutation == 'span': c.provenance['principal']['start'] += 1
    elif mutation == 'input': c.inputs['principal'] = 900000
    else: c.provenance['principal']['normalized_value'] = 900000
    assert verify_response('', decision, hits, [ToolResult(success=True, calculation=c)]).status == 'abstained'


@pytest.mark.parametrize('mutation', ['small_ratio_error', 'fractional_period', 'metric'])
def test_scorer_rejects_small_result_and_binding_mutations(mutation):
    case = next(c for c in json.loads(Path('evals/repair_v3/application.json').read_text())['cases'] if c['operation'] == 'current_ratio')
    result = dict(case['expected_result'])
    if mutation == 'small_ratio_error': result['ratio'] += .009
    elif mutation == 'fractional_period': result['periods'] = [2025.001]
    else: result['metric'] = 'margin'
    c = ToolCalculation(tool_name='current_ratio', inputs=case['expected_inputs'], result=result, trace='mutation')
    display = '\n'.join(['Current ratio'] + [f"{k.replace('_',' ')}: {v}" for k,v in result.items() if not isinstance(v, (dict,list))])
    assert not score_outcome(case, VerifiedResponse(answer=display, calculations=[c]))


def test_deletion_recovery_after_delete_succeeds_but_ack_fails(tmp_path, monkeypatch):
    p = OpenAIClient(Settings())
    r = HybridRetriever('recovery', str(tmp_path/'qdrant'), p)
    chunks = ingest_file('evals/fixtures/Cedar.pdf')
    r.index_chunks(chunks)
    original = r._delete_ids
    def interrupted(ids):
        original(ids)
        raise RuntimeError('Injected interruption after durable deletion')
    monkeypatch.setattr(r, '_delete_ids', interrupted)
    with pytest.raises(RuntimeError): r.delete_document(chunks[0].document_id)
    journal = r.journal_path
    assert journal.exists()
    r.close()
    reopened = HybridRetriever('recovery', str(tmp_path/'qdrant'), p)
    try:
        assert not reopened.chunks and not journal.exists()
    finally:
        reopened.close()


@pytest.mark.parametrize('problem', ['partial_prepayment', 'fractional_duration'])
def test_emi_form_never_silently_drops_input(tmp_path, monkeypatch, problem):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('QDRANT_PATH', str(tmp_path/'qdrant'))
    monkeypatch.setenv('EMBEDDING_PROVIDER', 'local_hash')
    app = AppTest.from_file('app.py', default_timeout=20).run()
    if problem == 'partial_prepayment': app.number_input(key='emi_prepay_amount').set_value(5000.)
    else: app.number_input(key='emi_tenure').set_value(20.1)
    app.button(key='FormSubmitter:emi_tool_form-Calculate EMI').click().run()
    assert not app.exception
    response = app.session_state['history'][-1]['response']
    assert response['status'] == 'clarification' and not response['calculations']


def test_portfolio_form_exposes_supported_conventions_and_usd(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('QDRANT_PATH', str(tmp_path/'qdrant'))
    monkeypatch.setenv('EMBEDDING_PROVIDER', 'local_hash')
    app = AppTest.from_file('app.py', default_timeout=20).run()
    assert app.selectbox(key='emi_currency').value == app.selectbox(key='portfolio_currency').value == 'USD'
    assert not any(b.label == 'Estimate Tax' for b in app.button)
    app.selectbox(key='portfolio_timing').select('beginning')
    app.selectbox(key='portfolio_rate_convention').select('effective_annual')
    app.button(key='FormSubmitter:portfolio_tool_form-Simulate Portfolio').click().run()
    assert not app.exception
    c = app.session_state['history'][-1]['response']['calculations'][0]
    assert c['inputs']['contribution_timing'] == 'beginning'
    rate = 1.08 ** (1/12) - 1
    reference = 1000 * ((1+rate)**120 - 1) / rate * (1+rate)
    assert c['result']['future_value'] == pytest.approx(reference, abs=.005)


@pytest.mark.parametrize('usage', [
    {'input_tokens': -1, 'output_tokens': 5},
    {'output_tokens': 5},
    {'input_tokens': 10, 'output_tokens': -5},
])
def test_bad_usage_cannot_release_budget_reservation(tmp_path, usage):
    from evaluation.budget import EvaluationBudget
    b = EvaluationBudget(2, tmp_path/'budget.json')
    token = b.reserve('gpt-5.4-mini', 100, 1024)
    reserved = b.data['entries'][token]['accounted_usd']
    b.settle(token, usage)
    assert b.data['entries'][token]['accounted_usd'] == reserved


def test_unexpected_request_exception_is_visible_and_pending_clears(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('QDRANT_PATH', str(tmp_path/'qdrant'))
    monkeypatch.setenv('EMBEDDING_PROVIDER', 'local_hash')
    app = AppTest.from_file('app.py', default_timeout=20).run()
    def fail(*args, **kwargs):
        raise RuntimeError('private diagnostic must not be displayed')
    monkeypatch.setattr('orchestration.ResearchAssistant.ask', fail)
    app.text_area(key='query').set_value('What is EMI?')
    app.button(key='FormSubmitter:query_form-Ask').click().run()
    assert not app.exception
    assert app.session_state['pending_request'] is None
    response = app.session_state['history'][-1]['response']
    assert response['status'] == 'provider_failure'
    assert 'private diagnostic' not in response['answer']


@pytest.mark.parametrize('response_text', [
    'Cedar 2025 net income: USD 24.',
    'Cedar 2024 revenue: USD 100.',
    'Cedar 2025 revenue: USD 120.\nCedar 2025 net income: USD 24.',
])
def test_true_but_unrequested_provider_facts_are_rejected(tmp_path, response_text):
    from schemas import AnswerClaim, StructuredLLMAnswer
    from orchestration import ResearchAssistant
    p = OpenAIClient(Settings())
    r = HybridRetriever('binding', str(tmp_path/'qdrant'), p)
    chunk = hit('Company: Cedar\nPeriod: 2025\nCurrency: USD\nRevenue: 120\nNet income: 24\nRevenue 2024: USD 100').chunk
    r.index_chunks([chunk])
    class WrongAnswer:
        last_response = None
        def generate_grounded_answer(self, *args):
            claims = [AnswerClaim(text=t, citation_ids=[chunk.id]) for t in response_text.splitlines()]
            return StructuredLLMAnswer(answer=response_text, claims=claims, used_citation_ids=[chunk.id])
    try:
        response = ResearchAssistant(r, WrongAnswer()).ask('What is revenue for Cedar in the report for 2025?', ['loan.pdf'], use_provider=True)
        assert response.status == 'abstained'
        assert any('requested' in reason for reason in response.reasons)
    finally:
        r.close()
