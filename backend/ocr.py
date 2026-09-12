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
# 4. Parse the raw text to find name, ID number, date of birth etc.

import cv2
import numpy as np
import pytesseract
import re
import os
import fitz  # PyMuPDF — used to convert PDF pages to images

# ---------------------------------------------------------------
# Tell pytesseract where the Tesseract program is installed.
# This is the path from when you installed it in Step 1E.
# If you installed it somewhere else, update this path.
# ---------------------------------------------------------------
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


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
def preprocess_image(image: np.ndarray) -> np.ndarray:
    # Step 1: Convert BGR (OpenCV default) to greyscale
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Step 2: Resize to 2x size — bigger image = more detail for OCR
    # fx=2, fy=2 means scale by factor 2 in both directions
    resized = cv2.resize(grey, None, fx=2, fy=2,
                         interpolation=cv2.INTER_CUBIC)

    # Step 3: Gaussian blur to reduce noise
    # (5, 5) is the kernel size — must be odd numbers
    # The blur smooths out grain without blurring text edges much
    blurred = cv2.GaussianBlur(resized, (5, 5), 0)

    # Step 4: Adaptive thresholding
    # This converts the image to pure black and white.
    # "Adaptive" means it adjusts the threshold locally for each
    # region of the image — handles uneven lighting much better
    # than a single global threshold.
    thresh = cv2.adaptiveThreshold(
        blurred,
        255,                              # max pixel value (white)
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,   # use gaussian weighted sum
        cv2.THRESH_BINARY,                # output: black or white
        11,                               # block size (neighbourhood)
        2                                 # constant subtracted from mean
    )

    return thresh


# ---------------------------------------------------------------
# FUNCTION: extract_text
# Runs Tesseract OCR on a preprocessed image and returns raw text.
#
# Tesseract config options:
# --oem 3  = use best available OCR engine (LSTM neural network)
# --psm 6  = assume image is a single uniform block of text
#            (good for ID cards which have structured text blocks)
# ---------------------------------------------------------------
def extract_text(image: np.ndarray) -> str:
    config = "--oem 3 --psm 6"
    text = pytesseract.image_to_string(image, config=config)
    return text.strip()


# ---------------------------------------------------------------
# FUNCTION: parse_id_fields
# Takes the raw OCR text and tries to find specific fields.
#
# ID cards have different formats, so we use flexible pattern
# matching (regex) to find common fields like:
#   - Name
#   - Date of birth
#   - ID / Aadhaar / PAN number
#
# regex (regular expressions) are patterns for matching text.
# Example: r"\d{4}\s\d{4}\s\d{4}" matches "1234 5678 9012"
# ---------------------------------------------------------------
def parse_id_fields(raw_text: str) -> dict:
    fields = {
        "raw_text": raw_text,
        "name":     None,
        "dob":      None,
        "id_number": None,
        "id_type":  None,
    }

    # Split into lines for easier processing
    lines = [line.strip() for line in raw_text.split("\n")
             if line.strip()]

    # --- Detect ID type and extract ID number ---

    # Aadhaar: 12 digits in groups of 4 (e.g. 1234 5678 9012)
    aadhaar_pattern = r"\b\d{4}\s?\d{4}\s?\d{4}\b"
    aadhaar_match   = re.search(aadhaar_pattern, raw_text)
    if aadhaar_match:
        fields["id_number"] = aadhaar_match.group().replace(" ", "")
        fields["id_type"]   = "Aadhaar"

    # PAN: 5 letters + 4 digits + 1 letter (e.g. ABCDE1234F)
    pan_pattern = r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b"
    pan_match   = re.search(pan_pattern, raw_text)
    if pan_match:
        fields["id_number"] = pan_match.group()
        fields["id_type"]   = "PAN"

    # --- Extract Date of Birth ---
    # Matches formats: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    dob_pattern = r"\b(\d{2})[/\-\.](\d{2})[/\-\.](\d{4})\b"
    dob_match   = re.search(dob_pattern, raw_text)
    if dob_match:
        fields["dob"] = dob_match.group()

    # --- Extract Name ---
    # On Indian ID cards, name usually appears after "Name:" label
    # or on a line by itself in all caps or title case
    name_pattern = r"(?:Name[:\s]+)([A-Za-z\s]+)"
    name_match   = re.search(name_pattern, raw_text, re.IGNORECASE)
    if name_match:
        fields["name"] = name_match.group(1).strip()
    else:
        # Fallback: look for a line with only letters and spaces
        # that is at least 5 characters (likely a name)
        for line in lines:
            if re.match(r"^[A-Za-z\s]{5,}$", line):
                # Skip common non-name words
                skip_words = ["government", "india", "republic",
                              "department", "card", "identity"]
                if not any(w in line.lower() for w in skip_words):
                    fields["name"] = line
                    break

    return fields

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

    # Step 2: Save the raw ID frame for debugging
    # You can check uploads/id_frame.jpg to see what was captured
    try:
        from main import UPLOADS_DIR
        cv2.imwrite(os.path.join(UPLOADS_DIR, "id_frame.jpg"), image)
    except Exception:
        pass  # Don't crash if save fails

    # Step 3: Preprocess the image
    cleaned = preprocess_image(image)

    # Step 4: Run OCR
    raw_text = extract_text(cleaned)

    # Step 5: If no text found at all
    if not raw_text:
        return {
            "success": False,
            "error":   "No text detected — try better lighting",
            "fields":  {}
        }

    # Step 6: Parse the text into structured fields
    fields = parse_id_fields(raw_text)

    return {
        "success": True,
        "fields":  fields,
        "message": "ID scanned successfully"
    }