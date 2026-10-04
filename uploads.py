from __future__ import annotations
import hashlib
import re
from pathlib import Path


def save_upload(name: str, data: bytes, directory: str | Path) -> Path:
    if not data or len(data) > 20 * 1024 * 1024:
        raise ValueError("Upload must be nonempty and at most 20 MB")
    # Treat both Windows and POSIX separators as untrusted input.
    basename = name.replace('\\', '/').rsplit('/', 1)[-1]
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', basename).strip(' .')
    if not safe or Path(safe).suffix.lower() not in {'.pdf', '.png', '.jpg', '.jpeg'}:
        raise ValueError("Upload a PDF, PNG, or JPEG file")
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / (hashlib.sha256(data).hexdigest()[:16] + '-' + safe)
    if target.parent.resolve() != root:
        raise ValueError("Invalid upload path")
    if not target.exists():
        target.write_bytes(data)
    return target
