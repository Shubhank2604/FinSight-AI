"""Local embedding contracts; unit tests never download models or call an API."""
from types import SimpleNamespace

import numpy as np
import pytest

from config import Settings
from embeddings import EmbeddingClient, EmbeddingError
from minilm_embeddings import DIMENSIONS, MAX_TOKENS, MiniLMEncoder, REVISION
from retrieval import HybridRetriever


def test_default_local_embeddings_need_no_openai_key_and_cache_queries(monkeypatch):
    calls = []
    class Encoder:
        def encode(self, texts):
            calls.append(texts)
            return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts]
    monkeypatch.setattr('minilm_embeddings.load_encoder', lambda cache: Encoder())
    monkeypatch.setattr(EmbeddingClient, '_openai_embed',
                        lambda *args: pytest.fail('Embedding must not call OpenAI'))
    client = EmbeddingClient(Settings())
    assert client.embedding_dimensions == 384
    assert len(client.embed_texts(['Annual revenue grew.'])[0]) == 384
    first = client.embed_query('sales growth')
    assert client.embed_query('sales growth') == first
    assert len(calls) == 2
    assert all(r['local_inference'] for r in client.embedding_requests)
    assert client._client is None


def test_minilm_has_separate_pinned_collection_and_rejects_wrong_dimensions(tmp_path):
    local = HybridRetriever('test', str(tmp_path / 'qdrant'), EmbeddingClient(Settings()))
    try:
        identity, name = local.index_identity, local.collection_name
        assert local.vector_size == 384
        assert identity['revision'] == REVISION
        assert identity['max_tokens'] == MAX_TOKENS
    finally:
        local.close()
    old = HybridRetriever('test', str(tmp_path / 'qdrant'),
                          EmbeddingClient(Settings(embedding_provider='local_hash')))
    try:
        assert old.collection_name != name and old.vector_size == 768
    finally:
        old.close()
    with pytest.raises(ValueError, match='384'):
        EmbeddingClient(Settings(), embedding_dimensions=768)


def test_long_chunks_encode_every_token_instead_of_truncating():
    encoder = MiniLMEncoder.__new__(MiniLMEncoder)
    encoder.cls, encoder.sep, encoder.pad = 101, 102, 0
    encoder.input_names = {'input_ids', 'attention_mask', 'token_type_ids'}
    encoder.tokenizer = SimpleNamespace(encode=lambda text, **kw:
                                       SimpleNamespace(ids=[int(t) for t in text.split()]))
    seen = []
    widths = []
    def run(outputs, inputs):
        ids = inputs['input_ids']
        widths.append(ids.shape[1])
        vectors = np.zeros((*ids.shape, DIMENSIONS))
        for row in range(len(ids)):
            length = int(inputs['attention_mask'][row].sum())
            seen.extend(ids[row, 1:length - 1].tolist())
            for col, token in enumerate(ids[row]):
                vectors[row, col, token % DIMENSIONS] = 1
        return [vectors]
    encoder.session = SimpleNamespace(run=run)
    text = ' '.join(['1000'] * 600 + ['2000'])
    vector = np.asarray(encoder.encode([text])[0])
    assert seen == [1000] * 600 + [2000]
    assert max(widths) <= MAX_TOKENS
    assert vector[2000 % DIMENSIONS] > 0
    assert np.isfinite(vector).all() and np.linalg.norm(vector) == pytest.approx(1)


def test_local_model_failure_does_not_fall_back_to_remote(monkeypatch):
    def fail(cache):
        raise RuntimeError('private diagnostic')
    monkeypatch.setattr('minilm_embeddings.load_encoder', fail)
    with pytest.raises(EmbeddingError, match='Local MiniLM') as error:
        EmbeddingClient(Settings()).embed_query('revenue')
    assert 'private diagnostic' not in str(error.value)


def test_indexing_rejects_cloud_embeddings_before_any_api_request(tmp_path, monkeypatch):
    from index_uploads import index_folder
    monkeypatch.setattr('index_uploads.load_settings', lambda: Settings(embedding_provider='openai'))
    with pytest.raises(ValueError, match='local embeddings'):
        index_folder(tmp_path)
