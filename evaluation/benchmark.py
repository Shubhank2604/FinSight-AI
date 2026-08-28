from __future__ import annotations

import json
import platform
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from evaluation.metrics import aggregate_metrics, evaluate_ranking, percentile
from local_embeddings import hash_embedding
from retrieval import HybridRetriever
from schemas import DocumentChunk, RetrievalHit


MODES = ("dense", "sparse", "hybrid")


class LocalEmbeddingClient:
    """Adapter that exercises production retrieval without API credentials."""

    def __init__(self, dimensions: int = 768) -> None:
        self.dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [hash_embedding(text, self.dimensions) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return hash_embedding(query, self.dimensions)


def load_dataset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    documents = payload.get("documents") or []
    cases = payload.get("cases") or []
    if not documents or not cases:
        raise ValueError("benchmark requires non-empty documents and cases")

    document_ids = [item["id"] for item in documents]
    case_ids = [item["id"] for item in cases]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("document chunk IDs must be unique")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("evaluation case IDs must be unique")

    for chunk_id in document_ids:
        UUID(chunk_id)

    known_ids = set(document_ids)
    for case in cases:
        relevant_ids = set(case.get("relevant_chunk_ids") or [])
        if not relevant_ids:
            raise ValueError(f"case {case['id']} has no relevance labels")
        unknown = relevant_ids - known_ids
        if unknown:
            raise ValueError(f"case {case['id']} references unknown chunks: {sorted(unknown)}")
    return payload


def _searchers(
    retriever: HybridRetriever, top_k: int
) -> dict[str, Callable[[str], list[RetrievalHit]]]:
    return {
        "dense": lambda query: retriever.dense_search(query, limit=top_k),
        "sparse": lambda query: retriever.sparse_search(query, limit=top_k),
        "hybrid": lambda query: retriever.hybrid_search(
            query,
            limit=top_k,
            dense_limit=max(top_k * 2, 8),
            sparse_limit=max(top_k * 2, 8),
        ),
    }


def run_benchmark(dataset_path: Path, top_k: int = 3) -> dict[str, Any]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    dataset = load_dataset(dataset_path)
    chunks = [DocumentChunk.model_validate(item) for item in dataset["documents"]]

    with tempfile.TemporaryDirectory(prefix="finsight-eval-") as temp_dir:
        retriever = HybridRetriever(
            collection_name="finsight_eval",
            qdrant_path=str(Path(temp_dir) / "qdrant"),
            gemini=LocalEmbeddingClient(),  # type: ignore[arg-type]
        )
        retriever.index_chunks(chunks)
        searchers = _searchers(retriever, top_k)
        per_mode: dict[str, list[dict[str, Any]]] = {mode: [] for mode in MODES}

        for case in dataset["cases"]:
            relevant_ids = set(case["relevant_chunk_ids"])
            for mode, search in searchers.items():
                started = time.perf_counter()
                hits = search(case["query"])
                latency_ms = (time.perf_counter() - started) * 1000.0
                retrieved_ids = [hit.chunk.id for hit in hits]
                metrics = evaluate_ranking(retrieved_ids, relevant_ids, top_k)
                per_mode[mode].append(
                    {
                        "case_id": case["id"],
                        "category": case["category"],
                        "query": case["query"],
                        "relevant_chunk_ids": sorted(relevant_ids),
                        "retrieved_chunk_ids": retrieved_ids,
                        "latency_ms": round(latency_ms, 3),
                        "metrics": metrics.as_dict(),
                        "_metrics": metrics,
                    }
                )
        retriever.client.close()

    summaries = {}
    serializable_cases = {}
    for mode, results in per_mode.items():
        latencies = [item["latency_ms"] for item in results]
        summaries[mode] = {
            **aggregate_metrics([item["_metrics"] for item in results]),
            "latency_ms_p50": round(percentile(latencies, 50), 3),
            "latency_ms_p95": round(percentile(latencies, 95), 3),
        }
        serializable_cases[mode] = [
            {key: value for key, value in item.items() if key != "_metrics"}
            for item in results
        ]

    return {
        "benchmark": dataset.get("name", dataset_path.stem),
        "dataset_version": dataset.get("version", "unknown"),
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "embedding_provider": "local_hash",
            "network_access": False,
        },
        "top_k": top_k,
        "document_count": len(chunks),
        "case_count": len(dataset["cases"]),
        "summary": summaries,
        "cases": serializable_cases,
    }


def markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        f"Retrieval benchmark: {report['benchmark']} (v{report['dataset_version']})",
        f"Cases={report['case_count']} | Chunks={report['document_count']} | K={report['top_k']}",
        "",
        "| Mode | Precision@K | Recall@K | Hit rate@K | MRR@K | nDCG@K | p50 ms | p95 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in MODES:
        metrics = report["summary"][mode]
        lines.append(
            "| {mode} | {precision_at_k:.3f} | {recall_at_k:.3f} | "
            "{hit_rate_at_k:.3f} | {reciprocal_rank:.3f} | {ndcg_at_k:.3f} | "
            "{latency_ms_p50:.3f} | {latency_ms_p95:.3f} |".format(
                mode=mode, **metrics
            )
        )
    return "\n".join(lines)
