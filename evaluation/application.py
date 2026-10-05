"""Actual ingestion/retrieval/orchestration evaluation; no oracle answers are injected."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import platform
import statistics
import subprocess
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from config import load_settings
from llm_prompts import PROMPT_VERSION
from evaluation.metrics import evaluate_ranking, aggregate_metrics
from financial_evidence import quantities
from evaluation.scoring import score_outcome, VERSION as SCORER_VERSION
from openai_client import OpenAIClient
from ingestion import ingest_file
from orchestration import ResearchAssistant, provider_failure_reason
from retrieval import HybridRetriever

ROOT=Path(__file__).resolve().parents[1]


def provenance(dataset_path,provider):
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','--','*.py'],cwd=ROOT,text=True).splitlines()
    code_files=sorted({ROOT/name for name in names if not any(part.startswith('.') or part in {'data','__pycache__'} for part in Path(name).parts)})
    digest=hashlib.sha256()
    for p in code_files:
        digest.update(p.relative_to(ROOT).as_posix().encode())
        digest.update(p.read_bytes().replace(b'\r\n',b'\n'))
    return {'generated_at':datetime.now(UTC).isoformat(),'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'dirty_worktree':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),'code_digest':digest.hexdigest(),'dataset_sha256':hashlib.sha256(dataset_path.read_bytes()).hexdigest(),'python':platform.python_version(),'platform':platform.platform(),'dependencies':{name:importlib.metadata.version(name) for name in ['pydantic','qdrant-client','rank-bm25','openai','pdfplumber','PyMuPDF','streamlit','numpy']},'embedding_provider':provider.settings.embedding_provider,'embedding_model':provider.embedding_model,'dimensions':provider.embedding_dimensions,'llm_provider':'openai','text_model':provider.settings.openai_model,'prompt_version':PROMPT_VERSION,'ingestion_version':'financial-lines-v2','cost_usd':None,'cost_reason':'Provider invoices/prices are not inferred; token usage is reported where available.','label_review':'agent-authored; not independently human-reviewed'}


def answer_correct(case,response):
    return score_outcome(case,response)


def summarize(records):
    if not records:
        return {'cases':0,'answer_correctness':None,'reason':'No completed requests in this group.'}
    expected_answerable=[r for r in records if r['expected_status']=='ok']
    accepted=[r for r in records if r['response']['status']=='ok']
    unsupported=[r for r in records if r['expected_status']!='ok']
    abstained=[r for r in records if r['response']['status'] in {'abstained','clarification'}]
    tp=sum(r['expected_status']!='ok' for r in abstained)
    def ratio(n,d):
        return round(n/d,4) if d else None
    return {'cases':len(records),'answer_correctness':ratio(sum(r['correct'] for r in records),len(records)),'answer_coverage':ratio(len(accepted),len(records)),'answerable_coverage':ratio(sum(r['response']['status']=='ok' for r in expected_answerable),len(expected_answerable)),'over_abstention':ratio(sum(r['response']['status']!='ok' for r in expected_answerable),len(expected_answerable)),'unsupported_answer_rate':ratio(sum(r['response']['status']=='ok' for r in unsupported),len(unsupported)),'abstention_precision':ratio(tp,len(abstained)),'abstention_recall':ratio(tp,len(unsupported)),'numerical_accuracy_on_accepted':ratio(sum(r['correct'] for r in accepted),len(accepted)),'citation_correctness_on_accepted':ratio(sum(r['citation_correct'] for r in accepted if r['case_requires_documents']),sum(r['case_requires_documents'] for r in accepted)),'final_context_evidence_coverage':ratio(sum(r['context_coverage'] for r in expected_answerable),len(expected_answerable)),'latency_ms_mean':round(statistics.mean(r['response']['diagnostics'].get('total_ms',0) for r in records),3),'retrieval':aggregate_metrics([evaluate_ranking(r['retrieved_ids'],set(r['relevant_ids']),3) for r in expected_answerable if r['relevant_ids']]),'claim_support':'Conservative numerical/metadata checks only; general semantic entailment is not measured.'}


def finalize_report(report):
    """Null scores and missing slots describe unrun work, never zero accuracy."""
    records=report['records']
    modes=list(dict.fromkeys(p['mode'] for p in report['planned_requests']))
    attempted={(r['id'],r['mode'],r['repeat']) for r in records}
    report['missing_requests']=[dict(p,status='not_run',reason='Evaluation stopped before this request.') for p in report['planned_requests'] if (p['id'],p['mode'],p['repeat']) not in attempted]
    report['summary']={mode:{group:summarize([r for r in records if r['mode']==mode and (group=='all' or r['split']==group)]) for group in ['all','development','held_out']} for mode in modes}
    report['completed_cases']=len(records)
    report['openai_response_count']=sum(bool(r['response']['diagnostics'].get('provider_used')) for r in records)
    report['successful_openai_calls']=sum(r['response']['diagnostics'].get('provider_request',{}).get('validation')=='schema_valid' for r in records)
    report['complete']=not report['failures'] and len(records)==report['planned_cases']
    report['repeat_status']={mode:[] for mode in modes}
    for mode in modes:
        for repeat in range(report['repeats']):
            group=[r for r in records if r['mode']==mode and r['repeat']==repeat]
            planned=sum(p['mode']==mode and p['repeat']==repeat for p in report['planned_requests'])
            report['repeat_status'][mode].append({'repeat':repeat,'planned':planned,'completed':len(group),'status':'complete' if len(group)==planned else ('partial' if group else 'not_run'),'answer_correctness':summarize(group)['answer_correctness']})
    if report['repeats']>1:
        report['observed_variability']={mode:[g['answer_correctness'] for g in groups] for mode,groups in report['repeat_status'].items()}


def write_report(report, destination):
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix('.pending.json')
    temporary.write_text(json.dumps(report,indent=2),encoding='utf-8')
    temporary.replace(destination)


def run(dataset_path=ROOT/'evals/application_benchmark.json',embedding_provider='local_hash',live=False,repeats=1,split='all',limit=None,modes=None,checkpoint=None):
    dataset_path=Path(dataset_path)
    dataset=json.loads(dataset_path.read_text(encoding='utf-8'))
    settings=replace(load_settings(),embedding_provider=embedding_provider)
    if settings.openai_eval_model:
        settings=replace(settings,openai_model=settings.openai_eval_model)
    provider=OpenAIClient(settings)
    report={'benchmark':'finsight-application-openai-v1','dataset_version':dataset['version'],'metadata':provenance(dataset_path,provider),'live_generation':live,'repeats':repeats,'split':split,'records':[],'failures':[]}
    cases=[c for c in dataset['cases'] if split=='all' or c['split']==split]
    if limit:
        cases=cases[:limit]
    selected_modes=modes or ['bm25','dense','hybrid']
    report['planned_requests']=[{'id':c['id'],'mode':m,'repeat':r,'split':c['split']} for m in selected_modes for r in range(repeats) for c in cases]
    report['planned_cases']=len(report['planned_requests'])
    if live and not settings.openai_configured:
        report['failures'].append({'type':'Configuration','reason':'OPENAI_API_KEY is unavailable; no live OpenAI requests were made.'})
        finalize_report(report)
        if checkpoint:
            write_report(report,checkpoint)
        return report
    with tempfile.TemporaryDirectory(prefix='finsight-app-eval-') as directory:
        retriever=HybridRetriever('evaluation',str(Path(directory)/'qdrant'),provider)
        try:
            chunks=[]
            for doc in dataset['documents']:
                path=ROOT/doc['path']
                if hashlib.sha256(path.read_bytes()).hexdigest()!=doc['sha256']:
                    raise ValueError('Fixture digest differs from frozen manifest')
                chunks.extend(ingest_file(path,source_name=doc['source_name']))
            retriever.index_chunks(chunks)
            provider.embed_queries([c['query'] for c in cases])
            for mode in selected_modes:
                service=ResearchAssistant(retriever,provider,mode)
                for repeat in range(repeats):
                    for case in cases:
                        response=service.ask(case['query'],case['sources'],use_provider=live)
                        selected=response.diagnostics.get('evidence',[])
                        pages={h['chunk']['page'] for h in selected if h['chunk']['source_name'] in case['sources']}
                        relevant=[c.id for c in chunks if c.source_name in case['sources'] and c.page in case['required_pages'] and c.type.value!='image']
                        retrieved=response.diagnostics.get('retrieval_candidate_ids',[])
                        citation_correct=bool(response.citations) and all(c.source_name in case['sources'] and c.page in case['required_pages'] for c in response.citations)
                        report['records'].append({'id':case['id'],'mode':mode,'repeat':repeat,'split':case['split'],'query':case['query'],'expected_status':case['expected_status'],'expected_value':case['expected_value'],'case_requires_documents':True,'correct':answer_correct(case,response),'citation_correct':citation_correct,'context_coverage':len(pages.intersection(case['required_pages']))/len(case['required_pages']),'retrieved_ids':retrieved,'relevant_ids':relevant,'response':response.model_dump(mode='json'),'provider_raw_output':getattr(provider,'last_response',None) if live else None})
                        if checkpoint:
                            finalize_report(report)
                            write_report(report,checkpoint)
                        if live and len(report['records'])%10==0:
                            print(f"Completed {len(report['records'])} live cases",flush=True)
                        if live and response.status=='provider_failure':
                            report['failures'].append({'type':'ProviderFailure','reason':response.answer,'last_case':case['id'], 'error_code':response.diagnostics.get('provider_request',{}).get('error_code'), 'completion':'Live evaluation stopped after provider failure; completed requests are retained.'})
                            raise RuntimeError('Provider evaluation stopped')
        except (Exception, KeyboardInterrupt) as exc:
            if not report['failures']:
                report['failures'].append({'type':type(exc).__name__,'reason':'Evaluation interrupted.' if isinstance(exc,KeyboardInterrupt) else provider_failure_reason(exc)})
        finally:
            retriever.close()
    report['embedding_requests']=provider.embedding_requests
    finalize_report(report)
    if checkpoint:
        write_report(report,checkpoint)
    return report



def main():
    p=argparse.ArgumentParser()
    p.add_argument('--embedding-provider',choices=['local_hash','gemini','openai'],default='local_hash')
    p.add_argument('--live',action='store_true')
    p.add_argument('--repeats',type=int,default=1)
    p.add_argument('--split',choices=['all','development','held_out'],default='all')
    p.add_argument('--limit',type=int)
    p.add_argument('--output',default=None)
    p.add_argument('--quality-gate',action='store_true')
    p.add_argument('--mode',choices=['bm25','dense','hybrid'],action='append')
    args=p.parse_args()
    if args.repeats<1:
        p.error('repeats must be positive')
    if args.output is None:
        args.output='evals/results/application-openai-live.json' if args.live else 'evals/results/application-openai-offline.json'
    report=run(embedding_provider=args.embedding_provider,live=args.live,repeats=args.repeats,split=args.split,limit=args.limit,modes=args.mode,checkpoint=args.output if args.live else None)
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'summary':report['summary'],'failures':report['failures'],'output':str(output)},indent=2))
    if args.live and not report['complete']:
        raise SystemExit('Live OpenAI evaluation incomplete; inspect failures and missing_requests in the report.')
    if args.quality_gate:
        summary=report['summary'].get('hybrid',{}).get('all',{})
        if not report['complete'] or not summary or (summary['answer_correctness'] or 0)<.95 or summary['answerable_coverage']<.9 or summary['unsupported_answer_rate']>0:
            raise SystemExit('Application quality gate failed')


if __name__=='__main__':
    main()
