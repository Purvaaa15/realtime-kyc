# vault.py
# Encrypted Evidence Vault for PehchaanAI.
#
# PURPOSE (FF180 Objective 4 - Privacy & Protected Biometric Storage):
# Instead of saving plaintext ID card and selfie photos to disk where anyone
# with folder access could view them, this module encrypts every evidence
# image BEFORE writing it to uploads/vault/<sid8>_<kind>.enc using Fernet
# symmetric encryption (AES-128-CBC + HMAC-SHA256 authentication).
#
# Why HMAC authentication matters:
# If someone modifies even 1 byte of an .enc file on disk, decryption fails
# safely with InvalidToken rather than silently returning corrupted bytes.
#
# MVP LIMITATION (be honest in project reports):
# By default, the Fernet key is derived deterministically from VAULT_KEY or
# SECRET_KEY in backend/.env. In production, you should set a dedicated,
# high-entropy VAULT_KEY stored in a Cloud KMS / Secrets Manager and rotate
# keys periodically.

import os
import time
import base64
import hashlib
from typing import Optional
from dotenv import load_dotenv
from cryptography.fernet import Fernet, InvalidToken

# Load backend/.env if it hasn't been loaded yet (safe to call multiple times)
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

UPLOADS_DIR = os.path.abspath(os.path.join(BACKEND_DIR, "..", "uploads"))
VAULT_DIR   = os.path.join(UPLOADS_DIR, "vault")

VALID_DOC_KINDS = ("id", "selfie")
DEFAULT_RETENTION_DAYS = int(os.getenv("VAULT_RETENTION_DAYS", "30"))


def _get_fernet() -> Fernet:
    """
    Build the Fernet cipher instance used to encrypt and decrypt evidence blobs.

    Priority:
      1. VAULT_KEY env var (used directly if it is already a valid Fernet key,
         otherwise hashed via SHA-256 into a 32-byte URL-safe base64 key).
      2. SECRET_KEY env var (hashed via SHA-256 so existing .env setups work
         out of the box without manual key generation).
    """
    vault_key = os.getenv("VAULT_KEY", "").strip()
    if vault_key:
        try:
            # Accept a genuine Fernet key directly (generated via Fernet.generate_key())
            return Fernet(vault_key.encode("utf-8"))
        except Exception:
            # If user put a regular passphrase in VAULT_KEY, derive a 32-byte key
            digest = hashlib.sha256(vault_key.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(digest))

    secret = os.getenv("SECRET_KEY", "pehchaan-dev-secret-change-in-prod").strip()
    if not secret:
        secret = "pehchaan-dev-secret-change-in-prod"
    digest = hashlib.sha256(f"pehchaan-vault:{secret}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _sanitize_sid(session_id: str) -> str:
    """
    Extract a safe 8-character prefix from session_id so user input can never
    cause directory traversal (e.g. '../../something').
    """
    cleaned = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    sid8 = cleaned[:8]
    if not sid8:
        raise ValueError("Invalid session_id for evidence vault")
    return sid8


def _evidence_path(session_id: str, doc_kind: str) -> str:
    """Resolve uploads/vault/<sid8>_<doc_kind>.enc after validating doc_kind."""
    if doc_kind not in VALID_DOC_KINDS:
        raise ValueError(f"Unsupported doc_kind '{doc_kind}'. Expected one of {VALID_DOC_KINDS}.")
    sid8 = _sanitize_sid(session_id)
    return os.path.join(VAULT_DIR, f"{sid8}_{doc_kind}.enc")


def encrypt_evidence(session_id: str, doc_kind: str, raw_bytes: bytes) -> str:
    """
    Encrypt raw image bytes and store them in uploads/vault/<sid8>_<doc_kind>.enc.
    Returns the encrypted file path on disk.
    """
    if not raw_bytes:
        raise ValueError("Cannot encrypt empty evidence bytes")

    os.makedirs(VAULT_DIR, exist_ok=True)
    path = _evidence_path(session_id, doc_kind)

    token = _get_fernet().encrypt(raw_bytes)
    with open(path, "wb") as f:
        f.write(token)

    return path


def decrypt_evidence(session_id: str, doc_kind: str) -> Optional[bytes]:
    """
    Read and decrypt stored evidence bytes for a session.
    Returns None if the encrypted file does not exist or decryption fails
    (e.g., tampered ciphertext or mismatched encryption key).
    """
    try:
        path = _evidence_path(session_id, doc_kind)
    except ValueError:
        return None

    if not os.path.isfile(path):
        return None

    try:
        with open(path, "rb") as f:
            token = f.read()
        return _get_fernet().decrypt(token)
    except (InvalidToken, OSError) as exc:
        print(f"[Vault] Decryption failed for {os.path.basename(path)}: {exc}")
        return None


def evidence_exists(session_id: str, doc_kind: str) -> bool:
    """Return True if an encrypted evidence blob exists for this session/kind."""
    try:
        return os.path.isfile(_evidence_path(session_id, doc_kind))
    except ValueError:
        return False


def get_evidence_media_type(raw_bytes: bytes) -> str:
    """
    Infer MIME type from decrypted file magic bytes so the browser renders
    PNG, JPEG, or WebP evidence accurately regardless of original upload format.
    """
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(raw_bytes) >= 12 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "image/webp"
    if raw_bytes.startswith(b"%PDF"):
        return "application/pdf"
    return "image/jpeg"


def get_vault_stats(retention_days: int = DEFAULT_RETENTION_DAYS) -> dict:
    """
    Summarize encrypted evidence files currently stored in the vault, including
    how many files have passed the configured retention window.
    """
    if not os.path.isdir(VAULT_DIR):
        return {
            "total_files":    0,
            "id_files":       0,
            "selfie_files":   0,
            "total_bytes":    0,
            "total_kb":       0.0,
            "expired_count":  0,
            "retention_days": retention_days,
        }

    cutoff = time.time() - (max(retention_days, 0) * 86400)
    total_files = 0
    id_files = 0
    selfie_files = 0
    total_bytes = 0
    expired_count = 0

    for entry in os.scandir(VAULT_DIR):
        if not entry.is_file() or not entry.name.endswith(".enc"):
            continue
        stat = entry.stat()
        total_files += 1
        total_bytes += stat.st_size
        if entry.name.endswith("_id.enc"):
            id_files += 1
        elif entry.name.endswith("_selfie.enc"):
            selfie_files += 1
        if stat.st_mtime < cutoff:
            expired_count += 1

    return {
        "total_files":    total_files,
        "id_files":       id_files,
        "selfie_files":   selfie_files,
        "total_bytes":    total_bytes,
        "total_kb":       round(total_bytes / 1024.0, 2),
        "expired_count":  expired_count,
        "retention_days": retention_days,
    }


def purge_expired_evidence(retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """
    Delete encrypted .enc files whose last-modified timestamp is older than
    `retention_days` days. Supports privacy/data-minimization retention policies.
    Returns the number of deleted files.
    """
    if retention_days < 0:
        raise ValueError("retention_days must be >= 0")

    if not os.path.isdir(VAULT_DIR):
        return 0

    cutoff = time.time() - (retention_days * 86400)
    deleted = 0

    for entry in os.scandir(VAULT_DIR):
        if not entry.is_file() or not entry.name.endswith(".enc"):
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                os.remove(entry.path)
                deleted += 1
        except OSError as exc:
            print(f"[Vault] Failed to purge {entry.name}: {exc}")

    return deleted


def delete_session_evidence(session_id: str) -> int:
    """
    Delete all encrypted evidence files belonging to one specific session.
    Used when an applicant exercises right-to-erasure (DPDP privacy policy).
    Returns the number of deleted files.
    """
    deleted = 0
    for kind in VALID_DOC_KINDS:
        try:
            path = _evidence_path(session_id, kind)
        except ValueError:
            continue
        if os.path.isfile(path):
            try:
                os.remove(path)
                deleted += 1
            except OSError as exc:
                print(f"[Vault] Failed to delete {os.path.basename(path)}: {exc}")
    return deleted
