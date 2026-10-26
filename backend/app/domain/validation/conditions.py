"""Condições declarativas (sem execução de código) usadas por regras.

Exemplo: {"all": [{"field": "status", "op": "eq", "value": "pago"},
                  {"field": "payment_date", "op": "is_null"}]}
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.mapping.entries import Record
from app.domain.values import is_blank, parse_date, parse_decimal, strip_accents, to_text

Operator = Literal[
    "eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "not_null",
    "contains", "starts_with", "ends_with",
]
_UNARY = {"is_null", "not_null"}
MAX_DEPTH = 3
MAX_CONDITIONS = 20


class Condition(BaseModel):
    field: str = Field(min_length=1, max_length=64)
    op: Operator
    value: Any = None
    value_field: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _check(self) -> Condition:
        if self.op in _UNARY:
            return self
        if self.value_field is None and self.value is None:
            raise ValueError(f"o operador {self.op!r} exige 'value' ou 'value_field'")
        if self.op in ("in", "not_in"):
            if not isinstance(self.value, list) or not 1 <= len(self.value) <= 500:
                raise ValueError("'in'/'not_in' exige uma lista com 1 a 500 valores")
        elif isinstance(self.value, (list, dict)):
            raise ValueError(f"o operador {self.op!r} exige um valor simples")
        return self


class ConditionGroup(BaseModel):
    all: list[Condition | ConditionGroup] | None = None
    any: list[Condition | ConditionGroup] | None = None

    @model_validator(mode="after")
    def _check(self) -> ConditionGroup:
        if (self.all is None) == (self.any is None):
            raise ValueError("o grupo de condições deve ter exatamente uma chave: 'all' ou 'any'")
        items = self.all if self.all is not None else self.any
        if not items:
            raise ValueError("o grupo de condições não pode ser vazio")
        if _depth(self) > MAX_DEPTH:
            raise ValueError(f"profundidade máxima de condições é {MAX_DEPTH}")
        if _count(self) > MAX_CONDITIONS:
            raise ValueError(f"no máximo {MAX_CONDITIONS} condições por grupo")
        return self

    def fields(self) -> set[str]:
        out: set[str] = set()
        for item in (self.all or self.any or []):
            if isinstance(item, Condition):
                out.add(item.field)
                if item.value_field:
                    out.add(item.value_field)
            else:
                out |= item.fields()
        return out


def _depth(g: ConditionGroup) -> int:
    items = g.all or g.any or []
    return 1 + max((_depth(i) for i in items if isinstance(i, ConditionGroup)), default=0)


def _count(g: ConditionGroup) -> int:
    return sum(_count(i) if isinstance(i, ConditionGroup) else 1 for i in (g.all or g.any or []))


def _norm_text(v: Any) -> str:
    return strip_accents(to_text(v)).strip().lower()


def _coerce(target: Any, value: Any) -> Any:
    """Converte o literal para o tipo do valor do registro."""
    if isinstance(target, bool):
        return value
    if isinstance(target, (Decimal, int)):
        return parse_decimal(value) if not isinstance(value, (int, float, Decimal)) else Decimal(str(value))
    if isinstance(target, date):
        return parse_date(value)
    return _norm_text(value)


def _cmp_operands(left: Any, right: Any) -> tuple[Any, Any]:
    if isinstance(left, (Decimal, int)) and not isinstance(left, bool):
        return Decimal(left), _coerce(left, right)
    if isinstance(left, date):
        return left, _coerce(left, right)
    return _norm_text(left), _norm_text(right)


def evaluate(cond: Condition | ConditionGroup, record: Record) -> bool:
    if isinstance(cond, ConditionGroup):
        if cond.all is not None:
            return all(evaluate(c, record) for c in cond.all)
        return any(evaluate(c, record) for c in cond.any or [])
    left = record.get(cond.field)
    if cond.op == "is_null":
        return is_blank(record.raw(cond.field))
    if cond.op == "not_null":
        return not is_blank(record.raw(cond.field))
    if left is None:
        return False
    right = record.get(cond.value_field) if cond.value_field else cond.value
    if right is None:
        return False
    if cond.op in ("in", "not_in"):
        values = right if isinstance(right, list) else [right]
        member = any(_cmp_operands(left, v)[0] == _cmp_operands(left, v)[1] for v in values)
        return member if cond.op == "in" else not member
    a, b = _cmp_operands(left, right)
    if b is None:
        return False
    try:
        match cond.op:
            case "eq":
                return a == b
            case "ne":
                return a != b
            case "gt":
                return a > b
            case "gte":
                return a >= b
            case "lt":
                return a < b
            case "lte":
                return a <= b
            case "contains":
                return str(b) in str(a)
            case "starts_with":
                return str(a).startswith(str(b))
            case "ends_with":
                return str(a).endswith(str(b))
    except TypeError:
        return False
    return False
