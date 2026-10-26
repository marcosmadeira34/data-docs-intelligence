"""Entradas de mapeamento, transformações autorizadas e aplicação a registros."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.canonical_fields import field_type, is_valid_target
from app.domain.values import DATE_FORMATS, digits_only, parse_typed, strip_accents, to_text

TEXT_TRANSFORMS = {
    "trim": lambda s: s.strip(),
    "upper": lambda s: s.upper(),
    "lower": lambda s: s.lower(),
    "digits_only": digits_only,
    "strip_accents": strip_accents,
    "collapse_spaces": lambda s: " ".join(s.split()),
}
NUMERIC_TRANSFORMS = {"negate", "abs"}
ALLOWED_TRANSFORMS = set(TEXT_TRANSFORMS) | NUMERIC_TRANSFORMS


class MappingEntry(BaseModel):
    source_column: str = Field(min_length=1, max_length=255)
    target_field: str | None = None
    status: Literal["approved", "suggested", "ignored"] = "suggested"
    confidence: float | None = Field(default=None, ge=0, le=1)
    rationale: str | None = Field(default=None, max_length=500)
    transforms: list[str] = Field(default_factory=list, max_length=6)
    required: bool = False
    number_style: Literal["br", "us", "auto"] = "auto"
    date_format: str | None = None
    source: str = "manual"

    @field_validator("target_field")
    @classmethod
    def _target(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_target(v):
            raise ValueError(f"campo de destino desconhecido: {v!r} (use um campo canônico ou o prefixo x_)")
        return v

    @field_validator("transforms")
    @classmethod
    def _transforms(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in ALLOWED_TRANSFORMS]
        if bad:
            raise ValueError(f"transformações não autorizadas: {bad}")
        return v

    @field_validator("date_format")
    @classmethod
    def _date_format(cls, v: str | None) -> str | None:
        if v is not None and v not in DATE_FORMATS and v != "excel_serial":
            raise ValueError(f"formato de data não suportado: {v}")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> MappingEntry:
        if self.status == "ignored":
            self.target_field = None
            self.required = False
        elif self.target_field is None and self.status == "approved":
            raise ValueError(f"a coluna {self.source_column!r} foi aprovada sem campo de destino")
        return self


def validate_entries(entries: list[MappingEntry]) -> list[str]:
    """Erros de consistência entre entradas (destinos duplicados, colunas repetidas)."""
    errors = []
    seen_sources: set[str] = set()
    seen_targets: dict[str, str] = {}
    for e in entries:
        if e.source_column in seen_sources:
            errors.append(f"a coluna {e.source_column!r} aparece mais de uma vez")
        seen_sources.add(e.source_column)
        if e.target_field and e.status != "ignored":
            if e.target_field in seen_targets:
                errors.append(f"o campo {e.target_field!r} está mapeado para {seen_targets[e.target_field]!r} e {e.source_column!r}")
            seen_targets[e.target_field] = e.source_column
    return errors


@dataclass(slots=True)
class FieldValue:
    raw: Any
    value: Any
    ok: bool
    source_column: str


@dataclass(slots=True)
class Record:
    row_number: int
    fields: dict[str, FieldValue]

    def get(self, key: str) -> Any:
        fv = self.fields.get(key)
        return fv.value if fv else None

    def raw(self, key: str) -> Any:
        fv = self.fields.get(key)
        return fv.raw if fv else None


class RecordBuilder:
    """Converte linhas brutas em registros canônicos tipados segundo o mapeamento."""

    def __init__(self, columns: list[str], entries: list[MappingEntry]):
        index = {c: i for i, c in enumerate(columns)}
        self.plan: list[tuple[int | None, MappingEntry, str]] = []
        self.missing_columns: list[str] = []
        for e in entries:
            if e.status == "ignored" or not e.target_field:
                continue
            idx = index.get(e.source_column)
            if idx is None:
                self.missing_columns.append(e.source_column)
            self.plan.append((idx, e, field_type(e.target_field)))

    @property
    def target_fields(self) -> list[str]:
        return [e.target_field for _, e, _ in self.plan if e.target_field]

    def build(self, row_number: int, row: list[Any]) -> Record:
        fields: dict[str, FieldValue] = {}
        for idx, entry, ftype in self.plan:
            raw = row[idx] if idx is not None and idx < len(row) else None
            value = raw
            text_transforms = [t for t in entry.transforms if t in TEXT_TRANSFORMS]
            if text_transforms and raw is not None:
                value = to_text(raw)
                for t in text_transforms:
                    value = TEXT_TRANSFORMS[t](value)
            parsed, ok = parse_typed(value, ftype, number_style=entry.number_style, date_format=entry.date_format)
            if ok and parsed is not None and ftype in ("decimal", "integer"):
                if "abs" in entry.transforms:
                    parsed = abs(parsed)
                if "negate" in entry.transforms:
                    parsed = -parsed
            fields[entry.target_field] = FieldValue(raw=raw, value=parsed, ok=ok, source_column=entry.source_column)  # type: ignore[index]
        return Record(row_number=row_number, fields=fields)
