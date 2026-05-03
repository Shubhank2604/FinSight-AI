from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from config import load_settings
from gemini_client import GeminiClient
from ingestion import ingest_file
from retrieval import HybridRetriever


SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}


def index_folder(folder: Path, embedding_provider: str | None = None) -> tuple[int, int, int]:
    settings = load_settings()
    if embedding_provider:
        settings = replace(settings, embedding_provider=embedding_provider)
    if not settings.gemini_configured:
        raise RuntimeError("GEMINI_API_KEY is required for embedding and indexing.")

    gemini = GeminiClient(settings)
    retriever = HybridRetriever(
        collection_name=settings.qdrant_collection,
        qdrant_path=settings.qdrant_path,
        gemini=gemini,
    )

    files = [
        path
        for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    extracted_count = 0
    chunks = []

    for path in files:
        document_chunks = ingest_file(path, source_name=path.name)
        extracted_count += len(document_chunks)
        chunks.extend(document_chunks)
        print(f"Extracted {len(document_chunks):>4} chunks from {path.name}")

    indexed_count = retriever.index_chunks(chunks)
    print(f"Catalog now contains {len(retriever.chunks)} chunks")
    return len(files), extracted_count, indexed_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Index uploaded FinSight AI documents.")
    parser.add_argument(
        "--folder",
        default="data/uploads/originals",
        help="Folder containing PDFs/images to index.",
    )
    parser.add_argument(
        "--embedding-provider",
        choices=["gemini", "local_hash"],
        default=None,
        help="Use Gemini embeddings or local deterministic hash embeddings.",
    )
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        raise FileNotFoundError(folder)

    file_count, extracted_count, indexed_count = index_folder(
        folder, embedding_provider=args.embedding_provider
    )
    print(
        f"Done. Files={file_count}, extracted_chunks={extracted_count}, "
        f"newly_indexed={indexed_count}"
    )


if __name__ == "__main__":
    main()
