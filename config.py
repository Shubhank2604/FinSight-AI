from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


DEFAULT_MODEL = "gpt-5.4-mini-2026-03-17"
# Responses/vision/Structured Outputs/web profiles checked on 2026-10-04.
MODEL_PROFILES = {
    "gpt-5.4-mini": "reasoning",
    DEFAULT_MODEL: "reasoning",
    "gpt-4.1-mini": "standard",
    "gpt-4.1-mini-2025-04-14": "standard",
}


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = field(default="", repr=False)
    openai_model: str = DEFAULT_MODEL
    openai_vision_model: str = ""
    openai_eval_model: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout: float = 30.0
    openai_max_retries: int = 2
    openai_max_output_tokens: int = 4096
    web_enabled: bool = False
    gemini_api_key: str = field(default="", repr=False)
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_provider: str = "local_hash"
    qdrant_collection: str = "finsight_chunks"
    qdrant_path: str = "data/index/qdrant"

    def __post_init__(self):
        for name in ("openai_model", "openai_vision_model", "openai_eval_model"):
            model = getattr(self, name)
            if (name == "openai_model" or model) and model not in MODEL_PROFILES:
                raise ValueError(f"Unsupported {name.upper()}. Supported models: {', '.join(MODEL_PROFILES)}.")
        if not math.isfinite(self.openai_timeout) or not 0 < self.openai_timeout <= 120:
            raise ValueError("OPENAI_TIMEOUT must be finite and between 0 and 120 seconds.")
        if type(self.openai_max_retries) is not int or not 0 <= self.openai_max_retries <= 3:
            raise ValueError("OPENAI_MAX_RETRIES must be an integer from 0 to 3.")
        if type(self.openai_max_output_tokens) is not int or not 128 <= self.openai_max_output_tokens <= 16384:
            raise ValueError("OPENAI_MAX_OUTPUT_TOKENS must be an integer from 128 to 16384.")
        if self.openai_embedding_model != 'text-embedding-3-small':
            raise ValueError('OPENAI_EMBEDDING_MODEL must be text-embedding-3-small; other spaces require separate validation.')
        if self.embedding_provider not in {"local_hash", "gemini", "openai"}:
            raise ValueError("EMBEDDING_PROVIDER must be local_hash, gemini or openai; changing embedding spaces requires a separate index.")

    @property
    def openai_configured(self) -> bool:
        key = self.openai_api_key.strip()
        return bool(key) and key not in {"your_openai_api_key_here", "replace_me"}


def _number(name, default, converter):
    try:
        return converter(os.getenv(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be a valid number.") from None


def load_settings() -> Settings:
    load_dotenv()
    web = os.getenv("OPENAI_WEB_ENABLED", "false").strip().lower()
    if web not in {"true", "false"}:
        raise ValueError("OPENAI_WEB_ENABLED must be true or false.")
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL).strip(),
        openai_vision_model=os.getenv("OPENAI_VISION_MODEL", "").strip(),
        openai_eval_model=os.getenv("OPENAI_EVAL_MODEL", "").strip(),
        openai_embedding_model=os.getenv('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small').strip(),
        openai_timeout=_number("OPENAI_TIMEOUT", 30, float),
        openai_max_retries=_number("OPENAI_MAX_RETRIES", 2, int),
        openai_max_output_tokens=_number("OPENAI_MAX_OUTPUT_TOKENS", 4096, int),
        web_enabled=web == "true",
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_embedding_model=os.getenv(
            "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"
        ).strip(),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "local_hash").strip().lower(),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "finsight_chunks").strip(),
        qdrant_path=os.getenv("QDRANT_PATH", "data/index/qdrant").strip(),
    )
