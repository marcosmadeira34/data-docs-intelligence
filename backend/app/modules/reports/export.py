"""Exportação CSV segura (proteção contra injeção de fórmulas em planilhas)."""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable, Iterator
from typing import Any

from app.domain.values import to_text

_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r", "|", "%")
_PLAIN_NUMBER = re.compile(r"^-?\d+([.,]\d+)?$")


def safe_cell(value: Any) -> str:
    """Neutraliza conteúdo que o Excel/LibreOffice interpretaria como fórmula."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    text = to_text(value)
    if text.startswith(_FORMULA_PREFIX) and not _PLAIN_NUMBER.match(text):
        return "'" + text
    return text


def csv_stream(header: list[str], rows: Iterable[list[Any]], delimiter: str = ";") -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
    yield "﻿"  # BOM para o Excel reconhecer UTF-8
    writer.writerow([safe_cell(h) for h in header])
    for i, row in enumerate(rows, 1):
        writer.writerow([safe_cell(c) for c in row])
        if i % 500 == 0:
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()
    yield buf.getvalue()
