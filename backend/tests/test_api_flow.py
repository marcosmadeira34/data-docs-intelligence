"""Fluxo completo do MVP (critérios de conclusão 1-16) via API, com dados sintéticos."""

import csv
import io

from fastapi.testclient import TestClient

from app.infrastructure.database.session import configure, get_engine
from app.main import create_app
from tests.conftest import Tenant, approve_all, make_profile


def _csv_rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))


def test_full_mvp_flow(tenant: Tenant, other_tenant: Tenant, demo_files):
    t = tenant
    # 2. empresa atendida
    company = t.create_client("Comercial Alfa Ltda")

    # 3-4. upload de arquivo desconhecido e identificação da estrutura
    r = t.upload(company["id"], demo_files["contas_pagar_2024_09.csv"])
    assert r.status_code == 201, r.text
    file1 = r.json()
    assert file1["detected_format"] == "csv" and len(file1["content_hash"]) == 64
    assert "storage_key" not in file1
    insp = file1["inspection"]
    assert insp["row_count"] == 61 and insp["options"]["delimiter"] == ";"

    # 5. confirmação do cabeçalho e mapeamento
    r = t.post(f"/api/v1/files/{file1['id']}/structure", json={"header_row": 1, "delimiter": ";"})
    assert r.status_code == 200 and r.json()["structure_confirmed"]
    sug = t.post(f"/api/v1/files/{file1['id']}/mapping").json()
    assert sug["provider"] == "heuristic" and sug["profile_matches"] == []
    targets = {s["source_column"]: s["target_field"] for s in sug["suggestions"]}
    assert targets["Valor"] == "amount" and targets["CNPJ"] == "counterparty_tax_id"

    # Aprovação explícita: sugestões pendentes impedem a aprovação
    pending = [{"source_column": s["source_column"], "target_field": s["target_field"], "status": "suggested"}
               for s in sug["suggestions"]]
    r = t.post("/api/v1/profiles", json={"name": "CP padrão", "client_id": company["id"], "file_id": file1["id"],
                                         "entries": pending, "approve": True})
    assert r.status_code == 422 and "pendentes" in str(r.json()["error"]["details"])

    # 6. salvar perfil
    entries = approve_all(sug["suggestions"], required=("document_number", "amount"))
    r = t.post("/api/v1/profiles", json={"name": "CP padrão", "client_id": company["id"], "file_id": file1["id"],
                                         "entries": entries, "approve": True})
    assert r.status_code == 201, r.text
    profile = r.json()
    assert profile["current_version"]["version"] == 1 and profile["current_version"]["approval_status"] == "approved"

    # 7. regras configuradas sem código
    rules = [
        {"name": "CNPJ válido", "rule_type": "format", "params": {"field": "counterparty_tax_id", "format": "cnpj"}},
        {"name": "Documento único", "rule_type": "unique_key", "params": {"fields": ["document_number"]}},
        {"name": "Valor positivo", "rule_type": "range", "params": {"field": "amount", "min": 0, "exclusive_min": True},
         "severity": "warning"},
        {"name": "Pago exige data", "rule_type": "dependency",
         "params": {"when": {"all": [{"field": "status", "op": "eq", "value": "pago"}]},
                    "then": {"all": [{"field": "payment_date", "op": "not_null"}]}}},
        {"name": "Regra desativada", "rule_type": "required", "params": {"field": "cost_center"}, "status": "inactive"},
    ]
    for rule in rules:
        assert t.post("/api/v1/validation-rules", json=rule).status_code == 201
    bad = t.post("/api/v1/validation-rules", json={"name": "Ruim", "rule_type": "regex", "params": {"field": "amount", "pattern": "(a+)+"}})
    assert bad.status_code == 422

    # 8-9. execução persistida
    r = t.post("/api/v1/jobs", json={"file_id": file1["id"], "profile_id": profile["id"]})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "succeeded", job["failure_reason"]
    assert job["records_read"] == 61
    assert job["input_snapshot"]["sha256"] == file1["content_hash"] and job["input_snapshot"]["profile_version"] == 1
    snapshot_keys = {r["rule_key"] for r in t.get(f"/api/v1/jobs/{job['id']}/report").json()["rules"]}
    assert "system.required.amount" in snapshot_keys
    assert not any("regra-desativada" in k for k in snapshot_keys)

    # 10. inconsistências com filtros
    f = t.get(f"/api/v1/jobs/{job['id']}/findings", params={"limit": 200}).json()
    by_msg = {(x["row_number"], x["field"]) for x in f["items"]}
    assert (5, "counterparty_tax_id") not in by_msg            # ausente não é formato inválido
    assert (7, "counterparty_tax_id") in by_msg                # dígito verificador inválido
    assert (10, "amount") in by_msg                            # valor "abc"
    assert (13, "issue_date") in by_msg                        # 31/02/2024
    assert (16, "amount") in by_msg                            # negativo (warning)
    assert (19, "payment_date") in by_msg                      # pago sem data
    assert (62, "document_number") in by_msg                   # duplicado
    assert f["facets"]["severity"]["warning"] == 1 and job["warning_count"] == 1
    only_warn = t.get(f"/api/v1/jobs/{job['id']}/findings", params={"severity": "warning"}).json()
    assert only_warn["total"] == 1 and only_warn["items"][0]["row_number"] == 16
    cnpj = next(x for x in f["items"] if x["row_number"] == 7)
    assert "*" in cnpj["observed_value"]                       # valor sensível mascarado

    # revisão de achado
    r = t.patch(f"/api/v1/jobs/{job['id']}/findings/{cnpj['id']}", json={"review_status": "acknowledged", "review_note": "ok"})
    assert r.status_code == 200 and r.json()["review_status"] == "acknowledged"

    # 11. exportação
    r = t.get(f"/api/v1/jobs/{job['id']}/findings/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = _csv_rows(r.text)
    assert rows[0][:4] == ["execucao", "arquivo", "sha256", "linha"] and len(rows) - 1 == f["total"]

    # 12. arquivo compatível reutiliza o perfil
    r = t.upload(company["id"], demo_files["contas_pagar_2024_10.csv"])
    file2 = r.json()
    matches = t.post(f"/api/v1/files/{file2['id']}/mapping").json()["profile_matches"]
    assert matches[0]["profile_id"] == profile["id"] and matches[0]["compatibility"]["status"] == "identical"
    job2 = t.post("/api/v1/jobs", json={"file_id": file2["id"], "profile_id": profile["id"]}).json()
    assert job2["status"] == "succeeded" and job2["records_read"] == 45

    # 13. mudança incompatível é detectada e exige revisão
    file3 = t.upload(company["id"], demo_files["contas_pagar_2024_11_layout_alterado.csv"]).json()
    r = t.post("/api/v1/jobs", json={"file_id": file3["id"], "profile_id": profile["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "structure_review_required"
    assert "Valor" in r.json()["error"]["details"]["missing_mapped_columns"]
    sug3 = t.post(f"/api/v1/files/{file3['id']}/mapping").json()
    assert sug3["profile_matches"][0]["compatibility"]["requires_review"]
    r = t.post(f"/api/v1/profiles/{profile['id']}/versions", json={
        "file_id": file3["id"], "entries": approve_all(sug3["suggestions"]), "approve": True, "change_note": "Novo layout"})
    assert r.status_code == 201
    versions = r.json()["versions"]
    assert [v["approval_status"] for v in versions] == ["approved", "superseded"]
    job3 = t.post("/api/v1/jobs", json={"file_id": file3["id"], "profile_id": profile["id"]}).json()
    assert job3["status"] == "succeeded" and job3["input_snapshot"]["profile_version"] == 2

    # 14. comparação entre dois arquivos
    erp = t.upload(company["id"], demo_files["erp_titulos_2024_09.csv"]).json()
    bank = t.upload(company["id"], demo_files["banco_pagamentos_2024_09.xlsx"]).json()
    suggestion = t.post("/api/v1/comparisons/suggest", json={"file_a_id": erp["id"], "file_b_id": bank["id"]}).json()
    assert suggestion["key_pairs"] == [{"column_a": "Documento", "column_b": "Nr Documento"}]
    config = {"key_pairs": suggestion["key_pairs"],
              "compare_pairs": [{k: v for k, v in p.items() if k != "warning"} for p in suggestion["loose_pairs"]]}
    r = t.post("/api/v1/comparisons", json={"name": "ERP x Banco", "file_a_id": erp["id"], "file_b_id": bank["id"], "config": config})
    assert r.status_code == 201, r.text
    cmp = r.json()
    s = cmp["summary"]
    assert cmp["status"] == "succeeded"
    assert (s["match"], s["mismatch"], s["only_a"], s["only_b"], s["duplicate_key_b"], s["missing_key_b"]) == (35, 2, 2, 2, 2, 1)
    res = t.get(f"/api/v1/comparisons/{cmp['id']}/results", params={"category": "mismatch"}).json()
    assert res["total"] == 2
    export = t.get(f"/api/v1/comparisons/{cmp['id']}/export.csv")
    assert export.status_code == 200 and len(_csv_rows(export.text)) > 5

    # 15. outra organização não acessa os dados
    for url in (f"/api/v1/jobs/{job['id']}", f"/api/v1/files/{file1['id']}", f"/api/v1/comparisons/{cmp['id']}",
                f"/api/v1/profiles/{profile['id']}", f"/api/v1/clients/{company['id']}"):
        assert other_tenant.get(url).status_code == 404

    # Dashboard com números reais
    d = t.get("/api/v1/dashboard").json()
    assert d["clients_active"] == 1 and d["files_uploaded"] == 5 and d["jobs_succeeded"] == 3 and d["comparisons"] == 1
    usage = t.get("/api/v1/organizations/current/usage").json()
    assert usage["usage"]["files"] == 5 and usage["usage"]["jobs"] == 3

    # 16. histórico disponível após "reiniciar" a aplicação (novo engine e nova instância do app)
    get_engine().dispose()
    configure()
    fresh = TestClient(create_app())
    hist = fresh.get("/api/v1/jobs", headers=t.headers).json()
    assert hist["total"] == 3
    assert fresh.get(f"/api/v1/jobs/{job['id']}/findings", headers=t.headers).json()["total"] == f["total"]


def test_idempotency_and_reprocess(tenant: Tenant, demo_files):
    company = tenant.create_client()
    file = tenant.upload(company["id"], demo_files["contas_pagar_2024_10.csv"]).json()
    profile = make_profile(tenant, file)
    body = {"file_id": file["id"], "profile_id": profile["id"]}
    a = tenant.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "abc-123"}).json()
    b = tenant.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "abc-123"}).json()
    assert a["id"] == b["id"]
    assert tenant.get("/api/v1/jobs").json()["total"] == 1
    r = tenant.post(f"/api/v1/jobs/{a['id']}/reprocess")
    assert r.status_code == 201 and r.json()["reprocess_of_id"] == a["id"] and r.json()["status"] == "succeeded"


def test_xlsx_alternative_layout_flow(tenant: Tenant, demo_files):
    company = tenant.create_client()
    f = tenant.upload(company["id"], demo_files["contas_pagar_alternativo_2024_09.xlsx"]).json()
    assert f["read_options"]["sheet"] == "Lançamentos" and f["read_options"]["header_row"] == 3
    profile = make_profile(tenant, f, name="Layout alternativo")
    job = tenant.post("/api/v1/jobs", json={"file_id": f["id"], "profile_id": profile["id"]}).json()
    assert job["status"] == "succeeded" and job["records_read"] == 30 and job["error_count"] == 0
    # trocar de aba na inspeção sem salvar
    other = tenant.get(f"/api/v1/files/{f['id']}/profile", params={"sheet": "Instruções"}).json()
    assert other["options"]["sheet"] == "Instruções"


def test_rule_versioning_and_global_rules(tenant: Tenant):
    globals_ = [r for r in tenant.get("/api/v1/validation-rules").json()["items"] if r["is_global"]]
    assert len(globals_) >= 5
    assert tenant.patch(f"/api/v1/validation-rules/{globals_[0]['id']}", json={"severity": "info"}).status_code == 403
    clone = tenant.post(f"/api/v1/validation-rules/{globals_[0]['id']}/clone").json()
    v2 = tenant.patch(f"/api/v1/validation-rules/{clone['id']}", json={"severity": "warning"}).json()
    assert v2["version"] == 2 and v2["rule_key"] == clone["rule_key"] and v2["severity"] == "warning"
    old = tenant.patch(f"/api/v1/validation-rules/{clone['id']}", json={"severity": "info"})
    assert old.status_code == 409  # versão antiga não pode ser alterada
    detail = tenant.get(f"/api/v1/validation-rules/{v2['id']}").json()
    assert [h["version"] for h in detail["history"]] == [2, 1]
    assert tenant.post("/api/v1/validation-rules/check", json={"rule_type": "range", "params": {"field": "amount"}}).status_code == 422


def test_file_rejections_via_api(tenant: Tenant, demo_files, monkeypatch):
    company = tenant.create_client()
    assert tenant.upload(company["id"], None, "vazio.csv", b"").json()["error"]["code"] == "empty_file"
    r = tenant.upload(company["id"], None, "nota.csv", b"%PDF-1.7 fake")
    assert r.status_code == 422 and r.json()["error"]["code"] == "content_mismatch"
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_bytes", 1000)
    r = tenant.upload(company["id"], demo_files["contas_pagar_2024_09.csv"])
    assert r.status_code == 413
    events = tenant.get("/api/v1/audit-events", params={"action": "file.rejected"}).json()
    assert events["total"] == 3  # vazio, conteúdo incompatível e tamanho excedido


def test_empty_rule_selection_applies_only_mapping_rules(tenant: Tenant, demo_files):
    company = tenant.create_client()
    file = tenant.upload(company["id"], demo_files["contas_pagar_2024_09.csv"]).json()
    profile = make_profile(tenant, file)
    tenant.post("/api/v1/validation-rules", json={"name": "CNPJ válido", "rule_type": "format",
                                                  "params": {"field": "counterparty_tax_id", "format": "cnpj"}})
    default = tenant.post("/api/v1/jobs", json={"file_id": file["id"], "profile_id": profile["id"]}).json()
    none = tenant.post("/api/v1/jobs", json={"file_id": file["id"], "profile_id": profile["id"], "rule_ids": []}).json()
    keys = lambda j: {r["rule_key"] for r in tenant.get(f"/api/v1/jobs/{j['id']}/report").json()["rules"]}  # noqa: E731
    assert any(k.startswith("cnpj-valido") for k in keys(default))
    assert all(k.startswith("system.") for k in keys(none))
    again = tenant.post(f"/api/v1/jobs/{none['id']}/reprocess").json()
    assert all(k.startswith("system.") for k in keys(again))
