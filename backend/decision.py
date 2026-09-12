# decision.py
# This module combines all verification results into a final verdict.
#
# Think of this as the "judge" — it looks at everything that happened
# during the session and decides: PASS, FAIL, or NEEDS REVIEW.
#
# Each check contributes to the final decision:
#   ✓ Face detected     → user was present
#   ✓ Liveness passed   → user is a real live person, not a photo
#   ✓ ID scanned        → identity document was presented
#   ✓ Face matched      → live face matches the ID card photo


# ---------------------------------------------------------------
# FUNCTION: make_decision
# Takes results from all verification steps and returns
# a final structured verdict.
#
# Parameters:
#   face_found      → bool: was a face detected?
#   liveness_passed → bool: did blink detection pass?
#   id_scanned      → bool: was ID card scanned successfully?
#   face_matched    → bool: did selfie match ID photo?
#   match_confidence→ float: how confident is the face match (0-100)
#   id_fields       → dict: extracted fields from ID card
# ---------------------------------------------------------------
def make_decision(
    face_found:       bool,
    liveness_passed:  bool,
    id_scanned:       bool,
    face_matched:     bool,
    match_confidence: float,
    id_fields:        dict,
    spoof_detected:   bool = False,   # NEW parameter
) -> dict:

    checks = {
        "face_detected":   face_found,
        "liveness_passed": liveness_passed,
        "no_spoof":        not spoof_detected,   # NEW check
        "id_scanned":      id_scanned,
        "face_matched":    face_matched,
    }

    passed_count = sum(1 for v in checks.values() if v)
    total_checks = len(checks)

    # Spoof detected → immediate FAIL, highest priority check
    if spoof_detected:
        verdict = "FAIL"
        message = "❌ Spoof detected — printed photo or screen replay suspected"
        color   = "red"

    elif all(checks.values()):
        verdict = "PASS"
        message = "✅ KYC Verification Passed — Identity confirmed"
        color   = "green"

    elif (face_found and liveness_passed and id_scanned
          and face_matched and match_confidence < 75):
        verdict = "REVIEW"
        message = "⚠️ Low confidence match — flagged for manual review"
        color   = "yellow"

    elif face_found and not liveness_passed:
        verdict = "FAIL"
        message = "❌ Liveness check failed — please try again"
        color   = "red"

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
        "id_fields":        id_fields,
    }