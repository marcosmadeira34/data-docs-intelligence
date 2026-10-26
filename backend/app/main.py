from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, request_id_var
from app.infrastructure.database.session import get_engine
from app.infrastructure.storage import get_storage
from app.modules.clients.router import router as clients_router
from app.modules.comparison.router import router as comparison_router
from app.modules.files.router import router as files_router
from app.modules.organizations.router import auth_router
from app.modules.organizations.router import router as org_router
from app.modules.processing.router import router as jobs_router
from app.modules.profiles.router import router as profiles_router
from app.modules.reports.router import router as reports_router
from app.modules.validation.router import router as rules_router

log = logging.getLogger("app")


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    rid = request_id_var.get()
    if rid:
        body["error"]["request_id"] = rid
    return JSONResponse(status_code=status, content=body)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        description="Ingestão, validação e comparação de planilhas para escritórios contábeis e BPOs financeiros.",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                           allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["*"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        rid = incoming if 8 <= len(incoming) <= 64 and incoming.replace("-", "").isalnum() else uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            # Recusa uploads declaradamente grandes antes de receber o corpo (o limite em streaming continua valendo).
            declared = request.headers.get("content-length", "")
            if request.method == "POST" and declared.isdigit() and int(declared) > settings.max_upload_bytes + 1024 * 1024:
                response = _error(413, "payload_too_large", "O arquivo excede o tamanho máximo permitido.")
            else:
                response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/v1"):
            response.headers.setdefault("Cache-Control", "no-store")
        log.info("http.request", extra={"method": request.method, "path": request.url.path, "status": response.status_code,
                                        "duration_ms": round((time.perf_counter() - start) * 1000, 1), "request_id": rid})
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        # Não ecoa os valores enviados (podem conter dados sensíveis).
        details = [{"loc": ".".join(str(p) for p in e.get("loc", [])), "message": e.get("msg")} for e in exc.errors()]
        return _error(422, "validation_failed", "Dados inválidos na requisição.", details)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("http.unhandled_error")
        return _error(500, "internal_error", "Erro interno. Informe o identificador da requisição ao suporte.")

    api = APIRouter(prefix="/api/v1")
    for r in (auth_router, org_router, clients_router, files_router, profiles_router, rules_router, jobs_router,
              comparison_router, reports_router):
        api.include_router(r)
    app.include_router(api)

    @app.get("/health/live", tags=["saúde"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["saúde"])
    def ready():
        checks = {}
        try:
            with get_engine().connect() as conn:
                conn.execute(text("select 1"))
            checks["database"] = "ok"
        except Exception:
            log.exception("health.database_failed")
            checks["database"] = "error"
        try:
            get_storage().exists("health-check")
            checks["storage"] = "ok"
        except Exception:
            log.exception("health.storage_failed")
            checks["storage"] = "error"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", "checks": checks})

    return app


app = create_app()
