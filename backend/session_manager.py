# session_manager.py
# Manages KYC sessions using Redis as the backing store.
#
# WHY REDIS?
# Redis is an in-memory key-value store. It's perfect for session data because:
#   - It's extremely fast (microsecond reads/writes)
#   - It has built-in TTL (time-to-live) — sessions auto-expire after 15 minutes
#   - It works across multiple server processes (unlike a Python dict)
#   - It persists across server restarts (unlike a Python dict)
#
# HOW SESSIONS WORK:
# 1. User opens the KYC page → server generates a UUID session ID
# 2. All session data (face_found, liveness, verdict etc.) stored in Redis
#    under key "session:{uuid}"
# 3. Every frame the browser sends includes the session ID
# 4. Server reads/writes that session's data from Redis
# 5. After 15 minutes of inactivity, Redis auto-deletes the session

import redis
import json
import uuid
import os
from datetime import datetime
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

# ---------------------------------------------------------------
# Redis connection
# redis.Redis() creates a connection pool to the Redis server.
# decode_responses=True means Redis returns strings, not bytes.
# ---------------------------------------------------------------
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True,
)

# Session TTL: 15 minutes (900 seconds)
SESSION_TTL = int(os.getenv("REDIS_TTL_SECONDS", 900))

# In-memory session fallback cache if Redis service is offline
_memory_sessions: dict[str, dict] = {}


# ---------------------------------------------------------------
# FUNCTION: create_session
# Generates a new session ID and initialises empty session state
# in Redis (or in-memory fallback). Returns session ID to browser.
# ---------------------------------------------------------------
def create_session(metadata: dict = None) -> str:
    session_id = str(uuid.uuid4())  # e.g. "a3f8c2d1-4b5e-..."
    meta = metadata or {}

    # Initial state for a brand new KYC session
    initial_state = {
        "session_id":       session_id,
        "tracking_code":    f"KYC-{session_id[:8].upper()}",
        "created_at":       datetime.utcnow().isoformat(),
        "status":           "active",     # active | completed | expired

        # Applicant & biometric consent metadata (FF180 privacy commitment)
        "user_id":          meta.get("user_id"),
        "applicant_name":   meta.get("applicant_name"),
        "applicant_email":  meta.get("applicant_email"),
        "purpose":          meta.get("purpose"),
        "consent_given":    bool(meta.get("consent_given", False)),
        "consent_at":       meta.get("consent_at"),

        # Step completion flags
        "face_found":       False,
        "liveness_passed":  False,
        "id_scanned":       False,
        "face_matched":     False,

        # Scores and data
        "liveness_blinks":  0,
        "match_confidence": 0.0,
        "match_distance":   0.0,
        "id_fields":        {},
        "fraud_score":      0.0,

        # Final verdict
        "verdict":          None,
        "verdict_reasons":  [],

        # Device info (populated when session starts)
        "ip_address":       None,
        "user_agent":       None,
    }

    try:
        redis_client.setex(
            f"session:{session_id}",
            SESSION_TTL,
            json.dumps(initial_state)
        )
    except Exception:
        _memory_sessions[session_id] = initial_state

    return session_id


# ---------------------------------------------------------------
# FUNCTION: get_session
# Retrieves session data from Redis (or in-memory cache).
# Returns None if session doesn't exist or has expired.
# ---------------------------------------------------------------
def get_session(session_id: str) -> dict | None:
    try:
        data = redis_client.get(f"session:{session_id}")
        if data is not None:
            return json.loads(data)
    except Exception:
        pass

    return _memory_sessions.get(session_id)


# ---------------------------------------------------------------
# FUNCTION: update_session
# Updates specific fields in a session without overwriting others.
# Also resets the TTL so active sessions don't expire mid-verification.
# ---------------------------------------------------------------
def update_session(session_id: str, updates: dict) -> bool:
    current = get_session(session_id)
    if current is None:
        return False

    current.update(updates)

    try:
        redis_client.setex(
            f"session:{session_id}",
            SESSION_TTL,
            json.dumps(current)
        )
    except Exception:
        _memory_sessions[session_id] = current

    return True


# ---------------------------------------------------------------
# FUNCTION: delete_session
# Explicitly deletes a session from Redis (or in-memory cache).
# ---------------------------------------------------------------
def delete_session(session_id: str) -> bool:
    deleted = False
    try:
        result = redis_client.delete(f"session:{session_id}")
        deleted = result > 0
    except Exception:
        pass

    if session_id in _memory_sessions:
        del _memory_sessions[session_id]
        deleted = True

    return deleted


# ---------------------------------------------------------------
# FUNCTION: get_all_sessions
# Returns a list of all active sessions.
# ---------------------------------------------------------------
def get_all_sessions() -> list:
    sessions = []
    try:
        keys = redis_client.keys("session:*")
        for key in keys:
            data = redis_client.get(key)
            if data:
                sessions.append(json.loads(data))
    except Exception:
        sessions = list(_memory_sessions.values())

    sessions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return sessions


# ---------------------------------------------------------------
# FUNCTION: check_redis_connection
# Simple health check — returns True if Redis is reachable.
# ---------------------------------------------------------------
def check_redis_connection() -> bool:
    try:
        redis_client.ping()
        return True
    except redis.ConnectionError:
        return False
