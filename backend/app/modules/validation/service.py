from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.domain.validation.conditions import ConditionGroup
from app.domain.validation.engine import RuleSpec
from app.domain.validation.rules import REGISTRY, parse_params
from app.domain.values import normalize_name
from app.modules.validation.models import ValidationRule

GLOBAL_RULES: list[dict[str, Any]] = [
    {"rule_key": "global-cpf-cnpj-valido", "name": "CPF/CNPJ do fornecedor/cliente válido", "rule_type": "format",
     "params": {"field": "counterparty_tax_id", "format": "cpf_cnpj"}, "severity": "error",
     "description": "Verifica os dígitos verificadores de CPF/CNPJ."},
    {"rule_key": "global-valor-numerico", "name": "Valor numérico", "rule_type": "data_type",
     "params": {"field": "amount", "type": "decimal"}, "severity": "error", "description": "O valor deve ser numérico."},
    {"rule_key": "global-emissao-valida", "name": "Data de emissão válida", "rule_type": "valid_date",
     "params": {"field": "issue_date"}, "severity": "error", "description": "A data de emissão deve existir no calendário."},
    {"rule_key": "global-vencimento-apos-emissao", "name": "Vencimento não anterior à emissão", "rule_type": "custom",
     "params": {"assert": {"all": [{"field": "due_date", "op": "gte", "value_field": "issue_date"}]}}, "severity": "warning",
     "description": "A data de vencimento não deve ser anterior à data de emissão."},
    {"rule_key": "global-documento-unico", "name": "Número do documento único", "rule_type": "unique_key",
     "params": {"fields": ["document_number"]}, "severity": "error", "description": "Cada documento deve aparecer uma única vez."},
]


def ensure_global_rules(db: Session) -> None:
    existing = set(db.scalars(select(ValidationRule.rule_key).where(ValidationRule.organization_id.is_(None))))
    for r in GLOBAL_RULES:
        if r["rule_key"] not in existing:
            db.add(ValidationRule(organization_id=None, version=1, category=REGISTRY[r["rule_type"]].category,
                                  status="active", is_current=True, **r))
    db.flush()


def validate_definition(rule_type: str, params: dict[str, Any], applies_when: dict[str, Any] | None) -> dict[str, Any]:
    """Valida parâmetros; devolve os parâmetros normalizados ou lança ValidationFailed com detalhes."""
    if rule_type not in REGISTRY:
        raise ValidationFailed(f"Tipo de regra desconhecido: {rule_type}.")
    try:
        parsed = parse_params(rule_type, params)
        if applies_when:
            ConditionGroup.model_validate(applies_when)
    except ValidationError as exc:
        raise ValidationFailed("Parâmetros inválidos.", details=[
            {"loc": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors(include_url=False, include_input=False)
        ]) from exc
    except ValueError as exc:
        raise ValidationFailed("Parâmetros inválidos.", details=[{"loc": "", "message": str(exc)}]) from exc
    return parsed.model_dump(mode="json", by_alias=True, exclude_none=True)


def new_rule_key(name: str) -> str:
    slug = re.sub(r"\s+", "-", normalize_name(name))[:50] or "regra"
    return f"{slug}-{uuid.uuid4().hex[:8]}"


def current_rules_query(org_id: uuid.UUID, include_global: bool = True):
    scope = ValidationRule.organization_id == org_id
    if include_global:
        scope = or_(scope, ValidationRule.organization_id.is_(None))
    return select(ValidationRule).where(scope, ValidationRule.is_current.is_(True))


def applicable_rules(db: Session, org_id: uuid.UUID, client_id: uuid.UUID, profile_id: uuid.UUID,
                     rule_ids: list[uuid.UUID] | None) -> list[ValidationRule]:
    """Regras de uma execução: as indicadas explicitamente (versões atuais) ou, se ``None``, as ativas no escopo.

    Lista vazia significa "nenhuma regra configurada" (apenas as derivadas do mapeamento).
    """
    if rule_ids is not None:
        if not rule_ids:
            return []
        rules = db.scalars(current_rules_query(org_id).where(ValidationRule.id.in_(rule_ids))).all()
        found = {r.id for r in rules}
        missing = [str(i) for i in rule_ids if i not in found]
        if missing:
            raise ValidationFailed("Regras inexistentes ou desatualizadas (use a versão atual).", details=missing)
        return [r for r in rules if r.status == "active"]
    stmt = current_rules_query(org_id, include_global=False).where(
        ValidationRule.status == "active",
        or_(ValidationRule.client_account_id.is_(None), ValidationRule.client_account_id == client_id),
        or_(ValidationRule.profile_id.is_(None), ValidationRule.profile_id == profile_id),
    )
    return list(db.scalars(stmt))


def to_spec(rule: ValidationRule) -> RuleSpec:
    return RuleSpec(rule_key=rule.rule_key, rule_type=rule.rule_type, params=rule.params, severity=rule.severity,  # type: ignore[arg-type]
                    name=rule.name, version=rule.version, rule_id=str(rule.id), applies_when=rule.applies_when,
                    message=rule.message)
