"""Credential-free tests use the official SDK with an in-memory HTTP transport."""
from __future__ import annotations

import json
from dataclasses import replace

import httpx2
import openai
import pytest
from PIL import Image
from pydantic import BaseModel

from config import DEFAULT_MODEL, Settings, load_settings
from embeddings import EmbeddingClient
from evaluation.application import run, summarize
from openai_client import OpenAIClient, ProviderError
from orchestration import ResearchAssistant
from schemas import AnswerClaim, ChunkType, DocumentChunk, RetrievalHit, Route, RouterDecision, StructuredLLMAnswer
from tools import calculate_emi
from verifier import verify_response


def payload(text=None, *, status='completed', output=None):
    if text is None:
        text=StructuredLLMAnswer(answer='Supported answer.',confidence=0.8).model_dump_json()
    return {'id':'resp_test','object':'response','created_at':1,'model':DEFAULT_MODEL,
            'status':status,'error':None,'incomplete_details':{'reason':'max_output_tokens'} if status=='incomplete' else None,
            'output':output if output is not None else [{'id':'msg_test','type':'message','status':'completed','role':'assistant',
                'content':[{'type':'output_text','text':text,'annotations':[]}]}],
            'usage':{'input_tokens':100,'output_tokens':20,'total_tokens':120,
                'input_tokens_details':{'cached_tokens':0},'output_tokens_details':{'reasoning_tokens':0}}}


def adapter(replies, settings=None):
    calls=[]
    sleeps=[]
    def handle(request):
        calls.append(json.loads(request.content))
        reply=replies[min(len(calls)-1,len(replies)-1)]
        if isinstance(reply,Exception):
            raise reply
        status,body=reply
        return httpx2.Response(status,json=body)
    sdk=openai.OpenAI(api_key='offline-secret',max_retries=0,http_client=httpx2.Client(transport=httpx2.MockTransport(handle)))
    return OpenAIClient(settings or Settings(),client=sdk,sleep=sleeps.append),calls,sleeps


def test_real_sdk_request_schema_and_telemetry():
    provider,calls,_=adapter([(200,payload())])
    result=provider.generate_grounded_answer('Explain',[])
    assert result.answer=='Supported answer.'
    request=calls[0]
    assert request['model']==DEFAULT_MODEL and request['store'] is False
    assert request['reasoning']=={'effort':'none'}
    assert 'temperature' not in request and 'tools' not in request
    schema=request['text']['format']['schema']
    assert request['text']['format']['strict'] is True
    assert schema['required']==list(schema['properties'])
    assert schema['additionalProperties'] is False
    assert schema['$defs']['AnswerClaim']['additionalProperties'] is False
    assert 'default' not in json.dumps(schema)
    assert provider.last_usage['total_tokens']==120
    assert provider.last_response['model']==DEFAULT_MODEL
    assert provider.last_response['validation']=='schema_valid'
    assert provider.last_response['latency_ms']>=0
    assert 'offline-secret' not in json.dumps(provider.last_response)


def test_generic_structured_extraction_and_standard_model():
    class Extraction(BaseModel):
        company: str
        revenue: float
    provider,calls,_=adapter([(200,payload('{"company":"Cedar","revenue":120.0}'))],Settings(openai_model='gpt-4.1-mini'))
    result=provider.generate_structured('Extract supplied facts, never calculate.',Extraction)
    assert result.company=='Cedar' and result.revenue==120
    assert calls[0]['text']['format']['name']=='Extraction'
    assert 'reasoning' not in calls[0]


@pytest.mark.parametrize('reply,code',[
    (payload(status='incomplete'),'incomplete'),
    (payload(status='failed'),'provider_failure'),
    (payload(text=''),'empty_output'),
    (payload(text='not JSON'),'schema'),
    (payload(text='{}'),'schema'),
    (payload(text=StructuredLLMAnswer(answer='',confidence=0.8).model_dump_json()),'empty_output'),
    (payload(text='{"answer":"x","confidence":2}'),'schema'),
    (payload(text='{"answer":"x"}'),'schema'),
    (payload(text=StructuredLLMAnswer(answer='x').model_dump_json()[:-1]+',"unexpected":true}'),'schema'),
    (payload(output=[{'id':'m','type':'message','status':'completed','role':'assistant','content':[{'type':'refusal','refusal':'no'}]}]),'refusal'),
])
def test_nonanswers_are_explicit_and_not_retried(reply,code):
    provider,calls,_=adapter([(200,reply)])
    with pytest.raises(ProviderError) as exc:
        provider.generate_grounded_answer('Explain',[])
    assert exc.value.code==code
    assert len(calls)==1 and provider.last_response['validation']=='failed'
    assert provider.last_usage['total_tokens']==120


@pytest.mark.parametrize('status,code,attempts',[(401,'authentication',1),(403,'permission',1),(404,'model_unavailable',1),(400,'unsupported_settings',1),(429,'rate_limit',3),(500,'provider_failure',3),(503,'provider_failure',3)])
def test_http_failures_and_bounded_retries(status,code,attempts):
    provider,calls,sleeps=adapter([(status,{'error':{'message':'do not expose offline-secret','code':'test'}})])
    with pytest.raises(ProviderError) as exc:
        provider.generate_grounded_answer('Explain',[])
    assert exc.value.code==code
    assert len(calls)==attempts and len(sleeps)==attempts-1
    assert provider.last_response['attempts']==attempts
    assert 'offline-secret' not in str(exc.value)+json.dumps(provider.last_response)


def test_quota_is_not_retried_and_rate_limit_can_recover():
    provider,calls,_=adapter([(429,{'error':{'code':'insufficient_quota','message':'quota'}})])
    with pytest.raises(ProviderError,match='quota'):
        provider.generate_grounded_answer('Explain',[])
    assert len(calls)==1
    provider,calls,sleeps=adapter([(429,{'error':{'code':'rate_limit_exceeded'}}),(200,payload())])
    assert provider.generate_grounded_answer('Explain',[]).answer
    assert len(calls)==2 and sleeps==[1]


@pytest.mark.parametrize('error,code',[(openai.APITimeoutError(request=httpx2.Request('POST','https://api.openai.com/v1/responses')),'timeout'),(openai.APIConnectionError(request=httpx2.Request('POST','https://api.openai.com/v1/responses')),'connection')])
def test_connection_failures_are_bounded(error,code):
    provider,calls,_=adapter([error])
    with pytest.raises(ProviderError) as exc:
        provider.generate_grounded_answer('Explain',[])
    assert exc.value.code==code and len(calls)==3


def test_missing_credentials_no_gemini_fallback():
    provider=OpenAIClient(Settings(gemini_api_key='not-used'))
    with pytest.raises(ProviderError,match='OPENAI_API_KEY'):
        provider.generate_grounded_answer('Explain',[])
    assert provider.last_response['attempts']==0
    assert provider.last_response['error_code']=='configuration'
    assert len(provider.embed_query('offline query'))==768
    assert 'not-used' not in repr(provider.settings)


@pytest.mark.parametrize('values',[{'openai_model':'gemini-2.5-flash'},{'openai_vision_model':'unsupported'},{'openai_eval_model':'unsupported'},{'openai_timeout':float('nan')},{'openai_max_retries':4},{'openai_max_output_tokens':0},{'embedding_provider':'unsupported'}])
def test_unsupported_configuration(values):
    with pytest.raises(ValueError):
        Settings(**values)


def test_env_configuration_validation(monkeypatch):
    monkeypatch.setattr('config.load_dotenv',lambda:None)
    monkeypatch.setenv('OPENAI_WEB_ENABLED','maybe')
    with pytest.raises(ValueError,match='true or false'):
        load_settings()
    monkeypatch.setenv('OPENAI_WEB_ENABLED','false')
    monkeypatch.setenv('OPENAI_MAX_RETRIES','secret-invalid-value')
    with pytest.raises(ValueError,match='OPENAI_MAX_RETRIES') as exc:
        load_settings()
    assert 'secret-invalid-value' not in str(exc.value)


def test_images_are_real_bytes_and_ids_remain_stable(tmp_path):
    path=tmp_path/'image.png'
    Image.new('RGB',(12,12),'white').save(path)
    hit=RetrievalHit(chunk=DocumentChunk(id='page-evidence',document_id='doc',source_name='report.pdf',page=2,type=ChunkType.IMAGE,content='Rendered page',metadata={'image_path':str(path)}),score=1,source='hybrid')
    provider,calls,_=adapter([(200,payload())],Settings(openai_vision_model='gpt-4.1-mini'))
    assert provider._image_parts([path])==provider._image_parts([path])
    provider.generate_multimodal_answer('Read', [path], [hit])
    content=calls[0]['input'][0]['content']
    assert 'page-evidence' in content[1]['text'] and 'page=2' in content[1]['text']
    assert content[2]['image_url'].startswith('data:image/png;base64,')
    assert calls[0]['model']=='gpt-4.1-mini'
    with pytest.raises(ValueError,match='missing'):
        provider._image_parts([tmp_path/'missing.png'])
    path.write_bytes(b'not an image')
    with pytest.raises(Exception):
        provider._image_parts([path])


def test_web_is_opt_in_and_annotations_sources_are_preserved():
    annotation={'type':'url_citation','url':'https://example.org/source','title':'Source','start_index':0,'end_index':10}
    output=[{'type':'web_search_call','id':'search','status':'completed','action':{'type':'search','query':'policy','sources':[{'type':'url','url':'https://example.org/source'}]}},
            {'type':'message','id':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':'Source fact.','annotations':[annotation,dict(annotation,start_index=11,end_index=12)]}]}]
    provider,calls,_=adapter([(200,payload(output=output))])
    with pytest.raises(ProviderError,match='disabled'):
        provider.generate_web_grounded_answer('Policy?')
    assert not calls
    provider.settings=replace(provider.settings,web_enabled=True)
    result,citations=provider.generate_web_grounded_answer('Policy?')
    assert result.answer=='Source fact.' and len(citations)==1
    assert calls[0]['tools']==[{'type':'web_search','external_web_access':True}]
    assert calls[0]['tool_choice']=='required'
    assert calls[0]['include']==['web_search_call.action.sources']
    assert len(citations[0].metadata['annotations'])==2
    assert citations[0].metadata['consulted_sources'][0]['url']==annotation['url']
    assert citations[0].metadata['published_at'] is None
    assert citations[0].metadata['freshness_verified'] is False


def test_web_without_annotations_is_failure():
    provider,_,_=adapter([(200,payload())],Settings(web_enabled=True))
    with pytest.raises(ProviderError,match='annotations'):
        provider.generate_web_grounded_answer('Policy?')


def test_schema_valid_wrong_financial_claim_is_rejected():
    chunk=DocumentChunk(id='fact',document_id='d',source_name='report.pdf',type=ChunkType.TEXT,content='Revenue grew 12%.')
    hit=RetrievalHit(chunk=chunk,score=1,source='hybrid')
    wrong=StructuredLLMAnswer(answer='Revenue grew 99%.',claims=[AnswerClaim(text='Revenue grew 99%.',citation_ids=['fact'])],used_citation_ids=['fact'])
    provider,_,_=adapter([(200,payload(wrong.model_dump_json()))])
    structured=provider.generate_grounded_answer('Revenue?', [hit])
    assert provider.last_response['validation']=='schema_valid'
    response=verify_response('',RouterDecision(route=Route.RETRIEVE_THEN_ANSWER,reason='test'),[hit],structured_answer=structured)
    assert response.status=='abstained'


def test_generation_cannot_change_authoritative_tool_values():
    tool=calculate_emi(1200,0,12)
    snapshot=tool.model_dump()
    wrong=StructuredLLMAnswer(answer='Monthly EMI: 999.',claims=[AnswerClaim(text='Monthly EMI: 999.')])
    provider,_,_=adapter([(200,payload(wrong.model_dump_json()))])
    structured=provider.generate_grounded_answer('Explain EMI',[],[tool.calculation])
    decision=RouterDecision(route=Route.COMPUTE_ONLY,required_tools=['emi_calculator'],reason='test')
    response=verify_response('',decision,tool_results=[tool],structured_answer=structured)
    assert response.status=='abstained' and tool.model_dump()==snapshot
    accepted=verify_response('',decision,tool_results=[tool])
    assert accepted.calculations[0].result==snapshot['calculation']['result']


def test_quota_report_retains_request_and_marks_later_repeats(tmp_path,monkeypatch):
    monkeypatch.setattr('evaluation.application.load_settings',lambda:Settings(openai_api_key='offline-test'))
    def quota(self,*args):
        raise ProviderError('quota','OpenAI quota exhausted.')
    monkeypatch.setattr(OpenAIClient,'generate_grounded_answer',quota)
    target=tmp_path/'report.json'
    report=run(live=True,repeats=3,limit=1,modes=['hybrid'],checkpoint=target)
    persisted=json.loads(target.read_text(encoding='utf-8'))
    assert len(report['records'])==1 and len(report['missing_requests'])==2
    assert report['records'][0]['response']['status']=='provider_failure'
    assert report['observed_variability']['hybrid']==[0.0,None,None]
    assert report['repeat_status']['hybrid'][1]['status']=='not_run'
    assert not persisted['complete'] and persisted['records']==report['records']


def test_missing_key_report_is_not_a_live_success(monkeypatch):
    monkeypatch.setattr('evaluation.application.load_settings',lambda:Settings())
    report=run(live=True,repeats=2,limit=1,modes=['hybrid'])
    assert report['successful_openai_calls']==0 and not report['records']
    assert len(report['missing_requests'])==2 and not report['complete']
    assert report['observed_variability']['hybrid']==[None,None]
    assert summarize([])['answer_correctness'] is None


def test_experimental_web_route_requires_both_opt_ins():
    annotation={'type':'url_citation','url':'https://example.org/source','title':'Source','start_index':0,'end_index':10}
    output=[{'type':'web_search_call','id':'search','status':'completed','action':{'type':'search','query':'price'}},
            {'type':'message','id':'m','role':'assistant','status':'completed','content':[{'type':'output_text','text':'Source fact.','annotations':[annotation]}]}]
    provider,calls,_=adapter([(200,payload(output=output))],Settings(web_enabled=True))
    service=ResearchAssistant(provider=provider)
    assert service.ask('What is the latest stock price?',allow_web=False,use_provider=True).status!='experimental'
    assert service.ask('What is the latest stock price?',allow_web=True,use_provider=False).status=='unsupported'
    assert not calls
    result=service.ask('What is the latest stock price?',allow_web=True,use_provider=True)
    assert result.status=='experimental' and result.citations[0].url=='https://example.org/source'
    assert result.diagnostics['provider_request']['validation']=='annotations_preserved_not_fact_verified'
    assert len(calls)==1


def test_model_change_keeps_embedding_collection_and_points(tmp_path):
    from retrieval import HybridRetriever
    settings=Settings(qdrant_path=str(tmp_path/'qdrant'))
    original=HybridRetriever('test',settings.qdrant_path,EmbeddingClient(settings))
    chunk=DocumentChunk(id='00000000-0000-0000-0000-000000000001',document_id='doc',source_name='report.pdf',type=ChunkType.TEXT,content='Revenue grew 12%.')
    original.index_chunks([chunk])
    identity=original.index_identity
    collection=original.collection_name
    original.close()
    changed=HybridRetriever('test',settings.qdrant_path,EmbeddingClient(replace(settings,openai_model='gpt-4.1-mini')))
    try:
        assert changed.index_identity==identity and changed.collection_name==collection
        assert changed.chunks[0].id==chunk.id
    finally:
        changed.close()


def test_optional_gemini_embedding_dependency_is_explicit(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules,'google',None)
    embeddings=EmbeddingClient(Settings(embedding_provider='gemini',gemini_api_key='private-key'))
    with pytest.raises(ValueError,match='requirements-embeddings.txt') as exc:
        embeddings.embed_query('revenue')
    assert 'private-key' not in str(exc.value)


def test_openai_embeddings_use_requested_space_and_order():
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx2.Response(200, json={'object': 'list', 'model': 'text-embedding-3-small',
            'data': [{'object': 'embedding', 'index': 1, 'embedding': [0., 1., 0.]},
                     {'object': 'embedding', 'index': 0, 'embedding': [1., 0., 0.]}],
            'usage': {'prompt_tokens': 5, 'total_tokens': 5}})
    e = EmbeddingClient(Settings(embedding_provider='openai', openai_api_key='offline-test'), 3)
    e._client = openai.OpenAI(api_key='offline-test', http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    assert e.embed_texts(['first', 'second']) == [[1., 0., 0.], [0., 1., 0.]]
    assert calls[0]['model'] == e.embedding_model
    assert calls[0]['dimensions'] == 3 and calls[0]['encoding_format'] == 'float'
    assert e.embedding_requests[0]['usage']['total_tokens'] == 5


def test_openai_embedding_error_does_not_expose_body():
    def handler(request):
        return httpx2.Response(401, json={'error': {'message': 'private-key private financial input', 'type': 'authentication_error'}})
    e = EmbeddingClient(Settings(embedding_provider='openai', openai_api_key='private-key', openai_max_retries=0))
    e._client = openai.OpenAI(api_key='private-key', max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    with pytest.raises(ValueError) as exc:
        e.embed_query('private financial input')
    assert 'private-key' not in str(exc.value) and 'private financial input' not in str(exc.value)
    assert e.embedding_requests[-1]['status'] == 'failed'
    assert e.embedding_requests[-1]['error_code'] == 'authentication'


@pytest.mark.parametrize('data', [
    [{'object': 'embedding', 'index': 0, 'embedding': [1.]}],
    [{'object': 'embedding', 'index': 1, 'embedding': [1., 0., 0.]}],
    [{'object': 'embedding', 'index': 0, 'embedding': [0., 0., 0.]}],
    [{'object': 'embedding', 'index': 0, 'embedding': [float('nan'), 0., 1.]}],
])
def test_openai_embeddings_reject_incompatible_responses(data):
    def handler(request):
        return httpx2.Response(200, content=json.dumps({'object': 'list', 'model': 'text-embedding-3-small',
            'data': data, 'usage': {'prompt_tokens': 1, 'total_tokens': 1}}).encode(), headers={'content-type': 'application/json'})
    e = EmbeddingClient(Settings(embedding_provider='openai', openai_api_key='offline-test'), 3)
    e._client = openai.OpenAI(api_key='offline-test', http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    with pytest.raises(ValueError, match='incompatible'):
        e.embed_query('revenue')


def test_openai_embedding_index_isolated_from_hash(tmp_path):
    from retrieval import HybridRetriever
    settings = Settings(qdrant_path=str(tmp_path/'qdrant'))
    r = HybridRetriever('test', settings.qdrant_path, EmbeddingClient(settings))
    old = r.collection_name
    r.close()
    semantic = HybridRetriever('test', settings.qdrant_path, EmbeddingClient(replace(settings, embedding_provider='openai')))
    try:
        assert semantic.collection_name != old
        assert semantic.index_identity['model'] == 'text-embedding-3-small'
        assert semantic.chunks == []
    finally:
        semantic.close()
    with pytest.raises(ValueError, match='dimensions'):
        EmbeddingClient(replace(settings, embedding_provider='openai'), 1537)


def test_live_acceptance_runner_records_unavailable_credentials(monkeypatch):
    from evaluation.provider_checks import run as checks
    monkeypatch.setattr('evaluation.provider_checks.load_settings',lambda:Settings())
    report=checks(live=True)
    assert not report['complete'] and len(report['records'])==3
    assert all(r['status']=='not_run' for r in report['records'])


def test_report_marks_partial_repeat(tmp_path,monkeypatch):
    monkeypatch.setattr('evaluation.application.load_settings',lambda:Settings(openai_api_key='offline-test'))
    def quota(self,*args):
        raise ProviderError('quota','OpenAI quota exhausted.')
    monkeypatch.setattr(OpenAIClient,'generate_grounded_answer',quota)
    report=run(live=True,repeats=2,limit=2,modes=['hybrid'],checkpoint=tmp_path/'report.json')
    assert report['repeat_status']['hybrid'][0]['status']=='partial'
    assert report['repeat_status']['hybrid'][1]['status']=='not_run'
    assert len(report['missing_requests'])==3
