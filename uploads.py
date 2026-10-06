from __future__ import annotations
import hashlib
import re
import shutil
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
    if target.is_symlink() or target.is_junction():
        raise ValueError('Upload target must not be a filesystem link')
    if target.exists() and target.read_bytes() != data:
        raise ValueError('Stored upload contents do not match; choose another filename')
    if not target.exists():
        target.write_bytes(data)
    return target


def index_upload(name: str, data: bytes, retriever, directory: str | Path) -> int:
    """Persist and index one upload. Repeated content does not re-embed."""
    from ingestion import ingest_file

    source = name.replace('\\', '/').rsplit('/', 1)[-1]
    path = save_upload(name, data, directory)
    document_id = hashlib.sha256(data).hexdigest()
    existing = [c for c in retriever.chunks if c.document_id == document_id]
    if existing:
        names = {c.source_name for c in existing}
        if source not in names and not any(c.metadata.get('upload_name') == source for c in existing):
            raise ValueError('Identical document content is already indexed under '
                             + ', '.join(sorted(names)) + '.')
        return 0
    upload_name = source
    if source in retriever.source_names():
        # A second file named report.pdf is an additional document, not an implicit deletion.
        source = f'{Path(source).stem} ({document_id[:16]}){Path(source).suffix}'
        if source in retriever.source_names():
            source = f'{Path(upload_name).stem} ({document_id}){Path(upload_name).suffix}'
    chunks = ingest_file(path, source_name=source)
    if not chunks:
        raise ValueError('No readable content was found in this file.')
    for chunk in chunks:
        chunk.metadata['upload_name'] = upload_name
    return retriever.index_chunks(chunks)


def remove_managed_upload(document_id: str, directory: str | Path,
                          image_directory: str | Path = 'data/uploads/extracted_images') -> int:
    """Delete only hash-verified copies within managed upload storage."""
    if not re.fullmatch(r'[0-9a-f]{64}', document_id):
        raise ValueError('Invalid uploaded document identity')
    root = Path(directory).absolute()
    images_root = Path(image_directory).absolute()
    if any(p.is_symlink() or p.is_junction()
           for target in (root, images_root) for p in (target, *target.parents)):
        raise ValueError('Upload storage must not contain filesystem links')
    targets = []
    for path in root.glob(document_id[:16] + '-*'):
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError('Unexpected linked upload file')
        if path.parent.resolve() != root.resolve():
            raise ValueError('Upload deletion escaped managed storage')
        if hashlib.sha256(path.read_bytes()).hexdigest() == document_id:
            targets.append(path)
    image_target = images_root / document_id
    if image_target.exists():
        if image_target.resolve().parent != images_root.resolve():
            raise ValueError('Image deletion escaped managed storage')
        if any(p.is_symlink() or p.is_junction()
               for p in (image_target, *image_target.rglob('*'))):
            raise ValueError('Extracted images must not contain filesystem links')
    for path in targets:
        path.unlink()
    if image_target.exists():
        shutil.rmtree(image_target)
    return len(targets)
