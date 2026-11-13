# auth.py
# Full-stack authentication & Role-Based Access Control (RBAC) for PehchaanAI.
#
# HOW IT WORKS (zero external crypto dependencies needed):
#   1. Passwords are hashed using PBKDF2-HMAC-SHA256 (120,000 iterations) with a
#      random 16-byte per-user salt — standard NIST-recommended password hashing.
#   2. Sessions use compact HMAC-SHA256 signed JSON Web Tokens (HS256 JWTs)
#      containing { sub, email, name, role, exp }.
#   3. Reviewer routes support BOTH signed reviewer JWTs (Authorization: Bearer)
#      AND the legacy X-Dashboard-Auth passcode for backward compatibility.

import os
import json
import hmac
import time
import base64
import hashlib
import secrets
from typing import Optional
from fastapi import Request
from dotenv import load_dotenv

from database import create_user_record, get_user_by_email, get_user_by_id, user_to_dict

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

TOKEN_TTL_SECONDS = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", "86400"))  # 24h
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")
DEFAULT_REVIEWER_EMAIL = "reviewer@pehchaanai.local"


def _get_signing_key() -> bytes:
    secret = os.getenv("SECRET_KEY", "pehchaan-dev-secret-change-in-prod").strip()
    if not secret:
        secret = "pehchaan-dev-secret-change-in-prod"
    return hashlib.sha256(f"pehchaan-jwt:{secret}".encode("utf-8")).digest()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad_len = (-len(data)) % 4
    return base64.urlsafe_b64decode(data + ("=" * pad_len))


def hash_password(password: str) -> str:
    """Hash a plaintext password using PBKDF2-HMAC-SHA256 + random 16-byte salt."""
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time verification against a stored PBKDF2 hash."""
    try:
        scheme, salt, expected_hex = stored_hash.split("$", 2)
        if scheme != "pbkdf2_sha256":
            return False
        actual_hex = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120_000,
        ).hex()
        return hmac.compare_digest(actual_hex, expected_hex)
    except Exception:
        return False


def create_access_token(user_dict: dict, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    """Create a signed HS256 JWT token for an authenticated User."""
    now = int(time.time())
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = _b64url_encode(json.dumps({
        "sub":   user_dict["id"],
        "email": user_dict["email"],
        "name":  user_dict["full_name"],
        "role":  user_dict["role"],
        "iat":   now,
        "exp":   now + ttl_seconds,
    }, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    sig = _b64url_encode(hmac.new(_get_signing_key(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def decode_access_token(token: str) -> Optional[dict]:
    """Verify JWT signature and expiration. Returns payload dict or None."""
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = _b64url_encode(
            hmac.new(_get_signing_key(), signing_input, hashlib.sha256).digest()
        )
        if not hmac.compare_digest(sig_b64, expected_sig):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def extract_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


def get_current_user_optional(request: Request) -> Optional[dict]:
    """Return the authenticated User dict if a valid Bearer token was sent, else None."""
    token = extract_bearer_token(request)
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        return None
    user = get_user_by_id(payload["sub"])
    if not user:
        return None
    return user_to_dict(user)


def get_reviewer_identity(request: Request) -> Optional[str]:
    """
    Authorize reviewer/dashboard endpoints via EITHER:
      - Role-verified Bearer JWT (`role` == 'reviewer' or 'admin'), OR
      - Legacy X-Dashboard-Auth header matching DASHBOARD_PASSWORD.
    Returns reviewer display name if authorized, or None if unauthorized.
    """
    user = get_current_user_optional(request)
    if user and user.get("role") in ("reviewer", "admin"):
        return user["full_name"]

    provided = request.headers.get("X-Dashboard-Auth", "")
    if provided and hmac.compare_digest(provided, DASHBOARD_PASSWORD):
        return "Compliance Reviewer"

    return None


def ensure_default_reviewer():
    """
    Create a seeded demo compliance reviewer account on startup if missing,
    so the Reviewer Portal works with email/password login out of the box.
    """
    existing = get_user_by_email(DEFAULT_REVIEWER_EMAIL)
    if existing:
        return existing

    # Ensure password meets minimum length even if env passcode is custom
    raw_pass = DASHBOARD_PASSWORD if len(DASHBOARD_PASSWORD) >= 6 else f"{DASHBOARD_PASSWORD}123456"[:12]
    pw_hash = hash_password(raw_pass)
    return create_user_record(
        full_name="Compliance Officer",
        email=DEFAULT_REVIEWER_EMAIL,
        password_hash=pw_hash,
        phone=None,
        role="reviewer",
    )
