"""Independent hash, OpenAI and optional legacy Gemini embedding spaces."""

from __future__ import annotations

from config import Settings
from local_embeddings import hash_embedding


class EmbeddingError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class EmbeddingClient:
    def __init__(self, settings: Settings, embedding_dimensions: int = 768):
        self.settings = settings
        self.embedding_dimensions = embedding_dimensions
        self.query_embeddings: dict[str, list[float]] = {}
        self._client = None
        self.embedding_requests = []
        if (
            settings.embedding_provider == "openai"
            and not 1 <= embedding_dimensions <= 1536
        ):
            raise ValueError("OpenAI embedding dimensions must be between 1 and 1536.")

    @property
    def embedding_model(self):
        return {
            "local_hash": "blake2b-hash-v1",
            "openai": self.settings.openai_embedding_model,
            "gemini": self.settings.gemini_embedding_model,
        }[self.settings.embedding_provider]

    def _openai_embed(self, texts):
        import math
        import time

        import openai

        started = time.perf_counter()
        if not self.settings.openai_configured:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings.")
        if self._client is None:
            self._client = openai.OpenAI(
                api_key=self.settings.openai_api_key,
                timeout=self.settings.openai_timeout,
                max_retries=self.settings.openai_max_retries,
            )
        receipt = None
        budget = getattr(self, "budget", None)
        if budget:
            receipt = budget.reserve(
                self.embedding_model,
                sum(len(t.encode("utf-8")) for t in texts),
                attempts=self.settings.openai_max_retries + 1,
            )
        try:
            response = self._client.embeddings.create(
                model=self.embedding_model,
                input=texts,
                dimensions=self.embedding_dimensions,
                encoding_format="float",
            )
        except (openai.APIConnectionError, openai.APIStatusError) as exc:
            # Never propagate a provider body containing private request content.
            body = getattr(exc, "body", None) or {}
            detail = body.get("error", body) if isinstance(body, dict) else {}
            status = getattr(exc, "status_code", None)
            code = {
                401: "authentication",
                403: "permission",
                404: "model_unavailable",
                429: "rate_limit",
                400: "invalid_request",
            }.get(status, "provider_failure")
            if isinstance(detail, dict) and detail.get("code") == "insufficient_quota":
                code = "quota"
            elif isinstance(exc, openai.APITimeoutError):
                code = "timeout"
            elif isinstance(exc, openai.APIConnectionError):
                code = "connection"
            self.embedding_requests.append(
                {
                    "status": "failed",
                    "model": self.embedding_model,
                    "error_code": code,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            )
            raise EmbeddingError(
                code,
                f"OpenAI embedding request failed ({code}). Existing index data is preserved; resolve the provider issue and retry.",
            ) from None
        if budget:
            budget.settle(receipt, response.usage.model_dump())
        data = sorted(response.data, key=lambda item: item.index)
        vectors = [list(item.embedding) for item in data]
        if [item.index for item in data] != list(range(len(texts))) or any(
            len(v) != self.embedding_dimensions
            or not all(math.isfinite(x) for x in v)
            or not any(v)
            for v in vectors
        ):
            raise ValueError("OpenAI returned incompatible embedding vectors.")
        self.embedding_requests.append(
            {
                "status": "completed",
                "model": response.model,
                "dimensions": self.embedding_dimensions,
                "inputs": len(texts),
                "usage": response.usage.model_dump(),
                "request_id": getattr(response, "_request_id", None),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        )
        return vectors

    def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        if not texts:
            return []
        if self.settings.embedding_provider == "local_hash":
            return [hash_embedding(text, self.embedding_dimensions) for text in texts]
        if self.settings.embedding_provider == "openai":
            return self._openai_embed(texts)
        if not self.settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is required only for EMBEDDING_PROVIDER=gemini."
            )
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ValueError(
                "Existing Gemini embeddings require requirements-embeddings.txt. Install that optional dependency or use a separate local_hash index."
            ) from None
        if self._client is None:
            self._client = genai.Client(
                api_key=self.settings.gemini_api_key,
                http_options=types.HttpOptions(
                    timeout=30000, retry_options=types.HttpRetryOptions(attempts=1)
                ),
            )
        response = self._client.models.embed_content(
            model=self.settings.gemini_embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(
                output_dimensionality=self.embedding_dimensions, task_type=task
            ),
        )
        vectors = [list(e.values) for e in response.embeddings]
        if len(vectors) != len(texts) or any(
            len(v) != self.embedding_dimensions for v in vectors
        ):
            raise ValueError("Embedding provider returned incompatible vectors.")
        return vectors

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, query: str) -> list[float]:
        if query in self.query_embeddings:
            return self.query_embeddings[query]
        return self._embed([query], "RETRIEVAL_QUERY")[0]

    def embed_queries(self, queries: list[str]) -> None:
        unique = list(
            dict.fromkeys(q for q in queries if q not in self.query_embeddings)
        )
        for start in range(0, len(unique), 24):
            batch = unique[start : start + 24]
            self.query_embeddings.update(
                zip(batch, self._embed(batch, "RETRIEVAL_QUERY"), strict=True)
            )
