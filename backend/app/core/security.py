"""Hash de senhas (Argon2id), tokens JWT e proteção contra força bruta."""

from __future__ import annotations

import secrets
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()
# Hash fixo para igualar o tempo de resposta quando o e-mail não existe.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")
ALGORITHM = "HS256"
ACCESS_COOKIE = "ddi_access"
CSRF_COOKIE = "ddi_csrf"
CSRF_HEADER = "X-CSRF-Token"
CLOCK_SKEW_SECONDS = 60


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, organization_id: uuid.UUID) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(organization_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.access_token_ttl_minutes)).timestamp()),
        "jti": secrets.token_hex(8),
        "typ": "access",
    }
    return jwt.encode(payload, s.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    # leeway tolera pequenas diferenças/ajustes de relógio entre instâncias (iat/exp)
    payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM], leeway=CLOCK_SKEW_SECONDS,
                         options={"require": ["exp", "sub", "org"]})
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("tipo de token inválido")
    return payload


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def generate_temporary_password() -> str:
    return secrets.token_urlsafe(12)


class LoginThrottle:
    """Bloqueio temporário após tentativas falhas (por e-mail + IP).

    Em memória: adequado a uma instância. Para múltiplas réplicas, mover para Redis/banco.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def _key(self, email: str, ip: str | None) -> str:
        return f"{email.lower()}|{ip or '-'}"

    def is_locked(self, email: str, ip: str | None) -> bool:
        s = get_settings()
        now = time.monotonic()
        with self._lock:
            attempts = [t for t in self._failures.get(self._key(email, ip), []) if now - t < s.login_lockout_seconds]
            self._failures[self._key(email, ip)] = attempts
            return len(attempts) >= s.login_max_attempts

    def fail(self, email: str, ip: str | None) -> None:
        with self._lock:
            self._failures.setdefault(self._key(email, ip), []).append(time.monotonic())

    def reset(self, email: str, ip: str | None) -> None:
        with self._lock:
            self._failures.pop(self._key(email, ip), None)


login_throttle = LoginThrottle()
