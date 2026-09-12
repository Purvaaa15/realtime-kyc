# main.py
# Entry point for the AI-Powered KYC Platform.
# Now supports:
#   - Multi-user Redis sessions (each user gets their own UUID)
#   - WebSocket real-time frame streaming
#   - PostgreSQL audit logging
#   - Explainable verdicts with reasons

from spoof_detector import analyze_spoof, extract_face_region
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, Depends, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
import uvicorn
import os
import json
import base64
import numpy as np
import cv2
from dotenv import load_dotenv

# Our custom modules
from face_detector import detect_face, LEFT_EYE_EAR_POINTS, RIGHT_EYE_EAR_POINTS
from liveness import LivenessChecker
from ocr import scan_document
from face_match import match_faces
from decision import make_decision
from session_manager import (
    create_session, get_session, update_session,
    delete_session, get_all_sessions, check_redis_connection
)
from database import get_db, save_session_to_db, log_audit_event, create_tables

load_dotenv()

# ---------------------------------------------------------------
# Absolute paths
# ---------------------------------------------------------------
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR     = os.path.join(BASE_DIR, "..")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
UPLOADS_DIR  = os.path.join(ROOT_DIR, "uploads")

os.makedirs(UPLOADS_DIR, exist_ok=True)

# ---------------------------------------------------------------
# Create FastAPI app
# ---------------------------------------------------------------
app = FastAPI(
    title="AI-Powered KYC Platform",
    version="2.0.0",
    description="Real-time identity verification with fraud intelligence"
)

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
SPOOF_AVG_THRESHOLD = 0.72

def get_liveness_checker(session_id: str) -> LivenessChecker:
    if session_id not in liveness_checkers:
        liveness_checkers[session_id] = LivenessChecker()
    return liveness_checkers[session_id]


# ---------------------------------------------------------------
# Startup: create DB tables, check Redis
# ---------------------------------------------------------------
@app.on_event("startup")
async def startup():
    create_tables()
    if check_redis_connection():
        print("Redis connected")
    else:
        print("WARNING: Redis not reachable — sessions will not persist")


# ---------------------------------------------------------------
# ROUTE 1: GET /
# ---------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------
# ROUTE 2: GET /health
# ---------------------------------------------------------------
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": "2.0.0",
        "redis": check_redis_connection(),
    }


# ---------------------------------------------------------------
# ROUTE 3: POST /session/start
# Creates a new KYC session and returns its ID.
# The browser stores this ID and sends it with every request.
# ---------------------------------------------------------------
@app.post("/session/start")
async def start_session(request: Request):
    session_id = create_session()

    # Log device info into session
    update_session(session_id, {
        "ip_address": request.client.host,
        "user_agent": request.headers.get("user-agent", ""),
    })

    log_audit_event(session_id, "session_started", {
        "ip": request.client.host
    })

    return {"session_id": session_id}


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
    already_flagged = session.get("spoof_detected", False)
    spoof_this_frame = not spoof_result["is_live"]
    spoof_detected = already_flagged or spoof_this_frame

    update_session(session_id, {
        "face_found": True,
        "liveness_passed": liveness_result["liveness_passed"],
        "liveness_blinks": liveness_result["blink_count"],
        "spoof_detected": spoof_detected,
        "spoof_score": spoof_result["spoof_score"],
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

    # Save ID frame with session prefix
    id_path = os.path.join(UPLOADS_DIR, f"id_{session_id[:8]}.jpg")
    with open(id_path, "wb") as f:
        f.write(image_bytes)

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

    # Save selfie
    selfie_path = os.path.join(UPLOADS_DIR, f"selfie_{session_id[:8]}.jpg")
    with open(selfie_path, "wb") as f:
        f.write(selfie_bytes)

    # Load saved ID frame
    id_path = os.path.join(UPLOADS_DIR, f"id_{session_id[:8]}.jpg")

    match_result = match_faces(selfie_bytes, id_path)

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

    # Run decision engine — now includes spoof detection result
    verdict = make_decision(
        face_found       = session["face_found"],
        liveness_passed  = session["liveness_passed"],
        id_scanned       = session["id_scanned"],
        face_matched     = session["face_matched"],
        match_confidence = session["match_confidence"],
        id_fields        = session["id_fields"],
        spoof_detected   = session.get("spoof_detected", False),
    )

    # Save verdict to session
    update_session(session_id, {
        "verdict":         verdict["verdict"],
        "verdict_message": verdict["message"],
        "status":          "completed",
    })

    log_audit_event(session_id, "verdict_reached", {
        "verdict": verdict["verdict"]
    })

    # Save completed session to PostgreSQL
    final_session = get_session(session_id)
    if final_session:
        save_session_to_db(final_session)

    # Clean up liveness checker
    if session_id in liveness_checkers:
        del liveness_checkers[session_id]

    return {
        "match":   match_result,
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

            update_session(session_id, {
                "face_found":      True,
                "liveness_passed": liveness_result["liveness_passed"],
                "liveness_blinks": liveness_result["blink_count"],
                "spoof_detected":  spoof_detected,
                "spoof_score":     avg_spoof_score,
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
# Run
# ---------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=True
    )