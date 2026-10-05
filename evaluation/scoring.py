"""Independent label scorer. Does not call the application's parser or verifier."""
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation

VERSION='bound-label-scorer-v3'
FACT=re.compile(r"^\s*(?P<entity>[A-Za-z][A-Za-z '&.-]*?)\s+(?P<period>(?:19|20)\d{2})\s+(?P<metric>revenue|net income|operating income|current assets|current liabilities|debt|equity)\s*:\s*(?P<currency>USD|CAD|AUD|EUR|GBP|INR|JPY|SGD|AED)\s*(?P<value>[+-]?\d[\d,]*(?:\.\d+)?)\s*(?P<scale>thousand|million|billion)?\s*\.?\s*$",re.I)
SCALE={'thousand':Decimal(1000),'million':Decimal(1000000),'billion':Decimal(1000000000)}

def parse_fact(text):
    m=FACT.fullmatch(text)
    if not m:return None
    return {'entity':m['entity'].casefold(),'metric':m['metric'].lower().replace(' ','_'),'period':int(m['period']),'value':Decimal(m['value'].replace(',',''))*SCALE.get((m['scale'] or '').lower(),Decimal(1)),'currency':m['currency'].upper()}

def legacy_labels(case):
    """Explicit historical label translation, never sent to the request pipeline."""
    if 'expected_facts' in case:return case['expected_facts']
    if case['operation'] not in {'revenue','net_income','current_assets','comparison'}:return []
    values=case['expected_value'] if isinstance(case['expected_value'],list) else [case['expected_value']]
    entity=case.get('expected_entity',case['sources'][0].rsplit('.',1)[0])
    periods=[2024,2025] if case['operation']=='comparison' else [case['expected_period']]
    return [{'entity':entity,'metric':'revenue' if case['operation']=='comparison' else case['operation'],'period':year,'value':value,'currency':case['expected_currency']} for year,value in zip(periods,values,strict=True)]

def equal(actual,expected,tolerance=Decimal('0')):
    if isinstance(expected,dict):return isinstance(actual,dict) and set(actual)==set(expected) and all(equal(actual[k],v,tolerance) for k,v in expected.items())
    if isinstance(expected,list):return isinstance(actual,list) and len(actual)==len(expected) and all(equal(a,b,tolerance) for a,b in zip(actual,expected,strict=True))
    if isinstance(expected,(float,int,Decimal)) and not isinstance(expected,bool):
        if isinstance(expected, int):
            tolerance = Decimal('0')
        try:return not isinstance(actual,bool) and Decimal(str(actual)).is_finite() and abs(Decimal(str(actual))-Decimal(str(expected)))<=tolerance
        except (InvalidOperation,TypeError):return False
    return actual==expected

def score_outcome(case,response):
    expected_status=case['expected_status']
    if expected_status!='ok':return response.status==expected_status
    if response.status!='ok':return False
    labels=legacy_labels(case)
    if labels:
        if response.calculations or len(response.claims)!=len(labels):return False
        actual=[parse_fact(c.text) for c in response.claims]
        if any(f is None for f in actual):return False
        wanted=[{**f,'entity':f['entity'].casefold(),'value':Decimal(str(f['value']))} for f in labels]
        unmatched=list(wanted)
        for fact in actual:
            match=next((f for f in unmatched if equal(fact,f,Decimal('.005'))),None)
            if match is None:return False
            unmatched.remove(match)
        # No additional factual narrative may be displayed alongside the claims.
        normalize=lambda s:re.sub(r'\s+',' ',re.sub(r'\[[^\[\]]+\]','',s)).strip()
        return not unmatched and normalize(response.answer)==normalize('\n'.join(c.text for c in response.claims))
    if case.get('expected_excerpts'):
        normalize=lambda s:re.sub(r'\s+',' ',re.sub(r'\[[^\[\]]+\]','',s)).strip()
        return not response.calculations and [c.text for c in response.claims]==case['expected_excerpts'] and normalize(response.answer)==normalize('\n'.join(case['expected_excerpts']))
    if len(response.calculations)!=1 or response.claims:return False
    c=response.calculations[0]
    visible=re.sub(r'\s+',' ',re.sub(r'\[[^\[\]]+\]','',response.answer)).strip()
    expected_display=' '.join([c.tool_name.replace('_',' ').capitalize()]+[f"{k.replace('_',' ')}: {v}" for k,v in c.result.items() if not isinstance(v,(dict,list))])
    if visible!=expected_display:return False
    operation=case.get('expected_operation',case['operation'])
    if c.tool_name!=operation:return False
    if case.get('expected_inputs') and not equal(c.inputs,case['expected_inputs']):return False
    if case.get('expected_result'):
        return equal(c.result,case['expected_result'],Decimal('.00005'))
    # Legacy reports lack complete tool labels: explicitly mark limited assessment.
    keys={'current_ratio':'ratio','debt_to_equity':'ratio','margin':'margin_pct','operating_margin':'margin_pct','yoy_growth':'growth_pct','emi_calculator':'monthly_emi'}
    key=keys.get(operation)
    if key is None or not equal(c.result.get(key),case['expected_value'],Decimal('.005') if operation=='emi_calculator' else Decimal('.00005')):return False
    if c.result.get('currency')!=case['expected_currency']:return False
    if operation!='emi_calculator':
        entity=case.get('expected_entity',case['sources'][0].rsplit('.',1)[0])
        periods=[case['expected_period']-1,case['expected_period']] if operation=='yoy_growth' else [case['expected_period']]
        if c.result.get('entity')!=entity or c.result.get('periods')!=periods:return False
    return True
