from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

import pdfplumber
import pymupdf as fitz
from PIL import Image

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


def _extract_pdf_images(
    path: Path, document_id: str, source_name: str
) -> list[DocumentChunk]:
    image_dir = Path("data/uploads/extracted_images") / document_id
    image_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[DocumentChunk] = []

    with fitz.open(path) as doc:
        for page_index, page in enumerate(doc, start=1):
            for image_index, image_info in enumerate(
                page.get_images(full=True), start=1
            ):
                xref = image_info[0]
                extracted = doc.extract_image(xref)
                extension = extracted.get("ext", "png")
                image_path = (
                    image_dir / f"page_{page_index}_image_{image_index}.{extension}"
                )
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
    acquisition = {}
    with fitz.open(path) as document:
        try:
            subject = json.loads(document.metadata.get("subject") or "{}")
            if isinstance(subject, dict):
                acquisition = {
                    k: subject[k]
                    for k in ["source_url", "original_page", "original_sha256"]
                    if k in subject
                }
        except (ValueError, TypeError):
            pass

    with pdfplumber.open(path) as pdf:
        current_section: str | None = None
        # Recognizable issuer title is document metadata, never evaluation labels.
        issuer_text = "\n".join((p.extract_text() or "") for p in pdf.pages[:3])
        document_entity = (
            "United States Mint"
            if re.search(r"UNITED STATES MINT", issuer_text, re.I)
            else None
        )
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            metadata = {"original_path": str(path), **acquisition}
            if document_entity:
                metadata["entity"] = document_entity
            for label, key, pattern in [
                ("Company", "entity", r"[^\n]+"),
                ("Period", "period", r"20\d{2}"),
                ("Currency", "currency", r"[A-Z]{3}"),
                ("Units", "units", r"million|billion|thousand"),
            ]:
                match = re.search(rf"{label}\s*:\s*({pattern})", text, re.I)
                if match:
                    metadata[key] = (
                        int(match.group(1))
                        if key == "period"
                        else match.group(1).strip()
                    )
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
                        metadata=metadata,
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
                        metadata={
                            **metadata,
                            "table_index": table_index,
                            "rows": table,
                        },
                    )
                )

    chunks.extend(_extract_pdf_images(path, document_id, source_name))
    return chunks


def _ingest_image(
    path: Path, document_id: str, source_name: str
) -> list[DocumentChunk]:
    with Image.open(path) as image:
        image.verify()
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


def ingest_file(
    path: str | Path, source_name: str | None = None
) -> list[DocumentChunk]:
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError("Input file is missing")
    if file_path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Input file exceeds the 20 MB local demonstration limit")
    source = source_name or file_path.name
    document_id = _file_sha256(file_path)
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _ingest_pdf(file_path, document_id, source)
    if suffix in {".png", ".jpg", ".jpeg"}:
        return _ingest_image(file_path, document_id, source)
    raise ValueError(f"Unsupported file type: {suffix}")


def render_pdf_pages(
    path: str | Path, pages: list[int], output_dir: str | Path
) -> list[DocumentChunk]:
    """Render only requested pages, including vector charts, with stable evidence IDs."""
    path = Path(path)
    document_id = _file_sha256(path)
    directory = Path(output_dir) / document_id
    directory.mkdir(parents=True, exist_ok=True)
    chunks = []
    with fitz.open(path) as doc:
        for number in sorted(set(pages)):
            if not 1 <= number <= len(doc):
                raise ValueError("Requested PDF page is outside the document")
            image_path = directory / f"page-{number}.png"
            doc[number - 1].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(
                str(image_path)
            )
            chunks.append(
                DocumentChunk(
                    id=_chunk_id(document_id, "rendered-page", number, 1),
                    document_id=document_id,
                    source_name=path.name,
                    type=ChunkType.IMAGE,
                    content=f"Rendered PDF page {number}; visual reading is experimental.",
                    page=number,
                    metadata={
                        "image_path": str(image_path),
                        "experimental": True,
                        "visual_numbers_verified": False,
                    },
                )
            )
    return chunks
