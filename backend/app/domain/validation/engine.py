"""Motor de validação: aplica especificações de regra a um fluxo de registros."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.domain.canonical_fields import FIELDS_BY_KEY
from app.domain.mapping.entries import Record
from app.domain.validation.conditions import ConditionGroup, evaluate
from app.domain.validation.rules import REGISTRY, RuleContext, RuleType, Severity, Violation, parse_params
from app.domain.values import mask_value, to_text

MAX_OBSERVED_LEN = 120


@dataclass
class RuleSpec:
    """Instância configurada de uma regra (versão imutável)."""

    rule_key: str
    rule_type: str
    params: dict[str, Any]
    severity: Severity = "error"
    name: str = ""
    version: int = 1
    rule_id: str | None = None
    applies_when: dict[str, Any] | None = None
    message: str | None = None


@dataclass
class Finding:
    rule_key: str
    rule_version: int
    rule_id: str | None
    rule_type: str
    severity: Severity
    message: str
    row_number: int | None
    field: str | None
    observed_value: str | None
    record_key: str | None
    evidence: dict[str, Any]


@dataclass
class RuleStats:
    rule_key: str
    rule_type: str
    version: int
    severity: str
    violations: int = 0
    stored: int = 0
    skipped_reason: str | None = None


@dataclass
class EngineResult:
    records: int = 0
    counts: Counter[str] = field(default_factory=Counter)
    rules: list[RuleStats] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "records": self.records,
            "errors": self.counts["error"],
            "warnings": self.counts["warning"],
            "infos": self.counts["info"],
            "rules": [s.__dict__ for s in self.rules],
        }


class _Bound:
    def __init__(self, spec: RuleSpec, impl: RuleType, when: ConditionGroup | None, stats: RuleStats):
        self.spec, self.impl, self.when, self.stats = spec, impl, when, stats


def _sensitive(field_key: str | None) -> bool:
    f = FIELDS_BY_KEY.get(field_key or "")
    return bool(f and (f.sensitive and f.data_type == "tax_id" or f.key == "bank_account"))


class ValidationEngine:
    """Uso: ``engine.run(records)``; achados são entregues ao ``sink`` à medida que surgem."""

    def __init__(
        self,
        specs: list[RuleSpec],
        *,
        mapped_fields: set[str],
        sink: Callable[[Finding], None],
        ctx: RuleContext | None = None,
        max_findings_per_rule: int = 5000,
        record_key_fields: tuple[str, ...] = ("document_number", "invoice_number", "external_id"),
        mask_sensitive: bool = True,
    ):
        self.ctx = ctx or RuleContext(mapped_fields=mapped_fields)
        self.ctx.mapped_fields = mapped_fields
        self.sink = sink
        self.max_per_rule = max_findings_per_rule
        self.key_field = next((f for f in record_key_fields if f in mapped_fields), None)
        self.mask = mask_sensitive
        self.result = EngineResult()
        self.bound: list[_Bound] = []
        for spec in specs:
            stats = RuleStats(spec.rule_key, spec.rule_type, spec.version, spec.severity)
            self.result.rules.append(stats)
            cls = REGISTRY.get(spec.rule_type)
            if cls is None:
                stats.skipped_reason = "tipo de regra desconhecido"
                continue
            params = parse_params(spec.rule_type, spec.params)
            when = ConditionGroup.model_validate(spec.applies_when) if spec.applies_when else None
            impl = cls(params, self.ctx, spec.rule_key)
            needed = impl.fields() | (when.fields() if when else set())
            missing = sorted(needed - mapped_fields)
            if missing:
                if spec.rule_type == "required":
                    # Campo obrigatório que nem existe no layout: um único achado no nível do arquivo.
                    self._emit(_Bound(spec, impl, None, stats), Violation(
                        f"Campo obrigatório '{missing[0]}' não está mapeado neste arquivo.", None, missing[0]), None)
                    stats.skipped_reason = "campo não mapeado (achado único registrado)"
                else:
                    stats.skipped_reason = f"campos não mapeados: {', '.join(missing)}"
                continue
            self.bound.append(_Bound(spec, impl, when, stats))

    def _emit(self, b: _Bound, v: Violation, record: Record | None) -> None:
        b.stats.violations += 1
        self.result.counts[b.spec.severity] += 1
        if b.stats.stored >= self.max_per_rule:
            return
        b.stats.stored += 1
        observed = None
        if v.observed is not None:
            observed = mask_value(v.observed, kind="tax_id" if _sensitive(v.field) else None, max_len=MAX_OBSERVED_LEN) \
                if self.mask else to_text(v.observed)[:MAX_OBSERVED_LEN]
        record_key = to_text(record.raw(self.key_field))[:120] if record is not None and self.key_field else None
        message = v.message
        if b.spec.message:
            message = f"{b.spec.message} ({v.message})"
        self.sink(Finding(
            rule_key=b.spec.rule_key, rule_version=b.spec.version, rule_id=b.spec.rule_id, rule_type=b.spec.rule_type,
            severity=b.spec.severity, message=message, row_number=v.row_number, field=v.field,
            observed_value=observed, record_key=record_key or None, evidence=v.evidence,
        ))

    def process(self, record: Record) -> None:
        self.result.records += 1
        for b in self.bound:
            if b.when is not None and not evaluate(b.when, record):
                continue
            for v in b.impl.check(record):
                self._emit(b, v, record)

    def finish(self) -> EngineResult:
        for b in self.bound:
            for v in b.impl.finalize():
                self._emit(b, v, None)
        return self.result

    def run(self, records: Iterable[Record]) -> EngineResult:
        for r in records:
            self.process(r)
        return self.finish()
