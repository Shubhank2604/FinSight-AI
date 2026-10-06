"""Upload lifecycle and automatic RAG policy, with no paid provider requests."""
from io import BytesIO
from pathlib import Path

from config import Settings
from openai_client import OpenAIClient
from retrieval import HybridRetriever
from uploads import index_upload, remove_managed_upload


class Uploaded(BytesIO):
    def __init__(self, name, data):
        super().__init__(data)
        self.name = name


def ui_setup(tmp_path, monkeypatch, files):
    import streamlit as st
    import uploads
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv('QDRANT_PATH', str(tmp_path / 'qdrant'))
    monkeypatch.setenv('EMBEDDING_PROVIDER', 'local_hash')
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-test')
    calls = []
    def upload(name, data, retriever, directory):
        calls.append(name)
        return index_upload(name, data, retriever, tmp_path / 'originals')
    monkeypatch.setattr(uploads, 'index_upload', upload)
    monkeypatch.setattr(uploads, 'remove_managed_upload',
                        lambda identity, directory: remove_managed_upload(
                            identity, tmp_path / 'originals', tmp_path / 'images'))
    monkeypatch.setattr(st, 'file_uploader',
                        lambda *args, **kwargs: files if kwargs['key'] == 'uploads_0' else [])
    return AppTest.from_file('app.py', default_timeout=20), calls


def test_automatic_upload_reruns_and_new_document_scope(tmp_path, monkeypatch):
    files = [Uploaded('Cedar.pdf', Path('evals/fixtures/Cedar.pdf').read_bytes())]
    app, calls = ui_setup(tmp_path, monkeypatch, files)
    app.run()
    assert not app.exception and not app.error
    assert calls == ['Cedar.pdf']
    assert app.multiselect(key='active_documents').value == ['Cedar.pdf']
    assert not app.tabs
    assert not any(item.label in {'Index uploads', 'Use OpenAI for document explanations',
                                  'Retrieval method'} for group in (app.button, app.checkbox, app.selectbox)
                   for item in group)
    app.run()
    assert calls == ['Cedar.pdf']
    # Preserve an explicit deselection, while newly uploaded documents join the scope.
    app.multiselect(key='active_documents').set_value([]).run()
    files.append(Uploaded('Elm.pdf', Path('evals/fixtures/Elm.pdf').read_bytes()))
    app.run()
    assert not app.exception
    assert calls == ['Cedar.pdf', 'Elm.pdf']
    assert app.multiselect(key='active_documents').value == ['Elm.pdf']


def test_specific_file_deletion_does_not_restore_upload(tmp_path, monkeypatch):
    files = [Uploaded(name, Path('evals/fixtures', name).read_bytes())
             for name in ['Cedar.pdf', 'Elm.pdf']]
    app, calls = ui_setup(tmp_path, monkeypatch, files)
    app.run()
    next(item for item in app.selectbox if item.label == 'Delete a document').select('Cedar.pdf')
    next(item for item in app.button if item.label == 'Delete file').click().run()
    assert not app.exception and not app.error
    assert app.multiselect(key='active_documents').options == ['Elm.pdf']
    assert len(list((tmp_path / 'originals').glob('*'))) == 1
    assert calls == ['Cedar.pdf', 'Elm.pdf']
    app.run()
    assert calls == ['Cedar.pdf', 'Elm.pdf']
    assert app.multiselect(key='active_documents').options == ['Elm.pdf']


def test_same_filename_keeps_both_documents_and_skips_reembedding(tmp_path):
    provider = OpenAIClient(Settings(embedding_provider='local_hash'))
    retriever = HybridRetriever('uploads', str(tmp_path / 'qdrant'), provider)
    try:
        a = Path('evals/fixtures/Cedar.pdf').read_bytes()
        b = Path('evals/fixtures/Elm.pdf').read_bytes()
        assert index_upload('report.pdf', a, retriever, tmp_path / 'originals') > 0
        assert index_upload('report.pdf', b, retriever, tmp_path / 'originals') > 0
        assert len(retriever.source_names()) == 2
        assert len({c.document_id for c in retriever.chunks}) == 2
        assert index_upload('report.pdf', b, retriever, tmp_path / 'originals') == 0
    finally:
        retriever.close()


def test_upload_failure_requires_explicit_retry(tmp_path, monkeypatch):
    import uploads
    files = [Uploaded('Cedar.pdf', Path('evals/fixtures/Cedar.pdf').read_bytes())]
    app, calls = ui_setup(tmp_path, monkeypatch, files)
    wrapped = uploads.index_upload
    attempts = []
    def interrupted(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError('private diagnostic')
        return wrapped(*args)
    monkeypatch.setattr(uploads, 'index_upload', interrupted)
    app.run()
    assert app.error and 'private diagnostic' not in app.error[0].value
    assert any(item.label == 'Retry failed uploads' for item in app.button)
    app.run()
    assert len(attempts) == 1
    next(item for item in app.button if item.label == 'Retry failed uploads').click().run()
    assert not app.exception and not app.error
    assert len(attempts) == 2 and calls == ['Cedar.pdf']


def test_deletion_preserves_unrelated_originals(tmp_path):
    import hashlib
    from uploads import save_upload
    data = Path('evals/fixtures/Cedar.pdf').read_bytes()
    other = Path('evals/fixtures/Elm.pdf').read_bytes()
    identity = hashlib.sha256(data).hexdigest()
    target = save_upload('Cedar.pdf', data, tmp_path / 'originals')
    unrelated = save_upload('Elm.pdf', other, tmp_path / 'originals')
    assert remove_managed_upload(identity, tmp_path / 'originals', tmp_path / 'images') == 1
    assert not target.exists() and unrelated.read_bytes() == other


def test_financial_reranking_prefers_requested_period_and_metric(tmp_path):
    from schemas import ChunkType, DocumentChunk, RetrievalHit
    from uuid import uuid4
    provider = OpenAIClient(Settings(embedding_provider='local_hash'))
    retriever = HybridRetriever('ranking', str(tmp_path / 'qdrant'), provider)
    try:
        texts = ['Company: Cedar\nPeriod: 2024\nRevenue: USD 100',
                 'Company: Cedar\nPeriod: 2025\nNet income: USD 24',
                 'Company: Cedar\nPeriod: 2025\nNet sales: USD 120']
        hits = [RetrievalHit(chunk=DocumentChunk(
            id=str(uuid4()), document_id='report', source_name='report.pdf',
            type=ChunkType.TEXT, content=text), score=.9, source='hybrid') for text in texts]
        selected = retriever.select_context_hits('What is revenue for Cedar in the report for 2025?', hits)
        assert selected[0].chunk.content == texts[2]
        assert len(selected) == 3
    finally:
        retriever.close()
