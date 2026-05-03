from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import fitz
import pdfplumber

from ingestion.chunker import chunk_text, detect_section, table_to_text
from schemas import ChunkType, DocumentChunk


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _chunk_id(document_id: str, kind: str, page: int | None, index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{kind}:{page}:{index}"))


def _extract_pdf_images(path: Path, document_id: str, source_name: str) -> list[DocumentChunk]:
    image_dir = Path("data/uploads/extracted_images") / document_id
    image_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[DocumentChunk] = []

    with fitz.open(path) as doc:
        for page_index, page in enumerate(doc, start=1):
            for image_index, image_info in enumerate(page.get_images(full=True), start=1):
                xref = image_info[0]
                extracted = doc.extract_image(xref)
                extension = extracted.get("ext", "png")
                image_path = image_dir / f"page_{page_index}_image_{image_index}.{extension}"
                image_path.write_bytes(extracted["image"])
                chunks.append(
                    DocumentChunk(
                        id=_chunk_id(document_id, "image", page_index, image_index),
                        document_id=document_id,
                        source_name=source_name,
                        type=ChunkType.IMAGE,
                        content=(
                            f"Extracted image from {source_name}, page {page_index}, "
                            f"image {image_index}."
                        ),
                        page=page_index,
                        section=None,
                        metadata={"image_path": str(image_path)},
                    )
                )
    return chunks


def _ingest_pdf(path: Path, document_id: str, source_name: str) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    chunk_index = 0

    with pdfplumber.open(path) as pdf:
        current_section: str | None = None
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            current_section = detect_section(text, current_section)

            for text_chunk in chunk_text(text):
                chunk_index += 1
                chunks.append(
                    DocumentChunk(
                        id=_chunk_id(document_id, "text", page_index, chunk_index),
                        document_id=document_id,
                        source_name=source_name,
                        type=ChunkType.TEXT,
                        content=text_chunk,
                        page=page_index,
                        section=current_section,
                    )
                )

            for table_index, table in enumerate(page.extract_tables() or [], start=1):
                table_text = table_to_text(table)
                if not table_text.strip():
                    continue
                chunk_index += 1
                chunks.append(
                    DocumentChunk(
                        id=_chunk_id(document_id, "table", page_index, chunk_index),
                        document_id=document_id,
                        source_name=source_name,
                        type=ChunkType.TABLE,
                        content=table_text,
                        page=page_index,
                        section=current_section,
                        metadata={"table_index": table_index, "rows": table},
                    )
                )

    chunks.extend(_extract_pdf_images(path, document_id, source_name))
    return chunks


def _ingest_image(path: Path, document_id: str, source_name: str) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            id=_chunk_id(document_id, "image", None, 1),
            document_id=document_id,
            source_name=source_name,
            type=ChunkType.IMAGE,
            content=f"Uploaded image or screenshot: {source_name}.",
            page=None,
            section=None,
            metadata={"image_path": str(path)},
        )
    ]


def ingest_file(path: str | Path, source_name: str | None = None) -> list[DocumentChunk]:
    file_path = Path(path)
    source = source_name or file_path.name
    document_id = _file_sha256(file_path)
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _ingest_pdf(file_path, document_id, source)
    if suffix in {".png", ".jpg", ".jpeg"}:
        return _ingest_image(file_path, document_id, source)
    raise ValueError(f"Unsupported file type: {suffix}")
