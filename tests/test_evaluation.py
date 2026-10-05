from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import Settings
from evaluation.benchmark import load_dataset, run_benchmark
from evaluation.metrics import aggregate_metrics, evaluate_ranking, percentile
from openai_client import OpenAIClient
from index_uploads import index_folder


def test_ranking_metrics_reward_early_relevant_results() -> None:
    metrics = evaluate_ranking(
        retrieved_ids=["relevant-a", "noise", "relevant-b"],
        relevant_ids={"relevant-a", "relevant-b"},
        top_k=3,
    )

    assert metrics.precision_at_k == pytest.approx(2 / 3)
    assert metrics.recall_at_k == 1.0
    assert metrics.hit_rate_at_k == 1.0
    assert metrics.reciprocal_rank == 1.0
    assert 0.0 < metrics.ndcg_at_k <= 1.0


def test_ranking_metrics_handle_complete_miss() -> None:
    metrics = evaluate_ranking(["noise"], {"relevant"}, top_k=3)

    assert metrics.precision_at_k == 0.0
    assert metrics.recall_at_k == 0.0
    assert metrics.hit_rate_at_k == 0.0
    assert metrics.reciprocal_rank == 0.0
    assert metrics.ndcg_at_k == 0.0


def test_aggregate_and_percentile_are_deterministic() -> None:
    first = evaluate_ranking(["a"], {"a"}, top_k=1)
    second = evaluate_ranking(["b"], {"a"}, top_k=1)

    assert aggregate_metrics([first, second])["recall_at_k"] == 0.5
    assert percentile([1.0, 3.0, 2.0], 50) == 2.0
    assert percentile([1.0, 3.0], 50) == 2.0


def test_dataset_validation_rejects_unknown_relevance_label(tmp_path: Path) -> None:
    dataset = {
        "documents": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "document_id": "doc",
                "source_name": "doc.pdf",
                "type": "text",
                "content": "revenue",
            }
        ],
        "cases": [
            {
                "id": "case",
                "category": "test",
                "query": "revenue",
                "relevant_chunk_ids": [
                    "00000000-0000-0000-0000-000000000002"
                ],
            }
        ],
    }
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown chunks"):
        load_dataset(path)


def test_checked_in_benchmark_runs_without_network_or_api_key() -> None:
    report = run_benchmark(Path("evals/retrieval_benchmark.json"), top_k=3)

    assert report["case_count"] == 18
    assert report["document_count"] == 18
    assert report["environment"]["embedding_provider"] == "local_hash"
    assert report["environment"]["network_access"] is False
    assert set(report["summary"]) == {"dense", "sparse", "hybrid"}
    assert report["summary"]["hybrid"]["recall_at_k"] >= 0.9


def test_local_hash_embeddings_do_not_require_gemini_key() -> None:
    settings = Settings(
        gemini_api_key="",
        gemini_embedding_model="gemini-embedding-test",
        embedding_provider="local_hash",
        qdrant_collection="test",
        qdrant_path="unused",
    )

    client = OpenAIClient(settings, embedding_dimensions=16)

    assert len(client.embed_query("retirement inflation")) == 16
    with pytest.raises(ValueError, match="generative operations"):
        client._require_client()


def test_local_hash_indexing_accepts_empty_folder_without_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("QDRANT_PATH", str(tmp_path / "qdrant"))

    assert index_folder(uploads, embedding_provider="local_hash") == (0, 0, 0)


def test_malformed_pdf_indexing_releases_storage(tmp_path, monkeypatch):
    from embeddings import EmbeddingClient
    from retrieval import HybridRetriever
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    (uploads / 'bad.pdf').write_bytes(b'not a PDF')
    settings = Settings(qdrant_path=str(tmp_path / 'qdrant'))
    monkeypatch.setattr('index_uploads.load_settings', lambda: settings)
    with pytest.raises(Exception):
        index_folder(uploads, embedding_provider='local_hash')
    restarted = HybridRetriever(settings.qdrant_collection, settings.qdrant_path, EmbeddingClient(settings))
    try:
        assert restarted.chunks == []
    finally:
        restarted.close()
