"""Comparação determinística de dois conjuntos tabulares por chave explícita.

Registros só são considerados correspondentes quando a chave configurada é
idêntica (após normalização explícita). Chaves duplicadas ou ausentes são
classificadas como ambíguas/não comparáveis, nunca pareadas por semelhança.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.values import is_blank, parse_date, parse_decimal, strip_accents, to_text

Category = Literal["match", "mismatch", "only_a", "only_b", "duplicate_key_a", "duplicate_key_b", "missing_key_a", "missing_key_b"]
CATEGORIES: tuple[str, ...] = ("match", "mismatch", "only_a", "only_b", "duplicate_key_a", "duplicate_key_b", "missing_key_a", "missing_key_b")


class KeyPair(BaseModel):
    column_a: str = Field(min_length=1, max_length=255)
    column_b: str = Field(min_length=1, max_length=255)


class ComparePair(BaseModel):
    column_a: str = Field(min_length=1, max_length=255)
    column_b: str = Field(min_length=1, max_length=255)
    kind: Literal["text", "number", "date"] = "text"
    abs_tolerance: Decimal = Field(default=Decimal("0"), ge=0)
    pct_tolerance: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    number_style_a: Literal["br", "us", "auto"] = "auto"
    number_style_b: Literal["br", "us", "auto"] = "auto"
    date_format_a: str | None = None
    date_format_b: str | None = None


class ComparisonConfig(BaseModel):
    key_pairs: list[KeyPair] = Field(min_length=1, max_length=4)
    compare_pairs: list[ComparePair] = Field(default_factory=list, max_length=40)
    key_normalization: list[Literal["trim", "case_insensitive", "strip_accents", "digits_only", "strip_leading_zeros"]] = Field(
        default_factory=lambda: ["trim", "case_insensitive"])
    text_normalization: list[Literal["trim", "case_insensitive", "strip_accents", "collapse_spaces"]] = Field(
        default_factory=lambda: ["trim", "case_insensitive", "collapse_spaces"])
    null_vs_value: Literal["divergent", "ignore"] = "divergent"

    @model_validator(mode="after")
    def _distinct(self) -> ComparisonConfig:
        keys = {(k.column_a, k.column_b) for k in self.key_pairs}
        if len(keys) != len(self.key_pairs):
            raise ValueError("pares de chave repetidos")
        return self


def _norm_text(v: Any, steps: list[str]) -> str:
    t = to_text(v)
    if "trim" in steps:
        t = t.strip()
    if "collapse_spaces" in steps:
        t = " ".join(t.split())
    if "strip_accents" in steps:
        t = strip_accents(t)
    if "case_insensitive" in steps:
        t = t.lower()
    if "digits_only" in steps:
        t = "".join(c for c in t if c.isdigit())
    if "strip_leading_zeros" in steps:
        t = t.lstrip("0") or ("0" if t else "")
    return t


@dataclass
class Side:
    columns: list[str]
    rows: Iterable[tuple[int, list[Any]]]


@dataclass
class ResultItem:
    category: str
    key: str | None
    row_a: int | None = None
    row_b: int | None = None
    differences: list[dict[str, Any]] = field(default_factory=list)
    note: str | None = None


@dataclass
class ComparisonOutcome:
    counts: Counter[str] = field(default_factory=Counter)
    rows_a: int = 0
    rows_b: int = 0
    field_divergences: Counter[str] = field(default_factory=Counter)

    def summary(self) -> dict[str, Any]:
        return {
            "rows_a": self.rows_a,
            "rows_b": self.rows_b,
            **{c: self.counts[c] for c in CATEGORIES},
            "field_divergences": dict(self.field_divergences),
        }


def _index(cols: list[str], names: list[str], side: str) -> list[int]:
    idx = {c: i for i, c in enumerate(cols)}
    missing = [n for n in names if n not in idx]
    if missing:
        raise ValueError(f"colunas inexistentes no arquivo {side}: {', '.join(missing)}")
    return [idx[n] for n in names]


def _compare_values(pair: ComparePair, a: Any, b: Any, null_vs_value: str, text_steps: list[str]) -> dict[str, Any] | None:
    """Retorna a divergência encontrada ou None se os valores forem equivalentes."""
    blank_a, blank_b = is_blank(a), is_blank(b)
    if blank_a and blank_b:
        return None
    if blank_a or blank_b:
        if null_vs_value == "ignore":
            return None
        return {"reason": "valor ausente em um dos arquivos"}
    if pair.kind == "number":
        da, db = parse_decimal(a, pair.number_style_a), parse_decimal(b, pair.number_style_b)
        if da is None or db is None:
            return {"reason": "valor não numérico; comparação insegura"}
        diff = db - da
        if abs(diff) <= pair.abs_tolerance or (pair.pct_tolerance and da != 0 and abs(diff) <= pair.pct_tolerance * abs(da)):
            return None
        return {"reason": "diferença numérica", "delta": str(diff)}
    if pair.kind == "date":
        ta, tb = parse_date(a, pair.date_format_a), parse_date(b, pair.date_format_b)
        if ta is None or tb is None:
            return {"reason": "data inválida; comparação insegura"}
        if ta == tb:
            return None
        return {"reason": "datas diferentes", "delta_days": (tb - ta).days}
    if _norm_text(a, text_steps) == _norm_text(b, text_steps):
        return None
    return {"reason": "textos diferentes"}


def compare(
    config: ComparisonConfig,
    side_a: Side,
    side_b: Side,
    sink: Callable[[ResultItem], None],
    *,
    include_matches: bool = False,
) -> ComparisonOutcome:
    out = ComparisonOutcome()
    key_a = _index(side_a.columns, [k.column_a for k in config.key_pairs], "A")
    key_b = _index(side_b.columns, [k.column_b for k in config.key_pairs], "B")
    cmp_a = _index(side_a.columns, [p.column_a for p in config.compare_pairs], "A")
    cmp_b = _index(side_b.columns, [p.column_b for p in config.compare_pairs], "B")

    def load(side: Side, key_idx: list[int], cmp_idx: list[int], label: str) -> tuple[dict[str, list[tuple[int, list[Any], str]]], int]:
        index: dict[str, list[tuple[int, list[Any], str]]] = {}
        count = 0
        for row_number, row in side.rows:
            count += 1
            parts = [row[i] if i < len(row) else None for i in key_idx]
            if any(is_blank(p) for p in parts):
                out.counts[f"missing_key_{label}"] += 1
                sink(ResultItem(f"missing_key_{label}", None, **{f"row_{label}": row_number},
                                note="Chave ausente; registro não pode ser comparado com segurança."))
                continue
            key = " | ".join(_norm_text(p, config.key_normalization) for p in parts)
            values = [row[i] if i < len(row) else None for i in cmp_idx]
            display = " | ".join(to_text(p)[:60] for p in parts)
            index.setdefault(key, []).append((row_number, values, display))
        return index, count

    idx_a, out.rows_a = load(side_a, key_a, cmp_a, "a")
    idx_b, out.rows_b = load(side_b, key_b, cmp_b, "b")

    for key, entries_a in idx_a.items():
        entries_b = idx_b.get(key)
        display = entries_a[0][2]
        if len(entries_a) > 1 or (entries_b and len(entries_b) > 1):
            sides = (("a", "b", entries_a, entries_b or []), ("b", "a", entries_b or [], entries_a))
            for label, other, entries, other_entries in sides:
                if len(entries) > 1:
                    # a linha única do outro lado (se houver) é vinculada para dar contexto
                    other_row = other_entries[0][0] if len(other_entries) == 1 else None
                    for row_number, _, _ in entries:
                        out.counts[f"duplicate_key_{label}"] += 1
                        sink(ResultItem(f"duplicate_key_{label}", display, **{f"row_{label}": row_number, f"row_{other}": other_row},
                                        note=f"Chave repetida {len(entries)} vezes no arquivo {label.upper()}; correspondência ambígua."))
            continue
        if not entries_b:
            out.counts["only_a"] += 1
            sink(ResultItem("only_a", display, row_a=entries_a[0][0]))
            continue
        (row_a, va, _), (row_b, vb, _) = entries_a[0], entries_b[0]
        diffs = []
        for pair, a, b in zip(config.compare_pairs, va, vb, strict=True):
            d = _compare_values(pair, a, b, config.null_vs_value, config.text_normalization)
            if d is not None:
                out.field_divergences[f"{pair.column_a} ↔ {pair.column_b}"] += 1
                diffs.append({"column_a": pair.column_a, "column_b": pair.column_b,
                              "value_a": to_text(a)[:120], "value_b": to_text(b)[:120], **d})
        if diffs:
            out.counts["mismatch"] += 1
            sink(ResultItem("mismatch", display, row_a=row_a, row_b=row_b, differences=diffs))
        else:
            out.counts["match"] += 1
            if include_matches:
                sink(ResultItem("match", display, row_a=row_a, row_b=row_b))

    for key, entries_b in idx_b.items():
        if key in idx_a:
            continue
        if len(entries_b) > 1:
            for row_number, _, display in entries_b:
                out.counts["duplicate_key_b"] += 1
                sink(ResultItem("duplicate_key_b", display, row_b=row_number,
                                note=f"Chave repetida {len(entries_b)} vezes no arquivo B; correspondência ambígua."))
            continue
        out.counts["only_b"] += 1
        sink(ResultItem("only_b", entries_b[0][2], row_b=entries_b[0][0]))
    return out
