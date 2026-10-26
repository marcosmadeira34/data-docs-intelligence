"""Comandos operacionais.

python -m app.cli bootstrap        # planos e regras globais (idempotente)
python -m app.cli seed-demo        # organização, usuários, empresas e arquivos sintéticos
python -m app.cli purge-retention  # aplica a política de retenção agora
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.demo.synthetic import generate_demo_files
from app.infrastructure.database import models as _all_models  # noqa: F401  (registra todas as tabelas no metadata)
from app.domain.mapping.entries import MappingEntry
from app.infrastructure.database.session import session_scope
from app.modules.billing import service as billing
from app.modules.clients.models import ClientAccount
from app.modules.comparison.models import ComparisonJob
from app.modules.files import service as files_service
from app.modules.organizations.models import Membership, Organization, User
from app.modules.profiles import service as profiles_service
from app.modules.validation import service as rules_service
from app.modules.validation.models import ValidationRule

DEMO_PASSWORD_ENV = "DDI_DEMO_PASSWORD"


def bootstrap() -> None:
    with session_scope() as db:
        billing.ensure_default_plans(db)
        rules_service.ensure_global_rules(db)
    print("bootstrap concluído: planos e regras globais disponíveis")


class _Ctx:
    def __init__(self, user: User, org: Organization):
        self.user, self.organization = user, org

    @property
    def org_id(self):
        return self.organization.id


def _org_with_owner(db, org_name: str, name: str, email: str, password: str) -> tuple[Organization, User]:
    org = Organization(name=org_name)
    user = User(name=name, email=email, password_hash=hash_password(password))
    db.add_all([org, user])
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
    billing.start_trial(db, org.id)
    return org, user


def seed_demo() -> None:
    from app.modules.comparison.router import run_comparison_now
    from app.modules.processing import service as processing_service
    from app.modules.processing.router import run_job_now

    password = os.environ.get(DEMO_PASSWORD_ENV, "Demo-2024-segura")
    bootstrap()
    with session_scope() as db:
        if db.scalar(select(User.id).where(User.email == "demo@exemplo.com.br")):
            print("dados de demonstração já existem; nada a fazer")
            return
        org, owner = _org_with_owner(db, "Escritório Demonstração (fictício)", "Ana Demonstração", "demo@exemplo.com.br", password)
        analyst = User(name="Bruno Analista", email="analista@exemplo.com.br", password_hash=hash_password(password))
        viewer = User(name="Carla Leitora", email="leitura@exemplo.com.br", password_hash=hash_password(password))
        db.add_all([analyst, viewer])
        db.flush()
        db.add_all([Membership(organization_id=org.id, user_id=analyst.id, role="analyst"),
                    Membership(organization_id=org.id, user_id=viewer.id, role="viewer")])
        _org_with_owner(db, "Outra Contabilidade (fictícia)", "Davi Outro", "outra@exemplo.com.br", password)
        alfa = ClientAccount(organization_id=org.id, name="Comercial Alfa Ltda (fictícia)", external_reference="ALFA-001")
        beta = ClientAccount(organization_id=org.id, name="Indústria Beta S.A. (fictícia)", external_reference="BETA-002")
        db.add_all([alfa, beta])
        db.flush()

        files = {}
        with tempfile.TemporaryDirectory() as tmp:
            for name, path in generate_demo_files(Path(tmp)).items():
                with path.open("rb") as fh:
                    files[name] = files_service.create_file(
                        db, organization_id=org.id, client_id=alfa.id, user_id=owner.id, filename=name,
                        stream=io.BytesIO(fh.read()), max_bytes=get_settings().max_upload_bytes)
        base = files["contas_pagar_2024_09.csv"]
        cols = {c["name"]: c for c in base.inspection["columns"]}
        from app.infrastructure.ai import HeuristicSuggester

        entries = []
        for s in HeuristicSuggester().suggest(base.inspection["columns"], 0.85):
            entries.append(MappingEntry(
                source_column=s.source_column, target_field=s.target_field, status="approved" if s.target_field else "ignored",
                confidence=s.confidence, rationale=s.rationale, number_style=cols[s.source_column].get("number_style") or "auto",
                required=s.target_field in ("document_number", "amount", "issue_date"), source="heuristic",
                transforms=["trim"] if s.target_field in ("document_number", "counterparty_name") else []))
        profile = profiles_service.create_profile(
            db, org_id=org.id, user_id=owner.id, name="Contas a pagar — layout padrão", description="Exportação padrão do ERP (fictício).",
            client_id=alfa.id, file=base, entries=entries, approve=True, suggestion_source="heuristic")
        for name, rtype, params, sev in [
            ("Situação permitida", "allowed_values", {"field": "status", "values": ["Pago", "Aberto", "Cancelado"]}, "warning"),
            ("Pago exige data de pagamento", "dependency", {"when": {"all": [{"field": "status", "op": "eq", "value": "pago"}]},
                                                             "then": {"all": [{"field": "payment_date", "op": "not_null"}]}}, "error"),
            ("Valor positivo", "range", {"field": "amount", "min": "0", "exclusive_min": True}, "warning"),
            ("Fornecedor obrigatório", "required", {"field": "counterparty_name"}, "error"),
            ("CNPJ válido", "format", {"field": "counterparty_tax_id", "format": "cnpj"}, "error"),
            ("Documento sem duplicidade", "unique_key", {"fields": ["document_number"]}, "error"),
            ("Data de pagamento preenchida (90%)", "completeness", {"field": "payment_date", "min_ratio": 0.9}, "info"),
        ]:
            params = rules_service.validate_definition(rtype, params, None)
            db.add(ValidationRule(organization_id=org.id, rule_key=rules_service.new_rule_key(name), version=1, name=name,
                                  rule_type=rtype, category=rules_service.REGISTRY[rtype].category, params=params, severity=sev,
                                  status="active", is_current=True, created_by=owner.id))
        db.flush()
        job, _ = processing_service.create_job(db, _Ctx(owner, org), file=base, profile=profile, rule_ids=None,
                                               auto_type_checks=True, idempotency_key="seed-demo-job")
        cmp = ComparisonJob(
            organization_id=org.id, client_account_id=alfa.id, name="ERP x Banco — setembro (demo)",
            file_a_id=files["erp_titulos_2024_09.csv"].id, file_b_id=files["banco_pagamentos_2024_09.xlsx"].id,
            config={"key_pairs": [{"column_a": "Documento", "column_b": "Nr Documento"}],
                    "compare_pairs": [{"column_a": "Valor", "column_b": "Valor Pago", "kind": "number", "abs_tolerance": "0.01",
                                       "number_style_a": "br"},
                                      {"column_a": "Vencimento", "column_b": "Data Pagamento", "kind": "date"},
                                      {"column_a": "Fornecedor", "column_b": "Favorecido", "kind": "text"}]},
            status="queued", created_by=owner.id)
        db.add(cmp)
        db.flush()
        job_id, cmp_id = job.id, cmp.id
    run_job_now(job_id)
    run_comparison_now(cmp_id)
    print("dados de demonstração criados")
    print("  usuários: demo@exemplo.com.br (owner), analista@exemplo.com.br (analyst), leitura@exemplo.com.br (viewer)")
    print("  outra organização: outra@exemplo.com.br (owner)")
    print(f"  senha: definida em {DEMO_PASSWORD_ENV}" if os.environ.get(DEMO_PASSWORD_ENV) else f"  senha: {password}")


def purge_retention() -> None:
    with session_scope() as db:
        print(f"{len(files_service.purge_expired(db, batch=10_000))} arquivo(s) expurgado(s)")


def main(argv: list[str] | None = None) -> None:
    configure_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=["bootstrap", "seed-demo", "purge-retention"])
    args = parser.parse_args(argv)
    {"bootstrap": bootstrap, "seed-demo": seed_demo, "purge-retention": purge_retention}[args.command]()


if __name__ == "__main__":
    main(sys.argv[1:])
