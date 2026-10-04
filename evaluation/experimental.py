"""Separate adapter smoke tests: provider support mappings are not entailment/freshness proof."""
from __future__ import annotations
import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pymupdf

from config import load_settings
from openai_client import OpenAIClient
from orchestration import provider_failure_reason


def visual_fixtures(directory):
    directory.mkdir(parents=True,exist_ok=True)
    paths=[]
    for kind in ['screenshot','chart','table']:
        with pymupdf.open() as doc:
            page=doc.new_page(width=500,height=400)
            page.insert_text((35,35),f'Synthetic {kind}: Acme 2025 (USD million)',fontsize=16)
            if kind=='chart':
                for x,label,value in [(70,'2024',100),(220,'2025',120)]:
                    page.draw_rect(pymupdf.Rect(x,300-value,x+80,300),color=(.1,.4,.7),fill=(.1,.4,.7))
                    page.insert_text((x,320),f'{label}: {value}',fontsize=14)
            elif kind=='table':
                for y,metric,value in [(90,'Revenue',120),(130,'Net income',24)]:
                    page.draw_rect(pymupdf.Rect(35,y,400,y+40))
                    page.insert_text((45,y+26),f'{metric}: {value}',fontsize=15)
            else:
                page.insert_text((35,95),'Revenue: USD 120 million\nNet income: USD 24 million',fontsize=16)
            path=directory/f'{kind}.png'
            page.get_pixmap().save(path)
            paths.append(path)
    return paths


def run(live=False, web=False):
    settings=replace(load_settings(),embedding_provider='local_hash')
    if settings.openai_eval_model:
        settings=replace(settings,openai_model=settings.openai_eval_model)
    provider=OpenAIClient(settings)
    report={'scope':'experimental adapter probes; excluded from verified performance','live':live,'provider':'openai','models':{'text':settings.openai_model,'vision':settings.openai_vision_model or settings.openai_model,'web':settings.openai_model},'visual':[],'web':{},'freshness_verified':False}
    paths=visual_fixtures(Path('evals/fixtures/visual'))
    for path in paths:
        record={'fixture':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'evidence_id':'visual-'+hashlib.sha256(path.read_bytes()).hexdigest()[:16],'expected_revenue_million':120}
        # These files contain no private input data.
        if live:
            try:
                result=provider.generate_multimodal_answer('Read the visible revenue, preserving its units and period. Return claims with the image evidence ID.',[path],[],[])
                record.update(status='provider_returned_output',raw_output=result.model_dump(mode='json'),usage=provider.last_usage,provider_request=provider.last_response,semantic_support_verified=False)
            except Exception as exc:
                record.update(status='blocked',reason=provider_failure_reason(exc),provider_request=provider.last_response)
        else:
            record.update(status='offline_image_parts_validated',image_parts=len(provider._image_parts([path])),semantic_support_verified=False)
        report['visual'].append(record)
    if live and web:
        try:
            answer,citations=provider.generate_web_grounded_answer('What is the most recent US Federal Reserve target rate? Give the source date and distinguish the source publication date from today.')
            report['web']={'status':'provider_returned_output','raw_output':answer.model_dump(mode='json'),'citations':[c.model_dump(mode='json') for c in citations],'usage':provider.last_usage,'provider_request':provider.last_response,'support_mappings_preserved':any(c.metadata.get('annotations') for c in citations),'freshness_verified':False}
        except Exception as exc:
            report['web']={'status':'blocked','reason':provider_failure_reason(exc),'provider_request':provider.last_response,'freshness_verified':False}
    if not (live and web):
        report['web']={'status':'not_run','reason':'Use --live --web and OPENAI_WEB_ENABLED=true for a live web check.'}
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--live',action='store_true')
    p.add_argument('--web',action='store_true',help='Explicitly request the experimental web-search probe.')
    p.add_argument('--output',default=None)
    args=p.parse_args()
    report=run(args.live,args.web)
    if args.output is None:
        args.output='evals/results/experimental-openai-live.json' if args.live else 'evals/results/experimental-openai-offline.json'
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'visual_statuses':[r['status'] for r in report['visual']],'web_status':report['web']['status'],'output':args.output},indent=2))
    if args.live and any(r.get('status')=='blocked' for r in report['visual']+[report['web']]):
        raise SystemExit('Experimental OpenAI checks blocked; see report.')
