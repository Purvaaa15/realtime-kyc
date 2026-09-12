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
    Float, DateTime, JSON, Text, Integer
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------
# Database connection
# DATABASE_URL format: postgresql://user:password@host:port/dbname
# ---------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://kyc_user:Purv%402005@localhost:5432/kyc_db"
)

# create_engine creates the connection pool
engine = create_engine(DATABASE_URL)

# SessionLocal is a factory for database sessions (not KYC sessions!)
# Each request gets its own DB session, uses it, then closes it.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base is the parent class for all our model classes
Base = declarative_base()


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

    # Final verdict
    verdict         = Column(String, nullable=True)   # PASS/FAIL/REVIEW
    verdict_message = Column(Text, nullable=True)

    # Step results
    face_found      = Column(Boolean, default=False)
    liveness_passed = Column(Boolean, default=False)
    id_scanned      = Column(Boolean, default=False)
    face_matched    = Column(Boolean, default=False)

    # Scores
    match_confidence = Column(Float, default=0.0)
    match_distance   = Column(Float, default=0.0)
    fraud_score      = Column(Float, default=0.0)
    liveness_blinks  = Column(Integer, default=0)

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
# MODEL: AuditEvent
# Append-only log of everything that happens in a session.
# One row per event (face_detected, blink_detected, etc.)
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
# Safe to run multiple times — won't drop existing tables.
# ---------------------------------------------------------------
def create_tables():
    Base.metadata.create_all(bind=engine)


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
# FUNCTION: save_session_to_db
# Called when a session is complete (verdict reached).
# Writes the final session state from Redis to PostgreSQL.
# ---------------------------------------------------------------
def save_session_to_db(session_data: dict):
    db = SessionLocal()
    try:
        record = KYCSession(
            id               = session_data["session_id"],
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
def log_audit_event(session_id: str, event_type: str, details: dict = None):
    db = SessionLocal()
    try:
        event = AuditEvent(
            session_id = session_id,
            event_type = event_type,
            details    = details or {},
        )
        db.add(event)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Audit log error: {e}")
    finally:
        db.close()