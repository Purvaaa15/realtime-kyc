# ocr.py
# This module handles ID document scanning using Tesseract OCR.
#
# OCR = Optical Character Recognition
# It's the technology that reads text from images.
#
# HOW IT WORKS:
# 1. Receive the image frame from the browser
# 2. Preprocess it (greyscale, denoise, threshold) to make text clearer
# 3. Run Tesseract on the cleaned image
# 4. Run quality gate to reject blurry/noisy frames
# 5. Parse the raw text for Aadhaar, PAN, Passport, DL, Voter ID, or Institutional ID
# 6. Validate document integrity (Aadhaar Verhoeff checksum, PAN holder type)

import cv2
import numpy as np
import pytesseract
import re
import os
import shutil
from typing import Optional
import fitz  # PyMuPDF — used to convert PDF pages to images
from dotenv import load_dotenv

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))


def _resolve_tesseract_cmd() -> Optional[str]:
    """Locate Tesseract cleanly across teammates' Windows/macOS/Linux machines."""
    env_cmd = os.getenv("TESSERACT_CMD", "").strip()
    if env_cmd and os.path.isfile(env_cmd):
        return env_cmd

    path_cmd = shutil.which("tesseract")
    if path_cmd:
        return path_cmd

    local_app_data = os.getenv("LOCALAPPDATA", "")
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(local_app_data, "Programs", "Tesseract-OCR", "tesseract.exe") if local_app_data else "",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


_tesseract_bin = _resolve_tesseract_cmd()
if _tesseract_bin:
    pytesseract.pytesseract.tesseract_cmd = _tesseract_bin

# ---------------------------------------------------------------
# VERHOEFF CHECKSUM TABLES (Used for Indian Aadhaar validation)
# The 12th digit of every real Aadhaar number is computed from the
# first 11 digits using the Verhoeff dihedral group D5 algorithm.
# This catches both single-digit typos/tampering and adjacent swaps!
# ---------------------------------------------------------------
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)

_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verify_aadhaar_verhoeff(number: str) -> bool:
    """Validate a 12-digit Aadhaar number using the Verhoeff checksum."""
    if not number or not number.isdigit() or len(number) != 12:
        return False
    # Real Aadhaar numbers cannot start with 0 or 1
    if number[0] in ("0", "1"):
        return False
    c = 0
    for i, digit in enumerate(reversed(number)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(digit)]]
    return c == 0


def validate_pan_format(pan: str) -> tuple[bool, str]:
    """Check PAN structure and 4th-character holder entity code."""
    if not pan or not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", pan):
        return False, "Invalid PAN structure"
    valid_entities = {
        "P": "Individual",
        "C": "Company",
        "H": "HUF",
        "F": "Firm",
        "A": "AOP",
        "T": "Trust",
        "B": "BOI",
        "L": "Local Authority",
        "J": "AJP",
        "G": "Government",
    }
    entity_code = pan[3]
    if entity_code not in valid_entities:
        return False, f"Invalid PAN entity code '{entity_code}'"
    return True, f"Valid PAN format ({valid_entities[entity_code]})"


# ---------------------------------------------------------------
# FUNCTION: preprocess_image
# Raw camera frames are often blurry, badly lit, or low contrast.
# This function cleans the image to make OCR more accurate.
#
# Steps:
# 1. Convert to greyscale (text is black/white — colour doesn't help)
# 2. Resize larger (Tesseract works better on bigger text)
# 3. Denoise (remove camera grain/noise)
# 4. Threshold (make pixels either pure black or pure white)
# ---------------------------------------------------------------
def _upscale_grayscale(image: np.ndarray, target_max_dim: int = 1600) -> np.ndarray:
    """Convert to grayscale and upscale small/low-res cards cleanly for Tesseract."""
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = grey.shape[:2]
    max_dim = max(h, w, 1)
    scale = max(2.0, min(4.0, float(target_max_dim) / float(max_dim)))
    return cv2.resize(grey, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def preprocess_image(image: np.ndarray) -> np.ndarray:
    """Adaptive-threshold preprocessing fallback for uneven camera lighting."""
    resized = _upscale_grayscale(image)
    blurred = cv2.GaussianBlur(resized, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        2,
    )
    return thresh


# ---------------------------------------------------------------
# FUNCTION: extract_text
# Runs Tesseract OCR on a preprocessed image and returns raw text.
# ---------------------------------------------------------------
def extract_text(image: np.ndarray, psm: int = 3) -> str:
    config = f"--oem 3 --psm {psm}"
    text = pytesseract.image_to_string(image, config=config)
    return text.strip()


# ---------------------------------------------------------------
# FUNCTION: parse_id_fields
# Takes the raw OCR text and tries to find specific fields across
# multiple document types (Aadhaar, PAN, Passport, Driving Licence,
# Voter ID, and Institutional ID).
#
# regex (regular expressions) are patterns for matching text.
# Example: r"\d{4}\s\d{4}\s\d{4}" matches "1234 5678 9012"
# ---------------------------------------------------------------
def parse_id_fields(raw_text: str) -> dict:
    fields = {
        "raw_text":        raw_text,
        "name":            None,
        "dob":             None,
        "id_number":       None,
        "id_type":         None,
        "id_valid":        None,    # True / False / None (when unverified/masked)
        "validation_note": None,
    }

    raw_lower = raw_text.lower()

    # Split into lines for easier processing
    lines = [line.strip() for line in raw_text.split("\n")
             if line.strip()]

    # --- Detect ID type, extract ID number, and validate format/checksum ---

    # 1. PAN: 5 letters + 4 digits + 1 letter (e.g. ABCDE1234F)
    pan_pattern = r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b"
    pan_match   = re.search(pan_pattern, raw_text)
    if pan_match:
        pan_num = pan_match.group()
        is_valid, note = validate_pan_format(pan_num)
        fields["id_number"]       = pan_num
        fields["id_type"]         = "PAN"
        fields["id_valid"]        = is_valid
        fields["validation_note"] = note

    # 2. Aadhaar: 12 digits in groups of 4 (e.g. 1234 5678 9012) or masked XXXX XXXX 1234
    # Use [ \t]? instead of \s? so a DOB year at the end of one line doesn't merge
    # with digits on the next line.
    if not fields["id_type"]:
        aadhaar_pattern = r"\b(?:\d{4}|[Xx]{4})[ \t]?(?:\d{4}|[Xx]{4})[ \t]?\d{4}\b"
        aadhaar_match   = re.search(aadhaar_pattern, raw_text)
        if aadhaar_match:
            num = re.sub(r"[ \t]+", "", aadhaar_match.group()).upper()
            fields["id_number"] = num
            fields["id_type"]   = "Aadhaar"
            if "X" in num:
                fields["id_valid"]        = None
                fields["validation_note"] = "Masked Aadhaar (checksum skipped)"
            else:
                is_valid = verify_aadhaar_verhoeff(num)
                fields["id_valid"]        = is_valid
                fields["validation_note"] = (
                    "Aadhaar Verhoeff checksum passed"
                    if is_valid else
                    "Aadhaar Verhoeff checksum failed (possible tampering or misread)"
                )
        elif "aadhaar" in raw_lower or "uidai" in raw_lower:
            fields["id_type"]         = "Aadhaar"
            fields["validation_note"] = "Aadhaar keywords detected, 12-digit number not visible"

    # 3. Driving Licence (Indian DL): e.g. MH12 20210012345 or MH-12 20210012345
    if not fields["id_type"]:
        dl_pattern = r"\b[A-Z]{2}[-\t ]?\d{2}[-\t ]?(?:19|20)\d{2}[ \t]?\d{7}\b"
        dl_match   = re.search(dl_pattern, raw_text)
        if dl_match:
            fields["id_number"]       = re.sub(r"[-\t ]+", "", dl_match.group())
            fields["id_type"]         = "Driving Licence"
            fields["id_valid"]        = True
            fields["validation_note"] = "Valid Indian Driving Licence format"
        elif "driving" in raw_lower and "licen" in raw_lower:
            fields["id_type"]         = "Driving Licence"
            fields["validation_note"] = "Driving Licence keywords detected"

    # 4. Passport (Indian Passport: 1 letter + 7 digits, or MRZ P<IND)
    if not fields["id_type"]:
        mrz_match = re.search(r"P<IND([A-Z<]+)", raw_text)
        passport_num_match = re.search(r"\b[A-Z][1-9]\d{6}\b", raw_text)
        if mrz_match or ("passport" in raw_lower):
            fields["id_type"] = "Passport"
            if passport_num_match:
                fields["id_number"]       = passport_num_match.group()
                fields["id_valid"]        = True
                fields["validation_note"] = "Valid Indian Passport format"
            else:
                fields["validation_note"] = "Passport detected"

    # 5. Voter ID (EPIC): 3 letters + 7 digits (e.g. ABC1234567)
    if not fields["id_type"]:
        epic_pattern = r"\b[A-Z]{3}\d{7}\b"
        epic_match   = re.search(epic_pattern, raw_text)
        if epic_match:
            fields["id_number"]       = epic_match.group()
            fields["id_type"]         = "Voter ID"
            fields["id_valid"]        = True
            fields["validation_note"] = "Valid Voter ID (EPIC) format"
        elif "election commission" in raw_lower or "electoral" in raw_lower:
            fields["id_type"]         = "Voter ID"
            fields["validation_note"] = "Voter ID keywords detected"

    # 6. Institutional / College ID fallback (e.g. Reg No / Roll No / PRN)
    if not fields["id_type"]:
        reg_match = re.search(
            r"(?:Reg\.?[ \t]*No\.?|PRN|Roll[ \t]*No\.?|Student[ \t]*ID)[:.\t ]*([A-Z0-9\-]{5,15})",
            raw_text,
            re.IGNORECASE,
        )
        inst_keywords = (
            "institute", "university", "college", "bachelor",
            "vishwakarma", "technology", "autonomous",
        )
        if reg_match or any(k in raw_lower for k in inst_keywords):
            fields["id_type"] = "Institutional ID"
            id_val = reg_match.group(1).strip() if reg_match else None
            if not id_val:
                standalone_num = re.search(r"^\s*(\d{6,10})\s*$", raw_text, re.MULTILINE)
                if standalone_num:
                    id_val = standalone_num.group(1).strip()
            if id_val:
                fields["id_number"]       = id_val
                fields["id_valid"]        = True
                fields["validation_note"] = "Institutional Registration ID detected"

    # --- Extract Date of Birth ---
    # Matches formats: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    dob_pattern = r"\b(\d{2})[/\-\.](\d{2})[/\-\.](\d{4})\b"
    dob_match   = re.search(dob_pattern, raw_text)
    if dob_match:
        fields["dob"] = dob_match.group()

    # --- Extract Name ---
    fields["name"] = _extract_best_name(raw_text, lines)

    return fields


def _extract_best_name(raw_text: str, lines: list[str]) -> Optional[str]:
    """
    Extract an applicant's printed name cleanly without picking bilingual
    Devanagari-transliterated noise or institution header lines.
    """
    # 1. Explicit inline label match (e.g. "Name: Aarav Sharma" / "Student Name: ...")
    # Exclude "Father's Name" / "Mother's Name" and reject placeholder label words.
    label_match = re.search(
        r"(?<!Father's )(?<!Father )(?<!Mother's )(?<!Mother )(?:Student[ \t]+)?\bName\b[: \t]+([A-Za-z][A-Za-z .]{2,45})",
        raw_text,
        re.IGNORECASE,
    )
    if label_match:
        candidate = re.sub(r"\s+", " ", label_match.group(1)).strip(" .,-:")
        if len(candidate) >= 3 and candidate.lower() not in ("card", "father", "mother"):
            return candidate

    # If a bilingual card puts "Name" at the end of a line and the actual name on the next line
    # (e.g. "a1a/ Name\nPURVA PANKAJ RATHI"), track that line anchor.
    name_label_idx = next(
        (
            i for i, ln in enumerate(lines)
            if re.search(r"\bName\b\s*:?\s*$", ln, re.I)
            and not re.search(r"(?:father|mother|husband)", ln, re.I)
        ),
        None,
    )

    skip_words = {
        "government", "india", "republic", "department", "card", "identity",
        "income", "tax", "permanent", "account", "election", "commission",
        "driving", "licence", "license", "transport", "passport", "authority",
        "unique", "identification", "institute", "technology", "trust",
        "charitable", "vishwakarma", "bachelor", "bachelors", "college",
        "university", "bansilal", "ramnath", "agarwal", "pune", "website",
        "male", "female", "transgender", "address", "signature", "student",
        "proof", "citizenship", "maharashtra", "bibwewadi", "indiranagar",
        "upper", "engineering", "computer", "science", "department", "course",
        "degree", "valid", "upto", "issue", "father", "mother", "husband",
        "birth", "year", "enrollment", "admission", "prn", "autonomous",
        "diploma", "master", "masters", "library",
    }

    dob_idx = next(
        (i for i, ln in enumerate(lines) if re.search(r"\b\d{2}[/\-\.]\d{2}[/\-\.]\d{4}\b", ln)),
        None,
    )
    reg_idx = next(
        (i for i, ln in enumerate(lines) if re.search(r"(?:Reg\.?\s*No|PRN|Roll\s*No|Student\s*ID)", ln, re.I)),
        None,
    )
    degree_idx = next(
        (i for i, ln in enumerate(lines) if re.search(r"(?:Bachelor|Master|B\.?Tech|M\.?Tech|Diploma)", ln, re.I)),
        None,
    )
    # Use the LAST top ministry header anchor so bilingual "GOVT. OF INDIA" skips Hindi lines above it
    govt_matches = [
        i for i, ln in enumerate(lines)
        if re.search(r"(?:INCOME\s*TAX|GOVT\.?\s*OF\s*INDIA|GOVERNMENT\s*OF\s*INDIA|ELECTION\s*COMMISSION)", ln, re.I)
    ]
    govt_idx = govt_matches[-1] if govt_matches else None

    best_score = 0
    best_name: Optional[str] = None

    for idx, raw_line in enumerate(lines):
        # Government cards (PAN/Aadhaar/Voter ID) never print holder names above the top ministry header
        if govt_idx is not None and idx < govt_idx:
            continue

        cleaned = re.sub(r"\s+", " ", raw_line).strip(" .,-:|")
        if not re.match(r"^[A-Za-z][A-Za-z\s.]{3,48}$", cleaned):
            continue

        words = [w.strip(".") for w in cleaned.split() if w.strip(".")]
        # Printed Indian names are almost always 2 to 4 words
        if not (2 <= len(words) <= 4):
            continue

        # Reject institutional/header keywords
        if any(w.lower() in skip_words for w in words):
            continue

        # Reject random lowercase OCR noise ("a", "ne", "tok", "carat", "wat", etc.)
        # Every valid name token must start uppercase (Title Case or ALL CAPS)
        # and avoid multi-lowercase noise tokens.
        if any(not w[0].isupper() for w in words):
            continue
        if any(len(w) == 1 and idx == 0 for w in words):
            continue

        score = 20 if len(words) in (2, 3) else 10
        # Direct next-line "Name\n<FULL NAME>" anchor on PAN / Govt cards
        if name_label_idx is not None and 0 < (idx - name_label_idx) <= 2:
            score += 85
        # Institutional ID: directly after Reg No / Roll No or directly above Bachelor/B.Tech
        if reg_idx is not None and 0 < (idx - reg_idx) <= 3:
            score += 60
        if degree_idx is not None and 0 < (degree_idx - idx) <= 2:
            score += 55
        # PAN / Govt cards: first clean ALL-CAPS name after GOVT OF INDIA / INCOME TAX beats father's name lower down
        if govt_idx is not None and 0 < (idx - govt_idx) <= 6:
            score += max(20, 48 - (idx - govt_idx) * 4)
        # Aadhaar / PAN / DL: 1-3 lines above DOB line
        if dob_idx is not None and 0 < (dob_idx - idx) <= 3:
            score += 50
        # Slight bonus for pure Title/Upper words with len >= 2
        if all(len(w) >= 2 for w in words):
            score += 10
        if all(w.isupper() for w in words):
            score += 5

        if score > best_score:
            best_score = score
            best_name = " ".join(words)

    return best_name


# ---------------------------------------------------------------
# FUNCTION: is_pdf
# Checks if the uploaded file is a PDF by looking at its first bytes.
# PDF files always start with "%PDF" — this is called a "magic number".
# Checking file content is more reliable than trusting the filename.
# ---------------------------------------------------------------
def is_pdf(file_bytes: bytes) -> bool:
    return file_bytes[:4] == b"%PDF"


# ---------------------------------------------------------------
# FUNCTION: pdf_to_image_bytes
# Converts the first page of a PDF into JPEG image bytes.
# Uses PyMuPDF (imported as fitz) to render the page as an image.
# ---------------------------------------------------------------
def pdf_to_image_bytes(pdf_bytes: bytes) -> bytes:
    # Open the PDF from memory (no need to save to disk first)
    pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")

    # Get the first page
    page = pdf_document[0]

    # Render page to an image at 2x resolution for better OCR accuracy
    # matrix=fitz.Matrix(2, 2) scales the render 2x in both directions
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))

    # Convert to PNG bytes, then we'll decode with OpenCV like any image
    image_bytes = pix.tobytes("png")

    pdf_document.close()
    return image_bytes


# ---------------------------------------------------------------
# FUNCTION: scan_document
# Main function called by main.py.
# Takes raw image bytes, preprocesses, runs OCR, parses fields.
# Returns a structured result dictionary.
# ---------------------------------------------------------------
def scan_document(image_bytes: bytes) -> dict:
    # Step 0: Check if this is a PDF and convert to image first
    if is_pdf(image_bytes):
        try:
            image_bytes = pdf_to_image_bytes(image_bytes)
        except Exception as e:
            return {
                "success": False,
                "error":   f"Could not read PDF: {str(e)}",
                "fields":  {}
            }

    # Step 1: Convert bytes → numpy array → OpenCV image
    np_arr = np.frombuffer(image_bytes, np.uint8)
    image  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if image is None:
        return {
            "success": False,
            "error":   "Could not decode image",
            "fields":  {}
        }

    # Step 2: Optional debug frame save (disabled by default to keep plaintext IDs off disk)
    if os.getenv("DEBUG_SAVE_CROPS", "false").strip().lower() == "true":
        try:
            uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            cv2.imwrite(os.path.join(uploads_dir, "id_frame.jpg"), image)
        except Exception:
            pass  # Don't crash if save fails

    # Step 3 & 4: Run multi-pass OCR (clean upscaled grayscale --psm 3 first,
    # adaptive-threshold --psm 6 fallback if needed for uneven camera lighting)
    def _passes_quality(txt: str) -> bool:
        if not txt or len(txt) < 15:
            return False
        clean_chars = [c for c in txt if c.isalnum() or c.isspace()]
        return (len(clean_chars) / max(len(txt), 1)) >= 0.75

    gray_up = _upscale_grayscale(image)
    raw_primary = extract_text(gray_up, psm=3)
    fields_primary = parse_id_fields(raw_primary) if _passes_quality(raw_primary) else None

    needs_fallback = (
        fields_primary is None
        or not fields_primary.get("id_type")
        or not fields_primary.get("name")
        or not fields_primary.get("id_number")
    )

    raw_text = raw_primary
    fields = fields_primary
    if needs_fallback:
        cleaned = preprocess_image(image)
        raw_fallback = extract_text(cleaned, psm=6)
        if _passes_quality(raw_fallback):
            fields_fallback = parse_id_fields(raw_fallback)
            if fields is None:
                raw_text = raw_fallback
                fields = fields_fallback
            else:
                # Merge any missing fields recovered cleanly by fallback pass
                for key in ("id_type", "id_number", "id_valid", "validation_note", "dob", "name"):
                    if fields.get(key) is None and fields_fallback.get(key) is not None:
                        fields[key] = fields_fallback[key]

    # Step 5: Quality gate — reject unreadable/blurry frames cleanly
    if fields is None:
        clean_ratio = (
            len([c for c in raw_text if c.isalnum() or c.isspace()]) / max(len(raw_text), 1)
            if raw_text else 0.0
        )
        err_msg = (
            "Could not read ID clearly — text is too short or blurry. Please upload a clear photo."
            if not raw_text or len(raw_text) < 15 or clean_ratio >= 0.75
            else "Could not read ID clearly — image may be blurry, reflective, or poorly lit. Please upload a clear photo."
        )
        return {
            "success":        False,
            "error":          err_msg,
            "fields":         {},
            "debug_raw_text": raw_text or "",
        }

    return {
        "success": True,
        "fields":  fields,
        "message": "ID scanned successfully",
    }


def redact_aadhaar_digits(image_bytes: bytes, last4_hint: Optional[str] = None) -> tuple[bytes, bool]:
    """
    Visually mask the first 8 digits of an Aadhaar number for UIDAI-aligned
    compliance previews, leaving only the last 4 digits readable.
    Returns (encoded_bytes, was_redacted).
    """
    work_bytes = image_bytes
    if is_pdf(work_bytes):
        try:
            work_bytes = pdf_to_image_bytes(work_bytes)
        except Exception:
            return image_bytes, False

    np_arr = np.frombuffer(work_bytes, np.uint8)
    image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if image is None:
        return image_bytes, False

    h_orig, w_orig = image.shape[:2]
    scale = 2.0 if max(h_orig, w_orig) < 1600 else 1.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if scale != 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    try:
        data = pytesseract.image_to_data(
            gray,
            config="--oem 3 --psm 6",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return image_bytes, False

    tokens = []
    count = len(data.get("text", []))
    for i in range(count):
        raw_tok = (data["text"][i] or "").strip()
        digits = re.sub(r"\D", "", raw_tok)
        if not digits:
            continue
        x = int(data["left"][i] / scale)
        y = int(data["top"][i] / scale)
        w = max(1, int(data["width"][i] / scale))
        h = max(1, int(data["height"][i] / scale))
        tokens.append((digits, x, y, w, h))

    boxes_to_mask = []
    hint = re.sub(r"\D", "", last4_hint or "")[-4:]

    # Pattern A: 3 consecutive 4-digit Aadhaar groups (e.g. 1234 5678 9012)
    four_tokens = [(idx, tok) for idx, tok in enumerate(tokens) if len(tok[0]) == 4]
    for pos in range(len(four_tokens) - 2):
        i1, t1 = four_tokens[pos]
        i2, t2 = four_tokens[pos + 1]
        i3, t3 = four_tokens[pos + 2]
        if (i2 - i1) <= 2 and (i3 - i2) <= 2:
            same_line = (
                abs(t1[2] - t2[2]) <= max(t1[4], t2[4]) * 1.5
                and abs(t2[2] - t3[2]) <= max(t2[4], t3[4]) * 1.5
            )
            ordered_lr = t1[1] <= t2[1] <= t3[1]
            if same_line and ordered_lr:
                if hint and t3[0] != hint:
                    continue
                boxes_to_mask.extend([(t1[1], t1[2], t1[3], t1[4]), (t2[1], t2[2], t2[3], t2[4])])

    # Pattern B: Single unbroken 12-digit token (mask leftmost 68% = first 8 digits)
    if not boxes_to_mask:
        for digits, x, y, w, h in tokens:
            if len(digits) == 12:
                if hint and not digits.endswith(hint):
                    continue
                boxes_to_mask.append((x, y, max(1, int(w * 0.68)), h))

    if not boxes_to_mask:
        return image_bytes, False

    redacted_img = image.copy()
    pad = 3
    for x, y, w, h in boxes_to_mask:
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(w_orig, x + w + pad)
        y2 = min(h_orig, y + h + pad)
        cv2.rectangle(redacted_img, (x1, y1), (x2, y2), (15, 23, 42), thickness=-1)

    ok, encoded = cv2.imencode(".jpg", redacted_img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        return image_bytes, False
    return encoded.tobytes(), True
