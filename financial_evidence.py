"""Bound financial records and faithful excerpts, never general prose entailment."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from decimal import Decimal
from calculation_inputs import InputIssue, SCALE_PATTERN, SCALES, currency_from_text
from schemas import RetrievalHit

CURRENCIES = r'USD|CAD|AUD|EUR|GBP|INR|JPY|SGD|AED|C\$|A\$|US\$|\$|€|£|₹'
QUANTITY = re.compile(rf'(?<![\w])(?P<open>\()?\s*(?P<cur>{CURRENCIES})?\s*(?P<n>[+-]?\d[\d,]*(?:\.\d+)?)\s*(?P<scale>{SCALE_PATTERN})?(?P<close>\))?\s*(?P<rate>%|percent|basis points?|bps|fraction)?\s*(?P<cur_after>USD|CAD|AUD|EUR|GBP|INR|JPY|SGD|AED)?(?!\w)', re.I)
PERIOD = re.compile(r'(?<![\w.$])(?:19|20)\d{2}(?![\d.]|\s*(?:million|billion|thousand|%))')

@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: str
    tolerance: Decimal

def quantities(text, default_currency=None, default_scale=None):
    text = re.sub(rf'({CURRENCIES})\s*\((\d[\d,.]*)\)\s*({SCALE_PATTERN})?', lambda m: f'{m[1]} -{m[2]} {m[3] or ""}', text, flags=re.I)
    result=[]
    for m in QUANTITY.finditer(text):
        n=m['n'].replace(',', '')
        value=Decimal(n)
        if m['open'] and m['close']: value=-value
        token=m['cur'] or m['cur_after']
        multiplier=Decimal(str(SCALES.get((m['scale'] or default_scale or '').lower(),1)))
        tolerance=Decimal(5)*Decimal(10)**(-len(n.partition('.')[2])-1)
        if m['rate']:
            unit='fraction'
            multiplier=Decimal(1) if m['rate'].lower()=='fraction' else Decimal('.0001') if m['rate'].lower() in {'bps','basis point','basis points'} else Decimal('.01')
        else: unit=currency_from_text(token) if token else default_currency or 'number'
        result.append(Quantity(value*multiplier,unit,tolerance*multiplier))
    return result

METRICS={
    'revenue':r'\b(?:revenue|revenues|net sales|total sales)\b',
    'net_income':r'\bnet (?:income|profit|earnings)\b',
    'operating_income':r'\boperating (?:income|profit)\b',
    'current_assets':r'\b(?:total )?current assets\b',
    'current_liabilities':r'\b(?:total )?current liabilities\b',
    'debt':r'\b(?:total )?debt\b',
    'equity':r'\b(?:(?:shareholders.?|stockholders.?|total) )?equity\b',
}
METRIC_RE=re.compile('|'.join(f'(?P<{k}>{v})' for k,v in METRICS.items()),re.I)

@dataclass
class FinancialFact:
    metric: str
    value: Decimal
    currency: str
    period: int | None
    entity: str
    chunk_id: str
    page: int | None
    source_name: str
    text: str
    scale: str='ones'
    headers: dict=field(default_factory=dict)
    relation: str='amount'
    tolerance: Decimal=Decimal('.005')
    start: int=0
    end: int=0
    def provenance(self):
        return {'source':'document','chunk_id':self.chunk_id,'page':self.page,'source_name':self.source_name,'text':self.text,'unit':self.currency,'period':self.period,'entity':self.entity,'metric':self.metric,'normalized_value':str(self.value),'scale':self.scale,'headers':self.headers,'start':self.start,'end':self.end}

def _headers(text,metadata):
    result=dict(metadata)
    for label,key,pattern in [('Company|Entity','entity',r'[^\n;]+'),('Period|Year','period',r'(?:19|20)\d{2}'),('Currency','currency',r'[A-Z]{3}'),('Units?','units',SCALE_PATTERN)]:
        values=re.findall(rf'^(?:{label})\s*:\s*({pattern})\s*$',text,re.I|re.M)
        if len({v.casefold() for v in values})>1: raise InputIssue(f'Conflicting {key} headers in evidence.','abstained')
        if values: result[key]=int(values[0]) if key=='period' else values[0].strip()
    return result

def _entity(prefix,fallback):
    prefix=re.sub(r'\b(?:in|for|during)?\s*(?:19|20)\d{2}\b','',prefix).strip(' ,:')
    prefix=re.sub(r'^(?:and|while|whereas)\s+','',prefix,flags=re.I)
    prefix=re.sub(r'\bFY\b','',prefix,flags=re.I).strip()
    match=re.fullmatch(r"([A-Z][A-Za-z '&.-]*?)(?:'s)?\s*(?:reported|reports|has|had)?\s*",prefix)
    return match[1].strip().removesuffix("'s") if match and prefix else fallback

def records_from_text(text,*,metadata=None,chunk_id='',page=None,source_name=''):
    headers=_headers(text,metadata or {})
    entity=str(headers.get('entity',''))
    period=headers.get('period')
    currency,scale=headers.get('currency'),headers.get('units')
    facts,table_years,table_metrics=[],[],[]
    offset=0
    for original in text.splitlines(keepends=True):
        line=original.strip()
        if re.match(r'^(?:Company|Entity|Period|Year|Currency|Units?)\s*:',line,re.I):
            offset+=len(original);continue
        cells=[c.strip() for c in line.split('|')]
        if '|' in line and not METRIC_RE.search(line):
            years=[int(y) for y in PERIOD.findall(line)]
            if years: table_years=years
        if '|' in line and re.match(r'^(?:Year|Period)\s*\|',line,re.I):
            table_metrics=[next((k for k,v in METRICS.items() if re.fullmatch(v,c,re.I)),None) for c in cells[1:]]
            offset+=len(original);continue
        if table_metrics and '|' in line and re.fullmatch(r'(?:19|20)\d{2}',cells[0]):
            for metric,cell in zip(table_metrics,cells[1:],strict=False):
                values=quantities(cell,currency,scale)
                if metric and len(values)==1:
                    q=values[0];facts.append(FinancialFact(metric,q.value,q.unit,int(cells[0]),entity,chunk_id,page,source_name,line,scale or 'ones',headers.copy(),tolerance=q.tolerance,start=offset,end=offset+len(original)))
            offset+=len(original);continue
        for clause in re.split(r';|(?<=\.)\s+',line):
            matches=list(METRIC_RE.finditer(clause))
            for i,m in enumerate(matches):
                prefix=clause[:m.start()] if i==0 else clause[matches[i-1].end():m.start()]
                if i: prefix=re.split(r'\band\b|\bwhile\b|\bwhereas\b',prefix,flags=re.I)[-1]
                local_entity=_entity(prefix,entity)
                tail=clause[m.end():matches[i+1].start() if i+1<len(matches) else len(clause)]
                tail=re.sub(r'\band\s+[A-Z][A-Za-z ]*(?:19|20)\d{2}\s*$','',tail)
                if table_years and '|' in clause and len(matches)==1:
                    values=[quantities(c,currency,scale) for c in tail.strip(' :|=').split('|')]
                    if len(values)!=len(table_years) or any(len(v)!=1 for v in values): continue
                    pairs=[(year,v[0],cell) for year,v,cell in zip(table_years,values,tail.strip(' :|=').split('|'),strict=True)]
                else:
                    years=[int(y) for y in PERIOD.findall(prefix)][-1:]
                    marked=re.compile(r'\b(?:in|for|during|year)\s+((?:19|20)\d{2})\b|^\s*((?:19|20)\d{2})(?=\s*(?:[:=]|was|is|were|reported))',re.I)
                    years.extend(int(ym[1] or ym[2]) for ym in marked.finditer(tail))
                    local_period=years[0] if len(set(years))==1 else period if not years else None
                    clean=marked.sub(' ',tail)
                    named=re.search(r'\bfor\s+([A-Z][A-Za-z &.-]*?)(?=\s+(?:in|for|was|is|during)\b|[,.:])',clean)
                    if named:
                        local_entity=named[1].strip();clean=clean[:named.start()]+clean[named.end():]
                    clean=re.split(r',\s+(?:a|an|up|down|representing|which)\b',clean,flags=re.I)[0]
                    values=quantities(clean,currency,scale)
                    pairs=[(local_period,values[0],tail)] if len(values)==1 else []
                for year,q,cell in pairs:
                    relation=('decrease' if re.search(r'declin\w*|decreas\w*|fell',cell,re.I) else 'increase' if re.search(r'grew|growth|increas\w*|rose',cell,re.I) else 'amount') if q.unit=='fraction' else 'amount'
                    facts.append(FinancialFact(m.lastgroup,q.value,q.unit,year,local_entity,chunk_id,page,source_name,clause,scale or 'ones',headers.copy(),relation,q.tolerance,offset,offset+len(original)))
        offset+=len(original)
    return facts

def extract_facts(hits: list[RetrievalHit]):
    return [f for h in hits for f in records_from_text(h.chunk.content,metadata=h.chunk.metadata,chunk_id=h.chunk.id,page=h.chunk.page,source_name=h.chunk.source_name) if f.currency not in {'number','fraction'} and f.period is not None]

def faithful_excerpt(claim,evidence):
    def norm(s):return re.sub(r'\s+',' ',re.sub(r'[^\w%$€£₹.-]+',' ',s)).strip(' .').casefold()
    candidate=norm(re.sub(r'^Source excerpt:\s*','',claim,flags=re.I))
    return bool(candidate) and any(candidate==norm(line) for line in re.split(r'\n|(?<=\.)\s+',evidence) if line.strip())

def supported_numbers(claim,evidence):
    clean=re.sub(r'\bpage\s+\d+','',claim,flags=re.I)
    if faithful_excerpt(clean,evidence) and (not quantities(clean) or clean.lower().startswith('source excerpt:')):return True
    try: expected,available=records_from_text(clean),records_from_text(evidence)
    except InputIssue:return False
    if not expected or not available:return False
    years={f.period for f in expected if f.period is not None}
    for q in quantities(clean):
        if q.unit=='number' and q.value in years:continue
        if not any(q.unit==f.currency and abs(q.value-f.value)<=q.tolerance for f in expected):return False
    if re.search(r'\b(?:insolvent|bankrupt|guaranteed|safe|recommend|buy|sell)\b',clean,re.I):return False
    return all(any(f.metric==a.metric and f.currency==a.currency and f.relation==a.relation and (f.period is None or f.period==a.period) and (not f.entity or f.entity.casefold()==a.entity.casefold()) and abs(f.value-a.value)<=f.tolerance for a in available) for f in expected)

def supported_claim(claim, hits):
    """Verified prose is either a complete faithful excerpt or canonical bound facts."""
    cited=[h for h in hits if h.chunk.id in claim.citation_ids]
    if not cited:return False
    if claim.text.lower().startswith('source excerpt:') or not quantities(claim.text):
        return any(faithful_excerpt(claim.text,h.chunk.content) for h in cited)
    # Canonical facts deliberately exclude unconstrained interpretation/advice.
    parts=re.split(r';|\n',claim.text)
    canonical=re.compile(rf"^\s*(?P<entity>[A-Za-z][A-Za-z '&.-]*?)\s+(?P<period>(?:19|20)\d{{2}})\s+(?P<metric>{'|'.join(METRICS.values())})\s*:\s*(?:{CURRENCIES})\s*[+-]?\d[\d,]*(?:\.\d+)?\s*(?:{SCALE_PATTERN})?\s*\.?\s*$",re.I)
    try:
        available=[f for h in cited for f in records_from_text(h.chunk.content,metadata=h.chunk.metadata)]
    except InputIssue:return False
    for part in parts:
        if not canonical.fullmatch(part):
            # An unchanged numeric excerpt is permitted only with an explicit label.
            return False
        expected=records_from_text(part)
        if len(expected)!=1:return False
        f=expected[0]
        matching=[a for a in available if a.metric==f.metric and a.period==f.period and a.entity.casefold()==f.entity.casefold()]
        if not matching or len({(a.value,a.currency) for a in matching})!=1:return False
        if not all(a.currency==f.currency and a.relation==f.relation and abs(a.value-f.value)<=f.tolerance for a in matching):return False
    return True

def select_fact(facts,metric,period=None,entity=None):
    matching=[f for f in facts if f.metric==metric and (period is None or f.period==period) and (entity is None or f.entity.casefold()==entity.casefold())]
    if not matching:raise InputIssue(f'No supported {metric} value for the requested company/period.','abstained')
    if len({(f.value,f.currency,f.period,f.entity.casefold()) for f in matching})>1:raise InputIssue(f'Conflicting or ambiguous {metric} values; specify one company and reporting period.','abstained')
    return matching[0]
