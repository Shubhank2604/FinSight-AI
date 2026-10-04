"""Revalidate recorded provider responses offline; never counts as new live calls."""
from __future__ import annotations
import json
from pathlib import Path
from evaluation.application import answer_correct
from schemas import RetrievalHit, RouterDecision, StructuredLLMAnswer
from verifier.verifi import verify_response


def replay(path='evals/results/application-live.json'):
    source=json.loads(Path(path).read_text())
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


if __name__=='__main__':
    report=replay()
    Path('evals/results/provider-replay.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
