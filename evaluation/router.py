from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from router import route_query


def evaluate(path='evals/router_benchmark.json'):
    path=Path(path)
    data=json.loads(path.read_text(encoding='utf-8'))
    records=[]
    matrix={}
    routes={}
    for c in data['cases']:
        predicted=route_query(c['query'],c['has_documents'],c['has_images'],c['allow_web']).route.value
        expected=c['expected_route']
        matrix.setdefault(expected,{})[predicted]=matrix.setdefault(expected,{}).get(predicted,0)+1
        routes.setdefault(expected,{'cases':0,'correct':0})
        routes[expected]['cases']+=1
        routes[expected]['correct']+=int(predicted==expected)
        records.append({**c,'predicted_route':predicted,'correct':predicted==expected})
    return {'dataset_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'label_review':data['label_provenance'],'cases':len(records),'accuracy':sum(r['correct'] for r in records)/len(records),'per_route':routes,'confusion_matrix':matrix,'split_accuracy':{split:sum(r['correct'] for r in records if r['split']==split)/sum(r['split']==split for r in records) for split in ['development','held_out']},'records':records}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output',default='evals/results/router-v2.json')
    p.add_argument('--quality-gate',action='store_true')
    args=p.parse_args()
    report=evaluate()
    Path(args.output).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='records'},indent=2))
    if args.quality_gate and report['accuracy']<.95:
        raise SystemExit('Router quality gate failed')
