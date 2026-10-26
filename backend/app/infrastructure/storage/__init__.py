"""Abstração de armazenamento de objetos privado (local em dev, S3 compatível em produção).

Chaves são geradas internamente (aleatórias, prefixadas pela organização) e
nunca são expostas em respostas da API.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings


class Storage(Protocol):
    def put_file(self, key: str, source: Path) -> None: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def local_copy(self, key: str) -> Iterator[Path]: ...
    def open_stream(self, key: str, chunk_size: int = 65536) -> Iterator[bytes]: ...


def new_object_key(organization_id: uuid.UUID, kind: str = "uploads") -> str:
    return f"org/{organization_id}/{kind}/{uuid.uuid4().hex}"


class LocalStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("chave de armazenamento inválida")
        return p

    def put_file(self, key: str, source: Path) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".partial")
        shutil.copyfile(source, tmp)
        tmp.replace(dest)
        dest.chmod(0o600)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    @contextmanager
    def local_copy(self, key: str) -> Iterator[Path]:
        p = self._path(key)
        if not p.is_file():
            raise FileNotFoundError(key)
        yield p

    def open_stream(self, key: str, chunk_size: int = 65536) -> Iterator[bytes]:
        with self._path(key).open("rb") as fh:
            while chunk := fh.read(chunk_size):
                yield chunk


class S3Storage:
    """Armazenamento S3 compatível (AWS S3, MinIO, RustFS...). Requer o extra ``s3``."""

    def __init__(self, bucket: str, endpoint_url: str | None, region: str | None):
        import boto3  # dependência opcional

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)

    def put_file(self, key: str, source: Path) -> None:
        self.client.upload_file(str(source), self.bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"})

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.client.exceptions.ClientError:
            return False

    @contextmanager
    def local_copy(self, key: str) -> Iterator[Path]:
        with tempfile.TemporaryDirectory(prefix="ddi-") as tmp:
            dest = Path(tmp) / "object"
            self.client.download_file(self.bucket, key, str(dest))
            yield dest

    def open_stream(self, key: str, chunk_size: int = 65536) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        yield from body.iter_chunks(chunk_size)


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "s3":
        return S3Storage(s.s3_bucket, s.s3_endpoint_url, s.s3_region)
    return LocalStorage(s.storage_local_root)
