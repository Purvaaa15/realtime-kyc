"""
Quick CLI smoke test for document OCR extraction.

Usage (from project root):
    venv\\Scripts\\python.exe backend\\test_ocr.py path\\to\\id_image_or_pdf
"""

import glob
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from ocr import scan_document


def main() -> int:
    if len(sys.argv) > 1:
        sample_path = sys.argv[1]
    else:
        candidates = sorted(glob.glob(os.path.join(BACKEND_DIR, "..", "uploads", "id_*.jpg")))
        if not candidates:
            print("Usage: python backend/test_ocr.py <path-to-id-image-or-pdf>")
            return 1
        sample_path = candidates[0]

    with open(sample_path, "rb") as f:
        result = scan_document(f.read())

    print(f"Scanned: {sample_path}")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
