"""Regressions for the complete-repair brief, including independent scorer mutations."""
import json
from pathlib import Path
from decimal import Decimal
import pytest
from calculation_inputs import extract_calculation_inputs, InputIssue
from financial_evidence import extract_facts, supported_numbers
from schemas import *
from tools import calculate_emi
from router import route_query
from tools.research import calculate_document_operation
from verifier import verify_response
from evaluation.scoring import score_outcome

def hit(text,id='record'):
    return RetrievalHit(chunk=DocumentChunk(id=id,document_id='d',source_name='Cedar.pdf',type='text',content=text,page=1),score=1,source='hybrid')

@pytest.mark.parametrize('amount',['500k','500 thousand','500 thousands','500000'])
def test_thousand_equivalence_and_exact_spans(amount):
    query=f'Calculate EMI on a loan of {amount} dollars at 8% for 20 years'
    model,origins=extract_calculation_inputs(query,'emi_calculator')
    assert model.principal==500000
    p=origins['principal'];assert query[p['start']:p['end']]==p['text']
    assert p['normalized_value']==500000 and p['unit']=='USD'
    assert calculate_emi(model.principal,model.annual_rate_pct,model.tenure_months).calculation.result['monthly_emi']==4182.2

def test_monthly_rate_converts_explicitly():
    q='Calculate EMI on a $500000 loan at 1% per month for 20 years'
    m,p=extract_calculation_inputs(q,'emi_calculator')
    assert m.annual_rate_pct==12
    assert p['annual_rate_pct']['raw_value']==1 and p['annual_rate_pct']['rate_period']=='month'
    assert p['annual_rate_pct']['text']=='1% per month'
    assert calculate_emi(m.principal,m.annual_rate_pct,m.tenure_months).calculation.result['monthly_emi']==5505.43

@pytest.mark.parametrize('rate',['1% per day','1% per week','1% per quarter','effective monthly rate: 1% per month','annual rate: 1% per month'])
def test_unsupported_rate_periods_never_relabel(rate):
    with pytest.raises(InputIssue):extract_calculation_inputs(f'Calculate EMI on $500000 loan at {rate} for 20 years','emi_calculator')

@pytest.mark.parametrize('amount',['500 trillion','500 hundred','500 mn'])
def test_unconsumed_modifiers_rejected(amount):
    with pytest.raises(InputIssue):extract_calculation_inputs(f'Calculate EMI on loan of {amount} dollars at 8% for 20 years','emi_calculator')

@pytest.mark.parametrize('cell,scale,expected',[('$120','million',120000000),('USD 120','billion',120000000000),('120','thousand',120000),('$2025',None,2025),('$2024.50',None,2024.5),('$2025','million',2025000000),('$120 thousand','million',120000),('USD (12)','million',-12000000)])
def test_currency_scale_yearlike_money(cell,scale,expected):
    text=f'Company: Cedar\nPeriod: 2025\nCurrency: USD\n'+(f'Units: {scale}\n' if scale else '')+f'Revenue: {cell}'
    facts=extract_facts([hit(text)])
    assert len(facts)==1 and facts[0].value==Decimal(str(expected)) and facts[0].period==2025
    assert facts[0].provenance()['headers']['currency']=='USD'

@pytest.mark.parametrize('join',[' and ','; ',';\n','. '])
def test_period_amount_bindings_not_membership(join):
    evidence='Company: Cedar\nCurrency: USD\nRevenue in 2024 was USD 100 million'+join+'revenue in 2025 was USD 120 million.'
    assert not supported_numbers('Cedar 2025 revenue: USD 100 million.',evidence)
    assert supported_numbers('Cedar 2025 revenue: USD 120 million.',evidence)

def test_table_columns_and_companies_bound():
    table='Company: Cedar\nCurrency: USD\nUnits: million\nMetric | 2025 | 2024\nRevenue | $120 | $100'
    assert not supported_numbers('Cedar 2025 revenue: USD 100 million.',table)
    assert supported_numbers('Cedar 2025 revenue: USD 120 million.',table)
    text='Cedar 2025 revenue: USD 120 million; Harbor 2025 revenue: USD 100 million.'
    assert not supported_numbers('Harbor 2025 revenue: USD 120 million.',text)

def test_nonnumeric_assertion_rejected_but_excerpt_usable():
    h=hit('Company: Cedar\nPeriod: 2025\nRevenue: USD 120 million.\nSupply risk: shortages can delay orders.')
    d=route_query('Explain risks in the report',has_documents=True)
    def verify(text):return verify_response('',d,[h],structured_answer=StructuredLLMAnswer(answer=text,claims=[AnswerClaim(text=text,citation_ids=[h.chunk.id])]))
    assert verify('Cedar is insolvent.').status=='abstained'
    assert verify('Source excerpt: Supply risk: shortages can delay orders.').status=='ok'
    assert verify('Cedar 2025 revenue: USD 120 million; Cedar is insolvent.').status=='abstained'

@pytest.mark.parametrize('metric,expected',[('net income',0),('current assets',50),('revenue',20)])
def test_growth_metric_and_final_operation_agreement(metric,expected):
    hits=[hit('Company: Cedar\nPeriod: 2024\nCurrency: USD\nRevenue: 100\nNet income: 24\nCurrent assets: 40','prior'),hit('Company: Cedar\nPeriod: 2025\nCurrency: USD\nRevenue: 120\nNet income: 24\nCurrent assets: 60','current')]
    q=f'Compute year-over-year {metric} growth for Cedar in the report for 2025'
    decision=route_query(q,has_documents=True)
    result=calculate_document_operation(q,'yoy_growth',hits)
    assert result.calculation.result['growth_pct']==expected
    assert verify_response('',decision,hits,[result]).status=='ok'
    result.calculation.operation.metric='debt'
    assert verify_response('',decision,hits,[result]).status=='abstained'

def test_multiple_operations_require_clarification():
    d=route_query('Calculate current ratio and net margin in the report',has_documents=True)
    assert d.route==Route.ABSTAIN and d.missing_inputs

@pytest.mark.parametrize('bad',[
    'Cedar 2024 revenue: USD 120000000.', 'Harbor 2025 revenue: USD 120000000.',
    'Cedar 2025 net income: USD 120000000.', 'Cedar 2025 revenue: CAD 120000000.',
    'Cedar 2025 revenue: USD -120000000.', 'Cedar 2025 revenue: USD 120.',
    'Cedar 2025 revenue: USD 120000000; also USD 999000000.',
    'Cedar 2025 revenue: USD 120000000; Cedar is insolvent.',
])
def test_scorer_mutations_reject(bad):
    case=json.loads(Path('evals/application_benchmark.json').read_text())['cases'][0]
    assert not score_outcome(case,VerifiedResponse(answer=bad,claims=[AnswerClaim(text=bad)]))

def test_scorer_positive_and_extra_claim_and_wrong_display():
    case=json.loads(Path('evals/application_benchmark.json').read_text())['cases'][0]
    good='Cedar 2025 revenue: USD 120 million.'
    r=VerifiedResponse(answer=good,claims=[AnswerClaim(text=good)])
    assert score_outcome(case,r)
    r.answer+=' Cedar is insolvent.';assert not score_outcome(case,r)
    r.answer=good;r.claims.append(AnswerClaim(text='Cedar 2025 debt: USD 99 million.'));assert not score_outcome(case,r)
