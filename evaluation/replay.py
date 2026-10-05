"""Revalidate recorded provider responses offline; never counts as new live calls."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from evaluation.application import answer_correct
from schemas import RetrievalHit, RouterDecision, StructuredLLMAnswer, VerifiedResponse
from evaluation.scoring import VERSION, legacy_labels, parse_fact, score_outcome
from evaluation.application import write_report
from verifier.verifi import verify_response


def read_historical(path):
    source_path=Path(path)
    if not source_path.exists() and source_path.suffix=='.json':
        index=Path('evals/results/evidence-index.json')
        match=next((e for e in json.loads(index.read_text())['entries'] if e['original_path']==source_path.as_posix()),None) if index.exists() else None
        source_path=Path(match['artifact']) if match else source_path.with_suffix('.json.gz')
    raw=source_path.read_bytes()
    return source_path,json.loads(gzip.decompress(raw) if source_path.suffix=='.gz' else raw)


def replay(path='evals/results/application-live.json'):
    _,source=read_historical(path)
    dataset=json.loads(Path('evals/application_benchmark.json').read_text())
    cases={c['id']:c for c in dataset['cases']}
    records=[]
    for record in source['records']:
        raw=record.get('provider_raw_output')
        if not raw or not raw.get('text'):
            continue
        structured=StructuredLLMAnswer.model_validate_json(raw['text'])
        old=record['response']
        hits=[RetrievalHit.model_validate(h) for h in old['diagnostics']['evidence']]
        decision=RouterDecision.model_validate(old['diagnostics']['route'])
        response=verify_response('',decision,hits,structured_answer=structured)
        records.append({'id':record['id'],'original_status':old['status'],'new_status':response.status,'correct':answer_correct(cases[record['id']],response),'reasons':response.reasons})
    return {'scope':'Offline replay of recorded provider outputs; no new provider calls, no full live benchmark claim','source':path,'source_code_digest':source['metadata']['code_digest'],'records':records}


def rescore(path='evals/results/application-openai-live-verified.json'):
    source_path,source=read_historical(path)
    dataset=json.loads(Path('evals/application_benchmark.json').read_text(encoding='utf-8'))
    cases={c['id']:c for c in dataset['cases']}
    records=[]
    for record in source['records']:
        response=VerifiedResponse.model_validate(record['response'])
        case=cases[record['id']]
        scope='complete_status_contract'
        if case['expected_status']=='ok' and response.status=='ok':
            if legacy_labels(case):
                scope='canonical_fact_contract' if response.claims and all(parse_fact(c.text) for c in response.claims) else 'unassessable_noncanonical_historical_prose'
            else:scope='partial_tool_labels_missing_complete_inputs_and_results'
        correct=None if scope.startswith('unassessable') else score_outcome(case,response)
        records.append({'id':record['id'],'mode':record['mode'],'repeat':record['repeat'],'historical_status':response.status,'historical_correct':record['correct'],'assessment_scope':scope,'correct':correct,'historical_generation_response':bool(response.diagnostics.get('provider_used'))})
    complete=[r for r in records if r['assessment_scope'] in {'complete_status_contract','canonical_fact_contract'}]
    partial=[r for r in records if r['assessment_scope'].startswith('partial')]
    return {'scope':'Offline rescore of retained outputs, zero new provider calls. No comparable replacement accuracy for noncanonical prose or incompletely labeled legacy tools.', 'source':source_path.as_posix(),'source_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),'source_revision':source['metadata']['revision'],'scorer_version':VERSION,'summary':{'historical_correct':sum(r['historical_correct'] for r in records),'historical_requests':len(records),'complete_assessable':len(complete),'complete_correct':sum(r['correct'] for r in complete),'partial_tool_assessable':len(partial),'partial_tool_correct':sum(r['correct'] for r in partial),'unassessable':sum(r['correct'] is None for r in records),'new_provider_calls':0},'records':records}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source',default='evals/results/application-openai-live-verified.json')
    p.add_argument('--output',default='evals/repair_v3/results/historical-rescore.json.gz')
    args=p.parse_args()
    report=rescore(args.source)
    write_report(report,args.output)
    print(json.dumps(report['summary'],indent=2))
