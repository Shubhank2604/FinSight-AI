"""Rebuild CC0 agent-authored fixtures. Splits are fixed by company before tuning."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
COMPANIES = ['Cedar', 'Harbor', 'Quartz', 'Maple', 'Juniper', 'Beacon', 'Willow', 'Pine', 'Orchid', 'Aspen', 'Birch', 'Elm']


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def build():
    directory = ROOT/'evals/fixtures'
    directory.mkdir(parents=True, exist_ok=True)
    cases, documents = [], []
    for index, company in enumerate(COMPANIES):
        split = 'development' if index < 8 else 'held_out'
        prior = 100 + index*10
        revenue = prior*1.2
        amounts = {'Revenue': revenue, 'Net income': revenue*.2, 'Operating income': revenue*.25, 'Current assets':60+index*2, 'Current liabilities':30+index, 'Debt':40+index*2, 'Equity':80+index*4}
        currency = ['USD','CAD','AUD'][index%3]
        path = directory/f'{company}.pdf'
        with pymupdf.open() as doc:
            # Actual PDFs contain vector table borders, text and headers; no provider is needed.
            for year in [2024,2025]:
                page = doc.new_page(width=612,height=792)
                scale = 'billion' if index%4==3 else 'million'
                divisor = 1000 if scale=='billion' else 1
                header=f'Company: {company}\nPeriod: {year}\nCurrency: {currency}\nUnits: {scale}'
                page.insert_text((40,40),header,fontsize=11)
                values={**amounts,'Revenue':prior if year==2024 else revenue}
                for row,(metric,value) in enumerate(values.items()):
                    top=110+row*28
                    page.draw_rect(pymupdf.Rect(40,top,430,top+28))
                    page.draw_line(pymupdf.Point(250,top),pymupdf.Point(250,top+28))
                    page.insert_text((48,top+18),metric,fontsize=11)
                    page.insert_text((258,top+18),str(round(value/divisor,6)),fontsize=11)
                page.insert_text((40,350),'Supply risk: component shortages can delay orders.\nEarly repayment is permitted without a penalty.',fontsize=11)
            page=doc.new_page()
            page.insert_text((40,40),f'Company: {company}\nLoan principal: {currency} 500000\nAnnual interest rate: 8%\nDuration: 20 years',fontsize=11)
            if index==11:
                page=doc.new_page()
                page.insert_text((40,40),f'Company: {company}\nPeriod: 2025\nCurrency: {currency}\nUnits: million\nRevenue: 999',fontsize=11)
            doc.save(path,garbage=4,deflate=True)
        documents.append({'source_name':path.name,'path':str(path.relative_to(ROOT)).replace('\\','/'),'company':company,'split':split,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'license':'CC0-1.0','label_provenance':'agent-authored, arithmetic labels generated from fixture parameters; no independent human review'})
        labels=[
            (f'What is revenue for {company} in the report for 2025?', 'revenue', revenue*1e6),
            (f'According to the report, what is net income for {company} in 2025?', 'net_income', revenue*.2*1e6),
            (f'What are current assets for {company} in the document for 2025?', 'current_assets',(60+index*2)*1e6),
            (f'Calculate current ratio for {company} in the report for 2025','current_ratio',2),
            (f'Compute net margin for {company} in the report for 2025','margin',20),
            (f'Calculate debt-to-equity for {company} in the report for 2025','debt_to_equity',.5),
            (f'Compute year-over-year revenue growth for {company} in the report for 2025','yoy_growth',20),
            (f'Compare revenue for {company} in the report for 2024 and 2025','comparison',[prior*1e6,revenue*1e6]),
            (f'What is revenue for {company} in the report for 2028?','absent',None),
            (f'Calculate EMI using the loan in the report for {company}','emi_calculator',4182.2),
        ]
        for n,(query,operation,expected) in enumerate(labels):
            conflict=index==11 and operation in {'revenue','margin','yoy_growth','comparison'}
            cases.append({'id':f'{company.lower()}-{n+1:02d}','query':query,'sources':[path.name], 'split':split,'operation':operation,'expected_status':'abstained' if expected is None or conflict else 'ok','expected_value':None if conflict else expected,'expected_currency':currency,'expected_period':2025,'required_pages':[3] if operation=='emi_calculator' else ([1,2] if operation in {'yoy_growth','comparison'} else [2]),'tags':['conflict'] if conflict else (['absent'] if expected is None else ['answerable'])})
    write_json(ROOT/'evals/application_benchmark.json',{'version':'2.0.0','created_on':'2026-10-04','split_policy':'company-level split frozen before implementation tuning: first 8 development, final 4 held out','label_provenance':'agent-authored, not independently human-reviewed','documents':documents,'cases':cases})
    groups=[
        ('document_fact','retrieve_then_answer',True,False,False,['What is revenue in the uploaded report?','Explain the mortgage prepayment clause in this report','Summarize portfolio returns for 2025 in this report','What is the current ratio in this report?','What are current assets in the statement?','Compare revenue across years in the report','Explain risks according to the document','What is debt in the filing?','Summarize the attached statement','What is the latest figure in the uploaded report?']),
        ('compute','compute_only',False,False,False,['Calculate EMI on a $500000 loan at 8% for 20 years','Compute EMI at 8% for 20 years','Project portfolio for $1000 monthly at 8% for 10 years','Calculate loan payments at 5%','Simulate investing $500 monthly','Estimate future value of an investment','Calculate EMI for CAD 200000','Compute mortgage payment','Calculate portfolio growth','Project investments over 10 years']),
        ('document_compute','retrieve_then_compute_then_answer',True,False,False,['Calculate current ratio in the report','Compute net margin in the document','Calculate debt-to-equity in the report','Compute year-over-year revenue growth in the report','Calculate EMI using the loan in the document','Project portfolio growth using the report','Calculate operating margin in the report','Calculate revenue growth in the report','Compute mortgage EMI from the uploaded report','Calculate net profit margin in the statement']),
        ('education','educational_answer',True,False,False,['What is revenue?','Explain current ratio','What are current assets?','Tell me about SEC filings','Explain retirement planning','How does EMI work?','What is net margin?','Define debt-to-equity','Explain revenue growth','What is a mortgage prepayment clause?']),
        ('web','web_grounded_answer',True,False,True,['What is the latest Fed interest rate?','What is the current stock price?','Search news about earnings today','What is the exchange rate today?','Find recent inflation news','What is current USD to CAD exchange rate?','Search online for the latest earnings','What is today\'s market price?','Tell me recent interest rate news','What is the latest price online?']),
        ('web_disabled','abstain',False,False,False,['What is the latest Fed rate?','What is the current stock price?','Search news today','What is exchange rate today?','Find recent inflation news','What is current USD to INR rate?','Search online for the latest earnings','What is today\'s market price?','Tell me recent interest rate news','What is the latest price online?']),
        ('missing_document','abstain',False,False,True,['What is revenue in the report?','Explain the clause in this document','Summarize the uploaded report','What is the current ratio in this report?','Calculate EMI from the report','What are current assets in the statement?','Explain risk in the filing','Compare revenue in the report','Calculate net margin from the report','What is equity according to the document?']),
        ('visual','multimodal_reasoning',True,True,False,['Explain this chart','Analyze the uploaded image','What is visible in the screenshot?','Describe this graph','Summarize this diagram','Explain the chart in the report','What is in this picture?','Read this image','Compare bars in this chart','Summarize the screenshot']),
        ('unsupported','abstain',False,False,False,['','Write a song','Buy shares for me','Calculate a bond price','Build a game','Calculate a cryptocurrency forecast','Forecast oil demand','Translate hello','Book a flight','Calculate my unsupported metric']),
        ('document_unsupported','abstain',True,False,False,['Calculate a bond price in the report','Compute EBITDA in the report','Calculate IRR in the document','Calculate duration in the report','Compute VaR in the report','Estimate dividends in the document','Calculate inventory turnover in the report','Calculate beta in the report','Compute taxable income in the document','Calculate free cash flow in the report']),
    ]
    router_cases=[]
    for category,route,docs,images,web,queries in groups:
        for i,q in enumerate(queries):
            router_cases.append({'id':f'{category}-{i+1:02d}','query':q,'has_documents':docs,'has_images':images,'allow_web':web,'expected_route':route,'split':'held_out' if i>=7 else 'development','category':category})
    write_json(ROOT/'evals/router_benchmark.json',{'version':'2.0.0','label_provenance':'agent-authored, no independent human review','split_policy':'final three per category held out before tuning','cases':router_cases})
    (directory/'LICENSE.txt').write_text('CC0 1.0: These synthetic documents and labels were authored for FinSight evaluation. No real company facts or private documents are included. No independent human review has occurred.\n',encoding='utf-8')
    print(f'Built {len(documents)} PDFs, {len(cases)} application cases, {len(router_cases)} router cases.')


if __name__=='__main__':
    build()
