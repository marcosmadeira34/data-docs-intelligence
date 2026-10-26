"""Catálogo de tipos de regra de validação declarativos e determinísticos.

Cada tipo define um modelo de parâmetros (validado antes de salvar) e uma
implementação que produz violações com evidência. Nenhum tipo executa código
fornecido pelo usuário; expressões regulares são restritas e validadas.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.mapping.entries import Record
from app.domain.validation.conditions import ConditionGroup, evaluate
from app.domain.values import FORMAT_CHECKS, is_blank, parse_typed, strip_accents, to_text

Severity = Literal["error", "warning", "info"]
FieldName = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")


@dataclass
class Violation:
    message: str
    row_number: int | None = None
    field: str | None = None
    observed: Any = None
    evidence: dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class RuleContext:
    """Dados externos disponíveis para as regras (ex.: valores de arquivo de referência)."""

    reference_sets: dict[str, set[str]] = dc_field(default_factory=dict)
    mapped_fields: set[str] = dc_field(default_factory=set)


class RuleType:
    key: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str]
    category: ClassVar[str]
    scope: ClassVar[Literal["row", "dataset", "cross_file"]] = "row"
    Params: ClassVar[type[BaseModel]]

    def __init__(self, params: BaseModel, ctx: RuleContext, rule_key: str):
        self.p = params
        self.ctx = ctx
        self.rule_key = rule_key

    def fields(self) -> set[str]:
        raise NotImplementedError

    def check(self, record: Record) -> list[Violation]:
        return []

    def finalize(self) -> list[Violation]:
        return []


REGISTRY: dict[str, type[RuleType]] = {}


def register(cls: type[RuleType]) -> type[RuleType]:
    REGISTRY[cls.key] = cls
    return cls


def _key_digest(parts: list[str]) -> bytes:
    return hashlib.blake2b("\x1f".join(parts).encode(), digest_size=12).digest()


def _norm(v: Any) -> str:
    return strip_accents(to_text(v)).strip().lower()


# --------------------------------------------------------------------------- 1. obrigatório


@register
class RequiredRule(RuleType):
    key = "required"
    label = "Campo obrigatório"
    description = "O campo deve estar preenchido em todos os registros."
    category = "completude"

    class Params(BaseModel):
        field: str = FieldName

    def fields(self) -> set[str]:
        return {self.p.field}

    def check(self, record: Record) -> list[Violation]:
        if is_blank(record.raw(self.p.field)):
            return [Violation("Campo obrigatório não preenchido.", record.row_number, self.p.field)]
        return []


# --------------------------------------------------------------------------- 2. tipo de dado


@register
class DataTypeRule(RuleType):
    key = "data_type"
    label = "Tipo de dado"
    description = "O valor deve ser interpretável como o tipo informado."
    category = "tipo"

    class Params(BaseModel):
        field: str = FieldName
        type: Literal["integer", "decimal", "date", "boolean", "tax_id", "text"]

    def fields(self) -> set[str]:
        return {self.p.field}

    def check(self, record: Record) -> list[Violation]:
        raw = record.raw(self.p.field)
        if is_blank(raw):
            return []
        _, ok = parse_typed(raw, self.p.type)
        if not ok:
            names = {"integer": "inteiro", "decimal": "numérico", "date": "data", "boolean": "sim/não", "tax_id": "CPF/CNPJ", "text": "texto"}
            return [Violation(f"Valor não é um {names[self.p.type]} válido.", record.row_number, self.p.field, raw,
                              {"expected_type": self.p.type})]
        return []


# --------------------------------------------------------------------------- 3. formato


@register
class FormatRule(RuleType):
    key = "format"
    label = "Formato"
    description = "Valida formatos conhecidos (CPF, CNPJ, e-mail, CEP, UF...), incluindo dígitos verificadores."
    category = "formato"

    class Params(BaseModel):
        field: str = FieldName
        format: Literal["cpf", "cnpj", "cpf_cnpj", "email", "cep", "uf", "digits", "phone_br"]

    def fields(self) -> set[str]:
        return {self.p.field}

    def check(self, record: Record) -> list[Violation]:
        raw = record.raw(self.p.field)
        if is_blank(raw):
            return []
        if not FORMAT_CHECKS[self.p.format](raw):
            return [Violation(f"Valor não corresponde ao formato {self.p.format.upper()}.", record.row_number, self.p.field, raw,
                              {"format": self.p.format})]
        return []


# --------------------------------------------------------------------------- 4. intervalo numérico


@register
class RangeRule(RuleType):
    key = "range"
    label = "Intervalo numérico"
    description = "O valor numérico deve estar entre o mínimo e o máximo informados."
    category = "intervalo"

    class Params(BaseModel):
        field: str = FieldName
        min: Decimal | None = None
        max: Decimal | None = None
        exclusive_min: bool = False

        @model_validator(mode="after")
        def _bounds(self):
            if self.min is None and self.max is None:
                raise ValueError("informe 'min' e/ou 'max'")
            if self.min is not None and self.max is not None and self.min > self.max:
                raise ValueError("'min' não pode ser maior que 'max'")
            return self

    def fields(self) -> set[str]:
        return {self.p.field}

    def check(self, record: Record) -> list[Violation]:
        v = record.get(self.p.field)
        if not isinstance(v, (Decimal, int)) or isinstance(v, bool):
            return []
        p = self.p
        below = p.min is not None and (v <= p.min if p.exclusive_min else v < p.min)
        above = p.max is not None and v > p.max
        if below or above:
            return [Violation("Valor fora do intervalo permitido.", record.row_number, p.field, record.raw(p.field),
                              {"min": str(p.min) if p.min is not None else None, "max": str(p.max) if p.max is not None else None,
                               "exclusive_min": p.exclusive_min})]
        return []


# --------------------------------------------------------------------------- 5. data válida


@register
class ValidDateRule(RuleType):
    key = "valid_date"
    label = "Data válida"
    description = "O valor deve ser uma data existente, opcionalmente dentro de um período."
    category = "data"

    class Params(BaseModel):
        field: str = FieldName
        min_date: date | None = None
        max_date: date | None = None
        not_in_future: bool = False

    def fields(self) -> set[str]:
        return {self.p.field}

    def check(self, record: Record) -> list[Violation]:
        raw = record.raw(self.p.field)
        if is_blank(raw):
            return []
        v = record.get(self.p.field)
        if not isinstance(v, date):
            v, ok = parse_typed(raw, "date")
            if not ok:
                return [Violation("Data inválida ou inexistente.", record.row_number, self.p.field, raw)]
        p = self.p
        if (p.min_date and v < p.min_date) or (p.max_date and v > p.max_date):
            return [Violation("Data fora do período permitido.", record.row_number, p.field, raw,
                              {"min_date": str(p.min_date) if p.min_date else None, "max_date": str(p.max_date) if p.max_date else None})]
        if p.not_in_future and v > date.today():
            return [Violation("Data no futuro.", record.row_number, p.field, raw)]
        return []


# --------------------------------------------------------------------------- 6. valores permitidos


@register
class AllowedValuesRule(RuleType):
    key = "allowed_values"
    label = "Valores permitidos"
    description = "O valor deve pertencer a uma lista fechada."
    category = "domínio"

    class Params(BaseModel):
        field: str = FieldName
        values: list[str] = Field(min_length=1, max_length=500)
        case_sensitive: bool = False

    def __init__(self, params, ctx, rule_key):
        super().__init__(params, ctx, rule_key)
        self._allowed = set(params.values) if params.case_sensitive else {_norm(v) for v in params.values}

    def fields(self) -> set[str]:
        return {self.p.field}

    def check(self, record: Record) -> list[Violation]:
        raw = record.raw(self.p.field)
        if is_blank(raw):
            return []
        v = to_text(raw).strip() if self.p.case_sensitive else _norm(raw)
        if v not in self._allowed:
            return [Violation("Valor não pertence à lista de valores permitidos.", record.row_number, self.p.field, raw,
                              {"allowed": self.p.values[:20]})]
        return []


# --------------------------------------------------------------------------- 7. duplicidade / 10. chave única


class _KeyTracker:
    def __init__(self) -> None:
        self.first_seen: dict[bytes, int] = {}

    def seen(self, parts: list[str], row: int) -> int | None:
        k = _key_digest(parts)
        first = self.first_seen.get(k)
        if first is None:
            self.first_seen[k] = row
        return first


class _FieldsParams(BaseModel):
    fields: list[str] = Field(min_length=1, max_length=6)

    @field_validator("fields")
    @classmethod
    def _names(cls, v: list[str]) -> list[str]:
        for f in v:
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", f):
                raise ValueError(f"nome de campo inválido: {f!r}")
        if len(set(v)) != len(v):
            raise ValueError("campos repetidos")
        return v


@register
class DuplicateRule(RuleType):
    key = "duplicate"
    label = "Duplicidade"
    description = "Detecta registros repetidos considerando um campo ou uma combinação de campos."
    category = "duplicidade"
    Params = _FieldsParams

    def __init__(self, params, ctx, rule_key):
        super().__init__(params, ctx, rule_key)
        self.tracker = _KeyTracker()

    def fields(self) -> set[str]:
        return set(self.p.fields)

    def check(self, record: Record) -> list[Violation]:
        parts = [_norm(record.raw(f)) for f in self.p.fields]
        if all(not p for p in parts):
            return []
        first = self.tracker.seen(parts, record.row_number)
        if first is not None:
            return [Violation(f"Registro duplicado (mesma combinação já vista na linha {first}).", record.row_number,
                              self.p.fields[0], " | ".join(to_text(record.raw(f)) for f in self.p.fields),
                              {"first_row": first, "fields": self.p.fields})]
        return []


@register
class UniqueKeyRule(RuleType):
    key = "unique_key"
    label = "Chave única"
    description = "Os campos da chave devem estar preenchidos e não podem se repetir."
    category = "duplicidade"
    Params = _FieldsParams

    def __init__(self, params, ctx, rule_key):
        super().__init__(params, ctx, rule_key)
        self.tracker = _KeyTracker()

    def fields(self) -> set[str]:
        return set(self.p.fields)

    def check(self, record: Record) -> list[Violation]:
        raws = [record.raw(f) for f in self.p.fields]
        missing = [f for f, r in zip(self.p.fields, raws, strict=True) if is_blank(r)]
        if missing:
            return [Violation("Chave incompleta: campo(s) da chave sem valor.", record.row_number, missing[0], None,
                              {"missing_fields": missing})]
        first = self.tracker.seen([_norm(r) for r in raws], record.row_number)
        if first is not None:
            return [Violation(f"Chave repetida (já usada na linha {first}).", record.row_number, self.p.fields[0],
                              " | ".join(to_text(r) for r in raws), {"first_row": first, "fields": self.p.fields})]
        return []


# --------------------------------------------------------------------------- 8. expressão regular restrita

_FORBIDDEN_REGEX = [
    (re.compile(r"\\[1-9]"), "referências anteriores (\\1) não são permitidas"),
    (re.compile(r"\(\?(?:=|!|<=|<!|P=|\()"), "lookahead/lookbehind/condicionais não são permitidos"),
    (re.compile(r"\([^()]*[+*][^()]*\)\s*[+*{]"), "quantificadores aninhados não são permitidos"),
    (re.compile(r"\{\s*\d{4,}"), "repetições acima de 999 não são permitidas"),
]
MAX_REGEX_INPUT = 500


def validate_safe_regex(pattern: str) -> re.Pattern[str]:
    if len(pattern) > 200:
        raise ValueError("a expressão regular deve ter no máximo 200 caracteres")
    for rx, msg in _FORBIDDEN_REGEX:
        if rx.search(pattern):
            raise ValueError(msg)
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"expressão regular inválida: {exc}") from exc


@register
class RegexRule(RuleType):
    key = "regex"
    label = "Expressão regular"
    description = "O valor deve (ou não deve) corresponder a um padrão. Padrões perigosos são rejeitados."
    category = "formato"

    class Params(BaseModel):
        field: str = FieldName
        pattern: str = Field(min_length=1, max_length=200)
        must_match: bool = True

        @field_validator("pattern")
        @classmethod
        def _safe(cls, v: str) -> str:
            validate_safe_regex(v)
            return v

    def __init__(self, params, ctx, rule_key):
        super().__init__(params, ctx, rule_key)
        self.rx = validate_safe_regex(params.pattern)

    def fields(self) -> set[str]:
        return {self.p.field}

    def check(self, record: Record) -> list[Violation]:
        raw = record.raw(self.p.field)
        if is_blank(raw):
            return []
        text = to_text(raw)[:MAX_REGEX_INPUT]
        matched = self.rx.fullmatch(text) is not None
        if matched != self.p.must_match:
            msg = "Valor não corresponde ao padrão exigido." if self.p.must_match else "Valor corresponde a um padrão proibido."
            return [Violation(msg, record.row_number, self.p.field, raw, {"pattern": self.p.pattern})]
        return []


# --------------------------------------------------------------------------- 9. dependência entre campos


@register
class DependencyRule(RuleType):
    key = "dependency"
    label = "Dependência entre campos"
    description = "Quando a condição 'quando' for verdadeira, a condição 'então' deve ser verdadeira."
    category = "consistência"

    class Params(BaseModel):
        when: ConditionGroup
        then: ConditionGroup

    def fields(self) -> set[str]:
        return self.p.when.fields() | self.p.then.fields()

    def check(self, record: Record) -> list[Violation]:
        if evaluate(self.p.when, record) and not evaluate(self.p.then, record):
            target = sorted(self.p.then.fields())[0]
            return [Violation("Dependência entre campos não atendida.", record.row_number, target, record.raw(target))]
        return []


# --------------------------------------------------------------------------- 11. totais x itens


@register
class TotalConsistencyRule(RuleType):
    key = "total_consistency"
    label = "Consistência entre totais e itens"
    description = ("Modo 'row': total da linha = soma dos campos informados. "
                   "Modo 'group': soma dos itens de cada grupo = total informado no grupo.")
    category = "consistência"

    class Params(BaseModel):
        mode: Literal["row", "group"]
        total_field: str = FieldName
        item_fields: list[str] = Field(default_factory=list, max_length=10)
        item_field: str | None = None
        group_by: list[str] = Field(default_factory=list, max_length=4)
        tolerance: Decimal = Field(default=Decimal("0.01"), ge=0)

        @model_validator(mode="after")
        def _mode(self):
            if self.mode == "row" and not self.item_fields:
                raise ValueError("o modo 'row' exige 'item_fields'")
            if self.mode == "group" and (not self.item_field or not self.group_by):
                raise ValueError("o modo 'group' exige 'item_field' e 'group_by'")
            return self

    def __init__(self, params, ctx, rule_key):
        super().__init__(params, ctx, rule_key)
        self.groups: dict[tuple[str, ...], dict[str, Any]] = {}

    @property
    def scope(self):  # type: ignore[override]
        return "row" if self.p.mode == "row" else "dataset"

    def fields(self) -> set[str]:
        if self.p.mode == "row":
            return {self.p.total_field, *self.p.item_fields}
        return {self.p.total_field, self.p.item_field, *self.p.group_by}

    def check(self, record: Record) -> list[Violation]:
        p = self.p
        total = record.get(p.total_field)
        if p.mode == "row":
            items = [record.get(f) for f in p.item_fields]
            if not isinstance(total, Decimal) or any(i is not None and not isinstance(i, (Decimal, int)) for i in items):
                return []
            s = sum((Decimal(i) for i in items if i is not None), Decimal(0))
            if abs(s - total) > p.tolerance:
                return [Violation("Total da linha difere da soma dos itens.", record.row_number, p.total_field, total,
                                  {"sum_items": str(s), "total": str(total), "difference": str(s - total)})]
            return []
        key = tuple(_norm(record.raw(f)) for f in p.group_by)
        g = self.groups.setdefault(key, {"sum": Decimal(0), "total": None, "first_row": record.row_number, "rows": 0, "conflict": False})
        g["rows"] += 1
        item = record.get(p.item_field)
        if isinstance(item, (Decimal, int)):
            g["sum"] += Decimal(item)
        if isinstance(total, Decimal):
            if g["total"] is None:
                g["total"] = total
            elif g["total"] != total:
                g["conflict"] = True
        return []

    def finalize(self) -> list[Violation]:
        out = []
        for key, g in self.groups.items():
            label = " | ".join(key)
            if g["conflict"]:
                out.append(Violation("O grupo informa totais diferentes em linhas distintas.", g["first_row"], self.p.total_field,
                                     None, {"group": label, "rows": g["rows"]}))
            elif g["total"] is not None and abs(g["sum"] - g["total"]) > self.p.tolerance:
                out.append(Violation("Soma dos itens do grupo difere do total informado.", g["first_row"], self.p.total_field,
                                     g["total"], {"group": label, "sum_items": str(g["sum"]), "total": str(g["total"]),
                                                  "difference": str(g["sum"] - g["total"]), "rows": g["rows"]}))
        return out


# --------------------------------------------------------------------------- 12. consistência entre arquivos


@register
class CrossFileRule(RuleType):
    key = "cross_file"
    label = "Consistência entre arquivos"
    description = "O valor deve existir em uma coluna de um arquivo de referência (ex.: cadastro de fornecedores)."
    category = "consistência"
    scope = "cross_file"

    class Params(BaseModel):
        field: str = FieldName
        reference_file_id: str = Field(min_length=1, max_length=64)
        reference_column: str = Field(min_length=1, max_length=255)
        normalize: list[Literal["trim", "upper", "digits_only"]] = Field(default_factory=lambda: ["trim", "upper"])

    def fields(self) -> set[str]:
        return {self.p.field}

    def check(self, record: Record) -> list[Violation]:
        raw = record.raw(self.p.field)
        if is_blank(raw):
            return []
        ref = self.ctx.reference_sets.get(self.rule_key)
        if ref is None:
            return []
        if normalize_reference(raw, self.p.normalize) not in ref:
            return [Violation("Valor não encontrado no arquivo de referência.", record.row_number, self.p.field, raw,
                              {"reference_file_id": self.p.reference_file_id, "reference_column": self.p.reference_column})]
        return []


def normalize_reference(value: Any, steps: list[str]) -> str:
    text = to_text(value)
    if "trim" in steps:
        text = text.strip()
    if "upper" in steps:
        text = strip_accents(text).upper()
    if "digits_only" in steps:
        text = re.sub(r"\D", "", text)
    return text


# --------------------------------------------------------------------------- 13. completude mínima


@register
class CompletenessRule(RuleType):
    key = "completeness"
    label = "Completude mínima"
    description = "Percentual mínimo de registros com o campo preenchido."
    category = "completude"
    scope = "dataset"

    class Params(BaseModel):
        field: str = FieldName
        min_ratio: float = Field(ge=0, le=1)

    def __init__(self, params, ctx, rule_key):
        super().__init__(params, ctx, rule_key)
        self.total = 0
        self.filled = 0

    def fields(self) -> set[str]:
        return {self.p.field}

    def check(self, record: Record) -> list[Violation]:
        self.total += 1
        if not is_blank(record.raw(self.p.field)):
            self.filled += 1
        return []

    def finalize(self) -> list[Violation]:
        if not self.total:
            return []
        ratio = self.filled / self.total
        if ratio < self.p.min_ratio:
            return [Violation(f"Completude de {ratio:.1%} abaixo do mínimo de {self.p.min_ratio:.0%}.", None, self.p.field, None,
                              {"filled": self.filled, "total": self.total, "ratio": round(ratio, 4), "min_ratio": self.p.min_ratio})]
        return []


# --------------------------------------------------------------------------- 14. personalizada declarativa


@register
class CustomRule(RuleType):
    key = "custom"
    label = "Regra personalizada"
    description = "Condição declarativa: quando 'when' (opcional) for verdadeira, 'assert' deve ser verdadeira."
    category = "personalizada"

    class Params(BaseModel):
        when: ConditionGroup | None = None
        assert_: ConditionGroup = Field(alias="assert")
        model_config = {"populate_by_name": True}

    def fields(self) -> set[str]:
        return (self.p.when.fields() if self.p.when else set()) | self.p.assert_.fields()

    def check(self, record: Record) -> list[Violation]:
        if self.p.when is not None and not evaluate(self.p.when, record):
            return []
        if not evaluate(self.p.assert_, record):
            target = sorted(self.p.assert_.fields())[0]
            return [Violation("Condição personalizada não atendida.", record.row_number, target, record.raw(target))]
        return []


def parse_params(rule_type: str, params: dict[str, Any]) -> BaseModel:
    cls = REGISTRY.get(rule_type)
    if cls is None:
        raise ValueError(f"tipo de regra desconhecido: {rule_type!r}")
    return cls.Params.model_validate(params)


def catalog() -> list[dict[str, Any]]:
    return [
        {"type": c.key, "label": c.label, "description": c.description, "category": c.category,
         "scope": c.scope if isinstance(c.scope, str) else "row", "params_schema": c.Params.model_json_schema(by_alias=True)}
        for c in REGISTRY.values()
    ]
