from __future__ import annotations

import json
import re
from pathlib import Path

from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from gemini_client import GeminiClient
from schemas import ChunkType, DocumentChunk, RetrievalHit


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9][a-zA-Z0-9._%-]*", text.lower())


def _query_wants_tables(query: str) -> bool:
    terms = {
        "revenue",
        "income",
        "cash",
        "flow",
        "margin",
        "ratio",
        "allocation",
        "holding",
        "portfolio",
        "statement",
        "table",
        "tax",
        "amount",
        "value",
        "price",
    }
    tokens = set(_tokenize(query))
    return bool(tokens.intersection(terms))


class HybridRetriever:
    def __init__(
        self,
        collection_name: str,
        qdrant_path: str,
        gemini: GeminiClient,
        vector_size: int = 768,
    ) -> None:
        self.collection_name = collection_name
        self.qdrant_path = Path(qdrant_path)
        self.catalog_path = self.qdrant_path.parent / "chunks.json"
        self.gemini = gemini
        self.vector_size = vector_size
        self.storage_mode = "local"
        self.qdrant_path.mkdir(parents=True, exist_ok=True)
        try:
            self.client = QdrantClient(path=str(self.qdrant_path))
        except RuntimeError as exc:
            if "already accessed by another instance" not in str(exc):
                raise
            self.storage_mode = "memory"
            self.client = QdrantClient(location=":memory:")
        self.chunks: list[DocumentChunk] = []
        self._bm25: BM25Okapi | None = None
        self._ensure_collection()
        self.load_catalog()

    def _ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=self.vector_size,
                distance=models.Distance.COSINE,
            ),
        )

    def load_catalog(self) -> None:
        if not self.catalog_path.exists():
            self.chunks = []
            self._bm25 = None
            return
        raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.chunks = [DocumentChunk.model_validate(item) for item in raw]
        self._rebuild_bm25()

    def save_catalog(self) -> None:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [chunk.model_dump(mode="json") for chunk in self.chunks]
        self.catalog_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _rebuild_bm25(self) -> None:
        corpus = [_tokenize(chunk.content) for chunk in self.chunks]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def source_names(self) -> list[str]:
        return sorted({chunk.source_name for chunk in self.chunks})

    def _source_allowed(
        self, chunk: DocumentChunk, source_names: list[str] | None
    ) -> bool:
        return not source_names or chunk.source_name in set(source_names)

    def index_chunks(self, chunks: list[DocumentChunk], batch_size: int = 24) -> int:
        if not chunks:
            return 0

        existing_ids = {chunk.id for chunk in self.chunks}
        new_chunks = [chunk for chunk in chunks if chunk.id not in existing_ids]
        if not new_chunks:
            return 0

        for start in range(0, len(new_chunks), batch_size):
            batch = new_chunks[start : start + batch_size]
            texts = [self._embedding_text(chunk) for chunk in batch]
            vectors = self.gemini.embed_texts(texts)
            points = [
                models.PointStruct(
                    id=chunk.id,
                    vector=vector,
                    payload=chunk.model_dump(mode="json"),
                )
                for chunk, vector in zip(batch, vectors, strict=True)
            ]
            self.client.upsert(collection_name=self.collection_name, points=points)

        self.chunks.extend(new_chunks)
        self._rebuild_bm25()
        self.save_catalog()
        return len(new_chunks)

    def _embedding_text(self, chunk: DocumentChunk) -> str:
        if chunk.type == ChunkType.TABLE:
            prefix = "Financial table chunk"
        elif chunk.type == ChunkType.IMAGE:
            prefix = "Financial image or screenshot reference"
        else:
            prefix = "Financial document text chunk"

        location = f"source={chunk.source_name}"
        if chunk.page is not None:
            location += f" page={chunk.page}"
        if chunk.section:
            location += f" section={chunk.section}"
        return f"{prefix}\n{location}\n{chunk.content}"

    def dense_search(
        self,
        query: str,
        limit: int = 8,
        source_names: list[str] | None = None,
    ) -> list[RetrievalHit]:
        if not self.chunks:
            return []

        query_vector = self.gemini.embed_query(query)
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=max(limit, 40) if source_names else limit,
            with_payload=True,
        )
        hits = []
        for point in response.points:
            if not point.payload:
                continue
            chunk = DocumentChunk.model_validate(point.payload)
            if not self._source_allowed(chunk, source_names):
                continue
            hits.append(
                RetrievalHit(
                    chunk=chunk,
                    score=round(max(min(float(point.score), 1.0), 0.0), 4),
                    source="dense",
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def sparse_search(
        self,
        query: str,
        limit: int = 8,
        source_names: list[str] | None = None,
    ) -> list[RetrievalHit]:
        if self._bm25 is None:
            return []

        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        max_score = float(ranked[0][1]) if ranked else 0.0
        hits = []
        for index, score in ranked:
            if score <= 0:
                continue
            chunk = self.chunks[index]
            if not self._source_allowed(chunk, source_names):
                continue
            normalised = float(score / max_score) if max_score else 0.0
            hits.append(
                RetrievalHit(
                    chunk=chunk,
                    score=round(normalised, 4),
                    source="sparse",
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def hybrid_search(
        self,
        query: str,
        limit: int = 8,
        dense_limit: int = 12,
        sparse_limit: int = 12,
        rrf_k: int = 60,
        source_names: list[str] | None = None,
    ) -> list[RetrievalHit]:
        diagnostics = self.search_with_diagnostics(
            query=query,
            limit=limit,
            dense_limit=dense_limit,
            sparse_limit=sparse_limit,
            rrf_k=rrf_k,
            source_names=source_names,
        )
        return diagnostics["hybrid"]

    def select_context_hits(
        self,
        query: str,
        hits: list[RetrievalHit],
        limit: int = 8,
        include_images: bool = False,
    ) -> list[RetrievalHit]:
        if not hits:
            return []

        query_tokens = set(_tokenize(query))
        wants_tables = _query_wants_tables(query)
        ranked = []
        for hit in hits:
            chunk_tokens = set(_tokenize(hit.chunk.content))
            overlap = len(query_tokens.intersection(chunk_tokens)) / max(len(query_tokens), 1)
            type_boost = 0.0
            if hit.chunk.type == ChunkType.TABLE and wants_tables:
                type_boost = 0.18
            elif hit.chunk.type == ChunkType.TEXT:
                type_boost = 0.08
            elif hit.chunk.type == ChunkType.IMAGE and not include_images:
                type_boost = -0.35

            score = hit.score + overlap + type_boost
            ranked.append((score, hit))

        selected = []
        seen_keys: set[tuple[str, int | None, str]] = set()
        for _, hit in sorted(ranked, key=lambda item: item[0], reverse=True):
            if hit.chunk.type == ChunkType.IMAGE and not include_images:
                continue
            key = (
                hit.chunk.source_name,
                hit.chunk.page,
                hit.chunk.content[:120],
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            selected.append(hit)
            if len(selected) >= limit:
                break

        return selected

    def search_with_diagnostics(
        self,
        query: str,
        limit: int = 8,
        dense_limit: int = 12,
        sparse_limit: int = 12,
        rrf_k: int = 60,
        source_names: list[str] | None = None,
    ) -> dict[str, list[RetrievalHit]]:
        dense_hits = self.dense_search(
            query, limit=dense_limit, source_names=source_names
        )
        sparse_hits = self.sparse_search(
            query, limit=sparse_limit, source_names=source_names
        )

        chunk_by_id: dict[str, DocumentChunk] = {}
        fused_scores: dict[str, float] = {}

        for result_set in (dense_hits, sparse_hits):
            for rank, hit in enumerate(result_set, start=1):
                chunk_by_id[hit.chunk.id] = hit.chunk
                fused_scores[hit.chunk.id] = fused_scores.get(hit.chunk.id, 0.0) + (
                    1.0 / (rrf_k + rank)
                )

        if not fused_scores:
            return {"dense": dense_hits, "sparse": sparse_hits, "hybrid": []}

        max_score = max(fused_scores.values())
        ranked_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)[:limit]
        hits = []
        for chunk_id in ranked_ids:
            chunk = chunk_by_id[chunk_id]
            score = fused_scores[chunk_id] / max_score
            if chunk.type == ChunkType.IMAGE:
                score *= 0.75
            hits.append(
                RetrievalHit(
                    chunk=chunk,
                    score=round(score, 4),
                    source="hybrid",
                )
            )
        return {
            "dense": dense_hits,
            "sparse": sparse_hits,
            "hybrid": sorted(hits, key=lambda hit: hit.score, reverse=True),
        }
