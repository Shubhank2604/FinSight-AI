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
    if not isinstance(min_tokens, int) or not isinstance(max_tokens, int) or not 0 < min_tokens <= max_tokens:
        raise ValueError("Require 0 < min_tokens <= max_tokens as integers")
    if not 0 <= overlap_ratio < 1:
        raise ValueError("overlap_ratio must be in [0, 1)")
    spans = list(re.finditer(r"\S+", text))
    words = [m.group() for m in spans]
    if not words:
        return []
    if len(words) <= max_tokens:
        return [text.strip()]

    overlap = max(1, int(max_tokens * overlap_ratio))
    step = max_tokens - overlap
    chunks = []
    start = 0

    while start < len(words):
        end = min(start + max_tokens, len(words))
        chunk_words = words[start:end]
        chunks.append(text[spans[start].start():spans[end-1].end()].strip())
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
