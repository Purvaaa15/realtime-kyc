# ai_agent.py
# Hybrid Agentic AI & Grounded RAG Layer for PehchaanAI (FF180 Objective 3).
#
# WHAT THIS MODULE PROVIDES:
#   1. PehchaanAI RAG Assistant (`chat_assistant`): answers applicant, reviewer,
#      and project-architecture questions using specific fact-level retrieval from
#      verified codebase documentation (+ live PostgreSQL/Redis session context).
#   2. Plain-English User Explainer (`explain_session_for_user`): gives clear reasons
#      and actionable next steps for PASS / REVIEW / FAIL / INCOMPLETE outcomes.
#   3. Reviewer AI Brief (`summarize_session_for_reviewer`): generates a structured
#      triage brief for human compliance reviewers inspecting escalated cases.
#
# HOW THE HYBRID DESIGN WORKS:
#   - Phrase + normalized-token Retrieval-Augmented Generation (RAG) selects the most
#     relevant knowledge cards and ranks individual verified facts to match the
#     specific question asked (avoiding generic stopword collisions).
#   - If you configure `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, or
#     `OLLAMA_BASE_URL` in backend/.env, it calls that LLM with the retrieved context.
#   - If NO external API key is set (or the network is offline), it synthesizes concise,
#     question-focused answers deterministically so every feature works reliably in
#     college demos without external API billing or failures.

import os
import re
import json
import urllib.request
from typing import Optional
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

# ---------------------------------------------------------------
# Grounded Knowledge Base for RAG Retrieval
# Every card & fact reflects verified code inside PehchaanAI.
# Separating multi-word phrases, clean domain keywords, and atomic
# facts lets offline synthesis pick exact answers instead of dumping
# unrelated paragraphs.
# ---------------------------------------------------------------
KNOWLEDGE_DOCS = [
    {
        "id": "project_overview",
        "title": "PehchaanAI Project Overview & Objectives",
        "phrases": [
            "what is pehchaanai",
            "about project",
            "problem statement",
            "ff 180",
            "ff180",
            "major project",
            "sdg 9",
            "how it works",
            "verification steps",
            "four step",
        ],
        "keywords": [
            "overview", "purpose", "goal", "objective", "vit", "pune", "ff180",
            "sdg", "onboarding", "wizard", "step", "workflow", "pipeline",
        ],
        "facts": [
            "PehchaanAI is a browser-based real-time Video KYC & Fraud Intelligence platform registered as VIT Pune BTech CS-A Group 47 major project (SDG 9).",
            "It solves the hours-to-days delay of traditional batch Video KYC by verifying identity in-session over live WebSockets.",
            "The guided 4-step wizard at /verify covers: (1) DPDP Biometric Consent -> (2) Live MediaPipe Blink Liveness & Anti-Spoof -> (3) Multi-ID OCR & Validation -> (4) 128-d Face Match, Fraud Risk Scoring & Instant Verdict.",
            "Beyond verification (/verify), the platform provides an Applicant Status Tracker & Erasure Portal (/status), User Accounts (/account), Compliance Reviewer Operations Portal (/dashboard), and Grounded AI Assistant (/assistant).",
        ],
    },
    {
        "id": "tech_stack",
        "title": "Full-Stack Technology Stack & Architecture",
        "phrases": [
            "tech stack",
            "technology stack",
            "which stack",
            "what languages",
            "frontend framework",
            "backend framework",
            "what libraries",
            "packages used",
            "vite build",
        ],
        "keywords": [
            "stack", "react", "typescript", "vite", "fastapi", "uvicorn",
            "python", "websocket", "opencv", "mediapipe", "dlib", "tesseract",
            "pymupdf", "postgres", "postgresql", "redis", "sqlalchemy",
            "cryptography", "fernet", "architecture", "framework", "library",
        ],
        "facts": [
            "Frontend: React 18, TypeScript 5, Vite 5, React Router DOM 6, and Lucide icons inside frontend-web/, compiled into frontend-web/dist/ so FastAPI serves everything from http://localhost:8000.",
            "Backend & Real-Time Streaming: Python 3.10, FastAPI 0.111.0, Uvicorn 0.30.1, and WebSockets 12.0 (/ws/kyc/{session_id}) streaming webcam frames every 500 ms.",
            "Computer Vision & Document AI: MediaPipe 0.10.14 (Face Mesh), face_recognition 1.3.0 (dlib 128-d embeddings), OpenCV 4.6.0, pytesseract 0.3.10 (Tesseract OCR), and PyMuPDF 1.24.5 (PDF conversion).",
            "Data & Security Layer: Redis 5.0.4 for 15-minute live session state, PostgreSQL 18 + SQLAlchemy 2.0.30 for permanent records/audit trails, and cryptography 50.0.2 (Fernet AES-128 Vault) + PBKDF2/HS256 JWT auth.",
        ],
    },
    {
        "id": "library_choices",
        "title": "Design Decisions: Tesseract vs PaddleOCR, dlib & Heuristic CV",
        "phrases": [
            "why tesseract",
            "why not paddleocr",
            "paddle ocr",
            "why dlib",
            "why face_recognition",
            "arcface",
            "protobuf conflict",
            "why heuristic",
        ],
        "keywords": [
            "paddleocr", "paddlepaddle", "protobuf", "tesseract", "arcface",
            "deepface", "dlib", "choice", "alternative", "conflict", "window",
        ],
        "facts": [
            "Tesseract OCR + PyMuPDF replaced PaddleOCR because on Windows Python 3.10, paddlepaddle 2.6.2 requires protobuf <= 3.20.2 whereas mediapipe 0.10.14 requires protobuf >= 4.25.",
            "face_recognition (dlib 128-d ResNet embeddings) was chosen for accurate CPU-friendly cross-domain matching (selfie vs printed ID) without GPU deployment overhead.",
            "Anti-spoofing uses deterministic OpenCV heuristics (LBP texture, FFT spectrum, Laplacian sharpness, and Canny/Hough bezel lines) instead of a heavy GPU deepfake CNN.",
        ],
    },
    {
        "id": "database_and_redis",
        "title": "PostgreSQL Schema & Redis Session Architecture",
        "phrases": [
            "database schema",
            "database tables",
            "why redis",
            "redis ttl",
            "session ttl",
            "session state",
            "sessions stored",
            "postgres tables",
            "how is data stored",
            "audit trail",
        ],
        "keywords": [
            "database", "postgres", "postgresql", "redis", "ttl", "table",
            "schema", "sqlalchemy", "column", "migration", "audit", "900",
        ],
        "facts": [
            "Redis (session_manager.py) stores active live sessions under key session:{uuid} with a 900-second (15-minute) TTL for fast in-memory frame updates during WebSocket streaming.",
            "PostgreSQL (database.py) stores 4 permanent tables: users (applicant & reviewer accounts), consent_records (v1.0-DPDP consent proofs), kyc_sessions (tracking code KYC-<SID8>, scores, verdicts, OCR fields), and audit_events.",
            "On startup, create_tables() runs safe idempotent ALTER TABLE kyc_sessions ADD COLUMN IF NOT EXISTS migrations and seeds the default compliance reviewer if missing.",
            "Every critical lifecycle step (session created, consent recorded, document scanned, face matched, fraud assessed, evidence accessed, reviewer decision, pii_erased) appends an audit event row.",
        ],
    },
    {
        "id": "liveness_detection",
        "title": "Real-Time Face Mesh & EAR Blink Liveness",
        "phrases": [
            "blink liveness",
            "eye aspect ratio",
            "how many blinks",
            "face landmark",
            "468 landmark",
            "how does liveness work",
            "ear threshold",
        ],
        "keywords": [
            "blink", "liveness", "ear", "eye", "landmark", "mesh", "468",
            "mediapipe", "webcam", "frame", "stream", "consec",
        ],
        "facts": [
            "face_detector.py uses MediaPipe Face Mesh (static_image_mode=True, refine_landmarks=True, min_detection_confidence=0.5) to track 468 2D/3D facial landmarks.",
            "liveness.py computes Eye Aspect Ratio (EAR) = vertical eyelid distance / horizontal eye width using eye landmarks [top, bottom, left, right] for both eyes.",
            "Open eyes normally score EAR 0.25–0.35; when EAR drops below EAR_THRESHOLD = 0.20 for at least EAR_CONSEC_FRAMES = 2 consecutive frames and reopens, 1 blink is counted.",
            "Passing liveness requires BLINKS_REQUIRED = 2 natural blinks in the live WebSocket stream to block still-photo presentation attacks.",
        ],
    },
    {
        "id": "anti_spoofing",
        "title": "Multi-Layer Heuristic Anti-Spoofing Defense",
        "phrases": [
            "anti spoof",
            "anti-spoofing",
            "spoof detection",
            "screen replay",
            "printed photo",
            "bezel detection",
            "spoof threshold",
            "spoof score",
        ],
        "keywords": [
            "spoof", "bezel", "fft", "lbp", "texture", "laplacian", "sharpness",
            "canny", "hough", "frequency", "replay", "screen", "photo", "deepfake",
        ],
        "facts": [
            "spoof_detector.py combines 4 OpenCV cues into a 0–1 realness score: Device Bezel Detection (50% weight), LBP Skin Texture Entropy (25%), 2D FFT High-Frequency Ring Ratio (20%), and Laplacian Sharpness (5%).",
            "Bezel detection uses Canny edge detection + HoughLinesP to spot long axis-aligned horizontal/vertical edges characteristic of phones or tablets held to a webcam.",
            "main.py smooths spoof scores across a 25-frame rolling window (SPOOF_HISTORY_SIZE = 25) with cutoff SPOOF_AVG_THRESHOLD = 0.72 (live faces average ~0.78–0.82; screen replays drift down to ~0.67–0.70).",
            "If the sustained average drops below 0.72, spoof_detected becomes True and forces an immediate FAIL verdict. Note: this is a calibrated CV heuristic, not a neural deepfake detector.",
        ],
    },
    {
        "id": "face_matching",
        "title": "128-D Face Matching & Calibrated Confidence Curve",
        "phrases": [
            "face match",
            "face matching",
            "confidence threshold",
            "confidence calculation",
            "euclidean distance",
            "match threshold",
            "128 dimensional",
            "id photo match",
        ],
        "keywords": [
            "match", "confidence", "distance", "embedding", "encoding", "128",
            "hog", "threshold", "upsample", "selfie", "portrait", "similarity",
        ],
        "facts": [
            "face_match.py extracts 128-dimensional dlib face encodings using upscaled images (>= 1000 px), HOG detection (fast upsample=1 with upsample=2 fallback for small ID portraits), L-channel CLAHE lighting normalization, 68-landmark 'large' alignment, and adaptive jitter averaging.",
            "Similarity is computed via Euclidean face_distance between the live selfie encoding and the ID photo encoding (boolean cutoff MATCH_THRESHOLD = 0.60; age/lighting variance 0.60–0.65 routes to human REVIEW when liveness and anti-spoofing pass).",
            "Piecewise confidence calibration: distance <= 0.32 -> 92%–100%; 0.32–0.46 -> 75%–92% (cross-domain PASS zone); 0.46–0.56 -> 50%–75% (borderline REVIEW zone); 0.56–0.60 -> 20%–50%; > 0.60 drops toward 0%.",
            "Even if matched=True (distance < 0.60), confidence must reach >= 75.0% for an automatic PASS; 50.0%–74.9% (or 0.60–0.65 age/lighting variance) routes to human compliance REVIEW.",
        ],
    },
    {
        "id": "ocr_and_documents",
        "title": "Document Intelligence, OCR Quality Gate & Indian ID Validators",
        "phrases": [
            "supported id",
            "supported document",
            "aadhaar card",
            "pan card",
            "verhoeff checksum",
            "quality gate",
            "pdf upload",
            "id upload",
            "upload fail",
            "blurry id",
            "ocr fail",
            "driving licence",
            "voter id",
            "ocr error",
        ],
        "keywords": [
            "aadhaar", "pan", "passport", "driving", "licence", "voter", "epic",
            "institutional", "ocr", "pdf", "verhoeff", "checksum", "quality",
            "scan", "document", "dob", "mrz", "upload", "blur", "rejected",
        ],
        "facts": [
            "ocr.py supports Indian Aadhaar, PAN, Driving Licence, Passport (MRZ P<IND), Voter ID (EPIC), and Institutional/College IDs uploaded as JPG, PNG, or PDF (max 10 MB).",
            "PDF uploads are detected by %PDF magic bytes and rendered at 2x scale in memory using PyMuPDF (fitz) before Tesseract preprocessing (greyscale, 2x cubic upscale, 5x5 Gaussian blur, thresholding).",
            "The OCR Quality Gate rejects blurry or noisy uploads if extracted text has < 15 characters OR fewer than 75% alphanumeric/whitespace characters.",
            "12-digit Aadhaar numbers are checked mathematically via the Verhoeff dihedral D5 checksum (and must not start with 0 or 1; masked XXXX XXXX 1234 skips checksum); PAN validates ^[A-Z]{5}[0-9]{4}[A-Z]$ and 4th-char entity code (e.g. P=Individual).",
        ],
    },
    {
        "id": "fraud_risk_engine",
        "title": "Unified Fraud Risk Engine (0–100 Score Breakdown)",
        "phrases": [
            "fraud score",
            "fraud risk",
            "risk score",
            "how is fraud calculated",
            "risk breakdown",
            "velocity check",
            "id reuse",
        ],
        "keywords": [
            "fraud", "risk", "score", "breakdown", "velocity", "reuse", "ip",
            "penalty", "component", "level", "medium", "100",
        ],
        "facts": [
            "fraud_engine.py computes a 0–100 Unified Fraud Risk Score across 4 components: Face Match Risk (max 30 pts), Spoof & Liveness Risk (max 35 pts), Document Integrity Risk (max 10 pts), and History/Velocity Risk (max 25 pts).",
            "Face risk scales smoothly as 30 * (1 - confidence/100); missing or failed matches score +30.0. Spoof adds +35.0; failed liveness adds +25.0; narrow spoof margin (< 0.80) adds up to +10.0.",
            "Document risk adds up to +10.0 for missing fields (id_number +4, id_type +3, name +2, dob +1) or +8.0 if checksum validation fails.",
            "History risk queries PostgreSQL for prior failed/spoofed sessions tied to the same ID (+15.0), ID reuse across >= 2 sessions (+8.0), or recent IP failures (+5.0 each, max 15). Levels: LOW (<25), MEDIUM (25–54.9), HIGH (>=55).",
        ],
    },
    {
        "id": "decision_verdicts",
        "title": "How PASS, REVIEW, and FAIL Verdicts Are Decided",
        "phrases": [
            "why review",
            "why fail",
            "why pass",
            "verdict rules",
            "pass threshold",
            "manual review",
            "incomplete verdict",
        ],
        "keywords": [
            "pass", "review", "fail", "incomplete", "verdict", "decision",
            "borderline", "escalate", "approve", "reject", "condition",
        ],
        "facts": [
            "FAIL (highest priority): triggers immediately if spoof_detected is True, or if face_found is True but blink liveness failed, or if face distance exceeds 0.60.",
            "REVIEW (Human Compliance Queue): triggers if all CV checks pass but match_confidence is borderline (50.0%–74.9%), OR if Unified Fraud Risk Score >= 55.0.",
            "PASS (Automatic Approval): requires face_detected, liveness_passed, no spoof, id_scanned, face_matched=True, match_confidence >= 75.0%, and fraud_score < 55.0.",
            "INCOMPLETE: returned when required steps were skipped (for instance, face match triggered without scanning an ID or completing liveness).",
        ],
    },
    {
        "id": "privacy_vault_dpdp",
        "title": "Encrypted Evidence Vault, DPDP Consent & Right-to-Erasure",
        "phrases": [
            "right to erasure",
            "erase my data",
            "delete biometric",
            "evidence vault",
            "fernet encryption",
            "how is selfie encrypted",
            "dpdp consent",
            "retention policy",
        ],
        "keywords": [
            "privacy", "encrypt", "fernet", "aes", "hmac", "vault", "erase",
            "erasure", "consent", "dpdp", "retention", "purge", "redacted",
            "security", "blob",
        ],
        "facts": [
            "vault.py encrypts every ID photo and selfie before saving to uploads/vault/<sid8>_<kind>.enc using Fernet (AES-128-CBC + HMAC-SHA256 authentication).",
            "HMAC authentication ensures any modified byte fails decryption safely with InvalidToken; reviewers viewing images inside /dashboard log an immutable evidence_accessed audit event (with UIDAI first-8-digit Aadhaar masking enabled by default).",
            "Explicit DPDP consent (v1.0-DPDP) is logged in consent_records before activating the webcam, and POST /session/start rejects consent_given=false with HTTP 400.",
            "Applicants can erase stored biometrics anytime via /status (Right-to-Erasure), which deletes vault .enc blobs, sets DB PII to [REDACTED], and logs pii_erased. Admins can also purge blobs older than 30 days.",
        ],
    },
    {
        "id": "auth_and_reviewer_portal",
        "title": "User Accounts, Tracking Codes & Reviewer Operations Portal",
        "phrases": [
            "reviewer portal",
            "how to sign in",
            "tracking code",
            "track status",
            "compliance export",
            "reviewer login",
            "jwt auth",
            "account history",
        ],
        "keywords": [
            "auth", "login", "register", "account", "jwt", "pbkdf2", "password",
            "passcode", "reviewer", "dashboard", "tracking", "status", "csv",
            "json", "export", "certificate", "receipt",
        ],
        "facts": [
            "User auth (auth.py) hashes passwords with PBKDF2-HMAC-SHA256 (120,000 iterations + 16-byte random salt) and issues 24-hour HS256 JWT tokens for /account history and RBAC.",
            "Every verification gets a short Tracking Code (KYC-<first 8 chars of UUID>) for public status lookup at /status with masked ID numbers and printable certificates.",
            "The Reviewer Portal (/dashboard or /reviewer) accepts either role-verified reviewer JWTs (default seeded email: reviewer@pehchaanai.local) or the DASHBOARD_PASSWORD configured in backend/.env.",
            "Reviewers can inspect live analytics, trigger AI triage briefs, decrypt vault photos side-by-side, Approve/Escalate/Reject cases with notes, and export filtered CSV or JSON compliance reports.",
        ],
    },
    {
        "id": "evaluation_and_limitations",
        "title": "Measured Evaluation Benchmarks & Honest MVP Limitations",
        "phrases": [
            "known limitations",
            "project limitations",
            "evaluation results",
            "false rejection rate",
            "false acceptance rate",
            "production ready",
            "latency numbers",
        ],
        "keywords": [
            "limitations", "evaluation", "benchmark", "frr", "far", "latency",
            "metric", "accuracy", "production", "drawback", "weakness", "impostor",
        ],
        "facts": [
            "Using backend/evaluate.py across 21 genuine (same-person) session pairs: PASS=12, REVIEW=9, FAIL=0 -> 0.0% False Rejection Rate (FRR), 100.0% (21/21) OCR Quality Gate pass rate, mean distance 0.4636, and mean confidence 71.6%.",
            "Honest limitation 1: Anti-spoofing is a calibrated OpenCV heuristic MVP (LBP/FFT/Laplacian/Bezel), NOT a production-grade neural deepfake detector.",
            "Honest limitation 2: False Acceptance Rate (FAR) is not empirically measured because the sample benchmark lacks impostor (different-person) pairs.",
            "Honest limitation 3: Liveness state lives in single-worker process memory, vault keys default to deterministic .env derivation rather than Cloud KMS, and DEBUG_SAVE_CROPS must stay false to keep plaintext CV crops off disk.",
        ],
    },
    {
        "id": "lighting_camera_tips",
        "title": "Tips to Improve Camera, Liveness & Match Results",
        "phrases": [
            "not detecting",
            "camera not working",
            "low confidence",
            "glasses glare",
            "how to pass",
            "retry camera",
            "blink not detected",
        ],
        "keywords": [
            "lighting", "dark", "blur", "glass", "camera", "retry", "tip",
            "help", "improve", "backlit", "reflection", "crop", "flat",
        ],
        "facts": [
            "Face soft, even front lighting and avoid sitting with a bright window or lamp behind you so your face landmarks and texture stay clear.",
            "Remove tinted sunglasses and tilt away heavy eyeglass glare so MediaPipe can track eye aspect ratio cleanly across 2 deliberate natural blinks.",
            "Upload an uncropped, sharp flat photo or original PDF of your ID without flash reflection covering your face portrait or ID number.",
            "If browser camera permission is blocked or the WebSocket drops on /verify, enable webcam access in Brave and click Retry Camera without restarting consent.",
        ],
    },
]

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "about", "be", "between", "by", "can",
    "compare", "could", "describe", "did", "difference", "do", "does", "explain",
    "for", "from", "give", "get", "how", "i", "in", "instead", "into", "is",
    "it", "its", "know", "me", "my", "of", "on", "or", "our", "pehchaan",
    "pehchaanai", "please", "pls", "project", "reason", "reasons", "session",
    "sessions", "should", "still", "system", "tell", "that", "the", "their", "them", "there", "these",
    "this", "to", "us", "use", "used", "using", "versus", "vs", "was", "we",
    "were", "what", "when", "where", "which", "who", "whom", "why", "will",
    "with", "work", "works", "working", "would", "you", "your",
}

KEEP_ENDING_WORDS = {
    "redis", "pass", "fps", "https", "status", "canvas", "glasses", "lens",
    "process", "progress", "success", "access", "business", "address",
    "liveness", "sharpness", "realness", "limitations",
}

SYNONYM_MAP = {
    "aadhar": "aadhaar",
    "license": "licence",
    "blurry": "blur",
    "blurred": "blur",
    "unreadable": "blur",
    "darkness": "dark",
    "glare": "lighting",
    "bright": "lighting",
    "backlit": "lighting",
    "backlight": "lighting",
    "light": "lighting",
    "remove": "erase",
    "delete": "erase",
    "deletion": "erase",
    "gdpr": "dpdp",
    "purge": "retention",
    "stored": "store",
    "storage": "store",
    "encrypted": "encrypt",
    "encryption": "encrypt",
    "cryptographic": "encrypt",
    "frontend": "stack",
    "backend": "stack",
    "tech": "stack",
    "technology": "stack",
    "technologies": "stack",
    "architecture": "stack",
    "built": "stack",
    "postgres": "postgresql",
    "sql": "database",
    "db": "database",
    "table": "database",
    "tables": "database",
    "deepfake": "spoof",
    "spoofing": "spoof",
    "replay": "spoof",
    "fake": "spoof",
    "paddle": "paddleocr",
    "pending": "review",
    "flagged": "review",
    "manual": "review",
    "routed": "review",
    "threshold": "threshold",
    "thresholds": "threshold",
    "limit": "limitations",
    "limitation": "limitations",
    "weakness": "limitations",
    "weaknesses": "limitations",
    "drawback": "limitations",
    "drawbacks": "limitations",
    "signin": "login",
    "signup": "register",
    "passcode": "password",
    "credentials": "password",
    "cred": "password",
    "track": "tracking",
    "receipt": "status",
    "evaluate": "evaluation",
    "metrics": "evaluation",
    "benchmark": "evaluation",
    "benchmarks": "evaluation",
    "accuracy": "evaluation",
    "glasses": "glass",
    "blinks": "blink",
    "scores": "score",
    "steps": "step",
    "checks": "check",
    "matches": "match",
    "matching": "match",
    "verdicts": "verdict",
    "documents": "document",
    "cards": "card",
    "ids": "id",
}

GREETING_WORDS = {"hi", "hello", "hey", "greetings", "namaste", "yo", "sup"}


def _normalize_word(word: str) -> str:
    w = (word or "").lower().strip()
    if w in SYNONYM_MAP:
        return SYNONYM_MAP[w]
    if w not in KEEP_ENDING_WORDS and len(w) > 4:
        if w.endswith("ing") and len(w) > 6:
            w = w[:-3]
        elif w.endswith("es") and not w.endswith("ses"):
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
    return SYNONYM_MAP.get(w, w)


def _tokenize(text: str, remove_stopwords: bool = True) -> list[str]:
    raw_words = re.findall(r"[a-z0-9]+", (text or "").lower())
    out = []
    for raw in raw_words:
        if remove_stopwords and raw in STOPWORDS:
            continue
        norm = _normalize_word(raw)
        if remove_stopwords and norm in STOPWORDS:
            continue
        out.append(norm)
    return out


def _score_doc(clean_q_lower: str, q_tokens: set[str], doc: dict) -> float:
    phrase_score = 0.0
    for ph in doc.get("phrases", []):
        if ph in clean_q_lower:
            phrase_score += 8.0

    kw_set = {_normalize_word(k) for k in doc.get("keywords", [])}
    title_tokens = set(_tokenize(doc["title"], remove_stopwords=True))
    body_tokens = set(_tokenize(" ".join(doc["facts"]), remove_stopwords=True))

    return (
        phrase_score
        + len(q_tokens & kw_set) * 3.0
        + len(q_tokens & title_tokens) * 2.5
        + len(q_tokens & body_tokens) * 1.1
    )


def _rank_facts(q_tokens: set[str], clean_q_lower: str, doc: dict, max_facts: int = 4) -> list[str]:
    """Select the specific facts inside a knowledge card that directly answer the query."""
    facts = doc.get("facts", [])
    scored_facts = []
    for idx, fact in enumerate(facts):
        fact_tokens = set(_tokenize(fact, remove_stopwords=True))
        fact_lower = fact.lower()
        overlap = len(q_tokens & fact_tokens)
        bonus = sum(1.5 for tok in q_tokens if len(tok) >= 3 and tok in fact_lower)
        scored_facts.append((overlap * 2.0 + bonus, idx, fact))

    max_fact_score = max((s for s, _, _ in scored_facts), default=0.0)
    broad_only = max_fact_score == 0 or (
        doc.get("id") in ("project_overview", "tech_stack", "evaluation_and_limitations")
        and sum(1 for s, _, _ in scored_facts if s > 0) <= 2
        and max_fact_score < 5.0
    )
    if broad_only:
        return facts[:max_facts]

    # Pick highest-scoring facts up to max_facts, then restore natural card sequence
    by_score = sorted(scored_facts, key=lambda item: (-item[0], item[1]))
    chosen_indices = {idx for s, idx, _ in by_score[:max_facts] if s > 0}
    if not chosen_indices:
        return facts[:max_facts]
    return [fact for idx, fact in enumerate(facts) if idx in chosen_indices]


def _retrieve_context(query: str, top_k: int = 3) -> list[tuple[float, dict]]:
    clean_lower = (query or "").lower()
    q_tokens = set(_tokenize(query, remove_stopwords=True))
    scored = []
    for doc in KNOWLEDGE_DOCS:
        s = _score_doc(clean_lower, q_tokens, doc)
        if s > 0:
            scored.append((s, doc))

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[:top_k]


def _doc_as_context_text(doc: dict) -> str:
    return " ".join(doc.get("facts", []))


def _is_greeting_or_help(query: str) -> bool:
    raw_words = re.findall(r"[a-z0-9]+", (query or "").lower())
    if not raw_words:
        return False
    if len(raw_words) <= 4 and all(w in GREETING_WORDS or w in STOPWORDS for w in raw_words):
        return any(w in GREETING_WORDS for w in raw_words)
    lower = query.lower().strip()
    return any(p in lower for p in ("what can you do", "what can you help", "how can you help", "who are you"))


def _is_session_focused(query: str) -> bool:
    lower = (query or "").lower()
    session_cues = (
        "this session", "my session", "my verification", "my result", "my status",
        "why did i", "why was i", "why review", "why fail", "why did it",
        "attached", "track", "score", "verdict", "confidence", "fraud",
    )
    return any(cue in lower for cue in session_cues)


def _post_json(url: str, headers: dict, payload: dict, timeout: int = 8) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _try_external_llm(system_prompt: str, user_prompt: str) -> tuple[Optional[str], Optional[str]]:
    """
    Attempt grounded text generation using whichever LLM provider env var is configured.
    Returns (text, provider_name) or (None, None) when offline / no key is configured.
    """
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
            res = _post_json(
                url,
                {"Content-Type": "application/json"},
                {
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 420},
                },
            )
            text = res["candidates"][0]["content"]["parts"][0]["text"].strip()
            if text:
                return text, "gemini"
        except Exception as exc:
            print(f"[AI Agent] Gemini fallback triggered: {exc}")

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            res = _post_json(
                "https://api.groq.com/openai/v1/chat/completions",
                {"Content-Type": "application/json", "Authorization": f"Bearer {groq_key}"},
                {
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 420,
                },
            )
            text = res["choices"][0]["message"]["content"].strip()
            if text:
                return text, "groq"
        except Exception as exc:
            print(f"[AI Agent] Groq fallback triggered: {exc}")

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            res = _post_json(
                "https://api.openai.com/v1/chat/completions",
                {"Content-Type": "application/json", "Authorization": f"Bearer {openai_key}"},
                {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 420,
                },
            )
            text = res["choices"][0]["message"]["content"].strip()
            if text:
                return text, "openai"
        except Exception as exc:
            print(f"[AI Agent] OpenAI fallback triggered: {exc}")

    ollama_url = os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
    if ollama_url:
        try:
            model = os.getenv("OLLAMA_MODEL", "llama3.2").strip() or "llama3.2"
            res = _post_json(
                f"{ollama_url}/api/generate",
                {"Content-Type": "application/json"},
                {"model": model, "prompt": f"{system_prompt}\n\n{user_prompt}", "stream": False},
            )
            text = (res.get("response") or "").strip()
            if text:
                return text, "ollama"
        except Exception as exc:
            print(f"[AI Agent] Ollama fallback triggered: {exc}")

    return None, None


def _format_session_snippet(session: Optional[dict]) -> str:
    if not session:
        return ""
    id_fields = session.get("id_fields") or {}
    return (
        f"Session {session.get('tracking_code') or session.get('id', '')[:8]}: "
        f"verdict={session.get('verdict') or 'IN_PROGRESS'}, "
        f"confidence={session.get('match_confidence') or 0:.1f}%, "
        f"fraud_score={session.get('fraud_score') or 0:.1f}/100, "
        f"liveness_passed={bool(session.get('liveness_passed'))}, "
        f"spoof_detected={bool(session.get('spoof_detected'))}, "
        f"id_type={id_fields.get('id_type') or 'Unknown'}, "
        f"id_valid={id_fields.get('id_valid')}."
    )


def _format_session_answer(session_context: dict) -> str:
    verdict = session_context.get("verdict") or "IN PROGRESS"
    conf = float(session_context.get("match_confidence") or 0.0)
    fraud = float(session_context.get("fraud_score") or 0.0)
    code = session_context.get("tracking_code") or str(session_context.get("id", ""))[:8]
    id_fields = session_context.get("id_fields") or {}

    lines = [
        f"Attached Session ({code}) Summary:",
        f"- Verdict: {verdict} (Face match confidence: {conf:.1f}%, Unified Fraud Risk: {fraud:.1f}/100)",
        f"- Checks: liveness={'passed' if session_context.get('liveness_passed') else 'pending/failed'}, "
        f"anti-spoof={'FLAGGED' if session_context.get('spoof_detected') else 'clean'}, "
        f"ID={id_fields.get('id_type') or 'Not scanned'}",
    ]
    reasons = session_context.get("verdict_reasons") or []
    if reasons:
        lines.append(f"- Recorded audit signals: {'; '.join(reasons[:4])}.")
    return "\n".join(lines)


def chat_assistant(question: str, session_context: Optional[dict] = None) -> dict:
    """
    Grounded RAG assistant for applicants, reviewers, and project evaluation questions.
    Retrieves relevant PehchaanAI docs (+ active session facts if attached)
    and synthesizes an answer via LLM if configured or local grounded fact selection.
    """
    clean_q = (question or "").strip()
    if not clean_q or _is_greeting_or_help(clean_q):
        return {
            "answer": (
                "Hello! I am PehchaanAI's grounded KYC & Architecture Assistant. You can ask me specific questions such as:\n"
                "- \"What tech stack and libraries does PehchaanAI use?\"\n"
                "- \"Why does the system use Tesseract instead of PaddleOCR?\"\n"
                "- \"How do blink liveness (EAR) and anti-spoofing work?\"\n"
                "- \"How are face confidence, fraud risk score (0-100), and PASS/REVIEW/FAIL calculated?\"\n"
                "- \"How does Vault encryption, DPDP erasure, or the Reviewer Portal work?\"\n"
                "- \"What are the evaluation results and known MVP limitations?\""
            ),
            "provider": "local-grounded",
            "citations": ["PehchaanAI Project Overview & Objectives"],
            "retrieved_chunks": 1,
        }

    ranked_hits = _retrieve_context(clean_q, top_k=3)
    best_score = ranked_hits[0][0] if ranked_hits else 0.0

    # If external LLM is configured, provide top retrieved docs (or overview fallback)
    llm_docs = [doc for _, doc in ranked_hits] if ranked_hits else [KNOWLEDGE_DOCS[0], KNOWLEDGE_DOCS[1]]
    citations = [doc["title"] for _, doc in ranked_hits] if ranked_hits else []
    context_block = "\n\n".join(f"[{d['title']}]\n{_doc_as_context_text(d)}" for d in llm_docs)
    session_line = _format_session_snippet(session_context)

    system_prompt = (
        "You are PehchaanAI's grounded KYC Support, Architecture & Compliance Assistant. "
        "Answer the user's SPECIFIC question directly and concisely using ONLY the provided reference facts and session state. "
        "Do not pad with unrelated modules, never claim unverified capabilities, and keep security thresholds exact."
    )
    user_prompt = f"Reference Context:\n{context_block}\n"
    if session_line:
        user_prompt += f"\nAttached Session Data:\n{session_line}\n"
    user_prompt += f"\nUser Question: {clean_q}"

    llm_answer, provider = _try_external_llm(system_prompt, user_prompt)
    if llm_answer:
        return {
            "answer": llm_answer,
            "provider": provider,
            "citations": citations or [d["title"] for d in llm_docs],
            "retrieved_chunks": len(llm_docs),
        }

    # --- Deterministic Offline Grounded Synthesis ---
    clean_lower = clean_q.lower()
    q_tokens = set(_tokenize(clean_q, remove_stopwords=True))
    sections = []
    used_citations = []

    if session_context and (_is_session_focused(clean_q) or best_score < 2.0):
        sections.append(_format_session_answer(session_context))

    # Reject completely off-topic queries clearly instead of dumping random pipeline docs
    if best_score < 2.2 and not session_context:
        return {
            "answer": (
                "I couldn't match that question to a PehchaanAI topic in my grounded documentation.\n\n"
                "Try asking specifically about: verification steps, React/FastAPI tech stack, Tesseract vs PaddleOCR, "
                "MediaPipe EAR blink liveness, anti-spoofing weights, 128-d face match calibration, Aadhaar Verhoeff/PAN validation, "
                "0-100 fraud risk formula, PASS/REVIEW/FAIL thresholds, Fernet Vault & DPDP erasure, Reviewer Portal, PostgreSQL/Redis, "
                "or evaluation metrics & MVP limitations."
            ),
            "provider": "local-grounded",
            "citations": [],
            "retrieved_chunks": 0,
        }

    if ranked_hits:
        top_score, primary_doc = ranked_hits[0]
        primary_facts = _rank_facts(q_tokens, clean_lower, primary_doc, max_facts=4)
        used_citations.append(primary_doc["title"])
        sections.append(f"{primary_doc['title']}:\n" + "\n".join(f"- {f}" for f in primary_facts))

        # Only include a second card when it genuinely adds distinct value to a multi-part question
        if len(ranked_hits) > 1:
            second_score, second_doc = ranked_hits[1]
            if second_score >= max(4.0, top_score * 0.50):
                second_facts = _rank_facts(q_tokens, clean_lower, second_doc, max_facts=2)
                used_citations.append(second_doc["title"])
                sections.append(f"{second_doc['title']}:\n" + "\n".join(f"- {f}" for f in second_facts))

    return {
        "answer": "\n\n".join(sections),
        "provider": "local-grounded",
        "citations": used_citations or ["Session Data"],
        "retrieved_chunks": len(used_citations),
    }


def explain_session_for_user(session: dict) -> dict:
    """
    Generate plain-English XAI feedback & actionable next steps for an applicant.
    """
    verdict = session.get("verdict") or "INCOMPLETE"
    conf = float(session.get("match_confidence") or 0.0)
    fraud = float(session.get("fraud_score") or 0.0)
    reasons = session.get("verdict_reasons") or []
    id_fields = session.get("id_fields") or {}
    review_action = session.get("review_action")

    next_steps = []
    if review_action == "approved" or (verdict == "PASS" and not review_action):
        headline = "Identity Verified Automatically" if not review_action else f"Approved by Compliance Reviewer ({session.get('reviewed_by') or 'Agent'})"
        summary = (
            f"All required live biometric and document checks succeeded with {conf:.1f}% cross-domain face similarity "
            f"and a low unified fraud risk score ({fraud:.1f}/100)."
        )
        next_steps = [
            "Download or print your Verification Certificate for your records.",
            "Keep your Tracking Code to check status or manage biometric data privacy anytime.",
        ]
    elif verdict == "REVIEW":
        headline = "Routed for Human Compliance Review"
        if conf < 75.0 and fraud < 50.0:
            summary = (
                f"Live blink liveness and document OCR checks succeeded with {conf:.1f}% cross-domain face similarity "
                f"and low unified fraud risk ({fraud:.1f}/100), while minor age/lighting variance routed your session for "
                "standard human compliance sign-off in the Reviewer Portal."
            )
        else:
            summary = (
                f"Your session completed with {conf:.1f}% face similarity and a {fraud:.1f}/100 fraud risk score, "
                "which was flagged for human compliance verification."
            )
        next_steps = [
            "No immediate re-submission is required — a compliance officer can inspect your encrypted session in the Reviewer Portal.",
            "Track updates on the Status page using your Tracking Code.",
            "If retrying later, face even front lighting and upload an uncropped flat photo of your ID.",
        ]
    elif session.get("spoof_detected"):
        headline = "Security Hold — Presentation Spoof Suspected"
        summary = (
            "The live anti-spoofing analyzer flagged visual cues consistent with a phone screen replay or printed photo "
            "(sustained average score dropped below the 0.58 threshold)."
        )
        next_steps = [
            "Ensure you are verifying live in front of the webcam rather than showing another screen or photo.",
            "Avoid harsh monitor reflections on eyeglasses and retry in balanced natural light.",
        ]
    else:
        headline = "Verification Could Not Be Completed"
        summary = session.get("verdict_message") or "One or more required identity checks did not pass."
        if not session.get("liveness_passed"):
            next_steps.append("Look straight at the webcam and blink slowly twice until liveness turns green.")
        if id_fields.get("id_valid") is False:
            next_steps.append(f"Check your uploaded ID image — {id_fields.get('validation_note') or 'checksum validation failed'}.")
        if not session.get("face_matched"):
            next_steps.append("Upload a clearer photo/PDF of the same person shown on camera so the portrait matches cleanly.")
        if not next_steps:
            next_steps.append("Start a fresh verification session in bright front lighting.")

    prompt = (
        f"Explain this KYC result warmly to the applicant in 2 concise sentences:\n"
        f"{_format_session_snippet(session)}\nReasons: {reasons}"
    )
    llm_text, provider = _try_external_llm(
        "You explain KYC results politely in plain English without jargon.",
        prompt,
    )

    return {
        "headline": headline,
        "summary": llm_text or summary,
        "next_steps": next_steps,
        "reasons": reasons,
        "provider": provider or "local-grounded",
    }


def summarize_session_for_reviewer(session: dict, audit_trail: list) -> dict:
    """
    Generate an AI Reviewer Agent case summary + triage recommendation (FF180 Objective 3).
    """
    verdict = session.get("verdict") or "INCOMPLETE"
    conf = float(session.get("match_confidence") or 0.0)
    fraud = float(session.get("fraud_score") or 0.0)
    spoof = bool(session.get("spoof_detected"))
    id_fields = session.get("id_fields") or {}
    reasons = session.get("verdict_reasons") or []

    risk_highlights = []
    if spoof:
        risk_highlights.append(f"Anti-spoofing flagged (avg score {session.get('spoof_score')})")
    if conf and conf < 75.0:
        risk_highlights.append(f"Cross-domain confidence is borderline ({conf:.1f}% vs 75.0% auto-pass bar)")
    if fraud >= 55.0:
        risk_highlights.append(f"Elevated Unified Fraud Score ({fraud:.1f}/100)")
    if id_fields.get("id_valid") is False:
        risk_highlights.append(f"Document validation warning: {id_fields.get('validation_note')}")
    if not risk_highlights:
        risk_highlights.append("No elevated fraud or anti-spoof anomalies recorded")

    if spoof or fraud >= 70.0 or not session.get("face_matched"):
        rec_action = "reject"
        rec_reason = "Strong security risk indicators (spoof flag, failed biometric match, or fraud score >= 70)."
    elif conf >= 65.0 and fraud < 40.0 and id_fields.get("id_valid") is not False and session.get("liveness_passed"):
        rec_action = "approve"
        rec_reason = "Borderline photo aging/lighting similarity with clean anti-spoof, valid liveness, and low fraud risk (< 40). Recommend decrypting vault images to visually confirm before approving."
    else:
        rec_action = "escalate"
        rec_reason = "Mixed biometric/fraud signals; visually inspect the decrypted ID and selfie photos before finalizing."

    prompt = (
        f"Write a concise 2-sentence compliance officer brief for this KYC case:\n"
        f"{_format_session_snippet(session)}\nAudit events: {len(audit_trail)}\nHighlights: {risk_highlights}"
    )
    llm_brief, provider = _try_external_llm(
        "You are a KYC Compliance Triage Assistant writing factual 2-sentence summaries for human reviewers.",
        prompt,
    )

    fallback_summary = (
        f"Applicant ({session.get('applicant_name') or 'Anonymous'}) submitted {id_fields.get('id_type') or 'an ID document'} "
        f"producing verdict {verdict} ({conf:.1f}% face match, {fraud:.1f}/100 fraud risk, {len(audit_trail)} audit events logged). "
        f"Suggested action: {rec_action.upper()}."
    )

    return {
        "executive_summary": llm_brief or fallback_summary,
        "risk_highlights": risk_highlights,
        "recommended_action": rec_action,
        "recommended_reason": rec_reason,
        "reasons": reasons,
        "audit_count": len(audit_trail),
        "provider": provider or "local-grounded",
    }
