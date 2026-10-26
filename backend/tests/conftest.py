"""Configuração de testes.

Banco: SQLite por padrão; defina DDI_TEST_DATABASE_URL para rodar contra PostgreSQL
(ex.: postgresql+psycopg://ddi:ddi@localhost:5442/ddi_test).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="ddi-tests-"))
os.environ["DDI_ENVIRONMENT"] = "test"
os.environ["DDI_DATABASE_URL"] = os.environ.get("DDI_TEST_DATABASE_URL", f"sqlite:///{_TMP / 'test.sqlite'}")
os.environ["DDI_STORAGE_LOCAL_ROOT"] = str(_TMP / "storage")
os.environ["DDI_SECRET_KEY"] = "test-secret-key-0123456789abcdef-xyz"
os.environ["DDI_LOG_LEVEL"] = "INFO"
os.environ["DDI_AI_PROVIDER"] = "none"
os.environ.setdefault("DDI_JOB_INLINE_MAX_BYTES", str(50 * 1024 * 1024))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import login_throttle  # noqa: E402
from app.demo.synthetic import generate_demo_files  # noqa: E402
from app.infrastructure.database.models import Base  # noqa: E402
from app.infrastructure.database.session import get_engine, session_scope  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.billing import service as billing  # noqa: E402
from app.modules.validation import service as rules_service  # noqa: E402

PASSWORD = "Senha-de-teste-123"


@pytest.fixture(scope="session", autouse=True)
def _database():
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    engine = get_engine()
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            names = ", ".join(t.name for t in Base.metadata.sorted_tables)
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        else:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
    login_throttle._failures.clear()


@pytest.fixture
def bootstrap():
    with session_scope() as db:
        billing.ensure_default_plans(db)
        rules_service.ensure_global_rules(db)


@pytest.fixture(scope="session")
def demo_files() -> dict[str, Path]:
    return generate_demo_files(_TMP / "demo")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class Tenant:
    """Organização de teste com helpers autenticados (Bearer)."""

    def __init__(self, client: TestClient, session: dict):
        self.client = client
        self.session = session
        self.headers = {"Authorization": f"Bearer {session['access_token']}"}
        self.org_id = session["organization"]["id"]

    def get(self, url, **kw):
        return self.client.get(url, headers=self.headers, **kw)

    def post(self, url, **kw):
        return self.client.post(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def patch(self, url, **kw):
        return self.client.patch(url, headers=self.headers, **kw)

    def delete(self, url, **kw):
        return self.client.delete(url, headers=self.headers, **kw)

    def create_client(self, name="Empresa Teste Ltda") -> dict:
        r = self.post("/api/v1/clients", json={"name": name})
        assert r.status_code == 201, r.text
        return r.json()

    def upload(self, client_id: str, path: Path, filename: str | None = None, content: bytes | None = None):
        data = content if content is not None else path.read_bytes()
        return self.post("/api/v1/files", data={"client_id": client_id}, files={"file": (filename or path.name, data)})

    def member(self, email: str, role: str) -> Tenant:
        r = self.post("/api/v1/organizations/current/members", json={"name": "Membro Teste", "email": email, "role": role})
        assert r.status_code == 201, r.text
        temp = r.json()["temporary_password"]
        login = self.client.post("/api/v1/auth/login", json={"email": email, "password": temp})
        assert login.status_code == 200, login.text
        return Tenant(self.client, login.json())


def signup(client: TestClient, org="Escritório Teste", email="dono@teste.com.br") -> Tenant:
    r = client.post("/api/v1/auth/signup", json={"organization_name": org, "name": "Dono Teste", "email": email,
                                                 "password": PASSWORD})
    assert r.status_code == 201, r.text
    return Tenant(client, r.json())


@pytest.fixture
def tenant(client, bootstrap) -> Tenant:
    return signup(client)


@pytest.fixture
def other_tenant(client, bootstrap) -> Tenant:
    return signup(TestClient(app), org="Outro Escritório", email="dono@outro.com.br")


def approve_all(suggestions: list[dict], required: tuple[str, ...] = ()) -> list[dict]:
    entries = []
    for s in suggestions:
        entries.append({
            "source_column": s["source_column"], "target_field": s["target_field"],
            "status": "approved" if s["target_field"] else "ignored", "confidence": s["confidence"],
            "number_style": s.get("number_style") or "auto", "required": s["target_field"] in required,
        })
    return entries


def make_profile(t: Tenant, file: dict, name="Perfil Teste", required=("document_number",)) -> dict:
    sug = t.post(f"/api/v1/files/{file['id']}/mapping").json()["suggestions"]
    r = t.post("/api/v1/profiles", json={"name": name, "client_id": file["client_account_id"], "file_id": file["id"],
                                         "entries": approve_all(sug, required), "approve": True})
    assert r.status_code == 201, r.text
    return r.json()
