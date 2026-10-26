"""Detecção do formato real do arquivo a partir do conteúdo (não da extensão)."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Literal

from app.core.errors import FileRejected

FileFormat = Literal["csv", "xlsx"]

SUPPORTED_EXTENSIONS: dict[str, FileFormat] = {".csv": "csv", ".txt": "csv", ".tsv": "csv", ".xlsx": "xlsx"}

_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_BINARY_SIGNATURES = {
    b"%PDF": "PDF",
    b"MZ": "executável",
    b"\x7fELF": "executável",
    b"\x89PNG": "imagem PNG",
    b"\xff\xd8\xff": "imagem JPEG",
    b"GIF8": "imagem GIF",
    b"Rar!": "RAR",
    b"\x1f\x8b": "GZIP",
    b"7z\xbc\xaf": "7z",
}


def detect_format(path: Path, original_filename: str, *, max_uncompressed: int) -> FileFormat:
    """Valida extensão e conteúdo. Lança ``FileRejected`` com mensagem segura."""
    ext = Path(original_filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise FileRejected(
            "Extensão não suportada. Envie arquivos .csv, .txt, .tsv ou .xlsx.", code="unsupported_extension"
        )
    expected = SUPPORTED_EXTENSIONS[ext]
    size = path.stat().st_size
    if size == 0:
        raise FileRejected("O arquivo está vazio.", code="empty_file")

    with path.open("rb") as fh:
        head = fh.read(8192)

    if head.startswith(_OLE_MAGIC):
        raise FileRejected(
            "Arquivos .xls (Excel 97-2003) não são suportados. Salve como .xlsx e envie novamente.",
            code="unsupported_format",
        )
    for sig, name in _BINARY_SIGNATURES.items():
        if head.startswith(sig):
            raise FileRejected(f"O conteúdo do arquivo ({name}) não corresponde a uma planilha.", code="content_mismatch")

    if head.startswith(_ZIP_MAGIC):
        if expected != "xlsx":
            raise FileRejected("O conteúdo é um arquivo compactado, incompatível com a extensão informada.", code="content_mismatch")
        _validate_xlsx_container(path, max_uncompressed)
        return "xlsx"

    if expected == "xlsx":
        raise FileRejected("O arquivo tem extensão .xlsx mas não é uma planilha Excel válida.", code="content_mismatch")
    _validate_text(head)
    return "csv"


def _validate_xlsx_container(path: Path, max_uncompressed: int) -> None:
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            names = {i.filename for i in infos}
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise FileRejected("O arquivo compactado não é uma planilha .xlsx válida.", code="corrupted_file")
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise FileRejected("Planilhas com macros não são aceitas.", code="macro_rejected")
            total = sum(i.file_size for i in infos)
            if total > max_uncompressed:
                raise FileRejected("O conteúdo descompactado da planilha excede o limite permitido.", code="decompression_limit")
            compressed = sum(i.compress_size for i in infos) or 1
            if total / compressed > 200:
                raise FileRejected("Taxa de compressão suspeita (possível arquivo malicioso).", code="decompression_limit")
            bad = zf.testzip()
            if bad is not None:
                raise FileRejected("O arquivo .xlsx está corrompido.", code="corrupted_file")
    except zipfile.BadZipFile as exc:
        raise FileRejected("O arquivo .xlsx está corrompido.", code="corrupted_file") from exc


def _validate_text(head: bytes) -> None:
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return  # UTF-16 com BOM é tratado pelo leitor
    if b"\x00" in head:
        raise FileRejected("O arquivo contém dados binários e não parece ser um CSV de texto.", code="content_mismatch")
    control = sum(1 for b in head if b < 32 and b not in (9, 10, 13))
    if control > max(5, len(head) // 100):
        raise FileRejected("O arquivo contém caracteres de controle demais para ser um CSV.", code="content_mismatch")
