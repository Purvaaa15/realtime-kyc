# database.py
# Sets up the PostgreSQL database connection and defines the schema.
#
# SQLAlchemy is a Python library that lets us work with databases
# using Python classes instead of writing raw SQL.
#
# ORM = Object Relational Mapper
# It maps Python classes → database tables
# e.g. KYCSession class → kyc_sessions table in PostgreSQL

from sqlalchemy import (
    create_engine, Column, String, Boolean,
    Float, DateTime, JSON, Text, Integer, text, or_
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import os
import uuid
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BACKEND_DIR, ".env"), override=True)

# ---------------------------------------------------------------
# Database connection
# DATABASE_URL format: postgresql://user:password@host:port/dbname
# Copy backend/.env.example -> backend/.env and set your local password.
# ---------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://kyc_user:your_postgres_password@localhost:5432/kyc_db"
)

# create_engine creates the connection pool
# pool_pre_ping=True and pool_recycle=300 ensure transparent reconnection
# when Neon serverless compute wakes from idle or closes idle sockets.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"connect_timeout": 10},
)

# SessionLocal is a factory for database sessions (not KYC sessions!)
# Each request gets its own DB session, uses it, then closes it.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base is the parent class for all our model classes
Base = declarative_base()


def check_database_connection() -> bool:
    """Return True when PostgreSQL answers a lightweight SELECT 1 query."""
    import time
    for attempt in range(2):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            if attempt == 0:
                time.sleep(0.5)
                continue
            print(f"[check_database_connection] DB health check warning: {e}")
            return False
    return False


# ---------------------------------------------------------------
# MODEL: User
# Stores registered applicants and compliance reviewers for full-stack
# role-based authentication (applicant | reviewer).
# ---------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id            = Column(String, primary_key=True, index=True)
    full_name     = Column(String, nullable=False)
    email         = Column(String, unique=True, index=True, nullable=False)
    phone         = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    role          = Column(String, default="applicant")  # applicant | reviewer
    created_at    = Column(DateTime, default=datetime.utcnow)


def user_to_dict(user: "User") -> dict:
    """Serialize a User record safely without exposing password_hash."""
    return {
        "id":         user.id,
        "full_name":  user.full_name,
        "email":      user.email,
        "phone":      user.phone,
        "role":       user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


# ---------------------------------------------------------------
# MODEL: ConsentRecord
# Permanent proof of user consent for live camera & biometric processing,
# aligned with DPDP / FF180 privacy commitments.
# ---------------------------------------------------------------
class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    session_id      = Column(String, index=True, nullable=False)
    user_id         = Column(String, index=True, nullable=True)
    applicant_name  = Column(String, nullable=True)
    applicant_email = Column(String, nullable=True)
    purpose         = Column(String, nullable=True)
    consent_given   = Column(Boolean, default=True)
    consent_version = Column(String, default="v1.0-DPDP")
    ip_address      = Column(String, nullable=True)
    timestamp       = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------
# MODEL: KYCSession
# Stores the final record of every completed KYC session.
# One row per session.
#
# This is the permanent audit trail — Redis is temporary,
# PostgreSQL is the permanent record.
# ---------------------------------------------------------------
class KYCSession(Base):
    __tablename__ = "kyc_sessions"

    # Primary key — same UUID used in Redis
    id              = Column(String, primary_key=True, index=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    completed_at    = Column(DateTime, nullable=True)

    # Applicant & consent metadata
    user_id         = Column(String, nullable=True, index=True)
    applicant_name  = Column(String, nullable=True)
    applicant_email = Column(String, nullable=True)
    purpose         = Column(String, nullable=True)
    tracking_code   = Column(String, nullable=True, index=True)
    consent_given   = Column(Boolean, default=False)
    consent_at      = Column(DateTime, nullable=True)
    erased_at       = Column(DateTime, nullable=True)

    # Final verdict
    verdict         = Column(String, nullable=True)   # PASS/FAIL/REVIEW
    verdict_message = Column(Text, nullable=True)

    # Step results
    face_found      = Column(Boolean, default=False)
    liveness_passed = Column(Boolean, default=False)
    id_scanned      = Column(Boolean, default=False)
    face_matched    = Column(Boolean, default=False)

    # Scores & anti-spoofing metrics
    match_confidence = Column(Float, default=0.0)
    match_distance   = Column(Float, default=0.0)
    fraud_score      = Column(Float, default=0.0)
    liveness_blinks  = Column(Integer, default=0)
    spoof_detected   = Column(Boolean, default=False)
    spoof_score      = Column(Float, nullable=True)

    # Extracted ID data (stored as JSON)
    id_fields        = Column(JSON, nullable=True)

    # Verdict reasons (list stored as JSON)
    verdict_reasons  = Column(JSON, nullable=True)

    # Device/network info
    ip_address       = Column(String, nullable=True)
    user_agent       = Column(String, nullable=True)

    # Agent review fields
    reviewed_by      = Column(String, nullable=True)
    review_note      = Column(Text, nullable=True)
    review_action    = Column(String, nullable=True)  # approved/rejected/escalated
    reviewed_at      = Column(DateTime, nullable=True)


# ---------------------------------------------------------------
# FUNCTION: session_to_dict
# Converts a KYCSession database row into a plain dictionary
# so it can be returned as JSON from a FastAPI route.
# ---------------------------------------------------------------
def session_to_dict(session: "KYCSession") -> dict:
    return {
        "id":               session.id,
        "tracking_code":    session.tracking_code or f"KYC-{session.id[:8].upper()}",
        "user_id":          session.user_id,
        "applicant_name":   session.applicant_name,
        "applicant_email":  session.applicant_email,
        "purpose":          session.purpose,
        "consent_given":    bool(session.consent_given),
        "consent_at":       session.consent_at.isoformat() if session.consent_at else None,
        "erased_at":        session.erased_at.isoformat() if session.erased_at else None,
        "created_at":       session.created_at.isoformat() if session.created_at else None,
        "completed_at":     session.completed_at.isoformat() if session.completed_at else None,
        "verdict":          session.verdict,
        "verdict_message":  session.verdict_message,
        "face_found":       session.face_found,
        "liveness_passed":  session.liveness_passed,
        "id_scanned":       session.id_scanned,
        "face_matched":     session.face_matched,
        "match_confidence": session.match_confidence,
        "match_distance":   session.match_distance,
        "fraud_score":      session.fraud_score,
        "liveness_blinks":  session.liveness_blinks,
        "spoof_detected":   session.spoof_detected,
        "spoof_score":      session.spoof_score,
        "id_fields":        session.id_fields,
        "verdict_reasons":  session.verdict_reasons,
        "ip_address":       session.ip_address,
        "user_agent":       session.user_agent,
        "reviewed_by":      session.reviewed_by,
        "review_note":      session.review_note,
        "review_action":    session.review_action,
        "reviewed_at":      session.reviewed_at.isoformat() if session.reviewed_at else None,
    }


def audit_event_to_dict(event: "AuditEvent") -> dict:
    return {
        "id":         event.id,
        "session_id": event.session_id,
        "timestamp":  event.timestamp.isoformat() if event.timestamp else None,
        "event_type": event.event_type,
        "details":    event.details,
        "actor":      event.actor,
    }


# ---------------------------------------------------------------
# MODEL: AuditEvent
# Append-only log of everything that happens in a session.
# One row per event (face_detected, blink, liveness_pass, etc.)
#
# This gives a complete timeline of every session — invaluable
# for debugging, compliance, and fraud investigation.
# ---------------------------------------------------------------
class AuditEvent(Base):
    __tablename__ = "audit_events"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    session_id  = Column(String, index=True)
    timestamp   = Column(DateTime, default=datetime.utcnow)
    event_type  = Column(String)   # face_detected, blink, liveness_pass, etc.
    details     = Column(JSON, nullable=True)  # any extra data for this event
    actor       = Column(String, default="system")  # system or agent name


# ---------------------------------------------------------------
# FUNCTION: create_tables
# Creates all tables in PostgreSQL if they don't exist yet.
# Also safely adds any new columns to existing tables so upgrades
# don't crash on an already-initialized database.
# ---------------------------------------------------------------
def create_tables():
    Base.metadata.create_all(bind=engine)

    # Safely add new columns if upgrading an existing kyc_sessions table
    migrations = [
        "ALTER TABLE kyc_sessions ADD COLUMN IF NOT EXISTS spoof_detected BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE kyc_sessions ADD COLUMN IF NOT EXISTS spoof_score FLOAT;",
        "ALTER TABLE kyc_sessions ADD COLUMN IF NOT EXISTS user_id VARCHAR;",
        "ALTER TABLE kyc_sessions ADD COLUMN IF NOT EXISTS applicant_name VARCHAR;",
        "ALTER TABLE kyc_sessions ADD COLUMN IF NOT EXISTS applicant_email VARCHAR;",
        "ALTER TABLE kyc_sessions ADD COLUMN IF NOT EXISTS purpose VARCHAR;",
        "ALTER TABLE kyc_sessions ADD COLUMN IF NOT EXISTS tracking_code VARCHAR;",
        "ALTER TABLE kyc_sessions ADD COLUMN IF NOT EXISTS consent_given BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE kyc_sessions ADD COLUMN IF NOT EXISTS consent_at TIMESTAMP;",
        "ALTER TABLE kyc_sessions ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;",
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            conn.execute(text(stmt))
        conn.commit()


# ---------------------------------------------------------------
# FUNCTION: get_db
# FastAPI dependency — gives each request a DB session,
# and ensures it's closed properly even if an error occurs.
#
# Usage in route:
#   @app.post("/something")
#   async def route(db: Session = Depends(get_db)):
#       db.add(something)
#       db.commit()
# ---------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------
# USER ACCOUNT & CONSENT HELPERS
# ---------------------------------------------------------------
def create_user_record(full_name: str, email: str, password_hash: str, phone: str = None, role: str = "applicant") -> "User | None":
    db = SessionLocal()
    try:
        user = User(
            id            = str(uuid.uuid4()),
            full_name     = full_name.strip(),
            email         = email.strip().lower(),
            phone         = phone.strip() if phone else None,
            password_hash = password_hash,
            role          = role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except Exception as e:
        db.rollback()
        print(f"Create user error: {e}")
        return None
    finally:
        db.close()


def get_user_by_email(email: str) -> "User | None":
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email.strip().lower()).first()
    finally:
        db.close()


def get_user_by_id(user_id: str) -> "User | None":
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()


def record_consent(
    session_id: str,
    user_id: str = None,
    applicant_name: str = None,
    applicant_email: str = None,
    purpose: str = None,
    consent_given: bool = True,
    ip_address: str = None,
    consent_version: str = "v1.0-DPDP",
) -> bool:
    db = SessionLocal()
    try:
        rec = ConsentRecord(
            session_id      = session_id,
            user_id         = user_id,
            applicant_name  = applicant_name,
            applicant_email = applicant_email,
            purpose         = purpose,
            consent_given   = consent_given,
            consent_version = consent_version,
            ip_address      = ip_address,
        )
        db.add(rec)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Consent save error: {e}")
        return False
    finally:
        db.close()


# ---------------------------------------------------------------
# FUNCTION: save_session_to_db
# Called when a session is complete (verdict reached).
# Writes the final session state from Redis to PostgreSQL.
# ---------------------------------------------------------------
def save_session_to_db(session_data: dict):
    db = SessionLocal()
    try:
        consent_at_raw = session_data.get("consent_at")
        consent_at_dt = datetime.fromisoformat(consent_at_raw) if consent_at_raw else None

        record = KYCSession(
            id               = session_data["session_id"],
            tracking_code    = session_data.get("tracking_code") or f"KYC-{session_data['session_id'][:8].upper()}",
            user_id          = session_data.get("user_id"),
            applicant_name   = session_data.get("applicant_name"),
            applicant_email  = session_data.get("applicant_email"),
            purpose          = session_data.get("purpose"),
            consent_given    = bool(session_data.get("consent_given", False)),
            consent_at       = consent_at_dt,
            created_at       = datetime.fromisoformat(session_data["created_at"]),
            completed_at     = datetime.utcnow(),
            verdict          = session_data.get("verdict"),
            verdict_message  = session_data.get("verdict_message"),
            face_found       = session_data.get("face_found", False),
            liveness_passed  = session_data.get("liveness_passed", False),
            id_scanned       = session_data.get("id_scanned", False),
            face_matched     = session_data.get("face_matched", False),
            match_confidence = session_data.get("match_confidence", 0.0),
            match_distance   = session_data.get("match_distance", 0.0),
            fraud_score      = session_data.get("fraud_score", 0.0),
            liveness_blinks  = session_data.get("liveness_blinks", 0),
            spoof_detected   = session_data.get("spoof_detected", False),
            spoof_score      = session_data.get("spoof_score"),
            id_fields        = session_data.get("id_fields", {}),
            verdict_reasons  = session_data.get("verdict_reasons", []),
            ip_address       = session_data.get("ip_address"),
            user_agent       = session_data.get("user_agent"),
        )
        db.add(record)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"DB save error: {e}")
        return False
    finally:
        db.close()


# ---------------------------------------------------------------
# FUNCTION: log_audit_event
# Appends one event to the audit log for a session.
# ---------------------------------------------------------------
def log_audit_event(session_id: str, event_type: str, details: dict = None, actor: str = "system"):
    db = SessionLocal()
    try:
        event = AuditEvent(
            session_id = session_id,
            event_type = event_type,
            details    = details or {},
            actor      = actor,
        )
        db.add(event)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Audit log error: {e}")
    finally:
        db.close()


# ---------------------------------------------------------------
# FUNCTION: get_fraud_history_signals
# Checks historical sessions in PostgreSQL for suspicious reuse:
# - Has this same ID number appeared in earlier sessions or failed attempts?
# - Has this same IP address had multiple failed/spoofed attempts recently?
# ---------------------------------------------------------------
def get_fraud_history_signals(session_id: str, id_number: str = None, ip_address: str = None) -> dict:
    db = SessionLocal()
    try:
        recent_sessions = (
            db.query(KYCSession)
            .filter(KYCSession.id != session_id)
            .order_by(KYCSession.created_at.desc())
            .limit(250)
            .all()
        )

        id_reuse_count = 0
        id_prior_failed = False
        ip_recent_failures = 0
        ip_total_recent = 0

        cutoff_24h = datetime.utcnow() - timedelta(hours=24)

        for s in recent_sessions:
            # Check ID number reuse across historical records
            if id_number:
                s_id_num = (s.id_fields or {}).get("id_number")
                if s_id_num and str(s_id_num).strip() == str(id_number).strip():
                    id_reuse_count += 1
                    if s.verdict == "FAIL" or s.spoof_detected:
                        id_prior_failed = True

            # Check IP velocity within the last 24 hours
            # Note: localhost ("127.0.0.1") during local testing will match often,
            # so we only count FAILED/SPOOFED attempts to avoid penalizing local dev tests.
            if ip_address and s.ip_address == ip_address:
                if s.created_at and s.created_at >= cutoff_24h:
                    ip_total_recent += 1
                    if s.verdict == "FAIL" or s.spoof_detected:
                        ip_recent_failures += 1

        return {
            "id_reuse_count": id_reuse_count,
            "id_prior_failed": id_prior_failed,
            "ip_recent_failures": ip_recent_failures,
            "ip_total_recent": ip_total_recent,
        }
    except Exception as e:
        print(f"Fraud history lookup error: {e}")
        return {
            "id_reuse_count": 0,
            "id_prior_failed": False,
            "ip_recent_failures": 0,
            "ip_total_recent": 0,
        }
    finally:
        db.close()


# ---------------------------------------------------------------
# FUNCTION: get_all_sessions_from_db
# Returns completed sessions from PostgreSQL for the dashboard.
# Supports optional filtering by verdict.
# ---------------------------------------------------------------
def get_all_sessions_from_db(verdict_filter: str = None, limit: int = 100):
    db = SessionLocal()
    try:
        query = db.query(KYCSession).order_by(KYCSession.created_at.desc())

        if verdict_filter and verdict_filter != "ALL":
            query = query.filter(KYCSession.verdict == verdict_filter)

        results = query.limit(limit).all()
        return results
    finally:
        db.close()


# ---------------------------------------------------------------
# FUNCTION: get_session_from_db
# Returns one session's full record by ID.
# ---------------------------------------------------------------
def get_session_from_db(session_id: str):
    db = SessionLocal()
    try:
        return db.query(KYCSession).filter(KYCSession.id == session_id).first()
    finally:
        db.close()


def lookup_session_by_ref(ref: str):
    """
    Find a completed session by full UUID, tracking code (KYC-XXXXXXXX),
    or 8+ character UUID prefix for the public Applicant Status Tracker.
    """
    clean = (ref or "").strip()
    if len(clean) < 8:
        return None

    db = SessionLocal()
    try:
        # 1. Exact UUID match or exact tracking_code match
        row = (
            db.query(KYCSession)
            .filter(
                or_(
                    KYCSession.id == clean,
                    KYCSession.tracking_code == clean.upper(),
                )
            )
            .first()
        )
        if row:
            return row

        # 2. Match 8-char prefix (either bare hex like "9772548d" or "KYC-9772548D")
        prefix = clean.upper().replace("KYC-", "").lower()
        if len(prefix) >= 8:
            return (
                db.query(KYCSession)
                .filter(KYCSession.id.like(f"{prefix}%"))
                .order_by(KYCSession.created_at.desc())
                .first()
            )
        return None
    finally:
        db.close()


def get_sessions_for_user(user_id: str = None, email: str = None, limit: int = 50):
    """Return all KYC sessions submitted by a registered user."""
    db = SessionLocal()
    try:
        filters = []
        if user_id:
            filters.append(KYCSession.user_id == user_id)
        if email:
            filters.append(KYCSession.applicant_email == email.strip().lower())
        if not filters:
            return []
        return (
            db.query(KYCSession)
            .filter(or_(*filters))
            .order_by(KYCSession.created_at.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()


def erase_session_pii(session_id: str) -> bool:
    """
    Scrub personally identifying fields on a KYCSession record after
    deleting encrypted evidence from the vault (DPDP right-to-erasure).
    """
    db = SessionLocal()
    try:
        session = db.query(KYCSession).filter(KYCSession.id == session_id).first()
        if session is None:
            return False

        existing_type = (session.id_fields or {}).get("id_type")
        session.applicant_name = "[REDACTED]"
        session.applicant_email = "[REDACTED]"
        session.id_fields = {
            "id_type": existing_type,
            "redacted": True,
            "validation_note": "PII erased per privacy request",
        }
        session.erased_at = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"PII erase error: {e}")
        return False
    finally:
        db.close()


# ---------------------------------------------------------------
# FUNCTION: get_audit_trail
# Returns the full event timeline for one session.
# ---------------------------------------------------------------
def get_audit_trail(session_id: str):
    db = SessionLocal()
    try:
        events = (
            db.query(AuditEvent)
            .filter(AuditEvent.session_id == session_id)
            .order_by(AuditEvent.timestamp.asc())
            .all()
        )
        return events
    finally:
        db.close()


# ---------------------------------------------------------------
# FUNCTION: update_review
# Called when an agent approves/rejects/escalates a REVIEW session.
# ---------------------------------------------------------------
def update_review(session_id: str, action: str, reviewer: str, note: str = ""):
    db = SessionLocal()
    try:
        session = db.query(KYCSession).filter(KYCSession.id == session_id).first()
        if session is None:
            return False

        session.review_action = action       # approved / rejected / escalated
        session.reviewed_by   = reviewer
        session.review_note   = note
        session.reviewed_at   = datetime.utcnow()

        # If approved, upgrade verdict to PASS; if rejected, to FAIL
        # If escalated, keep verdict as REVIEW so it remains visible for senior review
        if action == "approved":
            session.verdict = "PASS"
        elif action == "rejected":
            session.verdict = "FAIL"

        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print(f"Review update error: {e}")
        return False
    finally:
        db.close()


# ---------------------------------------------------------------
# FUNCTION: get_dashboard_stats
# Returns summary counts for the dashboard header cards.
# ---------------------------------------------------------------
def get_dashboard_stats():
    db = SessionLocal()
    try:
        total    = db.query(KYCSession).count()
        passed   = db.query(KYCSession).filter(KYCSession.verdict == "PASS").count()
        failed   = db.query(KYCSession).filter(KYCSession.verdict == "FAIL").count()
        review   = db.query(KYCSession).filter(KYCSession.verdict == "REVIEW").count()

        pass_rate = round((passed / total * 100), 1) if total > 0 else 0

        return {
            "total":     total,
            "passed":    passed,
            "failed":    failed,
            "review":    review,
            "pass_rate": pass_rate,
        }
    finally:
        db.close()


# ---------------------------------------------------------------
# FUNCTION: get_dashboard_analytics
# Computes detailed operational analytics across all stored sessions:
# - Verdict breakdown & incomplete count
# - Average match confidence, average fraud risk, & average session duration
# - Spoof flag count & spoof rate
# - ID document type distribution
# ---------------------------------------------------------------
def get_dashboard_analytics():
    db = SessionLocal()
    try:
        sessions = db.query(KYCSession).all()
        total = len(sessions)

        if total == 0:
            return {
                "total": 0,
                "verdicts": {"PASS": 0, "REVIEW": 0, "FAIL": 0, "INCOMPLETE": 0},
                "avg_confidence": 0.0,
                "avg_fraud_score": 0.0,
                "high_risk_count": 0,
                "avg_duration_sec": 0.0,
                "spoof_flagged": 0,
                "spoof_rate": 0.0,
                "id_types": {},
            }

        verdicts = {"PASS": 0, "REVIEW": 0, "FAIL": 0, "INCOMPLETE": 0}
        confidences = []
        fraud_scores = []
        high_risk_count = 0
        durations = []
        spoof_flagged = 0
        id_types = {}

        for s in sessions:
            v = s.verdict or "INCOMPLETE"
            verdicts[v] = verdicts.get(v, 0) + 1

            if s.match_confidence and s.match_confidence > 0:
                confidences.append(s.match_confidence)

            if s.fraud_score is not None:
                fraud_scores.append(s.fraud_score)
                if s.fraud_score >= 55.0:
                    high_risk_count += 1

            if s.created_at and s.completed_at:
                diff = (s.completed_at - s.created_at).total_seconds()
                if 0 <= diff < 3600:  # ignore outliers > 1 hr
                    durations.append(diff)

            if s.spoof_detected:
                spoof_flagged += 1

            doc_type = (s.id_fields or {}).get("id_type") or "Unclassified"
            id_types[doc_type] = id_types.get(doc_type, 0) + 1

        avg_conf = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
        avg_fraud = round(sum(fraud_scores) / len(fraud_scores), 1) if fraud_scores else 0.0
        avg_dur  = round(sum(durations) / len(durations), 1) if durations else 0.0
        spoof_rate = round((spoof_flagged / total) * 100, 1)

        return {
            "total": total,
            "verdicts": verdicts,
            "avg_confidence": avg_conf,
            "avg_fraud_score": avg_fraud,
            "high_risk_count": high_risk_count,
            "avg_duration_sec": avg_dur,
            "spoof_flagged": spoof_flagged,
            "spoof_rate": spoof_rate,
            "id_types": id_types,
        }
    finally:
        db.close()
