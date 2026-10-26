from __future__ import annotations

import hashlib
import logging
import re
import tempfile
import unicodedata
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import FileRejected, NotFound, PayloadTooLarge
from app.domain.ingestion.detect import detect_format
from app.domain.ingestion.inspect import InspectionLimits, InspectionReport, inspect_file, resolve_options
from app.domain.ingestion.readers import ReadOptions, ResolvedOptions
from app.infrastructure.database.base import as_utc
from app.infrastructure.storage import get_storage, new_object_key
from app.modules.files.models import FileAsset

log = logging.getLogger(__name__)
CHUNK = 1024 * 1024


def sanitize_filename(name: str | None) -> str:
    name = (name or "arquivo").replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".") or "arquivo"
    return name[:255]


def spool_upload(stream: BinaryIO, max_bytes: int, tmp_dir: Path) -> tuple[Path, int, str]:
    """Copia o upload para um arquivo temporário com limite de tamanho e calcula SHA-256."""
    digest = hashlib.sha256()
    size = 0
    path = tmp_dir / "upload"
    with path.open("wb") as out:
        while chunk := stream.read(CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise PayloadTooLarge(f"O arquivo excede o tamanho máximo de {max_bytes // (1024 * 1024)} MB.")
            digest.update(chunk)
            out.write(chunk)
    if size == 0:
        raise FileRejected("O arquivo está vazio.", code="empty_file")
    return path, size, digest.hexdigest()


def inspection_limits() -> InspectionLimits:
    s = get_settings()
    return InspectionLimits(sample_rows=s.inspection_sample_rows, preview_rows=s.preview_rows,
                            max_records=s.max_records_per_file, mask_sensitive=s.mask_sensitive_previews)


def read_options(file: FileAsset, overrides: dict[str, Any] | None = None) -> ReadOptions:
    base = dict(file.read_options or {})
    base.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return ReadOptions(sheet=base.get("sheet"), header_row=base.get("header_row"), delimiter=base.get("delimiter"),
                       encoding=base.get("encoding"))


def resolved_options(path: Path, file: FileAsset, opts: ReadOptions | None = None) -> ResolvedOptions:
    opts = opts or read_options(file)
    resolved = resolve_options(path, file.detected_format, opts)
    if not resolved.header_row:
        resolved.header_row = 1
    return resolved


@contextmanager
def local_file(file: FileAsset) -> Iterator[Path]:
    if file.status == "deleted" or not file.storage_key:
        raise NotFound("O conteúdo deste arquivo foi excluído (retenção ou exclusão manual).", code="file_content_deleted")
    with get_storage().local_copy(file.storage_key) as p:
        yield p


def create_file(db: Session, *, organization_id: uuid.UUID, client_id: uuid.UUID, user_id: uuid.UUID | None,
                filename: str, stream: BinaryIO, max_bytes: int) -> FileAsset:
    """Recebe, valida, inspeciona e armazena um arquivo. Não faz commit."""
    settings = get_settings()
    filename = sanitize_filename(filename)
    with tempfile.TemporaryDirectory(prefix="ddi-upload-") as tmp:
        path, size, digest = spool_upload(stream, max_bytes, Path(tmp))
        fmt = detect_format(path, filename, max_uncompressed=settings.max_xlsx_uncompressed_bytes)
        report = inspect_file(path, fmt, ReadOptions(), inspection_limits())
        key = new_object_key(organization_id)
        get_storage().put_file(key, path)
    duplicate = db.scalar(select(FileAsset.id).where(
        FileAsset.organization_id == organization_id, FileAsset.client_account_id == client_id,
        FileAsset.content_hash == digest, FileAsset.status != "deleted").limit(1))
    file = FileAsset(
        organization_id=organization_id, client_account_id=client_id, original_filename=filename, detected_format=fmt,
        size_bytes=size, content_hash=digest, storage_key=key, status="inspected", uploaded_by=user_id,
        retention_until=datetime.now(UTC) + timedelta(days=settings.file_retention_days), duplicate_of_id=duplicate,
        read_options=report.options, structure_confirmed=False, inspection=report.to_dict(),
    )
    db.add(file)
    db.flush()
    log.info("file.stored", extra={"file_id": str(file.id), "size_bytes": size, "format": fmt})
    return file


def reinspect(file: FileAsset, overrides: dict[str, Any]) -> InspectionReport:
    with local_file(file) as path:
        opts = read_options(file, overrides) if overrides else read_options(file)
        # Ao trocar de aba, a linha de cabeçalho anterior não vale mais.
        if overrides.get("sheet") and overrides.get("sheet") != (file.read_options or {}).get("sheet") and not overrides.get("header_row"):
            opts.header_row = None
        return inspect_file(path, file.detected_format, opts, inspection_limits())


def delete_content(file: FileAsset) -> None:
    """Remove o conteúdo armazenado e a prévia; mantém metadados para histórico e auditoria."""
    if file.storage_key:
        get_storage().delete(file.storage_key)
    file.storage_key = None
    file.status = "deleted"
    file.deleted_at = datetime.now(UTC)
    file.inspection = None


def purge_expired(db: Session, now: datetime | None = None, batch: int = 200) -> list[FileAsset]:
    now = now or datetime.now(UTC)
    files = db.scalars(select(FileAsset).where(FileAsset.status != "deleted", FileAsset.retention_until.is_not(None))
                       .order_by(FileAsset.retention_until).limit(batch)).all()
    purged = []
    for f in files:
        if as_utc(f.retention_until) and as_utc(f.retention_until) < now:
            delete_content(f)
            purged.append(f)
    return purged
