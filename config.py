from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _normalise_model_name(model_name: str) -> str:
    aliases = {
        "gemini-3-flash": "gemini-3-flash-preview",
    }
    return aliases.get(model_name.strip(), model_name.strip())


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_text_model: str
    gemini_embedding_model: str
    gemini_web_grounding_model: str
    embedding_provider: str
    qdrant_collection: str
    qdrant_path: str

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)


def load_settings() -> Settings:
    load_dotenv()

    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_text_model=_normalise_model_name(
            os.getenv("GEMINI_TEXT_MODEL", "gemini-3-flash-preview")
        ),
        gemini_embedding_model=os.getenv(
            "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"
        ).strip(),
        gemini_web_grounding_model=_normalise_model_name(
            os.getenv("GEMINI_WEB_GROUNDING_MODEL", "gemini-2.5-flash")
        ),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "gemini").strip().lower(),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "finsight_chunks").strip(),
        qdrant_path=os.getenv("QDRANT_PATH", "data/index/qdrant").strip(),
    )
