"""Six reproducible scenarios; failure injection is labeled and credential-free."""
from __future__ import annotations
import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from config import load_settings
from openai_client import OpenAIClient
from ingestion import ingest_file
from orchestration import ResearchAssistant
from retrieval import HybridRetriever


def run_demo():
    provider=OpenAIClient(replace(load_settings(),embedding_provider='local_hash',openai_api_key=''))
    with tempfile.TemporaryDirectory(prefix='finsight-demo-') as directory:
        retriever=HybridRetriever('demo',str(Path(directory)/'qdrant'),provider)
        try:
            for name in ['Cedar','Elm']:
                retriever.index_chunks(ingest_file(f'evals/fixtures/{name}.pdf'))
            retriever.index_chunks(ingest_file('evals/repair_v3/Mint-2024-CFO.pdf'))
            service=ResearchAssistant(retriever)
            scenarios=[
                ('Document fact','What is revenue in the report for 2025?',['Cedar.pdf']),
                ('Real public document fact','What is United States Mint revenue for 2024 in the report?',['Mint-2024-CFO.pdf']),
                ('Document calculation','Calculate EMI using the loan in the report',['Cedar.pdf']),
                ('Reporting-period comparison','Compare revenue in the report for 2024 and 2025',['Cedar.pdf']),
                ('Contradictory evidence','What is revenue in the report for 2025?',['Elm.pdf']),
            ]
            results=[{'scenario':title,'query':query,'response':service.ask(query,scope).model_dump(mode='json')} for title,query,scope in scenarios]
            class FailedProvider:
                def generate_grounded_answer(self,*args):
                    raise TimeoutError('Injected provider timeout')
            failure=ResearchAssistant(retriever,FailedProvider()).ask('What is revenue in the report for 2025?',['Cedar.pdf'],use_provider=True)
            results.append({'scenario':'Provider failure (injected, not a real provider call)','response':failure.model_dump(mode='json')})
            return results
        finally:
            retriever.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='.test-tmp/demo.json',help='Write the six-scenario report without overwriting retained evidence.')
    args=parser.parse_args()
    results=run_demo()
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(results,indent=2),encoding='utf-8')
    for case in results:
        response=case['response']
        print(f"\n{case['scenario']} [{response['status']}]\n{response['answer']}")
