"""
Local setup diagnostics script for PehchaanAI group mates.

Run from the project root after cloning and installing requirements:
    venv\\Scripts\\python.exe backend\\check_setup.py
"""

import glob
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _status(label: str, state: str, detail: str) -> None:
    print(f"[{state:4s}] {label:<24s} -> {detail}")


def main() -> int:
    print("=" * 64)
    print("  PehchaanAI - Local Clone Readiness Check")
    print("=" * 64)

    failures = 0

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if (3, 10) <= sys.version_info[:2] <= (3, 11):
        _status("Python Version", "PASS", py_ver)
    else:
        _status("Python Version", "WARN", f"{py_ver} (Python 3.10 recommended for mediapipe/dlib wheels)")

    # 2. backend/.env check
    env_path = os.path.join(BACKEND_DIR, ".env")
    if os.path.isfile(env_path):
        env_raw = open(env_path, "r", encoding="utf-8", errors="ignore").read()
        if "your_postgres_password" in env_raw:
            _status("backend/.env", "FAIL", "Still uses placeholder password 'your_postgres_password'")
            failures += 1
        else:
            _status("backend/.env", "PASS", "Found and customized")
    else:
        _status("backend/.env", "FAIL", "Missing! Run: copy backend\\.env.example backend\\.env")
        failures += 1

    # 3. Core Python packages
    required_pkgs = [
        ("cv2", "opencv-python"),
        ("mediapipe", "mediapipe"),
        ("face_recognition", "face-recognition"),
        ("pytesseract", "pytesseract"),
        ("fitz", "PyMuPDF"),
        ("sqlalchemy", "SQLAlchemy"),
        ("redis", "redis"),
        ("cryptography", "cryptography"),
    ]
    missing_pkgs = []
    for mod, pkg_name in required_pkgs:
        try:
            __import__(mod)
        except Exception:
            missing_pkgs.append(pkg_name)
    if missing_pkgs:
        _status("Python Packages", "FAIL", f"Missing: {', '.join(missing_pkgs)}")
        failures += 1
    else:
        _status("Python Packages", "PASS", f"All {len(required_pkgs)} core ML/backend packages import cleanly")

    # 4. Tesseract binary resolution
    try:
        from ocr import _resolve_tesseract_cmd

        tess = _resolve_tesseract_cmd()
        if tess:
            _status("Tesseract OCR", "PASS", tess)
        else:
            _status("Tesseract OCR", "FAIL", "Binary not found. Install Tesseract OCR or set TESSERACT_CMD in backend/.env")
            failures += 1
    except Exception as exc:
        _status("Tesseract OCR", "FAIL", str(exc))
        failures += 1

    # 5. PostgreSQL connection
    try:
        from database import check_database_connection

        if check_database_connection():
            _status("PostgreSQL", "PASS", "Connected cleanly via DATABASE_URL")
        else:
            _status("PostgreSQL", "FAIL", "Connection failed. Check PostgreSQL service & DATABASE_URL in backend/.env")
            failures += 1
    except Exception as exc:
        _status("PostgreSQL", "FAIL", str(exc))
        failures += 1

    # 6. Redis connection
    try:
        from session_manager import check_redis_connection

        if check_redis_connection():
            _status("Redis", "PASS", "Connected on configured REDIS_HOST:REDIS_PORT")
        else:
            _status("Redis", "FAIL", "Not reachable. Start Redis service on port 6379")
            failures += 1
    except Exception as exc:
        _status("Redis", "FAIL", str(exc))
        failures += 1

    # 7. React production build
    dist_index = os.path.join(ROOT_DIR, "frontend-web", "dist", "index.html")
    if os.path.isfile(dist_index):
        _status("React SPA Build", "PASS", "frontend-web/dist/index.html present")
    else:
        _status("React SPA Build", "WARN", "Not built yet. Run: cd frontend-web && npm.cmd install && npm.cmd run build")

    # 8. Optional sample images note
    uploads_samples = glob.glob(os.path.join(ROOT_DIR, "uploads", "id_*.jpg"))
    _status("Saved Samples", "INFO", f"{len(uploads_samples)} local test uploads found (not needed to run live webcam KYC)")

    print("-" * 64)
    if failures:
        print(f"Result: {failures} required check(s) failed. Fix [FAIL] items above before starting.")
        return 1
    print("Result: Ready! Run 'venv\\Scripts\\python.exe backend\\main.py' and open http://localhost:8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
