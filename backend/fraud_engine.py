# fraud_engine.py
# Unified Fraud Risk Engine for PehchaanAI (FF180 Objective 2).
#
# PURPOSE:
# Combines multiple independent verification and behavioral signals into
# a single 0-100 Unified Fraud Risk Score:
#   - 0.0   = lowest risk (all checks strong, clean history)
#   - 100.0 = maximum risk (multiple fraud indicators / attack detected)
#
# RISK COMPONENTS (100 points max):
#   1. Face Match Risk         (max 30 pts) — embedding distance / confidence
#   2. Spoof & Liveness Risk   (max 35 pts) — presentation attacks & blinks
#   3. Document Risk           (max 10 pts) — OCR completeness & checksum validation
#   4. History / Velocity Risk (max 25 pts) — ID reuse & IP failure velocity

import re
from difflib import SequenceMatcher
from database import get_fraud_history_signals


def _names_conflict(declared_name: str, ocr_name: str) -> bool:
    """
    Return True only when declared applicant name and OCR-extracted name
    clearly refer to different people (zero close words AND low overall similarity).
    """
    clean_decl = re.sub(r"[^a-z0-9 ]", " ", (declared_name or "").lower()).strip()
    clean_ocr  = re.sub(r"[^a-z0-9 ]", " ", (ocr_name or "").lower()).strip()
    if len(clean_decl) < 3 or len(clean_ocr) < 3:
        return False

    decl_words = [w for w in clean_decl.split() if len(w) >= 3]
    ocr_words  = [w for w in clean_ocr.split() if len(w) >= 3]
    if set(decl_words) & set(ocr_words):
        return False

    # Allow single-character OCR typos on any shared name token (e.g. Purva vs Purwa)
    for dw in decl_words:
        for ow in ocr_words:
            if SequenceMatcher(None, dw, ow).ratio() >= 0.78:
                return False

    return SequenceMatcher(None, clean_decl, clean_ocr).ratio() < 0.65


# ---------------------------------------------------------------
# FUNCTION: compute_fraud_risk
# Calculates the unified 0-100 fraud risk score and a structured
# breakdown of contributing risk factors for explainability.
#
# Parameters:
#   session_data    → dict from Redis session
#   history_signals → optional dict (used for testing without DB)
# ---------------------------------------------------------------
def compute_fraud_risk(session_data: dict, history_signals: dict = None) -> dict:
    risk_factors = []

    face_found       = bool(session_data.get("face_found", False))
    liveness_passed  = bool(session_data.get("liveness_passed", False))
    spoof_detected   = bool(session_data.get("spoof_detected", False))
    spoof_score      = session_data.get("spoof_score")
    id_scanned       = bool(session_data.get("id_scanned", False))
    face_matched     = bool(session_data.get("face_matched", False))
    match_confidence = float(session_data.get("match_confidence") or 0.0)
    id_fields        = session_data.get("id_fields") or {}
    session_id       = session_data.get("session_id", "")
    ip_address       = session_data.get("ip_address")

    # -----------------------------------------------------------
    # 1. Face Match Risk (0 – 30 pts)
    # High confidence reduces risk; failed/missing match maxes it out.
    # -----------------------------------------------------------
    match_distance = session_data.get("match_distance")
    is_plausible_match = face_matched or (match_distance is not None and float(match_distance) <= 0.66)

    if not face_found or (not is_plausible_match and match_confidence < 45.0):
        face_risk = 30.0
        risk_factors.append("Face match failed or no face detected (+30.0 risk)")
    else:
        clamped_conf = max(0.0, min(100.0, match_confidence))
        # Soft scaling: high confidence (>= 80%) has minimal risk (< 3.5 pts)
        face_risk = round(25.0 * ((100.0 - clamped_conf) / 100.0) ** 1.3, 1)
        if clamped_conf < 70.0:
            risk_factors.append(
                f"Moderate face-match confidence ({clamped_conf:.1f}%) (+{face_risk:.1f} risk)"
            )

    # -----------------------------------------------------------
    # 2. Spoof & Liveness Risk (0 – 35 pts)
    # Presentation attack (screen replay / photo) triggers full penalty.
    # Proximity to the live spoof threshold also contributes minor uncertainty.
    # -----------------------------------------------------------
    spoof_liveness_risk = 0.0
    if spoof_detected:
        spoof_liveness_risk = 35.0
        risk_factors.append("Presentation attack / spoofing detected (+35.0 risk)")
    else:
        if not liveness_passed:
            spoof_liveness_risk += 25.0
            risk_factors.append("Blink liveness check not passed (+25.0 risk)")

        # Add minor uncertainty risk only if spoof score is right at the boundary (below 0.58)
        if spoof_score is not None and spoof_score < 0.58:
            proximity_risk = min(8.0, max(0.0, ((0.58 - spoof_score) / 0.08) * 8.0))
            if proximity_risk >= 2.0:
                spoof_liveness_risk += proximity_risk
                risk_factors.append(
                    f"Anti-spoofing margin close to threshold (avg score {spoof_score:.3f}) (+{proximity_risk:.1f} risk)"
                )

    spoof_liveness_risk = min(35.0, spoof_liveness_risk)

    # -----------------------------------------------------------
    # 3. Document Integrity Risk (0 – 10 pts)
    # Checks whether key identity fields were parsed AND whether
    # mathematical/format validation (e.g. Aadhaar Verhoeff checksum) passed.
    # -----------------------------------------------------------
    document_risk = 0.0
    if not id_scanned:
        document_risk = 10.0
        risk_factors.append("ID document was not scanned (+10.0 risk)")
    else:
        missing_fields = []
        if not id_fields.get("id_number"):
            document_risk += 4.0
            missing_fields.append("id_number")
        if not id_fields.get("id_type"):
            document_risk += 3.0
            missing_fields.append("id_type")
        if not id_fields.get("name"):
            document_risk += 2.0
            missing_fields.append("name")
        if not id_fields.get("dob"):
            document_risk += 1.0
            missing_fields.append("dob")

        if missing_fields:
            risk_factors.append(
                f"Incomplete OCR extraction (missing {', '.join(missing_fields)}) (+{document_risk:.1f} risk)"
            )

        # Check cryptographic/format validation result from ocr.py
        if id_fields.get("id_valid") is False:
            document_risk += 8.0
            note = id_fields.get("validation_note") or "Document checksum/format failed"
            risk_factors.append(f"{note} (+8.0 risk)")

        # Cross-check declared applicant name (Step 1) against OCR name (Step 3)
        declared_name = (session_data.get("applicant_name") or "").strip()
        ocr_name = (id_fields.get("name") or "").strip()
        if _names_conflict(declared_name, ocr_name):
            document_risk += 4.0
            risk_factors.append(
                f"Declared name ('{declared_name}') differs from OCR ID name ('{ocr_name}') (+4.0 risk)"
            )

    document_risk = min(10.0, document_risk)

    # -----------------------------------------------------------
    # 4. Identity & Velocity History Risk (0 – 25 pts)
    # Queries PostgreSQL to detect reused ID numbers or rapid
    # failed attempts from the same IP address.
    # -----------------------------------------------------------
    if history_signals is None:
        history_signals = get_fraud_history_signals(
            session_id=session_id,
            id_number=id_fields.get("id_number"),
            ip_address=ip_address,
        )

    history_risk = 0.0
    if history_signals.get("id_prior_failed"):
        history_risk += 15.0
        risk_factors.append("ID number previously linked to a failed/spoofed session (+15.0 risk)")
    elif history_signals.get("id_reuse_count", 0) >= 2:
        history_risk += 8.0
        risk_factors.append(
            f"ID number reused across {history_signals['id_reuse_count']} prior sessions (+8.0 risk)"
        )

    is_local_ip = ip_address in ("127.0.0.1", "::1", "localhost", "testclient") or (
        bool(ip_address) and (ip_address.startswith("192.168.") or ip_address.startswith("10.") or ip_address == "None")
    )
    ip_failures = history_signals.get("ip_recent_failures", 0)
    if not is_local_ip and ip_failures >= 2:
        ip_penalty = min(15.0, (ip_failures - 1) * 5.0)
        history_risk += ip_penalty
        risk_factors.append(
            f"{ip_failures} recent failed/spoofed session(s) from same IP (+{ip_penalty:.1f} risk)"
        )

    history_risk = min(25.0, history_risk)

    # -----------------------------------------------------------
    # Combine & Classify
    # -----------------------------------------------------------
    total_score = round(min(100.0, face_risk + spoof_liveness_risk + document_risk + history_risk), 1)

    if total_score <= 20.0:
        risk_level = "LOW"
    elif total_score <= 50.0:
        risk_level = "MEDIUM"
    else:
        risk_level = "HIGH"

    if not risk_factors:
        risk_factors.append("No anomalous fraud indicators detected")

    return {
        "fraud_score": total_score,
        "risk_level":  risk_level,
        "breakdown": {
            "face_risk":           round(face_risk, 1),
            "spoof_liveness_risk": round(spoof_liveness_risk, 1),
            "document_risk":       round(document_risk, 1),
            "history_risk":        round(history_risk, 1),
        },
        "risk_factors": risk_factors,
    }
