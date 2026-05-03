from __future__ import annotations

import re


def detect_section(text: str, fallback: str | None = None) -> str | None:
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if len(cleaned) <= 90 and (
            cleaned.isupper()
            or re.match(r"^\d+(\.\d+)*\s+[A-Z][A-Za-z0-9 ,:/&()-]+$", cleaned)
        ):
            return cleaned
    return fallback


def chunk_text(
    text: str,
    min_tokens: int = 400,
    max_tokens: int = 800,
    overlap_ratio: float = 0.12,
) -> list[str]:
    words = text.split()
    if not words:
        return []
    if len(words) <= max_tokens:
        return [" ".join(words)]

    overlap = max(1, int(max_tokens * overlap_ratio))
    step = max_tokens - overlap
    chunks = []
    start = 0

    while start < len(words):
        end = min(start + max_tokens, len(words))
        chunk_words = words[start:end]
        if len(chunk_words) >= min_tokens or not chunks:
            chunks.append(" ".join(chunk_words))
        else:
            chunks[-1] = f"{chunks[-1]} {' '.join(chunk_words)}"
        if end == len(words):
            break
        start += step

    return chunks


def table_to_text(table: list[list[str | None]]) -> str:
    rows = []
    for row in table:
        cells = [str(cell).strip() if cell is not None else "" for cell in row]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)
