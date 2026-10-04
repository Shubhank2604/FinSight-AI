from __future__ import annotations


def test_streamlit_submit_shows_evidence_and_clears_pending(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('QDRANT_PATH',str(tmp_path/'qdrant'))
    monkeypatch.setenv('EMBEDDING_PROVIDER','local_hash')
    app=AppTest.from_file('app.py',default_timeout=20).run()
    assert not app.exception
    app.text_area(key='query').set_value('Calculate EMI for 20 years at 8% on a $500000 loan')
    app.button(key='FormSubmitter:query_form-Ask').click().run()
    assert not app.exception
    assert app.session_state['pending_request'] is None
    response=app.session_state['history'][-1]['response']
    assert response['status']=='ok'
    assert response['calculations'][0]['inputs']['principal']==500000
    assert any('Inputs and result' in e.label for e in app.expander)


def test_streamlit_document_citations_are_readable(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from config import load_settings
    from openai_client import OpenAIClient
    from ingestion import ingest_file
    from retrieval import HybridRetriever
    monkeypatch.setenv('QDRANT_PATH',str(tmp_path/'qdrant'))
    monkeypatch.setenv('EMBEDDING_PROVIDER','local_hash')
    provider=OpenAIClient(load_settings())
    retriever=HybridRetriever('finsight_chunks',str(tmp_path/'qdrant'),provider)
    retriever.index_chunks(ingest_file('evals/fixtures/Cedar.pdf'))
    retriever.close()
    app=AppTest.from_file('app.py',default_timeout=20).run()
    app.text_area(key='query').set_value('What is revenue in the report for 2025?')
    app.button(key='FormSubmitter:query_form-Ask').click().run()
    assert not app.exception
    response=app.session_state['history'][-1]['response']
    assert response['status']=='ok' and response['citations'][0]['page']==2
    assert any('Cedar.pdf, page 2' in e.value for e in app.markdown)
