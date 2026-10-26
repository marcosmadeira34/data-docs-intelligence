"""Inspeção estrutural de arquivos tabulares desconhecidos.

Produz um relatório JSON-serializável com abas, cabeçalhos candidatos, colunas,
tipos inferidos, ausências, prévia mascarada, alertas e ambiguidades. Quando a
interpretação é duvidosa, a ambiguidade é relatada em vez de decidida em silêncio.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.domain.canonical_fields import CANONICAL_FIELDS
from app.domain.ingestion import readers
from app.domain.ingestion.readers import ReadOptions, ResolvedOptions
from app.domain.values import (
    date_format_evidence,
    digits_only,
    is_blank,
    is_valid_cnpj,
    is_valid_cpf,
    mask_value,
    normalize_name,
    number_style_evidence,
    parse_bool,
    to_text,
)

HEADER_SCAN_ROWS = 25
_KNOWN_HEADER_TOKENS = {normalize_name(s) for f in CANONICAL_FIELDS for s in (*f.synonyms, f.label)}


@dataclass
class InspectionLimits:
    sample_rows: int = 1000
    preview_rows: int = 20
    max_records: int = 1_000_000
    mask_sensitive: bool = True
    inspect_merged_max_bytes: int = 5 * 1024 * 1024


@dataclass
class InspectionReport:
    format: str
    options: dict[str, Any]
    sheets: list[dict[str, Any]] = field(default_factory=list)
    header_candidates: list[dict[str, Any]] = field(default_factory=list)
    delimiter_candidates: list[dict[str, Any]] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    blank_rows: int = 0
    malformed_rows: dict[str, Any] = field(default_factory=lambda: {"count": 0, "examples": []})
    preview: list[list[str]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    ambiguities: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


# --------------------------------------------------------------------------- classificação de células


def classify_cell(value: Any) -> str:
    if is_blank(value):
        return "blank"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (datetime, date)):
        return "date"
    if isinstance(value, (int, float)):
        return "integer" if float(value).is_integer() else "decimal"
    text = to_text(value)
    d = digits_only(text)
    if len(d) in (11, 14) and re.fullmatch(r"[\d./\- ]{11,18}", text) and (is_valid_cpf(d) or is_valid_cnpj(d)):
        return "tax_id"
    if date_format_evidence(text):
        if not (text.isdigit() and len(text) == 8 and not text.startswith(("19", "20"))):
            return "date"
    style = number_style_evidence(text)
    if style != "none":
        if text.isdigit() and len(text) > 1 and text.startswith("0"):
            return "code"  # zeros à esquerda: código, não número
        if "," in text or "." in text:
            return "decimal"
        return "integer"
    if parse_bool(text) is not None and len(text) <= 5:
        return "boolean"
    return "text"


def _header_score(row: list[Any], width: int, below: list[list[Any]]) -> float:
    cells = [c for c in row if not is_blank(c)]
    if not cells or width == 0:
        return 0.0
    kinds = [classify_cell(c) for c in cells]
    text_ratio = sum(k == "text" for k in kinds) / len(cells)
    fill_ratio = min(1.0, len(cells) / width)
    norm = [normalize_name(to_text(c)) for c in cells]
    unique_ratio = len(set(norm)) / len(cells)
    known_ratio = sum(n in _KNOWN_HEADER_TOKENS for n in norm) / len(cells)
    # linhas abaixo devem ter dados com tipos diferentes de texto em parte das colunas
    typed_below = 0.0
    if below:
        typed = sum(
            1 for r in below for c in r if not is_blank(c) and classify_cell(c) in ("integer", "decimal", "date", "tax_id")
        )
        filled = sum(1 for r in below for c in r if not is_blank(c)) or 1
        typed_below = typed / filled
    if len(cells) == 1 and width > 2:
        return 0.05  # linha de título
    return round(0.35 * text_ratio + 0.25 * fill_ratio + 0.1 * unique_ratio + 0.2 * known_ratio + 0.1 * min(1.0, typed_below * 2), 4)


def detect_header_candidates(rows: list[tuple[int, list[Any]]]) -> list[dict[str, Any]]:
    widths = [sum(1 for c in r if not is_blank(c)) for _, r in rows]
    multi = [w for w in widths if w >= 2]
    width = Counter(multi).most_common(1)[0][0] if multi else max(widths, default=0)
    candidates = []
    for i, (row_number, row) in enumerate(rows[:HEADER_SCAN_ROWS]):
        score = _header_score(row, width, [r for _, r in rows[i + 1 : i + 6]])
        if score <= 0:
            continue
        candidates.append({
            "row": row_number,
            "score": score,
            "values": [to_text(c)[:60] for c in row[:30]],
            "is_title": sum(1 for c in row if not is_blank(c)) == 1 and width > 2,
        })
    candidates.sort(key=lambda c: (-c["score"], c["row"]))
    return candidates[:5]


# --------------------------------------------------------------------------- perfil de colunas


class _ColumnStats:
    def __init__(self, name: str, index: int):
        self.name = name
        self.index = index
        self.kinds: Counter[str] = Counter()
        self.blank = 0
        self.total = 0
        self.distinct: set[str] = set()
        self.number_styles: Counter[str] = Counter()
        self.date_formats: Counter[str] = Counter()
        self.date_rows = 0
        self.samples: list[Any] = []

    def add(self, value: Any) -> None:
        self.total += 1
        kind = classify_cell(value)
        if kind == "blank":
            self.blank += 1
            return
        self.kinds[kind] += 1
        text = to_text(value)
        if len(self.distinct) < 5000:
            self.distinct.add(text)
        if len(self.samples) < 5 and text not in [to_text(s) for s in self.samples]:
            self.samples.append(value)
        if kind in ("integer", "decimal") and isinstance(value, str):
            self.number_styles[number_style_evidence(text)] += 1
        if kind == "date" and isinstance(value, str):
            self.date_rows += 1
            for fmt in date_format_evidence(text):
                self.date_formats[fmt] += 1

    def result(self, mask: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        warnings: list[dict[str, Any]] = []
        filled = self.total - self.blank
        inferred = "empty"
        if filled:
            kind, count = self.kinds.most_common(1)[0]
            numeric = self.kinds["integer"] + self.kinds["decimal"]
            if numeric / filled >= 0.9 and kind in ("integer", "decimal"):
                inferred = "decimal" if self.kinds["decimal"] else "integer"
            elif count / filled >= 0.9:
                inferred = kind
            else:
                inferred = "text"
                warnings.append({"code": "mixed_types", "column": self.name,
                                 "message": f"A coluna '{self.name}' mistura tipos de dados ({dict(self.kinds)})."})
        number_style = None
        if inferred in ("integer", "decimal") and self.number_styles:
            br, us = self.number_styles["br"], self.number_styles["us"]
            if br and us:
                number_style = "br" if br >= us else "us"
                warnings.append({"code": "mixed_number_format", "column": self.name,
                                 "message": f"A coluna '{self.name}' mistura formatos numéricos brasileiro e americano."})
            elif br or us:
                number_style = "br" if br else "us"
            elif self.number_styles["ambiguous"]:
                number_style = "br"
                warnings.append({"code": "ambiguous_number_format", "column": self.name,
                                 "message": f"Valores como '1.234' na coluna '{self.name}' foram interpretados como milhar (padrão brasileiro). Confirme."})
        date_format = None
        if inferred == "date" and self.date_rows:
            full = [f for f, c in self.date_formats.items() if c == self.date_rows]
            # Se todos os valores servem a dd/mm e mm/dd, prevalece o padrão brasileiro.
            if "dd/mm/yyyy" in full:
                date_format = "dd/mm/yyyy"
            elif "mm/dd/yyyy" in full:
                date_format = "mm/dd/yyyy"
                warnings.append({"code": "us_date_format", "column": self.name,
                                 "message": f"A coluna '{self.name}' parece usar mês/dia/ano (formato americano). Confirme."})
            elif full:
                date_format = sorted(full)[0]
            else:
                warnings.append({"code": "mixed_date_format", "column": self.name,
                                 "message": f"A coluna '{self.name}' mistura formatos de data."})
        sensitive_kind = "tax_id" if inferred == "tax_id" else None
        samples = [mask_value(s, kind=sensitive_kind) if mask else to_text(s)[:80] for s in self.samples]
        return {
            "index": self.index,
            "name": self.name,
            "normalized": normalize_name(self.name),
            "inferred_type": inferred,
            "null_ratio": round(self.blank / self.total, 4) if self.total else 1.0,
            "filled": filled,
            "distinct_sample": len(self.distinct),
            "number_style": number_style,
            "date_format": date_format,
            "samples": samples,
        }, warnings


# --------------------------------------------------------------------------- inspeção


def resolve_options(path: Path, fmt: str, opts: ReadOptions, report: InspectionReport | None = None) -> ResolvedOptions:
    encoding = opts.encoding
    delimiter = opts.delimiter
    if fmt == "csv":
        if not encoding:
            guess = readers.detect_encoding(path)
            encoding = guess.encoding
            if report is not None and guess.note:
                report.warnings.append({"code": "encoding_guess", "message": guess.note})
        if not delimiter:
            sample = readers._read_text_sample(path, encoding)
            delimiter, scored, ambiguous = readers.detect_delimiter(sample)
            if report is not None:
                report.delimiter_candidates = scored
                if ambiguous:
                    report.ambiguities.append({
                        "code": "ambiguous_delimiter",
                        "message": "Mais de um delimitador produz uma estrutura consistente. Confirme o delimitador.",
                        "options": [s["delimiter"] for s in scored[:3]],
                    })
    return ResolvedOptions(format=fmt, sheet=opts.sheet, encoding=encoding, delimiter=delimiter, header_row=opts.header_row or 0)


def inspect_file(path: Path, fmt: str, opts: ReadOptions, limits: InspectionLimits | None = None) -> InspectionReport:
    limits = limits or InspectionLimits()
    report = InspectionReport(format=fmt, options={})
    if fmt == "xlsx":
        report.sheets = readers.list_sheets(path, inspect_merged=path.stat().st_size <= limits.inspect_merged_max_bytes)
        if not report.sheets:
            from app.core.errors import FileRejected

            raise FileRejected("A planilha não contém abas.", code="empty_file")
        if opts.sheet is None:
            visible = [s for s in report.sheets if s["visible"]] or report.sheets
            biggest = max(visible, key=lambda s: _dimension_cells(s.get("dimension")))
            opts = ReadOptions(sheet=biggest["name"], header_row=opts.header_row)
            if len(report.sheets) > 1:
                report.ambiguities.append({
                    "code": "multiple_sheets",
                    "message": f"A planilha tem {len(report.sheets)} abas. A aba '{opts.sheet}' foi selecionada; confirme ou escolha outra.",
                    "options": [s["name"] for s in report.sheets],
                })
        sheet_info = next((s for s in report.sheets if s["name"] == opts.sheet), None)
        if sheet_info and sheet_info.get("merged_ranges"):
            report.warnings.append({"code": "merged_cells",
                                    "message": f"A aba contém {len(sheet_info['merged_ranges'])} intervalo(s) de células mescladas; apenas a primeira célula de cada intervalo tem valor."})

    resolved = resolve_options(path, fmt, opts, report)

    # Varredura inicial para detectar cabeçalho
    head_rows: list[tuple[int, list[Any]]] = []
    for idx, row in readers.iter_raw_rows(path, fmt, resolved):
        head_rows.append((idx, row))
        if len(head_rows) >= HEADER_SCAN_ROWS + 6:
            break
    if not any(any(not is_blank(c) for c in r) for _, r in head_rows):
        from app.core.errors import FileRejected

        raise FileRejected("O arquivo (ou a aba selecionada) não contém dados.", code="empty_file")

    report.header_candidates = detect_header_candidates(head_rows)
    if opts.header_row:
        header_row = opts.header_row
    else:
        header_row = report.header_candidates[0]["row"] if report.header_candidates else 1
        cands = report.header_candidates
        if len(cands) > 1 and cands[0]["score"] - cands[1]["score"] < 0.05:
            report.ambiguities.append({
                "code": "ambiguous_header",
                "message": f"Não está claro se o cabeçalho está na linha {cands[0]['row']} ou {cands[1]['row']}. Confirme a linha de cabeçalho.",
                "options": [c["row"] for c in cands[:3]],
            })
        titles = [c["row"] for c in cands if c["is_title"] and c["row"] < header_row]
        if header_row > 1:
            report.warnings.append({"code": "title_rows",
                                    "message": f"As {header_row - 1} primeira(s) linha(s) foram tratadas como título/observação e ignoradas.",
                                    "rows": titles})
    resolved.header_row = header_row
    report.options = {"sheet": resolved.sheet, "header_row": header_row, "delimiter": resolved.delimiter, "encoding": resolved.encoding}

    columns, records = readers.iter_records(path, resolved)
    _, header_issues = readers.build_columns(next((r for i, r in head_rows if i == header_row), []))
    report.warnings.extend(header_issues)
    stats = [_ColumnStats(name, i) for i, name in enumerate(columns)]
    width = len(columns)
    blank = 0
    last_row = header_row
    for row_number, row in records:
        blank += row_number - last_row - 1
        last_row = row_number
        report.row_count += 1
        if report.row_count > limits.max_records:
            report.warnings.append({"code": "record_limit", "message": f"O arquivo excede o limite de {limits.max_records} registros; a contagem foi interrompida."})
            break
        if fmt == "csv" and len(row) != width:
            mal = report.malformed_rows
            mal["count"] += 1
            if len(mal["examples"]) < 10:
                mal["examples"].append({"row": row_number, "fields": len(row), "expected": width})
        if report.row_count <= limits.sample_rows:
            for i, st in enumerate(stats):
                st.add(row[i] if i < len(row) else None)
            if len(report.preview) < limits.preview_rows:
                report.preview.append(row)
        if len(row) > width and fmt == "xlsx" and any(not is_blank(c) for c in row[width:]):
            mal = report.malformed_rows
            mal["count"] += 1
            if len(mal["examples"]) < 10:
                mal["examples"].append({"row": row_number, "fields": len(row), "expected": width})
    report.blank_rows = blank
    if report.row_count == 0:
        report.warnings.append({"code": "no_records", "message": "Nenhum registro encontrado abaixo do cabeçalho."})
    if report.malformed_rows["count"]:
        report.warnings.append({"code": "malformed_rows",
                                "message": f"{report.malformed_rows['count']} linha(s) têm quantidade de campos diferente do cabeçalho."})

    for st in stats:
        col, col_warnings = st.result(limits.mask_sensitive)
        report.columns.append(col)
        report.warnings.extend(col_warnings)
    report.preview = [_mask_row(row, report.columns, limits.mask_sensitive) for row in report.preview]
    return report


def _dimension_cells(dimension: str | None) -> int:
    """Quantidade de células de um intervalo como 'A1:I33' (0 se desconhecido)."""
    from openpyxl.utils.cell import range_boundaries

    if not dimension:
        return 0
    try:
        min_col, min_row, max_col, max_row = range_boundaries(dimension)
    except ValueError:
        return 0
    return (max_col - min_col + 1) * (max_row - min_row + 1)


def _mask_row(row: list[Any], columns: list[dict[str, Any]], mask: bool) -> list[str]:
    out = []
    for i, col in enumerate(columns):
        value = row[i] if i < len(row) else None
        kind = "tax_id" if col["inferred_type"] == "tax_id" else None
        out.append(mask_value(value, kind=kind) if mask else to_text(value)[:200])
    return out
