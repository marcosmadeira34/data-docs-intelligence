"""Fila no banco: execução assíncrona, retentativas, classificação de falhas e recuperação."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.errors import FileRejected
from app.infrastructure.database.session import session_scope
from app.modules.processing import queue
from app.modules.processing import service as processing_service
from app.modules.processing.models import ProcessingJob, ValidationFinding
from app.worker import maintenance, run_once
from tests.conftest import Tenant, make_profile


@pytest.fixture
def queued_job(tenant: Tenant, demo_files, monkeypatch):
    monkeypatch.setattr(get_settings(), "job_inline_max_bytes", 0)  # força processamento assíncrono
    company = tenant.create_client()
    file = tenant.upload(company["id"], demo_files["contas_pagar_2024_09.csv"]).json()
    profile = make_profile(tenant, file)
    job = tenant.post("/api/v1/jobs", json={"file_id": file["id"], "profile_id": profile["id"]}).json()
    assert job["status"] == "queued"
    return uuid.UUID(job["id"]), {"file": file, "profile": profile}


def _job(job_id) -> ProcessingJob:
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        db.expunge(job)
        return job


def _findings(job_id) -> int:
    with session_scope() as db:
        return db.scalar(select(func.count()).select_from(ValidationFinding).where(ValidationFinding.job_id == job_id))


def test_worker_processes_queued_job(queued_job, tenant: Tenant):
    job_id, _ = queued_job
    assert run_once("test-worker") is True
    job = _job(job_id)
    assert job.status == "succeeded" and job.attempts == 1 and job.records_read == 61 and job.findings_stored > 0
    assert run_once("test-worker") is False  # fila vazia


def test_infrastructure_error_is_retried_then_fails_with_cleanup(queued_job):
    job_id, _ = queued_job
    calls = {"n": 0}

    def flaky(db, job):
        calls["n"] += 1
        db.add(ValidationFinding(job_id=job.id, organization_id=job.organization_id, rule_key="x", rule_version=1,
                                 rule_type="required", severity="error", message="parcial", evidence={}))
        db.flush()
        raise ConnectionError("armazenamento indisponível")

    def claim_and_run():
        with session_scope() as db:
            assert queue.claim_specific(db, ProcessingJob, job_id, "w")
        queue.run_claimed(ProcessingJob, job_id, flaky, processing_service.cleanup)

    claim_and_run()
    job = _job(job_id)
    assert job.status == "queued" and job.error_kind == "infrastructure_error" and job.run_after is not None
    # não é reprocessado antes do backoff
    with session_scope() as db:
        assert queue.claim_next(db, ProcessingJob, "w") is None
    claim_and_run()
    claim_and_run()
    job = _job(job_id)
    assert job.status == "failed" and job.attempts == 3 and calls["n"] == 3
    assert _findings(job_id) == 0


def test_file_error_is_not_retried(queued_job):
    job_id, _ = queued_job

    def bad_file(db, job):
        raise FileRejected("arquivo corrompido")

    with session_scope() as db:
        queue.claim_specific(db, ProcessingJob, job_id, "w")
    queue.run_claimed(ProcessingJob, job_id, bad_file, processing_service.cleanup)
    job = _job(job_id)
    assert job.status == "failed" and job.error_kind == "file_error" and job.attempts == 1


def test_timeout_classified(queued_job):
    job_id, _ = queued_job

    def slow(db, job):
        raise queue.JobTimeout()

    with session_scope() as db:
        queue.claim_specific(db, ProcessingJob, job_id, "w")
    queue.run_claimed(ProcessingJob, job_id, slow)
    assert _job(job_id).error_kind == "timeout"


def test_retry_is_idempotent(queued_job):
    job_id, _ = queued_job
    run_once("w")
    first = _findings(job_id)
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        job.status = "queued"
    run_once("w")
    assert _findings(job_id) == first  # sem duplicação de achados


def test_stale_running_job_recovered(queued_job, monkeypatch):
    job_id, _ = queued_job
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        job.status, job.attempts = "running", 1
        job.locked_at = datetime.now(UTC) - timedelta(hours=2)
    maintenance()
    assert _job(job_id).status == "queued"
    with session_scope() as db:
        job = db.get(ProcessingJob, job_id)
        job.status, job.attempts = "running", 3
        job.locked_at = datetime.now(UTC) - timedelta(hours=2)
    maintenance()
    job = _job(job_id)
    assert job.status == "failed" and job.error_kind == "infrastructure_error"


def test_cancel_queued_job(queued_job, tenant: Tenant):
    job_id, _ = queued_job
    assert tenant.post(f"/api/v1/jobs/{job_id}/cancel").json()["status"] == "cancelled"
    assert run_once("w") is False
    assert tenant.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 409


def test_concurrency_limit_per_org(queued_job, tenant: Tenant, monkeypatch):
    _, ctx = queued_job
    monkeypatch.setattr(get_settings(), "max_concurrent_jobs_per_org", 1)
    r = tenant.post("/api/v1/jobs", json={"file_id": ctx["file"]["id"], "profile_id": ctx["profile"]["id"]})
    assert r.status_code == 429 and r.json()["error"]["code"] == "concurrency_limit"


def test_retention_purge(tenant: Tenant, demo_files):
    company = tenant.create_client()
    f = tenant.upload(company["id"], demo_files["erp_titulos_2024_09.csv"]).json()
    from app.modules.files.models import FileAsset

    with session_scope() as db:
        db.get(FileAsset, uuid.UUID(f["id"])).retention_until = datetime.now(UTC) - timedelta(days=1)
    maintenance()
    detail = tenant.get(f"/api/v1/files/{f['id']}").json()
    assert detail["status"] == "deleted"
    events = tenant.get("/api/v1/audit-events", params={"action": "file.retention_purged"}).json()
    assert events["total"] == 1
