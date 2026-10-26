"""Erros de aplicação com resposta HTTP consistente.

Formato: {"error": {"code": str, "message": str, "details": any}}
Mensagens nunca incluem caminhos internos, chaves de armazenamento ou dados de arquivos.
"""

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class LimitExceeded(AppError):
    status_code = 429
    code = "limit_exceeded"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class FileRejected(AppError):
    """Arquivo inválido, corrompido ou não suportado (erro do arquivo, não da infraestrutura)."""

    status_code = 422
    code = "file_rejected"
