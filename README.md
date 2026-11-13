# PehchaanAI — Real-Time Video KYC & Identity Verification

**VIT Pune · Department of Computer Engineering · Major Project (BTech CS-A Group 47 · SDG 9)**

PehchaanAI is a browser-based **real-time Video KYC and Fraud Intelligence platform**. Instead of recording an onboarding video and verifying it hours or days later, PehchaanAI runs biometric consent, live webcam liveness, heuristic anti-spoofing, multi-document OCR with mathematical checksums, 128-d face matching, and a Unified Fraud Risk Engine *during* the live session—producing an instant **PASS / REVIEW / FAIL** verdict with an encrypted audit trail.

---

## Architecture Overview

- **Frontend (`frontend-web/`):** React 18, TypeScript 5, Vite 5, React Router DOM 6, Lucide Icons — compiled into `frontend-web/dist/` and served directly by FastAPI on `http://localhost:8000` (with fallback to `frontend/` if not yet built).
- **Backend (`backend/`):** Python 3.10, FastAPI 0.111.0, Uvicorn 0.30.1, WebSockets 12.0 (`/ws/kyc/{session_id}`).
- **Computer Vision & OCR:** MediaPipe 0.10.14 (`FaceMesh` 468 landmarks), OpenCV 4.6.0, `face-recognition` 1.3.0 (dlib 128-d embeddings), `pytesseract` 0.3.10 (Tesseract OCR), PyMuPDF 1.24.5 (PDF IDs).
- **State & Storage:** Redis 5.0.4 (15-min live session cache, key `session:{uuid}`), PostgreSQL 18 + SQLAlchemy 2.0.30 (`users`, `consent_records`, `kyc_sessions`, `audit_events`), and Fernet Vault (`cryptography` AES-128-CBC + HMAC-SHA256 `.enc` evidence blobs).
- **Hybrid RAG / Explainable AI (`ai_agent.py`):** Works deterministically offline with verified project docs (`local-grounded`), or upgrades seamlessly if `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, or `OLLAMA_BASE_URL` is added to `backend/.env`.

---

## Fresh Clone Setup Guide (For Group Mates on Windows)

### 1. Prerequisites
Install these tools locally before cloning:
1. **Python 3.10** (matching `mediapipe==0.10.14` & `dlib`/`face-recognition` wheels; note CMake / Visual Studio C++ Build Tools if building `dlib` from source)
2. **Node.js 18+** (tested with Node v24 + `npm.cmd`)
3. **PostgreSQL** (running on `localhost:5432`)
4. **Redis** (running locally on `localhost:6379`)
5. **Tesseract OCR** (on Windows, default installer writes to `C:\Program Files\Tesseract-OCR\tesseract.exe`; auto-detected or configurable via `TESSERACT_CMD`)

### 2. Clone & Configure Environment
```bat
git clone https://github.com/Purvaaa15/realtime-kyc.git
cd realtime-kyc
copy backend\.env.example backend\.env
```
Open `backend\.env` and update **`DATABASE_URL`** with your own local PostgreSQL username, password, and database (e.g., create database `kyc_db` in pgAdmin or `psql`), and customize `SECRET_KEY` and `DASHBOARD_PASSWORD` if desired.

### 3. Install Python Dependencies
```bat
python -m venv venv
venv\Scripts\activate.bat
pip install -r backend\requirements.txt
```
*(Note: Tesseract + PyMuPDF is used instead of PaddleOCR because on Windows Python 3.10, `paddlepaddle 2.6.2` requires `protobuf <= 3.20.2`, which conflicts with `mediapipe 0.10.14`'s `protobuf >= 4.25`.)*

### 4. Build the React + TypeScript Frontend
*(In VS Code PowerShell, use `npm.cmd` because `npm.ps1` may be blocked by Windows ExecutionPolicy.)*
```bat
cd frontend-web
npm.cmd install
npm.cmd run build
cd ..
```

### 5. Verify Local Setup, Start Services, and Launch PehchaanAI
Run the quick preflight checker to confirm `.env`, PostgreSQL, Redis, Tesseract, and React build status on your machine:
```bat
venv\Scripts\python.exe backend\check_setup.py
```
Once all required checks show `[PASS]`, start PostgreSQL & Redis and run the server directly from the project root:
```bat
venv\Scripts\python.exe backend\main.py
```
Look for `Redis connected` and `Uvicorn running on http://0.0.0.0:8000` in the terminal.  
*(PostgreSQL tables are created and migrated automatically on startup via `create_tables()`, and the default compliance reviewer `reviewer@pehchaanai.local` is seeded with `DASHBOARD_PASSWORD`.)*

### 6. Open in Browser (Always use `localhost`, not `0.0.0.0`)
- **Home / Overview:** `http://localhost:8000/`
- **Guided 4-Step KYC Wizard:** `http://localhost:8000/verify`
- **Track Status & DPDP Erasure:** `http://localhost:8000/status`
- **AI Support & Architecture Assistant:** `http://localhost:8000/assistant`
- **Applicant Sign In / Register / History:** `http://localhost:8000/login`
- **Compliance Reviewer Portal:** `http://localhost:8000/dashboard` (default passcode in `.env.example`: `admin123`, or email `reviewer@pehchaanai.local`)

---

## Core Verification Pipeline

1. **Consent & Session Init (`POST /session/start`):** Records `v1.0-DPDP` consent in PostgreSQL (`consent_records`) and initializes a Redis session with tracking code `KYC-<SID8>`.
2. **Real-Time Liveness & Anti-Spoof (`WS /ws/kyc/{session_id}`):**
   - **Blink Liveness (`liveness.py`):** Computes Eye Aspect Ratio (`EAR`) across 468 MediaPipe landmarks (`EAR_THRESHOLD = 0.20`, `2` blinks required).
   - **Anti-Spoofing (`spoof_detector.py`):** Combines Bezel detection (50%), LBP skin texture entropy (25%), 2D FFT frequency ratio (20%), and Laplacian sharpness (5%) over a rolling 25-frame window (`SPOOF_AVG_THRESHOLD = 0.72`).
3. **Document Intelligence (`POST /scan-id`, `ocr.py`):**
   - Supports **Aadhaar** (12-digit **Verhoeff** checksum), **PAN**, **Driving Licence**, **Passport**, **Voter ID**, and **Institutional ID** (JPG, PNG, or PDF).
   - Rejects unreadable scans via the OCR Quality Gate (`< 15` chars or `< 75%` alphanumeric/whitespace).
4. **Face Match, Fraud Engine & Verdict (`POST /match-face`):**
   - 128-d Euclidean distance (`MATCH_THRESHOLD = 0.60`), calibrated into confidence tiers (`>= 75%` auto-PASS band, `50%–74.9%` REVIEW band).
   - **Unified Fraud Risk Score (0–100, `fraud_engine.py`):** Combines Face Risk (max 30), Spoof/Liveness Risk (max 35), Document Integrity + Declared-vs-OCR Name Check (max 10), and DB ID-reuse / IP-velocity History Risk (max 25).
   - Stores ID & selfie photos encrypted in `uploads/vault/` via Fernet (AES-128-CBC + HMAC-SHA256) and supports DPDP Right-to-Erasure (`POST /api/sessions/{id}/erase`).

---

## Evaluation & Honest MVP Limitations

Run the calibration & latency benchmark anytime on saved pairs:
```bat
venv\Scripts\python.exe backend\evaluate.py
```
- **Observed genuine-pair benchmark (21 pairs):** `PASS=12, REVIEW=9, FAIL=0` -> **0.0% FRR**, **100.0% OCR Quality Gate pass rate (21/21)**, mean distance `0.4636`, mean confidence `71.6%`.
- **Multi-Subject Impostor Benchmark (FAR with group mates):** Add consented `uploads/subjects/<teammate_name>/selfie.jpg` and `id.jpg` folders (2+ teammates, git-ignored) and re-run `evaluate.py` to compute empirical cross-pair False Acceptance Rate (FAR).
- **Known Limitations:**
  - Anti-spoofing is a calibrated OpenCV heuristic MVP rather than a neural deepfake detector.
  - False Acceptance Rate (FAR) is not measured on the sample dataset because it lacks dedicated impostor (different-person) pairs.
  - WebSocket liveness state lives in single-worker process memory, and Fernet keys derive from `.env` (`SECRET_KEY` / `VAULT_KEY`) rather than an external KMS.
