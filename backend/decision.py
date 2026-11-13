# decision.py
# This module combines all verification results into a final verdict.
#
# Think of this as the "judge" — it looks at everything that happened
# during the session and decides: PASS, FAIL, or NEEDS REVIEW.
#
# Each check contributes to the final decision:
#   ✓ Face detected     → user was present
#   ✓ Liveness passed   → user is a real live person, not a photo
#   ✓ No spoof          → user is not holding a phone or printed photo
#   ✓ ID scanned        → identity document was presented & parsed
#   ✓ Face matched      → live face matches the ID card photo
#   ✓ Fraud risk check  → unified risk score (0-100) within safe threshold

# ---------------------------------------------------------------
# FUNCTION: make_decision
# Takes results from all verification steps and returns
# a final structured verdict with explainable reasons.
#
# Parameters:
#   face_found      → bool: was a face detected?
#   liveness_passed → bool: did blink detection pass?
#   id_scanned      → bool: was ID card scanned successfully?
#   face_matched    → bool: did selfie match ID photo?
#   match_confidence→ float: how confident is the face match (0-100)
#   id_fields       → dict: extracted fields from ID card
#   spoof_detected  → bool: was spoofing/presentation attack detected?
#   fraud_result    → dict (optional): output from fraud_engine.compute_fraud_risk()
# ---------------------------------------------------------------
def make_decision(
    face_found:       bool,
    liveness_passed:  bool,
    id_scanned:       bool,
    face_matched:     bool,
    match_confidence: float,
    id_fields:        dict,
    spoof_detected:   bool = False,
    fraud_result:     dict = None,
    match_distance:   float = None,
) -> dict:

    checks = {
        "face_detected":   face_found,
        "liveness_passed": liveness_passed,
        "no_spoof":        not spoof_detected,
        "id_scanned":      id_scanned,
        "face_matched":    face_matched,
    }

    passed_count = sum(1 for v in checks.values() if v)
    total_checks = len(checks)

    fraud_score = float(fraud_result.get("fraud_score", 0.0)) if fraud_result else 0.0
    risk_level  = fraud_result.get("risk_level", "LOW") if fraud_result else "LOW"

    # ---------------------------------------------------------------
    # Explainable Reasons Builder:
    # Generates plain-English explanations for each verification check
    # so human reviewers and audit trails know EXACTLY why a verdict
    # was reached (aligned with XAI / explainability goals).
    # ---------------------------------------------------------------
    reasons = []

    if face_found:
        reasons.append("Face detected in live video stream")
    else:
        reasons.append("No face detected in live video stream")

    if liveness_passed:
        reasons.append("Liveness confirmed via natural blink detection")
    elif face_found:
        reasons.append("Liveness check failed — insufficient natural blinks observed")

    if not spoof_detected:
        reasons.append("Anti-spoofing checks passed (texture, frequency, and screen bezel analysis)")
    else:
        reasons.append("Spoof detected — screen replay or printed photo suspected")

    if id_scanned:
        id_type = (id_fields or {}).get("id_type") or "Document"
        reasons.append(f"{id_type} scanned and text extracted")
    else:
        reasons.append("ID document not scanned or text could not be extracted")

    if face_matched:
        if match_confidence >= 75.0:
            reasons.append(f"Face matched against ID photo with high confidence ({match_confidence:.1f}%)")
        else:
            reasons.append(f"Face matched with moderate confidence ({match_confidence:.1f}%)")
    elif face_found and id_scanned:
        reasons.append("Face does not match photo on ID document (distance exceeded threshold)")

    if fraud_result is not None:
        reasons.append(f"Unified Fraud Risk Score: {fraud_score:.1f}/100 ({risk_level})")
        for factor in fraud_result.get("risk_factors", []):
            if factor != "No anomalous fraud indicators detected":
                reasons.append(f"Risk signal: {factor}")

    # ---------------------------------------------------------------
    # Verdict Determination:
    # ---------------------------------------------------------------

    # Spoof detected → immediate FAIL, highest priority security check
    if spoof_detected:
        verdict = "FAIL"
        message = "❌ Spoof detected — printed photo or screen replay suspected"
        color   = "red"

    # High Fraud Risk Score (>= 55) → route to REVIEW even if CV checks passed
    # (catches ID reuse across failed sessions or high velocity attacks)
    elif (face_found and liveness_passed and id_scanned
          and face_matched and fraud_score >= 55.0):
        verdict = "REVIEW"
        message = f"⚠️ Elevated fraud risk ({fraud_score:.1f}/100 — {risk_level}) — flagged for manual review"
        color   = "yellow"

    # IMPORTANT: check REVIEW *before* the blanket "all checks passed" check.
    # face_matched is a boolean (distance < 0.60) that says NOTHING about
    # how confident that match actually is — a match at 52% confidence
    # and a match at 95% confidence both report face_matched=True.
    # We gate a full PASS behind a real confidence bar (>= 75%),
    # routing borderline matches (50% - 74.9%) for human review.
    elif (face_found and liveness_passed and id_scanned
          and face_matched and match_confidence < 75.0):
        verdict = "REVIEW"
        message = f"⚠️ Moderate match confidence ({match_confidence:.1f}%) — flagged for manual review"
        color   = "yellow"

    elif all(checks.values()) and match_confidence >= 75.0:
        verdict = "PASS"
        message = "✅ KYC Verification Passed — Identity confirmed"
        color   = "green"

    elif face_found and not liveness_passed:
        verdict = "FAIL"
        message = "❌ Liveness check failed — please try again"
        color   = "red"

    elif (face_found and liveness_passed and id_scanned
          and not face_matched and match_distance is not None
          and match_distance <= 0.66):
        verdict = "REVIEW"
        message = (
            f"⚠️ Facial age/lighting variance detected (distance {match_distance:.3f}) — "
            "flagged for human compliance verification"
        )
        color   = "yellow"
        reasons.append(
            f"Borderline age/lighting distance ({match_distance:.4f} <= 0.6600): routed for side-by-side human review instead of auto-rejection"
        )

    elif face_found and liveness_passed and id_scanned and not face_matched:
        verdict = "FAIL"
        message = "❌ Face does not match ID card — verification failed"
        color   = "red"

    else:
        verdict = "INCOMPLETE"
        message = f"⚠️ Verification incomplete — {passed_count}/{total_checks} steps done"
        color   = "yellow"

    return {
        "verdict":          verdict,
        "message":          message,
        "color":            color,
        "checks":           checks,
        "passed_count":     passed_count,
        "total_checks":     total_checks,
        "match_confidence": match_confidence,
        "fraud_score":      fraud_score,
        "risk_level":       risk_level,
        "id_fields":        id_fields,
        "verdict_reasons":  reasons,
    }
