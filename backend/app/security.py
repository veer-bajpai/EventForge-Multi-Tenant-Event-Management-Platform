import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

import jwt
from fastapi import HTTPException, status

from .config import settings
from .models import utcnow

ALGO = "HS256"
_ITER = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.secret_key, algorithm=ALGO)


def create_access_token(user_id: int) -> str:
    now = utcnow()
    return _encode({"sub": str(user_id), "type": "access", "iat": now,
                    "exp": now + timedelta(minutes=settings.access_token_minutes)})


def create_refresh_token(user_id: int, family_id: str | None = None):
    """Returns (token, jti, family_id, expires_at)."""
    now = utcnow()
    jti, family_id = uuid.uuid4().hex, family_id or uuid.uuid4().hex
    exp = now + timedelta(days=settings.refresh_token_days)
    token = _encode({"sub": str(user_id), "type": "refresh", "jti": jti, "fam": family_id,
                     "iat": now, "exp": exp})
    return token, jti, family_id, exp


def decode_token(token: str, expected_type: str) -> dict:
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=[ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    if data.get("type") != expected_type:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    return data


def sign_webhook(body: bytes) -> str:
    return hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()


def verify_webhook(body: bytes, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(sign_webhook(body), signature)
