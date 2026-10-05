"""Small live acceptance checks on redistributable document fixtures.

Offline mode does no generation; mocked tests live in tests/, separately.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from config import load_settings
from evaluation.application import ROOT, provenance, write_report
from evaluation.budget import EvaluationBudget
from evaluation.scoring import score_outcome
from ingestion import ingest_file
from openai_client import OpenAIClient
from orchestration import ResearchAssistant, provider_failure_reason
from retrieval import HybridRetriever
from schemas import RetrievalHit, RouterDecision
from verifier import verify_response


def run(live=False,budget=None):
    settings=replace(load_settings(),embedding_provider='local_hash')
    if settings.openai_eval_model:
        settings=replace(settings,openai_model=settings.openai_eval_model)
    if budget:settings=replace(settings,openai_max_output_tokens=min(settings.openai_max_output_tokens,1024))
    provider=OpenAIClient(settings,budget=budget)
    report={'scope':'OpenAI live acceptance probes, separate from historical Gemini results',
            'live_requested':live,'metadata':provenance(ROOT/'evals/application_benchmark.json',provider), 'records':[]}
    names=['grounded_document_answer','structured_extraction','document_calculation_explanation']
    if not live or not settings.openai_configured:
        reason='Offline mode; no OpenAI calls.' if not live else 'OPENAI_API_KEY unavailable; no OpenAI calls.'
        report['records']=[{'check':name,'status':'not_run','reason':reason} for name in names]
        report['complete']=False
        return report
    with tempfile.TemporaryDirectory(prefix='finsight-openai-') as directory:
        retriever=HybridRetriever('openai-checks',str(Path(directory)/'qdrant'),provider)
        try:
            retriever.index_chunks(ingest_file(ROOT/'evals/fixtures/Cedar.pdf'))
            service=ResearchAssistant(retriever,provider)
            for name in names:
                provider.last_response=None
                try:
                    if name=='document_calculation_explanation':
                        # Production calculations are direct tool outputs; this separate
                        # probe checks the migrated explanation API cannot change them.
                        query='Calculate current ratio for 2025 in the report'
                        base=service.ask(query,['Cedar.pdf'])
                        if base.status!='ok' or not base.calculations:
                            raise ValueError('Document calculation failed before generation')
                        snapshots=[c.model_dump() for c in base.calculations]
                        hits=[RetrievalHit.model_validate(h) for h in base.diagnostics['evidence']]
                        structured=provider.generate_grounded_answer(query,hits,base.calculations)
                        from schemas import ToolResult
                        response=verify_response('',RouterDecision.model_validate(base.diagnostics['route']),hits,
                            tool_results=[ToolResult(success=True,calculation=c) for c in base.calculations],structured_answer=structured)
                        correct=response.status=='ok' and [c.model_dump() for c in response.calculations]==snapshots
                    else:
                        query='What is revenue for 2025 in the Cedar report?'
                        if name=='structured_extraction':
                            query='Extract the revenue for 2025 from the Cedar report as a factual claim, preserving company, currency, units, period and evidence IDs.'
                        response=service.ask(query,['Cedar.pdf'],use_provider=True)
                        expected={'operation':'revenue','expected_status':'ok','expected_facts':[
                            {'entity':'Cedar','metric':'revenue','period':2025,'currency':'USD','value':120000000}]}
                        correct=bool(response.citations) and score_outcome(expected,response)
                    record={'check':name,'status':'passed' if correct else 'failed','validation_passed':correct,
                            'response':response.model_dump(mode='json'),'provider_request':provider.last_response}
                except Exception as exc:
                    record={'check':name,'status':'failed','validation_passed':False,'reason':provider_failure_reason(exc),'provider_request':provider.last_response}
                report['records'].append(record)
                if (provider.last_response or {}).get('error_code'):
                    break
        finally:
            retriever.close()
    done={r['check'] for r in report['records']}
    report['records'].extend({'check':name,'status':'not_run','reason':'Stopped after provider failure.'} for name in names if name not in done)
    report['complete']=all(r['status']=='passed' for r in report['records'])
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--budget-usd',type=float)
    parser.add_argument('--budget-ledger',default='.test-tmp/openai-repair-budget.json')
    parser.add_argument('--output',default='evals/results/provider-openai-checks.json')
    args=parser.parse_args()
    if args.live and args.budget_usd is None:parser.error('Live checks require an explicitly authorized --budget-usd cap.')
    budget=EvaluationBudget(args.budget_usd,args.budget_ledger) if args.budget_usd is not None else None
    report=run(args.live,budget)
    write_report(report,args.output)
    print(json.dumps({'complete':report['complete'],'checks':[{k:r[k] for k in ('check','status')} for r in report['records']],'output':args.output},indent=2))
    if args.live and not report['complete']:
        raise SystemExit('OpenAI live verification incomplete; see report.')
