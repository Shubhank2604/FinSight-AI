from __future__ import annotations

import json
import re
import hashlib
import os
import math
from pathlib import Path

from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from embeddings import EmbeddingClient
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
        embedding_client: EmbeddingClient,
        vector_size: int = 768,
        ingestion_version: str = "financial-lines-v2",
    ) -> None:
        settings = getattr(embedding_client, "settings", None)
        identity = {"provider": getattr(settings, "embedding_provider", type(embedding_client).__name__), "model": getattr(settings, "gemini_embedding_model", "test"), "dimensions": vector_size, "ingestion": ingestion_version}
        if identity["provider"] == "local_hash":
            identity["model"] = "blake2b-hash-v1"
        elif identity['provider'] == 'openai':
            identity['model'] = settings.openai_embedding_model
        self.index_identity = identity
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
        self.collection_name = f"{collection_name}_{digest}"
        self.qdrant_path = Path(qdrant_path)
        self.catalog_path = self.qdrant_path.parent / f"{self.collection_name}.catalog.json"
        self.journal_path = self.qdrant_path.parent / f"{self.collection_name}.pending.json"
        self.embedding_client = embedding_client
        self.vector_size = vector_size
        self.storage_mode = "local"
        self.qdrant_path.mkdir(parents=True, exist_ok=True)
        try:
            self.client = QdrantClient(path=str(self.qdrant_path))
        except RuntimeError as exc:
            if "already accessed by another instance" not in str(exc):
                raise
            raise RuntimeError("Index storage is in use. Close the other FinSight process and retry, or use a different QDRANT_PATH.") from exc
        self.chunks: list[DocumentChunk] = []
        self._bm25: BM25Okapi | None = None
        try:
            self._ensure_collection()
            self._recover_transaction()
            self.load_catalog()
        except Exception:
            self.client.close()
            raise

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
        # Qdrant is authoritative. Reconstruct instead of trusting a stale JSON file.
        records = []
        offset = None
        while True:
            points, offset = self.client.scroll(collection_name=self.collection_name, offset=offset, limit=256, with_payload=True, with_vectors=False)
            records.extend(points)
            if offset is None:
                break
        self.chunks = sorted([DocumentChunk.model_validate(point.payload) for point in records if point.payload], key=lambda c: c.id)
        self._rebuild_bm25()
        self.save_catalog()

    def _atomic_json(self, path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)

    def _delete_ids(self, ids: list[str]) -> None:
        if ids:
            self.client.delete(collection_name=self.collection_name, points_selector=models.PointIdsList(points=ids), wait=True)

    def _recover_transaction(self) -> None:
        if not self.journal_path.exists():
            return
        journal = json.loads(self.journal_path.read_text(encoding="utf-8"))
        self._delete_ids(journal["old_ids"] if journal["phase"] == "ready" else journal["new_ids"])
        self.journal_path.unlink()

    def save_catalog(self) -> None:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"identity": self.index_identity, "chunks": [chunk.model_dump(mode="json") for chunk in self.chunks]}
        self._atomic_json(self.catalog_path, payload)

    def _rebuild_bm25(self) -> None:
        corpus = [_tokenize(chunk.content) for chunk in self.chunks]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def source_names(self) -> list[str]:
        return sorted({chunk.source_name for chunk in self.chunks})

    def _source_allowed(
        self, chunk: DocumentChunk, source_names: list[str] | None
    ) -> bool:
        return source_names is None or chunk.source_name in set(source_names)

    def index_chunks(self, chunks: list[DocumentChunk], batch_size: int = 24) -> int:
        if not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        ids = [c.id for c in chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate chunk IDs in upload")
        existing = {c.id: c for c in self.chunks}
        if any(c.id in existing and c != existing[c.id] for c in chunks):
            raise ValueError("An existing chunk ID has different content")
        documents_by_source = {}
        for c in chunks:
            documents_by_source.setdefault(c.source_name, set()).add(c.document_id)
        if any(len(documents) != 1 for documents in documents_by_source.values()):
            raise ValueError("One source name cannot represent multiple uploads in the same transaction")
        if not chunks:
            return 0

        existing_ids = {chunk.id for chunk in self.chunks}
        new_chunks = [chunk for chunk in chunks if chunk.id not in existing_ids]
        if not new_chunks:
            return 0

        old_ids = [c.id for c in self.chunks if c.source_name in documents_by_source and c.document_id not in documents_by_source[c.source_name]]
        journal = {"phase": "indexing", "new_ids": [c.id for c in new_chunks], "old_ids": old_ids}
        self._atomic_json(self.journal_path, journal)
        try:
            for start in range(0, len(new_chunks), batch_size):
                batch = new_chunks[start : start + batch_size]
                texts = [self._embedding_text(chunk) for chunk in batch]
                vectors = self.embedding_client.embed_texts(texts)
                if any(len(vector) != self.vector_size for vector in vectors):
                    raise ValueError("Embedding dimensions do not match the index identity")
                if any(not math.isfinite(value) for vector in vectors for value in vector):
                    raise ValueError("Embedding values must be finite")
                points = [models.PointStruct(id=chunk.id, vector=vector, payload=chunk.model_dump(mode="json")) for chunk, vector in zip(batch, vectors, strict=True)]
                self.client.upsert(collection_name=self.collection_name, points=points, wait=True)
            journal["phase"] = "ready"
            self._atomic_json(self.journal_path, journal)
            self._delete_ids(old_ids)
            self.load_catalog()
            self.journal_path.unlink()
        except Exception:
            self._recover_transaction()
            self.load_catalog()
            raise
        return len(new_chunks)

    def delete_document(self, document_id: str) -> None:
        ids = [c.id for c in self.chunks if c.document_id == document_id]
        journal = {"phase": "ready", "new_ids": [], "old_ids": ids}
        self._atomic_json(self.journal_path, journal)
        self._recover_transaction()
        self.load_catalog()

    def rebuild(self) -> int:
        # Re-embed in place. An embedding failure leaves all prior compatible points intact.
        chunks = list(self.chunks)
        for start in range(0, len(chunks), 24):
            batch = chunks[start:start+24]
            vectors = self.embedding_client.embed_texts([self._embedding_text(c) for c in batch])
            points = [models.PointStruct(id=c.id, vector=v, payload=c.model_dump(mode="json")) for c,v in zip(batch,vectors,strict=True)]
            self.client.upsert(collection_name=self.collection_name, points=points, wait=True)
        self.load_catalog()
        return len(chunks)

    def close(self) -> None:
        self.client.close()

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
        if not self.chunks or source_names == []:
            return []

        query_vector = self.embedding_client.embed_query(query)
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=limit,
            query_filter=models.Filter(must=[models.FieldCondition(key="source_name", match=models.MatchAny(any=source_names))]) if source_names is not None else None,
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
                hashlib.sha256(hit.chunk.content.encode()).hexdigest(),
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
