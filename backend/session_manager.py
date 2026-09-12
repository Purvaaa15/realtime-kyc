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

load_dotenv()

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


# ---------------------------------------------------------------
# FUNCTION: create_session
# Generates a new session ID and initialises empty session state
# in Redis. Returns the session ID to give to the browser.
# ---------------------------------------------------------------
def create_session() -> str:
    session_id = str(uuid.uuid4())  # e.g. "a3f8c2d1-4b5e-..."

    # Initial state for a brand new KYC session
    initial_state = {
        "session_id":       session_id,
        "created_at":       datetime.utcnow().isoformat(),
        "status":           "active",     # active | completed | expired

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

    # Store in Redis as JSON string
    # f"session:{session_id}" is the Redis key
    # ex=SESSION_TTL sets automatic expiry
    redis_client.setex(
        f"session:{session_id}",
        SESSION_TTL,
        json.dumps(initial_state)
    )

    return session_id


# ---------------------------------------------------------------
# FUNCTION: get_session
# Retrieves session data from Redis by session ID.
# Returns None if session doesn't exist or has expired.
# ---------------------------------------------------------------
def get_session(session_id: str) -> dict | None:
    data = redis_client.get(f"session:{session_id}")

    if data is None:
        return None  # Session expired or never existed

    return json.loads(data)


# ---------------------------------------------------------------
# FUNCTION: update_session
# Updates specific fields in a session without overwriting others.
# Also resets the TTL so active sessions don't expire mid-verification.
#
# Example:
#   update_session(sid, {"face_found": True, "liveness_blinks": 2})
# ---------------------------------------------------------------
def update_session(session_id: str, updates: dict) -> bool:
    # Get current state
    current = get_session(session_id)

    if current is None:
        return False  # Session not found

    # Merge updates into current state
    current.update(updates)

    # Write back to Redis, reset TTL
    redis_client.setex(
        f"session:{session_id}",
        SESSION_TTL,
        json.dumps(current)
    )

    return True


# ---------------------------------------------------------------
# FUNCTION: delete_session
# Explicitly deletes a session from Redis.
# Called when verification is complete or user requests reset.
# ---------------------------------------------------------------
def delete_session(session_id: str) -> bool:
    result = redis_client.delete(f"session:{session_id}")
    return result > 0


# ---------------------------------------------------------------
# FUNCTION: get_all_sessions
# Returns a list of all active sessions.
# Used by the agent dashboard to show all ongoing verifications.
# ---------------------------------------------------------------
def get_all_sessions() -> list:
    # Redis KEYS command finds all keys matching a pattern
    # WARNING: KEYS is slow on large datasets — use SCAN in production
    keys = redis_client.keys("session:*")

    sessions = []
    for key in keys:
        data = redis_client.get(key)
        if data:
            sessions.append(json.loads(data))

    # Sort by creation time, newest first
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