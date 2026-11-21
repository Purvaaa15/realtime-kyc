# main.py
# Entry point for the AI-Powered KYC Platform.
# Now supports:
#   - Multi-user Redis sessions (each user gets their own UUID)
#   - WebSocket real-time frame streaming
#   - PostgreSQL audit logging
#   - Explainable verdicts with reasons

import sys
import os

# Ensure backend directory is in Python module search path
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(_BACKEND_DIR, ".env"), override=True)

from spoof_detector import analyze_spoof, extract_face_region
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, Depends, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from sqlalchemy.orm import Session
import uvicorn
import os
import io
import csv
import json
import base64
import mimetypes
from datetime import datetime
import numpy as np
import cv2
from dotenv import load_dotenv

# Our custom modules
from face_detector import detect_face, LEFT_EYE_EAR_POINTS, RIGHT_EYE_EAR_POINTS
from ocr import is_pdf, pdf_to_image_bytes, scan_document, _resolve_tesseract_cmd, redact_aadhaar_digits
from vault import (
    encrypt_evidence,
    decrypt_evidence,
    evidence_exists,
    get_evidence_media_type,
    get_vault_stats,
    purge_expired_evidence,
    delete_session_evidence,
)
from liveness import LivenessChecker
from face_match import match_faces
from decision import make_decision
from fraud_engine import compute_fraud_risk
from session_manager import (
    create_session, get_session, update_session,
    delete_session, get_all_sessions, check_redis_connection
)
from database import (
    get_db, save_session_to_db, log_audit_event, create_tables,
    get_all_sessions_from_db, get_session_from_db, get_audit_trail,
    update_review, get_dashboard_stats, get_dashboard_analytics,
    session_to_dict, audit_event_to_dict, user_to_dict,
    create_user_record, get_user_by_email, record_consent,
    lookup_session_by_ref, get_sessions_for_user, erase_session_pii,
    check_database_connection,
)
from auth import (
    hash_password, verify_password, create_access_token,
    get_current_user_optional, get_reviewer_identity, ensure_default_reviewer,
)
from ai_agent import (
    chat_assistant, explain_session_for_user, summarize_session_for_reviewer,
)

# ---------------------------------------------------------------
# Absolute paths & explicit .env loading (works from any CWD)
# ---------------------------------------------------------------
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
ROOT_DIR     = os.path.join(BASE_DIR, "..")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
SPA_DIST_DIR = os.path.abspath(os.path.join(ROOT_DIR, "frontend-web", "dist"))
UPLOADS_DIR  = os.path.join(ROOT_DIR, "uploads")

os.makedirs(UPLOADS_DIR, exist_ok=True)


def _serve_frontend(fallback_filename: str = "index.html") -> HTMLResponse:
    """Serve the compiled React+TypeScript SPA when built, else fallback HTML."""
    spa_index = os.path.join(SPA_DIST_DIR, "index.html")
    if os.path.isfile(spa_index):
        with open(spa_index, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())

    legacy_path = os.path.join(FRONTEND_DIR, fallback_filename)
    with open(legacy_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# ---------------------------------------------------------------
# Create FastAPI app
# ---------------------------------------------------------------
app = FastAPI(
    title="AI-Powered KYC Platform",
    version="2.0.0",
    description="Real-time identity verification with fraud intelligence"
)

# ---------------------------------------------------------------
# Simple dashboard authentication
# For a student/demo project, a shared password is sufficient.
# In production this would be proper user accounts + JWT tokens.
# ---------------------------------------------------------------
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")

def verify_dashboard_auth(request: Request) -> bool:
    return get_reviewer_identity(request) is not None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# ---------------------------------------------------------------
# Per-session liveness checkers
# Now stored per session_id, not globally
# ---------------------------------------------------------------
liveness_checkers: dict[str, LivenessChecker] = {}

# ---------------------------------------------------------------
# Real-Time Reviewer Notification Hub
# Manages active WebSocket connections to the Reviewer Dashboard
# ---------------------------------------------------------------
class ReviewerNotificationHub:
    def __init__(self):
        self.active_reviewers: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_reviewers.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active_reviewers.discard(ws)

    async def broadcast(self, data: dict):
        for ws in list(self.active_reviewers):
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(ws)

reviewer_hub = ReviewerNotificationHub()

# Rolling buffer of recent spoof scores per session — smooths out
# frame-to-frame noise so one bad frame doesn't permanently flag
# a genuine live user
spoof_score_history: dict[str, list] = {}
SPOOF_HISTORY_SIZE = 25       # larger window = smoother average, less
                               # sensitive to a single lucky/unlucky frame
# Recalibrated from real test data:
#   - Genuine live face sessions stabilise around 0.78-0.82
#   - Phone/screen replay sessions drift down to 0.67-0.70
#     (the device bezel isn't visible in 100% of frames due to
#     natural hand movement, but it's visible often enough to
#     pull the average down over a sustained window)
# 0.72 sits cleanly between these two clusters based on observed data.
SPOOF_AVG_THRESHOLD = 0.58
SPOOF_WARMUP_FRAMES = 5

def get_liveness_checker(session_id: str) -> LivenessChecker:
    if session_id not in liveness_checkers:
        liveness_checkers[session_id] = LivenessChecker()
    return liveness_checkers[session_id]


# ---------------------------------------------------------------
# Startup: create DB tables, check Redis
# ---------------------------------------------------------------
def _runtime_diagnostics() -> dict:
    """Summarize local service and dependency readiness for /health and startup."""
    has_spa = os.path.isfile(os.path.join(SPA_DIST_DIR, "index.html"))
    has_external_llm = any(
        os.getenv(k, "").strip()
        for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "OLLAMA_BASE_URL")
    )
    return {
        "redis": check_redis_connection(),
        "database": check_database_connection(),
        "tesseract": _resolve_tesseract_cmd() is not None,
        "frontend": "react-spa" if has_spa else "legacy-html",
        "ai_mode": "external-llm" if has_external_llm else "local-grounded",
    }


@app.on_event("startup")
async def startup():
    create_tables()
    ensure_default_reviewer()
    diag = _runtime_diagnostics()
    if diag["redis"]:
        print("Redis connected")
    else:
        print("WARNING: Redis not reachable - sessions will not persist")
    if not diag["tesseract"]:
        print("WARNING: Tesseract binary not found - install Tesseract OCR or set TESSERACT_CMD in backend/.env")
    if diag["frontend"] != "react-spa":
        print("INFO: React build not found in frontend-web/dist; serving legacy frontend/. Run 'npm.cmd run build' inside frontend-web/.")


# ---------------------------------------------------------------
# ROUTE 1: GET / & React SPA Routes + Compiled /assets Serving
# ---------------------------------------------------------------
@app.get("/assets/{asset_path:path}")
async def serve_spa_asset(asset_path: str):
    assets_root = os.path.abspath(os.path.join(SPA_DIST_DIR, "assets"))
    requested = os.path.abspath(os.path.join(assets_root, asset_path))
    if not os.path.isdir(assets_root) or os.path.commonpath([assets_root, requested]) != assets_root:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if not os.path.isfile(requested):
        return JSONResponse({"error": "Asset not found"}, status_code=404)
    media_type, _ = mimetypes.guess_type(requested)
    return FileResponse(requested, media_type=media_type or "application/octet-stream")


@app.get("/", response_class=HTMLResponse)
async def root():
    return _serve_frontend("index.html")


@app.get("/verify", response_class=HTMLResponse)
@app.get("/status", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
@app.get("/register", response_class=HTMLResponse)
@app.get("/account", response_class=HTMLResponse)
@app.get("/assistant", response_class=HTMLResponse)
async def spa_frontend_routes():
    return _serve_frontend("index.html")


# ---------------------------------------------------------------
# ROUTE 2: GET /health
# ---------------------------------------------------------------
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": "2.0.0",
        **_runtime_diagnostics(),
    }


# ---------------------------------------------------------------
# ROUTE 3: POST /session/start
# Creates a new KYC session and returns its ID.
# The browser stores this ID and sends it with every request.
# ---------------------------------------------------------------
@app.post("/session/start")
async def start_session(request: Request):
    payload = {}
    try:
        raw_body = await request.body()
        if raw_body:
            parsed = json.loads(raw_body.decode("utf-8"))
            if isinstance(parsed, dict):
                payload = parsed
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    # If the caller explicitly sent a consent field, require it to be True
    if "consent_given" in payload and not bool(payload.get("consent_given")):
        return JSONResponse(
            {"error": "Biometric and camera consent is required to start verification"},
            status_code=400,
        )

    current_user = get_current_user_optional(request)
    applicant_name = (payload.get("applicant_name") or (current_user or {}).get("full_name") or "").strip() or None
    applicant_email = (payload.get("applicant_email") or (current_user or {}).get("email") or "").strip().lower() or None
    purpose = (payload.get("purpose") or "Identity Verification").strip() or "Identity Verification"
    consent_given = bool(payload.get("consent_given", False))
    consent_at = datetime.utcnow().isoformat() if consent_given else None

    session_id = create_session({
        "user_id":         (current_user or {}).get("id"),
        "applicant_name":  applicant_name,
        "applicant_email": applicant_email,
        "purpose":         purpose,
        "consent_given":   consent_given,
        "consent_at":      consent_at,
    })

    client_ip = request.client.host if request.client else None
    update_session(session_id, {
        "ip_address": client_ip,
        "user_agent": request.headers.get("user-agent", ""),
    })

    log_audit_event(session_id, "session_started", {
        "ip":      client_ip,
        "purpose": purpose,
    })

    if consent_given:
        record_consent(
            session_id=session_id,
            user_id=(current_user or {}).get("id"),
            applicant_name=applicant_name,
            applicant_email=applicant_email,
            purpose=purpose,
            consent_given=True,
            ip_address=client_ip,
        )
        log_audit_event(session_id, "consent_recorded", {
            "purpose":         purpose,
            "consent_version": "v1.0-DPDP",
        })

    return {
        "session_id":       session_id,
        "tracking_code":    f"KYC-{session_id[:8].upper()}",
        "consent_recorded": consent_given,
    }


# ---------------------------------------------------------------
# ROUTE 4: POST /session/reset
# Resets the session for a retry.
# ---------------------------------------------------------------
@app.post("/session/reset")
async def reset_session(data: dict):
    session_id = data.get("session_id")
    if not session_id:
        return JSONResponse({"error": "session_id required"}, status_code=400)

    delete_session(session_id)
    if session_id in liveness_checkers:
        del liveness_checkers[session_id]

    new_session_id = create_session()
    return {"session_id": new_session_id, "message": "Session reset"}


# ---------------------------------------------------------------
# ROUTE 5: POST /process-frame
# Receives a camera frame, runs face detection + liveness.
# Now takes session_id as a form field alongside the frame.
# ---------------------------------------------------------------
@app.post("/process-frame")
async def process_frame(
    frame: UploadFile = File(...),
    session_id: str = ""
):
    # Validate session
    session = get_session(session_id)
    if session is None:
        return JSONResponse(
            {"error": "Session not found or expired. Please refresh."},
            status_code=404
        )

    # Read image bytes
    image_bytes = await frame.read()

    # Save for debugging
    save_path = os.path.join(UPLOADS_DIR, f"frame_{session_id[:8]}.jpg")
    with open(save_path, "wb") as f:
        f.write(image_bytes)

    # Face detection
    face_result = detect_face(image_bytes)

    if not face_result["face_found"]:
        update_session(session_id, {"face_found": False})
        return {
            "face_found": False,
            "landmarks": [],
            "liveness": {
                "liveness_passed": False,
                "message": "No face detected — centre your face in the frame"
            }
        }

    # Eye landmark extraction for EAR
    landmarks = face_result["landmarks"]
    ear_left  = [landmarks[i] for i in LEFT_EYE_EAR_POINTS]
    ear_right = [landmarks[i] for i in RIGHT_EYE_EAR_POINTS]

    # Per-session liveness checker
    checker = get_liveness_checker(session_id)
    liveness_result = checker.process_frame(landmarks, ear_left, ear_right)

    # Log first face detection
    if not session.get("face_found"):
        log_audit_event(session_id, "face_detected")

    # Log liveness pass
    if liveness_result["liveness_passed"] and not session.get("liveness_passed"):
        log_audit_event(session_id, "liveness_passed", {
            "blinks": liveness_result["blink_count"]
        })

    # Anti-spoofing check
    np_arr = np.frombuffer(image_bytes, np.uint8)
    cv2_image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    face_crop = extract_face_region(cv2_image, landmarks)
    spoof_result = analyze_spoof(face_crop, full_frame=cv2_image)

    # Once spoofed, stay flagged for the rest of the session —
    # don't let a later "clean" frame erase an earlier spoof flag
    if session_id not in spoof_score_history:
        spoof_score_history[session_id] = []
    spoof_score_history[session_id].append(spoof_result["spoof_score"])
    if len(spoof_score_history[session_id]) > SPOOF_HISTORY_SIZE:
        spoof_score_history[session_id].pop(0)

    history_len = len(spoof_score_history[session_id])
    avg_spoof_score = sum(spoof_score_history[session_id]) / history_len

    already_flagged = session.get("spoof_detected", False)
    spoof_this_frame = (history_len >= SPOOF_WARMUP_FRAMES) and (avg_spoof_score < SPOOF_AVG_THRESHOLD)

    # If natural blink liveness passed and score is healthy (>= 0.60), clear false warmup flag
    if liveness_result["liveness_passed"] and avg_spoof_score >= 0.60:
        spoof_detected = False
    elif history_len >= SPOOF_WARMUP_FRAMES:
        spoof_detected = already_flagged or spoof_this_frame
    else:
        spoof_detected = False

    update_session(session_id, {
        "face_found": True,
        "liveness_passed": liveness_result["liveness_passed"],
        "liveness_blinks": liveness_result["blink_count"],
        "spoof_detected": spoof_detected,
        "spoof_score": round(avg_spoof_score, 3),
    })

    return {
        "face_found": True,
        "landmarks":  landmarks,
        "width":      face_result["width"],
        "height":     face_result["height"],
        "liveness":   liveness_result,
        "spoof":      spoof_result,
    }


# ---------------------------------------------------------------
# ROUTE 6: POST /scan-id
# ---------------------------------------------------------------
@app.post("/scan-id")
async def scan_id(
    frame: UploadFile = File(...),
    session_id: str = Form(...)
):
    session = get_session(session_id)
    if session is None:
        return JSONResponse({"error": "Session expired"}, status_code=404)

    image_bytes = await frame.read()

    # If a PDF ID card was uploaded, convert page 1 to PNG bytes before
    # encrypting so face matching and the vault viewer always receive an image.
    vault_id_bytes = image_bytes
    if is_pdf(image_bytes):
        converted = pdf_to_image_bytes(image_bytes)
        if converted:
            vault_id_bytes = converted

    # Store ID card encrypted at rest inside uploads/vault/ instead of plaintext .jpg
    encrypt_evidence(session_id, "id", vault_id_bytes)

    result = scan_document(image_bytes)

    if result["success"]:
        update_session(session_id, {
            "id_scanned": True,
            "id_fields":  result.get("fields", {}),
        })
        log_audit_event(session_id, "id_scanned", {
            "id_type": result.get("fields", {}).get("id_type")
        })

    return result


# ---------------------------------------------------------------
# ROUTE 7: POST /match-face
# ---------------------------------------------------------------
@app.post("/match-face")
async def match_face(
    frame: UploadFile = File(...),
    session_id: str = Form(...)
):
    session = get_session(session_id)
    if session is None:
        return JSONResponse({"error": "Session expired"}, status_code=404)

    selfie_bytes = await frame.read()

    # Encrypt live selfie at rest inside uploads/vault/ instead of plaintext .jpg
    encrypt_evidence(session_id, "selfie", selfie_bytes)

    # Decrypt ID image in memory from the vault; fall back to legacy plaintext
    # uploads/id_<sid8>.jpg only if the session pre-dates vault encryption.
    id_bytes = decrypt_evidence(session_id, "id")
    legacy_id_path = os.path.join(UPLOADS_DIR, f"id_{session_id[:8]}.jpg")

    match_result = match_faces(
        selfie_bytes,
        id_image_path=legacy_id_path if id_bytes is None else None,
        id_bytes=id_bytes,
    )

    confidence = match_result.get("confidence", 0.0) or 0.0

    update_session(session_id, {
        "face_matched":     match_result["matched"],
        "match_confidence": confidence,
        "match_distance":   match_result.get("distance", 0.0) or 0.0,
    })

    log_audit_event(session_id, "face_match_completed", {
        "matched":    match_result["matched"],
        "confidence": confidence,
    })

    # Get fresh session state
    session = get_session(session_id)

    # Run Unified Fraud Risk Engine (combines face, spoof, document, and history risks)
    fraud_result = compute_fraud_risk(session)

    log_audit_event(session_id, "fraud_risk_assessed", {
        "fraud_score":  fraud_result["fraud_score"],
        "risk_level":   fraud_result["risk_level"],
        "breakdown":    fraud_result["breakdown"],
        "risk_factors": fraud_result["risk_factors"],
    })

    # Run decision engine — includes spoof detection & unified fraud risk score
    verdict = make_decision(
        face_found       = session["face_found"],
        liveness_passed  = session["liveness_passed"],
        id_scanned       = session["id_scanned"],
        face_matched     = session["face_matched"],
        match_confidence = session["match_confidence"],
        id_fields        = session["id_fields"],
        spoof_detected   = session.get("spoof_detected", False),
        fraud_result     = fraud_result,
        match_distance   = match_result.get("distance"),
    )

    # Save verdict and unified fraud risk score to session
    update_session(session_id, {
        "fraud_score":     fraud_result["fraud_score"],
        "verdict":         verdict["verdict"],
        "verdict_message": verdict["message"],
        "verdict_reasons": verdict.get("verdict_reasons", []),
        "status":          "completed",
    })

    log_audit_event(session_id, "verdict_reached", {
        "verdict":     verdict["verdict"],
        "fraud_score": fraud_result["fraud_score"],
    })

    # Save completed session to PostgreSQL
    final_session = get_session(session_id)
    if final_session:
        save_session_to_db(final_session)

    # Real-time Reviewer Alert Notification
    try:
        if verdict.get("verdict") == "REVIEW":
            await reviewer_hub.broadcast({
                "type": "NEW_REVIEW_REQUIRED",
                "session": {
                    "id": session_id,
                    "tracking_code": (final_session or {}).get("tracking_code") or session_id[:8],
                    "applicant_name": (final_session or {}).get("applicant_name") or "Applicant",
                    "verdict": verdict.get("verdict"),
                    "verdict_message": verdict.get("message"),
                    "match_confidence": confidence,
                    "fraud_score": fraud_result.get("fraud_score", 0.0),
                    "created_at": str((final_session or {}).get("created_at") or datetime.utcnow()),
                    "reasons": verdict.get("verdict_reasons", []),
                }
            })
        else:
            await reviewer_hub.broadcast({
                "type": "SESSION_COMPLETED",
                "session_id": session_id,
                "applicant_name": (final_session or {}).get("applicant_name") or "Applicant",
                "verdict": verdict.get("verdict"),
                "tracking_code": (final_session or {}).get("tracking_code") or session_id[:8],
            })
    except Exception as e:
        print(f"[ReviewerHub] Broadcast alert error: {e}")

    # Clean up liveness checker
    if session_id in liveness_checkers:
        del liveness_checkers[session_id]

    return {
        "match":   match_result,
        "fraud":   fraud_result,
        "verdict": verdict,
    }


# ---------------------------------------------------------------
# ROUTE 8: GET /sessions
# Returns all sessions for the agent dashboard.
# ---------------------------------------------------------------
@app.get("/sessions")
async def list_sessions():
    sessions = get_all_sessions()
    return {"sessions": sessions, "count": len(sessions)}


# ---------------------------------------------------------------
# ROUTE 9: GET /sessions/{session_id}
# Returns one session's full data.
# ---------------------------------------------------------------
@app.get("/sessions/{session_id}")
async def get_session_detail(session_id: str):
    session = get_session(session_id)
    if session is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return session

# ---------------------------------------------------------------
# ROUTE: GET /dashboard
# Serves the dashboard HTML page (login + session list UI).
# ---------------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/reviewer", response_class=HTMLResponse)
async def dashboard_page():
    return _serve_frontend("dashboard.html")


# ---------------------------------------------------------------
# ROUTE: POST /api/dashboard/login
# Supports legacy dashboard passcode OR registered reviewer email+password.
# ---------------------------------------------------------------
@app.post("/api/dashboard/login")
async def dashboard_login(data: dict):
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "")

    if email:
        user = get_user_by_email(email)
        if not user or user.role not in ("reviewer", "admin") or not verify_password(password, user.password_hash):
            return JSONResponse({"success": False, "error": "Invalid reviewer credentials"}, status_code=401)
        user_dict = user_to_dict(user)
        return {"success": True, "token": create_access_token(user_dict), "user": user_dict}

    if password == DASHBOARD_PASSWORD:
        return {"success": True}
    return JSONResponse({"success": False, "error": "Incorrect password"}, status_code=401)


# ---------------------------------------------------------------
# ROUTE: GET /api/dashboard/stats
# Returns summary counts for the dashboard header.
# ---------------------------------------------------------------
@app.get("/api/dashboard/stats")
async def dashboard_stats(request: Request):
    if not verify_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return get_dashboard_stats()


# ---------------------------------------------------------------
# ROUTE: GET /api/dashboard/analytics
# Returns detailed operational analytics (spoof rate, avg duration, etc.).
# ---------------------------------------------------------------
@app.get("/api/dashboard/analytics")
async def dashboard_analytics(request: Request):
    if not verify_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return get_dashboard_analytics()


# ---------------------------------------------------------------
# ROUTE: GET /api/dashboard/sessions
# Returns the list of sessions, optionally filtered by verdict.
# Example: /api/dashboard/sessions?verdict=REVIEW
# ---------------------------------------------------------------
@app.get("/api/dashboard/sessions")
async def dashboard_sessions(request: Request, verdict: str = "ALL"):
    if not verify_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    sessions = get_all_sessions_from_db(verdict_filter=verdict)
    return {"sessions": [session_to_dict(s) for s in sessions]}


# ---------------------------------------------------------------
# ROUTE: GET /api/dashboard/sessions/{session_id}
# Returns full detail for one session, including its audit trail.
# ---------------------------------------------------------------
@app.get("/api/dashboard/sessions/{session_id}")
async def dashboard_session_detail(session_id: str, request: Request):
    if not verify_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    session = get_session_from_db(session_id)
    if session is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    audit_trail = get_audit_trail(session_id)

    return {
        "session":     session_to_dict(session),
        "audit_trail": [audit_event_to_dict(e) for e in audit_trail],
        "vault": {
            "has_id":     evidence_exists(session_id, "id"),
            "has_selfie": evidence_exists(session_id, "selfie"),
        },
    }


# ---------------------------------------------------------------
# ROUTE: POST /api/dashboard/sessions/{session_id}/review
# Agent approves/rejects/escalates a session.
# Body: { "action": "approved" | "rejected" | "escalated",
#          "reviewer": "agent name", "note": "optional note" }
# ---------------------------------------------------------------
@app.post("/api/dashboard/sessions/{session_id}/review")
async def dashboard_review_session(session_id: str, data: dict, request: Request):
    if not verify_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    reviewer_identity = get_reviewer_identity(request) or "Agent"
    action   = data.get("action")
    reviewer = (data.get("reviewer") or "").strip() or reviewer_identity
    note     = data.get("note", "")

    if action not in ("approved", "rejected", "escalated"):
        return JSONResponse({"error": "Invalid action"}, status_code=400)

    success = update_review(session_id, action, reviewer, note)
    if not success:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    log_audit_event(session_id, "agent_review", {
        "action": action, "reviewer": reviewer, "note": note
    }, actor=reviewer)

    # Broadcast review resolution event to all active reviewer dashboards
    try:
        await reviewer_hub.broadcast({
            "type": "SESSION_REVIEWED",
            "session_id": session_id,
            "action": action,
            "reviewer": reviewer
        })
    except Exception as e:
        print(f"[ReviewerHub] Broadcast review resolution error: {e}")

    return {"success": True, "message": f"Session {action} by {reviewer}"}


# ---------------------------------------------------------------
# ROUTE: GET /api/dashboard/sessions/{session_id}/evidence/{doc_kind}
# Decrypts ID or selfie evidence from the vault on demand for an
# authenticated agent, and records an 'evidence_accessed' audit event.
# ---------------------------------------------------------------
@app.get("/api/dashboard/sessions/{session_id}/evidence/{doc_kind}")
async def dashboard_session_evidence(session_id: str, doc_kind: str, request: Request, masked: bool = True):
    if not verify_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if doc_kind not in ("id", "selfie"):
        return JSONResponse({"error": "Invalid evidence type"}, status_code=400)

    session = get_session_from_db(session_id)
    if session is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    raw_bytes = decrypt_evidence(session_id, doc_kind)
    if raw_bytes is None:
        return JSONResponse(
            {"error": f"Encrypted {doc_kind} evidence not found in vault"},
            status_code=404,
        )

    out_bytes = raw_bytes
    aadhaar_redacted = False
    id_fields = session.id_fields or {}
    if doc_kind == "id" and masked and (id_fields.get("id_type") or "").lower() == "aadhaar":
        last4_hint = (id_fields.get("id_number") or "")[-4:]
        out_bytes, aadhaar_redacted = redact_aadhaar_digits(raw_bytes, last4_hint=last4_hint)

    # Audit trail must record every time a human agent decrypts PII/biometrics
    log_audit_event(session_id, "evidence_accessed", {
        "doc_kind": doc_kind,
        "masked": bool(masked),
        "aadhaar_redacted": aadhaar_redacted,
    })

    return Response(
        content=out_bytes,
        media_type=get_evidence_media_type(out_bytes),
        headers={
            "Cache-Control": "no-store",
            "X-Aadhaar-Redacted": "true" if aadhaar_redacted else "false",
        },
    )


# ---------------------------------------------------------------
# ROUTE: GET /api/dashboard/vault/stats
# Returns encrypted storage counts and how many files exceed retention.
# ---------------------------------------------------------------
@app.get("/api/dashboard/vault/stats")
async def dashboard_vault_stats(request: Request, retention_days: int = 30):
    if not verify_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if retention_days < 0:
        return JSONResponse({"error": "retention_days must be >= 0"}, status_code=400)

    return get_vault_stats(retention_days=retention_days)


# ---------------------------------------------------------------
# ROUTE: POST /api/dashboard/vault/purge
# Enforces data-minimization by deleting encrypted blobs older than
# retention_days (default 30).
# ---------------------------------------------------------------
@app.post("/api/dashboard/vault/purge")
async def dashboard_vault_purge(request: Request, retention_days: int = 30):
    if not verify_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    days = retention_days
    try:
        raw_body = await request.body()
        if raw_body:
            payload = json.loads(raw_body.decode("utf-8"))
            if isinstance(payload, dict) and "retention_days" in payload:
                days = int(payload["retention_days"])
    except Exception:
        return JSONResponse({"error": "Invalid retention_days"}, status_code=400)

    if days < 0:
        return JSONResponse({"error": "retention_days must be >= 0"}, status_code=400)

    deleted_count = purge_expired_evidence(retention_days=days)
    return {
        "success":        True,
        "deleted_count":  deleted_count,
        "retention_days": days,
        "stats":          get_vault_stats(retention_days=days),
    }


# ---------------------------------------------------------------
# AUTH & USER ACCOUNT ROUTES (/api/auth/*)
# ---------------------------------------------------------------
@app.post("/api/auth/register")
async def auth_register(data: dict):
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip() or None
    password = data.get("password") or ""

    if not full_name or not email or "@" not in email:
        return JSONResponse({"error": "Valid full name and email are required"}, status_code=400)

    if len(password) < 6:
        return JSONResponse({"error": "Password must be at least 6 characters"}, status_code=400)

    if get_user_by_email(email):
        return JSONResponse({"error": "An account with this email already exists"}, status_code=409)

    user = create_user_record(
        full_name=full_name,
        email=email,
        password_hash=hash_password(password),
        phone=phone,
        role="applicant",
    )
    if user is None:
        return JSONResponse({"error": "Could not create account"}, status_code=500)

    user_dict = user_to_dict(user)
    return {"token": create_access_token(user_dict), "user": user_dict}


@app.post("/api/auth/login")
async def auth_login(data: dict):
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = get_user_by_email(email)
    if not user or not verify_password(password, user.password_hash):
        return JSONResponse({"error": "Invalid email or password"}, status_code=401)

    user_dict = user_to_dict(user)
    return {"token": create_access_token(user_dict), "user": user_dict}


@app.get("/api/auth/me")
async def auth_me(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return {"user": user}


@app.get("/api/auth/sessions")
async def auth_my_sessions(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    rows = get_sessions_for_user(user_id=user["id"], email=user["email"])
    return {"sessions": [session_to_dict(s) for s in rows]}


# ---------------------------------------------------------------
# APPLICANT STATUS TRACKER & DPDP RIGHT-TO-ERASURE
# ---------------------------------------------------------------
def _mask_id_number(raw_num: str) -> str:
    if not raw_num:
        return ""
    s = str(raw_num).strip()
    if len(s) <= 4:
        return "*" * len(s)
    return ("*" * (len(s) - 4)) + s[-4:]


def _build_public_receipt(s_dict: dict) -> dict:
    id_fields = s_dict.get("id_fields") or {}
    sid = s_dict.get("id") or s_dict.get("session_id")
    return {
        "session_id":       sid,
        "tracking_code":    s_dict.get("tracking_code") or f"KYC-{sid[:8].upper()}",
        "applicant_name":   s_dict.get("applicant_name"),
        "purpose":          s_dict.get("purpose"),
        "consent_given":    bool(s_dict.get("consent_given")),
        "consent_at":       s_dict.get("consent_at"),
        "erased_at":        s_dict.get("erased_at"),
        "created_at":       s_dict.get("created_at"),
        "completed_at":     s_dict.get("completed_at"),
        "verdict":          s_dict.get("verdict"),
        "verdict_message":  s_dict.get("verdict_message"),
        "verdict_reasons":  s_dict.get("verdict_reasons") or [],
        "match_confidence": s_dict.get("match_confidence"),
        "fraud_score":      s_dict.get("fraud_score"),
        "liveness_passed":  bool(s_dict.get("liveness_passed")),
        "liveness_blinks":  s_dict.get("liveness_blinks") or 0,
        "spoof_detected":   bool(s_dict.get("spoof_detected")),
        "id_type":          id_fields.get("id_type"),
        "id_number_masked": _mask_id_number(id_fields.get("id_number")),
        "id_valid":         id_fields.get("id_valid"),
        "validation_note":  id_fields.get("validation_note"),
        "reviewed_by":      s_dict.get("reviewed_by"),
        "review_action":    s_dict.get("review_action"),
        "review_note":      s_dict.get("review_note"),
        "reviewed_at":      s_dict.get("reviewed_at"),
        "vault_present":    evidence_exists(sid, "id") or evidence_exists(sid, "selfie"),
    }


@app.get("/api/status/{ref}")
async def get_public_status(ref: str):
    row = lookup_session_by_ref(ref)
    if row is not None:
        return {"found": True, "receipt": _build_public_receipt(session_to_dict(row))}

    # Also check live in-progress Redis sessions
    live = get_session(ref)
    if live is not None:
        return {"found": True, "receipt": _build_public_receipt(live)}

    return JSONResponse({"found": False, "error": "No verification session found for this reference code"}, status_code=404)


@app.post("/api/sessions/{session_id}/erase")
async def erase_applicant_data(session_id: str, request: Request):
    row = get_session_from_db(session_id)
    if row is None:
        return JSONResponse({"error": "Completed session not found in database"}, status_code=404)

    current_user = get_current_user_optional(request)
    reviewer_id = get_reviewer_identity(request)

    body_email = ""
    try:
        raw_body = await request.body()
        if raw_body:
            parsed = json.loads(raw_body.decode("utf-8"))
            if isinstance(parsed, dict):
                body_email = (parsed.get("email") or "").strip().lower()
    except Exception:
        body_email = ""

    # Verify authorization: reviewer, owning logged-in user, matching session email,
    # or caller holds the full 36-char UUID on an anonymous session
    authorized = False
    actor = "applicant"
    if reviewer_id:
        authorized = True
        actor = reviewer_id
    elif current_user and (row.user_id == current_user["id"] or (row.applicant_email and row.applicant_email == current_user["email"])):
        authorized = True
        actor = current_user["email"]
    elif row.applicant_email and row.applicant_email != "[REDACTED]" and body_email == row.applicant_email:
        authorized = True
        actor = body_email
    elif not row.applicant_email and len(session_id) >= 32:
        authorized = True

    if not authorized:
        return JSONResponse(
            {"error": "Please sign in or confirm the applicant email used during verification to erase data"},
            status_code=403,
        )

    deleted_blobs = delete_session_evidence(session_id)
    ok = erase_session_pii(session_id)
    if not ok:
        return JSONResponse({"error": "Failed to redact database record"}, status_code=500)

    log_audit_event(session_id, "pii_erased", {"deleted_vault_blobs": deleted_blobs}, actor=actor)
    return {
        "success": True,
        "session_id": session_id,
        "deleted_blobs": deleted_blobs,
        "message": "Encrypted evidence deleted and personal fields redacted.",
    }


# ---------------------------------------------------------------
# HYBRID AI & RAG ENDPOINTS (/api/ai/* and reviewer brief)
# ---------------------------------------------------------------
def _resolve_any_session_dict(session_ref: str) -> dict | None:
    if not session_ref:
        return None
    live = get_session(session_ref)
    if live:
        return live
    row = lookup_session_by_ref(session_ref)
    if row:
        return session_to_dict(row)
    return None


@app.post("/api/ai/chat")
async def ai_support_chat(data: dict):
    question = (data.get("question") or "").strip()
    session_ref = (data.get("session_id") or "").strip()
    session_ctx = _resolve_any_session_dict(session_ref) if session_ref else None
    return chat_assistant(question, session_context=session_ctx)


@app.get("/api/ai/session/{session_id}/explain")
async def ai_explain_session(session_id: str):
    session_dict = _resolve_any_session_dict(session_id)
    if session_dict is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return explain_session_for_user(session_dict)


@app.get("/api/dashboard/sessions/{session_id}/ai-summary")
async def ai_reviewer_summary(session_id: str, request: Request):
    if not verify_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    row = get_session_from_db(session_id)
    if row is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    trail = [audit_event_to_dict(e) for e in get_audit_trail(session_id)]
    return summarize_session_for_reviewer(session_to_dict(row), trail)


# ---------------------------------------------------------------
# COMPLIANCE REPORT EXPORT (JSON / CSV)
# ---------------------------------------------------------------
@app.get("/api/dashboard/compliance/export")
async def dashboard_compliance_export(request: Request, format: str = "csv", verdict: str = "ALL"):
    if not verify_dashboard_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    sessions = [session_to_dict(s) for s in get_all_sessions_from_db(verdict_filter=verdict, limit=1000)]

    if format.lower() == "json":
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "filter": verdict,
            "count": len(sessions),
            "stats": get_dashboard_stats(),
            "vault": get_vault_stats(),
            "sessions": sessions,
        }
        return Response(
            content=json.dumps(report, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="pehchaanai_compliance_report.json"'},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Tracking Code", "Session ID", "Applicant Name", "Purpose", "Consent Given",
        "Verdict", "Match Confidence %", "Fraud Score", "Spoof Detected",
        "ID Type", "ID Valid", "Review Action", "Reviewed By", "Created At", "Erased At"
    ])
    for s in sessions:
        idf = s.get("id_fields") or {}
        writer.writerow([
            s.get("tracking_code"),
            s.get("id"),
            s.get("applicant_name") or "",
            s.get("purpose") or "",
            s.get("consent_given"),
            s.get("verdict") or "INCOMPLETE",
            s.get("match_confidence") or 0,
            s.get("fraud_score") or 0,
            s.get("spoof_detected"),
            idf.get("id_type") or "",
            idf.get("id_valid"),
            s.get("review_action") or "",
            s.get("reviewed_by") or "",
            s.get("created_at") or "",
            s.get("erased_at") or "",
        ])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="pehchaanai_compliance_report.csv"'},
    )

# ---------------------------------------------------------------
# WEBSOCKET: /ws/{session_id}
# Real-time frame streaming over WebSocket.
#
# HOW WEBSOCKETS WORK:
# Normal HTTP: browser sends request → server responds → connection closes
# WebSocket:   browser opens connection → stays open → both sides can
#              send messages anytime → much lower overhead for real-time
#
# Frame format sent by browser (JSON):
# {
#   "type": "frame",
#   "data": "<base64 encoded JPEG>"
# }
#
# Server responds with JSON:
# {
#   "face_found": true,
#   "landmarks": [...],
#   "liveness": {...}
# }
# ---------------------------------------------------------------
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()

    # Validate session
    session = get_session(session_id)
    if session is None:
        await websocket.send_json({"error": "Session not found"})
        await websocket.close()
        return

    checker = get_liveness_checker(session_id)

    try:
        while True:
            # Receive message from browser
            message = await websocket.receive_text()
            data    = json.loads(message)

            if data.get("type") != "frame":
                continue

            # Decode base64 image sent by browser
            # Browser sends: btoa(binaryString) of JPEG bytes
            image_b64   = data["data"].split(",")[-1]  # remove "data:image/jpeg;base64,"
            image_bytes = base64.b64decode(image_b64)

            # Run face detection
            face_result = detect_face(image_bytes)

            if not face_result["face_found"]:
                await websocket.send_json({
                    "face_found": False,
                    "landmarks":  [],
                    "liveness":   {
                        "liveness_passed": False,
                        "message": "No face detected"
                    }
                })
                continue

            # Eye points for EAR
            landmarks = face_result["landmarks"]
            ear_left  = [landmarks[i] for i in LEFT_EYE_EAR_POINTS]
            ear_right = [landmarks[i] for i in RIGHT_EYE_EAR_POINTS]

            # Liveness check (blink detection)
            liveness_result = checker.process_frame(
                landmarks, ear_left, ear_right
            )

                        # Anti-spoofing check — only run once liveness has started
            # to avoid wasting CPU on every single frame
            np_arr    = np.frombuffer(image_bytes, np.uint8)
            cv2_image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            face_crop = extract_face_region(cv2_image, landmarks)
            spoof_result = analyze_spoof(face_crop, full_frame=cv2_image)

            # Maintain a rolling window of this session's recent spoof
            # scores. Using an AVERAGE over multiple frames instead of
            # any single frame makes this robust to normal webcam noise
            # (autofocus hunting, brief motion blur) while still catching
            # SUSTAINED spoofing patterns.
            if session_id not in spoof_score_history:
                spoof_score_history[session_id] = []

            spoof_score_history[session_id].append(spoof_result["spoof_score"])
            if len(spoof_score_history[session_id]) > SPOOF_HISTORY_SIZE:
                spoof_score_history[session_id].pop(0)

            avg_spoof_score = sum(spoof_score_history[session_id]) / len(spoof_score_history[session_id])
            spoof_detected  = avg_spoof_score < SPOOF_AVG_THRESHOLD

            # DEBUG: print both the instant and the rolling average score
            print(f"Spoof check -- texture: {spoof_result['texture_score']}, "
                  f"frequency: {spoof_result['frequency_score']}, "
                  f"sharpness: {spoof_result['sharpness_score']}, "
                  f"bezel: {spoof_result['bezel_score']}, "
                  f"frame_score: {spoof_result['spoof_score']}, "
                  f"avg_score: {round(avg_spoof_score, 3)}, "
                  f"flagged: {spoof_detected}")

            # Check current session state for audit logging over WebSocket
            current_session = get_session(session_id) or {}

            # Log audit event for first face detected via WebSocket
            if not current_session.get("face_found"):
                log_audit_event(session_id, "face_detected")

            # Log audit event when liveness passes via WebSocket
            if liveness_result["liveness_passed"] and not current_session.get("liveness_passed"):
                log_audit_event(session_id, "liveness_passed", {
                    "blinks": liveness_result["blink_count"]
                })

            already_flagged = current_session.get("spoof_detected", False)
            history_len = len(spoof_score_history[session_id])
            spoof_this_frame = (history_len >= SPOOF_WARMUP_FRAMES) and (avg_spoof_score < SPOOF_AVG_THRESHOLD)

            # If user passed natural blink liveness and average score is healthy (>= 0.60), clear false warmup flags
            if liveness_result["liveness_passed"] and avg_spoof_score >= 0.60:
                spoof_detected = False
            elif history_len >= SPOOF_WARMUP_FRAMES:
                spoof_detected = already_flagged or spoof_this_frame
            else:
                spoof_detected = False

            if spoof_detected and not already_flagged:
                log_audit_event(session_id, "spoof_detected", {
                    "spoof_score": round(avg_spoof_score, 3)
                })

            update_session(session_id, {
                "face_found":      True,
                "liveness_passed": liveness_result["liveness_passed"],
                "liveness_blinks": liveness_result["blink_count"],
                "spoof_detected":  spoof_detected,
                "spoof_score":     round(avg_spoof_score, 3),
            })

            # Send result back to browser
            await websocket.send_json({
                "face_found": True,
                "landmarks":  landmarks,
                "width":      face_result["width"],
                "height":     face_result["height"],
                "liveness":   liveness_result,
                "spoof":      spoof_result,
            })

    except WebSocketDisconnect:
        # Browser disconnected — clean up
        if session_id in liveness_checkers:
            del liveness_checkers[session_id]
        if session_id in spoof_score_history:
            del spoof_score_history[session_id]
        print(f"WebSocket disconnected: {session_id[:8]}")


# ---------------------------------------------------------------
# ROUTE: WebSocket /ws/reviewer
# Real-time bidirectional push channel for the Compliance Reviewer Portal.
# Pushes instant alerts when a verification requires human review.
# ---------------------------------------------------------------
@app.websocket("/ws/reviewer")
async def reviewer_websocket_endpoint(websocket: WebSocket):
    await reviewer_hub.connect(websocket)
    try:
        # Confirm connection to client
        await websocket.send_json({"type": "CONNECTED", "message": "Reviewer Notification Channel Active"})
        while True:
            # Keep connection alive, listen for ping/heartbeat
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        reviewer_hub.disconnect(websocket)
    except Exception:
        reviewer_hub.disconnect(websocket)


# ---------------------------------------------------------------
# Run
# ---------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        app_dir=BASE_DIR,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=True,
        reload_dirs=[BASE_DIR],
    )