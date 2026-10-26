"""Autenticação, autorização por papel, isolamento entre organizações e vazamento de dados."""

import logging

import jwt
import pytest

from app.core.config import get_settings
from tests.conftest import PASSWORD, Tenant, make_profile, signup


@pytest.fixture
def seeded(tenant: Tenant, demo_files):
    company = tenant.create_client("Empresa Sigilosa")
    file = tenant.upload(company["id"], demo_files["contas_pagar_2024_09.csv"]).json()
    profile = make_profile(tenant, file)
    job = tenant.post("/api/v1/jobs", json={"file_id": file["id"], "profile_id": profile["id"]}).json()
    erp = tenant.upload(company["id"], demo_files["erp_titulos_2024_09.csv"]).json()
    cmp = tenant.post("/api/v1/comparisons", json={"file_a_id": file["id"], "file_b_id": erp["id"], "config": {
        "key_pairs": [{"column_a": "Documento", "column_b": "Documento"}]}}).json()
    rule = tenant.post("/api/v1/validation-rules", json={"name": "Regra R", "rule_type": "required",
                                                         "params": {"field": "amount"}}).json()
    return {"client": company, "file": file, "profile": profile, "job": job, "comparison": cmp, "rule": rule}


def test_unauthenticated_requests_rejected(client):
    for method, url in [("get", "/api/v1/me"), ("get", "/api/v1/clients"), ("post", "/api/v1/files"), ("get", "/api/v1/jobs")]:
        r = getattr(client, method)(url)
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_tampered_or_expired_token_rejected(tenant: Tenant, client):
    payload = jwt.decode(tenant.session["access_token"], options={"verify_signature": False})
    forged = jwt.encode({**payload, "org": payload["org"]}, "outra-chave-qualquer-com-32-bytes!!", algorithm="HS256")
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    expired = jwt.encode({**payload, "exp": 1}, get_settings().secret_key, algorithm="HS256")
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_token_for_foreign_org_rejected(tenant: Tenant, other_tenant: Tenant, client):
    payload = jwt.decode(tenant.session["access_token"], options={"verify_signature": False})
    swapped = jwt.encode({**payload, "org": other_tenant.org_id}, get_settings().secret_key, algorithm="HS256")
    assert client.get("/api/v1/clients", headers={"Authorization": f"Bearer {swapped}"}).status_code == 401


def test_cross_org_read_modify_download_delete_blocked(seeded, other_tenant: Tenant):
    o, s = other_tenant, seeded
    reads = [f"/api/v1/clients/{s['client']['id']}", f"/api/v1/files/{s['file']['id']}", f"/api/v1/files/{s['file']['id']}/profile",
             f"/api/v1/files/{s['file']['id']}/download", f"/api/v1/profiles/{s['profile']['id']}", f"/api/v1/jobs/{s['job']['id']}",
             f"/api/v1/jobs/{s['job']['id']}/findings", f"/api/v1/jobs/{s['job']['id']}/findings/export.csv",
             f"/api/v1/jobs/{s['job']['id']}/report", f"/api/v1/comparisons/{s['comparison']['id']}",
             f"/api/v1/comparisons/{s['comparison']['id']}/results", f"/api/v1/comparisons/{s['comparison']['id']}/export.csv",
             f"/api/v1/validation-rules/{s['rule']['id']}"]
    for url in reads:
        assert o.get(url).status_code == 404, url
    assert o.patch(f"/api/v1/clients/{s['client']['id']}", json={"name": "Invadido"}).status_code == 404
    assert o.patch(f"/api/v1/profiles/{s['profile']['id']}", json={"status": "archived"}).status_code == 404
    assert o.patch(f"/api/v1/validation-rules/{s['rule']['id']}", json={"severity": "info"}).status_code == 404
    assert o.delete(f"/api/v1/files/{s['file']['id']}").status_code == 404
    assert o.post("/api/v1/jobs", json={"file_id": s["file"]["id"], "profile_id": s["profile"]["id"]}).status_code == 404
    other_client = o.create_client("Cliente do outro")
    r = o.post("/api/v1/files", data={"client_id": s["client"]["id"]}, files={"file": ("a.csv", b"a;b\n1;2\n")})
    assert r.status_code == 404
    r = o.post("/api/v1/comparisons/suggest", json={"file_a_id": s["file"]["id"], "file_b_id": s["file"]["id"]})
    assert r.status_code == 404
    # listagens nunca incluem dados de outra organização
    assert o.get("/api/v1/files").json()["total"] == 0
    assert o.get("/api/v1/jobs").json()["total"] == 0
    assert [c["id"] for c in o.get("/api/v1/clients").json()["items"]] == [other_client["id"]]
    assert o.get("/api/v1/dashboard").json()["files_uploaded"] == 0


def test_role_permissions(seeded, tenant: Tenant):
    viewer = tenant.member("leitor@teste.com.br", "viewer")
    analyst = tenant.member("analista@teste.com.br", "analyst")
    # viewer: somente leitura
    assert viewer.get(f"/api/v1/jobs/{seeded['job']['id']}").status_code == 200
    assert viewer.get(f"/api/v1/files/{seeded['file']['id']}/download").status_code == 200
    assert viewer.post("/api/v1/clients", json={"name": "X Ltda"}).status_code == 403
    assert viewer.post("/api/v1/files", data={"client_id": seeded["client"]["id"]},
                       files={"file": ("a.csv", b"a;b\n1;2\n")}).status_code == 403
    assert viewer.post("/api/v1/jobs", json={"file_id": seeded["file"]["id"], "profile_id": seeded["profile"]["id"]}).status_code == 403
    assert viewer.patch(f"/api/v1/profiles/{seeded['profile']['id']}", json={"name": "Alterado"}).status_code == 403
    # analyst: opera, mas não administra membros nem exclui arquivos
    assert analyst.post("/api/v1/clients", json={"name": "Y Ltda"}).status_code == 201
    assert analyst.get("/api/v1/organizations/current/members").status_code == 403
    assert analyst.post("/api/v1/organizations/current/members",
                        json={"name": "Novo Dono", "email": "n@teste.com.br", "role": "owner"}).status_code == 403
    assert analyst.delete(f"/api/v1/files/{seeded['file']['id']}").status_code == 403
    assert analyst.get("/api/v1/audit-events").status_code == 403


def test_admin_cannot_escalate_or_touch_owners(tenant: Tenant):
    admin = tenant.member("admin@teste.com.br", "admin")
    members = tenant.get("/api/v1/organizations/current/members").json()
    owner_m = next(m for m in members if m["role"] == "owner")
    assert admin.post("/api/v1/organizations/current/members",
                      json={"name": "Novo Dono", "email": "novo@teste.com.br", "role": "owner"}).status_code == 403
    assert admin.patch(f"/api/v1/organizations/current/members/{owner_m['id']}", json={"status": "disabled"}).status_code == 403
    assert tenant.patch(f"/api/v1/organizations/current/members/{owner_m['id']}", json={"role": "viewer"}).status_code == 403


def test_disabled_membership_loses_access_immediately(tenant: Tenant):
    analyst = tenant.member("analista2@teste.com.br", "analyst")
    m = next(x for x in tenant.get("/api/v1/organizations/current/members").json() if x["email"] == "analista2@teste.com.br")
    assert tenant.patch(f"/api/v1/organizations/current/members/{m['id']}", json={"status": "disabled"}).status_code == 200
    assert analyst.get("/api/v1/me").status_code == 401


def test_csrf_required_for_cookie_auth(client, bootstrap):
    signup(client, email="cookie@teste.com.br")  # cookies ficam no client
    assert client.get("/api/v1/me").status_code == 200
    r = client.post("/api/v1/clients", json={"name": "Sem CSRF"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = client.post("/api/v1/clients", json={"name": "Com CSRF"}, headers={"X-CSRF-Token": client.cookies.get("ddi_csrf")})
    assert r.status_code == 201


def test_login_errors_are_generic_and_throttled(client, tenant: Tenant):
    unknown = client.post("/api/v1/auth/login", json={"email": "naoexiste@teste.com.br", "password": "qualquer"})
    wrong = client.post("/api/v1/auth/login", json={"email": "dono@teste.com.br", "password": "errada"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"email": "dono@teste.com.br", "password": "errada"})
    r = client.post("/api/v1/auth/login", json={"email": "dono@teste.com.br", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["error"]["code"] == "too_many_attempts"


def test_signup_can_be_disabled_and_password_policy(client, bootstrap, monkeypatch):
    r = client.post("/api/v1/auth/signup", json={"organization_name": "X", "name": "Y", "email": "y@t.com.br", "password": "123"})
    assert r.status_code == 422
    monkeypatch.setattr(get_settings(), "allow_signup", False)
    r = client.post("/api/v1/auth/signup", json={"organization_name": "XX", "name": "YY", "email": "y@t.com.br", "password": PASSWORD})
    assert r.status_code == 403


def test_delete_file_removes_content_but_keeps_history(seeded, tenant: Tenant):
    fid = seeded["file"]["id"]
    assert tenant.delete(f"/api/v1/files/{fid}").status_code == 204
    detail = tenant.get(f"/api/v1/files/{fid}").json()
    assert detail["status"] == "deleted" and detail["inspection"] is None
    assert tenant.get(f"/api/v1/files/{fid}/download").status_code == 422
    assert tenant.get(f"/api/v1/jobs/{seeded['job']['id']}").status_code == 200  # histórico preservado
    r = tenant.post("/api/v1/jobs", json={"file_id": fid, "profile_id": seeded["profile"]["id"]})
    assert r.status_code == 422


def test_cell_values_never_logged(tenant: Tenant, caplog, tmp_path):
    secret = "VALOR-SIGILOSO-XYZ-987"
    company = tenant.create_client()
    content = f"Documento;Fornecedor;Valor\nD1;{secret};abc\n".encode()
    with caplog.at_level(logging.DEBUG):
        f = tenant.upload(company["id"], None, "s.csv", content).json()
        profile = make_profile(tenant, f, name="Perfil P")
        tenant.post("/api/v1/jobs", json={"file_id": f["id"], "profile_id": profile["id"]})
    assert caplog.records, "esperava logs estruturados"
    assert secret not in caplog.text and secret not in str([r.__dict__ for r in caplog.records])


def test_error_responses_do_not_leak_internals(tenant: Tenant, seeded):
    r = tenant.get("/api/v1/files/00000000-0000-0000-0000-000000000000")
    body = r.text
    assert r.status_code == 404 and "org/" not in body and "storage" not in body.lower()
    file = tenant.get(f"/api/v1/files/{seeded['file']['id']}").json()
    assert "storage_key" not in file
    r = tenant.post("/api/v1/clients", json={"name": "x" * 5000})
    assert r.status_code == 422 and "x" * 100 not in r.text  # entrada não é ecoada
    assert r.headers.get("x-request-id")


def test_quota_limits_enforced_by_backend(tenant: Tenant, demo_files):
    from app.infrastructure.database.session import session_scope
    from app.modules.billing.models import Plan

    with session_scope() as db:
        plan = db.get(Plan, "trial")
        plan.limits = {**plan.limits, "files": 1}
    company = tenant.create_client()
    assert tenant.upload(company["id"], demo_files["erp_titulos_2024_09.csv"]).status_code == 201
    r = tenant.upload(company["id"], demo_files["erp_titulos_2024_09.csv"])
    assert r.status_code == 429 and r.json()["error"]["details"]["metric"] == "files", r.text


def test_inactive_client_cannot_receive_files(tenant: Tenant, demo_files):
    company = tenant.create_client()
    tenant.patch(f"/api/v1/clients/{company['id']}", json={"status": "inactive"})
    assert tenant.upload(company["id"], demo_files["erp_titulos_2024_09.csv"]).status_code == 422


def test_oversized_upload_rejected_before_body_is_read(tenant: Tenant, monkeypatch):
    company = tenant.create_client()
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 10)
    big = b"Documento;Valor\n" + b"A;1\n" * 400_000  # ~1,6 MB > limite + margem de 1 MB
    r = tenant.upload(company["id"], None, "grande.csv", big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
