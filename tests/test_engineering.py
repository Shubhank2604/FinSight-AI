from __future__ import annotations

import json
import math
import uuid
from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest

from calculation_inputs import InputIssue, currency_from_text, extract_calculation_inputs
from config import Settings
from financial_evidence import quantities, supported_numbers
from gemini_client import GeminiClient
from ingestion import ingest_file
from ingestion.chunker import chunk_text
from ingestion.extractor import render_pdf_pages
from orchestration import ResearchAssistant
from retrieval import HybridRetriever
from router import route_query
from schemas import AnswerClaim, ChunkType, DocumentChunk, RetrievalHit, Route, RouterDecision, StructuredLLMAnswer
from tools import calculate_emi, price_black_scholes_option, simulate_portfolio_growth
from uploads import save_upload
from verifier.verifi import verify_response


def settings(path, provider='local_hash', model='test'):
    return Settings('', 'test', model, 'test', provider, 'test', str(path))


def chunk(content, name='Acme.pdf', doc='doc', page=1):
    return DocumentChunk(id=str(uuid.uuid5(uuid.NAMESPACE_URL, content+name+doc)), document_id=doc, source_name=name, type=ChunkType.TEXT, content=content, page=page)


REPORT = 'Company: Acme\nPeriod: 2025\nCurrency: USD\nUnits: million\nRevenue | 120\nNet income | 24\nCurrent assets | 60\nCurrent liabilities | 30\nDebt | 40\nEquity | 80'
PRIOR = REPORT.replace('2025', '2024').replace('Revenue | 120', 'Revenue | 100')


@pytest.fixture
def retriever(tmp_path):
    client = GeminiClient(settings(tmp_path/'qdrant'))
    r = HybridRetriever('test', str(tmp_path/'qdrant'), client)
    yield r
    r.close()


@pytest.mark.parametrize('query', [
    'Calculate EMI for 20 years at 8% on a $500000 loan',
    'Calculate EMI on a $500000 loan for 20 years at 8%',
    'Calculate EMI at 8% on a USD 500000 loan over 240 months',
])
def test_reordered_emi_matches_reference(query):
    model, origins = extract_calculation_inputs(query, 'emi_calculator')
    assert (model.principal, model.annual_rate_pct, model.tenure_months) == (500000, 8, 240)
    assert set(origins) == {'principal', 'annual_rate_pct', 'tenure_months'}
    r = calculate_emi(model.principal, model.annual_rate_pct, model.tenure_months)
    monthly = .08/12
    reference = 500000*monthly/(1-(1+monthly)**-240)
    assert r.calculation.result['monthly_emi'] == pytest.approx(reference, abs=.005)


@pytest.mark.parametrize('query', [
    'Calculate EMI at 8% for 20 years',
    'Calculate EMI on a $500000 loan for 20 years at 8% or 9%',
    'Calculate EMI on a $500000 or $600000 loan for 20 years at 8%',
    'Calculate EMI for USD 500000 and CAD 500000 at 8% for 20 years',
    'Calculate EMI for $nan at 8% for 20 years',
    'Calculate EMI on a $500000 loan at 8% for 20 years including fees',
])
def test_invalid_query_inputs_clarify(query):
    with pytest.raises(InputIssue):
        extract_calculation_inputs(query, 'emi_calculator')


def test_portfolio_input_roles_and_conventions():
    m, origins = extract_calculation_inputs('At 8% return for 10 years, invest $1000 per month', 'portfolio_growth_simulator')
    assert m.monthly_investment == 1000
    r = simulate_portfolio_growth(**m.model_dump())
    rate = .08/12
    assert r.calculation.result['future_value'] == pytest.approx(1000*((1+rate)**120-1)/rate, abs=.005)
    beginning = simulate_portfolio_growth(1000, 8, 10, contribution_timing='beginning')
    assert beginning.calculation.result['future_value'] == pytest.approx(r.calculation.result['future_value']*(1+rate), abs=.02)
    zero = simulate_portfolio_growth(1000, 0, 2, initial_amount=500)
    assert zero.calculation.result['future_value'] == 24500


@pytest.mark.parametrize('text, expected', [('Canadian dollars $500', 'CAD'), ('C$500', 'CAD'), ('AUD $500', 'AUD'), ('Australian dollars $500', 'AUD')])
def test_currency_specificity(text, expected):
    assert currency_from_text(text) == expected


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf'), True])
def test_tools_reject_nonfinite(value):
    assert not calculate_emi(value, 8, 240).success
    assert not simulate_portfolio_growth(100, value, 10).success
    assert not price_black_scholes_option(100,100,1,5,value).success


def test_prepayment_iterator_and_loan_invariants():
    result = calculate_emi(1200, 0, 12, prepayments=iter([{'month':1,'amount':600}]))
    assert result.success
    assert result.calculation.result['total_prepayment'] == 600
    assert result.calculation.result['months_to_close'] == 6
    assert result.calculation.inputs['prepayments'] == [{'month':1,'amount':600}]
    assert not price_black_scholes_option(100,100,1,5,20, option_type='carrot').success


def test_black_scholes_reference_and_put_call_parity():
    call=price_black_scholes_option(100,100,1,5,20)
    put=price_black_scholes_option(100,100,1,5,20,option_type='put')
    assert call.calculation.result['price']==pytest.approx(10.450583572185565,abs=.00005)
    assert call.calculation.result['price']-put.calculation.result['price']==pytest.approx(100-100*math.exp(-.05),abs=.0001)


@pytest.mark.parametrize('query, expected', [
    ('What is revenue in the uploaded report?', Route.RETRIEVE_THEN_ANSWER),
    ('What is the current ratio in this report?', Route.RETRIEVE_THEN_ANSWER),
    ('Explain the mortgage prepayment clause in this report', Route.RETRIEVE_THEN_ANSWER),
    ('Summarize portfolio returns for 2025 in this report', Route.RETRIEVE_THEN_ANSWER),
    ('What is a current ratio?', Route.EDUCATIONAL_ANSWER),
    ('Calculate current ratio in the report', Route.RETRIEVE_THEN_COMPUTE_THEN_ANSWER),
])
def test_router_action_evidence(query, expected):
    assert route_query(query, has_documents=True, allow_web=True).route == expected


def verified(answer, claim_text, evidence, claim_ids=None, extra_ids=None, claims=True):
    c = chunk(evidence)
    ids = [c.id] if claim_ids is None else claim_ids
    s = StructuredLLMAnswer(answer=answer, claims=[AnswerClaim(text=claim_text, citation_ids=ids)] if claims else [], used_citation_ids=extra_ids or [c.id], confidence=1)
    return verify_response('', RouterDecision(route=Route.RETRIEVE_THEN_ANSWER, reason='test'), [RetrievalHit(chunk=c, score=1, source='hybrid')], structured_answer=s)


def test_answer_claim_disagreement_and_empty_coverage():
    assert verified('Revenue grew 999%.', 'Revenue grew 12%.', 'Revenue grew 12%.').status == 'abstained'
    assert verified('Revenue grew 12%.', '', 'Revenue grew 12%.', claims=False).status == 'abstained'
    accepted = verified('Unchecked narrative omitted.', 'Revenue grew 12%.', 'Revenue grew 12%.')
    assert accepted.status == 'ok' and 'Unchecked' not in accepted.answer


def test_all_citation_references_checked():
    assert verified('Revenue grew 12% [bad].', 'Revenue grew 12%.', 'Revenue grew 12%.').status == 'abstained'
    c = chunk('Revenue grew 12%.')
    assert verified('Revenue grew 12%.', 'Revenue grew 12%.', c.content, claim_ids=[c.id,'bad']).status == 'abstained'
    assert verified('Revenue grew 12%.', 'Revenue grew 12%.', c.content, extra_ids=[c.id,'bad']).status == 'abstained'
    assert verified('Revenue grew 12%.', 'Revenue grew 12% [bad].', c.content).status == 'abstained'


@pytest.mark.parametrize('claim, evidence, accepted', [
    ('Revenue was $12 billion.', 'Revenue was $12 million.', False),
    ('Revenue was CAD 12 million.', 'Revenue was USD 12 million.', False),
    ('Revenue grew 12%.', 'Debt grew 12%.', False),
    ('Revenue grew 12%.', 'Revenue declined 12%.', False),
    ('Revenue 2026 was $12 million.', 'Revenue 2025 was $12 million.', False),
    ('Revenue was $12.35 million.', 'Revenue was $12.345 million.', True),
    ('Revenue declined 1%.', 'Revenue declined 100 basis points.', True),
    ('Net income was USD -12 million.', 'Net income was USD (12) million.', True),
    ('Revenue grew 0.12 fraction.', 'Revenue grew 12%.', True),
    ('Revenue was 12 million USD.', 'Revenue was USD 12 million.', True),
    ('Other 2025 revenue: USD 120 million.', 'Company: Acme\nPeriod: 2025\nRevenue 2025: USD 120 million.', False),
])
def test_financial_evidence_units_and_context(claim,evidence,accepted):
    assert supported_numbers(claim, evidence) == accepted


def test_full_evidence_not_display_snippet():
    evidence = 'Context ' * 70 + '\nRevenue grew 12%.'
    r = verified('Revenue grew 12%.','Revenue grew 12%.',evidence)
    assert r.status == 'ok'
    assert '12%' not in r.citations[0].snippet


def test_mandatory_inputs_and_tool_identity():
    tool = calculate_emi(1200,0,12)
    d = RouterDecision(route=Route.COMPUTE_ONLY, required_tools=['portfolio_growth_simulator'], reason='test')
    assert verify_response('result',d,tool_results=[tool]).status == 'abstained'
    d.required_tools=['emi_calculator']
    d.missing_inputs=['principal']
    assert verify_response('result',d,tool_results=[tool]).status == 'clarification'


def test_document_core_workflows_and_provenance(retriever):
    retriever.index_chunks([chunk(REPORT),chunk(PRIOR)])
    service = ResearchAssistant(retriever)
    fact = service.ask('What is revenue for 2025 in the report?', ['Acme.pdf'])
    assert fact.status == 'ok' and '120000000' in fact.answer and fact.citations[0].page == 1
    for operation, expected in [('current ratio',2),('net margin',20),('debt-to-equity',.5),('year-over-year revenue growth',20)]:
        q=f'Calculate {operation} for 2025 in the report'
        response=service.ask(q,['Acme.pdf'])
        assert response.status == 'ok', response
        result=response.calculations[0]
        assert expected in result.result.values()
        assert all(p['chunk_id'] and p['unit']=='USD' for p in result.provenance.values())
    missing=service.ask('What is revenue for 2028 in the report?',['Acme.pdf'])
    assert missing.status == 'abstained'
    assert service.ask('What is revenue in the report?',[]).status == 'clarification'


def test_document_emi_no_query_numbers(retriever):
    retriever.index_chunks([chunk('Loan principal: USD 500000\nAnnual interest rate: 8%\nDuration: 20 years')])
    response=ResearchAssistant(retriever).ask('Calculate EMI using the loan in the report',['Acme.pdf'])
    assert response.status == 'ok', response
    calc=response.calculations[0]
    assert calc.inputs['principal']==500000
    assert calc.provenance['principal']['source']=='document'


def test_conflicting_evidence_abstains(retriever):
    retriever.index_chunks([chunk(REPORT),chunk(REPORT.replace('Revenue | 120','Revenue | 999'))])
    response=ResearchAssistant(retriever).ask('What is revenue in the report for 2025?',['Acme.pdf'])
    assert response.status=='abstained'


def test_index_restart_replace_delete_and_stale_catalog(tmp_path):
    path=tmp_path/'qdrant'
    provider=GeminiClient(settings(path))
    first=HybridRetriever('test',str(path),provider)
    old=chunk(REPORT,doc='old')
    first.index_chunks([old])
    assert first.index_chunks([old])==0
    first.close()
    first.catalog_path.write_text('invalid json')
    restarted=HybridRetriever('test',str(path),provider)
    assert len(restarted.chunks)==1
    new=chunk(REPORT.replace('120','121'),doc='new')
    restarted.index_chunks([new])
    assert [c.document_id for c in restarted.chunks]==['new']
    restarted.delete_document('new')
    restarted.close()
    empty=HybridRetriever('test',str(path),provider)
    assert empty.chunks==[]
    assert empty.index_chunks([old])==1
    empty.close()


def test_lock_and_embedding_identity(retriever,tmp_path):
    with pytest.raises(RuntimeError,match='in use'):
        HybridRetriever('test',str(retriever.qdrant_path),retriever.gemini)
    retriever.index_chunks([chunk(REPORT)])
    old_name=retriever.collection_name
    retriever.close()
    changed=HybridRetriever('other',str(retriever.qdrant_path),retriever.gemini,vector_size=384)
    assert changed.collection_name != old_name and changed.chunks==[]
    changed.close()


def test_interrupted_embedding_batches_roll_back(retriever,monkeypatch):
    retriever.index_chunks([chunk(REPORT,doc='old')])
    real=retriever.gemini.embed_texts
    count=0
    def broken(texts):
        nonlocal count
        count+=1
        if count==2:
            raise TimeoutError('provider timeout')
        return real(texts)
    monkeypatch.setattr(retriever.gemini,'embed_texts',broken)
    with pytest.raises(TimeoutError):
        retriever.index_chunks([chunk(REPORT,doc='new'),chunk(PRIOR,doc='new')],batch_size=1)
    assert len(retriever.chunks)==1 and retriever.chunks[0].document_id=='old'
    assert retriever.client.count(retriever.collection_name).count==1


def test_crash_journal_recovery_and_duplicate_ids(tmp_path):
    from qdrant_client import models
    path=tmp_path/'qdrant'
    provider=GeminiClient(settings(path))
    r=HybridRetriever('test',str(path),provider)
    c=chunk(REPORT)
    with pytest.raises(ValueError,match='Duplicate'):
        r.index_chunks([c,c])
    r.index_chunks([c])
    r._atomic_json(r.journal_path,{'phase':'indexing','new_ids':[c.id],'old_ids':[]})
    r.close()
    recovered=HybridRetriever('test',str(path),provider)
    assert recovered.chunks==[]
    assert recovered.index_chunks([c])==1
    recovered.client.delete(collection_name=recovered.collection_name,points_selector=models.PointIdsList(points=[c.id]))
    # Catalog has a chunk, Qdrant has no points; restart must not skip indexing it.
    recovered.close()
    repaired=HybridRetriever('test',str(path),provider)
    assert repaired.chunks==[] and repaired.index_chunks([c])==1
    repaired.close()


def test_source_filter_before_ranking_and_empty_scope(retriever):
    chunks=[chunk(f'Distractor {i} revenue statement',name=f'Other{i}.pdf',doc=f'other{i}') for i in range(45)]
    target=chunk(REPORT)
    retriever.index_chunks(chunks+[target])
    assert all(h.chunk.source_name=='Acme.pdf' for h in retriever.dense_search('revenue',limit=2,source_names=['Acme.pdf']))
    assert retriever.dense_search('revenue',source_names=[])==[]
    assert retriever.sparse_search('revenue',source_names=[])==[]


def test_pdf_extraction_and_vector_page_render(tmp_path):
    pdf=tmp_path/'report.pdf'
    with pymupdf.open() as doc:
        page=doc.new_page()
        page.insert_text((40,50),REPORT,fontsize=11)
        page.draw_rect(pymupdf.Rect(40,300,150,400))
        doc.save(pdf)
    chunks=ingest_file(pdf)
    assert any('Revenue' in c.content and c.page==1 for c in chunks)
    images=render_pdf_pages(pdf,[1],tmp_path/'images')
    assert images[0].id==render_pdf_pages(pdf,[1],tmp_path/'images')[0].id
    assert Path(images[0].metadata['image_path']).is_file()


def test_malformed_files_and_chunk_limits(tmp_path):
    bad=tmp_path/'bad.pdf'
    bad.write_bytes(b'not a pdf')
    with pytest.raises(Exception):
        ingest_file(bad)
    with pytest.raises(ValueError):
        chunk_text('hello',overlap_ratio=1)
    assert all(len(c.split())<=400 for c in chunk_text(' '.join(['word']*1300),min_tokens=200,max_tokens=400))
    one=save_upload('../../report.pdf',b'first',tmp_path/'uploads')
    two=save_upload('report.pdf',b'second',tmp_path/'uploads')
    assert one.parent==two.parent==(tmp_path/'uploads').resolve() and one!=two


def test_provider_failure_and_invalid_json(retriever):
    retriever.index_chunks([chunk(REPORT)])
    class Failure:
        def generate_grounded_answer(self,*args):
            raise RuntimeError('429 quota exhausted')
    service=ResearchAssistant(retriever,Failure())
    failed=service.ask('What is revenue in the report for 2025?',['Acme.pdf'],use_provider=True)
    assert failed.status=='provider_failure' and failed.citations==[]
    assert service.ask('Calculate current ratio in the report for 2025?',['Acme.pdf'],use_provider=True).status=='ok'
    for raw in ('', 'not json', '{}'):
        with pytest.raises(Exception):
            retriever.gemini._parse_structured_response(raw)
